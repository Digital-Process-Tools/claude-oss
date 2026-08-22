"""The scaffold CLI that /oss:scaffold invokes.

The default must be the safe one. A command that writes into someone's repo by default
is a command somebody runs to "see what it does".
"""

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402
import scaffold  # noqa: E402


def _write_halves(root, config):
    """Write the two-file shape /oss:setup produces, and return the project half's path."""
    project, local = oss_config.split(config)
    path = root / oss_config.CONFIG_NAME
    path.write_text(json.dumps(project), encoding="utf-8")
    (root / oss_config.LOCAL_CONFIG_NAME).write_text(json.dumps(local), encoding="utf-8")
    return path


def _write_config(root, **overrides):
    config = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": str(root),
        "worktree_root": str(root / "wt"),
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": ["README.md"],
        "changelog_dir": None,
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "state_file": ".max/oss-watch.json",
    }
    config.update(overrides)
    return _write_halves(root, config)


def test_the_default_run_writes_nothing(tmp_path, capsys):
    """Printing the plan is the default because the other option edits someone's repo."""
    config = _write_config(tmp_path)
    assert scaffold._main(["--root", str(tmp_path), "--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert "PLAN:" in out
    assert not (tmp_path / "CLAUDE.md").exists()


def test_the_plan_names_each_file_and_its_action(tmp_path, capsys):
    config = _write_config(tmp_path)
    scaffold._main(["--root", str(tmp_path), "--config", str(config)])
    out = capsys.readouterr().out
    assert "CLAUDE.md" in out
    assert "create" in out


def test_the_plan_distinguishes_present_from_create(tmp_path, capsys):
    config = _write_config(tmp_path)
    (tmp_path / "SECURITY.md").write_text("ours\n", encoding="utf-8")
    scaffold._main(["--root", str(tmp_path), "--config", str(config)])
    lines = {
        line.split()[1]: line.split()[0]
        for line in capsys.readouterr().out.splitlines()
        if line.startswith(("create", "present"))
    }
    assert lines["SECURITY.md"] == "present"
    assert lines["CLAUDE.md"] == "create"


def test_apply_writes_and_reports_what_it_wrote(tmp_path, capsys):
    config = _write_config(tmp_path)
    assert scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "WROTE:" in out
    assert (tmp_path / "CLAUDE.md").is_file()
    assert (tmp_path / ".github" / "PULL_REQUEST_TEMPLATE.md").is_file()


def test_apply_leaves_an_existing_file_alone(tmp_path):
    config = _write_config(tmp_path)
    (tmp_path / "CODE_OF_CONDUCT.md").write_text("ours\n", encoding="utf-8")
    scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"])
    assert (tmp_path / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8") == "ours\n"


def test_a_missing_config_is_a_named_failure(tmp_path, capsys):
    result = scaffold._main(["--root", str(tmp_path), "--config", str(tmp_path / "absent.json")])
    assert result == 1
    assert "not found" in capsys.readouterr().out


def test_an_invalid_config_refuses_before_writing_anything(tmp_path, capsys):
    path = tmp_path / ".oss.json"
    path.write_text(json.dumps({"repo": "owner/name"}), encoding="utf-8")
    assert scaffold._main(["--root", str(tmp_path), "--config", str(path), "--apply"]) == 1
    assert "FAIL" in capsys.readouterr().out
    assert not (tmp_path / "CLAUDE.md").exists()


def test_apply_works_with_a_relative_root(tmp_path, monkeypatch, capsys):
    """`--root .` is how the command invokes this, and it was broken while every test
    passed: they all handed in an absolute tmp_path, so the one form that ships was the
    one form never exercised. Found by running the tool on this repo, not by the suite.
    """
    config = _write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert scaffold._main(["--root", ".", "--config", str(config), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "01-oss" in out
    assert (tmp_path / ".claude" / "jit-context" / "paths" / "01-oss" / "00-index.tsv").is_file()


def test_apply_replaces_the_rule_layer_and_says_so(tmp_path, capsys):
    """Templates and rules have opposite contracts, so the output must not blur them:
    one is never overwritten, the other always is.
    """
    config = _write_config(tmp_path)
    scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"])
    out = capsys.readouterr().out
    assert "replaced" in out
    assert "rule layer" in out


def test_the_plan_names_the_test_gate_that_does_not_exist(tmp_path, capsys):
    """A verified test command nothing runs is a measurement, so it is stated."""
    config = _write_config(tmp_path)
    scaffold._main(["--root", str(tmp_path), "--config", str(config)])
    out = capsys.readouterr().out
    assert "pytest" in out
    assert "runs it" in out


def test_apply_says_nothing_about_a_leg_count(tmp_path, capsys):
    """#113 deleted `ci.required_checks`, and with it the finding that reported the
    value as stale. The positive control is the assertion below it: the run still
    prints findings, so this is a checker that went away rather than output that did.
    """
    config = _write_config(tmp_path)
    scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"])
    out = capsys.readouterr().out
    assert "required_checks" not in out
    assert "check-runs" not in out
    assert "no-changelog" in out, out


def test_apply_names_the_escape_hatch_label_it_will_not_create(tmp_path, capsys):
    config = _write_config(tmp_path)
    scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"])
    out = capsys.readouterr().out
    assert "no-changelog" in out
    assert "gh label create" in out


def test_the_generated_claude_md_names_the_configured_repo(tmp_path):
    config = _write_config(tmp_path, repo="acme/widget", default_branch="trunk")
    scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"])
    body = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "acme/widget" in body
    assert "trunk" in body


# ------------------------------------------------------------------------------ show


def test_show_prints_content_and_writes_nothing(tmp_path, capsys):
    config = _write_config(tmp_path, repo="acme/widget")
    assert scaffold._main(["--root", str(tmp_path), "--config", str(config), "--show"]) == 0
    out = capsys.readouterr().out
    assert "CLAUDE.md" in out
    assert "acme/widget" in out
    assert not (tmp_path / "CLAUDE.md").exists()


def test_show_one_path_prints_only_that_file(tmp_path, capsys):
    config = _write_config(tmp_path)
    assert scaffold._main(
        ["--root", str(tmp_path), "--config", str(config), "--show", "SECURITY.md"]
    ) == 0
    out = capsys.readouterr().out
    assert "Security Policy" in out
    assert "CLAUDE.md" not in out


def test_show_and_apply_together_is_refused_before_writing(tmp_path, capsys):
    config = _write_config(tmp_path)
    result = scaffold._main(
        ["--root", str(tmp_path), "--config", str(config), "--show", "--apply"]
    )
    assert result == 1
    assert "FAIL" in capsys.readouterr().out
    assert not (tmp_path / "CLAUDE.md").exists()


def test_show_of_an_unknown_path_is_a_named_failure(tmp_path, capsys):
    config = _write_config(tmp_path)
    result = scaffold._main(
        ["--root", str(tmp_path), "--config", str(config), "--show", "NOT_A_TEMPLATE.md"]
    )
    assert result == 1
    assert "FAIL" in capsys.readouterr().out


def test_show_includes_owned_files_even_when_every_template_already_exists(tmp_path, capsys):
    """The sharp case from the coordinator review: with every template already on disk,
    the bare `--show` this command tells the caller to run must still name the three
    files `apply` overwrites unconditionally -- printing nothing here reads as "apply
    would write nothing", which is false.
    """
    config = _write_config(tmp_path)
    scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"])
    result = scaffold._main(["--root", str(tmp_path), "--config", str(config), "--show"])
    assert result == 0
    out = capsys.readouterr().out
    assert ".oss/README.md" in out
    assert ".oss/assemble_changelog.py" in out
    assert ".github/workflows/oss-changelog.yml" in out
    assert "nothing to show" not in out


def test_show_labels_create_and_replace_differently(tmp_path, capsys):
    config = _write_config(tmp_path)
    scaffold._main(["--root", str(tmp_path), "--config", str(config), "--show"])
    out = capsys.readouterr().out
    create_line = next(line for line in out.splitlines() if "CLAUDE.md" in line)
    replace_line = next(line for line in out.splitlines() if ".oss/README.md" in line)
    assert create_line != replace_line
    assert "create" in create_line
    assert "replace" in replace_line


# ------------------------------------------- collision with an existing changelog gate


def _with_other_gate(root):
    directory = root / ".github" / "workflows"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "changelog.yml").write_text(
        "name: changelog\njobs:\n  fragment:\n    steps:\n      - run: python3 "
        ".github/scripts/assemble_changelog.py --check\n",
        encoding="utf-8",
    )


def test_the_plan_reports_a_decline_when_a_gate_already_exists(tmp_path, capsys):
    config = _write_config(tmp_path)
    _with_other_gate(tmp_path)
    scaffold._main(["--root", str(tmp_path), "--config", str(config)])
    out = capsys.readouterr().out
    assert "decline" in out
    assert "changelog" in out


def test_apply_reports_what_it_declined_and_does_not_write_it(tmp_path, capsys):
    config = _write_config(tmp_path)
    _with_other_gate(tmp_path)
    assert scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "declined" in out
    assert "--force-owned" in out
    assert not (tmp_path / ".github" / "workflows" / "oss-changelog.yml").exists()


def test_force_owned_flag_writes_the_trio_despite_a_detected_gate(tmp_path, capsys):
    config = _write_config(tmp_path)
    _with_other_gate(tmp_path)
    assert scaffold._main(
        ["--root", str(tmp_path), "--config", str(config), "--apply", "--force-owned"]
    ) == 0
    assert (tmp_path / ".github" / "workflows" / "oss-changelog.yml").is_file()


# #125: the flag reached apply() and neither of the two paths a maintainer runs first.
# Both arms of each pair live in one test on one fixture -- asserting only the forced
# arm would still pass if the decline half quietly stopped working, and the decline
# half is the thing the flag exists to override.


def test_the_dry_run_stops_advising_the_flag_that_was_just_passed(tmp_path, capsys):
    config = _write_config(tmp_path)
    _with_other_gate(tmp_path)

    assert scaffold._main(
        ["--root", str(tmp_path), "--config", str(config), "--force-owned"]
    ) == 0
    forced = capsys.readouterr().out
    assert forced.count("replace ") >= 3, forced
    assert "decline " not in forced, forced
    assert "Pass --force-owned to override" not in forced, forced

    assert scaffold._main(["--root", str(tmp_path), "--config", str(config)]) == 0
    unforced = capsys.readouterr().out
    assert unforced.count("decline ") >= 3, unforced
    assert "Pass --force-owned to override" in unforced, unforced


def test_the_preview_stops_hiding_the_three_files_the_apply_would_overwrite(tmp_path, capsys):
    config = _write_config(tmp_path)
    _with_other_gate(tmp_path)

    assert scaffold._main(
        ["--root", str(tmp_path), "--config", str(config), "--force-owned", "--show"]
    ) == 0
    forced = capsys.readouterr().out
    assert forced.count("would replace") >= 3, forced
    for name in sorted(scaffold.OWNED):
        assert name in forced, forced

    assert scaffold._main(["--root", str(tmp_path), "--config", str(config), "--show"]) == 0
    unforced = capsys.readouterr().out
    # Narrowed from a bare `"would replace" not in unforced` in #182: the rule layer is
    # replaced wholesale on every run and now previews as such, so a blanket assertion
    # here would be asserting the defect. The subject of this test is the trio, and it
    # is still declined -- named file by file rather than by a substring that three
    # different write contracts all happen to share.
    for name in sorted(scaffold.CHANGELOG_OWNED):
        assert "----- {} (would replace".format(name) not in unforced, unforced
    # Positive control, so the loop above cannot pass on an empty preview: the run does
    # still show something it would replace, and it is the layer.
    assert unforced.count("would replace") >= 1, unforced
    assert ".claude/jit-context/paths/01-oss/changelog-fragments.md" in unforced, unforced


def test_the_dry_run_survives_a_workflow_directory_it_cannot_read(tmp_path, capsys):
    """#124 mechanism 1 through the CLI: the raise came before any output, so
    /oss:scaffold printed no plan at all -- dry run, --show and --apply alike."""
    config = _write_config(tmp_path)
    _with_other_gate(tmp_path)
    directory = tmp_path / ".github" / "workflows"

    os.chmod(str(directory), 0o000)
    try:
        try:
            os.listdir(str(directory))
        except PermissionError:
            pass
        except OSError as exc:
            pytest.skip(
                "chmod 000 gave {} (errno {}) rather than a denied listing; the "
                "unreadable dry run went untested".format(type(exc).__name__, exc.errno)
            )
        else:
            pytest.skip(
                "chmod 000 still allows listing {} -- root, or a platform that does not "
                "enforce the mode bit. The unreadable dry run went untested.".format(directory)
            )
        assert scaffold._main(["--root", str(tmp_path), "--config", str(config)]) == 0
        out = capsys.readouterr().out
        assert "PLAN:" in out, out
        assert out.count("decline ") >= 3, out
    finally:
        os.chmod(str(directory), 0o755)

    # Positive control on the identical tree: readable, the plan still prints.
    assert scaffold._main(["--root", str(tmp_path), "--config", str(config)]) == 0
    assert "PLAN:" in capsys.readouterr().out


# #117: the decline has to reach the rule layer. `_main` installs `01-oss` on the same
# run that declined the owned trio, so a declined repo received a rule describing an
# assembler that run deliberately did not vendor -- and a remedy sentence naming the
# command that had just declined.


def _installed_changelog_rule(root):
    """The installed rule, line wrapping collapsed.

    Every anchor below is prose, and a phrase spanning a wrap is absent from the file it
    is plainly in -- which turns a `not in` guard off with nothing failing. Collapsing
    first is what makes the negative assertions mean anything.
    """
    body = (
        root / ".claude" / "jit-context" / "paths" / "01-oss" / "changelog-fragments.md"
    ).read_text(encoding="utf-8")
    return " ".join(body.split())


def test_the_installed_rule_describes_the_repo_the_gate_decision_produced(tmp_path, capsys):
    """Both arms, one test: a repo whose trio was declined, and a repo that got it. The
    declined arm alone would still pass if rule emission stopped describing anything.
    """
    gated = tmp_path / "gated"
    gated.mkdir()
    gated_config = _write_config(gated)
    _with_other_gate(gated)
    assert scaffold._main(["--root", str(gated), "--config", str(gated_config), "--apply"]) == 0
    capsys.readouterr()
    gated_rule = _installed_changelog_rule(gated)

    clean = tmp_path / "clean"
    clean.mkdir()
    clean_config = _write_config(clean)
    assert scaffold._main(["--root", str(clean), "--config", str(clean_config), "--apply"]) == 0
    capsys.readouterr()
    clean_rule = _installed_changelog_rule(clean)

    # Declined: nothing was vendored, so the rule names no invocation, does not send the
    # reader back to the command that declined, and names the gate that does run.
    assert not (gated / ".oss" / "assemble_changelog.py").exists()
    assert "assemble_changelog.py --check" not in gated_rule, gated_rule
    assert "run that and this rule is rewritten" not in gated_rule, gated_rule
    assert ".github/workflows/changelog.yml" in gated_rule, gated_rule

    # Written: the same run on a repo with no foreign gate vendors the assembler and the
    # rule names it. This is the arm that fails loudly if emission breaks outright.
    assert (clean / ".oss" / "assemble_changelog.py").is_file()
    assert ".oss/assemble_changelog.py" in clean_rule, clean_rule
    assert "will not put one here" not in clean_rule, clean_rule


def test_force_owned_does_not_leave_the_rule_calling_the_write_a_decline(tmp_path, capsys):
    """With the flag the trio IS written, so the gate detection still says `found` while
    nothing was declined. Reporting the decline anyway would be the same false sentence
    pointing the other way.
    """
    config = _write_config(tmp_path)
    _with_other_gate(tmp_path)
    assert scaffold._main(
        ["--root", str(tmp_path), "--config", str(config), "--apply", "--force-owned"]
    ) == 0
    capsys.readouterr()

    body = _installed_changelog_rule(tmp_path)
    assert ".oss/assemble_changelog.py" in body, body
    assert "will not put one here" not in body, body
