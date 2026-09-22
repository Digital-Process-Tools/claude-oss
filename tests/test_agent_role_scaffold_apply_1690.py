"""#1690: a `doctor` spawn was observed running `scaffold.py --apply`,
committing the result to the default branch and pushing it, in a run whose
own prompt explicitly said not to. The withholding for release authority
(#695) is the precedent this issue names by name: a role marker `release_
publish.py` refuses under, in code, rather than a sentence in a brief a
spawn can ignore. This is the same shape for a second role (`doctor`) and a
second action (`scaffold.py --apply`), plus the settings-file digest #1690
separately asks for.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import agent_role  # noqa: E402


# ------------------------------------------------------- role_forbids_scaffold_apply


def test_no_role_set_does_not_forbid_scaffold_apply(monkeypatch):
    monkeypatch.delenv(agent_role.ROLE_ENV, raising=False)
    assert agent_role.role_forbids_scaffold_apply() is False


def test_maintainer_role_does_not_forbid_scaffold_apply(monkeypatch):
    """Positive control: a role other than doctor must not be caught."""
    monkeypatch.setenv(agent_role.ROLE_ENV, "maintainer")
    assert agent_role.role_forbids_scaffold_apply() is False


def test_sub_manager_role_does_not_forbid_scaffold_apply(monkeypatch):
    """The two denylists are independent -- release's own forbidden role
    must not be swept into this one."""
    monkeypatch.setenv(agent_role.ROLE_ENV, "sub-manager")
    assert agent_role.role_forbids_scaffold_apply() is False


def test_doctor_role_forbids_scaffold_apply(monkeypatch):
    monkeypatch.setenv(agent_role.ROLE_ENV, "doctor")
    assert agent_role.role_forbids_scaffold_apply() is True


def test_doctor_role_is_case_and_whitespace_insensitive(monkeypatch):
    monkeypatch.setenv(agent_role.ROLE_ENV, "  Doctor  ")
    assert agent_role.role_forbids_scaffold_apply() is True


# ------------------------------------------------------------ scaffold_apply_refusal


def test_scaffold_apply_refusal_for_doctor_names_the_role_and_the_action(monkeypatch):
    monkeypatch.setenv(agent_role.ROLE_ENV, "doctor")
    result = agent_role.scaffold_apply_refusal()
    assert result["forbidden"] is True
    assert "doctor" in result["reason"]
    assert "--i-was-asked" in result["reason"]


def test_scaffold_apply_refusal_i_was_asked_wins_outright(monkeypatch):
    """The escape hatch: a caller that was genuinely told to run this
    passes the flag, and it wins regardless of role."""
    monkeypatch.setenv(agent_role.ROLE_ENV, "doctor")
    result = agent_role.scaffold_apply_refusal(i_was_asked=True)
    assert result["forbidden"] is False
    assert result["reason"] is None


def test_scaffold_apply_refusal_maintainer_role_not_forbidden(monkeypatch):
    """Positive control: a maintainer running scaffold by hand is never
    caught by this, with or without the flag."""
    monkeypatch.setenv(agent_role.ROLE_ENV, "maintainer")
    result = agent_role.scaffold_apply_refusal()
    assert result["forbidden"] is False


# -------------------------------------------------------------- settings_local_digest


def test_settings_local_digest_absent_when_no_file(tmp_path):
    result = agent_role.settings_local_digest(root=str(tmp_path))
    assert result["state"] == "absent"
    assert result["digest"] is None


def test_settings_local_digest_present_and_stable(tmp_path):
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.local.json").write_text(
        '{"permissions": {"allow": []}}', encoding="utf-8"
    )
    first = agent_role.settings_local_digest(root=str(tmp_path))
    second = agent_role.settings_local_digest(root=str(tmp_path))
    assert first["state"] == "present"
    assert first["digest"] == second["digest"]
    assert first["digest"]


def test_settings_local_digest_changes_when_content_changes(tmp_path):
    """The positive control for the whole point of this function: a
    permission gained mid-run must not read the same as one that was
    always there."""
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    settings_path = settings_dir / "settings.local.json"
    settings_path.write_text('{"permissions": {"allow": []}}', encoding="utf-8")
    before = agent_role.settings_local_digest(root=str(tmp_path))
    settings_path.write_text(
        '{"permissions": {"allow": ["Bash(gh label create:*)"]}}', encoding="utf-8"
    )
    after = agent_role.settings_local_digest(root=str(tmp_path))
    assert before["digest"] != after["digest"]


def test_settings_local_digest_unreadable_directory_is_not_absent(
    tmp_path, monkeypatch
):
    """The negative control's sibling: a settings file this process cannot
    read must not render the same as a repo that genuinely has none."""
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    settings_path = settings_dir / "settings.local.json"
    settings_path.write_text("{}", encoding="utf-8")

    real_read_bytes = Path.read_bytes

    def fake_read_bytes(self):
        if self == settings_path:
            raise OSError("permission denied")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)
    result = agent_role.settings_local_digest(root=str(tmp_path))
    assert result["state"] == "unreadable"
    assert result["digest"] != None  # noqa: E711 -- it is a reason string, not None
