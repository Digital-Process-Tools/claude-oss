"""Two defects filed together (#1346), plus two the self-review round on the
same fix caught before it shipped.

1. `--mark-stale` exited 0 and printed nothing whether the board was actually
   marked stale or `repo_config(root).get("repo")` failed to resolve a repo --
   the same absence-vs-clean-pass shape this whole plugin is named after.
   `commands/triage.md` makes `--mark-stale` a mandatory end-of-sweep step, but
   an orchestrating session reading only the exit code cannot tell "marked" from
   "silently did nothing" -- both are exit 0, no output.

2. `--root` as the final token on the command line raised `IndexError`:
   ``argv[argv.index("--root") + 1]`` with nothing after it. Both `--mark-stale`
   and `--refresh` parsed `--root` this same broken way, independently, so the
   fix is one small helper (`_arg_value`) used by both call sites rather than a
   second hand-rolled parse.

3. The first version of the fix printed "marked X stale" unconditionally once a
   repo resolved, discarding `mark_board_stale`'s own return value -- so a real
   write failure (permission denied, unwritable cache dir) still printed
   "marked" and still exited 0, the identical absence-vs-success collapse one
   level down. Now the receipt reads the return value.

4. The receipt interpolates a repo slug or a `--root` path straight into
   `print()`; on Windows the console encodes stdout with its own codepage
   rather than the source encoding, so a non-ASCII path could otherwise raise
   `UnicodeEncodeError` after the work it reports had already happened. The
   `--mark-stale` branch now reconfigures stdout/stderr with
   ``errors="backslashreplace"`` first, the same idiom `lane_setup.py`'s CLI
   entry point already uses.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


# ------------------------------------------------------------- --mark-stale receipt


def test_mark_stale_prints_marked_receipt_when_repo_resolves(monkeypatch, capsys):
    """Must-fire: a repo that resolves gets marked, and the receipt says so."""
    calls = []

    def _mark(repo):
        calls.append(repo)
        return True

    monkeypatch.setattr(statusline, "repo_config", lambda root: {"repo": "org/repo"})
    monkeypatch.setattr(statusline, "mark_board_stale", _mark)

    rc = statusline.main(["--mark-stale"])

    assert rc == 0
    assert calls == ["org/repo"]
    out = capsys.readouterr().out
    assert "marked" in out.lower()
    assert "org/repo" in out
    assert "not marked" not in out.lower()


def test_mark_stale_prints_not_marked_receipt_when_no_repo(monkeypatch, capsys):
    """Must-fire, the paired negative: no resolvable repo means nothing is marked,
    and the receipt must say so rather than staying silent like the marked case."""
    calls = []
    monkeypatch.setattr(statusline, "repo_config", lambda root: {})
    monkeypatch.setattr(statusline, "mark_board_stale", lambda repo: calls.append(repo))

    rc = statusline.main(["--mark-stale"])

    assert rc == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "not marked" in out.lower()
    assert "no repo resolved" in out.lower()


def test_mark_stale_prints_not_marked_receipt_when_write_fails(monkeypatch, capsys):
    """Must-fire, a third case the self-review round added: a repo resolves but
    `mark_board_stale` itself fails (silent-on-failure by design, per its own
    docstring) -- the receipt must say "not marked" here too, not "marked",
    or a real write failure prints exactly like a real success."""
    monkeypatch.setattr(statusline, "repo_config", lambda root: {"repo": "org/repo"})
    monkeypatch.setattr(statusline, "mark_board_stale", lambda repo: False)

    rc = statusline.main(["--mark-stale"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "not marked" in out.lower()
    assert "org/repo" in out


def test_mark_stale_still_returns_0_and_calls_mark_board_stale_currently_working_case(
    monkeypatch,
):
    """Must-not-regress: the previously-working path (repo present, mark
    succeeds) must keep calling mark_board_stale and keep exiting 0."""
    calls = []

    def _mark(repo):
        calls.append(repo)
        return True

    monkeypatch.setattr(statusline, "repo_config", lambda root: {"repo": "org/repo"})
    monkeypatch.setattr(statusline, "mark_board_stale", _mark)

    rc = statusline.main(["--mark-stale", "--root", "."])

    assert rc == 0
    assert calls == ["org/repo"]


def test_mark_stale_reconfigures_streams_to_survive_a_hostile_codepage(
    monkeypatch, capsys
):
    """The receipt must not crash when the console cannot encode the repo slug
    or root path directly -- `reconfigure(errors="backslashreplace")` is what
    keeps a non-ASCII value from raising `UnicodeEncodeError` on Windows."""
    calls = []

    class _Stream:
        def __init__(self):
            self.reconfigured_with = None
            self.written = []

        def reconfigure(self, errors=None):
            self.reconfigured_with = errors
            calls.append(errors)

        def write(self, s):
            self.written.append(s)

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stdout", _Stream())
    monkeypatch.setattr(sys, "stderr", _Stream())
    monkeypatch.setattr(statusline, "repo_config", lambda root: {"repo": "org/repo"})
    monkeypatch.setattr(statusline, "mark_board_stale", lambda repo: True)

    rc = statusline.main(["--mark-stale"])

    assert rc == 0
    assert calls == ["backslashreplace", "backslashreplace"]


def test_mark_stale_survives_a_stream_with_no_reconfigure_method(monkeypatch):
    """Must-not-regress: a stream too old to carry `reconfigure` (pre-3.7, or a
    test double) must not turn the receipt path itself into a crash."""

    class _NoReconfigure:
        def write(self, s):
            pass

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stdout", _NoReconfigure())
    monkeypatch.setattr(sys, "stderr", _NoReconfigure())
    monkeypatch.setattr(statusline, "repo_config", lambda root: {"repo": "org/repo"})
    monkeypatch.setattr(statusline, "mark_board_stale", lambda repo: True)

    rc = statusline.main(["--mark-stale"])

    assert rc == 0


# ------------------------------------------------------------------- --root parsing


def test_mark_stale_root_as_last_argument_does_not_raise(monkeypatch):
    seen = []
    monkeypatch.setattr(statusline, "repo_config", lambda root: seen.append(root) or {})
    monkeypatch.setattr(statusline, "mark_board_stale", lambda repo: None)

    rc = statusline.main(["--mark-stale", "--root"])

    assert rc == 0
    assert seen == ["."]


def test_refresh_root_as_last_argument_does_not_raise(monkeypatch, tmp_path):
    monkeypatch.setattr(statusline, "refresh", lambda root, session_id=None: None)
    monkeypatch.setattr(statusline, "repo_config", lambda root: {})
    monkeypatch.setattr(
        statusline, "_lock_path", lambda repo: tmp_path / "does-not-exist.lock"
    )

    rc = statusline.main(["--refresh", "--root"])

    assert rc == 0
