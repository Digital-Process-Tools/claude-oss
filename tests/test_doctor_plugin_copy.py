"""`plugin copy` -- which copy of this plugin answered this invocation (#262, #248).

Version equality provably cannot answer that question: the manifest version does
not move between releases, so an installed copy at the tag and a clone twelve
merges past it declare the same number. Every fixture here therefore *constructs*
that shape -- two trees declaring the same plugin name and the same version while
implementing different contracts -- and the load-bearing assertion is the pair:
version equality returns the same answer for the skewed and the identical fixture
while this check returns different ones.

The must-not-fire half is never asserted alone. "No skew detected" is exactly what
a detector that cannot see anything prints, so each silence here sits in the same
fixture as a firing.
"""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402

SCOPE = "plugin copy scope:"
COPY = "plugin copy:"

#: Repeated on every scope line, in all three of its states. #248 is a session
#: resolving one command's text once; a line that reported the copy behind *this*
#: command as though it spoke for the session would be the same defect one layer up.
SESSION_CAVEAT = "any other command or skill in this session"


@pytest.fixture(autouse=True)
def clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _plugin_tree(root, name="oss", version="0.5.0", contract="1"):
    """A tree of the shape this check compares. `contract` is the thing that moves."""
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": name, "version": version}) + "\n", encoding="utf-8"
    )
    for sub in ("agents", "commands", "skills", "scripts"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "commands" / "doctor.md").write_text("run the diagnostic\n", encoding="utf-8")
    (root / "skills" / "manager.md").write_text("the loop\n", encoding="utf-8")
    (root / "agents" / "developer.md").write_text("one issue\n", encoding="utf-8")
    (root / "scripts" / "report_schema.py").write_text(
        "SCHEMA_VERSION = {}\n".format(contract), encoding="utf-8"
    )
    return root


def _line(lines, label):
    """The one line carrying `label`, or a failure naming everything that printed."""
    matched = [(level, message) for level, message in lines if message.startswith(label)]
    assert len(matched) == 1, "expected exactly one {!r} line, got {!r}".format(label, lines)
    return matched[0]


def _manifest_version(root):
    return json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))[
        "version"
    ]


def _skewed_pair(tmp_path):
    answered = _plugin_tree(tmp_path / "installed", contract="1")
    checkout = _plugin_tree(tmp_path / "clone", contract="2")
    return answered, checkout


def _identical_pair(tmp_path):
    answered = _plugin_tree(tmp_path / "installed", contract="1")
    checkout = _plugin_tree(tmp_path / "clone", contract="1")
    return answered, checkout


def _provenance(answered, checkout, attested="flag"):
    kwargs = {}
    if attested == "flag":
        kwargs = {"attested": answered, "attested_source": "--plugin-root"}
    return doctor.plugin_provenance(answered, checkout, **kwargs)


# --------------------------------------------------------------------------
# The pair that is the whole point: version equality cannot separate these two
# fixtures, and this check must.
# --------------------------------------------------------------------------


def test_version_equality_cannot_separate_the_two_fixtures_and_this_check_does(tmp_path):
    skew_answered, skew_checkout = _skewed_pair(tmp_path / "a")
    same_answered, same_checkout = _identical_pair(tmp_path / "b")

    # The detector somebody reaches for first, run over both fixtures. It agrees
    # with itself, which is the defect #262 records.
    assert _manifest_version(skew_answered) == _manifest_version(skew_checkout)
    assert _manifest_version(same_answered) == _manifest_version(same_checkout)

    skew_level, skew_message = _line(_provenance(skew_answered, skew_checkout), COPY)
    same_level, same_message = _line(_provenance(same_answered, same_checkout), COPY)

    assert skew_level == "WARN", skew_message
    assert same_level == "OK", same_message
    assert skew_message != same_message


def test_a_skew_names_the_differing_file_and_the_version_that_hid_it(tmp_path):
    answered, checkout = _skewed_pair(tmp_path)
    level, message = _line(_provenance(answered, checkout), COPY)

    assert level == "WARN", message
    assert "scripts/report_schema.py" in message, message
    assert "0.5.0" in message, message


def test_identical_trees_report_identical_rather_than_silence(tmp_path):
    answered, checkout = _identical_pair(tmp_path)
    level, message = _line(_provenance(answered, checkout), COPY)

    assert level == "OK", message
    assert "identical" in message, message


def test_a_difference_outside_scripts_is_seen_too(tmp_path):
    answered, checkout = _identical_pair(tmp_path)
    (checkout / "skills" / "manager.md").write_text("the loop, revised\n", encoding="utf-8")

    level, message = _line(_provenance(answered, checkout), COPY)
    assert level == "WARN", message
    assert "skills/manager.md" in message, message


