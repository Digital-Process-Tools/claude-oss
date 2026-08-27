"""#586: the dispatch runbook still taught the hand-retyped held set that

`--derive-held` (#558) was built to replace. `skills/manager/phases/dispatch.md`
is what the loop reads when it dispatches, and `skills/manager/SKILL.md` carries
the spine's shorter copy of the same instruction -- both named `--against
PATTERN` as *the* way to check a new lane against everything already running,
with no mention that a derivation exists.

Read literally off the issue: "Shipping the flag without moving the runbook
keeps that exact failure available, with a fix sitting one flag away that
nobody is told about. A capability nobody is routed to and a capability that
does not exist are the same thing from where the reader stands."

This is a content assertion, so every negative here is paired with a positive
in the same fixture: the file must still exist and be readable (or the "must
not say X" half would pass on a missing file), --derive-held must be named as
the route, the could-not-derive-the-held-set state must be named as the named
fallback's own reading (not a bare "if it fails, type it by hand"), and the
old table row's *only* command example must no longer be the hand-typed one
with no derivation mentioned beside it.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DISPATCH = REPO_ROOT / "skills" / "manager" / "phases" / "dispatch.md"
SPINE = REPO_ROOT / "skills" / "manager" / "SKILL.md"


def _read(path):
    assert path.is_file(), "{0} must exist and be readable".format(path)
    text = path.read_text(encoding="utf-8")
    assert text, "{0} must not be empty".format(path)
    return text


def test_dispatch_names_derive_held_as_the_route():
    text = _read(DISPATCH)
    assert "--derive-held" in text, (
        "dispatch.md must route the reader to --derive-held (#558), not only "
        "to the hand-typed --against side"
    )


def test_dispatch_names_the_could_not_derive_state_as_a_named_fallback():
    text = _read(DISPATCH)
    assert "could-not-derive-the-held-set" in text, (
        "the failure mode of --derive-held is a third state, not a plain "
        "'if it fails, type it by hand' -- it must be named in the runbook's "
        "own words (#558)"
    )
    idx_derive = text.index("--derive-held")
    idx_state = text.index("could-not-derive-the-held-set")
    idx_against = text.index("--against PATTERN")
    assert idx_derive < idx_state < idx_against, (
        "the reading order must be: --derive-held is the route, then the "
        "could-not-derive-the-held-set state, then --against as its named "
        "fallback -- not the old order where --against is the only mechanism "
        "and the derivation never appears"
    )


def test_dispatch_still_leaves_the_candidate_side_to_the_maintainer():
    text = _read(DISPATCH)
    assert "#267" in text, (
        "an issue's own files are still not derivable from its body -- #558 "
        "does not dispute #267, and the rewrite must not imply the whole "
        "call became automatic"
    )


def test_spine_table_row_also_names_derive_held():
    text = _read(SPINE)
    idx = text.index("naming a lane, against everything already running")
    row_end = text.index("\n", idx)
    row = text[idx:row_end]
    assert "--derive-held" in row, (
        "the spine's own copy of this instruction (loaded every tick) must "
        "not keep teaching the hand-retyped --against set once the phase "
        "file routes the reader to --derive-held instead -- a rule that "
        "lands in only one of the two copies reaches fewer readers and the "
        "two can drift"
    )


def test_spine_table_keeps_the_bundling_row_on_plain_against():
    text = _read(SPINE)
    idx = text.index("bundling a second issue into a lane already claimed")
    row_end = text.index("\n", idx)
    row = text[idx:row_end]
    assert "--against PATTERN" in row, (
        "the bundling check compares a candidate's declared lane against one "
        "named running lane, not the --derive-held aggregate every other "
        "lane and open pull request contributes to -- conflating the two "
        "rows would route the bundling case to a call that answers a "
        "different question"
    )


def test_dispatch_mutual_exclusion_is_still_documented():
    text = _read(DISPATCH)
    assert "mutually exclusive" in text or "mutual" in text.lower(), (
        "--derive-held and --against are refused together by the script "
        "(#558) -- the runbook should not imply both can be combined"
    )


def test_dispatch_bundling_paragraph_does_not_claim_the_same_call():
    """The bundling-check paragraph used to cross-reference the disjointness

    paragraph above it as "the same ... call ... already runs" -- true while
    both used plain --against, and false the moment the paragraph above it
    was rewritten to lead with --derive-held instead. The bundling check
    needs overlap against one named running lane, not the --derive-held
    aggregate, so it still uses plain --against and must say so without
    claiming to be the same call as the one that no longer is.
    """
    text = _read(DISPATCH)
    idx = text.index("Never bundle an issue a running lane already touches")
    end = text.index("The two-issue row must not become a rule", idx)
    paragraph = text[idx:end]
    assert "--against PATTERN" in paragraph, (
        "the bundling check must still name --against PATTERN explicitly"
    )
    assert "the same" not in paragraph.lower() or "not the same" in paragraph.lower(), (
        "the bundling paragraph must not claim to reuse 'the same call' as "
        "the disjointness paragraph above it now that that paragraph leads "
        "with --derive-held instead of --against"
    )
