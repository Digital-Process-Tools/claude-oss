"""The 01-oss rule layer, previewed before `--apply` replaces it (#182).

`/oss:scaffold` writes two kinds of thing. The templates are defaults, created once when
absent; the owned files and the rule layer are ours, replaced wholesale on every run. The
preview covered the first two and not the third, so a run against a repo that already has
every default and already runs a changelog gate printed

    PLAN: 0 to create, 11 already present, 3 declined (already covered elsewhere)

for a run whose only effect was to delete and rewrite six rule files -- markdown a hook
injects into a model's context on a match. The class is `misreports`: an absence the tool
produced, read as an absence in the world.

Two things every test here is built around:

* **A negative assertion needs a positive control.** "The plan does not read as a no-op"
  also passes when the plan is empty because the fixture never built a layer, so every
  such assertion is paired with a "must fire" case in the same fixture.
* **A preview is only worth anything if it is what gets written.** The decisive tests
  here do not check the preview's wording; they run `show()`, then `--apply`, and compare
  the previewed bodies byte for byte against the files on disk -- once down each of the
  two branches the changelog rule has.
"""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
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
        "version_sites": [".claude-plugin/plugin.json", "README.md"],
        "changelog_dir": "changelog.d",
        "changelog_untagged": ["0.1.0"],
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "state_file": ".max/oss-watch.json",
    }
    config.update(overrides)
    return config


def _write_config(root):
    """The two-file shape /oss:setup produces. Returns the project half's path."""
    config = _config(clone=str(root), worktree_root=str(root / "wt"))
    project, local = oss_config.split(config)
    path = root / oss_config.CONFIG_NAME
    path.write_text(json.dumps(project), encoding="utf-8")
    (root / oss_config.LOCAL_CONFIG_NAME).write_text(json.dumps(local), encoding="utf-8")
    return path


def _foreign_gate(root):
    """A changelog gate under somebody else's name, so the owned trio is declined.

    This is the repository shape the issue was measured in: every default present, a
    gate already running, and therefore nothing at all in the plan except the rule
    layer nobody could see.
    """
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "changelog.yml").write_text(
        "name: changelog\non: [pull_request]\njobs:\n"
        "  fragment:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: python3 tools/assemble_changelog.py --check\n",
        encoding="utf-8",
    )


def _paths(entries, action):
    return sorted(entry["path"] for entry in entries if entry["action"] == action)


def _rule_bodies(shown):
    return {
        path: body
        for path, _action, body in shown
        if path.startswith(".claude/jit-context/")
    }

# --------------------------------------------------------------- the plan lists them


def test_the_plan_lists_the_rule_files_the_run_would_replace(tmp_path):
    result = scaffold.plan_rules(tmp_path, _config())
    assert result["state"] == "previewed", result
    replaced = _paths(result["entries"], "replace")
    assert replaced, "no rule rows -- every assertion below would vacuously pass"
    # One row per file, not one row for the layer: the file count is not stable across
    # plugin versions, which is an argument for showing it rather than against.
    assert ".claude/jit-context/paths/01-oss/changelog-fragments.md" in replaced
    assert ".claude/jit-context/paths/01-oss/00-index.tsv" in replaced
    assert ".claude/jit-context/tools/01-oss/supertool-required.md" in replaced
    assert ".claude/jit-context/vocabulary/01-oss/oss-state.md" in replaced


def test_the_preview_covers_exactly_the_files_install_writes(tmp_path):
    """The preview and the write are the same list, or the preview is decoration."""
    previewed = set(_paths(scaffold.plan_rules(tmp_path, _config())["entries"], "replace"))
    assert previewed, "nothing previewed -- both sides of the comparison would be empty"
    written = oss_rules.install(
        tmp_path, fragments_dir="changelog.d", untagged=["0.1.0"], gate=("none", "")
    )
    actual = set(
        os.path.relpath(str(path), str(tmp_path)).replace(os.sep, "/") for path in written
    )
    assert previewed == actual


# ------------------------------------------------- the sharp case from the issue body


