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

import hashlib
import json
import os
import stat
import sys
import threading
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
    """A tree of the shape this check compares. `contract` is the thing that moves.

    Every file is written as BYTES with LF endings, never `write_text`. Text mode uses
    `newline=None`, which translates to CRLF on Windows -- and then
    `test_line_endings_alone_are_not_reported_as_a_skew`, which writes CRLF into the
    other side, would be writing the bytes that were already there. Deleting the
    normalisation from the code under test would leave all four Windows legs green:
    coverage reported and not had, on the leg nobody re-reads.
    """
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "plugin.json").write_bytes(
        (json.dumps({"name": name, "version": version}) + "\n").encode("utf-8")
    )
    for sub in ("agents", "commands", "skills", "scripts"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "commands" / "doctor.md").write_bytes(b"run the diagnostic\n")
    (root / "skills" / "manager.md").write_bytes(b"the loop\n")
    (root / "agents" / "developer.md").write_bytes(b"one issue\n")
    (root / "scripts" / "report_schema.py").write_bytes(
        "SCHEMA_VERSION = {}\n".format(contract).encode("utf-8")
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
    # The three assertions above are ALL satisfied by the SKEW branch, which appends
    # the same sentence -- so without these two this test passes against the very bug
    # it is named for. Two byte-identical trees with one unreadable file are UNKNOWN,
    # not different, and the branch this test exists for is the one that says so.
    assert "SKEW" not in message, message
    assert "could not be answered" in message, message


def test_an_unreadable_file_is_not_counted_into_a_real_difference(tmp_path):
    """The must-fire beside it: a genuine difference elsewhere is still a SKEW, and the
    unreadable path is not counted into the tally.
    """
    answered, checkout = _identical_pair(tmp_path)
    (checkout / "skills" / "manager.md").write_text("the loop, revised\n", encoding="utf-8")
    victim = checkout / "scripts" / "report_schema.py"
    if not _deny_read(victim):
        pytest.skip(
            "the mode bit did not deny a read on this platform/filesystem; whether an "
            "unreadable path is counted into a real skew went untested here"
        )
    try:
        level, message = _line(_provenance(answered, checkout), COPY)
    finally:
        os.chmod(str(victim), stat.S_IRUSR | stat.S_IWUSR)

    assert level == "WARN", message
    assert "SKEW" in message, message
    assert "differ in 1 of" in message, message
    assert "skills/manager.md" in message, message
    assert "could not be read" in message, message


def test_a_symlinked_compared_directory_is_declined_rather_than_followed(tmp_path):
    """`os.walk` always traverses the top it is given, symlink or not, so a tracked
    `scripts -> /` would be an unbounded read inside a diagnostic contracted to finish.
    """
    answered, checkout = _identical_pair(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("not ours\n", encoding="utf-8")
    victim = checkout / "scripts"
    for entry in victim.iterdir():
        entry.unlink()
    victim.rmdir()
    try:
        victim.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(
            "symlink refused ({}); the declined-symlink branch went untested".format(exc)
        )

    level, message = _line(_provenance(answered, checkout), COPY)
    assert level == "WARN", message
    assert "symlink" in message, message
    assert "secret.txt" not in message, message


def test_a_symlinked_file_inside_a_compared_directory_is_declined_too(tmp_path):
    """#279. The decline covered the top of the tree and nothing under it.

    `os.walk` refuses symlinked *sub*directories and never sees a symlinked *file* as
    anything but an ordinary entry in `filenames`, and `read_bytes()` follows it. So a
    tracked `agents/leaked.md -> /etc/passwd` had its bytes folded into the digest, and
    `unreadable` stayed empty -- a receipt byte-identical to a tree that had no symlink
    in it at all, which is this repository's own defect class.

    Declining rather than resolving-and-containment-checking is the choice here, argued
    in `plugin_tree_digest`'s docstring. The cost is asserted rather than hidden: a
    symlinked file inside the tree is *unknown*, and this test requires it to say so.

    Two must-fire halves in the same fixture, because "not in files" is what a digest
    that read nothing also prints: the ordinary file beside it is hashed, and the
    identity line reports that the scan was partial.
    """
    tree = _plugin_tree(tmp_path / "tree")
    outside = tmp_path / "outside" / "secret.txt"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"not ours\n")
    (tree / "agents" / "real.md").write_bytes(b"ours\n")
    victim = tree / "agents" / "leaked.md"
    try:
        victim.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(
            "symlink to a file refused ({}); whether a symlinked FILE is declined, and "
            "whether it lands in `unreadable`, both went untested here".format(exc)
        )
    assert os.path.islink(str(victim)), "the symlink fixture did not take"

    files, unreadable = doctor.plugin_tree_digest(tree)

    assert "agents/real.md" in files, files
    assert "agents/leaked.md" not in files, files
    assert "agents/leaked.md" in unreadable, unreadable
    assert "symlink" in unreadable["agents/leaked.md"], unreadable
    outside_digest = hashlib.sha256(outside.read_bytes()).hexdigest()
    assert outside_digest not in files.values(), files
    assert "could not be read" in doctor._tree_identity(tree, files, unreadable)


def test_a_non_regular_file_is_declined_rather_than_opened(tmp_path):
    """#279's worse half, and a separate decision: a FIFO with no symlink involved.

    Opening a FIFO with no writer blocks forever, so `read_bytes()` never returned and
    the diagnostic's *exit 0 always, one VERDICT line* contract was unreachable -- from
    inside a launcher that runs it before every session with no timeout.

    The guard is `os.lstat` before the open, which neither follows nor blocks. The hang
    is asserted against rather than reasoned about: the call runs in a daemon thread and
    the thread must finish. A test that only checked the return value would pass by
    hanging the suite instead.
    """
    tree = _plugin_tree(tmp_path / "tree")
    victim = tree / "commands" / "pipe.md"
    if not hasattr(os, "mkfifo"):
        pytest.skip(
            "os.mkfifo does not exist on this platform, so whether a non-regular file "
            "is declined rather than opened went untested here"
        )
    try:
        os.mkfifo(str(victim))
    except (OSError, NotImplementedError) as exc:
        pytest.skip(
            "mkfifo refused ({}); whether a non-regular file is declined rather than "
            "opened went untested here".format(exc)
        )
    assert stat.S_ISFIFO(os.lstat(str(victim)).st_mode), "the FIFO fixture did not take"

    outcome = {}

    def run():
        outcome["result"] = doctor.plugin_tree_digest(tree)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(20)
    assert not worker.is_alive(), (
        "plugin_tree_digest did not return within 20s -- it opened the FIFO (#279)"
    )

    files, unreadable = outcome["result"]
    # Must-fire beside it: the ordinary files in the same tree were still read.
    assert "commands/doctor.md" in files, files
    assert "commands/pipe.md" not in files, files
    assert "commands/pipe.md" in unreadable, unreadable
    assert "regular file" in unreadable["commands/pipe.md"], unreadable


def test_a_symlinked_ancestor_of_a_compared_file_is_declined_too(tmp_path):
    """The same containment hole one level up, found while fixing #279.

    `os.lstat` refuses a symlinked leaf and refuses nothing above it, so
    `.claude-plugin -> /elsewhere` still had its manifest read from outside the tree.
    The compared *directories* need no equivalent: their tops are checked before the
    walk and `os.walk` declines symlinked subdirectories itself.

    Must-fire in the same fixture: everything else in the tree is still hashed, so this
    cannot pass against a digest that read nothing.
    """
    tree = _plugin_tree(tmp_path / "tree")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "plugin.json").write_bytes(b'{"name": "not-ours", "version": "9.9.9"}\n')
    victim = tree / ".claude-plugin"
    (victim / "plugin.json").unlink()
    victim.rmdir()
    try:
        victim.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(
            "symlink refused ({}); whether a symlinked ANCESTOR of a compared file is "
            "declined went untested here".format(exc)
        )
    assert os.path.islink(str(victim)), "the symlink fixture did not take"

    files, unreadable = doctor.plugin_tree_digest(tree)

    assert "agents/developer.md" in files, files
    assert ".claude-plugin/plugin.json" not in files, files
    assert ".claude-plugin/plugin.json" in unreadable, unreadable
    assert "symlink" in unreadable[".claude-plugin/plugin.json"], unreadable
    outside_digest = hashlib.sha256((outside / "plugin.json").read_bytes()).hexdigest()
    assert outside_digest not in files.values(), files


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
    monkeypatch.setattr(doctor.shutil, "which", lambda name, **kwargs: None)

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
    monkeypatch.setattr(doctor.shutil, "which", lambda name, **kwargs: None)

    assert doctor.main(["--root", str(tmp_path), "--plugin-root", str(tmp_path / "nope")]) == 0
    out = capsys.readouterr().out
    assert SCOPE in out, out
    assert COPY in out, out
    assert out.rstrip().splitlines()[-1].startswith("VERDICT: ")
