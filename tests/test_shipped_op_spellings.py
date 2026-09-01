"""Every `supertool 'OP...'` spelling this plugin ships has to resolve to a real op.

The rule that ships in `.claude/jit-context/tools/01-oss/supertool-required.md` blocks
`Read`, `Edit`, `Write`, `Glob` and `Grep` and hands the reader the op that replaces
the refused call. The `Write` row named `write:PATH`, and there is no `write` op -- so
the remedy handed to a blocked agent was itself unrunnable, at the exact moment the
agent had just been stopped (#197). Four of the five rows were right and nothing
checked any of them.

Two layers, because the two questions have different answers on different machines:

  inventory  Every spelling found in shipped prose must be declared below, and every
             declaration must still be found in shipped prose. This runs everywhere,
             including CI, which has no `supertool` -- it is a human confirming once
             that a spelling resolves, and a guard against a *new* spelling arriving
             unconfirmed.
  roster     Where `supertool` is on PATH, the declarations are measured against the
             ops actually loaded (`ops:roster`). That is the layer that settles a
             spelling without anyone confirming anything, and it is the layer CI
             cannot run.

The third state is the point. `ops:roster` lists the ops **loaded here**, and which
ops load depends on which presets a project enables -- so a spelling absent from the
roster is not evidence that it resolves nowhere, and a contributor without the
`github` preset must not fail a document naming `gh-issue`. Each declaration therefore
carries where it resolves, a preset-gated one is measured only on a machine that
loaded that preset, and a roster that could not be read skips while naming what went
unmeasured rather than passing quietly.

Scope, declared rather than left to be discovered: only the invocation form
`supertool 'OP...'` (single or double quoted, optionally `./supertool`, every argument
of a batched call) is extracted. A bare backticked mention such as "the `repo:` op" in
running prose is not an invocation and is not checked.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import manager_docs  # noqa: E402
import oss_rules  # noqa: E402

#: Where a declared spelling resolves. `None` is a built-in -- loaded everywhere
#: `supertool` is installed at all. A string is the preset that carries the op, which a
#: project enables in its `.supertool.json`; those are only measurable on a machine
#: that loaded it.
OP_INVENTORY = {
    "batch": None,
    "channel": "watch",
    "edit": None,
    "gh-branch": "github",
    "gh-issue": "github",
    "gh-issues": "github",
    "gh-labels": "github",
    "gh-pr-create": "github",
    "gh-pr-edit": "github",
    "gh-pr-merge": "github",
    "gh-prs": "github",
    "git-commit": "git",
    "git-diff": "git",
    "git-worktrees": "git",
    "glob": None,
    "grep": None,
    "help": None,
    "ops": None,
    "ops-compact": None,
    "paste": None,
    "radar": "watch",
    "read": None,
}

# `supertool` / `./supertool`, then each whitespace-separated quoted argument. The
# separator is whitespace only, so a heredoc opener `<<'EOF'` ends the argument list
# rather than being read as an op called EOF.
#
# The lookbehind is not a word boundary, and that is measured rather than
# defensive (#582's lane): a boundary only requires a word/non-word transition,
# and `-` is non-word, so the old pattern matched inside `not-supertool` -- a
# phrase written in a comment to describe that very defect in a sibling
# derivation -- and this guard reported the quoted argument beside it as an
# undeclared op spelling shipped to a reader. A word ending in "supertool" is not
# this command, and the remedy would have been to declare a placeholder op nobody
# ships, which is the opposite mistake this file's own docstring warns about for
# `op1`/`op2`. Narrowing only: every real invocation this matched before it still
# matches.
_CALL_RE = re.compile(
    r"(?:\./)?(?<![\w.-])supertool(?P<args>(?:\s+(?:'[^']*'|\"[^\"]*\"))+)"
)
_ARG_RE = re.compile(r"'([^']*)'|\"([^\"]*)\"")
_OP_RE = re.compile(r"\A([A-Za-z][A-Za-z0-9_.-]*)")


def op_spellings(text):
    """[(op, line number)] for every `supertool 'OP...'` invocation in `text`."""
    found = []
    for line_number, line in enumerate(text.splitlines(), 1):
        for call in _CALL_RE.finditer(line):
            for arg in _ARG_RE.finditer(call.group("args")):
                value = arg.group(1) if arg.group(1) is not None else arg.group(2)
                op = _OP_RE.match(value)
                if op:
                    found.append((op.group(1), line_number))
    return found


def shipped_documents():
    """(label, text) for shipped prose plus the doctor entry point's own execution
    surface -- the set of things a reader is meant to paste a remedy out of.

    The rule layer is in here twice on purpose, and they are two different things: the
    bodies in `scripts/oss_rules.py` are what `/oss:scaffold` installs into every
    managed repository, and the files under `.claude/jit-context/` are this repository
    own installed copy. Fixing one and not the other is how a fix reaches nobody, or
    reaches everybody except here.

    #224: this used to claim a population wider than its globs -- "everything this
    plugin ships that a reader executes" -- while never reading `bin/oss-workspace`
    or `scripts/doctor.py`, 15 `supertool 'OP...'` remedies printed to a user's
    stderr at runtime. Widened to `bin/oss-workspace` and to `scripts/doctor*.py`,
    which is `doctor.py` plus every `doctor_check_*.py` module #497 split its checks
    into -- the message text moved with them, so the population has to follow.

    #752: `(REPO_ROOT / "skills").rglob("SKILL.md")` reads a literal filename, which
    is the spine alone -- `skills/manager/phases/*.md` was added by the same commit
    (`ad38b93`, #750) that this test's own `_CALL_RE` narrowing landed in, and neither
    guard could see the other's file. `CLAUDE.md`'s own rule for exactly this shape --
    "a content check over the loop reads the set, never the spine" -- is
    `scripts/manager_docs.py`, already consumed by `tests/test_content_invariants.py`
    for this identical purpose. Routed through it here too, rather than adding a
    second `skills/manager/phases/*.md` glob next to the first: a phase file added
    later reaches both checks the moment it exists, not when two globs are
    remembered in step.

    Deliberately **not** `scripts/*.py` as a whole: `scripts/batch_hint.py` writes
    `supertool 'op1' 'op2'` as an ILLUSTRATIVE example inside its own docstring,
    syntactically identical to a real invocation. A blind sweep would report
    `op1`/`op2` as undeclared spellings for text nobody is meant to paste, or force
    declaring placeholders that bless a spelling nobody ships -- the opposite
    mistake. So the docstring above is narrowed to match what is actually covered,
    rather than left claiming everything: the named entry points a reader runs
    directly (`bin/oss-workspace`, `python3 scripts/doctor.py`), not every module
    this plugin happens to ship.
    """
    documents = []
    manager_paths, manager_unreadable = manager_docs.documents(REPO_ROOT)
    assert not manager_unreadable, (
        "manager_docs.documents() could not list skills/manager/phases/, so this "
        "sweep cannot claim to have covered the manager loop's phase files: "
        "{}".format(manager_unreadable)
    )
    for path in manager_paths:
        documents.append((path.relative_to(REPO_ROOT).as_posix(), path.read_text(encoding="utf-8")))
    for pattern in ("agents/*.md", "commands/*.md", ".claude/jit-context/*/*/*.md"):
        for path in sorted(REPO_ROOT.glob(pattern)):
            documents.append((path.relative_to(REPO_ROOT).as_posix(), path.read_text(encoding="utf-8")))
    entry_points = [REPO_ROOT / "bin" / "oss-workspace"]
    entry_points.extend(sorted((REPO_ROOT / "scripts").glob("doctor*.py")))
    for path in entry_points:
        if path.is_file():
            documents.append((path.relative_to(REPO_ROOT).as_posix(), path.read_text(encoding="utf-8")))
    for dimension, bodies in oss_rules.rules(repo_root=REPO_ROOT).items():
        for filename, body in sorted(bodies.items()):
            documents.append(("oss_rules.rules()[{}][{}]".format(dimension, filename), body))
    return documents


def undeclared_spellings(documents, inventory):
    """The findings: a spelling nobody has confirmed resolves anywhere."""
    return [
        "{}:{}: supertool {!r} is not a declared op".format(label, line_number, op)
        for label, text in documents
        for op, line_number in op_spellings(text)
        if op not in inventory
    ]


def loaded_ops():
    """(ops, reason) -- the ops `supertool` reports as loaded here, or why not.

    Never an empty set for "could not ask": an empty roster and an unreadable one are
    the two states this repository is named after, and they come back separately.
    """
    executable = shutil.which("supertool")
    if executable is None:
        return None, "supertool is not on PATH"
    try:
        # The resolved path, not the bare name: on Windows `which` honours PATHEXT and
        # finds a `.cmd`/`.exe` that a bare name would not reach without a shell.
        completed = subprocess.run(
            [executable, "ops:roster"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return None, "supertool ops:roster timed out"
    except OSError as exc:
        return None, "supertool ops:roster did not run: {}".format(exc)
    text = completed.stdout.decode("utf-8", "replace")
    # The roster ends with the op names in one indented block, each optionally suffixed
    # `*` (writes in this tree) or `!` (writes outside it).
    ops = set()
    for line in text.splitlines():
        if not line.startswith("  ") or line.strip()[:1] in ("-", ">", "`", "#"):
            continue
        for token in line.split():
            bare = token.rstrip("*!")
            match = _OP_RE.match(bare)
            if match and match.group(0) == bare:
                ops.add(bare)
    if not ops:
        return None, "supertool ops:roster named no ops (exit {})".format(completed.returncode)
    return ops, None


def test_bin_and_doctor_entry_points_are_swept():
    """#224: the sweep's docstring claimed to cover "everything this plugin ships
    that a reader executes" while its four globs never looked at `bin/oss-workspace`
    or `scripts/doctor.py` -- 15 `supertool 'OP...'` remedies printed to a user's
    stderr at runtime, uncovered. This is the positive half: the population must
    include the doctor entry point's own execution surface (`doctor.py` plus the
    `doctor_check_*.py` modules #497 split its checks into -- the message text
    moved with them) and the workspace launcher.
    """
    labels = {label for label, _ in shipped_documents()}
    assert "bin/oss-workspace" in labels, sorted(labels)
    assert "scripts/doctor.py" in labels, sorted(labels)
    assert any(label.startswith("scripts/doctor_check_") for label in labels), sorted(labels)


def test_an_illustrative_example_is_not_swept():
    """The negative control for the same fix. `scripts/batch_hint.py` writes
    `supertool 'op1' 'op2'` as an ILLUSTRATIVE example in its own docstring --
    syntactically identical to a real invocation, and not one. A blind
    `scripts/*.py` glob was rejected for exactly this: it would report `op1`/
    `op2` as undeclared spellings for text nobody is meant to paste, or force
    declaring placeholders that bless a spelling nobody ships. The population
    stays the named doctor entry point plus the launcher, not the whole
    directory.
    """
    labels = {label for label, _ in shipped_documents()}
    assert "scripts/batch_hint.py" not in labels, sorted(labels)


def test_the_extractor_finds_something():
    """A regex that matched nothing has checked nothing."""
    documents = shipped_documents()
    assert documents, "no shipped documents found"
    total = sum(len(op_spellings(text)) for _, text in documents)
    assert total > 10, (
        "found only {} supertool invocations across {} shipped documents -- either the "
        "documents stopped naming ops, or the extraction no longer matches how they "
        "are written".format(total, len(documents))
    )


def test_the_extractor_flags_a_bad_spelling_and_spares_a_good_one():
    """The positive control for the silence assertion below.

    `test_every_shipped_op_spelling_is_declared` asserts an absence, and an absence
    also arrives when the extractor is broken. This fixture is the shape #197 shipped:
    one row right, one row wrong.
    """
    body = "- **Read** -- `supertool 'read:PATH'`\n- **Write** -- `supertool 'write:PATH'`\n"
    findings = undeclared_spellings([("fixture", body)], OP_INVENTORY)
    assert len(findings) == 1, findings
    assert "'write'" in findings[0], findings[0]
    assert "fixture:2" in findings[0], findings[0]


def test_the_extractor_reads_every_argument_of_a_batched_call():
    text = "supertool 'read:a.md' 'grep:x:b.md' \"map:c.md\""
    assert op_spellings(text) == [("read", 1), ("grep", 1), ("map", 1)]
    assert undeclared_spellings([("f", "supertool 'read:a' 'nosuchop:b'")], OP_INVENTORY) == [
        "f:1: supertool 'nosuchop' is not a declared op"
    ]


def test_a_heredoc_delimiter_is_not_read_as_an_op():
    assert op_spellings("supertool 'paste:@-' <<'EOF'") == [("paste", 1)]


def test_every_shipped_op_spelling_is_declared():
    """The layer that runs in CI, where there is no supertool to ask."""
    findings = undeclared_spellings(shipped_documents(), OP_INVENTORY)
    assert not findings, (
        "shipped prose names ops that are not declared in OP_INVENTORY. Confirm each "
        "one resolves (`supertool 'ops:roster'`) and declare it, or fix the "
        "spelling:\n  " + "\n  ".join(findings)
    )


def test_every_declared_op_is_still_named_by_shipped_prose():
    """A declaration nobody ships is a licence, not a guard."""
    used = {op for _, text in shipped_documents() for op, _ in op_spellings(text)}
    stale = sorted(set(OP_INVENTORY) - used)
    assert not stale, (
        "declared in OP_INVENTORY but named by no shipped document: {} -- delete the "
        "entry rather than leave it blessing a spelling nobody ships".format(stale)
    )


def test_declared_built_in_ops_are_loaded_here():
    """The layer only a machine carrying supertool can run -- and it says when it did not.

    A preset-gated declaration is passed over individually when that preset is not
    loaded, and the ones passed over are named, because no failures over an unmeasured
    set is the defect this plugin is named after.
    """
    ops, reason = loaded_ops()
    if ops is None:
        pytest.skip(
            "{} -- {} declared op spellings went unmeasured against a live op "
            "list".format(reason, len(OP_INVENTORY))
        )
    missing = []
    unmeasured = []
    for op, preset in sorted(OP_INVENTORY.items()):
        if op in ops:
            continue
        if preset is None:
            missing.append(op)
        else:
            unmeasured.append("{} (preset {} not loaded here)".format(op, preset))
    assert not missing, (
        "declared as built-in but absent from `supertool ops:roster`: {}. Not measured "
        "on this machine: {}".format(missing, unmeasured or "none")
    )


def test_an_unreadable_roster_comes_back_as_a_reason_not_as_no_ops():
    """The positive control for the skip above: no ops must never render as no findings."""
    ops, reason = loaded_ops()
    if ops is None:
        assert reason, "loaded_ops() returned no ops and no reason"
    else:
        assert {"read", "paste", "edit"} <= ops, sorted(ops)[:20]


def test_phase_files_are_in_the_swept_population():
    """#752: the sweep must actually read the phase files, not merely declare that
    it does. Before the fix, `(REPO_ROOT / "skills").rglob("SKILL.md")` matched only
    the spine -- every one of these labels was absent.
    """
    labels = {label for label, _ in shipped_documents()}
    assert "skills/manager/SKILL.md" in labels, sorted(labels)
    for phase in ("dispatch.md", "handback.md", "merge.md", "release.md", "review.md", "accounting.md"):
        label = "skills/manager/phases/{}".format(phase)
        assert label in labels, sorted(labels)


def test_a_planted_bad_spelling_in_a_phase_file_is_caught():
    """Positive control, in the auditor's own shape (#752's own words): a planted
    `supertool 'totally-fake-op:1'` in SKILL.md was caught; the same plant in a
    phase file returned nothing, because the file was not in the population at
    all. Nothing on disk is touched -- the plant is applied to the phase file's
    own label after reading the real population, so this proves the label a
    phase file is swept under is one `undeclared_spellings` actually acts on.
    """
    documents = shipped_documents()
    phase_labels = [label for label, _ in documents if label.startswith("skills/manager/phases/")]
    assert phase_labels, "no phase files found in the swept population"
    planted = [(phase_labels[0], "supertool 'totally-fake-op:1'\n")]
    findings = undeclared_spellings(planted, OP_INVENTORY)
    assert any("totally-fake-op" in f for f in findings), findings


def test_an_unreadable_phases_directory_is_not_read_as_an_empty_one(monkeypatch):
    """The third state: `manager_docs.documents()` distinguishes "no phases
    directory" from "could not list it" (#571), and `shipped_documents()` must
    not swallow the second into a narrowed-but-silent population -- silently
    reporting every phase file's op spellings as declared because none were
    read is this repository's own defect class landing on the check meant to
    catch it. Exercised by injecting the exact contract `manager_docs.
    documents()` promises (a populated `unreadable` list), not by breaking a
    real directory's permissions -- CLAUDE.md's own permission-fixture bullet
    warns that root and some filesystems ignore the mode bit, which would make
    this assertion untested exactly where it claims to be tested.
    """

    def fake_documents(root=None):
        spine = REPO_ROOT / "skills" / "manager" / "SKILL.md"
        return [spine], ["permission denied (simulated)"]

    monkeypatch.setattr(manager_docs, "documents", fake_documents)
    with pytest.raises(AssertionError, match="could not list"):
        shipped_documents()
