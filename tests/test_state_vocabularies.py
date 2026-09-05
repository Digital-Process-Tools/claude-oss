"""One state name, two meanings -- swept across every vocabulary in scripts/ (#134).

`state` is a key that exists to be branched on. #134 was filed because one name
covered two unrelated situations and nothing complained: the moment somebody writes
`if finding["state"] == "unreadable"` they get both arms.

This is the sweep, and it is a **registry**, not a discovery run. Every state name
emitted from more than one site in one vocabulary has to be listed below with a
sentence saying why the sites mean the same thing. Adding a brand-new state name
costs nothing here. Adding a *second site for a name that already exists* -- the
#134 shape -- fails until somebody either renames it or writes the sentence.

Three outcomes, because two would put this file in the class it was written to
catch:

  clean                 every module parsed, states were found, none collides
  collisions            a multi-site state that is not in the registry
  could-not-enumerate   a module would not read or would not parse, OR the scan
                        found no vocabularies at all

`could-not-enumerate` wins over both of the others. A scan that could not look must
never render as a scan that found nothing, and a scan of an empty set is trivially
collision-free -- which is why the vacuity case is folded into the same outcome
rather than reported as `clean`.

## What this cannot see, stated rather than left out

The enumerator reads source. It resolves a string literal and a module-level
`STATE_* = "..."` constant, at a dict literal or at a `payload["state"] = ...`
assignment. It cannot resolve a state that comes back from a call -- those are
counted in `UNRESOLVED_SITES` rather than dropped -- and it cannot see the case
#134 itself reports.

That last one is the honest limit and it is worth spelling out. `check_test_ci`
emits `unreadable` from exactly **one** site, so no collision below flags it; the
three distinct causes behind it (`.github/workflows/` unwalkable, a child entry that
would not stat, a file that would not read) are folded upstream, into the one list
`_workflow_scan` and `_workflow_texts` build. A cause fan-in behind a single literal
is dataflow, not a countable site, and no static pass here finds it.

What a static pass *can* do is refuse to let one be invisible, which is what
`FAN_IN_STATES` below is. The fan-in is declared, the causes are pinned against a
tuple `scaffold.py` itself exports, and the dynamic guard that drives all three is
named -- so deleting or renaming that guard fails here rather than leaving a state
nobody checks. Whether the guard *observed* anything is its own assertion, made at
runtime where the causes are, and this file does not claim otherwise. So this guard
narrows the class; it does not close it.

It also once had a blind spot of its own shape, which is what `MERGED_VOCABULARIES`
is for: a per-function scan is the wrong unit when a function fans a helper's
findings into its own returned list, and it reported `scaffold.check_metadata` clean
by splitting one vocabulary in two at a function boundary.

It also only reads the key `state`. Two vocabularies in this plugin are shaped like
states and are not spelled that way, so nothing below is evidence about either:
`doctor.agent_dispatch` returns `(level, message)` pairs over OK/WARN/FAIL, and
`oss_config._ignore_rule` returns a bare `(state, detail)` tuple over
clear/ignored/unknown. Said here rather than left out -- a vocabulary missing from a
sweep reads exactly like a vocabulary the sweep cleared.

## Decided locally, or derived from another module

Worth knowing per vocabulary, because the expensive failures here are compositional
rather than local. #126 taught `scaffold` to decline the owned changelog trio, and
`doctor.owned_drift` went on reporting all three files as `absent` with the remedy
"Run /oss:scaffold" -- a command that would decline again. Both commits were correct
on their own.

  doctor.owned_drift          DERIVED. `declined` and one of the five `unknown`
                              arms come from `scaffold.check_changelog_gate`, via
                              `doctor._gate_verdict`, which maps every state that
                              is not `found` onto `unknown` on purpose. A state
                              added to that scaffold function lands here as
                              `unknown` rather than as a break -- and rather than
                              as a wrong answer.
  doctor.dependency_findings  LOCAL, off `compare_versions`.
  release_delta / _publish    LOCAL. Both read `.oss.json` for policy, but every
                              state is decided in the module that prints it.
  scaffold.check_*            LOCAL to scaffold, and consumed by `doctor` as
                              `finding["detail"]` only -- which is why #134 was
                              invisible and why it was still worth filing.
  oss_config.verify_*         LOCAL.

## The site counts, and why they stay

`MULTI_SITE_STATES` and `UNRESOLVED_SITES` pin a NUMBER, not a property, so a
correct change in `scripts/` fails a test in `tests/` with a message saying what to
write. #153 wrote it that way partly because it could not edit `scaffold.py` or
`oss_config.py` at all -- a cross-lane pin -- and that constraint is gone: #134's
follow-up owns both files and changed one.

The count still stays, on its own merits. The value of this registry is the
sentence, and a sentence nobody is forced to re-read decays into boilerplate: a
third arm arriving under a two-arm reason is exactly how a collision gets absorbed
rather than noticed. Nothing static can check that a new arm still means what the
sentence says, so the count is what makes somebody look. It is a deliberate cost
paid on a rare event, not an accident of who owned which file.
"""