def test_a_run_whose_only_effect_is_the_rule_layer_does_not_read_as_a_no_op(tmp_path, capsys):
    config = _write_config(tmp_path)
    _foreign_gate(tmp_path)
    assert scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"]) == 0
    capsys.readouterr()

    assert scaffold._main(["--root", str(tmp_path), "--config", str(config)]) == 0
    out = capsys.readouterr().out
    summary = [line for line in out.splitlines() if line.startswith("PLAN:")]
    assert len(summary) == 1, out

    # Positive control: this fixture really is the sharp case. Without these three the
    # assertion below would pass against a plan that never had anything to hide.
    assert "0 to create" in summary[0], summary[0]
    assert "3 declined" in summary[0], summary[0]
    assert "decline  .oss/assemble_changelog.py" in out

    # The must-fire half: the run still replaces the layer, and the plan says so.
    assert ".claude/jit-context/paths/01-oss/changelog-fragments.md" in out
    assert "rule file" in summary[0], summary[0]


# ---------------------------------------------------- the preview is what gets written


def test_the_previewed_bodies_are_byte_identical_to_what_apply_writes(tmp_path, capsys):
    """The whole point, and the only assertion here a wrong preview cannot pass.

    The preview renders the layer against the tree as it will be AFTER the writes;
    `--apply` renders it after actually making them. If the two disagree the preview is
    a second confident answer rather than a fix for the first one.
    """
    config = _write_config(tmp_path)
    previewed = _rule_bodies(scaffold.show(tmp_path, _config()))
    assert previewed, "nothing previewed -- the loop below would assert nothing"

    assert scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"]) == 0
    capsys.readouterr()
    for path, body in previewed.items():
        assert (tmp_path / path).read_text(encoding="utf-8") == body, path


def test_the_previewed_bodies_match_apply_when_the_trio_is_declined(tmp_path, capsys):
    """The other branch: no assembler is written, and the rule has to say why not."""
    config = _write_config(tmp_path)
    _foreign_gate(tmp_path)
    previewed = _rule_bodies(scaffold.show(tmp_path, _config()))
    assert previewed, "nothing previewed -- the loop below would assert nothing"

    assert scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"]) == 0
    capsys.readouterr()
    for path, body in previewed.items():
        assert (tmp_path / path).read_text(encoding="utf-8") == body, path

# ------------------------------------- the branch that depends on this run's own writes


def test_the_preview_names_the_assembler_this_run_would_create(tmp_path):
    """The assembler lookup is re-run AFTER the writes, and that is load-bearing.

    On a first-ever scaffold `.oss/assemble_changelog.py` does not exist while the
    preview runs and does exist by the time the rule is rendered, so a preview that
    read the tree as it stands would show the could-not-locate rule for a repository
    about to have a perfectly good one. The answer is derived from the plan, and the
    preview says where it came from rather than passing it off as a read.
    """
    result = scaffold.plan_rules(tmp_path, _config())
    assert result["state"] == "previewed", result
    rule = [
        entry
        for entry in result["entries"]
        if entry["path"].endswith("paths/01-oss/changelog-fragments.md")
    ]
    assert len(rule) == 1, result["entries"]
    body = rule[0]["body"]
    assert ".oss/assemble_changelog.py" in body
    assert "could not be located" not in body
    # Derived, and said to be derived rather than presented as something read off disk.
    assert not (tmp_path / ".oss" / "assemble_changelog.py").exists()
    assert any(".oss/assemble_changelog.py" in line for line in result["basis"]), result["basis"]


def test_the_preview_renders_the_could_not_locate_rule_when_the_trio_is_declined(tmp_path):
    """The positive control for the test above: the other of the two answers.

    Same function, same fixture family, opposite verdict. Without this one a preview
    hardcoded to the with-assembler branch would pass the test above.
    """
    _foreign_gate(tmp_path)
    result = scaffold.plan_rules(tmp_path, _config())
    assert result["state"] == "previewed", result
    body = [
        entry["body"]
        for entry in result["entries"]
        if entry["path"].endswith("paths/01-oss/changelog-fragments.md")
    ][0]
    assert "could not be located" in body
    assert "under a different name" in body


# ---------------------------------------------------- the layer is removed, not merged


def test_a_rule_file_this_version_no_longer_ships_is_previewed_as_a_removal(tmp_path):
    layer = tmp_path / ".claude" / "jit-context" / "paths" / oss_rules.LAYER
    layer.mkdir(parents=True)
    (layer / "retired-rule.md").write_text("---\ntitle: old\n---\n", encoding="utf-8")
    (layer / "changelog-fragments.md").write_text("stale copy\n", encoding="utf-8")

    result = scaffold.plan_rules(tmp_path, _config())
    removed = _paths(result["entries"], "remove")
    replaced = _paths(result["entries"], "replace")

    # Must fire: the layer is deleted before it is rewritten, so a retired rule goes.
    assert ".claude/jit-context/paths/01-oss/retired-rule.md" in removed
    # Must not fire, with the control above making the absence mean something: a file
    # this version does ship is a replace, not a removal.
    assert ".claude/jit-context/paths/01-oss/changelog-fragments.md" not in removed
    assert ".claude/jit-context/paths/01-oss/changelog-fragments.md" in replaced