def test_a_file_present_on_one_side_only_is_a_difference(tmp_path):
    answered, checkout = _identical_pair(tmp_path)
    (checkout / "commands" / "radar.md").write_text("new\n", encoding="utf-8")

    level, message = _line(_provenance(answered, checkout), COPY)
    assert level == "WARN", message
    assert "commands/radar.md" in message, message


def test_line_endings_alone_are_not_reported_as_a_skew(tmp_path):
    answered, checkout = _identical_pair(tmp_path)
    (checkout / "commands" / "doctor.md").write_bytes(b"run the diagnostic\r\n")

    level, message = _line(_provenance(answered, checkout), COPY)
    assert level == "OK", message
    assert "identical" in message, message


# --------------------------------------------------------------------------
# The third state, in each of the ways this check can fail to look.
# --------------------------------------------------------------------------


def test_a_repo_that_is_not_a_checkout_of_this_plugin_says_so_rather_than_nothing(tmp_path):
    answered = _plugin_tree(tmp_path / "installed")
    plain = tmp_path / "some-managed-repo"
    plain.mkdir()

    level, message = _line(_provenance(answered, plain), COPY)
    assert level == "OK", message
    assert "not a checkout of this plugin" in message, message
    assert "nothing to compare" in message, message


def test_a_different_plugin_is_not_compared(tmp_path):
    answered = _plugin_tree(tmp_path / "installed", name="oss")
    other = _plugin_tree(tmp_path / "other", name="supertool")

    level, message = _line(_provenance(answered, other), COPY)
    assert level == "OK", message
    assert "not a checkout of this plugin" in message, message


def test_a_manifest_that_will_not_parse_is_unknown_rather_than_clean(tmp_path):
    answered = _plugin_tree(tmp_path / "installed")
    checkout = _plugin_tree(tmp_path / "clone")
    (checkout / ".claude-plugin" / "plugin.json").write_text("{ not json", encoding="utf-8")

    level, message = _line(_provenance(answered, checkout), COPY)
    assert level == "WARN", message
    assert "could not be determined" in message, message
    assert "nothing was compared" in message, message
    assert "identical" not in message, message


def test_answering_from_a_root_that_is_gone_is_reported_rather_than_raised(tmp_path):
    answered = tmp_path / "vanished"
    checkout = _plugin_tree(tmp_path / "clone")

    lines = _provenance(answered, checkout)
    level, message = _line(lines, COPY)
    assert level == "WARN", message
    assert "identical" not in message, message


def test_an_unreadable_file_makes_the_comparison_incomplete_rather_than_clean(tmp_path):
    """A permission fixture is a measurement. The deny is confirmed by attempting the
    exact operation the code under test performs, and the test skips carrying what went
    untested when the platform did not take it -- root, some filesystems, and Windows'
    read-only attribute all decline to produce this condition.
    """
    answered, checkout = _identical_pair(tmp_path)
    victim = checkout / "scripts" / "report_schema.py"
    try:
        os.chmod(str(victim), 0)
    except OSError as exc:
        pytest.skip("chmod refused ({}); an unreadable file was not tested".format(exc))
    try:
        victim.read_bytes()
    except OSError:
        denied = True
    else:
        denied = False
    if not denied:
        os.chmod(str(victim), stat.S_IRUSR | stat.S_IWUSR)
        pytest.skip(
            "the mode bit did not deny a read on this platform/filesystem; the "
            "incomplete-comparison branch went untested here"
        )

    try:
        level, message = _line(_provenance(answered, checkout), COPY)
    finally:
        os.chmod(str(victim), stat.S_IRUSR | stat.S_IWUSR)

    assert level == "WARN", message
    assert "could not be read" in message, message
    assert "identical" not in message, message


def _deny_read(path):
    """Make `path` unreadable and confirm it. Returns False when the platform declined."""
    try:
        os.chmod(str(path), 0)
    except OSError:
        return False
    try:
        path.read_bytes()
    except OSError:
        return True
    os.chmod(str(path), stat.S_IRUSR | stat.S_IWUSR)
    return False


def test_a_partial_scan_says_so_even_where_nothing_is_compared(tmp_path):
    """The branches that return before any comparison print an identity and nothing
    else, so the identity has to carry how much of the tree it did not see. A digest
    over 20 of 26 files and one over all 26 are otherwise the same shape.
    """
    answered = _plugin_tree(tmp_path / "installed")
    plain = tmp_path / "some-managed-repo"
    plain.mkdir()
    victim = answered / "scripts" / "report_schema.py"
    if not _deny_read(victim):
        pytest.skip(
            "the mode bit did not deny a read on this platform/filesystem; a partial "
            "scan in a branch that compares nothing went untested here"
        )

    try:
        level, message = _line(_provenance(answered, plain), COPY)
    finally:
        os.chmod(str(victim), stat.S_IRUSR | stat.S_IWUSR)

    assert "could not be read" in message, message
    assert "less than the whole tree" in message, message
    # Still OK: nothing about this repo is wrong. The incompleteness is a property of
    # the identity, and saying so is the point -- it must not be silent.
    assert level == "OK", message


