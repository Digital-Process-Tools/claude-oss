"""Guard for #751: an unquoted `${CLAUDE_PLUGIN_ROOT}/scripts/...` invocation
survives outside `dispatch.md`, because `tests/test_op_table_commands_687_689.py`
scopes its whole-document sweep (the `#741` widening, below its own header) to
that one file alone.

`handback.md:84` was the instance found: `${CLAUDE_PLUGIN_ROOT}/scripts/
rename_changelog_fragment.py <old path> <new number>` — a real, argument-bearing
invocation a session runs verbatim, unquoted, so a plugin root containing a
space (an ordinary Windows home directory built from a two-word account name)
word-splits into argv before the script is reached. This is the fifth recorded
instance of the class in this repository (#687, #689, and two more inside
`dispatch.md` itself, per #751's own table).

Scope, decided rather than defaulted (#751 names both options and asks for a
choice): **every file `scripts/manager_docs.documents()` returns** — the spine
plus every `skills/manager/phases/*.md` file — not the whole loop. That is
narrower than "every code fence in the loop's prose," which `CLAUDE.md` and
`#689` both call a larger, separate piece of work, and it is also NOT the
"blind whole-loop version" #751 says was tried and rejected during the
`dispatch.md` widening: that version also swept `agents/*.md` and flagged
`agents/developer.md:461` — a location-only mention (`${CLAUDE_PLUGIN_ROOT}/
scripts/doctor.py reads it off the loop's own installed manifest`), which
names where a function lives and carries no arguments and no imperative
framing. `agents/developer.md` is not in `manager_docs.documents()`'s
population at all, so scoping to that population reaches the same phase-file
family (`#751`'s own words: "the same document family, all executed as
prose") without re-admitting that false positive. Measured directly below
(`test_the_developer_md_false_positive_class_is_out_of_scope`), not merely
argued: the same regex against `agents/developer.md`'s own text still fires,
proving the false positive is real and that population scoping — not a
smarter regex — is what keeps it out.

Deliberately a new file rather than an edit to `test_op_table_commands_687_689.py`:
that file is outside this lane, `manager_docs` and the regex it needs are not,
and this guard's subject (every manager-loop document) is a strict superset of
that file's (one document's table plus `dispatch.md`).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import manager_docs  # noqa: E402

# Same pattern `test_op_table_commands_687_689.py` uses for the identical class,
# scoped identically: a `${CLAUDE_PLUGIN_ROOT}/scripts/...` reference not
# preceded by a double quote.
_UNQUOTED_ROOT_SCRIPT_RE = re.compile(r'(?<!")\$\{CLAUDE_PLUGIN_ROOT\}/scripts/')


def _unquoted_plugin_root_script_refs(text):
    """[(line number, line text)] for every unquoted ${CLAUDE_PLUGIN_ROOT}/scripts/
    reference in `text`.
    """
    return [
        (i, line.strip())
        for i, line in enumerate(text.splitlines(), 1)
        if _UNQUOTED_ROOT_SCRIPT_RE.search(line)
    ]


def _manager_loop_documents():
    """[(label, text)] for the spine plus every phase file. Raises loudly on an
    unreadable phases directory rather than silently narrowing to the spine --
    the same defect `manager_docs`'s own docstring (#571) exists to prevent one
    call further down.
    """
    paths, unreadable = manager_docs.documents(REPO_ROOT)
    assert not unreadable, (
        "manager_docs.documents() could not list skills/manager/phases/, so "
        "this sweep cannot claim to have covered it: {}".format(unreadable)
    )
    return [
        (path.relative_to(REPO_ROOT).as_posix(), path.read_text(encoding="utf-8"))
        for path in paths
    ]


def test_the_manager_loop_quotes_every_plugin_root_script_reference():
    """Must-not-fire: no unquoted ${CLAUDE_PLUGIN_ROOT}/scripts/... left anywhere
    in the spine or a phase file (#751)."""
    offenders = {
        label: refs
        for label, text in _manager_loop_documents()
        for refs in [_unquoted_plugin_root_script_refs(text)]
        if refs
    }
    assert not offenders, (
        "unquoted ${{CLAUDE_PLUGIN_ROOT}}/scripts/... in the manager loop -- "
        "word-splits on a plugin root containing a space: {0}".format(offenders)
    )


def test_unquoted_plugin_root_script_reference_is_detected_when_present():
    """Must-fire control: the #751 line as it stood before its fix is caught."""
    bad = (
        "   `${CLAUDE_PLUGIN_ROOT}/scripts/rename_changelog_fragment.py <old path> "
        "<new number>` performs both"
    )
    assert _unquoted_plugin_root_script_refs(bad) == [(1, bad.strip())]


def test_quoted_plugin_root_script_reference_is_not_flagged():
    """Must-not-fire control: the fixed form is not a false positive."""
    good = (
        '   `"${CLAUDE_PLUGIN_ROOT}/scripts/rename_changelog_fragment.py" <old path> '
        "<new number>` performs both"
    )
    assert _unquoted_plugin_root_script_refs(good) == []


def test_the_developer_md_false_positive_class_is_out_of_scope():
    """Measured, not argued: the same regex against agents/developer.md's own
    text still finds the location-only mention at line 461 -- the "blind
    whole-loop version" #751 says was rejected for exactly this. Confirms this
    guard's population scoping, not a smarter regex, is what keeps it out: this
    file is not in manager_docs.documents(), so it is never read by the sweep
    above at all.
    """
    developer_md = (REPO_ROOT / "agents" / "developer.md").read_text(encoding="utf-8")
    hits = _unquoted_plugin_root_script_refs(developer_md)
    assert hits, (
        "expected the known false-positive line in agents/developer.md to still "
        "trip the bare regex -- if it no longer does, the reasoning above for "
        "why this guard is scoped to manager_docs.documents() rather than the "
        "whole loop needs re-checking"
    )
    labels = {label for label, _ in _manager_loop_documents()}
    assert "agents/developer.md" not in labels, sorted(labels)
