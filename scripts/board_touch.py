#!/usr/bin/env python3
"""Mark the cached board stale when this session just changed it (#516).

A `PostToolUse` hook on `Bash`. #515 shortened the board's refresh interval; this closes
the window that is left, and it is the window that matters -- the seconds right after this
session merges a pull request or closes an issue, when somebody is watching the line.

**It never fetches.** It runs after every `Bash` call, and a network call here would put
`gh` latency in front of all of them. Marking the cache stale is enough: the render path
already forks a detached refresh when it sees a stale cache.

**It never marks the board stale for *now*.** GitHub's search index lags its own API by
seconds, so a refresh fired the instant a merge returns can re-cache the pre-merge counts
and then sit on them for a whole interval -- staler than doing nothing. The mark carries a
settle delay and the render honours it.

Every failure path here is silent and returns 0. A hook that raises reaches the user as a
broken tool call on every command they run, which is a far worse outcome than a status line
that stays stale for another minute.

Python 3.9 compatible.
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import statusline  # noqa: E402

#: How long after the command before the board is considered stale. Not zero, and the
#: reason is the forge rather than this code: `search/issues` is served from an index that
#: trails the merge that changed it, so a refresh taken immediately can record the old
#: counts under a fresh stamp -- which is worse than the staleness it was fixing.
SETTLE_DELAY = 10

#: Commands that change what this repo's board says. Matched at command position -- after a
#: start, a pipe, a quote or a shell separator -- so a commit message or a grep pattern
#: naming one of these is not one of these. Generous inside that: a command wrongly matched
#: costs a single refresh, one missed costs a stale board until the interval expires.
#: A supertool op, which is quoted and always preceded by the launcher, so the launcher is
#: what anchors it. `grep -r 'gh-issue-create' docs/` names one and is not one.
_OP_CALL = re.compile(
    r"supertool\S*\s+['\"]?(gh-pr-merge|gh-pr-create|gh-pr-edit|gh-issue-create)",
    re.IGNORECASE,
)

#: A raw `gh` call, anchored at command position -- the start, or after a separator. The
#: anchor is the whole point: `git commit -m 'gh pr merge closed it'` contains the words and
#: runs no merge, and a substring test would refresh the board on the commit message.
_RAW_CALL = re.compile(
    r"(?:\A|[;&|]|\n)\s*(?:sudo\s+)?gh\s+(?:pr\s+(?:merge|create|close|reopen|edit)"
    r"|issue\s+(?:create|close|reopen|edit))",
    re.IGNORECASE,
)


def changes_the_board(command):
    """Did this command change what the tracker would say about this repo?"""
    if not isinstance(command, str) or not command.strip():
        return False
    return bool(_OP_CALL.search(command) or _RAW_CALL.search(command))


def main(argv=None, stdin_text=None, now=None):
    try:
        raw = sys.stdin.read() if stdin_text is None else stdin_text
        payload = json.loads(raw) if raw and raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
        command = (payload.get("tool_input") or {}).get("command")
        if changes_the_board(command):
            root = statusline.repo_root(payload.get("cwd") or os.getcwd())
            if root is not None:
                repo = statusline.repo_config(root).get("repo")
                if repo:
                    statusline.mark_board_stale(repo, now=now, delay=SETTLE_DELAY)
    except Exception:  # noqa: BLE001 -- see the module docstring: never break a tool call
        pass
    sys.stdout.write("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
