"""#1717: doctor.py's label-vocabulary check writing to GitHub even when
called as a read-only diagnostic.

Investigating the issue as filed turned up a correction worth recording
here rather than only in the pull request body: #1717 names two callers
that supposedly reach this write with "no user action" -- the status
line's detached `refresh()` (`scripts/statusline.py`) and every tick's
identity probe (`skills/manager/phases/tick-order.md`). Neither actually
does. Both invoke `doctor.py` with only `--root`, never `--install-audit`,
and `check_label_vocabulary` (the only caller of `create_priority_label_
family`, doctor.py's one label-creating write) is called from exactly one
place in the whole file: inside `run_install_audit`, reached only when
`--install-audit` is passed. The ordinary diagnostic path -- what
statusline and tick-order both actually run -- structurally cannot reach
it.

What #1717 DOES get right: `commands/run/install-audit.md`'s own docs
described every check, including the label-vocabulary one, purely as a
read ("a named gap, not a silent pass"), with no mention that it also
WRITES when the family is entirely absent (#1686). That mismatch between
what the command's own docs promise and what it does is real and is fixed
in this diff by disclosing the write there.

This file is a regression lock on the structural fact above (the ordinary
path never reaches the write) plus the doc-disclosure fix -- not a fix for
a defect in doctor.py's own runtime behaviour, which this investigation
found to already be correctly gated.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR_PY = REPO_ROOT / "scripts" / "doctor.py"
INSTALL_AUDIT_MD = REPO_ROOT / "commands" / "run" / "install-audit.md"


def _doctor_text():
    return DOCTOR_PY.read_text(encoding="utf-8")


def test_check_label_vocabulary_is_called_exactly_once():
    """The one call site doctor.py's label-creating write is reachable
    from. If a future change adds a second call site (e.g. wiring this
    into the ordinary diagnostic sequence, as #1686's own "Where" section
    originally proposed), this test forces that change to be deliberate
    rather than incidental."""
    text = _doctor_text()
    calls = re.findall(r"(?<!def )check_label_vocabulary\(", text)
    assert len(calls) == 1


def test_the_one_call_site_is_inside_run_install_audit():
    text = _doctor_text()
    audit_start = text.find("def run_install_audit(")
    assert audit_start != -1
    next_def = text.find("\ndef ", audit_start + 1)
    assert next_def != -1
    body = text[audit_start:next_def]
    assert "check_label_vocabulary(" in body


def test_main_never_calls_check_label_vocabulary_outside_the_install_audit_branch():
    """The ordinary (non---install-audit) run -- what the status line's
    refresh() and every tick's identity probe actually invoke -- must not
    reach this call at all. `main()`'s own `if install_audit:` branch
    returns before the ~25-check ordinary sequence runs, and
    `check_label_vocabulary` never appears in that later stretch."""
    text = _doctor_text()
    main_start = text.find("def main(argv=None):")
    assert main_start != -1
    branch_start = text.find("if install_audit:", main_start)
    assert branch_start != -1
    # `run_install_audit` is called and returned from inside this branch;
    # everything AFTER it, up to the next top-level def, is the ordinary
    # sequence every other caller actually reaches.
    ordinary_start = text.find("\n    # #418:", branch_start)
    assert ordinary_start != -1, "the ordinary sequence's own leading comment moved"
    end_marker = text.find('if __name__ == "__main__":', ordinary_start)
    assert end_marker != -1
    ordinary_body = text[ordinary_start:end_marker]
    assert "check_label_vocabulary(" not in ordinary_body


def test_install_audit_docs_disclose_the_label_creation_write():
    text = INSTALL_AUDIT_MD.read_text(encoding="utf-8")
    assert "1686" in text
    assert "creates it" in text or "this command creates" in text