import ast
import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

# The scripts that emit a `state` vocabulary. Named rather than globbed: a glob that
# silently matched nothing would make every assertion below trivially true, and
# "no module emits a state" is precisely the absence this file must not produce.
STATE_EMITTING_SCRIPTS = (
    "doctor.py",
    "oss_config.py",
    "release_delta.py",
    "release_publish.py",
    "release_version.py",
    "scaffold.py",
)

# (module, vocabulary, state) -> (site count, why the sites mean one thing).
#
# The sentence is the point. A count on its own is a boolean wearing a number, and a
# registry of booleans is what let #134 sit in the tree unnoticed.
MULTI_SITE_STATES = {
    ("doctor.py", "owned_drift", "absent"): (
        2,
        "both say the file is not in this repo and /oss:scaffold would write it. They "
        "differ only in how that was established: one file is outside "
        "scaffold.CHANGELOG_OWNED, so no gate governs it and the answer needs no gate "
        "read (#479); the other is inside it and the gate came back `write`. Same "
        "state, same detail sentence, same remedy -- a caller branching on `state` "
        "has nothing to tell apart, and owned_drift_summary groups them into one line "
        "for exactly that reason.",
    ),
    ("doctor.py", "owned_drift", "unknown"): (
        5,
        "all five say this owned file's drift could not be determined -- the plugin's "
        "own copy would not render, the repo's copy would not stat or would not read, "
        "or the changelog-gate verdict behind an absent file came back unknown. One "
        "meaning, one remedy, and owned_drift_summary groups on the detail so the "
        "five never collapse into one line.",
    ),
    ("oss_config.py", "verify_test_command", "not-found"): (
        3,
        "all three say the runner is not there -- absent from PATH before anything "
        "ran, an OSError on spawn, or the shell's own 127/9009 afterwards. The remedy "
        "is `install it` in every case, which is what keeps this apart from `failed`.",
    ),
    ("release_publish.py", "execute", "could-not-create"): (
        2,
        "the call raised, or it exited non-zero. Both mean gh was invoked and no "
        "release exists, which is the single distinction this state carries against "
        "`created`.",
    ),
    ("scaffold.py", "check_metadata", "unknown"): (
        2,
        "the probe carries neither topics key, or its entries are a shape this cannot "
        "read. Both say topics were not checked, which is not the same as this repo "
        "having none. Recorded against `check_metadata` rather than `_check_topics` "
        "because MERGED_VOCABULARIES folds the helper into the list its caller "
        "returns -- see there.",
    ),
    ("scaffold.py", "check_metadata", "missing"): (
        2,
        "no description, or no topics. Two situations under one state name, in ONE "
        "list handed to ONE consumer -- the #134 shape exactly, and invisible to a "
        "per-function scan because the second site sits inside `_check_topics`. Kept "
        "rather than renamed because the discriminator already exists and is already "
        "carried: this vocabulary is keyed by the pair (field, state), and every "
        "finding the function returns has a `field`. Renaming to "
        "`description-missing` / `topics-missing` would spell the field twice. That "
        "sentence is only true while `field` is always there, so it is not left as a "
        "sentence -- tests/test_repo_metadata.py::"
        "test_the_metadata_vocabulary_is_keyed_by_field_and_state_together drives "
        "both sites and asserts it.",
    ),
}

