"""#494: `apply()` writes `.claude/settings.json`, and neither the plan nor the receipt
named it.

`settings_plan`/`apply_settings` are a real, correctly bounded key-level write -- #485
proved that half. The gap #494 found is upstream of the write: `plan()` walks paths only
and deliberately does not carry the settings key into it (the file is not ours, only one
key inside it is), so `show()`, which renders `plan()`'s entries, could never mention
`.claude/settings.json` either -- an agent asking "what would --apply do" got a preview
that was silently short one file. And the `--apply` receipt itself drops the fourth
bucket `apply()` already returns: `result["extended"]` is built and never printed, so
`grep -rn extended scripts commands skills agents` found only the three places that
define it, and nowhere that reads it.

Fixed at both ends, without pretending settings.json is a path-level entry `plan()` owns:
`show()` calls `settings_plan` directly, renders the body only for the two actions that
would write something (`create`, `extend` -- `present` and `decline` change nothing, so
there is nothing to preview), and the `--apply` receipt in `_main()` prints every bucket
`apply()` returns, `extended` included.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402
import scaffold  # noqa: E402


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
    project, local = oss_config.split(config)
    path = root / oss_config.CONFIG_NAME
    path.write_text(json.dumps(project), encoding="utf-8")
    (root / oss_config.LOCAL_CONFIG_NAME).write_text(
        json.dumps(local), encoding="utf-8"
    )
    return path


def test_show_with_no_path_names_settings_json_when_it_would_be_created(tmp_path):
    config = _write_config(tmp_path)
    shown = scaffold.show(str(tmp_path), oss_config.load_from(str(config))[0])
    paths = [entry[0] for entry in shown]
    assert scaffold.SETTINGS_PATH in paths, (
        "show() named nothing at .claude/settings.json even though a fresh repo has no "
        "such file and --apply would create one (#494)"
    )
    settings_entry = next(e for e in shown if e[0] == scaffold.SETTINGS_PATH)
    assert settings_entry[1] == "create"
    body = json.loads(settings_entry[2])
    assert "statusLine" in body


def test_show_with_no_path_names_settings_json_when_it_would_be_extended(tmp_path):
    config = _write_config(tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"enabledPlugins": {"oss@dpt-plugins": True}}), encoding="utf-8"
    )
    shown = scaffold.show(str(tmp_path), oss_config.load_from(str(config))[0])
    settings_entry = next(e for e in shown if e[0] == scaffold.SETTINGS_PATH)
    assert settings_entry[1] == "extend"
    body = json.loads(settings_entry[2])
    assert body["enabledPlugins"] == {"oss@dpt-plugins": True}
    assert "statusLine" in body


def test_show_omits_settings_json_when_nothing_would_be_written(tmp_path):
    """The must-not-fire control: a repo that already has a statusLine gets no preview
    entry for it, exactly like a template already `present` gets none today."""
    config = _write_config(tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"statusLine": {"command": "mine"}}), encoding="utf-8"
    )
    shown = scaffold.show(str(tmp_path), oss_config.load_from(str(config))[0])
    paths = [entry[0] for entry in shown]
    assert scaffold.SETTINGS_PATH not in paths


def test_show_a_single_named_settings_path_renders_its_pending_body(tmp_path):
    config = _write_config(tmp_path)
    shown = scaffold.show(
        str(tmp_path), oss_config.load_from(str(config))[0], path=scaffold.SETTINGS_PATH
    )
    assert len(shown) == 1
    path, action, body = shown[0]
    assert path == scaffold.SETTINGS_PATH
    assert action == "create"
    assert "statusLine" in json.loads(body)


def test_show_does_not_claim_settings_json_is_an_owned_file():
    """The ownership boundary #494 preserved, said as an assertion: settings.json is a
    key-level write, not a path this plugin owns wholesale -- it must not appear in
    OWNED, which is replaced unconditionally on every run."""
    assert scaffold.SETTINGS_PATH not in scaffold.OWNED


def test_apply_receipt_prints_the_extended_bucket(tmp_path, capsys):
    """The other half of #494: `apply()` already returns `extended`; the CLI receipt
    silently dropped it. Driven through `_main()` because that is where the drop lived
    -- `apply()` itself already returns the bucket correctly."""
    config = _write_config(tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"enabledPlugins": {"oss@dpt-plugins": True}}), encoding="utf-8"
    )
    assert (
        scaffold._main(["--root", str(tmp_path), "--config", str(config), "--apply"])
        == 0
    )
    out = capsys.readouterr().out
    assert scaffold.SETTINGS_PATH in out, (
        "the --apply receipt never printed .claude/settings.json even though it was "
        "extended -- apply() returns the bucket and _main() dropped it (#494)"
    )


def test_show_cli_labels_an_extend_as_extend_not_replace(tmp_path, capsys):
    """Caught in review: `_main`'s `--show` loop used to fall through to the OWNED
    trio's "would replace (rewritten every run)" wording for any action that was not
    literally "create" -- which silently included "extend" the moment settings.json
    became reachable there. An extend is a key merged into an existing file, not a
    file rewritten every run, and the wrong label misdescribes the pending write to
    the maintainer deciding whether to run --apply (#494 follow-up)."""
    config = _write_config(tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"enabledPlugins": {"oss@dpt-plugins": True}}), encoding="utf-8"
    )
    assert (
        scaffold._main(["--root", str(tmp_path), "--config", str(config), "--show"])
        == 0
    )
    out = capsys.readouterr().out
    assert "would extend" in out, (
        "an extend action printed something other than an extend label: {!r}".format(
            out
        )
    )
    assert (
        "would replace (rewritten every run)"
        not in out.split(scaffold.SETTINGS_PATH)[1].split("-----")[0]
    ), "the settings.json entry itself was still labelled 'replace'"


def test_show_a_single_named_settings_path_still_answers_when_already_present(tmp_path):
    """The docstring's promise -- "worth knowing even for a [file] already present" --
    applies to settings.json too: a maintainer naming the path directly gets the
    `present` state and its reason, not the collapse into "nothing to show" the bulk
    listing uses for the same state (#494 follow-up)."""
    config = _write_config(tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"statusLine": {"command": "mine"}}), encoding="utf-8"
    )
    shown = scaffold.show(
        str(tmp_path), oss_config.load_from(str(config))[0], path=scaffold.SETTINGS_PATH
    )
    assert len(shown) == 1
    path, action, body = shown[0]
    assert action == "present"
    assert "statusLine" in body


def test_show_a_single_named_settings_path_states_a_decline_reason(tmp_path):
    config = _write_config(tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{not json", encoding="utf-8")
    shown = scaffold.show(
        str(tmp_path), oss_config.load_from(str(config))[0], path=scaffold.SETTINGS_PATH
    )
    assert len(shown) == 1
    path, action, body = shown[0]
    assert action == "decline"
    assert "could not be read" in body


def test_extended_is_read_somewhere_other_than_where_it_is_defined():
    """The issue's second question: `grep -rn extended scripts commands skills agents`
    used to return only the three lines inside `apply()` that build the bucket. This
    asserts the fix rather than re-running the grep: `_main`'s source now names the key
    it prints from, so the bucket has a reader."""
    import inspect

    source = inspect.getsource(scaffold._main)
    assert '"extended"' in source or "'extended'" in source, (
        "scaffold._main does not read the extended bucket -- apply() still builds a "
        "value nothing consumes (#494)"
    )
