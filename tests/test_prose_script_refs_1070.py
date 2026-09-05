"""#1070: does every `scripts/<name>.py` this plugin's prose tells an agent to
run actually exist, and does every `--flag` it hands one resolve against that
script's own parser?

`tests/test_unwired_scripts_253.py` guards the opposite direction -- a script
nothing references. This guards the direction that breaks a lane mid-flight: a
stale prose call site that reads as a working command until an agent runs it.

Every negative assertion here is paired with a positive control in the same
fixture, per this repository's own convention -- a fixture that produces no
findings at all would satisfy "this is not reported missing" without
exercising anything.
"""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import prose_script_refs as refs  # noqa: E402


# --- fixtures ----------------------------------------------------------------


def _plugin_tree(root, files):
    """Write `{relative path: text}` under `root` and return `root`."""
    for rel, text in files.items():
        target = Path(root) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return Path(root)


ARGPARSE_SCRIPT = """\
import argparse


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    main()
"""

MANUAL_ARGV_SCRIPT = """\
import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    model = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--model":
            i += 1
            model = argv[i]
        elif arg == "--background":
            pass
        i += 1
    return model


if __name__ == "__main__":
    main()
"""


# --- real_scripts --------------------------------------------------------------


def test_real_scripts_lists_this_repos_own_scripts():
    names = refs.real_scripts(SCRIPTS_DIR)
    assert names is not None
    assert "prose_script_refs.py" in names, (
        "positive control: this module's own file must be in the derived set, "
        "or the derivation is not reading scripts/ at all"
    )


def test_real_scripts_of_a_missing_directory_is_none(tmp_path):
    assert refs.real_scripts(tmp_path / "does-not-exist") is None


# --- script_flags --------------------------------------------------------------


def test_script_flags_derives_argparse_style_flags(tmp_path):
    script = tmp_path / "argparse_style.py"
    script.write_text(ARGPARSE_SCRIPT, encoding="utf-8")
    flags, error = refs.script_flags(script)
    assert error is None
    assert flags == {"--repo", "--json"}


def test_script_flags_derives_manual_argv_style_flags(tmp_path):
    """Not every script under scripts/ builds an ArgumentParser --
    `plugin_update.py`, `select_issues.py` and `fleet_label.py` parse
    `sys.argv` by hand. A check that only understood `ArgumentParser` would
    report every one of their real flags as missing."""
    script = tmp_path / "manual_argv.py"
    script.write_text(MANUAL_ARGV_SCRIPT, encoding="utf-8")
    flags, error = refs.script_flags(script)
    assert error is None
    assert flags == {"--model", "--background"}


def test_script_flags_of_an_unreadable_file_is_none_with_a_detail(tmp_path):
    script = tmp_path / "gone.py"
    flags, error = refs.script_flags(script)
    assert flags is None
    assert error


def test_script_flags_of_a_syntax_error_is_none_with_a_detail(tmp_path):
    script = tmp_path / "broken.py"
    script.write_text("def broken(:\n", encoding="utf-8")
    flags, error = refs.script_flags(script)
    assert flags is None
    assert "SyntaxError" in error


# --- check_text: tier 1, existence --------------------------------------------


def test_tier1_flags_a_script_that_does_not_exist(tmp_path):
    (tmp_path / "real.py").write_text("pass\n", encoding="utf-8")
    text = "See `scripts/real.py` and `scripts/does_not_exist.py`.\n"
    findings = refs.check_text(text, tmp_path)
    kinds = [(f["kind"], f["script"]) for f in findings]
    assert ("missing-script", "does_not_exist.py") in kinds
    assert ("missing-script", "real.py") not in kinds, (
        "positive control: a script that IS on disk must never be reported "
        "missing, or this assertion is not testing the existence check at all"
    )


def test_tier1_does_not_flag_narrative_mention_of_a_real_script():
    findings = refs.check_text(
        "`scripts/prose_script_refs.py` derives both sides.\n", SCRIPTS_DIR
    )
    assert findings == []


# --- check_text: tier 2, flags -------------------------------------------------


def test_tier2_flags_a_flag_the_script_does_not_accept(tmp_path):
    scripts_dir = tmp_path
    (scripts_dir / "real.py").write_text(ARGPARSE_SCRIPT, encoding="utf-8")
    text = (
        "```bash\n"
        'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/real.py" --repo . --nope\n'
        "```\n"
    )
    findings = refs.check_text(text, scripts_dir)
    kinds = [(f["kind"], f["script"], f["flag"]) for f in findings]
    assert ("missing-flag", "real.py", "--nope") in kinds
    assert ("missing-flag", "real.py", "--repo") not in kinds, (
        "positive control: a flag the script DOES accept must never be reported missing"
    )


def test_tier2_accepts_help_universally(tmp_path):
    """Every ArgumentParser in this tree leaves add_help at its default, so
    --help/-h are always valid even though no script declares them by hand."""
    scripts_dir = tmp_path
    (scripts_dir / "real.py").write_text(ARGPARSE_SCRIPT, encoding="utf-8")
    text = '`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/real.py" --help`\n'
    findings = refs.check_text(text, scripts_dir)
    assert findings == []


def test_tier2_does_not_flag_a_flag_from_a_bare_narrative_mention(tmp_path):
    """A `scripts/x.py` occurrence that is not inside a documented command
    line (a fenced block or an inline backtick span) contributes no Tier 2
    findings at all -- prose describing a script is not a call to it."""
    scripts_dir = tmp_path
    (scripts_dir / "real.py").write_text(ARGPARSE_SCRIPT, encoding="utf-8")
    text = "scripts/real.py takes --repo and also, elsewhere, --nope is mentioned.\n"
    findings = refs.check_text(text, scripts_dir)
    assert findings == []


