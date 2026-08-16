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

Exit 0 when every report validates, 1 otherwise. A missing or unparseable file is an
error, never a pass: a report that could not be read is not a report with no findings.

Handed the pull request payload instead of the report -- the two land in one directory
one suffix apart -- it says so by name and names the call to run. Enumerating the
fourteen report keys a correct payload lacks is accurate and useless: it reads as a
finding about the file rather than as a mistake by the caller, and the move it invites
is hand-writing `head`, the one value nothing downstream verifies.
"""

import argparse
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
    # annotations, carried for readers and ignored on purpose
    "$schema", "$id", "$defs", "$comment", "title", "description", "examples",
    "x-honesty", "x-honesty-on-disk", "x-enforced", "x-enforced-on-disk", "x-convention",
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


def validate_file(path, schema=None, check_pr_body=True):
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ["{}: cannot read the report ({})".format(path, exc)]
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ["{}: not valid json ({})".format(path, exc)]
    if _is_forge_payload(report, schema if schema is not None else load_schema()):
        return [_wrong_file(path)]
    errors = validate(report, schema)
    if check_pr_body:
        errors = errors + validate_pr_body(report, schema, base_dir=path.parent)
    return errors


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
    for report in args.reports:
        try:
            errors = validate_file(report, schema, check_pr_body=not args.shape_only)
        except ValueError as exc:
            # A broken schema, not a broken report. It must not surface as a traceback
            # and it must never surface as a report with nothing wrong with it.
            _line(sys.stderr, "the schema itself is unusable: {}".format(exc))
            return 1
        if errors:
            failed = True
            _line(sys.stdout, "INVALID {}".format(report))
            for error in errors:
                _line(sys.stdout, "  {}".format(error))
        else:
            _line(sys.stdout, "ok {}".format(report))
        if args.shape_only:
            # A check that was skipped must never render as a check that passed.
            _line(sys.stdout, "  shape only: the pull request payload was not read")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
