"""#1631: `doctor.py` never looked at the size of a managed repo's own
`CLAUDE.md` -- a byte added to it is paid on every turn of every agent
forever, and nothing said so. `check_claude_md_size` compares it against a
per-repo threshold read from `.oss.json`'s own `claude_md_size_threshold`
(joining the `*_route_threshold` family), in four states, never two: `over`,
`under`, `unconfigured` (absent threshold must not read as `ok`) and
`could-not-tell` (an absent or unreadable file must never render as a size
of zero).

Every negative assertion here is paired with a positive control in the same
fixture, per this repository's own rule: an assertion that a WARN did not
fire also passes when the check never ran at all.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_claude_md_size as mod  # noqa: E402


def setup_function(_):
    doctor.FINDINGS.clear()


def _levels():
    return [level for level, _ in doctor.FINDINGS]


def _text():
    return "\n".join(message for _, message in doctor.FINDINGS)


# ------------------------------------------------------- claude_md_size_state


def test_over_threshold_is_over(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("x" * 100, encoding="utf-8")
    state, size, detail = mod.claude_md_size_state(str(tmp_path), 50)
    assert state == "over", detail
    assert size == 100
    assert "100" in detail and "50" in detail


def test_under_threshold_is_under(tmp_path):
    """Positive control for the assertion above: a small file beside the
    identical configured threshold must not also read as `over`."""
    (tmp_path / "CLAUDE.md").write_text("x" * 10, encoding="utf-8")
    state, size, detail = mod.claude_md_size_state(str(tmp_path), 50)
    assert state == "under", detail
    assert size == 10


def test_no_configured_threshold_is_unconfigured_never_ok(tmp_path):
    """Absent config must not render identically to a repo comfortably under
    a configured limit -- this is its own state, not folded into `under`."""
    (tmp_path / "CLAUDE.md").write_text("x" * 500000, encoding="utf-8")
    state, size, detail = mod.claude_md_size_state(str(tmp_path), None)
    assert state == "unconfigured", detail
    assert size == 500000


def test_a_non_positive_or_wrong_typed_threshold_is_also_unconfigured(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("x", encoding="utf-8")
    assert mod.claude_md_size_state(str(tmp_path), 0)[0] == "unconfigured"
    assert mod.claude_md_size_state(str(tmp_path), -5)[0] == "unconfigured"
    assert mod.claude_md_size_state(str(tmp_path), "50")[0] == "unconfigured"
    assert mod.claude_md_size_state(str(tmp_path), True)[0] == "unconfigured"


def test_a_missing_claude_md_is_could_not_tell_never_zero(tmp_path):
    """The defect class this plugin is named after, in a size check: a
    missing file and a genuinely tiny one must not both read as small."""
    state, size, detail = mod.claude_md_size_state(str(tmp_path), 50)
    assert state == "could-not-tell", detail
    assert size is None


def test_an_unreadable_claude_md_is_also_could_not_tell(tmp_path, monkeypatch):
    (tmp_path / "CLAUDE.md").write_text("x", encoding="utf-8")

    def _boom(self):
        raise PermissionError("nope")

    monkeypatch.setattr(Path, "stat", _boom)
    state, size, detail = mod.claude_md_size_state(str(tmp_path), 50)
    assert state == "could-not-tell", detail
    assert size is None


# ------------------------------------------------------------- the check itself


def test_check_warns_over_threshold_and_names_the_jit_route(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("x" * 100, encoding="utf-8")
    mod.check_claude_md_size(str(tmp_path), {"claude_md_size_threshold": 50})
    assert _levels() == ["WARN"]
    text = _text()
    assert ".claude/jit-context/paths/" in text
    assert ".claude/jit-context/tools/" in text
    assert ".claude/jit-context/vocabulary/" in text
    assert "claude-jit-context:vocabulary" in text


def test_check_passes_under_threshold(tmp_path):
    """Positive control for the WARN above: a small file under the same
    configured threshold reports OK, not the same WARN."""
    (tmp_path / "CLAUDE.md").write_text("x" * 10, encoding="utf-8")
    mod.check_claude_md_size(str(tmp_path), {"claude_md_size_threshold": 50})
    assert _levels() == ["OK"]


def test_check_reports_notice_never_ok_when_unconfigured(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("x" * 500000, encoding="utf-8")
    mod.check_claude_md_size(str(tmp_path), {})
    assert _levels() == ["NOTICE"]
    assert "claude_md_size_threshold" in _text()


def test_check_reports_notice_never_ok_on_a_missing_file(tmp_path):
    mod.check_claude_md_size(str(tmp_path), {"claude_md_size_threshold": 50})
    assert _levels() == ["NOTICE"]
    assert "third state" in _text()


def test_check_tolerates_a_non_dict_config(tmp_path):
    """`config` can be `None` -- the same shape every sibling check in this
    file family accepts when `.oss.json` could not be loaded at all."""
    (tmp_path / "CLAUDE.md").write_text("x", encoding="utf-8")
    mod.check_claude_md_size(str(tmp_path), None)
    assert _levels() == ["NOTICE"]
