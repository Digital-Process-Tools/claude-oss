"""#544: a census of the places this repository states a fact whose authority is
somewhere else -- another tool's accepted-input pattern, a forge's documented limit,
a command's own rules -- so a new site is compared against the rule #180 already
wrote down instead of being invisible to it.

This is #173's shape one level up: a sweep of patterns cannot see a value that never
had one, so this census enumerates the *sites* the borrowed values live at, by hand,
rather than trying to detect them by shape. What it CAN check by machine is drift --
a censused site whose symbol moved or vanished -- and that a site is never left in an
undeclared fourth state.

Every "must not" is paired with a "must" in the same fixture: a checker that flags
every site (even correct ones) is not the same as one that found a real defect, and a
render that only lists problems cannot be told from one that never looked.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import borrowed_authority as ba  # noqa: E402


def _site(**over):
    base = {
        "id": "example",
        "module": "oss_config",
        "symbol": "CONFIG_NAME",
        "claim": "the config filename",
        "authority": "this repository's own convention",
        "state": ba.STATE_DERIVED,
        "note": "",
    }
    base.update(over)
    return base


# --- shape and state validation -------------------------------------------------

def test_a_known_good_site_validates_clean():
    problems = ba.validate_sites([_site()])
    assert problems == []


def test_unrecognised_state_is_refused():
    problems = ba.validate_sites([_site(state="mostly-fine")])
    assert problems and "mostly-fine" in problems[0]


def test_unmeasured_site_without_a_note_is_refused():
    # The third state is load-bearing (CLAUDE.md, #173): "declared unmeasurable" needs
    # the declaration, not just the word. An unmeasured site with an empty note is
    # indistinguishable from a site nobody classified.
    problems = ba.validate_sites([_site(state=ba.STATE_UNMEASURED, note="")])
    assert problems and "note" in problems[0]


def test_unmeasured_site_with_a_note_validates_clean():
    # Positive control for the case above: the same state, with the reason stated,
    # is accepted.
    problems = ba.validate_sites(
        [_site(state=ba.STATE_UNMEASURED, note="cannot be queried from a test (#544)")]
    )
    assert problems == []


def test_missing_field_is_refused():
    site = _site()
    del site["authority"]
    problems = ba.validate_sites([site])
    assert problems and "authority" in problems[0]


# --- drift: a censused site whose symbol moved or vanished ----------------------

def test_a_real_site_resolves():
    # Must: an entry naming a symbol that actually exists in the named module is not
    # reported as drifted.
    problems = ba.resolve_sites([_site(module="oss_config", symbol="CONFIG_NAME")])
    assert problems == []


def test_a_renamed_symbol_is_reported_as_drift():
    # Must not: the same check, on a symbol that does not exist, in the same fixture
    # shape as the "must" above -- so a checker that always passes cannot hide here.
    problems = ba.resolve_sites(
        [_site(module="oss_config", symbol="THIS_SYMBOL_DOES_NOT_EXIST_544")]
    )
    assert problems
    assert "THIS_SYMBOL_DOES_NOT_EXIST_544" in problems[0]


def test_an_unimportable_module_is_reported_not_raised():
    problems = ba.resolve_sites([_site(module="no_such_module_544", symbol="X")])
    assert problems
    assert "no_such_module_544" in problems[0]


def test_a_multi_symbol_entry_checks_every_name():
    # `symbol` may name more than one attribute (e.g. a group of related constants),
    # separated by " / ". Every one of them has to resolve.
    problems = ba.resolve_sites(
        [_site(module="oss_config", symbol="CONFIG_NAME / LOCAL_CONFIG_NAME")]
    )
    assert problems == []
    problems = ba.resolve_sites(
        [_site(module="oss_config", symbol="CONFIG_NAME / NOPE_544")]
    )
    assert problems and "NOPE_544" in problems[0]


# --- the real census: every entry resolves, and the whole set is well-formed ----

def test_the_real_census_has_no_shape_problems():
    assert ba.validate_sites(ba.SITES) == []


def test_the_real_census_sites_all_resolve():
    # Every censused symbol still exists where the census says it does -- the drift
    # guard, run against the actual repository rather than a fixture.
    problems = ba.resolve_sites(ba.SITES)
    assert problems == [], problems


def test_the_real_census_carries_both_known_resolved_and_known_open_sites():
    # Positive control on the census content itself: it must not be a census that
    # only ever reports clean, and it must not be a census that only ever reports a
    # finding -- #544 asks for both states to be visible.
    states = {site["state"] for site in ba.SITES}
    assert ba.STATE_DERIVED in states or ba.STATE_MEASURED in states
    assert ba.STATE_UNMEASURED in states


# --- render: clean sites reported as loudly as the ones found wanting -----------

def test_render_lists_every_site_not_only_problems():
    lines = ba.render(
        [
            _site(id="clean-one", state=ba.STATE_DERIVED),
            _site(id="open-one", state=ba.STATE_UNMEASURED, note="cannot be queried"),
        ]
    )
    joined = "\n".join(lines)
    assert "clean-one" in joined
    assert "open-one" in joined


def test_render_marks_a_drifted_site_distinctly_from_a_clean_one():
    lines = ba.render(
        [
            _site(id="ok-site", module="oss_config", symbol="CONFIG_NAME"),
            _site(id="drifted-site", module="oss_config", symbol="NOPE_544"),
        ]
    )
    joined = "\n".join(lines)
    ok_line = next(line for line in lines if "ok-site" in line)
    drifted_line = next(line for line in lines if "drifted-site" in line)
    assert ok_line != drifted_line
    assert "drift" in drifted_line.lower() or "not found" in drifted_line.lower()


# --- CLI ---------------------------------------------------------------------

def test_closing_keyword_site_records_what_the_keywords_are_used_for():
    """#556: the note beside the closing-keyword site must say more than "no reason
    recorded". It has to record that the constant is used only as an absence
    detector -- never to decide what a body will close -- and that GitHub matches a
    keyword by position, not sentence meaning, which is what makes a negated closing
    sentence harmless rather than a missed case. A note that only repeats "no reason
    recorded" would validate the shape check above and still leave #556 open.
    """
    site = next(s for s in ba.SITES if s["id"] == "closing-keyword")
    note = site["note"].lower()
    assert "position" in note, site["note"]
    assert "absence detector" in note, site["note"]
    assert "#556" in site["note"], site["note"]


def test_cli_exits_zero_and_prints_every_site():
    import subprocess

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "borrowed_authority.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    assert result.returncode == 0, result.stdout
    for site in ba.SITES:
        assert site["id"] in result.stdout


def test_cli_reports_drift_with_nonzero_exit(monkeypatch):
    # Cannot drift the real census without editing owned files this lane does not
    # touch, so this drives `_main` with an injected, broken site list -- the same
    # "must not" pairing as `test_a_renamed_symbol_is_reported_as_drift`, exercised
    # through the CLI entry point instead of the library function.
    broken = [_site(id="broken", module="oss_config", symbol="NOPE_544")]
    monkeypatch.setattr(ba, "SITES", broken)
    exit_code = ba._main([])
    assert exit_code != 0
