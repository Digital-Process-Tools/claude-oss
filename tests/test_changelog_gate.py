"""What the generated fragment gate does when it is actually run.

The other workflow tests read the rendered text. This one extracts the gate's own
`run:` body out of the template, puts it in front of a real git repository with a real
base ref, and reads the exit status -- because the defect in #87 is not visible in the
text at all. `git diff --name-only` lists a **deletion** identically to an addition, so
a pull request that changed product code and removed somebody else's pending fragment
passed green, and the receipt named the file being deleted as the evidence that a
fragment was present.

The fix is not `--diff-filter=AM`. That closes the bypass and blocks every release cut,
because a release legitimately deletes every fragment it folds into `CHANGELOG.md` and
adds none. So the cases below are a matched set and have to be read together: the
release cut is the one that fails if somebody reaches for the one-flag fix.

Deliberately not a YAML parse -- pyyaml is not a dependency of this repo, and the block
this extracts is the block a maintainer reads.

Python 3.9 compatible.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scaffold  # noqa: E402

GENERATED_WORKFLOW = ".github/workflows/oss-changelog.yml"

GATE_STEP = "- name: A user-visible change carries a fragment"

LINKS_STEP = "- name: CHANGELOG.md's link refs agree with its release headings"


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
        "ci": {"required_checks": 0},
        "state_file": ".max/oss-watch.json",
    }
    config.update(overrides)
    return config


def _step_script(step):
    """One step's shell body, dedented, ready to hand to bash."""
    body = scaffold.render_owned(GENERATED_WORKFLOW, _config())
    lines = body.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == step]
    assert len(starts) == 1, "expected exactly one {!r} step, found {}".format(
        step, len(starts)
    )
    start = starts[0]
    runs = [i for i in range(start + 1, len(lines)) if lines[i].strip() == "run: |"]
    assert runs, "the gate step has no `run: |` block"
    head = runs[0]
    indent = len(lines[head]) - len(lines[head].lstrip())
    block = []
    for line in lines[head + 1:]:
        if not line.strip():
            block.append("")
            continue
        if len(line) - len(line.lstrip()) <= indent:
            break
        block.append(line)
    assert block, "the step's `run: |` block is empty"
    return textwrap.dedent("\n".join(block)) + "\n"


def _gate_script():
    return _step_script(GATE_STEP)


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        check=True,
    ).stdout


def _write(repo, files):
    for name, content in files.items():
        target = repo / name
        if content is None:
            if target.exists():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


BASE = {
    "README.md": "# a repo\n",
    "CHANGELOG.md": "# Changelog\n\n## [Unreleased]\n",
    "src.py": "value = 1\n",
    "docs/guide.md": "a sentence\n",
    "changelog.d/906.added.md": "- somebody else's pending entry (#906).\n",
}


