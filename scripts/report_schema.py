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
"""

import argparse
import json
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
    "x-honesty", "x-enforced", "x-convention",
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
    "finding": _rule_finding,
    "class-verdict": _rule_class_verdict,
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


def validate_file(path, schema=None):
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ["{}: cannot read the report ({})".format(path, exc)]
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ["{}: not valid json ({})".format(path, exc)]
    return validate(report, schema)


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
    args = parser.parse_args(argv)

    try:
        schema = load_schema(args.schema)
    except (OSError, ValueError) as exc:
        _line(sys.stderr, "cannot load the schema: {}".format(exc))
        return 1

    failed = False
    for report in args.reports:
        try:
            errors = validate_file(report, schema)
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
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
