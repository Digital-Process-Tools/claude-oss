"""#1181: written directly into its own module, per the per-check module
convention (#497, #630) that a new check does not go into `doctor.py` at all
-- see the convention block at the top of doctor.py for the rule and
scripts/doctor_modules.py for the ratchet that enforces it. (New check, not
a relocation.)

Does `labels.lane_other`'s declared spelling -- the triager's own recorded
"no real lane owns this issue's files" decision (#1130) -- actually exist as
a label on this repo's forge? Gated on the same local facts
`check_label_vocabulary` (still in doctor.py) already gates on: `gh` on PATH,
`origin`/config naming the repo.

`doctor.py` imports the names below back out of this module immediately
after this docstring's own code is defined, the same pattern
`doctor_check_branch_protection.py` documents for its own checks -- so
`doctor.check_lane_other_label` answers exactly as it does here, and a
test's `monkeypatch.setattr(doctor, ...)` reaches this module's code.
"""

import json
import subprocess

import doctor
import gh_which


def lane_other_label_state(project_dir, config=None, run=None):
    """#1181: does `labels.lane_other`'s declared spelling actually exist as
    a label on this repo's forge?

    Mirrors `doctor.label_vocabulary_state`/`doctor.lane_label_state`'s
    three-state shape, with the fourth state those two do not need:
    `labels.lane_other` is itself optional (opt-in, null-is-fine, same as
    `filed_by_loop`), so "nobody has declared one" is a distinct, legitimate
    state from "declared, but the forge has no such label" --
    `doctor.check_filed_by_loop` already keeps that pair apart, and #1181's
    own issue names the identical gap for this key: nothing checked whether
    the declared spelling corresponds to a real label, and #1181's own
    "three ways this is wrong" section shows the fix has to distinguish "not
    declared" from "declared and absent" from "could not tell", not from
    `label_vocabulary_state`'s narrower shape.

      declared-and-present  the declared spelling exists on the forge.
      declared-and-absent   a spelling is declared, but no such label exists.
      not-declared          `labels.lane_other` is absent or `null` -- a
                             legitimate choice, same posture as
                             `filed_by_loop`'s own `not-declared`.
      could-not-tell        the value is not a usable label name, or the
                             forge could not be read. Must never render the
                             same as `declared-and-absent` -- an unreadable
                             forge is not evidence the label is missing.
    """
    labels = config.get("labels") if isinstance(config, dict) else None
    labels = labels if isinstance(labels, dict) else {}
    if "lane_other" not in labels or labels.get("lane_other") is None:
        return "not-declared", None
    lane_other = labels.get("lane_other")
    if not isinstance(lane_other, str) or not lane_other.strip():
        return (
            "could-not-tell",
            "labels.lane_other is not a usable label name (expected a "
            "non-empty string or null), got {!r}".format(lane_other),
        )
    run = subprocess.run if run is None else run
    slug = (config or {}).get("repo") if config else None
    if slug is not None and not isinstance(slug, str):
        return "could-not-tell", "the repo value in .oss.json is not a string"
    if not slug:
        slug, reason = doctor._origin_slug(project_dir, run=run)
        if slug is None:
            return "could-not-tell", reason
    # #1157: see `doctor.label_vocabulary_state` -- same reason, same fix.
    gh_bin = gh_which.safe_which("gh")
    if gh_bin is None:
        return "could-not-tell", "gh is not on PATH"
    try:
        done = run(
            [
                gh_bin,
                "label",
                "list",
                "--repo",
                slug,
                "--json",
                "name",
                "--limit",
                "200",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=25,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "could-not-tell", "gh label list did not run ({})".format(exc)
    if done.returncode != 0:
        return "could-not-tell", "gh label list failed for {}".format(slug)
    try:
        rows = json.loads(done.stdout or "[]")
    except ValueError:
        return (
            "could-not-tell",
            "gh label list returned output that did not parse as JSON",
        )
    names = {
        row.get("name") for row in rows if isinstance(row, dict) and row.get("name")
    }
    if lane_other in names:
        return "declared-and-present", (slug, lane_other)
    return "declared-and-absent", (slug, lane_other)


def check_lane_other_label(project_dir, config=None, run=None):
    if doctor.oss_config is None:
        doctor.report(
            "WARN",
            "labels.lane_other: not checked (scripts/oss_config.py could not "
            "be imported)",
        )
        return
    if config is None:
        doctor.report(
            "WARN", "labels.lane_other: not checked (.oss.json could not be read)"
        )
        return
    state, payload = lane_other_label_state(project_dir, config=config, run=run)
    if state == "declared-and-present":
        slug, lane_other = payload
        doctor.report(
            "OK",
            "labels.lane_other: '{}' is declared and exists as a label on {}.".format(
                lane_other, slug
            ),
        )
    elif state == "declared-and-absent":
        slug, lane_other = payload
        doctor.report(
            "WARN",
            "labels.lane_other: '{}' is declared but no such label exists on "
            "{} -- select_issues.py will find zero lane-other issues forever, "
            "which reads exactly like a lane that fills correctly and never "
            "has candidates. Create the label (`gh label create {} --repo {} "
            "--color ...`) or correct the spelling in .oss.json.".format(
                lane_other, slug, lane_other, slug
            ),
        )
    elif state == "not-declared":
        doctor.report(
            "OK",
            "labels.lane_other: not-declared -- a legitimate choice; issues "
            "the triager decides no lane owns are simply left with no lane "
            "label. Set labels.lane_other in .oss.json to give that decision "
            "its own recorded state (#1130).",
        )
    else:
        doctor.report("WARN", "labels.lane_other: could not tell -- {}".format(payload))
