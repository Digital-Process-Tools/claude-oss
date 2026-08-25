"""#536: `_settings_preview`'\''s `extend` arm re-read `.claude/settings.json` itself,
unguarded, after `settings_plan` had already read and classified it. A file that errors
or changes between the two reads escaped as a raw `OSError`/`ValueError` out of
`/oss:scaffold --show`, contrary to the function'\''s own docstring, which promises
`None` rather than a raise.

Fix: reuse the document `settings_plan` already parsed (carried on the `extend` entry)
instead of re-reading -- closing the second question to the filesystem entirely rather
than guarding it, per CLAUDE.md'\''s trap against asking the filesystem a second question
to explain why the first one failed.
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
    (root / oss_config.LOCAL_CONFIG_NAME).write_text(json.dumps(local), encoding="utf-8")
    return path


def _write_settings(root, document):
    settings = root / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(document), encoding="utf-8")
    return settings


def test_settings_preview_survives_settings_json_erroring_after_the_first_read(tmp_path, monkeypatch):
    """Mechanism, not tone: `Path.read_text` is wrapped (per CLAUDE.md'\''s trap, patching
    the method the code under test calls rather than an injected accessor) to succeed on
    the first call against settings.json -- the read `settings_plan` performs -- and
    raise `OSError(5, "Input/output error")` on any call after that. Before the fix this
    reproduces the issue'\''s own exercised failure: `ESCAPED OSError` out of
    `_settings_preview`. After the fix, reusing the already-parsed document means no
    second read is ever attempted, so nothing raises.
    """
    _write_config(tmp_path)
    settings_path = _write_settings(tmp_path, {"enabledPlugins": {"oss@dpt-plugins": True}})

    calls = {"settings_reads": 0}
    real_read_text = Path.read_text

    def wrapped(self, *args, **kwargs):
        if self == settings_path:
            calls["settings_reads"] += 1
            if calls["settings_reads"] > 1:
                raise OSError(5, "Input/output error")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", wrapped)

    action, body = scaffold._settings_preview(str(tmp_path))

    assert calls["settings_reads"] == 1, (
        "the fix should reuse the document settings_plan already parsed, so "
        "settings.json is read exactly once -- {} reads happened".format(
            calls["settings_reads"]
        )
    )
    assert action == "extend"
    document = json.loads(body)
    assert document["enabledPlugins"] == {"oss@dpt-plugins": True}
    assert "statusLine" in document


def test_settings_preview_extend_still_renders_an_ordinary_file(tmp_path):
    """Control pair: an ordinary extendable file, with no injected failure at all, must
    still render its body -- the fix must not turn every extend into `None`."""
    _write_config(tmp_path)
    _write_settings(tmp_path, {"enabledPlugins": {"oss@dpt-plugins": True}})

    result = scaffold._settings_preview(str(tmp_path))
    assert result is not None
    action, body = result
    assert action == "extend"
    document = json.loads(body)
    assert document["enabledPlugins"] == {"oss@dpt-plugins": True}
    assert "statusLine" in document


def test_apply_settings_extend_reads_settings_json_exactly_once(tmp_path, monkeypatch):
    """The auditor's adjacent finding, same run: `apply_settings`'s `extend` arm did the
    identical unguarded second read `_settings_preview` was fixed for, three lines below
    a `settings_plan` call that -- after this issue's fix -- already carries the parsed
    document on the entry. Mechanism, not tone: `Path.read_text` is wrapped to succeed on
    the first call against settings.json and raise on any call after that; if
    `apply_settings` still re-reads, this fires and the write never completes."""
    _write_config(tmp_path)
    settings_path = _write_settings(tmp_path, {"enabledPlugins": {"oss@dpt-plugins": True}})

    calls = {"settings_reads": 0}
    real_read_text = Path.read_text

    def wrapped(self, *args, **kwargs):
        if self == settings_path:
            calls["settings_reads"] += 1
            if calls["settings_reads"] > 1:
                raise OSError(5, "Input/output error")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", wrapped)

    entry = scaffold.apply_settings(str(tmp_path))

    assert calls["settings_reads"] == 1, (
        "apply_settings should reuse the document settings_plan already parsed, so "
        "settings.json is read exactly once -- {} reads happened".format(
            calls["settings_reads"]
        )
    )
    assert entry["action"] == "extend"
    # Restore the real read_text before verifying the write -- the wrapper above is a
    # probe on apply_settings's own reads, not on this test's own cleanup read.
    monkeypatch.undo()
    written = json.loads(settings_path.read_text(encoding="utf-8"))
    assert written["enabledPlugins"] == {"oss@dpt-plugins": True}
    assert written["statusLine"] == dict(scaffold.STATUSLINE_SETTING)
