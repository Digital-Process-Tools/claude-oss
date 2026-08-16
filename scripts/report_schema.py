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
report names -- a newer report, an older one, or a schema that does not declare its own
version. That is not the same as malformed, and printing it as `INVALID` is how a
correct report written yesterday reads as a broken one today. A missing or unparseable
file is an error, never a pass: a report that could not be read is not a report with no
findings.

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
    # the contract number, read by the version pass below rather than by _walk
    "x-schema-version",
    # annotations, carried for readers and ignored on purpose
    "$schema", "$id", "$defs", "$comment", "title", "description", "examples",
    "x-honesty", "x-honesty-on-disk", "x-honesty-versioning",
    "x-enforced", "x-enforced-on-disk", "x-convention",
}

# Keys that carry prose for a reader and change nothing a validator does. Stripped
# before the contract is fingerprinted, so rewording a description does not demand a
# version bump -- and so the guard on the bump does not train the reflex of moving the
# number to make CI green. x-schema-version is stripped too: the fingerprint answers
# "what does this contract require", which has to be independent of its own label or
# the comparison is circular.
_ANNOTATION_KEYS = {
    "title", "description", "examples", "$comment",
    "x-honesty", "x-honesty-on-disk", "x-honesty-versioning", "x-convention",
    "x-schema-version",
}

# One entry per version this schema has ever declared, mapping it to the fingerprint of
# the enforcing content at that version. 1 is absent on purpose and always will be: it
# is what every report written before anyone counted says, across at least three
# mutually incompatible schemas, and no fingerprint can be recovered for a contract
# nobody recorded. Adding an entry here is the act of declaring a new contract.
CONTRACT_FINGERPRINTS = {
    2: "d687807f452f7aa4c4773519fcbc00ab3aff097c04facf1b5e2652bf931bcb70",
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
# The three states below are the whole point. A copy of this validator holds exactly
# ONE contract. It can compare two numbers; it cannot compute the relationship between
# its contract and another version's, because it does not have the other one. So a
# newer report and an older report are the same epistemic state -- unvalidatable by
# this copy -- and neither is invalid. Collapsing either into "invalid" recreates #212
# one layer down: the maintainer hit exactly that on 2026-08-16, when a report written
# the day before came back as a bare `INVALID ... missing required key 'docs'` with
# nothing to distinguish an older contract from a malformed file.

VERSION_CURRENT = "current"
VERSION_MISMATCH = "mismatch"
VERSION_UNDECIDABLE = "undecidable"


def contract_version(schema):
    """The contract number the schema declares, or None if it declares none."""
    value = schema.get("x-schema-version") if isinstance(schema, dict) else None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def version_verdict(report, schema):
    """Return `(state, sentence)`: which contract this report claims, versus ours.

    Three states, and the third is load-bearing:

    - `current`   -- the numbers agree. The sentence still names the number, because
                     announcing the contract on a PASS is the whole of #212's remedy.
    - `mismatch`  -- both sides named a contract and they differ. Not invalid.
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
    if not _text(node, "text"):
        errors.append("{}: a finding carries its sentence, not a boolean".format(_label(path)))
    if node.get("disposition") in ("refused", "argued-down") and not _text(node, "reason"):
        errors.append(
            "{}: disposition {!r} needs a reason -- a refusal with no argument reads "
            "exactly like a well-argued one".format(_label(path), node.get("disposition"))
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


def _rule_pr_body(node, path, errors):
    state = node.get("state")
    if state == "written" and not _text(node, "path"):
        errors.append("{}: state 'written' needs the path it was written to".format(_label(path)))
    if state == "not-written" and not _text(node, "reason"):
        errors.append("{}: state 'not-written' needs a reason".format(_label(path)))


_RULES = {
    "survey": _rule_survey,
    "review-survey": _rule_review_survey,
    "finding": _rule_finding,
    "class-verdict": _rule_class_verdict,
    "docs-target": _rule_docs_target,
    "test-phase": _rule_test_phase,
    "pr-body": _rule_pr_body,
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
        # speak for this report at all? It cannot when the numbers differ, and it
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
