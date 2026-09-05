"""This repository's own `.claude/settings.json` must name a tracked file (#496).

`.oss/` is gitignored in THIS repository specifically -- the comment beside the
ignore entry gives the reason: a vendored copy of `scripts/statusline.py` would
be a second copy of a file this repo already carries, swept by the same guards
and free to drift. The committed `statusLine` command pointed at that
gitignored path anyway, so `git ls-files .oss/` returns nothing and a fresh
clone's status line silently targets a file that was never checked in.

This is a fact about this repo's own checked-in settings, not about what
`scaffold.py` writes into a managed repo it scaffolds -- there `.oss/` IS
tracked (the "ours" contract in CLAUDE.md), so the identical command is
correct and stays untouched.
"""

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_this_repos_own_statusline_does_not_point_at_the_gitignored_copy():
    settings = json.loads(
        (REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    command = settings["statusLine"]["command"]
    assert ".oss/statusline.py" not in command, (
        "command names a path this repo's own .gitignore excludes: " + command
    )


def test_the_command_names_a_path_this_repo_actually_tracks():
    """The must-fire control: the path now named is genuinely checked in, not just
    a string that happens to avoid the gitignored one.
    """
    settings = json.loads(
        (REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    command = settings["statusLine"]["command"]
    assert "scripts/statusline.py" in command

    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "scripts/statusline.py"],
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    assert tracked == "scripts/statusline.py"
