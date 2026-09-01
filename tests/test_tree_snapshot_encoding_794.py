"""`tree_snapshot.py`'s CLI must survive a console that cannot encode what it
is printing (#794).

It is the delta's new CLI and the only one of eight that does not reconfigure
its streams to `backslashreplace` -- `lane_setup.py`, `release_delta.py`,
`scaffold.py`, `checklist_skew.py`, `ranking_table.py`, `release_version.py`
and `rename_changelog_fragment.py` all do. On a console whose codepage cannot
encode a character in the VERDICT line -- cp1252, Windows' default for a
**piped** stdout, which is how an agent runs this -- the bare `print` at line
301 raises `UnicodeEncodeError` and the process dies at **exit 1**, which is
this module's own `EXIT_CODES["mutated"]`. So a clean tree, and worse, a
`could-not-compare` tree (exit 3) -- the third state that is this module's
entire reason for existing -- both read back as `mutated`.

A verdict's `added`/`removed` lists come straight from `git status
--porcelain`'s own paths, so a status line naming a file with a character
outside the console's codepage is not a contrived input: it is an ordinary
untracked filename.

Every assertion here is paired: the fixture is confirmed to bite before
anything is concluded from surviving it, the same shape
`test_scaffold_show_console_encoding_702.py` uses for the same class of bug.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import spawn_guard  # noqa: E402

TREE_SNAPSHOT = REPO_ROOT / "scripts" / "tree_snapshot.py"

#: The character actually named in the issue's own reproduction. Written as a
#: codepoint escape rather than pasted, so this file stays ASCII and cannot
#: itself become an instance of the bug it tests.
GLYPH = "\u21a5"

CP1252_ENV = {"PYTHONIOENCODING": "cp1252"}


def _child(argv, extra_env=None, *, cwd=None, subject):
    env = dict(os.environ)
    env.update(extra_env or {})
    return spawn_guard.run(
        [sys.executable] + list(argv),
        subject=subject,
        capture_output=True,
        text=True,
        errors="replace",
        env=env,
        cwd=cwd,
        timeout=60,
    )


def _fixture_bites():
    """`(established, why)` -- does a child told to use cp1252 really refuse GLYPH?

    A measurement, never a given: if this platform's cp1252 happens to accept
    the character, or `PYTHONIOENCODING` is ignored, a survival below proves
    nothing at all.
    """
    probe = _child(
        ["-c", "import sys; sys.stdout.write({0!r})".format(GLYPH)],
        CP1252_ENV,
        subject="whether a cp1252 child really refuses this glyph",
    )
    if probe.returncode != 0 and "UnicodeEncodeError" in (probe.stderr or ""):
        return True, ""
    return False, (
        "a child run with PYTHONIOENCODING=cp1252 wrote the glyph without dying "
        "(exit {0}, stderr {1!r}), so this platform cannot establish the "
        "condition the fix is for".format(probe.returncode, (probe.stderr or "")[:200])
    )


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@example.com"], root)
    _git(["config", "user.name", "t"], root)
    (root / "seed.txt").write_text("seed", encoding="utf-8")
    _git(["add", "seed.txt"], root)
    _git(["commit", "-q", "-m", "seed"], root)
    return root


# --- the code-level half: static, runs on every platform ---------------------


def test_the_fix_is_present_in_the_entry_point():
    """The one static half. A subprocess assertion that skips on a platform
    where the fixture does not bite would otherwise leave nothing at all
    checked there.
    """
    source = TREE_SNAPSHOT.read_text(encoding="utf-8")
    assert 'stream.reconfigure(errors="backslashreplace")' in source, (
        "scripts/tree_snapshot.py prints a VERDICT line carrying arbitrary git "
        "status paths and does not reconfigure its streams, so a console "
        "codepage that cannot encode one of them kills the command at the "
        "print with exit 1 -- EXIT_CODES['mutated'] -- masking clean and "
        "could-not-compare alike (#794)"
    )


# --- the control and the real assertion, in one fixture -----------------------


def test_control_the_cp1252_fixture_really_does_kill_a_bare_write():
    """Must fire. Without this, the subprocess assertion below passes just as
    happily on a platform where `PYTHONIOENCODING` was ignored -- a green
    tick over a condition that was never established.
    """
    established, why = _fixture_bites()
    if not established:
        pytest.skip(
            why + " -- what goes untested here is the whole of this file's "
            "subprocess half"
        )
    assert established


def test_compare_survives_a_console_that_cannot_encode_a_mutated_verdict(tmp_path):
    """The `mutated` path: an untracked filename carrying `GLYPH`.

    Not the crash the fix is really for -- git's default `core.quotePath=true`
    octal-escapes a non-ASCII byte in `git status --porcelain`'s own output,
    so this particular verdict line is pure ASCII by the time it reaches
    `print`. Kept anyway, as the positive control the brief asks for: it
    proves the reconfigured stream does not merely avoid the crash by
    accident of this fixture never exercising it, and it must still exit
    `EXIT_CODES["mutated"]` (1) for a genuinely mutated tree either way.
    """
    established, why = _fixture_bites()
    if not established:
        pytest.skip(
            why + " -- so whether the mutated VERDICT print survives such a "
            "console went unmeasured"
        )
    root = _repo(tmp_path)
    before_path = root / "before.json"
    snap = _child(
        [str(TREE_SNAPSHOT), "snapshot", "--root", str(root)],
        subject="taking the before-snapshot",
    )
    assert snap.returncode == 0, (snap.returncode, snap.stdout, snap.stderr)
    before_path.write_text(snap.stdout, encoding="utf-8")

    (root / (GLYPH + ".txt")).write_text("new", encoding="utf-8")

    done = _child(
        [
            str(TREE_SNAPSHOT), "compare",
            "--before", str(before_path),
            "--root", str(root),
        ],
        CP1252_ENV,
        subject="whether compare's VERDICT print survives a cp1252 console "
        "for a mutated tree",
    )
    assert "UnicodeEncodeError" not in (done.stderr or ""), (
        "tree_snapshot.py compare died encoding its own VERDICT line: "
        "{0}".format((done.stderr or "")[-400:])
    )
    assert done.returncode == 1, (
        "expected EXIT_CODES['mutated'] (1) for a genuinely mutated tree, "
        "got {0}: stdout={1!r} stderr={2!r}".format(
            done.returncode, done.stdout[-400:], done.stderr[-400:]
        )
    )
    assert "VERDICT: mutated" in done.stdout, done.stdout


def test_compare_survives_a_console_that_cannot_encode_a_could_not_compare_verdict(
    tmp_path,
):
    """The reproduction the issue actually names: `_run_git`'s error string
    embeds git's own stderr, which is localised, so a non-English git install
    can put an arbitrary character into a `could-not-compare` reason with no
    special `core.quotePath` setting at all. Reproduced deterministically here
    by handing `compare` a before-snapshot whose own `error` field already
    carries `GLYPH` -- the exact shape `_read_before` would hand back from a
    localised git failure -- rather than depending on a locale being
    installed on the machine running this suite.

    This is the sharper of the two cases: #794's own point is that a crash
    here is indistinguishable from `mutated` (exit 1), destroying the very
    state -- `could-not-compare`, exit 3 -- this module exists to keep
    separate from a clean tree.
    """
    established, why = _fixture_bites()
    if not established:
        pytest.skip(
            why + " -- so whether the could-not-compare VERDICT print "
            "survives such a console went unmeasured"
        )
    root = _repo(tmp_path)
    before_path = root / "before.json"
    before_path.write_text(
        json.dumps({"root": ".", "head": None, "status": None, "error": GLYPH}),
        encoding="utf-8",
    )

    done = _child(
        [
            str(TREE_SNAPSHOT), "compare",
            "--before", str(before_path),
            "--root", str(root),
        ],
        CP1252_ENV,
        subject="whether compare's VERDICT print survives a cp1252 console "
        "for a could-not-compare verdict",
    )
    assert "UnicodeEncodeError" not in (done.stderr or ""), (
        "tree_snapshot.py compare died encoding its own VERDICT line: "
        "{0}".format((done.stderr or "")[-400:])
    )
    assert done.returncode == 3, (
        "expected EXIT_CODES['could-not-compare'] (3), got {0} -- a crash "
        "here would exit 1, the same code as 'mutated' (#794): "
        "stdout={1!r} stderr={2!r}".format(
            done.returncode, done.stdout[-400:], done.stderr[-400:]
        )
    )
    assert "VERDICT: could-not-compare" in done.stdout, done.stdout
