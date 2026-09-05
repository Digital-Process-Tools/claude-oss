"""docs/status-line.md documents every field `statusline.render` actually emits (#650).

Before #650, `README.md` documented none of the status line's fields --
not even the four that predate #613's `ch` field, which is why #645 (closing
#613) had nowhere to add the fifth one and handed the whole section to the
maintainer instead. #795 later moved this whole section out of README.md and
into its own `docs/status-line.md`, alongside the rest of the material README
carried by issue-number receipt rather than as a pitch and a start -- the fact
this file pins travels with it rather than staying behind in the trimmed
README. This does not re-render the line and diff it against the doc (that
would just move the drift into a second copy of the format strings); it pins
the one thing worth pinning without inventing a fixture no future field would
naturally show up in -- that every literal prefix `render()` actually emits is
still named somewhere in the status line doc, so the day a field's own prefix
changes and nobody touches the doc, this fails instead of nothing noticing.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STATUS_LINE_DOC = REPO_ROOT / "docs" / "status-line.md"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


def _status_line_section():
    text = STATUS_LINE_DOC.read_text(encoding="utf-8")
    match = re.search(r"# Status line\n(.*)\Z", text, re.DOTALL)
    assert match, "docs/status-line.md has no '# Status line' section"
    return match.group(1)


# The literal prefix each field's own format string in statusline.py opens
# with -- read from the source strings themselves, not retyped from memory,
# so a rename of the prefix breaks this test rather than agreeing with it.
FIELD_PREFIXES = ("pr ", "np ", "nl ", "rel ", "trap ", "last ", "plug ", "ch")


def test_readme_status_line_section_exists():
    _status_line_section()


def test_readme_names_every_field_prefix_render_emits():
    section = _status_line_section()
    for prefix in FIELD_PREFIXES:
        assert prefix.strip() in section, (
            "README's status line section omits {!r}".format(prefix)
        )


def test_readme_documents_the_watch_channel_opt_out():
    """`ch` is the one field with a documented off switch (`watch_channel`);
    the config key it reads is `oss_config.WATCH_CHANNEL_KEY` -- read from the
    source rather than retyped, so a rename of the key breaks this test.
    """
    import oss_config  # noqa: E402

    section = _status_line_section()
    assert oss_config.WATCH_CHANNEL_KEY in section


def test_readme_names_every_channel_state_glyph():
    """Every state `_channel_field` can render must appear in the README's
    `ch` row -- read from `statusline.CHANNEL_STATES`, the source of truth
    for what the five upstream states are, not retyped.
    """
    section = _status_line_section()
    # The unicode markers `_symbols(ascii_only=False)` uses for `ch`.
    for glyph in ("✓", "✗", "◐", "!", "?"):
        assert glyph in section, (
            "README's ch row is missing the {!r} state marker".format(glyph)
        )