# (module, caller) -> the helpers whose findings arrive inside the caller's own
# returned list. Folded together before collisions are looked for.
#
# Per-function granularity is the wrong unit for a function that fans a helper's
# findings into its own list. `check_metadata` appends whatever `_check_topics`
# returns and hands back one list, so a caller sees one vocabulary and has one
# `state` key to branch on. Swept apart, `missing` looked like two vocabularies each
# using the word once -- a clean answer produced by where a function boundary happened
# to fall, which is this repository's own defect class wearing a scan result's
# clothes.
#
# A declaration here is a claim about the code, so it is checked rather than trusted:
# `test_every_merged_vocabulary_declaration_is_true` asserts the caller really does
# call the callee. A stale merge would union two vocabularies that no longer meet and
# manufacture a collision -- the opposite error, and equally unwanted.
MERGED_VOCABULARIES = {
    ("scaffold.py", "check_metadata"): ("_check_topics",),
}

# (module, vocabulary, state) -> (causes, guard file, guard test name).
#
# The limit this file's docstring names, given teeth. A state emitted from ONE site
# and reached by several distinct situations is dataflow: no static pass here can see
# it, and #134's surviving instance is one of them. What a static pass CAN do is
# refuse to let such a state be invisible. Each one is listed, with the causes it
# folds and the dynamic guard that drives every one of them through a fixture.
#
# Three properties, and the third is deliberately not claimed:
#
#   * the causes match the tuple the module itself exports, so the table and the code
#     cannot drift apart in silence;
#   * the named guard exists in the tree, so renaming or deleting it fails here rather
#     than leaving a table pointing at nothing;
#   * whether that guard actually OBSERVED all of them is its own assertion, made at
#     runtime where the causes are. Said out loud rather than implied: a registry that
#     looked like it proved observation would be exactly the absence this repo is
#     named after.
FAN_IN_STATES = {
    ("scaffold.py", "check_test_ci", "unreadable"): (
        ("directory-unwalkable", "entry-unstattable", "file-unreadable"),
        "tests/test_scaffold.py",
        "test_the_three_causes_behind_one_unreadable_state_are_each_observed",
    ),
}

# module -> {vocabulary: how many sites hand `state` a value this cannot resolve}.
# Recorded, never ignored: an unresolved site is a hole in the sweep and a reader is
# entitled to know how big it is.
UNRESOLVED_SITES = {
    "doctor.py": {
        # `compare_versions(...)` -> current / behind / ahead / unknown.
        "dependency_findings": 1,
        # `_jit_layer_verdict(...)` -> reads / reads-by-glob / unread /
        # could-not-determine / no-layer.
        # Seven causes fan into one emission on purpose, so the level table has one place
        # to consult. That is the fan-in this file's docstring says no static pass here
        # can see -- and the compensating guard is named rather than assumed:
        # `tests/test_jit_layer_readers.py::test_every_state_this_check_emits_has_a_level`
        # drives all five states through fixtures, asserts the set was *observed*, and
        # only then checks `doctor.JIT_LAYER_LEVELS` against it.
        "jit_layer_readers": 1,
    },
}


def _module_states(source, label="<source>"):
    """``(vocabularies, unresolved, error)`` for one module's text. Never raises.

    ``vocabularies`` is ``{function: {state: [line, ...]}}``; ``unresolved`` is
    ``[(function, line), ...]``; a non-empty ``error`` means nothing else in the
    tuple is evidence about anything.
    """
    try:
        tree = ast.parse(source, label)
    except (SyntaxError, ValueError) as exc:
        return {}, [], "{0}: {1}".format(type(exc).__name__, exc)

    constants = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not (
            isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        ):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = node.value.value

    vocabularies = {}
    unresolved = []
    stack = []

    def resolve(value):
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        if isinstance(value, ast.Name) and value.id in constants:
            return constants[value.id]
        return None

    def record(value, lineno):
        where = ".".join(stack) or "<module>"
        name = resolve(value)
        if name is None:
            unresolved.append((where, lineno))
            return
        vocabularies.setdefault(where, {}).setdefault(name, []).append(lineno)

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Dict(self, node):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "state":
                    record(value, getattr(value, "lineno", node.lineno))
            self.generic_visit(node)

        def visit_Assign(self, node):
            # `result["state"] = STATE_CREATED` -- release_publish.execute reaches two
            # of its five states this way, and a dict-literal-only scan sees neither.
            for target in node.targets:
                if not isinstance(target, ast.Subscript):
                    continue
                index = target.slice
                if isinstance(index, ast.Constant) and index.value == "state":
                    record(node.value, node.lineno)
            self.generic_visit(node)

    Visitor().visit(tree)
    return vocabularies, unresolved, ""


