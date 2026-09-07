"""``check_lane_coupling`` -- its own module per the #497/#630 convention.

`doctor.py` keeps `main()`, the check registry and the shared contract (exit
0 always, one VERDICT line, `report()`/`unmeasured()`); this module holds one
check and its own private helpers. Every shared name -- `report` -- is
reached through `import doctor`, never `from doctor import name`, the reason
spelled out in full in `scripts/doctor_check_statusline.py`: a name looked
up this way is always the current value in `doctor`'s own namespace, which
is what keeps a test's `monkeypatch.setattr(doctor, ...)` reaching this
module too.

Wraps `scripts/lane_coupling.py`'s own three states (`ok` / `finding` /
`not-configured`) in the doctor states the contract asks for
(`.claude/jit-context/paths/00-manual/doctor-check-contract.md`) -- the
identical shape #1229's `doctor_check_lane_patterns.py` already uses for the
closely related check:

* `not-configured` is `NOTICE`, never `WARN` -- a repo that has never
  declared `labels.lane_patterns` cannot be checked at all, which is the
  structurally-unanswerable state NOTICE exists for (#764), reported on
  every run and never gating the VERDICT.
* `finding` is `WARN` -- at least one UNACKNOWLEDGED test file's static
  references span two or more lanes, a lane's `lane_patterns` value is
  malformed, or a test file could not be read. Every remedy names an edit
  to `.oss.json` a session can make directly: fix the test/pattern, or --
  once reviewed and confirmed intentional, per #1244's own noise-reduction
  design -- add the test file to `labels.lane_coupling_allowlist`.
* `ok` is `OK`. The acknowledged count is folded into the message
  informationally, the same `uncovered_count` shape
  `doctor_check_lane_patterns.py` already uses -- never one line per
  acknowledged file, which is exactly the ~48-line noise #1244 exists to
  avoid.

**Why an allowlist, not a threshold or a narrower literal scope (#1244's own
three explicitly-offered options).** A trial run over this repo's own real
suite found 48 of 465 test files already span two or more lanes, almost all
of them a whole-repo guard test (`tests/test_content_invariants.py`,
`tests/test_unwired_scripts_253.py`, ...) reading several lanes' files on
purpose to check a cross-cutting invariant -- not an accidental #1201-shaped
collision. Neither a lane-count threshold nor a narrower "bookkeeping-shaped
literal" scope can tell the two apart: #1201's own real incident (`CLAUDE.md`
+ `scripts/skill_phases.py`) spanned exactly two lanes, the same as most of
the 48, and a majority of the 48 already read literal, non-glob paths, so
neither axis separates "intentional" from "accidental". What DOES separate
them is a human having looked -- exactly what `labels.lane_coupling_
allowlist` records, per this repo's own governing rule that a fact about one
repository never lives in shared code (the same reason `labels.lane_
patterns` itself is per-repo config rather than a hardcoded table). A test
file NOT on the allowlist still fires as `WARN`, so a genuinely new,
unreviewed coupling -- the entire reason this module exists -- still reaches
a maintainer.

`scripts/lane_coupling.py` is its own module rather than logic inlined
here, matching `lane_pattern_coverage.py`'s own precedent, so it stays
runnable by hand while reviewing a candidate for the allowlist -- the exact
moment somebody wants the answer.
"""

import doctor
import lane_coupling


def _lane_patterns_from(config):
    labels = config.get("labels")
    if not isinstance(labels, dict):
        return None
    return labels.get("lane_patterns")


def _allowlist_from(config):
    labels = config.get("labels")
    if not isinstance(labels, dict):
        return None
    return labels.get("lane_coupling_allowlist")


def check_lane_coupling(project_dir, config):
    if config is None:
        doctor.report(
            "WARN",
            "lane coupling: no .oss.json config available -- cannot be checked.",
        )
        return
    lane_patterns = _lane_patterns_from(config)
    allowlist = _allowlist_from(config)
    result = lane_coupling.lane_coupling_report(
        project_dir, lane_patterns, allowlist=allowlist
    )
    if result["state"] == "not-configured":
        doctor.report(
            "NOTICE",
            "lane coupling: labels.lane_patterns is not declared in .oss.json "
            "-- test-suite lane coupling cannot be checked. This is the "
            "ordinary state for a repo that has not adopted the lane-pattern "
            "convention, not a finding.",
        )
        return
    if result["state"] == "ok":
        message = (
            "lane coupling: no test file's static references span an "
            "unacknowledged pair of lanes."
        )
        count = len(result["acknowledged"])
        if count:
            message += (
                " {} test file(s) intentionally span multiple lanes and are "
                "acknowledged via labels.lane_coupling_allowlist -- "
                "informational only (#1244).".format(count)
            )
        doctor.report("OK", message)
        return
    parts = []
    for lane in result["malformed"]:
        if lane is None:
            parts.append(
                "labels.lane_patterns is not an object mapping a lane name to "
                "a list of glob patterns -- fix its shape in .oss.json."
            )
        else:
            parts.append(
                "{0}'s value in .oss.json's labels.lane_patterns is malformed "
                "-- fix its shape in .oss.json.labels.lane_patterns.{0}".format(lane)
            )
    for path, detail in result["unreadable"]:
        parts.append("{} could not be read/parsed: {}".format(path, detail))
    for test_file, lanes in result["spans"]:
        lane_names = ", ".join(lane for lane, _refs in lanes)
        parts.append(
            "{} statically references files in {} -- if this is a whole-repo "
            "guard test spanning lanes on purpose, add it to .oss.json's "
            "labels.lane_coupling_allowlist; otherwise it may be an "
            "unnoticed #1201-shaped coupling worth investigating.".format(
                test_file, lane_names
            )
        )
    doctor.report("WARN", "lane coupling: " + " | ".join(parts))
