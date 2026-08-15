"""#113: `ci.required_checks` is deleted, not guarded.

The key was a measurement that cannot be measured. The only quantity derivable
without a run is the workflow *job declaration* count, and this repo's own config
is the proof that it is not the merge gate's number: three job declarations
(`pytest`, `shell`, `fragment`) against fourteen check runs on every pull request,
because a 3x4 matrix expands one declaration into twelve. A guard asserting the
config matched the declarations would have gone green over a value wrong by eleven
-- a check that can only look at the wrong quantity, rendering as agreement, which
is the defect class this plugin is named after.

The number a maintainer needs is read live off the pull request. Nothing else can
produce it: a matrix expands, a reusable workflow declares nothing locally, an
org- or app-level check never appears in `.github/workflows/` at all, and a run
that has not happened declares nothing either.

So these tests assert two things. Nothing reads the key -- and removing it is not
a breaking change, because an `.oss.json` already on somebody's disk still carries
it and must still validate.
"""

import ast
import io
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCTOR = REPO_ROOT / "scripts" / "doctor.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402
import oss_rules  # noqa: E402
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


def _probe(**overrides):
    probe = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "labels": [],
        "milestones": [],
        "workflow_jobs": [],
        "files": ["README.md"],
        "tags": [],
        "merge_method": None,
        # Every candidate the probe lists needs a state: "could not answer" is not
        # "carries no version", and `probe_problems` refuses the gap rather than
        # deriving around it.
        "version_evidence": {"README.md": "none"},
    }
    probe.update(overrides)
    return probe


# ------------------------------------------------------------------- the key is gone


def test_this_repos_own_config_carries_no_ci_block():
    """The issue's subject. 3 on disk, 14 on the board, and the value nobody may
    trust is the one a reader who has not read the manager skill will believe.
    """
    config = json.loads((REPO_ROOT / oss_config.CONFIG_NAME).read_text(encoding="utf-8"))
    assert "ci" not in config


def test_ci_is_no_longer_a_required_key():
    assert "ci" not in oss_config.REQUIRED_KEYS


def _reads_required_checks(source):
    """Every place the name is used to *fetch a value*: `x["required_checks"]` or
    `x.get("required_checks")`. Parsed rather than grepped, because prose explaining
    why the key went away legitimately names it -- doctor's own warning does -- and a
    plain substring sweep cannot tell a consumer from an epitaph.
    """
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Subscript):
            index = node.slice
            if isinstance(index, ast.Constant) and index.value == "required_checks":
                hits.append(node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "get" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and first.value == "required_checks":
                    hits.append(node.lineno)
    return hits


def test_no_script_reads_required_checks():
    """The consumer inventory, asserted rather than grepped once by hand. If a new
    consumer appears, it is a consumer of a number nothing can produce.
    """
    offenders = {}
    for path in sorted((REPO_ROOT / "scripts").glob("*.py")):
        lines = _reads_required_checks(path.read_text(encoding="utf-8"))
        if lines:
            offenders[str(path.relative_to(REPO_ROOT))] = lines
    assert offenders == {}, offenders


def test_the_reader_sweep_can_actually_see_a_reader():
    """Positive control for the sweep above. An empty offender list also comes back
    from a matcher that matches nothing -- which is this repo's own defect class
    hiding inside the test written to prevent it.
    """
    source = 'a = config["required_checks"]\nb = config.get("required_checks")\n'
    assert _reads_required_checks(source) == [1, 2]


def test_scaffold_no_longer_carries_a_required_checks_checker():
    """`check_ci` existed only to report on the key's staleness. With the key gone
    its whole subject is gone; leaving it would report on a value nothing writes.
    """
    assert not hasattr(scaffold, "check_ci")


def test_the_probe_emits_no_ci_block_even_with_workflow_jobs():
    """`--probe` counted job declarations and shipped the count as `required_checks`.
    That is where the wrong value on disk came from (#85).
    """
    built = oss_config.build(_probe(workflow_jobs=["tests.yml:pytest", "changelog.yml:fragment"]))
    assert "ci" not in built


def test_build_says_nothing_about_required_checks_but_still_speaks(monkeypatch, capsys):
    """Positive control in the same fixture. Asserting a NOTE is absent also passes
    when `--build` printed nothing at all -- so pin a NOTE that must still fire.
    """
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps(_probe(workflow_jobs=["tests.yml:pytest"])))
    )
    assert oss_config._main(["--build"]) == 0
    captured = capsys.readouterr()
    assert "required_checks" not in captured.err
    # must fire: worktree_root is still a naming guess and still says so.
    assert "worktree_root" in captured.err
    assert "ci" not in json.loads(captured.out)


# ------------------------------------------------- removing it is not a breaking change


def test_a_config_still_carrying_ci_on_disk_validates_clean():
    """The cleanup must not become a breaking change. Every `.oss.json` written by
    an earlier version of this plugin still has the block, and those repos did not
    ask to be broken by a key going away.
    """
    assert oss_config.validate(_config(ci={"required_checks": 3})) == []