def test_a_layer_directory_that_cannot_be_listed_is_reported_not_reported_empty(tmp_path):
    """A directory this process cannot enter is not a directory with nothing in it.

    The deny is measured rather than assumed: root ignores the mode bit, some
    filesystems ignore it, and Windows' `os.chmod` on a directory toggles a read-only
    attribute that does not stop a listing. If the attempt succeeds anyway the test
    skips carrying what went untested.
    """
    base = tmp_path / ".claude" / "jit-context"
    readable = base / "tools" / oss_rules.LAYER
    readable.mkdir(parents=True)
    (readable / "retired-tool-rule.md").write_text("---\ntitle: old\n---\n", encoding="utf-8")
    denied = base / "paths" / oss_rules.LAYER
    denied.mkdir(parents=True)
    (denied / "retired-path-rule.md").write_text("---\ntitle: old\n---\n", encoding="utf-8")

    original = stat.S_IMODE(os.stat(str(denied)).st_mode)
    try:
        os.chmod(str(denied), 0o000)
    except OSError as exc:
        pytest.skip(
            "chmod 000 on a directory failed ({}); the unreadable-layer arm went "
            "untested on this platform".format(exc)
        )
    try:
        try:
            os.listdir(str(denied))
        except OSError:
            pass
        else:
            pytest.skip(
                "the mode bit did not deny a listing here (root, or a filesystem that "
                "ignores it); the unreadable-layer arm went untested"
            )

        result = scaffold.plan_rules(tmp_path, _config())
        # Must fire: the layer that could not be read is named as unreadable.
        assert result["unreadable"], result
        assert any(
            "paths/{}".format(oss_rules.LAYER) in entry["path"]
            for entry in result["unreadable"]
        ), result["unreadable"]
        # Must not fire: it is not quietly reported as holding nothing to remove.
        removed = _paths(result["entries"], "remove")
        assert ".claude/jit-context/paths/01-oss/retired-path-rule.md" not in removed
        # Positive control in the same fixture: the readable sibling still enumerates,
        # so an empty `unreadable` could not have come from a scan that saw nothing.
        assert ".claude/jit-context/tools/01-oss/retired-tool-rule.md" in removed
    finally:
        os.chmod(str(denied), original)


# ------------------------------------------------------------------- the third state


def test_a_layer_that_cannot_be_rendered_is_reported_rather_than_omitted(
    tmp_path, capsys, monkeypatch
):
    """`could not preview` and `previews to nothing` must not render alike.

    `oss_rules.rules()` refuses a gate state it has no sentence for rather than
    rendering the most plausible one to hand. Swallowing that here would put the plan
    straight back where the issue found it -- reporting a write-nothing run for a run
    that writes.
    """

    def _refuse(*args, **kwargs):
        raise oss_rules.RulesError("unknown changelog gate state 'maybe'")

    config = _write_config(tmp_path)

    # Positive control first, unpatched: this fixture does previewable work, so the
    # `unknown` below is the refusal and not an empty tree.
    clean = scaffold.plan_rules(tmp_path, _config())
    assert clean["state"] == "previewed" and clean["entries"], clean

    monkeypatch.setattr(oss_rules, "rules", _refuse)
    result = scaffold.plan_rules(tmp_path, _config())
    assert result["state"] == "unknown", result
    assert "unknown changelog gate state" in result["detail"]

    assert scaffold._main(["--root", str(tmp_path), "--config", str(config)]) == 0
    out = capsys.readouterr().out
    summary = [line for line in out.splitlines() if line.startswith("PLAN:")][0]
    assert "rule layer" in summary and "not previewed" in summary, summary


# ------------------------------------------------------------------------- --show


def test_show_renders_the_rule_bodies(tmp_path):
    shown = {path: body for path, _action, body in scaffold.show(tmp_path, _config())}
    rule = ".claude/jit-context/tools/01-oss/supertool-required.md"
    assert rule in shown
    assert shown[rule] == oss_rules.TOOLS_SUPERTOOL


