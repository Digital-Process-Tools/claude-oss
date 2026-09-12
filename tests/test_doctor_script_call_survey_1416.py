"""#1416: `check_script_call_survey` is the `/oss:doctor` entry point for
`scripts/script_call_survey.py`'s own three-state classification -- a
`NOTICE`, never a `WARN`/`FAIL`, since this check lists rather than judges.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_script_call_survey as mod  # noqa: E402


def _plugin(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "commands").mkdir()
    (tmp_path / "agents").mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "bin").mkdir()
    return tmp_path


def test_reports_a_single_notice_naming_mentioned_only_scripts(tmp_path):
    root = _plugin(tmp_path)
    (root / "scripts" / "called_one.py").write_text("print(1)", encoding="utf-8")
    (root / "scripts" / "described_only.py").write_text("print(1)", encoding="utf-8")
    (root / "commands" / "foo.md").write_text(
        "```bash"
        + chr(10)
        + "python3 scripts/called_one.py"
        + chr(10)
        + "```"
        + chr(10)
        + "`scripts/described_only.py` computes something."
        + chr(10),
        encoding="utf-8",
    )
    doctor.FINDINGS.clear()
    mod.check_script_call_survey(str(root))
    assert len(doctor.FINDINGS) == 1
    state, message = doctor.FINDINGS[0]
    assert state == "NOTICE", message
    assert "1 script(s) called" in message, message
    assert "1 mentioned-only" in message, message
    assert "described_only.py" in message, message
    assert "called_one.py" not in message.split("Mentioned-only:")[-1], message


def test_never_reports_a_finding_that_fails_or_warns_on_its_own_account(tmp_path):
    """The check lists, it does not judge (#1416): a directory with every
    script only mentioned in prose must still render `NOTICE`, never
    `WARN`/`FAIL`."""
    root = _plugin(tmp_path)
    (root / "scripts" / "orphan.py").write_text("print(1)", encoding="utf-8")
    doctor.FINDINGS.clear()
    mod.check_script_call_survey(str(root))
    assert len(doctor.FINDINGS) == 1
    state, _message = doctor.FINDINGS[0]
    assert state == "NOTICE", _message


def test_an_unreadable_root_warns_rather_than_silently_undercounting(
    tmp_path, monkeypatch
):
    """Must-fire: a root this survey could not list must surface as WARN,
    never a clean NOTICE that quietly omits it."""
    root = _plugin(tmp_path)
    (root / "scripts" / "x.py").write_text("print(1)", encoding="utf-8")

    import doctor as doctor_mod

    real_dir_state = doctor_mod._dir_state

    def _fake(path):
        if str(path).endswith("commands"):
            return "unreadable", "simulated permission denial"
        return real_dir_state(path)

    monkeypatch.setattr(doctor_mod, "_dir_state", _fake)
    doctor.FINDINGS.clear()
    mod.check_script_call_survey(str(root))
    assert len(doctor.FINDINGS) == 1
    state, message = doctor.FINDINGS[0]
    assert state == "WARN", message