def test_a_legacy_ci_block_of_any_shape_validates_clean():
    """Nothing reads it, so nothing can be wrong with its type. A validator still
    type-checking a dead key is asserting against a value with no consumer.
    """
    assert oss_config.validate(_config(ci="whatever it used to be")) == []


def test_the_tolerance_is_specific_and_not_a_validator_that_stopped_checking():
    """Positive control for the two above. A genuinely unknown key must still be
    refused -- otherwise those tests pass because unknown-key detection broke.
    """
    problems = oss_config.validate(_config(cid={"required_checks": 3}))
    assert any("cid" in p and "unknown key" in p for p in problems), problems


def test_ci_stays_project_scope_so_split_does_not_move_a_legacy_key_to_the_laptop():
    """A tolerated key must still land in the committed half if somebody splits a
    config that has one -- moving it into `.oss.local.json` would hide it.
    """
    assert "ci" in oss_config.PROJECT_KEYS
    project, local = oss_config.split(_config(ci={"required_checks": 3}))
    assert "ci" in project
    assert "ci" not in local


# ------------------------------------------------------------------ doctor says so once


def _run_doctor(cwd):
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    return subprocess.run(
        [sys.executable, str(DOCTOR)],
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


def _write_config(root, **overrides):
    config = _config(clone=str(root), worktree_root=str(root / "wt"), **overrides)
    project, local = oss_config.split(config)
    (root / oss_config.CONFIG_NAME).write_text(
        json.dumps(project, indent=2), encoding="utf-8"
    )
    (root / oss_config.LOCAL_CONFIG_NAME).write_text(
        json.dumps(local, indent=2), encoding="utf-8"
    )


def test_doctor_points_at_a_legacy_ci_block_rather_than_ignoring_it(tmp_path):
    """Tolerated is not the same as invisible. A dead measurement left on disk reads
    exactly like a live one to the next person who opens the file.
    """
    _write_config(tmp_path, ci={"required_checks": 3})
    result = _run_doctor(tmp_path)
    assert result.returncode == 0
    assert "ci.required_checks" in result.stdout
    assert "gh pr checks" in result.stdout


def test_doctor_stays_quiet_about_ci_when_the_config_does_not_carry_it(tmp_path):
    """Positive control in the same shape: the notice above must be produced by the
    key being present, not printed unconditionally over every repo.
    """
    _write_config(tmp_path)
    result = _run_doctor(tmp_path)
    assert result.returncode == 0
    assert "ci.required_checks" not in result.stdout


# ------------------------------------------------------------------------ stale prose


def test_no_command_doc_still_tells_a_maintainer_to_set_the_number():
    """Docs are part of the deletion. The key may be *named* -- a reader arriving with
    it in their `.oss.json` needs to be told what happened to it -- but no doc may
    still carry the old remedy, which was `gh api .../check-runs`, then set it by hand.
    """
    docs = sorted((REPO_ROOT / "commands").glob("*.md"))
    # An empty glob makes every assertion below vacuously true -- a sweep that could
    # not look, rendering as a sweep that found nothing.
    assert docs, "no command docs found; the sweep below would pass over anything"
    offenders = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in docs
        if "check-runs" in path.read_text(encoding="utf-8")
    )
    assert offenders == [], offenders


def test_the_rule_shipped_into_managed_repos_does_not_list_the_key():
    """The consumer a hand-grep of `scripts/` and `commands/` misses. `oss_rules.py`
    ships a rule about `.oss.json` into every repo this plugin scaffolds, and that copy
    listed `ci.required_checks` among the keys and called it "the merge gate's
    arithmetic" -- prose about a key that no longer exists, in repos we do not own.
    """
    keys_line = next(
        line for line in oss_rules.OSS_CONFIG.splitlines() if "`state_file`" in line
    )
    assert "required_checks" not in keys_line, keys_line


def test_this_repos_installed_rule_copy_matches_the_template_it_is_generated_from():
    """Positive control for the test above: it asserts on the template, and the file a
    reader of this repo opens is the installed copy. If the two drift, the assertion is
    about text nobody reads.
    """
    installed = REPO_ROOT / ".claude" / "jit-context" / "paths" / "01-oss" / "oss-config.md"
    assert installed.read_text(encoding="utf-8") == oss_rules.OSS_CONFIG


def test_the_docs_that_still_name_the_key_say_it_was_deleted():
    """The other half. Naming it without saying it is gone is the stale-prose failure
    this test exists to catch -- and asserting only the absence above would pass over
    a doc that still presents the key as live configuration.
    """
    docs = sorted((REPO_ROOT / "commands").glob("*.md"))
    assert docs, "no command docs found; the loop below would inspect nothing"
    named = [p for p in docs if "required_checks" in p.read_text(encoding="utf-8")]
    # The loop is over docs that mention the key, so it inspects nothing if none do.
    # That is a legitimate end state -- but it must be reached by measurement, not by
    # a glob that came back empty, so both halves are pinned.
    assert named, "no command doc names the key; a reader arriving with it is told nothing"
    for path in named:
        body = path.read_text(encoding="utf-8")
        assert "#113" in body, path.name
        assert "deleted" in body, path.name