def _fold_merges(label, vocabularies, merges):
    """Fold a helper's states into the caller whose list they arrive in.

    ``merges`` is ``{(label, caller): (callee, ...)}``. The callee's entry is removed
    once folded: leaving it would report the same site under two names and double
    every count in the registry.

    A callee named for a caller that does not exist here, or a callee this module has
    no vocabulary for, is left alone rather than guessed at --
    ``test_every_merged_vocabulary_declaration_is_true`` is what turns a stale
    declaration into a failure, and doing it here as well would fail the wrong test
    with the wrong message.
    """
    for (merge_label, caller), callees in sorted(merges.items()):
        if merge_label != label or caller not in vocabularies:
            continue
        for callee in callees:
            for state, lines in vocabularies.pop(callee, {}).items():
                vocabularies[caller].setdefault(state, []).extend(lines)
    return vocabularies


def sweep(sources, reasons=None, merges=None):
    """``sources`` is ``{label: text}``. Returns the three-outcome report.

    ``text`` may be ``None``, which is how "this module would not be read" reaches
    here -- an error, not an empty module. ``reasons[label]`` says why, when there
    is a why to say. ``merges`` is MERGED_VOCABULARIES, or a fixture's own.
    """
    reasons = reasons or {}
    merges = merges or {}
    report = {
        "outcome": "clean",
        "collisions": [],
        "unresolved": {},
        "errors": [],
        "vocabularies": {},
    }
    for label in sorted(sources):
        text = sources[label]
        if text is None:
            report["errors"].append(
                "{0}: could not be read{1}".format(
                    label, ": " + reasons[label] if reasons.get(label) else ""
                )
            )
            continue
        vocabularies, unresolved, error = _module_states(text, label)
        if error:
            report["errors"].append("{0}: {1}".format(label, error))
            continue
        vocabularies = _fold_merges(label, vocabularies, merges)
        report["vocabularies"][label] = vocabularies
        for function, states in vocabularies.items():
            for state, lines in states.items():
                if len(lines) > 1:
                    report["collisions"].append((label, function, state, sorted(lines)))
        for function, _line in unresolved:
            per_module = report["unresolved"].setdefault(label, {})
            per_module[function] = per_module.get(function, 0) + 1

    found_any = any(report["vocabularies"][label] for label in report["vocabularies"])
    if report["errors"] or not found_any:
        # Both arms are the same fact: this scan is not evidence. An empty scan is
        # collision-free the way an unrun check is finding-free.
        report["outcome"] = "could-not-enumerate"
    elif report["collisions"]:
        report["outcome"] = "collisions"
    report["collisions"].sort()
    return report


def _printable(text):
    """One line, printable ASCII only.

    A read failure's message carries a path somebody else chose, and it ends up in an
    assertion message pytest writes to stdout. On Windows that write is encoded with
    the console's codepage rather than this file's -- typically cp1252 -- where one
    character out of range raises `UnicodeEncodeError` and kills the run at the
    report, after the sweep it was reporting on already finished. Flattened here so
    the failure that reaches a reader is the one that happened.
    """
    flat = " ".join(str(text).split())
    return "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in flat)


def _read_scripts():
    """``(sources, reasons)``. A module that would not read is ``None`` with a why.

    Never printed, only returned: a `print` here would be a second place the failure
    can die, and it is the place the encoding gets chosen by the console.
    """
    sources = {}
    reasons = {}
    for name in STATE_EMITTING_SCRIPTS:
        path = SCRIPTS / name
        try:
            # Explicit, because the default encoding is the console's on Windows and
            # a module here carries characters cp1252 has no room for.
            sources[name] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            sources[name] = None
            reasons[name] = _printable("{0}: {1}".format(type(exc).__name__, exc))
    return sources, reasons


