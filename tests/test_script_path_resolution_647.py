"""A shipped command that looks like ${CLAUDE_PLUGIN_ROOT}/scripts/X.py, but is
spelled scripts/X.py instead, resolves to nothing in every managed repository --
the script lives in the plugin, not in the repo being managed (#647).

`agents/developer.md:145` told a lane to `run python3 scripts/lane_setup.py <issue>
--lane ...`. That path is repo-relative; the script is not on disk in any repo this
plugin manages. The same class recurs across `skills/manager/SKILL.md` and every
`skills/manager/phases/*.md`: a script path spelled as a literal, runnable command
with arguments, inside backticks, with no `${CLAUDE_PLUGIN_ROOT}/` prefix.

This is not a ban on the bare string `scripts/whatever.py` -- most occurrences are
prose, naming the script as an artifact ("scripts/doctor.py already derives both
halves"), and those are fine: nobody types a sentence into a shell. The class this
guards is narrower and mechanical: a backtick span containing `scripts/NAME.py`
immediately followed, inside the same span, by at least one more token -- an
argument -- which is what a copy-pasted command looks like as opposed to a name
mentioned in passing. A few sites are deliberately relative to the MANAGED
repository rather than the plugin (assemble_changelog.py's own vendored copy,
report_schema.py's "this tree, if it ships one" fallback) and are named in
ALLOWED_SUBSTRINGS with the reason inline rather than silently excluded.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FILES = [
    "agents/developer.md",
    "agents/auditor.md",
    "agents/release-auditor.md",
    "agents/triager.md",
    "skills/manager/SKILL.md",
    "skills/manager/phases/dispatch.md",
    "skills/manager/phases/handback.md",
    "skills/manager/phases/review.md",
    "skills/manager/phases/merge.md",
    "skills/manager/phases/release.md",
    "skills/manager/phases/accounting.md",
]

# A backtick span holding "scripts/NAME.py" followed, inside the same span, by
# at least one more token -- an argument -- is a command, not a name mentioned
# in prose. re.DOTALL because markdown wraps a long command across a line break
# (dispatch.md:126 is exactly that case) and a per-line scan would miss it.
COMMAND_SPAN = re.compile(r"`([^`]*?scripts/[A-Za-z_]+\.py\s+\S[^`]*?)`", re.DOTALL)

# Lines deliberately relative to the repo being MANAGED, not the plugin --
# already reasoned about where they live, and out of scope for this guard.
ALLOWED_SUBSTRINGS = (
    "this tree's own",
    "this tree, if it ships one",
    "the same order this repo's own",
    "a managed repository may ship",
)


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"no .git found walking up from {here}")


def command_shaped_unprefixed(text: str) -> list[str]:
    """Every command-shaped `scripts/*.py ARGS` span missing the plugin-root
    prefix, as 'lineno :: snippet' strings -- never a bare count, so a caller
    can see which line to fix rather than only how many are wrong."""
    hits = []
    for match in COMMAND_SPAN.finditer(text):
        span = match.group(1)
        flat = span.replace("\n", " ")
        if "${CLAUDE_PLUGIN_ROOT}" in span or "./scripts/" in span:
            continue
        if any(sub in flat for sub in ALLOWED_SUBSTRINGS):
            continue
        line_no = text.count("\n", 0, match.start()) + 1
        hits.append(f"{line_no} :: {flat.strip()[:140]}")
    return hits


@pytest.mark.parametrize("relpath", FILES)
def test_no_repo_relative_script_commands(relpath):
    path = repo_root() / relpath
    if not path.exists():
        pytest.skip(f"{relpath} not present in this tree")
    text = path.read_text(encoding="utf-8")
    hits = command_shaped_unprefixed(text)
    assert not hits, (
        f"{relpath}: script path(s) shown as a runnable command without the "
        f"${{CLAUDE_PLUGIN_ROOT}}/ prefix -- resolves to nothing in every "
        f"managed repository (#647): {hits!r}"
    )


def test_positive_control_would_catch_a_repo_relative_command():
    """A negative assertion needs a positive control: prove the scanner fires
    on the exact shape #647 reported, not only that it stays silent today."""
    text = "run `python3 scripts/lane_setup.py <issue> --lane PATTERN`"
    hits = command_shaped_unprefixed(text)
    assert hits, "scanner failed to flag an unprefixed, command-shaped script path"


def test_prefixed_command_is_not_flagged():
    text = (
        'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lane_setup.py" <issue> --lane PATTERN'
    )
    hits = command_shaped_unprefixed(text)
    assert not hits, f"prefixed command wrongly flagged: {hits!r}"


def test_prose_mention_is_not_flagged():
    text = "`scripts/lane_setup.py`'s own `CROSS_CUTTING_GUARDS` is the derived list"
    hits = command_shaped_unprefixed(text)
    assert not hits, f"a bare prose mention wrongly flagged: {hits!r}"
