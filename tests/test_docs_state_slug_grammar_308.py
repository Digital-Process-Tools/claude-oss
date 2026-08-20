"""Five documents state the changelog fragment naming convention, and until #308 none
of them stated the slug that `_NAME_RE` -- the assembler's own grammar -- has accepted
from the start, and that `scripts/release_version.py` accepted too as of #297/#305.

The grammar exists in exactly one place worth citing: `scripts/assemble_changelog.py`'s
own refusal message, which spells the form as `<issue>.<section>[.<slug>].md`. That
string is read out of the assembler at runtime here rather than retyped as a second
literal, so this file cannot itself drift from `_NAME_RE` the way the five documents
did (#308's own point).

Every "document states the form" assertion below is paired with a control that proves
the check has teeth: the canonical form is shown to (a) explicitly document the
optional segment, not just the word "slug" somewhere on the page, (b) round-trip
through the real parser for both the slugged and unslugged spelling, and (c) still be
refused for a name outside the grammar. Without the last two, "the string appears
somewhere in the document" would pass against a document that also stated something
false about what the parser does.

Two of the five sites are templates that ship into other repositories --
`scaffold.py`'s fragment README and its embedded workflow -- and are read here as the
*rendered* output, not the template source, because a passing grep against the
template string proves nothing about what a scaffolded repository actually receives.
"""

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

# Imported rather than `importorskip`ed, same reasoning as
# tests/test_release_version_fragment_names_297.py: a missing module is a red
# collection error, which is what a missing module is.
import assemble_changelog  # noqa: E402
import oss_rules  # noqa: E402
import scaffold  # noqa: E402


def _canonical_form():
    """The naming grammar, in the assembler's own words -- read out of its refusal
    message rather than hand-copied, so this file cannot itself state a form that has
    drifted from `_NAME_RE`."""
    with pytest.raises(assemble_changelog.BadFragment) as excinfo:
        assemble_changelog.parse_fragment_name("not-a-fragment-name")
    match = re.search(r"does not parse as (\S+)", str(excinfo.value))
    assert match, str(excinfo.value)
    return match.group(1)


CANONICAL = _canonical_form()


def _config():
    return {"changelog_dir": "changelog.d"}


# --------------------------------------------------- the canonical form itself has teeth


def test_the_canonical_form_documents_the_optional_slug():
    """The must-fire control for every assertion in this file: if the assembler's own
    message ever stopped spelling out the optional segment, every check below would
    start passing vacuously against a document that also dropped it."""
    assert CANONICAL == "<issue>.<section>[.<slug>].md", CANONICAL


def test_the_canonical_form_round_trips_through_the_grammar():
    """Not just a string: a name built from each half of it is genuinely accepted,
    with the bracketed segment both present and absent."""
    unslugged = assemble_changelog.parse_fragment_name("12.fixed.md")
    assert unslugged.slug == "", unslugged

    slugged = assemble_changelog.parse_fragment_name("12.fixed.example-slug.md")
    assert slugged.slug == "example-slug", slugged
    assert slugged.issue == 12 and slugged.section == "fixed", slugged


def test_the_canonical_form_still_refuses_a_name_outside_it():
    """The must-fire control beside the round trip above: the grammar the canonical
    form describes still refuses a name outside it, so the round trip is measuring a
    real accept/refuse boundary and not "everything ending in .md"."""
    with pytest.raises(assemble_changelog.BadFragment):
        assemble_changelog.parse_fragment_name("not-a-fragment-name")


def test_the_two_segment_form_is_a_different_string_than_the_canonical_one():
    """The must-fire control for the five checks below: proves the file can
    distinguish the old, narrower sentence from the current one, rather than the
    assertion being satisfiable by any sentence mentioning fragments at all."""
    old_form = "<issue>.<section>.md"
    assert old_form != CANONICAL
    assert CANONICAL not in old_form


# ------------------------------------------------------------------- the five sites


def test_changelog_d_readme_states_the_canonical_form():
    text = (REPO_ROOT / "changelog.d" / "README.md").read_text(encoding="utf-8")
    assert CANONICAL in text, text


def test_the_rule_layer_states_the_canonical_form():
    text = oss_rules.changelog_fragments(
        assembler="scripts/assemble_changelog.py", fragments_dir="changelog.d"
    )
    assert CANONICAL in text, text


def test_the_changelog_command_states_the_canonical_form():
    text = (REPO_ROOT / "commands" / "changelog.md").read_text(encoding="utf-8")
    assert CANONICAL in text, text


def test_the_scaffolded_fragments_readme_states_the_canonical_form():
    """The site with teeth (#308): the *rendered* template a scaffolded repository
    actually receives, not the template source sitting in this repository."""
    text = scaffold.render("changelog.d/README.md", _config())
    assert CANONICAL in text, text


def test_the_scaffolded_workflow_states_the_canonical_form():
    """The other templated site: the rendered `.github/workflows/oss-changelog.yml`
    this plugin writes into a scaffolded repository's own CI."""
    text = scaffold.render_owned(
        ".github/workflows/oss-changelog.yml", _config(), str(REPO_ROOT)
    )
    assert CANONICAL in text, text


def test_this_repos_own_changelog_workflow_states_the_canonical_form():
    """A sixth site the reviewer found (#308): this repository's own hand-maintained
    `.github/workflows/changelog.yml` -- distinct from the `oss-changelog.yml`
    template `scaffold.py` writes into *other* repositories -- carries the same
    error-message sentence and had drifted from it the same way."""
    text = (REPO_ROOT / ".github" / "workflows" / "changelog.yml").read_text(
        encoding="utf-8"
    )
    assert CANONICAL in text, text