@pytest.fixture(scope="module")
def shipped():
    sources, reasons = _read_scripts()
    return sweep(sources, reasons, MERGED_VOCABULARIES)


# --- the guard's own three outcomes, each with a case that reaches it ----------


def test_a_module_that_will_not_parse_is_could_not_enumerate_and_never_clean():
    report = sweep({"broken.py": "def f(:\n"})
    assert report["outcome"] == "could-not-enumerate", report
    assert report["errors"], "an unparseable module produced no error line"


def test_a_module_that_will_not_read_is_could_not_enumerate_and_never_clean():
    report = sweep({"gone.py": None})
    assert report["outcome"] == "could-not-enumerate", report
    assert "gone.py" in report["errors"][0]

    # And the reason travels with it, flattened to printable ASCII. The error line
    # reaches a reader through an assertion message pytest writes to stdout, and on
    # Windows that write is encoded with the console's codepage: an em dash or a
    # non-ASCII path in an OS error would raise UnicodeEncodeError and take the run
    # out at the report rather than at the fault.
    detailed = sweep(
        {"gone.py": None}, {"gone.py": _printable("OSError: — café\nline 2")}
    )
    assert detailed["errors"] == ["gone.py: could not be read: OSError: ? caf? line 2"]
    assert all(32 <= ord(ch) < 127 for ch in detailed["errors"][0])


def test_an_empty_scan_is_could_not_enumerate_rather_than_clean():
    """The vacuity control. Nothing scanned is trivially collision-free."""
    assert sweep({})["outcome"] == "could-not-enumerate"
    assert sweep({"quiet.py": "x = 1\n"})["outcome"] == "could-not-enumerate"


def test_the_enumerator_sees_a_collision_a_reader_can_see():
    """The positive control for `clean`, in the same fixture as the negative one.

    Without this pair, `no collisions found` is a sentence the scan prints whether or
    not it is able to find one.
    """
    colliding = (
        "def check(x):\n"
        "    if x:\n"
        "        return {'state': 'unreadable', 'detail': 'the file'}\n"
        "    return {'state': 'unreadable', 'detail': 'the directory'}\n"
    )
    report = sweep({"m.py": colliding})
    assert report["outcome"] == "collisions", report
    assert report["collisions"] == [("m.py", "check", "unreadable", [3, 4])]

    distinct = (
        "def check(x):\n"
        "    if x:\n"
        "        return {'state': 'unreadable', 'detail': 'the file'}\n"
        "    return {'state': 'unwalkable', 'detail': 'the directory'}\n"
    )
    assert sweep({"m.py": distinct})["outcome"] == "clean"


def test_a_state_set_by_assignment_is_seen_not_missed():
    """`payload["state"] = X` is how release_publish.execute reaches two of its five."""
    source = "DONE = 'created'\ndef execute(p):\n    p['state'] = DONE\n    return p\n"
    report = sweep({"m.py": source})
    assert report["vocabularies"]["m.py"]["execute"] == {"created": [3]}


def test_a_state_the_scan_cannot_resolve_is_counted_not_dropped():
    source = "def f(x):\n    return {'state': compare(x), 'detail': ''}\n"
    report = sweep({"m.py": source})
    assert report["unresolved"] == {"m.py": {"f": 1}}
    # And it does not masquerade as a vocabulary that was fully read.
    assert report["vocabularies"]["m.py"] == {}
    assert report["outcome"] == "could-not-enumerate", (
        "a module whose only state site could not be resolved was reported as "
        "enumerated"
    )


# --- the sweep over what this repo actually ships ------------------------------


def test_every_state_emitting_script_was_read_and_produced_a_vocabulary(shipped):
    for name in STATE_EMITTING_SCRIPTS:
        assert name in shipped["vocabularies"], "{0} was not enumerated: {1}".format(
            name, shipped["errors"]
        )
        assert shipped["vocabularies"][name], (
            "{0} parsed and yielded no state vocabulary at all -- either it stopped "
            "emitting states, in which case take it off STATE_EMITTING_SCRIPTS, or "
            "the enumerator stopped seeing them".format(name)
        )


