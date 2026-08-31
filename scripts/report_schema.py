#!/usr/bin/env python3
"""Validate an agent report against schemas/agent-report.schema.json.

A dependency-free checker for the subset of JSON Schema the report actually uses --
type, required, properties, additionalProperties, enum, const, items, $ref, allOf --
plus the cross-field rules that are the whole point of the document and that JSON
Schema says expensively: a survey that nobody checked has to say why and must carry no
items; a refusal has to carry its argument; a test phase that was observed has to carry
a result and one that was not has to carry a reason.

What this refuses is exactly the schema's x-enforced list, and every name in that list
is paired with a mutation in tests/test_agent_report_schema.py, so the list cannot
quietly grow past the code. Everything in x-convention is unchecked and says so there.

This validates shape, never truth. Nothing here can tell a review that ran from one
that claims it did. That limit is the reason findings carry sentences instead of
booleans -- the sentence is what an orchestrator can still argue with.

  python3 scripts/report_schema.py REPORT.json [REPORT.json ...]

Three verdicts, three exit codes, because two of them used to be one. `ok` is 0 and
`INVALID` is 1; `UNVALIDATABLE` is 2 and means this copy does not hold the contract the
report names -- a newer report, an older one it cannot vouch for, or a schema that does
not declare its own version. That is not the same as malformed, and printing it as
`INVALID` is how a correct report written yesterday reads as a broken one today. A
missing or unparseable file is an error, never a pass: a report that could not be read
is not a report with no findings.

An older contract is not automatically unreadable, though it was until #416: every
bump invalidated every in-flight lane's report on the strength of an integer
comparison, and the window was as long as a lane takes. The schema declares, per
version, whether it widened the version below it, and a chain of declared widenings
back to the report's own number means a document valid there is valid here -- so the
verdict is `ok` and the sentence says which contract it read and why. Nothing derives
that: a copy holds one schema, the older one is absent rather than unread, and an
undeclared step refuses. A real narrowing still answers `UNVALIDATABLE`.

Every verdict row names the contract it was decided against, on the pass as well as on
the failure. A validator that announces its version only when it objects cannot be
compared with another copy, which is the whole reason the announcement exists.

Handed the pull request payload instead of the report -- the two land in one directory
one suffix apart -- it says so by name and names the call to run. Enumerating the
fourteen report keys a correct payload lacks is accurate and useless: it reads as a
finding about the file rather than as a mistake by the caller, and the move it invites
is hand-writing `head`, the one value nothing downstream verifies.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "agent-report.schema.json"

# Keywords this validator implements. Anything else in a subschema is refused rather
# than skipped: a `minLength` or a `oneOf` written into the schema and quietly ignored
# is a constraint that reads as enforced and is not -- a guard nominally on, effectively
# off, which is the class of defect this whole document exists to make visible.
_KEYWORDS = {
    "type", "const", "enum", "required", "properties", "additionalProperties",
    "items", "$ref", "allOf",
    # ours
    "x-items", "x-rule",
    # the contract number and the relations between contracts, both read by the
    # version pass below rather than by _walk
    "x-schema-version", "x-schema-compatibility",
    # annotations, carried for readers and ignored on purpose
    "$schema", "$id", "$defs", "$comment", "title", "description", "examples",
    "x-honesty", "x-honesty-on-disk", "x-honesty-versioning", "x-honesty-compatibility",
    "x-honesty-compliance",
    "x-enforced", "x-enforced-on-disk", "x-convention",
}

# Keys that carry prose for a reader and change nothing a validator does. Stripped
# before the contract is fingerprinted, so rewording a description does not demand a
# version bump -- and so the guard on the bump does not train the reflex of moving the
# number to make CI green. x-schema-version is stripped too: the fingerprint answers
# "what does this contract require", which has to be independent of its own label or
# the comparison is circular.
# x-schema-compatibility is deliberately NOT stripped, and the first version of #416
# stripped it. The argument for stripping was that it is a claim about how contracts
# relate rather than a constraint a document satisfies, by analogy with
# x-schema-version -- and review took the analogy apart. x-schema-version is circular
# because the fingerprint RECORD IS KEYED BY IT; hashing the key would compare a value
# against a table that value selects. Nothing keys on the compatibility map. It decides
# which documents this validator accepts, which is precisely the enforcing-versus-
# annotation line x-honesty-versioning draws, and two failures were being conflated:
#
#   - a declaration wrong at the moment it was written. Uncatchable here, because
#     checking it needs the other schema, which this copy does not hold. Still true.
#   - a declaration EDITED afterwards with no bump. Entirely catchable, and it is #221's
#     own shape one layer up -- two installed copies both announcing version 5 and
#     disagreeing about whether a version-4 report is `ok` or UNVALIDATABLE.
#
# The prose about the map (x-honesty-compatibility) is stripped, like every other
# narrative. The map itself is inside.
_ANNOTATION_KEYS = {
    "title", "description", "examples", "$comment",
    "x-honesty", "x-honesty-on-disk", "x-honesty-versioning", "x-honesty-compatibility",
    "x-honesty-compliance",
    "x-convention",
    "x-schema-version",
}

# One entry per version this schema has ever declared, mapping it to the fingerprint of
# the enforcing content at that version. 1 is absent on purpose and always will be: it
# is what every report written before anyone counted says, across at least three
# mutually incompatible schemas, and no fingerprint can be recovered for a contract
# nobody recorded. Adding an entry here is the act of declaring a new contract.
#
# The keys are also the list of numbers that were ever contracts, which is what the
# compatibility chain walks: "the contract below N" is the largest RECORDED version
# under N, never N-1, so a gap in the numbering cannot make a version nobody declared
# look like a predecessor. Each note below says what its bump did to the contract below
# it, in the same words the schema's x-schema-compatibility declares in machine-readable
# form; they are two statements of one fact and they must agree.
CONTRACT_FINGERPRINTS = {
    2: "d687807f452f7aa4c4773519fcbc00ab3aff097c04facf1b5e2652bf931bcb70",
    # 3 (#254): the review-finding disposition `filed` is gone and
    # `report-for-filing` replaces it, and that value now needs a reason. Both
    # directions are breaking, which is why the number moved: a version-2 copy
    # refuses every version-3 report that uses the new word, and a version-3
    # copy refuses every version-2 report that used the old one.
    3: "940a1c68c40f5bca2c8f8a9a05cf32e241df709d0998a435db57b871caf0fcd5",
    # 4 (#274): pr_body carries `closes`, and a `written` payload is refused without
    # one. Breaking in both directions, which is why the number moved: a version-3
    # copy refuses every version-4 report because `closes` is an unknown key, and a
    # version-4 copy refuses every version-3 report because the key is absent.
    4: "eec52e1f12bdac241428aa446abae980fa8180ab4c348d6e076b232e3adbf37f",
    # 5 (#411): `below-bar` joins both filing enums, and an item using it carries a
    # `pr_anchor` the on-disk pass finds in the pull request body. ADDITIVE, and so
    # far the only bump that is: nothing was removed from an enum, nothing became
    # required, no pattern tightened, and the new rules fire only on an item that
    # takes the third receipt -- which no version-4 report can spell. The number
    # still moved, because breaking in ONE direction is breaking: a version-4 copy
    # refuses every version-5 report that takes the receipt, since the value is not
    # in its enum and `pr_anchor` is an unknown key. The two directions are separate
    # questions and this record answers the backwards one; x-schema-compatibility
    # declares the same thing where the validator can read it (#416).
    #
    # 5's fingerprint was RE-TAKEN at #416, from
    # 51f55eab...288a2e7cd, and the contract did not move with it. What moved is the
    # strip method: x-schema-compatibility went from annotation to enforcing content,
    # which semantic_fingerprint's own docstring says is re-recorded rather than
    # bumped, since the value is method-dependent and no document's requirements
    # changed. 2, 3 and 4 are NOT re-taken and cannot be: they hash documents that no
    # longer exist, so they were computed under whatever method shipped with them and
    # only the current version's entry is ever compared against anything.
    5: "bf53ecee7c14789b2cfd1144ec06588efc9b1c17f209803148df15cf6879de22",
    # 6 (#518): a top-level `compliance` survey, required, so a run can name an
    # instruction from its own brief it declined and why -- the observed gap was
    # a spawned reviewer misreading tracked policy as injected content and
    # dropping the tooling it named, with nothing in the report able to say so.
    # BREAKING, both directions: a version-5 copy refuses every version-6 report
    # because `compliance` is required and unknown to it; a version-6 copy
    # refuses every version-5 report because `compliance` is missing. Unlike #411
    # this is not additive -- the new key is required, not merely a new enum
    # member on an existing one, so an old document is no longer a subset.
    6: "fbdd6e52e6cff60b6a3b9f540bf3bd4c848094660c2b7a2e9a9303146659c99c",
    # 7 (#632): `tests.full`, optional, says whether the DEVELOPER lane's own
    # full-suite run happened -- three states (ran / not-run / could-not-run),
    # the same could-not-look-is-not-clean shape every other survey here uses.
    # Motivated by the manager's own doctrine that it never reproduces the
    # suite itself (skills/manager/phases/review.md): the report is the only
    # route by which the manager learns whether a local full run happened at
    # all, and on what platform. ADDITIVE: nothing removed, nothing newly
    # required, no pattern tightened -- an old report with no `full` key is
    # still valid, since `full` is optional and `tests`' own `required` list
    # is unchanged. The number still moved, because a version-6 copy refuses
    # any version-7 report carrying `full` (an unknown key under
    # additionalProperties: false), which is breaking in that one direction.
    7: "e6cdbcea7419317c93a8ce9d398c3814b8eb4541fb8afdc05925d750f4487067",
    # 8 (#698): forge_payload gains `no_close`, optional -- supertool's own field
    # for opening a pull request that deliberately closes nothing, which the
    # payload previously could not carry at all under additionalProperties:
    # false, so every such pull request this pipeline produced validated
    # INVALID by construction. ADDITIVE: nothing removed, nothing newly
    # required, no pattern tightened -- an old report with no `no_close` in its
    # payload is still valid. The number still moved, because a version-7 copy
    # refuses any version-8 payload carrying `no_close` (an unknown key under
    # forge_payload's own additionalProperties: false), which is breaking in
    # that one direction. The on-disk pass also gained one rule, paired with a
    # mutation test: a payload declaring `no_close: true` while its own body
    # still binds a closing keyword is refused.
    8: "184b54a76a33b8f5e4452a6759c2dea5e251cc96fa818dc36ee31d38bd80065e",
}

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "number": (int, float),
    "integer": int,
    "null": type(None),
}


def load_schema(path=None):
    path = Path(path) if path else SCHEMA_PATH
    return json.loads(path.read_text(encoding="utf-8"))


# --- the contract number ------------------------------------------------------
#
# schema_version was `const: 1` in every copy of the schema ever shipped, across at
# least three contracts that refuse each other's reports (#221). A frozen marker is
# worse than no marker: an unversioned artifact is honestly silent, while a version
# field that reads 1 whatever the contract is answers confidently and wrongly. And
# `const` did not merely fail to record a version -- it forbade recording one, so the
# remedy #212 proposed (have the validator announce which schema it validated against)
# would have printed 1 from both copies and CONFIRMED the skew rather than revealed it.
#
# The four states below are the whole point, and a report this copy cannot speak for
# must never be called invalid. Collapsing that into "invalid" recreates #212 one layer
# down: the maintainer hit exactly that on 2026-08-16, when a report written the day
# before came back as a bare `INVALID ... missing required key 'docs'` with nothing to
# distinguish an older contract from a malformed file.
#
# A copy of this validator holds exactly ONE contract document, so it cannot COMPUTE
# the relationship between its contract and another version's -- it does not have the
# other one, which is why #416 is answered by a declaration rather than by a comparison
# of two schemas. What it can do is read what the author recorded at each bump. That
# makes a newer report and an older one two different epistemic states rather than one:
# nothing here holds a claim about a contract that did not exist when this copy shipped,
# so a newer report is always unvalidatable, while an older one is unvalidatable only
# where the chain of declarations does not reach it.

VERSION_CURRENT = "current"
VERSION_READABLE = "readable"
VERSION_MISMATCH = "mismatch"
VERSION_UNDECIDABLE = "undecidable"

# The relation each contract declares to the contract below it, and the only three words
# that mean anything here. `additive` is the claim that every document valid under the
# predecessor is valid under this version -- nothing removed from an enum, nothing newly
# required, no pattern tightened -- which is what makes this copy able to answer about a
# report from that predecessor. Anything else, INCLUDING an absent entry and a word
# nobody recognises, is not readable: the failure of a bump that forgot to declare is
# silence, and silence has to land on the refusing side.
#
# It is a claim about the whole contract, NOT about the schema document alone, and the
# difference has teeth. The cross-field rules live in _RULES and in the functions
# validate() calls directly, and validate_pr_body() leaves the report entirely -- none
# of which the schema document describes. Declaring `additive` because only an optional
# key was added, while a rule in this file quietly started refusing something, makes
# every older report render as INVALID: a hard finding against a contract it was never
# written for, where before #416 the same finding printed under UNVALIDATABLE with "not
# necessarily defects in the report". So the declaration is a claim about this file too.
COMPAT_ADDITIVE = "additive"
COMPAT_BREAKING = "breaking"
COMPAT_UNKNOWN = "unknown"
COMPAT_VALUES = (COMPAT_ADDITIVE, COMPAT_BREAKING, COMPAT_UNKNOWN)

# 1 is not a contract and no declaration can make it one: it is the value every report
# written before anybody counted carries, across at least three mutually incompatible
# schemas, so a chain declared additive all the way down must still stop above it.
FIRST_CONTRACT = 2


def contract_version(schema):
    """The contract number the schema declares, or None if it declares none."""
    value = schema.get("x-schema-version") if isinstance(schema, dict) else None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def contract_compatibility(schema):
    """`{version: relation-to-the-version-below}`, as the schema declares it.

    Declared rather than derived, and that is the judgment this makes (#416). The
    alternative is comparing the two schema documents and deciding subset for
    itself -- but a copy of this validator holds exactly ONE document. The older
    schema is not unread, it is absent, so there is nothing to compare and the
    cleverness has no input. The author records the relation at the bump, which is
    the one moment anybody holds both contracts at once.

    A key that is not an integer, or a value that is not a string, is dropped
    rather than guessed at. It then reads as undeclared, which refuses.
    """
    raw = schema.get("x-schema-compatibility") if isinstance(schema, dict) else None
    if not isinstance(raw, dict):
        return {}
    declared = {}
    for key, value in raw.items():
        if isinstance(key, bool) or not isinstance(key, (int, str)):
            continue
        try:
            version = int(key)
        except (TypeError, ValueError):
            continue
        declared[version] = value if isinstance(value, str) else None
    return declared


def _previous_contract(version, record):
    """The contract immediately below `version` -- the largest RECORDED number under it.

    Not `version - 1`. The numbering is contiguous today and nothing says it stays
    that way, and decrementing through a gap invents a predecessor: a schema at 7
    whose real predecessor is 5 would read a report claiming 6 -- a number no
    contract ever had, so a typo or a forged value -- and refuse the genuine 5.
    Review found that; it was unreachable and wrong in both directions at once.
    """
    below = [known for known in record if known < version]
    return max(below) if below else None


def readable_from(schema, record=None):
    """The OLDEST contract this copy can still answer for, or None if it has no number.

    Walked step by step rather than read off a single `minimum-readable`, because
    the two fail in opposite directions. One number left unchanged through a
    breaking bump keeps vouching for contracts that stopped being subsets -- the
    accepts-everything-older failure #416 says must not be caused. A missing step
    declaration refuses, which costs a lane one relayed sentence.

    `record` is the set of numbers that were ever contracts, defaulting to
    CONTRACT_FINGERPRINTS. It is the chain's own footing: a version nobody recorded
    is a contract nobody described, and claiming a document from it is a subset of
    ours is a claim about a thing this copy has no record of.
    """
    ours = contract_version(schema)
    if ours is None:
        return None
    record = CONTRACT_FINGERPRINTS if record is None else record
    declared = contract_compatibility(schema)
    oldest = ours
    while declared.get(oldest) == COMPAT_ADDITIVE:
        below = _previous_contract(oldest, record)
        # FIRST_CONTRACT is the second lock rather than the first: `record` already
        # omits 1 on purpose and always will. Both are kept, because the floor is a
        # fact about the value 1 and not about any particular record a caller passes.
        if below is None or below < FIRST_CONTRACT:
            break
        oldest = below
    return oldest


def version_verdict(report, schema, record=None):
    """Return `(state, sentence)`: which contract this report claims, versus ours.

    Four states, and the two that are not `current` or `mismatch` are the ones
    doing the work:

    - `current`   -- the numbers agree. The sentence still names the number, because
                     announcing the contract on a PASS is the whole of #212's remedy.
    - `readable`  -- the report names an OLDER contract that WAS a contract, and every
                     step from it up to ours is declared additive, so a document valid
                     under it is valid under ours and this copy can answer about it
                     (#416). The sentence says so rather than passing as though the
                     numbers matched: `ok` and `ok, older contract, additive only` are
                     not the same claim. `record` is the set of numbers that were ever
                     contracts; a number outside it is nobody's contract and lands on
                     `mismatch` however the chain reads.
    - `mismatch`  -- both sides named a contract, they differ, and nothing declares
                     the difference away. A NEWER report always lands here: the
                     declarations only run backwards, and a widening chain behind us
                     says nothing about the step in front.
    - `undecidable` -- one side named nothing. A report with no version, or a schema
                     that does not declare its own, leaves nothing to compare; that is
                     not agreement, and answering `current` by default would be a
                     verdict produced by the absence of a disagreement.
    """
    ours = contract_version(schema)
    theirs = report.get("schema_version") if isinstance(report, dict) else None
    if isinstance(theirs, bool) or not isinstance(theirs, int):
        theirs = None

    if ours is None:
        return VERSION_UNDECIDABLE, (
            "the schema this copy loaded declares no x-schema-version, so it cannot say "
            "which contract it implements and cannot certify this report against it"
        )
    if theirs is None:
        return VERSION_UNDECIDABLE, (
            "this report names no schema_version, so there is nothing to compare with "
            "the contract this copy implements (version {})".format(ours)
        )
    if theirs == ours:
        return VERSION_CURRENT, "report schema version {}".format(ours)
    record = CONTRACT_FINGERPRINTS if record is None else record
    oldest = readable_from(schema, record)
    if oldest <= theirs < ours and theirs in record:
        return VERSION_READABLE, (
            "report schema version {}, read under version {} -- every contract "
            "change from {} to {} is declared additive, so a report written "
            "against {} is a document this copy holds the contract for. Not the "
            "same claim as a report written against {}.".format(
                theirs, ours, theirs, ours, theirs, ours
            )
        )
    newer = theirs > ours
    return VERSION_MISMATCH, (
        "this report was written against report schema version {} and this copy "
        "implements version {} -- {} contract, which this copy does not hold. That "
        "is not a defect in the report.{}".format(
            theirs, ours,
            "a newer" if newer else "an older",
            " Install a plugin copy at or above the one that wrote it."
            if newer else "",
        )
    )


# Maps whose keys are NAMES rather than schema keywords. Stripping by key name inside
# one of these deletes a real constraint: this document has a property literally called
# `title` at $defs/forge_payload/properties, which validate_pr_body enforces, and a
# strip that walked into it silently blessed retyping or deleting it. Found by review
# on the first version of this fingerprint (#221), which is exactly the failure mode a
# guard like this has -- it under-fires quietly and the guard still reports clean.
_NAME_MAPS = {"properties", "$defs"}


def _strip_annotations(node, keys_are_names=False):
    if isinstance(node, dict):
        return {
            key: _strip_annotations(value, key in _NAME_MAPS and not keys_are_names)
            for key, value in node.items()
            if keys_are_names or key not in _ANNOTATION_KEYS
        }
    if isinstance(node, list):
        return [_strip_annotations(item, False) for item in node]
    return node


def semantic_fingerprint(schema):
    """sha256 over what this schema ENFORCES, with the prose stripped.

    Not a hash of the file. A hash of the file would fire on every reworded
    sentence, which within a week teaches the reflex of bumping the version to
    make CI green -- and a number moved to silence a guard carries no more
    information than one that never moves at all.

    The enforcement LISTS are deliberately inside it, though nothing in _walk
    reads them: x-enforced and x-enforced-on-disk are the schema's own statement
    of what a validator refuses, paired one-to-one with a mutation table, so a
    change there is nearly always a contract change. The false positive is a
    rename and costs one recorded fingerprint; the false negative costs two
    copies claiming one version for two contracts.

    What it cannot see, said here rather than discovered later: this fingerprints
    the DOCUMENT. The cross-field rules live in _RULES as Python, and a contract
    change made entirely there -- a rule function that starts refusing something
    new, with no keyword moving in the schema -- changes what this validator
    accepts and leaves this hash untouched. That gap is real and unguarded.

    And the value is method-dependent: changing what gets stripped changes every
    fingerprint without changing any contract, so the recorded entry is re-taken
    rather than the version bumped when this function moves.
    """
    canonical = json.dumps(
        _strip_annotations(schema), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def contract_drift(schema=None, record=None):
    """Has the contract moved without the number? Return a sentence, or None.

    Three outcomes, and the one that matters is the unrecorded version. A hash
    guard whose natural failure mode is "no record, nothing to compare" passes
    hardest at the single moment it is worth anything -- immediately after
    somebody bumps the number -- which is this repository's own defect class
    inside the guard written to prevent it. So an unknown version is a finding,
    never a shrug, and it carries the fingerprint to record.
    """
    schema = load_schema() if schema is None else schema
    record = CONTRACT_FINGERPRINTS if record is None else record
    version = contract_version(schema)
    if version is None:
        return (
            "the schema declares no integer x-schema-version, so nothing can be "
            "compared against it -- a contract with no number cannot be told from one "
            "that never moved"
        )
    fingerprint = semantic_fingerprint(schema)
    if version not in record:
        return (
            "schema version {} has no recorded fingerprint. If the contract moved, "
            "record {} against {} in CONTRACT_FINGERPRINTS; if it did not, the number "
            "was bumped for nothing and should go back.".format(
                version, fingerprint, version
            )
        )
    if record[version] != fingerprint:
        return (
            "the schema's enforcing content fingerprints as {} but version {} was "
            "recorded as {}. Something a validator acts on changed without the "
            "contract number moving, so an older copy would refuse a report this one "
            "accepts and both would claim version {}.".format(
                fingerprint, version, record[version], version
            )
        )
    return None


def _resolve(sub, root):
    seen = 0
    while isinstance(sub, dict) and "$ref" in sub:
        ref = sub["$ref"]
        if not ref.startswith("#/"):
            raise ValueError("only local refs are supported: {}".format(ref))
        node = root
        for part in ref[2:].split("/"):
            try:
                node = node[part]
            except (KeyError, TypeError):
                raise ValueError("unresolvable ref: {}".format(ref))
        sub = node
        seen += 1
        if seen > 20:
            raise ValueError("$ref cycle at {}".format(ref))
    return sub


def _type_ok(value, name):
    expected = _TYPES[name]
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, expected)


def _label(path):
    return path or "<report>"


def _walk(value, sub, root, path, errors, rules):
    sub = _resolve(sub, root)
    if not isinstance(sub, dict):
        return

    unknown = sorted(set(sub) - _KEYWORDS)
    if unknown:
        raise ValueError(
            "schema at {} uses keyword(s) this validator does not implement: {}. "
            "Implement them or drop them -- silently ignoring one is a constraint that "
            "reads as enforced and is not.".format(_label(path), ", ".join(unknown))
        )

    for branch in sub.get("allOf", []):
        _walk(value, branch, root, path, errors, rules)

    if "type" in sub:
        names = sub["type"] if isinstance(sub["type"], list) else [sub["type"]]
        if not any(_type_ok(value, name) for name in names):
            errors.append(
                "{}: expected {}, got {}".format(
                    _label(path), " or ".join(names), type(value).__name__
                )
            )
            return

    if "const" in sub and value != sub["const"]:
        errors.append("{}: expected {!r}, got {!r}".format(_label(path), sub["const"], value))
    if "enum" in sub and value not in sub["enum"]:
        errors.append(
            "{}: {!r} is not one of {}".format(_label(path), value, sub["enum"])
        )

    if isinstance(value, dict):
        for key in sub.get("required", []):
            if key not in value:
                errors.append("{}: missing required key {!r}".format(_label(path), key))
        properties = sub.get("properties", {})
        if sub.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append("{}: unknown key {!r}".format(_label(path), key))
        for key, child in properties.items():
            if key in value:
                _walk(value[key], child, root, "{}.{}".format(path, key) if path else key,
                      errors, rules)
        if "x-items" in sub and isinstance(value.get("items"), list):
            for index, item in enumerate(value["items"]):
                _walk(item, sub["x-items"], root,
                      "{}.items[{}]".format(_label(path), index), errors, rules)

    if isinstance(value, list) and "items" in sub and isinstance(sub["items"], dict):
        for index, item in enumerate(value):
            _walk(item, sub["items"], root, "{}[{}]".format(_label(path), index), errors, rules)

    if "x-rule" in sub:
        rules.append((sub["x-rule"], value, path))


def _text(node, key):
    value = node.get(key)
    return value.strip() if isinstance(value, str) else ""


def _rule_survey(node, path, errors):
    """checked-with-no-items and never-checked must not be spellable the same way."""
    state = node.get("state")
    items = node.get("items")
    if state in ("not-checked", "partial") and not _text(node, "reason"):
        errors.append(
            "{}: state {!r} needs a reason -- an empty list with no reason cannot say "
            "whether anyone looked".format(_label(path), state)
        )
    if state == "not-checked" and isinstance(items, list) and items:
        errors.append(
            "{}: state 'not-checked' carries {} item(s); a survey nobody ran has "
            "nothing to report".format(_label(path), len(items))
        )


def _rule_review_survey(node, path, errors):
    """The survey rules, plus the one state only a delegated survey can be in.

    A spawn can execute, consume its budget and hand back an empty final message.
    Reported honestly and structurally that is `findings: []` under state
    `checked` -- byte-identical to a clean review, which is how #200 lost real
    findings. So the state is `returned-nothing`, and the whole content of it is
    the reason: which spawn went quiet, and what is lost. Items are allowed here
    and forbidden under `not-checked`, because a caller that re-derived part of
    the review from its own transcript has something to report and nobody it can
    attribute it to.
    """
    _rule_survey(node, path, errors)
    if node.get("state") == "returned-nothing" and not _text(node, "reason"):
        errors.append(
            "{}: state 'returned-nothing' needs a reason -- name the spawn that came "
            "back empty and what was lost; without it this reads exactly like a "
            "review that ran and found nothing".format(_label(path))
        )


def _rule_finding(node, path, errors):
    """The dispositions that hand something to the reader, and what each owes.

    A refusal owes its argument: with no reason it reads exactly like a
    well-argued one.

    `report-for-filing` owes the same thing for the opposite reason. It is not a
    verdict, it is work handed to the maintainer, and the schema deliberately has
    no word for a completed filing -- an agent cannot file, so the only thing this
    value can mean is a request (#254). What the maintainer needs before they can
    act on one is why the agent did not simply fix it.

    `below-bar` owes it for the reason opposite again (#411): the maintainer is
    being asked NOT to open anything, so the argument they need is the one for
    leaving it closed. Its second obligation is a claim about a file rather than
    about this node, so it is checked in `below_bar_report_errors` -- outside
    `_RULES`, which hands a rule its own node and nothing else.

    That is the same judgment the developer brief demands of an `adjacent` item, and
    it is NOT the same contract, which is worth saying rather than implying: an
    `adjacent` item has no `reason` field at all -- `$defs/adjacent` is
    `additionalProperties: false` and defines no such key, and `_RULES` has no entry
    for it -- so there the argument rides inside the free-text `text` and nothing
    checks that it arrived. Here it is a field of its own and it is refused when
    empty. Claiming parity would be this repository's own defect class in a
    docstring: an enforcement asserted by the prose next to the checker rather than
    by the checker. The asymmetry is `reason` alone, and narrowly: `adjacent` does
    carry the enforced `pr_anchor`, so "adjacent is unchecked" is now too broad a
    sentence to write.
    """
    if not _text(node, "text"):
        errors.append("{}: a finding carries its sentence, not a boolean".format(_label(path)))
    if node.get("disposition") in ("refused", "argued-down") and not _text(node, "reason"):
        errors.append(
            "{}: disposition {!r} needs a reason -- a refusal with no argument reads "
            "exactly like a well-argued one".format(_label(path), node.get("disposition"))
        )
    if node.get("disposition") == "report-for-filing" and not _text(node, "reason"):
        errors.append(
            "{}: disposition 'report-for-filing' needs a reason -- this is work "
            "handed to the maintainer, and without the argument for not fixing it "
            "here they have to reconstruct the judgment before they can "
            "file".format(_label(path))
        )
    if node.get("disposition") == BELOW_BAR and not _text(node, "reason"):
        errors.append(
            "{}: disposition 'below-bar' needs a reason -- this one asks the "
            "maintainer NOT to open an issue, so what they need in order to leave it "
            "closed is the argument that the class has no reachable caller. Without "
            "it, a judged decision and a shrug render identically".format(_label(path))
        )


def _rule_compliance_item(node, path, errors):
    """A declined instruction owes its argument, the same way a refusal does (#518).

    `instruction` and `reason` are both schema-required, but `required` only
    checks presence -- an empty string satisfies it. This is the rule that makes
    the silent-decline shape actually unspellable: an item that names the
    instruction and leaves the reason blank is exactly a decline that stays
    quiet about itself, dressed as a declared one. It is refused for the same
    reason `_rule_finding` refuses an empty reason on `refused` -- an argument
    that never arrived reads identically to one that was not needed, and this
    field exists to keep those apart.
    """
    if not _text(node, "instruction"):
        errors.append(
            "{}: a compliance item needs the instruction it declined, named "
            "specifically enough that the maintainer can find it in the "
            "brief".format(_label(path))
        )
    if not _text(node, "reason"):
        errors.append(
            "{}: a compliance item needs a reason -- an instruction named with no "
            "argument is a decline that stays silent about itself, which is the "
            "exact case this field exists to make unspellable".format(_label(path))
        )


def _rule_class_verdict(node, path, errors):
    if node.get("state") in ("not-applicable", "not-checked") and not _text(node, "why"):
        errors.append(
            "{}: state {!r} needs a why -- a class nobody reached must not read like a "
            "class that passed".format(_label(path), node.get("state"))
        )


def _rule_docs_target(node, path, errors):
    """The two states an agent can write without having opened the file.

    `updated` is proven by the diff. The other two are proven by nothing, and
    "no change needed" is exactly what a run that never read the file also
    writes -- so the why is the whole content of those two states.
    """
    state = node.get("state")
    if state == "no-change-needed" and not _text(node, "why"):
        errors.append(
            "{}: state 'no-change-needed' needs a why -- say what you read the file "
            "against; with no reason it reads exactly like a file nobody "
            "opened".format(_label(path))
        )
    if state == "not-read" and not _text(node, "why"):
        errors.append(
            "{}: state 'not-read' needs a why -- an unread doc is a gap somebody can "
            "act on, not the absence of a finding".format(_label(path))
        )


def _rule_test_phase(node, path, errors):
    state = node.get("state")
    if state == "observed" and not _text(node, "result"):
        errors.append("{}: state 'observed' needs the result it observed".format(_label(path)))
    if state in ("not-applicable", "not-run") and not _text(node, "reason"):
        errors.append(
            "{}: state {!r} needs a reason -- a phase nobody ran is not a phase that "
            "passed".format(_label(path), state)
        )


def _rule_full_suite(node, path, errors):
    """tests.full (#632): the same shape as $defs/phase, different vocabulary.

    `ran` owes its result for the same reason `phase`'s `observed` does: a claim
    that a suite ran and nothing else is not evidence, it is prose. `not-run`
    and `could-not-run` both owe a reason, and for different reasons that must
    not collapse into one -- `not-run` is a decision against
    agents/developer.md's own criteria, `could-not-run` is the harness failing
    before any decision was made. Rendering both the same way is exactly the
    class this whole schema exists to make unspellable: a check that could not
    look must never read like one that looked and found nothing.
    """
    state = node.get("state")
    if state == "ran" and not _text(node, "result"):
        errors.append(
            "{}: state 'ran' needs the result it observed -- a claim that the full "
            "suite ran with nothing else is prose, not evidence".format(_label(path))
        )
    if state in ("not-run", "could-not-run") and not _text(node, "reason"):
        errors.append(
            "{}: state {!r} needs a reason -- a suite nobody ran and a suite that "
            "could not start are different claims and must not render the "
            "same way".format(_label(path), state)
        )


def _rule_pr_body(node, path, errors):
    state = node.get("state")
    if state == "written" and not _text(node, "path"):
        errors.append("{}: state 'written' needs the path it was written to".format(_label(path)))
    if state == "not-written" and not _text(node, "reason"):
        errors.append("{}: state 'not-written' needs a reason".format(_label(path)))

    closes = node.get("closes")
    if state == "written" and not isinstance(closes, dict):
        errors.append(
            "{}: state 'written' needs a `closes` saying what merging this will close. "
            "Three states, and only the third is a defect: it closes something, it "
            "deliberately closes nothing, or nobody said -- and `pr_body: written` with "
            "nothing beside it is exactly true and exactly not the question.".format(
                _label(path)
            )
        )
    if not isinstance(closes, dict):
        return
    closes_path = (path + ".closes") if path else "closes"
    closes_state = closes.get("state")
    if closes_state == "closes" and not _issue_numbers(closes.get("issues")):
        errors.append(
            "{}: state 'closes' needs at least one issue number in `issues`. Saying it "
            "closes something without saying what closes nothing.".format(_label(closes_path))
        )
    if closes_state == "closes-nothing" and not _text(closes, "reason"):
        errors.append(
            "{}: state 'closes-nothing' needs a reason. A deliberate re-scope and a "
            "forgotten keyword are one missing line apart, and without one they render "
            "identically.".format(_label(closes_path))
        )


# --- the third receipt (#411) ---------------------------------------------------
#
# The filing bar defines three receipts and this contract encoded two, so a lane
# that decided "real, below the bar, belongs in the pull request body" had to spell
# it `report-for-filing` and disclaim it in the free text underneath. The label said
# file this and the prose said do not; the maintainer read the label first.
#
# `below-bar` is the third word, and it is checked rather than declared. The report
# already names the pull request payload and this validator already opens it, so the
# item quotes a fragment of the body it was recorded at and the on-disk pass looks
# for it. Same standing as the closing-keyword check above -- an absence detector.

BELOW_BAR = "below-bar"

# An anchor shorter than this proves nothing: two or three words can appear in a body
# that never mentions the finding, and the containment check would then pass on a
# receipt nobody wrote. The floor cannot make containment mean substance -- nothing
# stdlib can read prose for that -- so what it buys is a cost, and the number is the
# length of a short phrase rather than a measurement of anything.
ANCHOR_FLOOR = 24


def _collapse(text):
    """One space between words, so wrapping a body is free.

    A body is prose somebody wrapped and an anchor is a fragment somebody quoted;
    matching raw text would fire on where a line happened to break, which is a false
    finding about a receipt that is really there. A checker with false findings gets
    worked around rather than fixed.
    """
    return " ".join(text.split())


def below_bar_items(report):
    """Every item claiming the third receipt, as `(label, item)`, from both surveys.

    Both, because a finding is below the bar or it is not and who noticed it does not
    change that: `adjacent` is what the agent found itself and `review.findings` is
    what a spawn handed over. Written defensively rather than with the schema in hand,
    because it runs before the shape pass has agreed the report is even shaped right.
    """
    if not isinstance(report, dict):
        return []
    found = []
    surveys = [("adjacent", report.get("adjacent"), "action")]
    review = report.get("review")
    if isinstance(review, dict):
        surveys.append(("review.findings", review.get("findings"), "disposition"))
    for prefix, survey, key in surveys:
        if not isinstance(survey, dict) or not isinstance(survey.get("items"), list):
            continue
        for index, item in enumerate(survey["items"]):
            if isinstance(item, dict) and item.get(key) == BELOW_BAR:
                found.append(("{}.items[{}]".format(prefix, index), item))
    return found


def below_bar_report_errors(report):
    """What a below-bar item owes inside the report itself, before any file is opened.

    Two things, and the second is what stops the on-disk check being optional: an
    item whose receipt is a line in the pull request body needs there to BE a pull
    request body. Without this, `pr_body: not-written` is a route that makes every
    below-bar claim unverifiable while still rendering as a decision -- a guard
    nominally on and effectively off, which is the defect class this repo is named
    after wearing the clothes of the fix for it.
    """
    items = below_bar_items(report)
    if not items:
        return []
    node = report.get("pr_body") if isinstance(report, dict) else None
    state = node.get("state") if isinstance(node, dict) else None
    errors = []
    for label, item in items:
        anchor = _collapse(_text(item, "pr_anchor"))
        if not anchor:
            errors.append(
                "{}: below-bar needs a `pr_anchor` -- the receipt for this item is a "
                "line in the pull request body, and without a fragment to look for, "
                "the claim that it is there is checked by nobody. That is the silent "
                "drop the third receipt exists to stop.".format(label)
            )
        elif len(anchor) < ANCHOR_FLOOR:
            errors.append(
                "{}: `pr_anchor` is {} character(s); a fragment shorter than {} can "
                "turn up in a body that never mentions this finding, so containment "
                "would pass on a receipt nobody wrote. Quote a phrase from the line "
                "you actually wrote.".format(label, len(anchor), ANCHOR_FLOOR)
            )
        if state != "written":
            errors.append(
                "{}: below-bar says this is recorded in the pull request body, and "
                "pr_body.state is {!r}. There is no body for it to be in, so the "
                "decision has no receipt -- file it, fix it, or write the body."
                .format(label, state)
            )
    return errors


def below_bar_body_errors(report, body):
    """Compare each below-bar item's anchor against what the body actually says.

    HTML comments go first, because a receipt nobody can read is not one. Code spans
    deliberately do NOT -- unlike the closing-keyword check, where stripping them is
    correct because a forge does not honour a backticked keyword. A reader sees a
    backticked sentence perfectly well, and the reader is who this receipt is for.
    """
    if not isinstance(body, str):
        return []
    text = _collapse(_HTML_COMMENT.sub(" ", body)).casefold()
    errors = []
    for label, item in below_bar_items(report):
        anchor = _collapse(_text(item, "pr_anchor"))
        if not anchor:
            # The shape pass already named this. Saying it twice buries the rest.
            continue
        # Case-folded, and that is a measurement rather than a preference: the first
        # report ever written against this check quoted a sentence the body carries
        # inside `**bold**`, where the word is capitalised, and a case-sensitive
        # containment refused a receipt that was plainly there. Folding can only turn
        # a finding into a pass, never the reverse, so it costs the check nothing it
        # was ever able to claim -- and a checker with false findings gets worked
        # around rather than fixed.
        if anchor.casefold() in text:
            continue
        errors.append(
            "pr_body.payload.body: {} says it is recorded in the pull request body "
            "and the body does not carry its `pr_anchor` ({}). A below-bar item is a "
            "named decision not to file; with nothing in the body it is a silent "
            "drop that reads like one. An anchor found only inside an HTML comment "
            "does not count, because nobody reads it.".format(
                label, _one_line(anchor, 80)
            )
        )
    return errors


def _issue_numbers(value):
    """The integers in `issues`, with bools -- which are ints in Python -- excluded."""
    if not isinstance(value, list):
        return []
    return [n for n in value if isinstance(n, int) and not isinstance(n, bool)]


_RULES = {
    "survey": _rule_survey,
    "review-survey": _rule_review_survey,
    "finding": _rule_finding,
    "class-verdict": _rule_class_verdict,
    "docs-target": _rule_docs_target,
    "test-phase": _rule_test_phase,
    "full-suite": _rule_full_suite,
    "pr-body": _rule_pr_body,
    "compliance-item": _rule_compliance_item,
}


def validate(report, schema=None):
    """Return a list of problems. Empty means the report is well shaped, nothing more."""
    schema = schema if schema is not None else load_schema()
    errors = []
    rules = []
    _walk(report, schema, schema, "", errors, rules)
    for name, node, path in rules:
        if isinstance(node, dict):
            _RULES[name](node, path, errors)
    # Not an x-rule: this one spans the whole report. A below-bar item is a claim
    # about pr_body, and _RULES hands each rule its own node and nothing else, so a
    # per-node rule could not see the field it has to be checked against.
    errors.extend(below_bar_report_errors(report))
    return errors


def _one_line(text, limit=200):
    """Text from outside this script, reduced to one printable ASCII line.

    pr_body.path is chosen by whoever wrote the report. A newline in one forges a
    receipt row -- this command prints `ok <file>` and `INVALID <file>` and a
    reader scanning the output cannot tell a forged row from a real one -- and a
    control character rewrites what the terminal already printed.
    """
    flat = " ".join(str(text).split())
    safe = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in flat)
    return safe[:limit]


def resolved_receipt(path):
    """Where on disk a path on the command line actually landed.

    Returns `(text, state)` -- `resolved` carrying an absolute path, or
    `could-not-resolve` carrying the sentence saying so. Never the argument
    echoed back as though it had been resolved.

    `ok reports/x.json` is the same string whether that resolved inside the
    worktree root the brief names or inside the main clone a stale cwd left the
    session in. #685 is two handbacks damaged by exactly that silence in one
    session, and the second one was reported as a note that had *vanished from
    the shared worktree root between writes*. It had not vanished; it was
    written one directory over, and was found untracked in the clone hours
    later. Nothing in the loop named the directory anything was read from or
    written to, so "the file is not there" and "I am not where I think I am"
    render identically -- this repository's own defect class, in a handback
    rather than in a checker.

    This does not stop the write going to the wrong place. It stops the wrong
    place being invisible, which is the half a validator can actually reach.
    """
    try:
        return _one_line(Path(path).resolve(), 300), "resolved"
    except (OSError, ValueError) as exc:
        # ValueError as well as OSError, for the reason `_contained_path` gives
        # below: a NUL byte in a path raises `ValueError` from `resolve()` on
        # every supported interpreter, and an over-long component raises
        # `OSError`. Either way this is a location that could not be stated --
        # which is not the same answer as a location, and must not print like
        # one.
        return (
            "could not resolve {} to an absolute path ({})".format(
                _one_line(path, 120), _one_line(exc, 80)
            ),
            "could-not-resolve",
        )


def _contained_path(base_dir, raw_path):
    """Resolve the payload's path against the report's own directory.

    Returns `(path, problem)`, exactly one of them None -- and the third state is
    the point. A path that cannot be *decided* about is refused with a sentence
    rather than opened on the grounds that nothing objected.

    The join is `base / raw_path`, and pathlib drops the base when the right-hand
    side is absolute -- which is what lets one join and one containment test cover
    both spellings of the escape rather than needing a branch each. So an
    absolute path is neither specially accepted nor specially refused: it is
    resolved like any other and then has to land inside the base, which it does
    whenever the report names its payload the way a report is supposed to -- by
    the absolute path of a sibling. That is why containment is not decorative
    here and why refusing absolute paths outright, which would break every report
    written so far, is not needed to get it. On Windows the same expression is
    also what disarms `C:/...`: the drive-absolute spelling discards the base, so
    a guard reading the raw string for a leading separator would never see it,
    while a containment test on the joined result cannot miss it.

    Both sides are resolved, so a symlink sitting inside the base and pointing out
    of it is refused too -- resolving reads link targets and opens nothing.
    Comparison is on `os.path.normcase` parts: exact, drive-aware, and immune to
    the case-folding difference between the platforms.
    """
    if base_dir is None:
        return None, (
            "pr_body.path: no directory to resolve the payload against, so it was not "
            "opened. The payload is checked by resolving it against the report's own "
            "directory; without one there is nothing to contain it to, and that is a "
            "check that could not run rather than a check that passed."
        )
    try:
        base = Path(base_dir).resolve()
        candidate = (base / raw_path).resolve()
    except (OSError, ValueError) as exc:
        # ValueError, not only OSError: a NUL byte is legal in a JSON string and
        # `resolve()` raises `ValueError: embedded null character in path` for one,
        # on every supported interpreter. Caught here it is this sentence; escaping
        # here it reached main()'s `except ValueError`, which says "the schema itself
        # is unusable" -- a report crashing the check, reported as the maintainer's
        # own configuration being broken.
        return None, (
            "pr_body.path: could not resolve {} well enough to tell whether it stays "
            "inside the report's own directory ({}), so it was not opened.".format(
                _one_line(raw_path, 120), _one_line(exc, 80)
            )
        )
    root = [os.path.normcase(part) for part in base.parts]
    if [os.path.normcase(part) for part in candidate.parts][: len(root)] != root:
        return None, (
            "pr_body.path: {} resolves outside the report's own directory, so it was "
            "not opened. A report names the payload it wrote beside itself; a path "
            "leading anywhere else names a file the report does not own, and opening "
            "one means this process reading it and quoting parts of it back.".format(
                _one_line(raw_path, 120)
            )
        )
    return candidate, None


# --- what the body closes (#274) ------------------------------------------------
#
# An ABSENCE detector, deliberately, and the distinction is the whole risk of adding
# it. It answers "can I find no closing keyword bound to this number?", never "what
# will the forge close?". Every transformation below can only make it report more
# often -- stripping code spans, stripping HTML comments, requiring the keyword
# adjacent to each declared number -- so a finding is strong and a pass is weak. That
# is the right way round for something running before anything is published.
#
# Not a second copy of supertool's `_checks.closing_issue_refs`. That reader decides
# which issues a forge closes; every route to it from here makes a forge call and two
# of them publish, so it is unreachable from a stdlib-only validator, and a duplicated
# resolver is what the top of CLAUDE.md forbids. gh-pr-create stays the authority.
#
# On the two traps that make a substring grep wrong this is not merely conservative
# but correct, and both were observed in one night: `Closes #A #B` closes only #A, so
# #B needs its own keyword and does not have one; and a backticked `Closes #A` creates
# no reference while rendering as one that plainly did (PR #332, opening paragraph).
#
# What the keywords do, recorded rather than only asserted (#556, CLAUDE.md's #180
# rule): a forge matches a closing keyword by its POSITION relative to the reference,
# not by the sentence's meaning, so a negation right in front of it -- "does not
# close #241" -- still binds. That is not a hole in the word list below; it is why
# this detector's identical blindness to negation is harmless rather than a bug.
# `_binds` and `_ANY_CLOSING_REFERENCE` are exactly as positional as the forge is, so
# a negated sentence still counts as bound in both directions: a declared `closes` is
# satisfied (the forge closes it too, disclaimer or not) and a declared
# `closes-nothing` is refused (the forge closes it despite the disclaimer). Observed
# when PR #554's body disclaimed closing #241 in prose and GitHub closed it anyway on
# merge -- reopened by hand. What stays unmeasured is the word list itself, tracked
# in scripts/borrowed_authority.py (site "closing-keyword").

_CLOSING_KEYWORD = r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)"

# `keyword [:] whitespace [owner/repo]#N`, or the full issue URL a forge also honours.
# The whitespace is required -- a forge does not read `Closes#1` -- and the digit
# lookahead at each call site is what stops a search for #27 matching #274.
_BOUND = r"\b" + _CLOSING_KEYWORD + r"\b[ \t]*:?\s+(?:[\w.-]+/[\w.-]+)?"

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,}).*?(?:^[ \t]{0,3}\1[^\n]*$|\Z)",
                    re.DOTALL | re.MULTILINE)
_INLINE_CODE = re.compile(r"(`+)[\s\S]*?\1")
_ANY_CLOSING_REFERENCE = re.compile(_BOUND + r"#\d+", re.IGNORECASE)


def prose_of(body):
    """The body with the spans a forge reads no closing reference out of removed.

    Order matters: a fence is three backticks, so an inline-code pass run first would
    eat one and leave the rest looking like prose. Removal is conservative in the one
    direction that is safe here -- anything wrongly removed can only turn a pass into
    a finding, never the other way.
    """
    text = _HTML_COMMENT.sub(" ", body)
    text = _FENCE.sub(" ", text)
    return _INLINE_CODE.sub(" ", text)


def _binds(text, issue):
    pattern = re.compile(
        _BOUND + r"(?:#{n}(?!\d)|https?://\S*?/issues/{n}(?!\d))".format(n=issue),
        re.IGNORECASE,
    )
    return pattern.search(text) is not None


def closing_body_errors(closes, body):
    """Compare what the report says it closes against what the body actually binds."""
    if not isinstance(closes, dict) or not isinstance(body, str):
        return []
    text = prose_of(body)
    state = closes.get("state")
    errors = []
    if state == "closes":
        for issue in _issue_numbers(closes.get("issues")):
            if _binds(text, issue):
                continue
            errors.append(
                "pr_body.payload.body: the report says merging this closes #{n}, and the "
                "body binds no closing keyword (Closes/Fixes/Resolves) to #{n} outside a "
                "code span or an HTML comment. A bare #{n} is not a closing reference, "
                "`Closes #A #{n}` closes only #A, and a backticked `Closes #{n}` closes "
                "nothing while rendering as one that plainly did -- so merging this would "
                "close nothing and the board would read clean. This reports an absence it "
                "could find; gh-pr-create stays the authority on what a body does "
                "close.".format(n=issue)
            )
    elif state == "closes-nothing":
        found = _ANY_CLOSING_REFERENCE.search(text)
        if found is not None:
            errors.append(
                "pr_body.payload.body: the report says this closes nothing, and the body "
                "binds a closing keyword ({}). A maintainer reading `closes-nothing` "
                "expects the issue to survive the merge; the same absence pointing the "
                "other way closes one nobody decided to close.".format(
                    _one_line(found.group(0), 60)
                )
            )
    return errors


def no_close_body_errors(payload):
    """#698: the payload's own `no_close` against its own body -- a narrower check
    than `closing_body_errors` above, which compares the REPORT's declared
    `pr_body.closes` against the body. This one needs neither: `no_close` is the
    field supertool's `gh-pr-create` actually reads off the payload to decide
    whether to open a non-closing pull request at all, so a payload that sets it
    true while its own body still binds a closing keyword is contradicting
    itself, independent of what the report separately claims about `closes`.

    Same shape as the `closes-nothing` arm on purpose: an absence detector, so a
    finding is strong and a pass is weak, and it says nothing about what the
    forge will actually close.
    """
    if not isinstance(payload, dict) or payload.get("no_close") is not True:
        return []
    body = payload.get("body")
    if not isinstance(body, str):
        return []
    found = _ANY_CLOSING_REFERENCE.search(prose_of(body))
    if found is None:
        return []
    return [
        "pr_body.payload.no_close: true, and the body binds a closing keyword ({}) "
        "outside a code span or an HTML comment. no_close is supertool's own escape "
        "hatch for a pull request that genuinely closes nothing; a bound keyword "
        "beside it says the opposite, and the forge would close the issue despite "
        "the payload's own claim that it would not.".format(_one_line(found.group(0), 60))
    ]


#: A backslash followed by an `n`, as two characters in the DECODED body.
#: Spelled through `chr` rather than as a string escape so that no reader --
#: and no payload carrying this source through another serialisation on its way
#: to disk -- has to count backslashes to know what it is. #685 is a doubled
#: backslash surviving every validator it passed.
_LITERAL_NEWLINE = chr(92) + "n"
_REAL_NEWLINE = chr(10)


def escaped_newline_body_errors(payload):
    """#685 instance 1: a body that is more escaped than it is formatted.

    Observed once, and discovered only because somebody read the payload before
    opening it: 30 literal backslash-n sequences against 4 real newlines, in a
    body hand-built as JSON inside a TOML literal. The three closing lines sat
    on real newlines and everything above them did not -- one half of the write
    escaped and the other half did not -- so it was not a uniform encoding
    choice anybody could argue for. Opened unread it renders as one enormous
    line with every heading and paragraph break visible as a backslash and an
    n, under the maintainer's account, after the agent's session has ended.

    An ABSENCE detector, in the same sense as `closing_body_errors` above and
    for the same reason: it answers "is this body more escaped than formatted?"
    and never "is this body correct". A finding is strong; a pass is weak --
    four stray escapes under thirty real line breaks pass, and should, because
    this counts a ratio and does not read the prose.

    This repository is hostile to heuristics, and the objection it raises is
    that an un-passable check gets tuned until it passes. That objection is
    answered by the remedy rather than by a flag: literal escapes are counted
    only OUTSIDE code spans and fences, so a body that genuinely means a
    backslash-n puts it in backticks -- where a forge renders it verbatim and
    this check does not look, and which is what markdown wants anyway. No new
    payload key was added for it, deliberately: `forge_payload` carries the
    forge's own vocabulary (#698), and an escape hatch invented here would be
    this repository's word in somebody else's object.

    On a damaged body the strippers are also the safe way round. `_FENCE` is
    line-anchored, so a one-line body has no fences to strip and the count
    stays high -- a wrongly-unstripped span can only turn a pass into a
    finding, never the other way.
    """
    if not isinstance(payload, dict):
        return []
    body = payload.get("body")
    if not isinstance(body, str):
        return []
    literal = prose_of(body).count(_LITERAL_NEWLINE)
    real = body.count(_REAL_NEWLINE)
    if literal <= real:
        return []
    return [
        "pr_body.payload.body: {} literal backslash-n sequences outside code spans "
        "against {} real line break(s) -- more escaped than formatted. A JSON "
        "payload written with doubled backslashes opens as one enormous line with "
        "every heading and paragraph break visible in the rendered body, and the "
        "reading lands on somebody else after your session has ended (#685, "
        "observed at 30 against 4). If the body genuinely means a backslash-n, put "
        "it in a code span: a forge renders it verbatim there and this check does "
        "not look inside one. This counts a ratio; it does not read the prose, so "
        "a pass here is weak.".format(literal, real)
    ]


def validate_pr_body(report, schema=None, base_dir=None):
    """Open the pull request payload the report says it wrote, and check its shape.

    The one check that leaves the report. `pr_body.state` of `written` is the report's
    single claim about a file the *next* step consumes, and a payload the forge refuses
    is discovered after the agent's session has ended -- at which point somebody reads
    the body, wraps it, and invents a title. The title is the sentence most people read
    and the only part of a pull request that survives a squash into the log, so it
    belongs to whoever did the work; a check costing one `open()` keeps it there.

    Kept out of validate() on purpose. A shape checker that quietly touches the
    filesystem is two tools wearing one name, and neither can then be trusted about
    what it did. The caller chooses; the command line says when it skipped.
    """
    if not isinstance(report, dict):
        return []
    node = report.get("pr_body")
    if not isinstance(node, dict) or node.get("state") != "written":
        return []
    raw_path = node.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        # The shape pass already refuses this. Saying it twice buries the other errors.
        return []

    path, problem = _contained_path(base_dir, raw_path)
    if problem is not None:
        return [problem]
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [
            "pr_body.path: cannot open the payload the report says it wrote ({})".format(
                _one_line(exc)
            )
        ]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [
            "pr_body.path: {} is not the JSON payload a forge consumes ({}). A bare "
            "markdown body is the shape the next step refuses, and the refusal lands "
            "on somebody else after your session has ended.".format(
                _one_line(path), _one_line(exc)
            )
        ]

    schema = schema if schema is not None else load_schema()
    errors = []
    rules = []
    _walk(payload, schema["$defs"]["forge_payload"], schema, "pr_body.payload", errors, rules)
    if errors:
        return errors

    for field in ("title", "body"):
        if not _text(payload, field):
            errors.append(
                "pr_body.payload.{}: empty. The forge accepts it and a human then has to "
                "write it, which is the step this file exists to delete.".format(field)
            )
    branch = report.get("branch")
    if isinstance(branch, str) and payload.get("head") != branch:
        errors.append(
            "pr_body.payload.head: {!r} but the report is on branch {!r} -- a pull "
            "request opened from somewhere other than the work".format(payload.get("head"), branch)
        )
    # Reached only once the payload was opened and parsed. A body that could not be
    # read has no closing keyword to be missing, and reporting one for it would be
    # this file's own defect class inside the check written against it.
    errors.extend(closing_body_errors(node.get("closes"), payload.get("body")))
    errors.extend(no_close_body_errors(payload))
    errors.extend(escaped_newline_body_errors(payload))
    errors.extend(below_bar_body_errors(report, payload.get("body")))
    return errors


def _is_forge_payload(document, schema):
    """Is this unmistakably the pull request payload rather than the report?

    A finished run leaves both files in one directory, differing by a suffix, and
    the payload is the one the surrounding prose has just been discussing -- so it
    is the one a caller reaches for. Fed to the report pass it produces fourteen
    missing keys and three unknown ones about a file with nothing wrong with it,
    which reads as a finding rather than as a category error and invites the reader
    to go correct a correct payload.

    The test is "unmistakably a payload", never "failed to be a report": every key
    the forge requires is present, every key present is one the forge defines, and
    no report-only required key appears. Keying on the negative would turn every
    malformed report into "you passed the wrong file" -- a wrong answer delivered
    calmly, which is worse than the wall it replaced.

    Report-*only* is the load-bearing word. The report has a top-level `head` too --
    a commit SHA where the payload's is a branch name, same word, two objects -- so
    an intersection against the report's whole required list is never empty for a
    payload and the detector silently never fires. The third clause is redundant
    while the two key sets are otherwise disjoint, and is kept for the day one of
    them grows a name the other already has.
    """
    if not isinstance(document, dict):
        return False
    payload = schema.get("$defs", {}).get("forge_payload", {})
    required = set(payload.get("required", ()))
    known = set(payload.get("properties", {}))
    if not required or not known:
        # A schema that stopped defining the payload cannot classify one. Decline
        # rather than guess; the shape pass below still answers, loudly.
        return False
    keys = set(document)
    return (
        required <= keys
        and keys <= known
        and not (keys & (set(schema.get("required", ())) - known))
    )


def _wrong_file(path):
    """Name the mistake and the call to run. A wall of missing keys does neither."""
    return (
        "{}: this is a pull request payload (title, body, head, base), not an agent "
        "report, so nothing in it was validated. Validate the report instead -- it "
        "names this payload at pr_body.path, and validating it opens this file and "
        "checks its head against the report's branch, which is the check this file "
        "cannot answer on its own:"
        "\n    python3 report_schema.py <the report path the agent replied with>".format(path)
    )


def inspect_file(path, schema=None, check_pr_body=True):
    """Return `(version_state, version_sentence, errors)` for one report on disk.

    The version state and the shape errors are returned side by side rather than
    merged, because they answer different questions and merging them is the whole
    of #221: "this does not satisfy the contract I hold" and "I do not hold the
    contract this claims" are one string apart and worlds apart in what to do next.

    A file that could not be read or parsed has no version to state -- that is
    `undecidable` carrying the read failure, never `current` by default.
    """
    path = Path(path)
    schema = load_schema() if schema is None else schema
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return VERSION_UNDECIDABLE, "the report could not be read", [
            "{}: cannot read the report ({})".format(path, exc)
        ]
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        return VERSION_UNDECIDABLE, "the report could not be parsed", [
            "{}: not valid json ({})".format(path, exc)
        ]
    if _is_forge_payload(report, schema):
        # A category error, not a contract question. Naming a version here would
        # invite correcting a correct payload.
        return VERSION_UNDECIDABLE, "this is not a report", [_wrong_file(path)]

    state, sentence = version_verdict(report, schema)
    errors = validate(report, schema)
    if check_pr_body:
        errors = errors + validate_pr_body(report, schema, base_dir=path.parent)
    return state, sentence, errors


def validate_file(path, schema=None, check_pr_body=True):
    """The shape half of inspect_file, for callers that only want the findings."""
    return inspect_file(path, schema, check_pr_body)[2]


def _line(stream, text):
    """Print without letting the console's codepage kill the run.

    Everything printed here can echo the report: a path, an enum value, a finding's
    sentence. Output is encoded with the console's codepage, not the file's, and on
    Windows that is typically cp1252 -- where one accented character raises
    UnicodeEncodeError and ends the process at the print, after the validation the
    print was reporting already happened. A mangled character beats a dead process.
    """
    try:
        print(text, file=stream)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        safe = text.encode(encoding, "backslashreplace").decode(encoding, "replace")
        print(safe, file=stream)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate an agent report.")
    parser.add_argument("reports", nargs="+", help="report JSON files")
    parser.add_argument("--schema", default=None, help="override the schema location")
    parser.add_argument(
        "--shape-only",
        action="store_true",
        help="do not open the pull request payload named by pr_body.path (and say so)",
    )
    args = parser.parse_args(argv)

    try:
        schema = load_schema(args.schema)
    except (OSError, ValueError) as exc:
        _line(sys.stderr, "cannot load the schema: {}".format(exc))
        return 1

    failed = False
    unvalidatable = False
    ours = contract_version(schema)
    for report in args.reports:
        try:
            state, sentence, errors = inspect_file(
                report, schema, check_pr_body=not args.shape_only
            )
        except ValueError as exc:
            # A broken schema, not a broken report. It must not surface as a traceback
            # and it must never surface as a report with nothing wrong with it.
            _line(sys.stderr, "the schema itself is unusable: {}".format(exc))
            return 1

        # Three verdicts, ranked, and the ranking turns on ONE question: can this copy
        # speak for this report at all? It cannot when the numbers differ in a way
        # nothing declares away -- `readable` is exactly the case where they differ and
        # this copy CAN speak, so it is deliberately absent from the test below and
        # falls through to ok/INVALID with everything else. Its shape findings are real
        # findings about the report: a widening only ever accepts more, so anything our
        # contract refuses the older one refused too. And it
        # cannot when the schema it loaded declares no number -- in that second case
        # it holds no stateable contract, so it has no standing to call anything
        # invalid, however much the shape pass found. Shape findings must never
        # promote a foreign contract to INVALID: they answer a question about OUR
        # contract, and letting them decide the word is the confident wrong answer
        # #221 is about. What is left under `undecidable` is a report that named no
        # version -- a defect in the file, which the shape pass has already named as
        # a missing required key, so it lands on INVALID with everything else.
        cannot_speak = (
            state == VERSION_MISMATCH
            or ours is None
            or (state == VERSION_UNDECIDABLE and not errors)
        )
        if cannot_speak:
            unvalidatable = True
            held = "version {}".format(ours) if ours is not None else (
                "the schema this copy loaded, which names no contract"
            )
            _line(sys.stdout, "UNVALIDATABLE {}".format(report))
            _line(sys.stdout, "  {}".format(sentence))
            if errors:
                _line(sys.stdout, (
                    "  the shape pass ran anyway, against {}. These are findings "
                    "about the contract THIS copy holds and are not necessarily "
                    "defects in the report:".format(held)
                ))
                for error in errors:
                    _line(sys.stdout, "    {}".format(error))
            else:
                _line(sys.stdout, (
                    "  the shape pass found nothing, but it answered a question about "
                    "{} and not about the contract this report claims, so it is not "
                    "necessarily a clean report.".format(held)
                ))
        elif errors:
            failed = True
            _line(sys.stdout, "INVALID {} ({})".format(report, sentence))
            for error in errors:
                _line(sys.stdout, "  {}".format(error))
        else:
            # The version is named on the pass too. A validator that announces the
            # contract only when it objects tells two copies apart exactly when
            # nobody is comparing them, which was #212's remedy defeating itself.
            _line(sys.stdout, "ok {} ({})".format(report, sentence))
        # Under every verdict, not only the pass. A receipt that appears only on
        # a clean run tells two directories apart exactly when nobody is
        # comparing them, which was #212's remedy defeating itself one field
        # over. The path above is the argument as typed; this is where it landed.
        where, where_state = resolved_receipt(report)
        _line(sys.stdout, "  at: {}".format(
            where if where_state == "resolved" else "could-not-resolve -- " + where
        ))
        if args.shape_only:
            # A check that was skipped must never render as a check that passed.
            _line(sys.stdout, "  shape only: the pull request payload was not read")
    if failed:
        return 1
    # 2 is not 0 and not 1 on purpose: a caller that only tests for zero still stops,
    # and one that cares can tell "this copy cannot speak for this report" from "this
    # report is wrong". argparse also exits 2 on a bad command line; that arrives with
    # a usage block on stderr and no verdict row on stdout, which distinguishes it.
    return 2 if unvalidatable else 0


if __name__ == "__main__":
    sys.exit(main())