def test_show_can_render_one_rule_by_path(tmp_path):
    rule = ".claude/jit-context/vocabulary/01-oss/oss-state.md"
    shown = scaffold.show(tmp_path, _config(), path=rule)
    assert shown == [(rule, "replace", oss_rules.STATE_FILE)]


def test_the_show_output_names_the_rule_files(tmp_path, capsys):
    config = _write_config(tmp_path)
    _foreign_gate(tmp_path)
    assert scaffold._main(["--root", str(tmp_path), "--config", str(config), "--show"]) == 0
    out = capsys.readouterr().out
    assert ".claude/jit-context/paths/01-oss/changelog-fragments.md" in out
    assert "would replace (rewritten every run)" in out

# ------------------------------------------- what the repo under inspection gets to say


def test_a_newline_in_a_filename_cannot_start_a_line_of_its_own_in_the_layer_note(
    tmp_path, capsys
):
    """The gate detail is built from filenames in somebody else's repository.

    It is data, and #182 put it in a line this loop prints and people read. A newline in
    one would end the `layer    ` line and start whatever follows at column 0 of a CI log
    -- the shape #173 and #180 closed for `.oss.json` values reaching a generated
    CLAUDE.md, arriving here through a different door.

    The fixture is measured, not assumed: a newline is legal in a POSIX filename and
    refused by Windows, so the test creates the file and skips with what went untested
    when it cannot.
    """
    config = _write_config(tmp_path)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    body = "on: [pull_request]\njobs:\n  x:\n    steps:\n      - run: assemble_changelog\n"
    # The positive control, and the reason an empty `layer` line cannot pass this test:
    # an ordinary name that must appear in the detail whatever happens to the odd one.
    (workflows / "ordinary.yml").write_text(body, encoding="utf-8")
    hostile = workflows / "ev\nil.yml"
    try:
        hostile.write_text(body, encoding="utf-8")
    except (OSError, ValueError) as exc:
        pytest.skip(
            "this platform refused a filename containing a newline ({}); the layer "
            "note's handling of one went untested here".format(exc)
        )

    assert scaffold._main(["--root", str(tmp_path), "--config", str(config)]) == 0
    out = capsys.readouterr().out
    layer_lines = [line for line in out.splitlines() if line.startswith("layer    ")]

    # Must fire: the note is rendered at all, and names the ordinary workflow.
    assert layer_lines, out
    assert any("ordinary.yml" in line for line in layer_lines), layer_lines
    # Must fire: the hostile name is still reported, flattened rather than dropped --
    # suppressing it would trade a forged line for a silent one.
    assert any("ev il.yml" in line for line in layer_lines), layer_lines
    # Must not fire: it did not get a line of its own.
    assert "ev\nil.yml" not in out, out


# ----------------------------------------------------- --show takes a path a user types


def test_show_accepts_a_path_with_the_local_separator(tmp_path):
    """`--show` compares a typed string against forward-slash paths.

    Every generated path this plugin knows is built with `/` on purpose, so the three
    membership tests in `show()` are string equality against forward slashes -- and a
    Windows maintainer typing the separator their shell completes with was told the file
    "is not a known template, owned file or rule", which is indistinguishable from the
    file not existing. #182 is the first change to advertise a path deep enough
    (`.claude/jit-context/paths/01-oss/oss-config.md`) that anybody would type it.

    Asserted on every platform rather than behind a Windows branch: the subject is a
    string the user typed, not a path the OS produced, so a backslash form is a real
    input everywhere, and a platform branch here would make the assertion vacuous on the
    two legs that pass today.
    """
    rule = ".claude/jit-context/vocabulary/01-oss/oss-state.md"
    assert scaffold.show(tmp_path, _config(), path=rule.replace("/", "\\")) == [
        (rule, "replace", oss_rules.STATE_FILE)
    ]
    template = ".github/ISSUE_TEMPLATE/bug_report.md"
    assert scaffold.show(tmp_path, _config(), path=template.replace("/", "\\")) == [
        (template, "create", scaffold.render(template, _config()))
    ]
    # Positive control: normalising separators did not turn the refusal off. A path that
    # is genuinely not ours is still refused, in both spellings.
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.show(tmp_path, _config(), path="NOT_A_TEMPLATE.md")
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.show(tmp_path, _config(), path=".claude\\jit-context\\paths\\01-oss\\nope.md")