def test_no_module_failed_to_enumerate(shipped):
    assert not shipped["errors"], shipped["errors"]


def test_every_multi_site_state_is_registered_with_a_reason(shipped):
    """The #134 guard itself.

    A second site for a state name that already exists in the same vocabulary is the
    shape that was filed. It is allowed -- two code paths can honestly reach one
    state -- but only on the record.
    """
    seen = dict(((m, f, s), lines) for m, f, s, lines in shipped["collisions"])
    unregistered = sorted(key for key in seen if key not in MULTI_SITE_STATES)
    assert not unregistered, (
        "state name(s) emitted from more than one site in one vocabulary and not in "
        "MULTI_SITE_STATES: {0}. Either rename one site so the two situations are "
        "tellable apart by a caller that branches on `state`, or add an entry saying "
        "why they are one thing.".format(
            [
                "{0}:{1}:{2} at {3}".format(m, f, s, seen[(m, f, s)])
                for m, f, s in unregistered
            ]
        )
    )
    stale = sorted(key for key in MULTI_SITE_STATES if key not in seen)
    assert not stale, (
        "MULTI_SITE_STATES lists {0}, which the sweep no longer finds. A registry "
        "entry for a collision that is gone is a sentence nobody will "
        "re-check.".format(stale)
    )
    for key in sorted(MULTI_SITE_STATES):
        count, why = MULTI_SITE_STATES[key]
        assert len(seen[key]) == count, (
            "{0} now has {1} site(s), registered as {2}: {3}".format(
                key, len(seen[key]), count, seen[key]
            )
        )
        assert why.strip(), "{0} is registered with no reason".format(key)


def test_unresolved_state_sites_match_what_is_recorded(shipped):
    assert shipped["unresolved"] == UNRESOLVED_SITES, (
        "the set of state values this scan could not resolve changed. Every one is a "
        "hole in the sweep: record it in UNRESOLVED_SITES with what the call returns, "
        "or hand the site a literal. Found {0}, recorded {1}".format(
            shipped["unresolved"], UNRESOLVED_SITES
        )
    )


def test_release_publish_keeps_its_two_vocabularies_under_different_keys(shipped):
    """`notes_section` answers about the changelog; `plan`/`execute` about the release.

    Both used to return their answer under `state`, in one module, and `receipt` and
    `_exit_code` accept any dict -- so a notes payload reaching either printed
    `state: FOUND` at the top of a release receipt. Nothing routed one there, which
    is exactly the #134 argument: the collision costs nothing until somebody writes
    the obvious line.
    """
    functions = shipped["vocabularies"]["release_publish.py"]
    assert "notes_section" not in functions, (
        "notes_section emits `state` again; its vocabulary (found/empty/missing) is "
        "not the publish lifecycle's and must not share the key"
    )


# --- vocabularies that arrive merged, and states that arrive fanned in ---------


def test_a_helper_folded_into_its_caller_makes_a_hidden_collision_visible():
    """The positive control for the merge machinery, on a fixture showing both
    readings of one source.

    Apart, each function uses `missing` once and the sweep is clean. Together --
    which is what the single returned list actually is -- it is a collision. Without
    this pair, folding could quietly do nothing and every merged registry entry would
    be a sentence about a union that never happened.
    """
    source = (
        "def _topics(p):\n"
        "    return {'field': 'topics', 'state': 'missing'}\n"
        "def check(p):\n"
        "    out = [{'field': 'description', 'state': 'missing'}]\n"
        "    out.append(_topics(p))\n"
        "    return out\n"
    )
    apart = sweep({"m.py": source})
    assert apart["outcome"] == "clean", apart
    assert apart["collisions"] == []

    together = sweep({"m.py": source}, merges={("m.py", "check"): ("_topics",)})
    assert together["outcome"] == "collisions", together
    assert together["collisions"] == [("m.py", "check", "missing", [2, 4])]
    assert "_topics" not in together["vocabularies"]["m.py"], (
        "the folded helper is still listed on its own, so every site it owns is "
        "counted twice"
    )