def test_tier2_does_not_reach_across_a_paragraph_to_a_different_scripts_flag(
    tmp_path,
):
    """Regression for the false positive this module's own build hit against
    the real corpus: `select_issues.py` (documented as taking no flags) was
    mentioned in the same paragraph as `--claim`, a flag that belongs to a
    different script (`issue_claim.py`) discussed two sentences later. A
    paragraph-wide window reads that as `select_issues.py --claim` and must
    not."""
    scripts_dir = tmp_path
    (scripts_dir / "select_issues.py").write_text(
        "def main(argv=None):\n    del argv\n", encoding="utf-8"
    )
    (scripts_dir / "issue_claim.py").write_text(ARGPARSE_SCRIPT, encoding="utf-8")
    text = (
        "**Run `scripts/select_issues.py`** as the dispatch call. It does not "
        "replace `--claim` below -- reading who is claimable and writing a "
        "claim stay separate calls.\n"
    )
    findings = refs.check_text(text, scripts_dir)
    assert findings == [], (
        "a flag mentioned later in the same paragraph, for a different "
        "script, must not be attributed to the first script named -- "
        "got {0!r}".format(findings)
    )


def test_tier2_follows_a_backslash_continued_logical_line(tmp_path):
    """A fenced-block command wrapped across physical lines with a trailing
    `\\` must still be read as one command -- the flag on the continuation
    line belongs to the script named on the line above."""
    scripts_dir = tmp_path
    (scripts_dir / "real.py").write_text(ARGPARSE_SCRIPT, encoding="utf-8")
    text = (
        "```bash\n"
        'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/real.py" \\\n'
        "  --nope --repo .\n"
        "```\n"
    )
    findings = refs.check_text(text, scripts_dir)
    kinds = [(f["kind"], f["script"], f["flag"]) for f in findings]
    assert ("missing-flag", "real.py", "--nope") in kinds


def test_tier2_keeps_two_scripts_in_one_fenced_block_apart(tmp_path):
    """A fenced block naming two different scripts on two different logical
    lines must check each script's flags against only its own line."""
    scripts_dir = tmp_path
    (scripts_dir / "first.py").write_text(ARGPARSE_SCRIPT, encoding="utf-8")
    (scripts_dir / "second.py").write_text(MANUAL_ARGV_SCRIPT, encoding="utf-8")
    text = (
        "```bash\n"
        'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/first.py" --repo .\n'
        'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/second.py" --model sonnet\n'
        "```\n"
    )
    findings = refs.check_text(text, scripts_dir)
    assert findings == [], (
        "both flags are real, for the script actually named on their own "
        "line -- got {0!r}".format(findings)
    )


def test_tier2_reports_could_not_derive_flags_for_a_broken_script(tmp_path):
    scripts_dir = tmp_path
    (scripts_dir / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    text = '`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/broken.py" --whatever`\n'
    findings = refs.check_text(text, scripts_dir)
    kinds = [(f["kind"], f["script"]) for f in findings]
    assert ("could-not-derive-flags", "broken.py") in kinds


# --- survey: three states, real corpus -----------------------------------------


def test_survey_over_this_repos_own_prose_has_no_findings():
    """The real corpus, checked against itself: this is the guard, not just a
    fixture exercise. A finding here means shipped prose names a script that
    does not exist or a flag that script does not accept."""
    findings, roots = refs.survey(REPO_ROOT)
    states = dict((name, state) for name, state, _detail in roots)
    for name, state, detail in roots:
        assert state == "read", "{0}: {1} ({2})".format(name, state, detail)
    assert findings == [], findings
    assert set(states) == set(refs.OP_TEXT_ROOTS)


def test_survey_a_missing_source_root_is_absent_not_unreadable(tmp_path):
    _plugin_tree(tmp_path, {"scripts/x.py": "pass\n", "commands/tick.md": "x\n"})
    findings, roots = refs.survey(tmp_path)
    states = dict((name, state) for name, state, _detail in roots)
    assert states["agents"] == "absent", states
    assert states["skills"] == "absent", states
    assert states["commands"] == "read", states
    assert findings == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits only")
def test_survey_an_unreadable_source_root_is_reported_as_unreadable(tmp_path):
    """A root the walk could not enter must never render as a root with
    nothing wrong in it -- the defect class this whole repository is named
    after."""
    _plugin_tree(
        tmp_path,
        {
            "scripts/real.py": "pass\n",
            "commands/tick.md": "`scripts/real.py`\n",
            "agents/developer.md": "`scripts/does_not_exist.py`\n",
        },
    )
    denied = tmp_path / "agents"
    try:
        os.chmod(str(denied), 0o000)
    except OSError as exc:
        pytest.skip("os.chmod would not set mode 000 ({0})".format(exc))
    try:
        if os.access(str(denied), os.R_OK):
            pytest.skip("this process can read a 0o000 directory (likely root)")
        try:
            os.listdir(str(denied))
        except OSError:
            pass
        else:
            pytest.skip("the deny did not take -- os.listdir still succeeded")
        findings, roots = refs.survey(tmp_path)
        states = dict((name, state) for name, state, _detail in roots)
        assert states["agents"] == "unreadable", states
        assert states["commands"] == "read", (
            "positive control: the readable root in the same fixture must "
            "still report `read`, or the assertion above is about a broken "
            "fixture"
        )
    finally:
        os.chmod(str(denied), 0o700)
