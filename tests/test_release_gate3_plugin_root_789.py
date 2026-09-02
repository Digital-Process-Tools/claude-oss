"""#789: `commands/release.md` gate 3 invoked `checklist_skew.py` (and
`ranking_table.py`) via a bare `${CLAUDE_PLUGIN_ROOT}` interpolation with no
`--plugin-root` flag. `checklist_skew.py --help` documents that its own
`--plugin-root` default is `os.environ.get("CLAUDE_PLUGIN_ROOT")` -- a real
shell environment variable, not the literal path substituted into the command
text at injection time (`commands/tick.md`'s own comment: "a version-pinned
path substituted once when this command was injected"). In a session where the
shell process does not carry that variable exported, the script runs (the
file WAS found, because the path text was substituted literally) but its own
internal env lookup comes back empty, and it degrades to `could-not-tell` --
a real JSON answer that reads as a legitimate unknown where a measurement
(`not-applicable`) was available one flag away.

`commands/tick.md` step 1 already solves this for `doctor.py`: resolve the
actually-installed root via `plugin_update.py --print-resolved-root --root .`,
falling back to the pinned `${CLAUDE_PLUGIN_ROOT}` only if that fails, and
name which route was used. Gate 3 needs the identical resolution for both
`checklist_skew.py` and `ranking_table.py` (which shares the identical
`--plugin-root`/env-var mechanism, confirmed by its own `--help`), passed
explicitly as `--plugin-root`.

**A first version of this fix (caught in this lane's own self-review, #789)
computed the resolved root once in a shared fenced block and consumed it from
two other, separate fenced blocks far below.** Bash variables do not survive
between separate command invocations -- only `cd` does -- so an agent running
each fenced block as its own Bash call would find `$GATE3_ROOT` empty at both
use sites, and both `checklist_skew.py` and `ranking_table.py` treat an empty
`--plugin-root` value as equivalent to omitting the flag entirely (a falsy
check in each script), silently reproducing the exact pre-fix degradation
while *looking* fixed (an explicit `--plugin-root` is visibly present in the
command text). The fix is now self-contained: each of the two call sites
resolves and consumes its own root inside the *same* fenced block, exactly as
`commands/tick.md`'s `DOCTOR_ROOT` block already does for `doctor.py`.

`release_delta.py` does not take `--plugin-root` at all (`--help` confirms:
only `--repo`/`--match`/`--config`) -- it has no internal env-var fallback to
degrade, so it is out of scope for this fix; noted rather than silently
skipped.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_MD = REPO_ROOT / "commands" / "release.md"

BASH_FENCE_RE = re.compile(r"```bash\n(.*?)```", re.S)


def _text():
    return RELEASE_MD.read_text(encoding="utf-8")


def _bash_blocks():
    return BASH_FENCE_RE.findall(_text())


def test_release_md_exists():
    assert RELEASE_MD.is_file()


def test_gate3_resolves_the_plugin_root_before_using_it():
    """Must fire against the pre-fix recipe (regression control below), must
    NOT fire against the fixed file: gate 3 must resolve the installed plugin
    root the same way commands/tick.md step 1 does, rather than relying on a
    possibly-unset $CLAUDE_PLUGIN_ROOT inside checklist_skew.py's own
    default."""
    text = _text()
    assert "--print-resolved-root" in text, (
        "gate 3 must resolve the installed plugin root the same way "
        "commands/tick.md step 1 does, rather than relying on a possibly-"
        "unset $CLAUDE_PLUGIN_ROOT inside checklist_skew.py's own default"
    )


def test_checklist_skew_call_passes_plugin_root_explicitly():
    text = _text()
    calls = [
        line for line in text.splitlines()
        if "scripts/checklist_skew.py" in line and "python3" in line
    ]
    assert calls, "no checklist_skew.py invocation found in commands/release.md"
    for line in calls:
        assert "--plugin-root" in line, (
            "checklist_skew.py must be invoked with an explicit --plugin-root "
            "(the resolved root), not left to its own $CLAUDE_PLUGIN_ROOT "
            "fallback: {!r}".format(line)
        )


def test_ranking_table_call_passes_plugin_root_explicitly():
    text = _text()
    calls = [
        line for line in text.splitlines()
        if "scripts/ranking_table.py" in line and "python3" in line
    ]
    assert calls, "no ranking_table.py invocation found in commands/release.md"
    for line in calls:
        assert "--plugin-root" in line, (
            "ranking_table.py must be invoked with an explicit --plugin-root "
            "for the same reason as checklist_skew.py (#789): its own default "
            "is the identical possibly-unset $CLAUDE_PLUGIN_ROOT env lookup"
        )


def test_release_delta_has_no_plugin_root_flag_to_add():
    """Control: release_delta.py genuinely has no --plugin-root option, so its
    bare ${CLAUDE_PLUGIN_ROOT} call site is only used to locate the script
    file, not as a runtime parameter -- confirmed by its own --help, out of
    scope for this fix."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "release_delta.py"), "--help"],
        capture_output=True, text=True, check=True,
    )
    assert "--plugin-root" not in result.stdout


