"""#582: does the supertool that resolves here carry the ops this plugin's own
shipped text names?

`doctor.py` already answers *is supertool on PATH* (`check_tool`) and *is
`./supertool` the right entry point* (`check_supertool_entry_point`). Neither
answers the question this file covers, and the two failure modes are different:
the plugin and the supertool carrying its ops are two separately released
artifacts on two clocks, so an `oss` release naming an op the installed
supertool predates fails mid-tick, at the step that needed it, with nobody
having asked first.

The three states are the whole point, and the third is the one this repository
is named after: `present`, `missing`, and **`could-not-ask`** -- the roster call
itself did not answer. A `could-not-ask` rendered as `present` is a confident
answer to a question nobody put.

Every negative assertion here is paired with a positive control in the same
fixture: a fixture that produces no ops at all would satisfy "this op is not
reported missing" without exercising anything.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import doctor  # noqa: E402
import doctor_check_supertool_ops as ops_check  # noqa: E402
import spawn_guard  # noqa: E402


# --- fixtures ---------------------------------------------------------------


def _plugin_tree(root, files):
    """Write `{relative path: text}` under `root` and return `root`."""
    for rel, text in files.items():
        target = Path(root) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return Path(root)


def _roster_text(names):
    """A roster output shaped like the real one: prose, then an indented block
    of whitespace-separated op names carrying their safety class."""
    return (
        "## Ops\n"
        "\n"
        "Every op loaded here, and nothing else -- the complete list.\n"
        "\n"
        "- unmarked -- read-only. Call it blind.\n"
        "- `*` -- writes files in this tree.\n"
        "\n"
        "> 14 shipped presets (bluesky, claims) are not loaded here.\n"
        "\n"
        "  " + " ".join(names) + "\n"
    )


class _Completed(object):
    def __init__(self, returncode=0, stdout=b""):
        self.returncode = returncode
        self.stdout = stdout


def _run_answering(text, returncode=0):
    def run(argv, **kwargs):
        return _Completed(returncode, text.encode("utf-8"))

    return run


def _which_finding(path="/usr/local/bin/supertool"):
    return lambda name: path


def _capture(monkeypatch):
    """Collect `(state, message)` pairs `doctor.report` emits, without printing."""
    seen = []
    monkeypatch.setattr(doctor, "report", lambda state, message: seen.append((state, message)))
    return seen


# --- deriving the expected set from the shipped text ------------------------


def test_op_names_are_derived_from_the_shipped_command_and_skill_text(tmp_path):
    """The expected set comes from the text, never from a constant beside the
    check -- a constant goes silently narrower than its subject the moment
    somebody adds a call (#547's shape, which is why #582 asks for this)."""
    root = _plugin_tree(
        tmp_path,
        {
            "commands/tick.md": "   supertool 'gh-prs' 'gh-issues:per=100' 'gh-branch'\n",
            "skills/manager/SKILL.md": "run `supertool 'radar:--state'` first\n",
            "agents/developer.md": "- `./supertool 'edit:@-'` with a heredoc\n",
        },
    )
    named, roots = ops_check.named_ops(root)
    assert set(named) == {"gh-prs", "gh-issues", "gh-branch", "radar", "edit"}, (
        "every op named by a call in the shipped text must be derived, including "
        "the second and third argument of a multi-op call; got {!r}".format(sorted(named))
    )
    assert {r[0] for r in roots} == set(ops_check.OP_TEXT_ROOTS)
    assert all(r[1] == "read" for r in roots), roots
    assert named["gh-issues"] == ["commands/tick.md"], (
        "each derived op must name the file it was read out of, so a `missing` "
        "finding can point at the call that will break"
    )


def test_prose_naming_an_op_that_is_not_a_call_is_not_derived(tmp_path):
    """The positive control for the negative: the same fixture carries one word
    that must NOT be derived and one call that must be. A derivation that found
    nothing at all would pass the first assertion alone."""
    root = _plugin_tree(
        tmp_path,
        {
            "commands/tick.md": (
                "The op is `write`, and `op1`/`op2` are placeholders.\n"
                "python3 supertool.py 'not-a-call'\n"
                "supertool 'gh-prs'\n"
            ),
        },
    )
    named, _roots = ops_check.named_ops(root)
    assert "write" not in named, (
        "a bare word in prose is not a supertool call and must not be derived -- "
        "measured on this repository, where a whole-tree scan derived `write`, "
        "`op1` and `op2` out of CHANGELOG.md alone"
    )
    assert "op1" not in named and "op2" not in named
    assert "not-a-call" not in named, (
        "`supertool.py` is a filename, not the command; the word boundary must hold"
    )
    assert "gh-prs" in named, (
        "positive control: the real call in the same fixture must still be derived, "
        "or the three assertions above pass over a derivation that found nothing"
    )


@pytest.mark.must_assert_on("linux")
def test_an_unreadable_source_root_is_reported_as_unreadable_not_as_no_ops(tmp_path):
    """A root the walk could not enter must never render as a root with no calls
    in it -- that is an absence produced by the tool, read as an absence in the
    world."""
    root = _plugin_tree(
        tmp_path,
        {
            "commands/tick.md": "supertool 'gh-prs'\n",
            "agents/developer.md": "supertool 'edit:@-'\n",
        },
    )
    denied = root / "agents"
    try:
        os.chmod(str(denied), 0o000)
    except OSError as exc:
        pytest.skip(
            "os.chmod would not set mode 000 ({}); what went untested is whether "
            "an unreadable source root is reported rather than silently empty".format(exc)
        )
    try:
        if os.access(str(denied), os.R_OK):
            pytest.skip(
                "this process can read a 0o000 directory (root, or a filesystem "
                "without POSIX modes); what went untested is whether an unreadable "
                "source root is reported rather than silently empty"
            )
        try:
            os.listdir(str(denied))
        except OSError:
            pass
        else:
            pytest.skip(
                "the deny did not take -- os.listdir still succeeded on the 0o000 "
                "directory; what went untested is whether an unreadable source root "
                "is reported rather than silently empty"
            )
        named, roots = ops_check.named_ops(root)
        states = dict((name, state) for name, state, _detail in roots)
        assert states["agents"] == "unreadable", (
            "a denied root must report `unreadable`; got {!r}".format(states)
        )
        assert states["commands"] == "read", (
            "positive control: the readable root in the same fixture must still "
            "report `read`, or the assertion above is about a broken fixture"
        )
        assert "gh-prs" in named
    finally:
        os.chmod(str(denied), 0o700)


def test_a_missing_source_root_is_absent_not_unreadable(tmp_path):
    root = _plugin_tree(tmp_path, {"commands/tick.md": "supertool 'gh-prs'\n"})
    _named, roots = ops_check.named_ops(root)
    states = dict((name, state) for name, state, _detail in roots)
    assert states["agents"] == "absent", states
    assert states["commands"] == "read", states


# --- asking the resolved supertool ------------------------------------------


def test_the_roster_is_parsed_into_op_names_without_their_safety_class():
    parsed = ops_check.parse_roster(_roster_text(["gh-prs", "paste*", "radar!", "ops"]))
    assert parsed == {"gh-prs", "paste", "radar", "ops"}, (
        "the class markers `*` and `!` are supertool's own annotation, not part "
        "of the op name; got {!r}".format(sorted(parsed))
    )


def test_roster_prose_is_not_parsed_as_op_names():
    """Positive control in the same fixture: the block of real names must still
    parse, or "no prose leaked in" is satisfied by parsing nothing at all."""
    parsed = ops_check.parse_roster(_roster_text(["gh-prs", "ops"]))
    assert "unmarked" not in parsed and "shipped" not in parsed and "presets" not in parsed
    assert parsed == {"gh-prs", "ops"}


def test_a_roster_that_does_not_list_the_op_used_to_ask_it_is_could_not_ask():
    """The parse carries its own positive control into the product code: the
    roster is fetched by running an op, so that op must appear in what came
    back. If it does not, the output was not understood -- and an output that
    was not understood must not be reported as a complete inventory."""
    state, available, detail = ops_check.supertool_roster(
        run=_run_answering("nothing here looks like a roster at all\n"),
        which=_which_finding(),
    )
    assert state == "could-not-ask", (state, sorted(available), detail)
    assert ops_check.ROSTER_OP.split(":")[0] in detail

    state, available, _detail = ops_check.supertool_roster(
        run=_run_answering(_roster_text(["gh-prs", "ops"])), which=_which_finding()
    )
    assert state == "read", "positive control: a roster carrying the control op reads"
    assert available == {"gh-prs", "ops"}


def test_prose_shaped_like_a_roster_block_is_not_read_as_one():
    """A reviewer finding on this diff, and it defeated the control the module
    claims to carry. Lowercase English with no punctuation matches the op-name
    token shape exactly, and the word `ops` is the control token itself -- so an
    indented banner mentioning ops parsed as a complete inventory of English
    words. The block now has to carry at least one token no sentence produces.
    """
    banner = (
        "supertool: unrecognized configuration, falling back to defaults\n"
        "\n"
        "  usage information for ops and other legacy commands is deprecated\n"
        "  please update your config to continue using this tool safely\n"
    )
    assert ops_check.parse_roster(banner) == set(), ops_check.parse_roster(banner)

    state, available, detail = ops_check.supertool_roster(
        run=_run_answering(banner), which=_which_finding()
    )
    assert state == "could-not-ask", (state, sorted(available), detail)

    # Positive control in the same fixture: a real-shaped roster must still read,
    # or "prose is rejected" is satisfied by a parse that rejects everything.
    state, available, _detail = ops_check.supertool_roster(
        run=_run_answering(_roster_text(["gh-prs", "ops"])), which=_which_finding()
    )
    assert state == "read" and available == {"gh-prs", "ops"}


def test_an_unquoted_call_is_derived_and_a_sentence_is_not(tmp_path):
    """An auditor finding on this diff: the derivation only saw quoted arguments,
    so `supertool ops:roster` written bare -- which this diff itself added to
    `commands/doctor.md` -- contributed nothing and was indistinguishable from an
    op nobody names.

    The must-not-fire half is the reason the bare form requires a colon. Measured
    across `commands/`, `skills/` and `agents/`: with the colon required, exactly
    one bare call is derived and it is the real one; without it, eighteen English
    words are, because `the supertool that answers here` is a sentence.
    """
    root = _plugin_tree(
        tmp_path,
        {
            "commands/doctor.md": (
                "One real subprocess per run (`supertool ops:roster`), from the\n"
                "directory being diagnosed. Whether the supertool that answers\n"
                "here carries them is what this line is for.\n"
            ),
        },
    )
    named, _roots = ops_check.named_ops(root)
    assert "ops" in named, (
        "an unquoted `supertool ops:roster` names an op and must be derived; "
        "got {!r}".format(sorted(named))
    )
    for word in ("that", "answers", "here", "supertool"):
        assert word not in named, (
            "{!r} came out of an ordinary sentence, not a call: {!r}".format(
                word, sorted(named)
            )
        )
    assert set(named) == {"ops"}, sorted(named)


def test_a_hyphen_before_the_command_is_not_a_call(tmp_path):
    """The other half of the same reviewer finding: a bare word boundary is
    satisfied by a hyphen, so `not-supertool 'fake-op'` in prose derived an op
    nobody calls -- and the roster would correctly not carry it, producing a
    `missing` line naming a call that does not exist."""
    root = _plugin_tree(
        tmp_path,
        {
            "commands/tick.md": (
                "not-supertool 'fake-op' is a decoy\n"
                "supertool 'gh-prs'\n"
            ),
        },
    )
    named, _roots = ops_check.named_ops(root)
    assert "fake-op" not in named, sorted(named)
    assert "gh-prs" in named, (
        "positive control: the real call in the same fixture must still be derived"
    )


def test_supertool_not_on_path_is_could_not_ask():
    state, available, detail = ops_check.supertool_roster(
        run=_run_answering(_roster_text(["git-status", "ops"])), which=lambda name: None
    )
    assert state == "could-not-ask"
    assert available == set()
    assert "PATH" in detail


def test_a_roster_call_that_will_not_run_is_could_not_ask():
    def run(argv, **kwargs):
        raise OSError("Exec format error")

    state, _available, detail = ops_check.supertool_roster(run=run, which=_which_finding())
    assert state == "could-not-ask"
    assert "Exec format error" in detail


def test_a_nonzero_roster_call_is_could_not_ask():
    state, _available, detail = ops_check.supertool_roster(
        run=_run_answering("unknown operation\n", returncode=2), which=_which_finding()
    )
    assert state == "could-not-ask"
    assert "2" in detail


# --- the inventory, in three states -----------------------------------------


def test_present_when_every_named_op_resolves(tmp_path):
    root = _plugin_tree(tmp_path, {"commands/tick.md": "supertool 'gh-prs' 'radar'\n"})
    state, detail = ops_check.supertool_op_inventory(
        plugin_root=root,
        run=_run_answering(_roster_text(["gh-prs", "radar!", "ops"])),
        which=_which_finding(),
    )
    assert state == "present", (state, detail)
    assert "2" in detail, "the count of ops actually checked belongs in the line"


def test_missing_names_each_op_individually_and_where_it_is_called_from(tmp_path):
    root = _plugin_tree(
        tmp_path,
        {
            "commands/tick.md": "supertool 'gh-prs' 'radar'\n",
            "skills/manager/SKILL.md": "supertool 'gl-mr:1'\n",
        },
    )
    state, detail = ops_check.supertool_op_inventory(
        plugin_root=root,
        run=_run_answering(_roster_text(["gh-prs", "ops"])),
        which=_which_finding(),
    )
    assert state == "missing", (state, detail)
    assert "radar" in detail and "gl-mr" in detail, (
        "each missing op is named individually, never counted; got {!r}".format(detail)
    )
    assert "commands/tick.md" in detail.replace(os.sep, "/")
    assert "gh-prs" not in detail, (
        "positive control: an op that DOES resolve must not appear in the missing "
        "list, or `missing` is just naming everything it derived"
    )


def test_could_not_ask_never_renders_as_present(tmp_path):
    root = _plugin_tree(tmp_path, {"commands/tick.md": "supertool 'gh-prs'\n"})
    state, detail = ops_check.supertool_op_inventory(
        plugin_root=root, run=_run_answering(""), which=lambda name: None
    )
    assert state == "could-not-ask", (state, detail)
    assert state != "present"


def test_deriving_no_ops_at_all_is_could_not_ask_not_present(tmp_path):
    """An expected set of zero is vacuously satisfied by any roster. Reporting
    that as `present` is the same defect as reporting an unread roster as one --
    so it is its own could-not-ask, with the reason named."""
    root = Path(tmp_path)
    (root / "commands").mkdir()
    state, detail = ops_check.supertool_op_inventory(
        plugin_root=root,
        run=_run_answering(_roster_text(["gh-prs", "ops"])),
        which=_which_finding(),
    )
    assert state == "could-not-ask", (state, detail)
    assert "no supertool call" in detail, detail
    # The per-root states have to be in the sentence: "read it and found nothing"
    # and "it is not there" are the same empty contribution and not the same fact,
    # and this is the one arm where nothing else in the line separates them.
    assert "commands/: read" in detail, detail
    assert "skills/: absent" in detail and "agents/: absent" in detail, detail


def test_every_source_root_absent_does_not_read_as_a_clean_empty_scan(tmp_path):
    """Positive control for the assertion above, in the opposite direction: with
    no root on disk at all the line must still name all three as absent rather
    than implying three directories were opened and found quiet."""
    state, detail = ops_check.supertool_op_inventory(
        plugin_root=Path(tmp_path) / "not-a-plugin-root",
        run=_run_answering(_roster_text(["gh-prs", "ops"])),
        which=_which_finding(),
    )
    assert state == "could-not-ask", (state, detail)
    for name in ops_check.OP_TEXT_ROOTS:
        assert "{}/: absent".format(name) in detail, detail


# --- the reported line ------------------------------------------------------


def test_the_check_reports_one_line_in_every_state(tmp_path, monkeypatch):
    root = _plugin_tree(tmp_path, {"commands/tick.md": "supertool 'gh-prs'\n"})

    seen = _capture(monkeypatch)
    ops_check.check_supertool_ops(
        plugin_root=root,
        run=_run_answering(_roster_text(["gh-prs", "ops"])),
        which=_which_finding(),
    )
    assert len(seen) == 1 and seen[0][0] == "OK", seen
    present_line = seen[0][1]

    seen = _capture(monkeypatch)
    ops_check.check_supertool_ops(
        plugin_root=root,
        run=_run_answering(_roster_text(["git-status", "ops"])),
        which=_which_finding(),
    )
    assert len(seen) == 1 and seen[0][0] == "WARN", seen
    missing_line = seen[0][1]
    assert "gh-prs" in missing_line

    seen = _capture(monkeypatch)
    ops_check.check_supertool_ops(
        plugin_root=root, run=_run_answering(""), which=lambda name: None
    )
    assert len(seen) == 1 and seen[0][0] == "WARN", seen
    unknown_line = seen[0][1]

    assert unknown_line != present_line and unknown_line != missing_line, (
        "the three states must be distinguishable in the OUTPUT, not only in the "
        "code -- #582's own acceptance criterion"
    )
    assert "unknown" in unknown_line, (
        "the could-not-ask line has to say the answer is unknown; got {!r}".format(unknown_line)
    )
    assert "unknown" not in missing_line, (
        "positive control: a real gap must not be worded as an unknown one"
    )


def test_the_check_never_raises_when_the_plugin_root_is_not_there(tmp_path, monkeypatch):
    """doctor.py's contract is exit 0 always. A check that raises out of `main()`
    takes the VERDICT line with it."""
    seen = _capture(monkeypatch)
    ops_check.check_supertool_ops(
        plugin_root=tmp_path / "does-not-exist",
        run=_run_answering(_roster_text(["git-status", "ops"])),
        which=_which_finding(),
    )
    assert len(seen) == 1 and seen[0][0] == "WARN", seen


# --- against the tree this actually ships -----------------------------------


def test_every_op_this_plugin_names_resolves_in_the_supertool_installed_here():
    """The dogfood assertion. Skipped -- loudly, naming what went untested --
    when the roster could not be asked on this machine, because an inventory
    that could not be read is not evidence that the ops are there."""
    state, available, detail = ops_check.supertool_roster()
    if state != "read":
        pytest.skip(
            "the installed supertool's roster could not be read ({}); what went "
            "untested is whether every op this plugin's shipped text names "
            "resolves here".format(detail)
        )
    named, roots = ops_check.named_ops(REPO_ROOT)
    unreadable = [r for r in roots if r[1] == "unreadable"]
    assert not unreadable, (
        "a source root of this repository could not be read: {!r}".format(unreadable)
    )
    assert named, "this repository's own shipped text names no supertool ops at all"
    missing = sorted(name for name in named if name not in available)
    assert not missing, (
        "this plugin's shipped text names op(s) the supertool installed here does "
        "not carry: {!r} (sources: {!r})".format(
            missing, dict((m, named[m]) for m in missing)
        )
    )


def test_doctor_reexports_the_check_and_names_the_module_by_its_full_path():
    assert doctor.check_supertool_ops is ops_check.check_supertool_ops, (
        "doctor.check_supertool_ops must be a re-export of the one definition, "
        "not a second copy"
    )
    text = (SCRIPTS_DIR / "doctor.py").read_text(encoding="utf-8")
    assert "scripts/doctor_check_supertool_ops.py" in text, (
        "tests/test_unwired_scripts_253.py matches on the full relative path, and "
        "a bare `import` statement does not contain the `.py` suffix"
    )


def test_the_check_runs_inside_the_real_script_entry_point(tmp_path):
    """`main()` calls it, and `doctor.py` run as `__main__` reaches it. Nothing
    a unit test can see: the moved-module alias only exists in that run."""
    completed = spawn_guard.run(
        [sys.executable, str(SCRIPTS_DIR / "doctor.py"), "--root", str(tmp_path)],
        subject="whether the supertool op inventory check runs inside doctor.py's real __main__",
        cwd=str(tmp_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
    )
    output = completed.stdout.decode("utf-8", "replace")
    assert completed.returncode == 0, output
    assert "supertool op inventory:" in output, (
        "the check produced no line at all in a real run:\n{}".format(output)
    )
