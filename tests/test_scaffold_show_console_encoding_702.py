"""`/oss:scaffold --show` must survive a console that cannot encode what it is
printing.

Anything written to stdout is encoded with the **console's** codepage, not the
source file's. On Windows that is typically cp1252, which has no `U+21A5`, no
`U+2191` and no `U+2713` -- so a `print(body)` of a body carrying one of those
raises `UnicodeEncodeError` and kills the command, after the work that print was
reporting has already happened.

Measured through the real CLI on macOS with `PYTHONIOENCODING=cp1252`, at the
commit that introduced the second instance:

    UnicodeEncodeError: 'charmap' codec can't encode character U+21A5
    in position 2334: character maps to <undefined>

(The codepoint is spelled out rather than pasted here for the same reason `GLYPH`
below is an escape: a traceback pytest prints from this file would otherwise carry
the character into the very console that cannot encode it.)

Two bodies are affected and only one of them is new:

- `.oss/statusline.py`, which carries `U+2713` and did so before this change --
  **pre-existing**, and swept into this fix rather than left for a later CI matrix;
- `vocabulary/01-oss/plugin-currency.md`, which #702 made a shipped body. Its
  statusline-marker table is *about* those glyphs, so spelling them out in ASCII
  would gut the table it exists to be.

The fix is this repository's own idiom, already used in `lane_setup.py`,
`release_delta.py`, `release_version.py`, `ranking_table.py` and
`checklist_skew.py`: reconfigure both streams to `backslashreplace` at the top of
`_main`. That is deliberately not `replace`: `backslashreplace` renders the
character visibly as an escape rather than dropping it or substituting a question
mark, so the reader sees something odd instead of silently receiving a body that
differs from the one `--apply` would write. Trading the crash for a quiet
corruption would be the worse fix.

Every assertion here is paired: the fixture is confirmed to bite before anything
is concluded from it surviving, and the test skips carrying what went unmeasured
when it does not.
"""

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import oss_rules  # noqa: E402
import spawn_guard  # noqa: E402

SCAFFOLD = REPO_ROOT / "scripts" / "scaffold.py"

#: The character actually observed killing the CLI. Written as a codepoint escape
#: rather than pasted, so this file stays ASCII and cannot itself become an instance.
GLYPH = "\u21a5"

RULE_PATH = ".claude/jit-context/vocabulary/01-oss/plugin-currency.md"

CP1252_ENV = {"PYTHONIOENCODING": "cp1252"}


def _child(argv, extra_env, subject):
    env = dict(os.environ)
    env.update(extra_env)
    return spawn_guard.run(
        [sys.executable] + list(argv),
        subject=subject,
        capture_output=True,
        text=True,
        errors="replace",
        env=env,
        timeout=60,
    )


def _fixture_bites():
    """`(established, why)` -- does a child told to use cp1252 really refuse GLYPH?

    A measurement, never a given. If the interpreter here ignores
    `PYTHONIOENCODING`, or this platform's cp1252 happens to accept the character,
    then a scaffold run that survives proves nothing at all, and the assertions
    below must skip rather than report coverage they do not have.
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


def _repo(tmp_path):
    (tmp_path / ".oss.json").write_text(
        json.dumps(
            {
                "repo": "acme/widget",
                "default_branch": "main",
                "branch_pattern": "fix/{issue}",
                "test_command": "pytest",
                "version_sites": ["README.md"],
                "changelog_dir": "changelog.d",
                "docs_targets": ["README.md"],
                "labels": {"priority": [], "lanes": []},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / ".oss.local.json").write_text(
        json.dumps({"clone": "/c", "worktree_root": "/w", "state_file": "/s.json"}),
        encoding="utf-8",
    )
    return tmp_path


# --- why the risk exists: pure, runs on every platform -------------------------------


def test_the_shipped_rule_body_carries_a_character_cp1252_has_no_room_for():
    """Not an assumption about Windows: `cp1252` is asked directly. If this ever
    stops holding, the fix below is no longer needed for this body and this test
    says so by failing rather than by quietly passing.
    """
    assert GLYPH in oss_rules.PLUGIN_CURRENCY, "the glyph left the rule body"
    with pytest.raises(UnicodeEncodeError):
        GLYPH.encode("cp1252")


def test_the_fix_is_present_in_the_entry_point_that_prints_bodies():
    """The one static half. A subprocess assertion that skips on a platform where
    the fixture does not bite would otherwise leave nothing at all checked there.
    """
    source = SCAFFOLD.read_text(encoding="utf-8")
    # The call, not the word: the comment beside the fix also spells
    # `backslashreplace`, so a bare substring check would pass on prose alone --
    # a guard that survives the removal of the thing it guards.
    assert 'stream.reconfigure(errors="backslashreplace")' in source, (
        "scripts/scaffold.py prints generated file bodies verbatim and no longer "
        "reconfigures its streams, so a console codepage that cannot encode one "
        "of them kills the command at the print (#702)"
    )


# --- the control and the real assertion, in one fixture ------------------------------


def test_control_the_cp1252_fixture_really_does_kill_a_bare_write():
    """Must fire. Without this, the two subprocess assertions below pass just as
    happily on a platform where `PYTHONIOENCODING` was ignored -- a green tick over
    a condition that was never established.
    """
    established, why = _fixture_bites()
    if not established:
        pytest.skip(
            why + " -- what goes untested here is the whole of this file's "
            "subprocess half; the static check above still ran"
        )
    assert established


@pytest.mark.parametrize(
    "target",
    [RULE_PATH, ".oss/statusline.py"],
    ids=["the-rule-body-702-made-shippable", "the-pre-existing-statusline-instance"],
)
def test_scaffold_show_survives_a_console_that_cannot_encode_the_body(tmp_path, target):
    established, why = _fixture_bites()
    if not established:
        pytest.skip(
            why
            + " -- so whether --show survives such a console went unmeasured "
            "for {0}".format(target)
        )
    root = _repo(tmp_path)
    done = _child(
        [
            str(SCAFFOLD),
            "--root",
            str(root),
            "--config",
            str(root / ".oss.json"),
            "--show",
            target,
        ],
        CP1252_ENV,
        subject="whether --show survives a cp1252 console for {0}".format(target),
    )
    assert "UnicodeEncodeError" not in (done.stderr or ""), (
        "scaffold --show {0} died encoding its own output: {1}".format(
            target, (done.stderr or "")[-400:]
        )
    )
    assert done.returncode == 0, (
        done.returncode,
        done.stdout[-400:],
        done.stderr[-400:],
    )
    assert done.stdout.strip(), "printed nothing, so surviving proves nothing"