def _pull_request(tmp_path, head_files):
    """A repo whose HEAD differs from `origin/main` by exactly `head_files`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _write(repo, BASE)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    # The gate diffs against `origin/$BASE_REF`; no remote is needed for that ref to
    # exist, only the ref itself.
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    _write(repo, head_files)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "head")
    return repo


def _run_gate(repo):
    return subprocess.run(
        ["bash", "-c", _gate_script()],
        cwd=str(repo),
        env={"BASE_REF": "main", "PATH": "/usr/bin:/bin:/usr/local/bin"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


# ------------------------------------------------------------------ positive controls
#
# Every case below asserts about an exit status, and a gate that crashed on line one
# would produce a non-zero one for three of them. These two say the harness reaches the
# gate's own verdicts at all.


def test_the_gate_script_extracts_and_is_not_empty():
    script = _gate_script()
    assert "git diff" in script, script


def test_a_normal_pull_request_with_a_fragment_passes(tmp_path):
    repo = _pull_request(
        tmp_path,
        {"src.py": "value = 2\n", "changelog.d/925.fixed.md": "- a fix (#925).\n"},
    )
    result = _run_gate(repo)
    assert result.returncode == 0, result.stdout
    assert "925.fixed.md" in result.stdout


def test_a_pull_request_with_no_fragment_at_all_is_refused(tmp_path):
    repo = _pull_request(tmp_path, {"src.py": "value = 2\n"})
    result = _run_gate(repo)
    assert result.returncode != 0, result.stdout


# --------------------------------------------------------------------------- the bypass


def test_deleting_someone_elses_fragment_does_not_satisfy_the_gate(tmp_path):
    """#87 / upstream #925. Product code changes, a pending fragment disappears, and
    nothing is added. The gate used to print `Fragment present:` and name the file it
    was removing.
    """
    repo = _pull_request(
        tmp_path,
        {"src.py": "value = 2\n", "changelog.d/906.added.md": None},
    )
    result = _run_gate(repo)
    assert result.returncode != 0, result.stdout
    assert "Fragment present" not in result.stdout, (
        "the receipt named the deleted fragment as evidence one is present:\n"
        + result.stdout
    )


def test_adding_your_own_fragment_does_not_licence_deleting_somebody_elses(tmp_path):
    """What pins the branch ORDER inside the gate, and nothing else does.

    Found by review: with the deletion branch moved below the "was anything added"
    branch, every other test in this file still passed, and this shape went green
    printing `Fragment present:` over a receipt that named the entry it was dropping.
    A pull request may announce its own change and still not be entitled to remove
    somebody else's.
    """
    repo = _pull_request(
        tmp_path,
        {
            "src.py": "value = 2\n",
            "changelog.d/906.added.md": None,
            "changelog.d/925.fixed.md": "- a fix (#925).\n",
        },
    )
    result = _run_gate(repo)
    assert result.returncode != 0, result.stdout
    assert "906.added.md" in result.stdout, result.stdout
    assert "deleted" in result.stdout, result.stdout


def test_deleting_a_fragment_and_nothing_else_is_refused(tmp_path):
    """The plainest instance, and the one a `shipped`-paths gate would wave through:
    losing a fragment needs no code change to go with it.
    """
    repo = _pull_request(tmp_path, {"changelog.d/906.added.md": None})
    result = _run_gate(repo)
    assert result.returncode != 0, result.stdout


# ------------------------------------------------------- and why the one-flag fix fails


def test_a_release_cut_passes(tmp_path):
    """Deletions plus a rewritten CHANGELOG.md. This is the case `--diff-filter=AM`
    turns red, and it is why the fix has to be two diffs.
    """
    repo = _pull_request(
        tmp_path,
        {
            "CHANGELOG.md": "# Changelog\n\n## [1.0.0]\n\n- somebody else's entry.\n",
            "changelog.d/906.added.md": None,
        },
    )
    result = _run_gate(repo)
    assert result.returncode == 0, result.stdout
    # The receipt, not just the status: a gate that fell out of the "Fragment
    # present" branch by accident would also be zero here.
    assert "Release cut" in result.stdout, result.stdout
    assert "906.added.md" in result.stdout, result.stdout


def test_a_release_cut_that_also_carries_its_own_fragment_reports_both(tmp_path):
    """A release that also announces something is legitimate, and a receipt that prints
    only the half it added is the shape this gate exists to refuse.
    """
    repo = _pull_request(
        tmp_path,
        {
            "CHANGELOG.md": "# Changelog\n\n## [1.0.0]\n\n- somebody else's entry.\n",
            "changelog.d/906.added.md": None,
            "changelog.d/925.fixed.md": "- a fix (#925).\n",
        },
    )
    result = _run_gate(repo)
    assert result.returncode == 0, result.stdout
    assert "906.added.md" in result.stdout, result.stdout
    assert "925.fixed.md" in result.stdout, result.stdout


def test_nothing_changed_against_the_base_is_skipped_not_a_finding(tmp_path):
    """The third state. An empty diff is the gate being unable to look, not a pull
    request that forgot its fragment.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _write(repo, BASE)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    result = _run_gate(repo)
    assert result.returncode == 0, result.stdout
    assert "skipped" in result.stdout, result.stdout


# -------------------------------------------------------- the two guards lost in #88


