"""The version number is proposed from the fragments, or it is not proposed (#171).

Every other release input is pinned somewhere a reader can find it -- `tag_pattern`,
`commit_subject`, the range, the publish policy, the version *sites*. The number
itself was not, so it came from whoever was cutting the release and from an
impression of what the delta felt like. #171 is the receipt for that: a `removed`
fragment sat unread in the same directory as the recommendation, and the
compatibility verdict that would have settled the question was a sentence in its
body where nothing could read it.

What this suite holds still:

  * the rule reads the fragment sections, not a feeling.
  * a `removed` fragment must declare whether it breaks compatibility, and one that
    does not is `could not decide` -- never a quiet minor.
  * a flag that is *present and unrecognised* is also `could not decide`. A
    wrong-but-present flag is worse than an absent one, so it never grades as
    compatible.
  * the third state emits no number at all. A default patch bump over a breaking
    change is indistinguishable in the tag from a considered one.
  * it *proposes*. The receipt says so, and the maintainer accepts or overrides.

Every case that asserts the rule refused also proposes, one mutation away, in the
same fixture. An exit 3 out of a harness that never reached the script is
indistinguishable from a refusal.
"""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
SCRIPT = SCRIPTS / "release_version.py"
sys.path.insert(0, str(SCRIPTS))

# Imported, not `importorskip`ed. A missing module here is a red collection error,
# which is what a missing module is; an `importorskip` would have rendered the whole
# of this file as `1 skipped` -- a green run over a rule nobody wrote.
import release_version  # noqa: E402

PROPOSED = 0
COULD_NOT_DECIDE = 3
NO_BASELINE = 4

GIT = shutil.which("git")

SEMVER = re.compile(r"\b\d+\.\d+\.\d+\b")


# --------------------------------------------------------------------------- helpers