def test_a_complete_scan_does_not_claim_an_incomplete_one(tmp_path):
    """The positive control for the line above: same fixture, nothing denied."""
    answered = _plugin_tree(tmp_path / "installed")
    plain = tmp_path / "some-managed-repo"
    plain.mkdir()

    level, message = _line(_provenance(answered, plain), COPY)
    assert level == "OK", message
    assert "could not be read" not in message, message


# --------------------------------------------------------------------------
# The scope line: what this invocation established, and what it did not.
# --------------------------------------------------------------------------


def test_scope_is_unknown_when_nothing_named_the_root(tmp_path):
    answered, checkout = _identical_pair(tmp_path)
    level, message = _line(_provenance(answered, checkout, attested=None), SCOPE)

    assert level == "WARN", message
    assert "not established" in message, message
    assert "--plugin-root" in message, message


def test_scope_is_ok_when_the_invocation_named_the_root_that_ran(tmp_path):
    answered, checkout = _identical_pair(tmp_path)
    level, message = _line(_provenance(answered, checkout), SCOPE)

    assert level == "OK", message
    assert "not established" not in message, message


def test_scope_reports_a_named_root_that_is_not_the_tree_that_ran(tmp_path):
    answered, checkout = _identical_pair(tmp_path)
    lines = doctor.plugin_provenance(
        answered, checkout, attested=tmp_path / "elsewhere", attested_source="--plugin-root"
    )
    level, message = _line(lines, SCOPE)

    assert level == "WARN", message
    assert "elsewhere" in message, message
    assert str(answered) in message, message


@pytest.mark.parametrize("attested", ["flag", None])
def test_every_scope_state_says_it_covers_one_command_only(tmp_path, attested):
    answered, checkout = _identical_pair(tmp_path)
    _, message = _line(_provenance(answered, checkout, attested=attested), SCOPE)
    assert SESSION_CAVEAT in message, message


def test_scope_disagreement_state_also_says_it(tmp_path):
    answered, checkout = _identical_pair(tmp_path)
    lines = doctor.plugin_provenance(
        answered, checkout, attested=tmp_path / "elsewhere", attested_source="--plugin-root"
    )
    _, message = _line(lines, SCOPE)
    assert SESSION_CAVEAT in message, message


def test_the_environment_is_named_when_it_is_what_attested(tmp_path):
    answered, checkout = _identical_pair(tmp_path)
    lines = doctor.plugin_provenance(
        answered, checkout, attested=answered, attested_source="CLAUDE_PLUGIN_ROOT"
    )
    level, message = _line(lines, SCOPE)
    assert level == "OK", message
    assert "CLAUDE_PLUGIN_ROOT" in message, message


# --------------------------------------------------------------------------
# The attestation source, and the contract.
# --------------------------------------------------------------------------


def test_the_flag_wins_over_the_environment():
    assert doctor.plugin_attestation("/flag", "/env") == (Path("/flag"), "--plugin-root")
    assert doctor.plugin_attestation(None, "/env") == (Path("/env"), "CLAUDE_PLUGIN_ROOT")
    assert doctor.plugin_attestation(None, None) == (None, None)
    assert doctor.plugin_attestation(None, "") == (None, None)


def test_parse_args_carries_plugin_root_and_never_raises():
    root, plugin_root, problems = doctor.parse_args(["--root", "x", "--plugin-root", "y"])
    assert (root, plugin_root, problems) == ("x", "y", [])
    root, plugin_root, problems = doctor.parse_args(["--nonsense"])
    assert (root, plugin_root) == (None, None)
    assert problems


def test_main_still_exits_zero_with_one_verdict_and_prints_the_new_lines(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.delenv("SUPERTOOL_WATCH_NAME", raising=False)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)

    assert doctor.main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    lines = out.rstrip().splitlines()
    assert lines[-1].startswith("VERDICT: "), out
    assert sum(1 for line in lines if line.startswith("VERDICT: ")) == 1, out
    assert any(SCOPE in line for line in lines), out
    assert any(COPY in line for line in lines), out


def test_a_plugin_root_that_does_not_exist_still_produces_both_lines(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)

    assert doctor.main(["--root", str(tmp_path), "--plugin-root", str(tmp_path / "nope")]) == 0
    out = capsys.readouterr().out
    assert SCOPE in out, out
    assert COPY in out, out
    assert out.rstrip().splitlines()[-1].startswith("VERDICT: ")
