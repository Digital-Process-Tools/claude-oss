"""#1036: `scripts/select_issues.py` (#970) is the composed dispatch-selection
call, but the loop's own imperative directives never named it -- only an
informational aside in `skills/manager/phases/dispatch.md` mentioned it, and
`commands/tick.md` step 5 named `dispatch_rank.py` and `lane_setup.py --claim`
as the calls to run by hand instead.

This asserts the two sites carry an actual directive naming
`select_issues.py` as *the* dispatch-selection call to run, not merely a
description of what it does -- a description can be read past; an imperative
sentence starting with "Run" is what a session following the file's own
convention (`**Run the companion search.**`, `**Claim before you spawn...**`)
actually executes.

#1037 (landed in the same lane, after this fix): step 5 moved out of
`commands/tick.md` into its own phase file, read by a sub-manager rather than
injected into the scheduler on every tick -- so the first check below now
reads that file instead.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_DIRECTIVE_RE = re.compile(
    r"\*\*Run[^*]*`(?:python3 \"\$\{CLAUDE_PLUGIN_ROOT\}/)?scripts/select_issues\.py`"
)


def _read(relpath):
    return (REPO_ROOT / relpath).read_text(encoding="utf-8")


def test_tick_md_step_5_directs_select_issues_py():
    text = _read("skills/manager/phases/tick-order.md")
    assert _DIRECTIVE_RE.search(text), (
        "skills/manager/phases/tick-order.md step 5 must carry an imperative "
        "directive naming scripts/select_issues.py as the dispatch-selection "
        "call to run, not only dispatch_rank.py/lane_setup.py --claim by hand"
    )


def test_dispatch_phase_file_directs_select_issues_py():
    text = _read("skills/manager/phases/dispatch.md")
    assert _DIRECTIVE_RE.search(text), (
        "skills/manager/phases/dispatch.md must reword its select_issues.py "
        "mention from a description into a directive"
    )
