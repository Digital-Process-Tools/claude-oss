"""This repository's own `.supertool.json`, as two invariants (#189, #648).

A config file is not code, and a test that re-reads the JSON it just wrote
asserts nothing. These two assert something the file cannot state about
itself, and both were red on the commit that preceded them:

1. Enabling the `watch` preset without declaring a radar tier leaves `radar`
   refusing. The refusal is correct rather than a bug, so nothing fails until
   somebody runs the op -- the preset is simply one key short of working and
   no test, lint or CI leg says so.
2. A repository name hand-typed into a tracked file travels with that file
   when a contributor copies it into another repository, at which point two
   repos bind one watcher socket with a declaration each.

The second one used to assert an ABSENCE: no op block anywhere in this file
declared `watch_name`, full stop. Its own docstring named the condition under
which that was expected to change -- "the name is derived from `.oss.json` by
`bin/oss-workspace` once #192 lands; it is not typed here" -- and both #192
(`022e437`) and #230 (`d416a7a`, the declared-name route `bin/oss-workspace`
itself now honours) landed with nobody returning to update it. #648 found the
guard still refusing a declaration those two changes made legitimate, and the
absence assertion was never the actual requirement: #189's stated harm is
COPY-PROPAGATION, a hand-typed value traveling unchanged into a repository it
does not belong to. An absence assertion cannot tell "correctly declared for
THIS repo" from "copy-pasted from another one" apart, because it refuses both
identically -- it happened to also refuse the correct case, which is what
made it look like the right guard for four years of nobody hitting the
distinction.

So the guard below is not an absence assertion any more. It is a
DERIVED-EQUALITY one: whatever `.supertool.json` declares must equal what
`scripts/oss_config.watch_channel_name` derives from this repository's own
`.oss.json` `repo` value -- the same fold `bin/oss-workspace` itself performs
when nothing is declared. #189's harm is still caught, and caught BETTER than
before: copy this file wholesale into a repository whose `.oss.json` names a
different `repo` and the derived name differs from the declared one, so this
test fails where the old absence assertion could not tell the two repos
apart at all. `_declared_watch_name` and `_declared_watch_names` are kept as
their own small readers (not a re-derivation of the fold, which lives only in
`oss_config.watch_channel_name` and is imported rather than duplicated) so
the assertion below states the comparison plainly.

Each pairs with a positive control on a synthetic document, because an
assertion that two values are equal also passes when the reader found
nothing at all on either side -- an unreadable file, a parser looking in the
wrong place, a repo root resolved one directory too high.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / ".supertool.json"
OSS_CONFIG = REPO_ROOT / ".oss.json"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import oss_config  # noqa: E402

#: The five ops that actually spawn or reach a poller -- `doctor.py`'s own
#: `_watch_declaration_split` docstring and the installed supertool's
#: `presets/watch/naming.py:WATCH_OPS`. Written down here rather than
#: imported: this asserts a fact about THIS REPO'S CONFIG, not a re-derivation
#: of the dependency's own list, and the two would drift silently if either
#: changed alone -- the same reasoning `doctor.py`'s own module docstring
#: gives for reading its copy from the installed dependency instead of the
#: other way around.
WATCH_OPS = ("channel", "radar", "unwatch", "watch", "watches")


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _radar_tiers(doc):
    """`ops.radar.radar_tiers` when it is a mapping, else None."""
    ops = doc.get("ops")
    if not isinstance(ops, dict):
        return None
    radar = ops.get("radar")
    if not isinstance(radar, dict):
        return None
    tiers = radar.get("radar_tiers")
    return tiers if isinstance(tiers, dict) else None


def _watch_names(doc):
    """Every `ops.*.watch_name` in the document, by op name."""
    ops = doc.get("ops")
    if not isinstance(ops, dict):
        return {}
    return {
        name: block["watch_name"]
        for name, block in ops.items()
        if isinstance(block, dict) and "watch_name" in block
    }


def test_the_config_is_there_and_declares_presets():
    """The control the two tests below stand on.

    Without it a moved file or a parse failure renders as two clean passes:
    no presets found, therefore no tier required; no ops found, therefore no
    name declared.
    """
    assert CONFIG.is_file(), "{} is missing".format(CONFIG)
    doc = _load(CONFIG)
    assert isinstance(doc, dict)
    assert isinstance(doc.get("presets"), list) and doc["presets"], (
        "no presets declared, so the watch-preset test below would pass vacuously"
    )


def test_the_watch_preset_comes_with_a_radar_tier():
    doc = _load(CONFIG)
    if "watch" not in doc.get("presets", []):
        pytest.skip("the watch preset is not enabled here, so radar is not loaded")
    tiers = _radar_tiers(doc)
    assert tiers, (
        "the watch preset is enabled and ops.radar.radar_tiers is absent or empty, "
        "so radar refuses instead of reconciling a board. This repository is on "
        "GitHub: declare the gh-prs tier."
    )
    assert "gh-prs" in tiers, (
        "this repository is on GitHub, so gh-prs is the tier that reads its "
        "board; declared tiers are {}".format(sorted(tiers))
    )


def test_a_watch_preset_without_a_tier_is_what_that_reader_catches():
    """Positive control: the reader fires on the shape the test above names."""
    assert _radar_tiers({"presets": ["git", "watch"], "ops": {"radar": {}}}) is None
    assert _radar_tiers({"presets": ["watch"]}) is None
    assert _radar_tiers({"ops": {"radar": {"radar_tiers": {}}}}) == {}
    assert _radar_tiers({"ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}}) == {
        "gh-prs": {}
    }


def _derived_watch_name():
    """What `bin/oss-workspace` itself would derive for this repository, straight
    from `oss_config.watch_channel_name` -- the one place the fold lives.
    """
    doc = _load(OSS_CONFIG)
    name, problem = oss_config.watch_channel_name(doc.get("repo"))
    assert not problem, (
        "this repository's own .oss.json repo value is not derivable: {}".format(
            problem
        )
    )
    return name


def test_every_declared_watch_name_matches_what_oss_json_derives():
    """The replacement for #189's absence assertion (#648).

    Every `watch_name` this file declares, on every op in WATCH_OPS, must equal
    the name `oss_config.watch_channel_name` derives from this repository's own
    `.oss.json`. A hand-typed value that happens to equal the derivation is
    indistinguishable from the derivation itself and carries none of #189's
    harm; a value that does not equal it is either stale or copy-propagated,
    and either way this must fail.

    This also asserts completeness -- every op in WATCH_OPS declares it, not
    only one -- because `doctor.py`'s own `#623` guard (`_watch_declaration_split`)
    treats a single-op declaration as `partial`: the other four ops silently
    fall back to the environment, which is the exact harm #648 was filed
    about. `tests/test_doctor_watch_declaration_split_623.py` is the test for
    that mechanism; this one is the test that this repo's own file satisfies
    it.

    And it asserts the other direction too: no `watch_name` declared under an
    op OUTSIDE WATCH_OPS -- a typo (`"wathc"`), a stray key on an unrelated op,
    or a future watch-adjacent op this tuple has not caught up with. #189's
    original absence check (`_watch_names(doc) == {}`) scanned every op block
    in the file, not a fixed list, so replacing it with a WATCH_OPS-scoped
    equality check alone would have narrowed coverage silently: a value sitting
    outside the tuple was invisible to `missing` above no matter what it said,
    while the op it was actually meant for still fell back to the environment
    -- the exact #648 harm, just relocated. Found by this issue's own review
    round rather than assumed correct on the first pass.
    """
    expected = _derived_watch_name()
    declared = _watch_names(_load(CONFIG))
    missing = sorted(op for op in WATCH_OPS if declared.get(op) != expected)
    assert not missing, (
        "ops.<op>.watch_name in {} must equal {!r} (derived from this "
        "repository's own .oss.json by oss_config.watch_channel_name) for "
        "every op in {!r} -- {} do not match. Declaring a different value, or "
        "leaving an op silent, is exactly the copy-propagation and partial-"
        "declaration harms #189 and #648 both name -- see this module's "
        "docstring.".format(CONFIG.name, expected, WATCH_OPS, missing)
    )
    stray = sorted(set(declared) - set(WATCH_OPS))
    assert not stray, (
        "ops.<op>.watch_name in {} is declared under {} -- outside WATCH_OPS "
        "{!r}, so the equality check above never reads it. This is the other "
        "half of #189's original absence check: a stray declaration here is "
        "either a typo or copy-propagated cruft, and either way the op it was "
        "actually meant for is still silent.".format(CONFIG.name, stray, WATCH_OPS)
    )


def test_a_mismatched_or_partial_declaration_is_what_that_reader_catches():
    """Positive control, in the new derived-equality shape.

    A name that does not match the derivation must fail the assertion above,
    a declaration on only some of WATCH_OPS must fail it too, and a name
    declared under an op OUTSIDE WATCH_OPS must fail the `stray` assertion --
    three "must fire"s beside
    `test_every_declared_watch_name_matches_what_oss_json_derives`'s two
    "must not fire"s. Exercised directly against `_watch_names` and
    `_derived_watch_name`'s own logic rather than by mutating the tracked
    file, so this stays a fixture rather than a write.
    """
    expected = _derived_watch_name()
    wrong_name = expected + "-copied-from-elsewhere"

    # A single wrong name on every op: mismatched, not merely partial.
    everywhere_wrong = _watch_names(
        {"ops": {op: {"watch_name": wrong_name} for op in WATCH_OPS}}
    )
    assert all(everywhere_wrong.get(op) != expected for op in WATCH_OPS)

    # Correct on one op, silent on the rest: the #623 partial state, which
    # must not clear a check that requires every op to carry the value.
    partial = _watch_names({"ops": {"radar": {"watch_name": expected}}})
    assert partial.get("radar") == expected
    assert any(partial.get(op) != expected for op in WATCH_OPS if op != "radar")

    # Correct on every op: the shape this repository's own file must reach,
    # and the case the assertion above must NOT fire on.
    everywhere_right = _watch_names(
        {"ops": {op: {"watch_name": expected} for op in WATCH_OPS}}
    )
    assert all(everywhere_right.get(op) == expected for op in WATCH_OPS)
    assert not (set(everywhere_right) - set(WATCH_OPS))

    # Declared on an op OUTSIDE WATCH_OPS -- a typo or a stray key on an
    # unrelated op. The equality check above never reads it (it only iterates
    # WATCH_OPS), so this is what the `stray` assertion exists to catch.
    stray = _watch_names({"ops": {"git-commit": {"watch_name": expected}}})
    assert set(stray) - set(WATCH_OPS) == {"git-commit"}

    assert _watch_names({}) == {}