def test_a_merge_declared_for_a_function_that_is_not_there_folds_nothing():
    """A stale declaration must not invent a vocabulary. It fails in the test that
    reads the source, not here, and here it has to be inert."""
    source = "def check(p):\n    return {'state': 'missing'}\n"
    report = sweep({"m.py": source}, merges={("m.py", "check"): ("gone",)})
    assert report["outcome"] == "clean", report
    assert report["vocabularies"]["m.py"] == {"check": {"missing": [2]}}


def test_every_merged_vocabulary_declaration_is_true(shipped):
    """Each caller in MERGED_VOCABULARIES really does call each callee.

    Read off the source rather than trusted, because a merge nobody re-checks unions
    two vocabularies that stopped meeting -- which manufactures a collision instead
    of hiding one, and is just as wrong.
    """
    assert MERGED_VOCABULARIES, "the merge registry is empty -- the checks are vacuous"

    # A callee declared under two callers folds into the first one and then silently
    # into nothing, because `_fold_merges` pops it. Nothing today does that, and
    # nothing may: a second declaration would look exactly like a fold that happened.
    # Refused here rather than defended in the fold, so the message names the registry
    # line to change.
    claimed = {}
    for (label, caller), callees in sorted(MERGED_VOCABULARIES.items()):
        for callee in callees:
            assert (label, callee) not in claimed, (
                "MERGED_VOCABULARIES folds {0}:{1} into both {2} and {3}. It is popped "
                "on the first fold, so the second one would quietly union "
                "nothing.".format(label, callee, claimed[(label, callee)], caller)
            )
            claimed[(label, callee)] = caller

    for (label, caller), callees in sorted(MERGED_VOCABULARIES.items()):
        path = SCRIPTS / label
        tree = ast.parse(path.read_text(encoding="utf-8"), label)
        defs = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == caller
        ]
        assert defs, "MERGED_VOCABULARIES names {0}:{1}, which does not exist".format(
            label, caller
        )
        called = set(
            node.func.id
            for node in ast.walk(defs[0])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        )
        for callee in callees:
            assert callee in called, (
                "MERGED_VOCABULARIES folds {0}:{1} into {0}:{2}, but {2} no longer "
                "calls it. Drop the entry, or two vocabularies are being unioned for "
                "no reason.".format(label, callee, caller)
            )


def test_every_fan_in_state_is_single_site_and_names_a_guard_that_exists(shipped):
    """The compensating guard for the thing this file's docstring cannot see.

    Three assertions, because each catches a different way the record goes stale:

    * the state is still emitted from exactly one site, so it is still invisible to
      the static pass and this entry is still the right home for it;
    * the causes still match what the module itself exports, so table and code cannot
      drift apart;
    * the dynamic guard still exists under the name recorded, so a rename fails here
      rather than leaving a table pointing at nothing.

    What is NOT asserted, said rather than implied: that the guard observed anything.
    That claim belongs to the guard, at runtime, where the causes are.
    """
    assert FAN_IN_STATES, "the fan-in registry is empty -- every check below is vacuous"
    for key in sorted(FAN_IN_STATES):
        label, function, state = key
        causes, guard_file, guard_test = FAN_IN_STATES[key]
        sites = shipped["vocabularies"].get(label, {}).get(function, {}).get(state)
        assert sites, "{0}:{1} no longer emits {2!r} at all".format(
            label, function, state
        )
        assert len(sites) == 1, (
            "{0}:{1}:{2} is now emitted from {3} sites, so the static sweep can see "
            "it and MULTI_SITE_STATES is where it belongs -- not here".format(
                label, function, state, len(sites)
            )
        )

        module = importlib.import_module(Path(label).stem)
        exported = tuple(getattr(module, "WORKFLOW_SCAN_CAUSES", ()))
        assert tuple(causes) == exported, (
            "{0} exports causes {1!r}; FAN_IN_STATES records {2!r}".format(
                label, exported, tuple(causes)
            )
        )

        guard = REPO_ROOT / guard_file
        text = guard.read_text(encoding="utf-8") if guard.exists() else ""
        assert "def {0}(".format(guard_test) in text, (
            "FAN_IN_STATES points at {0}::{1}, which is not there. The causes behind "
            "{2}:{3}:{4} are dataflow and nothing static sees them, so that test is "
            "the only thing between this state and the absence it hides.".format(
                guard_file, guard_test, label, function, state
            )
        )