def test_the_workflow_re_dispatches_when_the_escape_label_is_applied():
    """The failure message tells you to label the pull request `no-changelog`. With
    GitHub's default event set -- opened, synchronize, reopened -- applying it starts no
    run, and a re-run replays the original payload, so the label is invisible to that
    too. The remedy the gate prints has to be a remedy.
    """
    body = scaffold.render_owned(GENERATED_WORKFLOW, _config())
    assert "no-changelog" in body, "the escape hatch is not named -- this is vacuous"
    types = [line.strip() for line in body.splitlines() if line.strip().startswith("types:")]
    assert types, "`on: pull_request:` carries no `types:` -- " + body
    assert "labeled" in types[0], types
    assert "unlabeled" in types[0], types
    for required in ("opened", "synchronize", "reopened"):
        assert required in types[0], (
            "naming any type replaces the default set, so " + required + " has to be "
            "listed explicitly: " + types[0]
        )


def test_the_workflow_audits_the_changelog_link_refs():
    """`--check-links` is implemented in the assembler and was never invoked, so
    CHANGELOG.md's link-reference definitions stopped being audited per pull request and
    the run that found them stale became the run cutting the tag.
    """
    body = scaffold.render_owned(GENERATED_WORKFLOW, _config())
    assert "--check-links" in body, body


def _links_repo(tmp_path, changelog):
    """A repo carrying the vendored assembler where the generated step expects it."""
    repo = tmp_path / "repo"
    (repo / scaffold.OWNED_DIR).mkdir(parents=True)
    (repo / scaffold.OWNED_DIR / "assemble_changelog.py").write_text(
        (REPO_ROOT / "scripts" / "assemble_changelog.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repo / "changelog.d").mkdir()
    if changelog is not None:
        (repo / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return repo


def _run_links(repo):
    return subprocess.run(
        ["bash", "-c", _step_script(LINKS_STEP)],
        cwd=str(repo),
        env={"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


STALE = """# Changelog

## [1.0.0] - 2026-01-01

- a thing.
"""

AUDITED = STALE + """
[Unreleased]: https://github.com/owner/name/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/owner/name/releases/tag/v1.0.0
"""


def test_a_stale_link_ref_table_is_a_finding(tmp_path):
    """The positive control, and the whole reason the step was added. Without it the
    two checks below could be passing because the step does nothing at all.
    """
    result = _run_links(_links_repo(tmp_path, STALE))
    assert result.returncode != 0, result.stdout
    assert "1.0.0" in result.stdout, result.stdout


def test_an_audited_link_ref_table_passes(tmp_path):
    result = _run_links(_links_repo(tmp_path, AUDITED))
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    "changelog", [None, "# Changelog\n\n## [Unreleased]\n"], ids=["absent", "pre-release"]
)
def test_a_repo_that_has_not_cut_a_release_is_skipped_not_red(tmp_path, changelog):
    """`check_links` returns SKIPPED (exit 1), not OK, when there is no `## [x.y.z]`
    heading to audit refs against or no CHANGELOG.md at all -- and the scaffold creates
    neither. A step that treated that as a finding would redden every pull request in a
    freshly scaffolded repo, and it sits above the fragment gate, so the gate this
    change exists to fix would never run there. Found by review.
    """
    result = _run_links(_links_repo(tmp_path, changelog))
    assert result.returncode == 0, result.stdout
    assert "skipped" in result.stdout, (
        "it passed without saying it could not look:\n" + result.stdout
    )


@pytest.mark.parametrize("mode", ["--check", "--check-links"])
def test_every_assembler_invocation_is_scoped_to_the_managed_repo(mode):
    """`assemble_changelog.py` derives its root by walking up for a `.git`, so a run
    given neither `--dir` nor `--changelog` can resolve somewhere else entirely. The
    added step has to carry the same arguments as the one beside it.
    """
    body = scaffold.render_owned(GENERATED_WORKFLOW, _config())
    lines = [line for line in body.splitlines() if mode + " " in line]
    assert lines, mode + " is never invoked"
    for line in lines:
        assert "--changelog CHANGELOG.md" in line, line
