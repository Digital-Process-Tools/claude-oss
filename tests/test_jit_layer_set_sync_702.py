"""The rule layer on disk and the rule layer the generator ships must be the same
set, in both directions -- #702.

`scripts/oss_rules.py` is the one place the `01-oss` layer is declared, and
`install()` **removes the layer before rewriting it**. So a rule that exists in this
repository's own `.claude/jit-context/` and not in `oss_rules.RULES` is deleted by
the next `/oss:scaffold --apply`, and has never shipped into any managed repository
at all. That is what happened to `vocabulary/01-oss/plugin-currency.md`: added
deliberately by `655c9a4`, indexed with seven keyword rows, observed firing in a
live session, and `grep -c 'plugin-currency' scripts/oss_rules.py` answered `0`.

The reverse direction costs something too, and is checked here as well: a rule the
generator ships and this repository does not carry is a rule written into strangers'
repositories that nobody here ever reads.

## Why the check is over the SET rather than over one hand-named pair

`tests/test_supertool_rule_sync_577.py` already compares two bodies -- for exactly
one hand-named pair. `CLAUDE.md` records the reasoning that put it there, and none
of that reasoning is specific to the supertool rule. **A guard built for one pair,
in a set that grows, goes quietly narrower than its own subject**, which is the
shape this repository names at the end of its phase-split section. #702 is that
happening: the layer grew one entry and the guard could not see it.

That file stays rather than being folded in here. Its control pair pins the
normalisation contract -- CRLF and trailing whitespace are not drift -- against
synthetic bodies that do not depend on today's repo state, and nothing below
duplicates it.

## Derivation was weighed and declined, for #577's own reason one file over

Generating one copy from the other at import or build time removes this class
rather than guarding it. It was declined for #577 because it would change how the
rule layer is assembled for a single pair; the same argument holds for the set,
with one addition -- `install()` already generates the on-disk layer from
`oss_rules.RULES`, so the two copies are *already* generator and output. What has no
mechanism is anybody re-running the generator over this repository, and a comparison
test costs one file and answers exactly that.
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_rules  # noqa: E402

LAYER_ROOT = REPO_ROOT / ".claude" / "jit-context"

#: Not a rule and not an entry: the index is a build artifact `install()` writes from
#: `index_rows()`, and `claude-jit-context`'s own builders skip the name.
INDEX = oss_rules.INDEX

#: Entries whose body is rendered against the tree it is going into rather than being a
#: module constant, so a byte comparison between `RULES` and this repository's tracked
#: copy asks the wrong question -- `RULES` is `rules()` with no `repo_root`, which is
#: deliberately the could-not-locate form. The SET check above still covers these; only
#: the body check below skips them, and `test_a_named_exception_is_still_an_exception`
#: fails if one stops needing the carve-out, so the list cannot quietly become a licence.
RENDERED_PER_TREE = {("paths", "changelog-fragments.md")}


def layer_entries(root, dimension):
    """`(entries, problem)` for one dimension's `01-oss` directory.

    `problem` is the third state and it is never folded into an empty set: a
    directory that could not be listed has not been shown to hold no rules. The
    listing is attempted directly rather than pre-checked with `Path.exists()`, for
    the reason `CLAUDE.md` records under that call's own name -- it swallows a short
    list of errnos and re-raises the rest, and which is which moves between
    interpreter versions.
    """
    layer = Path(root) / ".claude" / "jit-context" / dimension / oss_rules.LAYER
    try:
        names = os.listdir(str(layer))
    except FileNotFoundError as exc:
        return None, "no such directory: {}".format(exc)
    except OSError as exc:
        return None, "could not be listed: {}".format(exc)
    return {name for name in names if name != INDEX}, None


def compare(on_disk, shipped):
    """`(on_disk_only, shipped_only)` -- both directions, never one number."""
    return sorted(set(on_disk) - set(shipped)), sorted(set(shipped) - set(on_disk))


def _normalize(text):
    """Line endings and trailing whitespace only, never a content transform. CI runs
    Windows legs where a checkout can arrive with CRLF.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines)


# --- controls, first, so the assertions below cannot pass for the wrong reason -------


def test_control_a_matching_pair_of_sets_reports_nothing():
    """The must-not-fire half. Without the two must-fire controls beside it, an
    always-empty `compare` would satisfy every assertion in this file.
    """
    assert compare({"a.md", "b.md"}, {"a.md", "b.md"}) == ([], [])


def test_control_an_entry_on_disk_and_not_shipped_is_caught():
    """This issue's own direction: the file is discarded on the next scaffold."""
    assert compare({"a.md", "b.md"}, {"a.md"}) == (["b.md"], [])