def test_pre_fix_recipe_would_have_failed_this_check():
    """Regression control: the bare interpolation this issue reports, run
    through the same check, must fail -- proving the assertions above are not
    vacuously true."""
    bad = (
        '   ```bash\n'
        '   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/checklist_skew.py" --repo . --json\n'
        '   ```\n'
    )
    calls = [
        line for line in bad.splitlines()
        if "scripts/checklist_skew.py" in line and "python3" in line
    ]
    assert calls
    assert not any("--plugin-root" in line for line in calls)


def _blocks_calling(script_name):
    return [b for b in _bash_blocks() if script_name in b and "python3" in b]


def test_checklist_skew_resolution_and_call_share_one_fenced_block():
    """The class of defect a reviewer found in this lane's own first draft:
    resolving GATE3_ROOT in one fence and consuming it in a different, later
    fence relies on shell state a Bash tool call does not actually carry
    across invocations. Every bash block that calls checklist_skew.py with
    --plugin-root must also contain the resolution logic that produces the
    value it passes."""
    blocks = _blocks_calling("scripts/checklist_skew.py")
    assert blocks, "no checklist_skew.py bash block found"
    for block in blocks:
        assert "--print-resolved-root" in block, (
            "checklist_skew.py's call and its plugin-root resolution must "
            "live in the same fenced bash block -- found the call without "
            "the resolution in the same block:\n{}".format(block)
        )


def test_ranking_table_resolution_and_call_share_one_fenced_block():
    blocks = _blocks_calling("scripts/ranking_table.py")
    assert blocks, "no ranking_table.py bash block found"
    for block in blocks:
        assert "--print-resolved-root" in block, (
            "ranking_table.py's call and its plugin-root resolution must "
            "live in the same fenced bash block -- found the call without "
            "the resolution in the same block:\n{}".format(block)
        )


def test_split_block_form_would_have_failed_the_same_check():
    """Regression control (#789, caught by self-review): must-fire against
    the exact split-block shape this lane's first draft produced -- a
    resolution block followed by a SEPARATE block containing only the call,
    which is what the fix above must never regress to."""
    split_form = (
        "text before\n\n"
        "```bash\n"
        'RESOLVED_ROOT="$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/plugin_update.py" '
        '--print-resolved-root --root . 2>/dev/null)"\n'
        "GATE3_ROOT=\"$RESOLVED_ROOT\"\n"
        "```\n\n"
        "text between\n\n"
        "```bash\n"
        'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/checklist_skew.py" --repo . '
        '--plugin-root "$GATE3_ROOT" --json\n'
        "```\n"
    )
    blocks = [b for b in BASH_FENCE_RE.findall(split_form) if "checklist_skew.py" in b]
    assert blocks
    for block in blocks:
        assert "--print-resolved-root" not in block, (
            "the split-block regression fixture should NOT carry the "
            "resolution in the same block as the call -- if it does, this "
            "fixture no longer represents the defect it is meant to guard"
        )
