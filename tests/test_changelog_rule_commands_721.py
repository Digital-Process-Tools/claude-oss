"""#721: the changelog rule published a command the shipped assembler refuses.

#699 found that `assemble_changelog.py --check --check-links` ran only the links
audit and printed one confident `ok` for it. #720 closed that half by making the
combination a **hard refusal** -- exit 2, naming a replacement command for each
half. It deliberately did not touch the other half: `scripts/oss_rules.py` and the
committed rule it renders both still published the combined invocation under
"Check before pushing", so the documented pre-push command and the shipped script
disagreed, and the disagreement was a refusal that audits nothing.

The timing is what makes it worth a guard rather than a one-line edit. Both the
vendored `.oss/assemble_changelog.py` and the rule text are `ours`, replaced in the
same `/oss:scaffold` run -- so a managed repository that never refreshes keeps a
consistent (silently half-auditing) pair, and one that does refresh gets the new
script beside the old rule. Nothing connects those two events for whoever hits it.

**So this file does not grep for `--check --check-links`.** A string check pins the
one spelling that was wrong on the day it was written; the class is "the rule
publishes an invocation this script refuses", and the only thing that can see that
class is the script. Every command the rule emits is handed to
`assemble_changelog.main()` in a fixture and required not to come back `REFUSED`.
That would have fired the moment #720 landed, on a diff that touched neither file.

The assembler is run in-process rather than spawned: the flags are the subject, and
a subprocess buys a second failure mode (`spawn_guard`, an interpreter, a PATH) for
nothing. A scaffolded tree's rule names `.oss/assemble_changelog.py`, which
`scaffold._owned_assembler` copies verbatim from `scripts/assemble_changelog.py`, so
running the in-tree module against those argv is running the same file.

Python 3.9 compatible.
"""

import contextlib
import io
import shlex
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# Imported rather than `importorskip`ed. A missing module here is a red collection
# error, which is what a missing module is; an `importorskip` renders the whole file
# as `1 skipped` -- a green run over a guard nobody executed.
import assemble_changelog  # noqa: E402
import oss_rules  # noqa: E402

REFUSED = assemble_changelog.REFUSED

COMMITTED_RULE = (
    REPO_ROOT / ".claude" / "jit-context" / "paths" / "01-oss" / "changelog-fragments.md"
)

#: The version the fixture's CHANGELOG.md declares, and the one the rendered rule
#: declares as untagged -- so the link audit has a heading to look at and a reason
#: not to demand a `releases/tag/v...` URL for it. Both halves come from one value
#: for the same reason `.oss.json` holds `changelog_untagged` once.
FIXTURE_UNTAGGED = ["0.1.0"]

#: A changelog the link audit has something to say `ok` about: an `[Unreleased]`
#: heading with its link ref, and one release heading whose missing ref is declared
#: rather than absent. Both halves are the fixture's job -- a refusal about this
#: file's contents would be indistinguishable from a refusal about the flags, which
#: are the subject.
CHANGELOG_BODY = """# Changelog

## [Unreleased]

## [0.1.0] - 2020-01-01

### Fixed

- something (#1)

[Unreleased]: https://example.invalid/compare/v0.1.0...HEAD
"""

FRAGMENT_BODY = "- a fix that names its own issue (#1).\n"


def _assembler_lines(body):
    """Every shell line in a rule body that invokes the assembler.

    Deliberately not `_assembler_command` from `tests/test_oss_rules.py`: that helper
    is about the path the rule names, this file is about the flags it names, and a
    shared helper would make one of the two files fail for the other's reason.
    """
    return [
        line.strip()
        for line in body.splitlines()
        if line.strip().startswith("python3 ") and "assemble_changelog.py" in line
    ]


def _tree(tmp_path, name="repo"):
    """A plugin-shaped tree with one valid fragment and one release heading."""
    root = tmp_path / name
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "assemble_changelog.py").write_text("# ours\n", encoding="utf-8")
    (root / "changelog.d").mkdir()
    (root / "changelog.d" / "1.fixed.md").write_text(FRAGMENT_BODY, encoding="utf-8")
    (root / "CHANGELOG.md").write_text(CHANGELOG_BODY, encoding="utf-8")
    return root


def _rendered(root):
    return oss_rules.rules(
        root, fragments_dir="changelog.d", untagged=FIXTURE_UNTAGGED
    )["paths"]["changelog-fragments.md"]