def _main(argv):
    """Drive the CLI in-process: the receipt and the exit code, together."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = release_version.main(argv)
    return code, buf.getvalue()


def _payload(argv):
    code, out = _main(list(argv) + ["--json"])
    assert out.strip(), "no JSON on stdout"
    return code, json.loads(out)


def _repo(tmp_path, name="repo", changelog_dir="changelog.d", tag_pattern="v{version}"):
    root = tmp_path / name
    (root / changelog_dir).mkdir(parents=True)
    config = {"changelog_dir": changelog_dir, "release": {"tag_pattern": tag_pattern}}
    (root / ".oss.json").write_text(json.dumps(config), encoding="utf-8")
    return root


def _frag(root, name, body, changelog_dir="changelog.d"):
    (root / changelog_dir / name).write_text(body, encoding="utf-8")


COMPATIBLE = "- Compatibility: compatible - the key still validates (#1).\n"
BREAKING = "- Compatibility: breaking - callers passing the old key fail (#1).\n"

# --------------------------------------------------------------------- the happy path


def test_only_fixes_and_security_propose_a_patch(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "1.fixed.md", "- a fix (#1).\n")
    _frag(root, "2.security.md", "- a hardening (#2).\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    assert payload["state"] == "proposed"
    assert payload["change_class"] == "fix"
    assert payload["bump"] == "patch"
    assert payload["version"] == "0.4.1"


def test_an_added_fragment_proposes_a_minor(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "1.fixed.md", "- a fix (#1).\n")
    _frag(root, "2.added.md", "- a new capability (#2).\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    assert payload["change_class"] == "feature"
    assert payload["bump"] == "minor"
    assert payload["version"] == "0.5.0"
    assert payload["sections"] == {"added": 1, "fixed": 1}


def test_the_section_counts_are_reported_so_the_evidence_is_visible(tmp_path):
    """The harm in #171 was a recommendation that never mentioned the one fragment
    bearing on it. The counts and the removal are in the receipt, by name."""
    root = _repo(tmp_path)
    _frag(root, "1.added.md", "- a capability (#1).\n")
    _frag(root, "113.removed.md", "- a key is gone (#113).\n" + COMPATIBLE)

    code, out = _main(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    assert "113.removed.md" in out
    assert "removed" in out and "added" in out


# ------------------------------------------------- what `removed` means in a 0.x line


def test_a_removal_declared_compatible_is_a_feature(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "113.removed.md", "- a key is gone (#113).\n" + COMPATIBLE)

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    assert payload["change_class"] == "feature"
    assert payload["bump"] == "minor"
    assert payload["version"] == "0.5.0"
    assert payload["declared_compatible"] == ["113.removed.md"]
    assert payload["declared_breaking"] == []


def test_a_breaking_change_is_a_minor_in_a_0x_line_and_the_fold_is_stated(tmp_path):
    """The project's answer, written down: under 0.x a breaking change is a minor.

    It is the semver 0.x convention rather than a house rule, and the receipt says
    the fold happened -- otherwise a maintainer who wanted 1.0.0 sees a minor and no
    reason to argue with it.
    """
    root = _repo(tmp_path)
    _frag(root, "113.removed.md", "- a key is gone (#113).\n" + BREAKING)

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    assert payload["change_class"] == "breaking"
    assert payload["line"] == "0.x"
    assert payload["bump"] == "minor"
    assert payload["version"] == "0.5.0"
    assert payload["declared_breaking"] == ["113.removed.md"]
    assert "0.x" in payload["reason"]


def test_the_same_breaking_change_is_a_major_at_1_0_or_later(tmp_path):
    """The positive control for the fold above: the flag is inert in a 0.x line and
    decisive past 1.0, and the same fixture shows both."""
    root = _repo(tmp_path)
    _frag(root, "113.removed.md", "- a key is gone (#113).\n" + BREAKING)

    code, payload = _payload(["--repo", str(root), "--current", "1.4.0"])

    assert code == PROPOSED
    assert payload["line"] == ">=1.0"
    assert payload["bump"] == "major"
    assert payload["version"] == "2.0.0"


def test_a_breaking_declaration_outranks_every_other_section(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "1.fixed.md", "- a fix (#1).\n")
    _frag(root, "2.changed.md", "- a change (#2).\n" + BREAKING)

    code, payload = _payload(["--repo", str(root), "--current", "1.4.0"])

    assert code == PROPOSED
    assert payload["change_class"] == "breaking"
    assert payload["bump"] == "major"

# --------------------------------------------------------------- the third state


def test_a_removal_that_declares_nothing_cannot_decide(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "1.fixed.md", "- a fix (#1).\n")
    _frag(root, "113.removed.md", "- a key is gone (#113).\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == COULD_NOT_DECIDE
    assert payload["state"] == "could-not-decide"
    assert payload["undeclared"] == ["113.removed.md"]
    assert payload["version"] is None
    assert payload["bump"] is None


def test_the_same_removal_proposes_once_it_declares(tmp_path):
    """The must-fire half. Without it, exit 3 above is satisfied by a script that
    refuses everything, including a fixture it should answer."""
    root = _repo(tmp_path)
    _frag(root, "1.fixed.md", "- a fix (#1).\n")
    _frag(root, "113.removed.md", "- a key is gone (#113).\n" + COMPATIBLE)

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    assert payload["version"] == "0.5.0"


def test_an_unrecognised_section_cannot_decide(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "1.added.md", "- a capability (#1).\n")
    _frag(root, "2.improved.md", "- something (#2).\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == COULD_NOT_DECIDE
    assert payload["unreadable"] == ["2.improved.md"]
    assert payload["version"] is None


def test_the_same_directory_proposes_once_the_section_is_one_of_the_six(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "1.added.md", "- a capability (#1).\n")
    _frag(root, "2.changed.md", "- something (#2).\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    assert payload["version"] == "0.5.0"


def test_no_fragments_at_all_cannot_decide(tmp_path):
    root = _repo(tmp_path)

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == COULD_NOT_DECIDE
    assert payload["fragments"] == 0
    assert payload["version"] is None


def test_one_fragment_is_enough_to_propose(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "1.fixed.md", "- a fix (#1).\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    assert payload["fragments"] == 1


def test_a_missing_fragment_directory_cannot_decide(tmp_path):
    root = _repo(tmp_path)
    shutil.rmtree(str(root / "changelog.d"))

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == COULD_NOT_DECIDE
    assert payload["version"] is None


def test_a_config_that_names_no_fragment_directory_cannot_decide(tmp_path):
    """It never guesses `changelog.d`. A directory this script picked is a directory
    the project did not name, and an empty one there would read as `no fragments`."""
    root = tmp_path / "unconfigured"
    root.mkdir()
    (root / ".oss.json").write_text(json.dumps({"release": {}}), encoding="utf-8")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == COULD_NOT_DECIDE
    assert "changelog_dir" in payload["reason"]
    assert payload["version"] is None


def test_the_same_repo_proposes_once_the_directory_is_named(tmp_path):
    root = tmp_path / "unconfigured"
    (root / "changelog.d").mkdir(parents=True)
    (root / ".oss.json").write_text(
        json.dumps({"changelog_dir": "changelog.d", "release": {}}), encoding="utf-8"
    )
    _frag(root, "1.fixed.md", "- a fix (#1).\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    assert payload["version"] == "0.4.1"


# ------------------------- scaffold's own fallback, recognised rather than refused (#299)


def _scaffold_workflow(root):
    workflow = root / ".github" / "workflows" / "oss-changelog.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text("name: oss changelog\n", encoding="utf-8")


def test_a_scaffolded_repo_with_no_changelog_dir_key_proposes(tmp_path):
    """The state #299 is about: `/oss:scaffold --apply` created `changelog.d/` and the
    gating workflow that names it, but `changelog_dir` itself is still null. A directory
    this script picked out of thin air would be exactly the failure `NO_DIRECTORY`
    exists to refuse -- but scaffold DID name one, in the workflow it wrote, and this is
    that same fallback recognised rather than re-guessed."""
    root = tmp_path / "scaffolded"
    (root / "changelog.d").mkdir(parents=True)
    (root / ".oss.json").write_text(
        json.dumps({"changelog_dir": None, "release": {}}), encoding="utf-8"
    )
    _scaffold_workflow(root)
    _frag(root, "1.fixed.md", "- a fix (#1).\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    assert payload["version"] == "0.4.1"


def test_a_scaffolded_repo_with_no_changelog_dir_key_at_all_also_proposes(tmp_path):
    """The absent-key shape, not just explicit null -- `/oss:setup` never writes the
    key at all when nothing was probed, so this is the config a freshly scaffolded
    repo actually carries."""
    root = tmp_path / "scaffolded-absent-key"
    (root / "changelog.d").mkdir(parents=True)
    (root / ".oss.json").write_text(json.dumps({"release": {}}), encoding="utf-8")
    _scaffold_workflow(root)
    _frag(root, "1.fixed.md", "- a fix (#1).\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    assert payload["version"] == "0.4.1"


def test_a_null_changelog_dir_with_no_scaffolded_workflow_still_cannot_decide(tmp_path):
    """The positive control's negative twin, in the same shape of fixture: null and NO
    `oss-changelog.yml` is the repo that genuinely has not adopted fragments, and the
    loud refusal from before #299 must be unchanged for it -- a directory picked here
    is still a directory nobody named."""
    root = tmp_path / "not-adopted"
    (root / "changelog.d").mkdir(parents=True)
    (root / ".oss.json").write_text(
        json.dumps({"changelog_dir": None, "release": {}}), encoding="utf-8"
    )
    _frag(root, "1.fixed.md", "- a fix (#1).\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == COULD_NOT_DECIDE
    assert "changelog_dir" in payload["reason"]
    assert payload["version"] is None


# ------------------------------------------- a wrong-but-present flag never grades


def test_an_unrecognised_compatibility_verdict_cannot_decide(tmp_path):
    root = _repo(tmp_path)
    _frag(
        root,
        "113.removed.md",
        "- a key is gone (#113).\n- Compatibility: probably fine (#113).\n",
    )

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == COULD_NOT_DECIDE
    assert payload["unreadable"] == ["113.removed.md"]
    assert payload["version"] is None


def test_a_compatibility_line_with_no_reason_cannot_decide(tmp_path):
    """The flag without the sentence is the same unsourced verdict one field along.
    #171's fragment already carried the sentence; the field only makes it findable."""
    root = _repo(tmp_path)
    _frag(root, "113.removed.md", "- a key is gone (#113).\n- Compatibility: compatible\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == COULD_NOT_DECIDE
    assert payload["unreadable"] == ["113.removed.md"]


def test_the_same_line_reads_once_it_carries_its_reason(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "113.removed.md", "- a key is gone (#113).\n" + COMPATIBLE)

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    assert payload["declared_compatible"] == ["113.removed.md"]


def test_the_assumption_behind_an_undeclared_fragment_is_counted_and_named(tmp_path):
    """Sections other than `removed` are read as compatible when they say nothing.
    That is an assumption, so it is reported rather than folded in silently."""
    root = _repo(tmp_path)
    _frag(root, "1.changed.md", "- a change (#1).\n")
    _frag(root, "2.changed.md", "- another change (#2).\n" + COMPATIBLE)

    code, out = _main(["--repo", str(root), "--current", "0.4.0"])
    _, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    assert payload["assumed_compatible"] == 1
    assert "assumed" in out

# ------------------------------------------------------- the third state names nothing


def _proposal_line(receipt):
    for line in receipt.splitlines():
        if line.startswith("proposal"):
            return line
    raise AssertionError("no proposal line in:\n" + receipt)


def test_a_refusal_never_names_a_number(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "113.removed.md", "- a key is gone (#113).\n")

    code, out = _main(["--repo", str(root), "--current", "0.4.0"])

    assert code == COULD_NOT_DECIDE
    line = _proposal_line(out)
    assert "NONE" in line
    assert not SEMVER.search(line), line


def test_a_proposal_does_name_one(tmp_path):
    """The must-fire half of the assertion above: `no number in the proposal line`
    passes just as readily over a script that never proposes anything."""
    root = _repo(tmp_path)
    _frag(root, "113.removed.md", "- a key is gone (#113).\n" + COMPATIBLE)

    code, out = _main(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    line = _proposal_line(out)
    assert SEMVER.search(line), line
    assert "0.5.0" in line


def test_the_receipt_says_it_is_a_proposal_rather_than_a_decision(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "1.added.md", "- a capability (#1).\n")

    _, out = _main(["--repo", str(root), "--current", "0.4.0"])

    lowered = out.lower()
    assert "proposal" in lowered
    assert "override" in lowered


# ------------------------------------------------------------------- the baseline


def test_an_unparseable_current_version_has_no_baseline(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "1.added.md", "- a capability (#1).\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4"])

    assert code == NO_BASELINE
    assert payload["state"] == "no-baseline"
    assert payload["bump"] is None
    assert payload["version"] is None
    # The class is still known, and saying so is the difference between "I could
    # not read the delta" and "I could not read the number it applies to".
    assert payload["change_class"] == "feature"


def test_a_prerelease_current_version_has_no_baseline(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "1.added.md", "- a capability (#1).\n")

    code, payload = _payload(["--repo", str(root), "--current", "1.0.0-rc1"])

    assert code == NO_BASELINE
    assert payload["version"] is None


def test_a_triple_is_a_baseline(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "1.added.md", "- a capability (#1).\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    assert payload["current"] == "0.4.0"


def test_a_refusal_about_the_fragments_outranks_a_missing_baseline(tmp_path):
    """Both are wrong here; the fragments are the one the maintainer has to fix, and
    a baseline complaint would send them to the other end of the problem."""
    root = _repo(tmp_path)
    _frag(root, "113.removed.md", "- a key is gone (#113).\n")

    code, payload = _payload(["--repo", str(root), "--current", "nonsense"])

    assert code == COULD_NOT_DECIDE
    assert payload["state"] == "could-not-decide"

# ------------------------------------------------- deriving the baseline from a tag


needs_git = pytest.mark.skipif(
    GIT is None,
    reason="git is not on PATH, so a tag baseline cannot be built or observed here",
)


def _env():
    env = dict(os.environ)
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "T",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "T",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


def _git(root, *args):
    done = subprocess.run(
        [GIT, "-C", str(root)] + list(args),
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout.strip()


def _commit(root, name="a.txt"):
    (Path(root) / name).write_text(name, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "c")


@needs_git
def test_the_baseline_comes_from_the_last_tag_that_matches_the_pattern(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "1.added.md", "- a capability (#1).\n")
    _git(root, "init", "-q")
    _commit(root)
    _git(root, "tag", "v0.4.0")
    _commit(root, "b.txt")

    code, payload = _payload(["--repo", str(root)])

    assert code == PROPOSED
    assert payload["current"] == "0.4.0"
    assert payload["version"] == "0.5.0"
    assert payload["baseline"] == "tag"


@needs_git
def test_a_repo_with_no_tag_has_no_baseline(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "1.added.md", "- a capability (#1).\n")
    _git(root, "init", "-q")
    _commit(root)

    code, payload = _payload(["--repo", str(root)])

    assert code == NO_BASELINE
    assert payload["version"] is None
    assert payload["change_class"] == "feature"


@needs_git
def test_a_null_tag_pattern_has_no_baseline(tmp_path):
    """`v1.2.0` and `1.2.0` are the same release under two spellings, and the repo is
    the only thing that knows which. Stripping a leading `v` on a hunch is how a
    number gets read out of a tag that never carried one."""
    root = _repo(tmp_path, tag_pattern=None)
    _frag(root, "1.added.md", "- a capability (#1).\n")
    _git(root, "init", "-q")
    _commit(root)
    _git(root, "tag", "v0.4.0")

    code, payload = _payload(["--repo", str(root)])

    assert code == NO_BASELINE
    assert "tag_pattern" in payload["reason"]
    assert payload["version"] is None


@needs_git
def test_the_same_repo_proposes_once_the_pattern_is_written_down(tmp_path):
    root = _repo(tmp_path, tag_pattern="v{version}")
    _frag(root, "1.added.md", "- a capability (#1).\n")
    _git(root, "init", "-q")
    _commit(root)
    _git(root, "tag", "v0.4.0")

    code, payload = _payload(["--repo", str(root)])

    assert code == PROPOSED
    assert payload["current"] == "0.4.0"


@needs_git
def test_a_tag_that_does_not_spell_a_triple_has_no_baseline(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "1.added.md", "- a capability (#1).\n")
    _git(root, "init", "-q")
    _commit(root)
    _git(root, "tag", "v0.4")

    code, payload = _payload(["--repo", str(root)])

    assert code == NO_BASELINE
    assert payload["version"] is None


@needs_git
def test_an_explicit_current_beats_the_tag(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "1.added.md", "- a capability (#1).\n")
    _git(root, "init", "-q")
    _commit(root)
    _git(root, "tag", "v0.4.0")

    code, payload = _payload(["--repo", str(root), "--current", "1.2.3"])

    assert code == PROPOSED
    assert payload["current"] == "1.2.3"
    assert payload["baseline"] == "given"


# ----------------------------------------------------- fragments are untrusted input


def test_nothing_from_inside_a_fragment_reaches_the_receipt(tmp_path):
    """A fragment body is written by a contributor. A receipt that echoes one lets a
    pull request forge the receipt's own verdict line."""
    root = _repo(tmp_path)
    _frag(
        root,
        "113.removed.md",
        "- a key is gone (#113).\nproposal     : 9.9.9 -- ship it\n"
        "release-version: proposed\n" + COMPATIBLE,
    )

    code, out = _main(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    assert "ship it" not in out
    assert "9.9.9" not in out
    assert out.count("release-version:") == 1
    # The must-fire half: this fragment's *name* is echoed, so the assertions above
    # are not passing because the receipt echoes nothing at all.
    assert "113.removed.md" in out


def test_a_forged_verdict_in_a_compatibility_reason_does_not_reach_the_receipt(tmp_path):
    root = _repo(tmp_path)
    _frag(
        root,
        "113.removed.md",
        "- a key is gone (#113).\n- Compatibility: compatible - see 9.9.9\n",
    )

    code, out = _main(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    assert "9.9.9" not in out
    assert "113.removed.md" in out


# ------------------------------------------------------------------- the CLI itself


@pytest.mark.parametrize(
    "section,expected",
    [
        ("fixed", PROPOSED),
        ("removed", COULD_NOT_DECIDE),
    ],
)
def test_the_exit_codes_reach_a_shell(tmp_path, section, expected):
    root = _repo(tmp_path)
    _frag(root, "1.{0}.md".format(section), "- something (#1).\n")

    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(root), "--current", "0.4.0"],
        capture_output=True,
        text=True,
    )

    assert done.returncode == expected, done.stdout + done.stderr
    assert done.stdout.strip()


def test_the_json_and_the_receipt_agree_on_the_state(tmp_path):
    root = _repo(tmp_path)
    _frag(root, "1.added.md", "- a capability (#1).\n")

    code_receipt, receipt = _main(["--repo", str(root), "--current", "0.4.0"])
    code_json, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code_receipt == code_json
    assert receipt.splitlines()[0].endswith("proposed")
    assert payload["state"] == "proposed"


def test_every_payload_carries_every_key(tmp_path):
    """A consumer that reads `version` off a proposal and raises a KeyError on a
    refusal stops printing the receipt at the moment it matters most."""
    root = _repo(tmp_path)
    _frag(root, "1.removed.md", "- a key is gone (#1).\n")
    _, refused = _payload(["--repo", str(root), "--current", "0.4.0"])
    _frag(root, "1.removed.md", "- a key is gone (#1).\n" + COMPATIBLE)
    _, proposed = _payload(["--repo", str(root), "--current", "0.4.0"])
    _, no_baseline = _payload(["--repo", str(root), "--current", "0.4"])

    assert set(refused) == set(proposed) == set(no_baseline)

# ------------------------------------------------- the rule is written down, twice
#
# A script nobody is told to run is the same gap one directory along. The two
# documents that state every other release input have to state this one, and the
# fragment convention has to document the field the rule reads -- otherwise the
# compatibility verdict goes on living in a body where nothing can see it, which is
# the whole of #171.


RELEASE_COMMAND = REPO_ROOT / "commands" / "release.md"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from manager_docs import ManagerLoop  # noqa: E402

#: The manager loop's whole prose -- SKILL.md plus every phase file it defers
#: to. The checks below ask "does the loop say X", never "does one file say
#: X"; pinned to the spine alone they would have gone quietly narrower than
#: their own subject the moment a paragraph moved into a phase file.
MANAGER_SKILL = ManagerLoop(REPO_ROOT)
FRAGMENT_README = REPO_ROOT / "changelog.d" / "README.md"

VERSION_RULE_ANCHORS = [
    ("names-the-script-that-computes-it", ("release_version.py",)),
    ("it-proposes-rather-than-decides", ("proposal",)),
    # Not the bare word `override`: both documents already carry it about other
    # things, so an anchor on it would have been green before this rule existed --
    # a check that reports satisfied without having looked at the subject.
    ("the-maintainer-can-override-it", ("override the proposal",)),
    ("a-rule-that-cannot-decide-says-so", ("could not decide",)),
    ("no-number-is-invented-for-the-third-state", ("names no number",)),
    ("what-a-removal-means-in-a-0x-line", ("0.x",)),
]


def _version_rule_unmet(text):
    folded = text.lower()
    return {
        name
        for name, anchors in VERSION_RULE_ANCHORS
        if not all(anchor.lower() in folded for anchor in anchors)
    }


def test_the_release_command_says_where_the_number_comes_from():
    unmet = _version_rule_unmet(RELEASE_COMMAND.read_text(encoding="utf-8"))
    assert not unmet, (
        "commands/release.md pins every release input except the number that names "
        "the release: " + repr(sorted(unmet))
    )


def test_the_manager_skill_says_the_same_thing():
    """Two documents state the release gates. If only one gains the rule, the other
    keeps sending its reader to an unsourced guess -- which is how #171 happened."""
    unmet = _version_rule_unmet(MANAGER_SKILL.read_text(encoding="utf-8"))
    assert not unmet, (
        "skills/manager/SKILL.md states the release gates without saying how the "
        "version is chosen: " + repr(sorted(unmet))
    )


def test_the_version_rule_anchors_fire_on_the_gate_as_it_was_stated_before():
    """The positive control, and it is the actual prior text: gate 4 said where the
    number goes and nothing said what it is. Every anchor must report unmet against
    it, or the two checks above say nothing about whether the rule is written down.
    """
    the_unsourced_gate = (
        "4. **Every site in `version_sites` bumped**, swept **unfiltered**:\n\n"
        "   ```bash\n   git grep -n \"<the new version>\"\n   ```\n\n"
        "   A sweep keyed on the *outgoing* version only finds sites that are "
        "half-bumped. It cannot find one frozen at some third value, which is the "
        "one most likely to be wrong. A README is not a `.json`, so an allowlist by "
        "extension cannot see it.\n"
    )
    unmet = _version_rule_unmet(the_unsourced_gate)
    assert unmet == {name for name, _ in VERSION_RULE_ANCHORS}, repr(sorted(unmet))


FRAGMENT_FIELD_ANCHORS = [
    ("names-the-field", ("compatibility:",)),
    ("names-both-verdicts", ("breaking", "compatible")),
    ("says-which-section-must-carry-it", ("removed",)),
    ("says-the-reason-is-part-of-it", ("reason",)),
]


def _fragment_field_unmet(text):
    folded = text.lower()
    return {
        name
        for name, anchors in FRAGMENT_FIELD_ANCHORS
        if not all(anchor.lower() in folded for anchor in anchors)
    }


def test_the_fragment_convention_documents_the_compatibility_field():
    unmet = _fragment_field_unmet(FRAGMENT_README.read_text(encoding="utf-8"))
    assert not unmet, (
        "changelog.d/README.md does not document the field the version rule reads, "
        "so an author writes the verdict into the body again: " + repr(sorted(unmet))
    )


def test_the_fragment_field_anchors_fire_on_the_convention_as_it_was_stated_before():
    the_prior_convention = (
        "## Body\n\nA single top-level `-` list. No headings, no raw HTML, no "
        "unclosed fences. Name the issue in the text -- the file name is metadata, "
        "and metadata does not survive being read out of context.\n"
    )
    unmet = _fragment_field_unmet(the_prior_convention)
    assert unmet == {name for name, _ in FRAGMENT_FIELD_ANCHORS}, repr(sorted(unmet))


def test_this_repos_own_removal_fragment_declares_its_compatibility():
    """Dogfood. #171's evidence was a fragment in this very directory whose
    compatibility verdict was prose. If the convention does not reach the file that
    produced the issue, it has not reached anything.

    Skipped rather than asserted when no removal fragment is pending, and the reason
    says so -- a sweep over an empty set is trivially clean, which is the shape this
    repository is named after.
    """
    removals = sorted(FRAGMENT_README.parent.glob("*.removed.md"))
    if not removals:
        pytest.skip("no removal fragment is pending, so there is nothing to check")
    undeclared = [
        path.name
        for path in removals
        if not release_version.compatibility(path.read_text(encoding="utf-8"))[0]
    ]
    assert not undeclared, (
        "these removal fragments state no machine-readable compatibility verdict: "
        + repr(undeclared)
    )

def test_a_fragment_that_cannot_be_read_is_reported_rather_than_dropped(tmp_path):
    """`Path.is_file` swallows every OSError and answers False, so a filter built on
    it drops the entry it could not stat and the count comes back one short -- a
    clean-looking scan of a directory that was not fully read.

    The fixture is a directory wearing a fragment's name, which needs no permission
    bit and therefore behaves the same on every platform: the name selects it, the
    read refuses it, and it lands in `unreadable`.
    """
    root = _repo(tmp_path)
    _frag(root, "1.fixed.md", "- a fix (#1).\n")
    (root / "changelog.d" / "2.added.md").mkdir()

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == COULD_NOT_DECIDE
    assert payload["unreadable"] == ["2.added.md"]
    assert payload["fragments"] == 2
    assert payload["version"] is None


def test_the_same_directory_proposes_once_the_unreadable_entry_is_a_file(tmp_path):
    """The must-fire half: two fragments, both readable, and the count is the same 2.
    Without this the assertion above is satisfied by a scan that refuses everything.
    """
    root = _repo(tmp_path)
    _frag(root, "1.fixed.md", "- a fix (#1).\n")
    _frag(root, "2.added.md", "- a capability (#2).\n")

    code, payload = _payload(["--repo", str(root), "--current", "0.4.0"])

    assert code == PROPOSED
    assert payload["unreadable"] == []
    assert payload["fragments"] == 2
    assert payload["version"] == "0.5.0"

# The rule an agent is *given* is a fourth place the convention lives, and it is the
# one that reaches an author at the moment they write a fragment. The three documents
# above are pulled; this one is pushed. It came back as a review finding on this very
# commit: the README, the command and the skill had all been updated and the injected
# rule still described the pre-#171 body, so an agent following only what it was
# handed would omit the field and stop the next release.

RULE_LAYER = (
    REPO_ROOT / ".claude" / "jit-context" / "paths" / "01-oss" / "changelog-fragments.md"
)


def test_the_injected_fragment_rule_names_the_compatibility_field():
    """The artifact, not the generator. tests/test_oss_rules.py holds the committed
    layer equal to what `scripts/oss_rules.py` renders; this holds that rendering to
    the convention, which equality alone cannot -- two copies agree perfectly while
    both being out of date."""
    unmet = _fragment_field_unmet(RULE_LAYER.read_text(encoding="utf-8"))
    assert not unmet, (
        "the jit-context rule injected when an agent touches changelog.d/ still "
        "describes the pre-#171 body: " + repr(sorted(unmet))
    )


def test_the_injected_rule_anchors_fire_on_the_body_paragraph_as_it_was_stated_before():
    the_prior_rule = (
        "**Body:** a single top-level `-` list. No headings, no raw HTML, no unclosed "
        "fences. Name the issue in the text as well as the filename -- the filename "
        "is metadata, and metadata does not survive being read out of context.\n"
    )
    unmet = _fragment_field_unmet(the_prior_rule)
    assert unmet == {name for name, _ in FRAGMENT_FIELD_ANCHORS}, repr(sorted(unmet))