def test_control_an_entry_shipped_and_not_on_disk_is_caught():
    """The other direction: a rule written into other people's repositories that
    this one is not dogfooding.
    """
    assert compare({"a.md"}, {"a.md", "b.md"}) == ([], ["b.md"])


def test_control_the_index_is_not_counted_as_an_entry(tmp_path):
    layer = tmp_path / ".claude" / "jit-context" / "vocabulary" / oss_rules.LAYER
    layer.mkdir(parents=True)
    (layer / INDEX).write_text("k\tv.md\n", encoding="utf-8")
    (layer / "v.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    entries, problem = layer_entries(tmp_path, "vocabulary")
    assert problem is None
    assert entries == {"v.md"}


def test_a_dimension_that_cannot_be_read_is_a_third_state_not_an_empty_set(tmp_path):
    """`(None, reason)` rather than `(set(), None)`. An unreadable directory and a
    directory with no rules in it are the two things this repository exists to keep
    apart, and the pass they would share here would be a clean report about a layer
    nothing looked at.
    """
    entries, problem = layer_entries(tmp_path, "vocabulary")
    assert entries is None
    assert problem, "a third state with no reason is a shrug"


# --- the invariant itself ------------------------------------------------------------


def test_the_dimensions_on_disk_and_in_the_generator_are_the_same_set():
    on_disk = sorted(
        name
        for name in os.listdir(str(LAYER_ROOT))
        if (LAYER_ROOT / name / oss_rules.LAYER).is_dir()
    )
    assert on_disk == sorted(oss_rules.RULES), (on_disk, sorted(oss_rules.RULES))


def test_every_dimension_ships_exactly_the_entries_it_carries_on_disk():
    findings = []
    for dimension in sorted(oss_rules.RULES):
        entries, problem = layer_entries(REPO_ROOT, dimension)
        if problem:
            findings.append("{}: could not compare -- {}".format(dimension, problem))
            continue
        on_disk_only, shipped_only = compare(entries, oss_rules.RULES[dimension])
        for name in on_disk_only:
            findings.append(
                "{}/{}: in this repository's layer and shipped by nobody -- "
                "install() deletes the layer before rewriting it, so the next "
                "/oss:scaffold --apply discards this file (#702)".format(dimension, name)
            )
        for name in shipped_only:
            findings.append(
                "{}/{}: shipped into every scaffolded repository and not carried "
                "here, so this repository is not dogfooding a rule it writes into "
                "other people's (#702)".format(dimension, name)
            )
    assert not findings, findings


def test_every_static_rule_body_matches_its_tracked_copy():
    """The generalisation of #577's pairwise check to the whole set.

    A body that has drifted in only one copy is the failure #570 demonstrated: the
    `requires:` paragraph went stale in both the tracked `.md` and the generator's
    constant, and was only caught because one lane happened to hold both files.
    """
    findings = []
    for dimension in sorted(oss_rules.RULES):
        for name in sorted(oss_rules.RULES[dimension]):
            if (dimension, name) in RENDERED_PER_TREE:
                continue
            tracked = LAYER_ROOT / dimension / oss_rules.LAYER / name
            try:
                on_disk = tracked.read_text(encoding="utf-8")
            except OSError as exc:
                findings.append("{}/{}: could not be read -- {}".format(dimension, name, exc))
                continue
            if _normalize(on_disk) != _normalize(oss_rules.RULES[dimension][name]):
                findings.append(
                    "{}/{}: the tracked copy and the generator constant have "
                    "diverged -- the generator is what gets written into every "
                    "scaffolded repository, where nobody here will see it go "
                    "wrong (#577, #702)".format(dimension, name)
                )
    assert not findings, findings


def test_a_named_exception_is_still_an_exception():
    """An exception list that has drifted is a licence. Each entry here claims its
    body genuinely differs between the two copies because it renders per tree; if one
    stops differing, the carve-out is no longer earned and this fails rather than
    silently widening the set of things nobody compares.
    """
    for dimension, name in sorted(RENDERED_PER_TREE):
        tracked = (LAYER_ROOT / dimension / oss_rules.LAYER / name).read_text(
            encoding="utf-8"
        )
        assert _normalize(tracked) != _normalize(oss_rules.RULES[dimension][name]), (
            "{}/{} no longer differs from the generator's default rendering, so its "
            "entry in RENDERED_PER_TREE is exempting a pair that could now simply be "
            "compared".format(dimension, name)
        )