def _run(root, command, monkeypatch):
    """Run one published command through the assembler, from inside *root*.

    `--dir` and `--changelog` are relative in the rule, as they must be -- the rule
    is read from the repository root -- so the cwd is what makes them resolve.
    """
    tokens = shlex.split(command)
    assert tokens[0] == "python3", command
    monkeypatch.chdir(root)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = assemble_changelog.main(tokens[2:])
    return code, buf.getvalue()


# ------------------------------------------------------------------ the reported bug


def test_every_command_the_generated_rule_publishes_is_one_the_assembler_accepts(
    tmp_path, monkeypatch
):
    """The generator, which is the side that matters: its output ships into every
    scaffolded repository, where nobody here will ever see it go wrong.
    """
    root = _tree(tmp_path)
    commands = _assembler_lines(_rendered(root))
    assert commands, "the rule emitted no invocation for a tree that has an assembler"

    for command in commands:
        code, out = _run(root, command, monkeypatch)
        assert code != REFUSED, (
            "the rule publishes a command the assembler refuses:\n{0}\n{1}".format(
                command, out))


def test_every_command_the_committed_rule_publishes_is_one_the_assembler_accepts(
    tmp_path, monkeypatch
):
    """The artifact beside the generator. The committed layer is what this
    repository's own sessions read, and a regeneration nobody ran leaves the old
    answer in the tree with every generator test green (#68).

    The fixture's paths stand in for this repository's, so the assembler resolves
    `--dir` and `--changelog` against a tree whose contents are known. What is under
    test is the flag set, not this repository's fragments.
    """
    root = _tree(tmp_path, name="committed")
    body = COMMITTED_RULE.read_text(encoding="utf-8")
    commands = _assembler_lines(body)
    assert commands, "the committed rule emits no invocation, though this repo has one"

    for command in commands:
        code, out = _run(root, command, monkeypatch)
        assert code != REFUSED, (
            "the committed rule publishes a refused command:\n{0}\n{1}".format(
                command, out))


# ------------------------------------------------------ the controls that must fire


def test_the_combination_that_was_published_is_still_refused(tmp_path, monkeypatch):
    """The positive control, and the whole reason the assertions above mean anything.

    Without it, `code != REFUSED` passes against a harness that never reached the
    script, a fixture the script cannot read, or a #720 that was quietly reverted --
    an absence of refusals is not evidence that refusals are visible from here.
    """
    root = _tree(tmp_path, name="control")

    code, out = _run(
        root,
        "python3 scripts/assemble_changelog.py --check --check-links "
        "--dir 'changelog.d' --changelog CHANGELOG.md",
        monkeypatch,
    )

    assert code == REFUSED, out
    assert "only ever ran the links audit" in out, out


def test_no_single_published_command_asks_for_both_audits_at_once(tmp_path):
    """The shape, asserted against the token list rather than the raw line: `--check`
    is a substring of `--check-links`, so a text search for one finds the other and
    reports agreement it never established.
    """
    root = _tree(tmp_path, name="shape")
    for body in (_rendered(root), COMMITTED_RULE.read_text(encoding="utf-8")):
        for command in _assembler_lines(body):
            tokens = shlex.split(command)
            assert not ("--check" in tokens and "--check-links" in tokens), command


def test_both_audits_are_published_rather_than_one_being_dropped(tmp_path):
    """The other way to make this file green, and the wrong one. Publishing only
    `--check` satisfies every "not refused" assertion above while silently retiring
    the link-reference audit -- a check that stopped running, which is the defect
    this repository is named after rather than a fix for it.
    """
    root = _tree(tmp_path, name="both")
    for label, body in (
        ("generated", _rendered(root)),
        ("committed", COMMITTED_RULE.read_text(encoding="utf-8")),
    ):
        flags = set()
        for command in _assembler_lines(body):
            flags.update(
                t for t in shlex.split(command) if t in ("--check", "--check-links"))
        assert flags == {"--check", "--check-links"}, (label, sorted(flags))


def test_each_published_command_names_the_resolver_argument_its_mode_reads(tmp_path):
    """Given neither `--dir` nor `--changelog`, the assembler walks up from the
    caller's cwd for a `.git` -- which names wherever the reader happens to be
    standing, not necessarily the repository the rule was written into (#68).

    Both flags on both lines, which is not redundancy for its own sake: it is exactly
    what `scaffold.CHANGELOG_WORKFLOW`'s two steps pass, and the rule's own closing
    paragraph promises that the command you run and the one that gates the pull
    request cannot disagree.
    """
    root = _tree(tmp_path, name="resolver")
    for command in _assembler_lines(_rendered(root)):
        tokens = shlex.split(command)
        assert "--dir" in tokens, command
        assert "--changelog" in tokens, command
