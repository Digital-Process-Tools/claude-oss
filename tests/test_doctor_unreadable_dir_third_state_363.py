"""#363: six more is_dir()/exists() swallow sites in doctor.py, the same
class #341 closed one instance of, one call site over.

An unreadable *parent* of a directory makes `Path.is_dir()`/`Path.exists()`
raise `OSError` on at least 3.9, 3.11 and 3.13 (this repo's own measurement,
recorded beside `_safe_is_file` in doctor.py and in CLAUDE.md for `exists()`)
and swallow to `False` only on this repo's local 3.14. Before this fix every
site here let that raise either crash the process or -- where pathlib's own
swallow happened to fire -- read as a confident "does not exist", with a
remedy attached, exactly #341's own sentence one check family over.

Every case below is exercised twice: an *injected* raise, which reproduces
the defect on every interpreter regardless of which one runs the suite, and
-- where a real fixture is possible -- a `chmod`-based one, self-skipping
with what went untested when the platform's own permission model does not
take (root, some filesystems, Windows' read-only attribute not stopping a
listing).

Every "must not fire" case is paired with a "must fire" case in the same
fixture: a genuinely absent directory must still report absence, not the new
third state swallowing every negative into "unknown".
"""

import errno
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _raise_for(monkeypatch, method_name, target, exc):
    """Patch `Path.<method_name>` to raise `exc` only when called on `target`,
    and behave normally everywhere else -- self-verifying, since a fixture
    that patched every call would make the "must fire" and "must not fire"
    cases indistinguishable.
    """
    real = getattr(Path, method_name)

    def fake(self, *a, **kw):
        if self == target:
            raise exc
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, method_name, fake)


# ---------------------------------------------------------------------------
# check_directory (~line 1251): config's `clone` / `worktree_root`
# ---------------------------------------------------------------------------


def test_check_directory_unreadable_reports_unknown_not_absent(monkeypatch, tmp_path):
    """The must-fire half. An unreadable directory must not print "does not
    exist" with the remedy that sentence carries.
    """
    target = tmp_path / "maybe-there"
    _raise_for(monkeypatch, "stat", target, PermissionError(errno.EACCES, "denied"))

    doctor.check_directory("clone", str(target))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)
    assert "does not exist" not in message, message
    assert "unknown" in message, message


def test_check_directory_genuinely_absent_still_reports_absent(tmp_path):
    """The must-not-fire control, same fixture shape: a directory that truly
    is not there must still say so.
    """
    target = tmp_path / "not-there"

    doctor.check_directory("clone", str(target))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)
    assert "does not exist" in message, message


def test_check_directory_real_unreadable_parent_reaches_unknown(tmp_path):
    """Same claim, measured against a real filesystem rather than injected.

    Confirmed by attempting the exact operation `_dir_state` performs --
    `Path.stat()` on the child, not `Path.is_dir()` -- because root ignores
    the mode bit, some filesystems ignore it, Windows' `os.chmod` on a
    directory toggles a read-only attribute that does not stop a listing,
    and -- the reason this probes `stat()` specifically rather than
    `is_dir()` (self-review, #363) -- on this repo's local Python 3.14,
    `Path.is_dir()` itself swallows the very `PermissionError` `stat()`
    raises, so a probe against `is_dir()` would report "the mode bit did not
    deny traversal on this platform" when the mode bit did, and the true
    cause was the interpreter's own pathlib, not the platform. Probing the
    call the code under test actually makes is what a permission fixture
    being a measurement rather than a given means here.
    """
    import os

    parent = tmp_path / "denied-parent"
    parent.mkdir()
    child = parent / "child"
    child.mkdir()

    try:
        os.chmod(str(parent), 0o000)
    except OSError as exc:
        pytest.skip(
            "os.chmod would not set mode 000 ({}); what went untested is "
            "whether a real unreadable parent reaches the unknown "
            "state".format(exc)
        )

    try:
        try:
            child.stat()
        except OSError:
            pass
        else:
            pytest.skip(
                "the mode bit did not deny traversal on this platform/"
                "filesystem: Path.stat() on the child succeeded despite "
                "the denied parent. What went untested is whether a real "
                "unreadable parent reaches the unknown state."
            )

        doctor.check_directory("clone", str(child))
        level, message = doctor.FINDINGS[-1]
        assert level == "WARN", (level, message)
        assert "does not exist" not in message, message
        assert "unknown" in message, message
    finally:
        os.chmod(str(parent), 0o700)


# ---------------------------------------------------------------------------
# check_jit_rules (~line 2548): rules_dir.is_dir()
# ---------------------------------------------------------------------------


def test_check_jit_rules_unreadable_reports_unknown_not_absent(monkeypatch, tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    target = project_dir / doctor.JIT_RULES_DIR
    _raise_for(monkeypatch, "stat", target, PermissionError(errno.EACCES, "denied"))

    doctor.check_jit_rules(project_dir)
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)
    assert "no rules for this repo" not in message, message
    assert "unknown" in message, message


def test_check_jit_rules_genuinely_absent_still_reports_no_rules(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    doctor.check_jit_rules(project_dir)
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", (level, message)
    assert "no rules for this repo" in message, message


# ---------------------------------------------------------------------------
# resolve_project_dir's own `chosen.is_dir()` (~line 4875): the entry point
# where the third state is established rather than consumed.
# ---------------------------------------------------------------------------


def test_resolve_project_dir_unreadable_root_reports_unknown_not_fail(monkeypatch, tmp_path):
    """#363's own established fact: `is_dir()` on a mode-000 *target*
    succeeds, since `stat` needs execute permission on the parent, not the
    target -- so #341's own reproduction never reaches this line, and the
    scenario is an unreadable *parent* of `--root`.
    """
    target = tmp_path / "maybe-a-repo"
    _raise_for(monkeypatch, "stat", target, PermissionError(errno.EACCES, "denied"))

    chosen, findings = doctor.resolve_project_dir(str(target), None, str(tmp_path))
    assert chosen == target
    levels = [level for level, _ in findings]
    assert "FAIL" not in levels, findings
    assert any("unknown" in message for _, message in findings), findings
    assert not any("not a directory" in message for _, message in findings), findings


def test_resolve_project_dir_genuinely_absent_root_still_fails(tmp_path):
    """The must-not-fire control: `--root` naming a path that plainly is not
    a directory must still be a FAIL -- the state this fix must not widen
    away.
    """
    target = tmp_path / "not-a-repo"

    chosen, findings = doctor.resolve_project_dir(str(target), None, str(tmp_path))
    levels = [level for level, message in findings]
    assert "FAIL" in levels, findings
    assert any("not a directory" in message for _, message in findings), findings


def test_resolve_project_dir_unreadable_git_check_reports_unknown(monkeypatch, tmp_path):
    """The narrow sibling at the same call site: `(chosen / ".git").exists()`
    raising must not crash `resolve_project_dir` and must not silently read
    as "no .git here".
    """
    target = tmp_path / "a-repo"
    target.mkdir()
    git_marker = target / ".git"
    _raise_for(monkeypatch, "exists", git_marker, PermissionError(errno.EACCES, "denied"))

    chosen, findings = doctor.resolve_project_dir(str(target), None, str(tmp_path))
    assert chosen == target
    levels = [level for level, _ in findings]
    assert "FAIL" not in levels, findings
    assert any("unknown" in message for _, message in findings), findings
    assert not any("no .git here" in message for _, message in findings), findings


def test_resolve_project_dir_git_absent_still_warns(tmp_path):
    """Must-not-fire control for the sibling above: a real directory with no
    `.git` must still get the ordinary WARN.
    """
    target = tmp_path / "not-a-git-repo"
    target.mkdir()

    chosen, findings = doctor.resolve_project_dir(str(target), None, str(tmp_path))
    assert any("no .git here" in message for _, message in findings), findings


# ---------------------------------------------------------------------------
# merge_permission_state (~line 1592): path.exists() over settings_candidates
# ---------------------------------------------------------------------------


def test_merge_permission_state_unreadable_candidate_reaches_unknown_bucket(monkeypatch, tmp_path):
    """The function already has an `unknown` bucket for exactly this kind of
    failure and never reached it (#363). An `.exists()` raise on one
    candidate must land there, not be silently `continue`d past.
    """
    home = tmp_path / "home"
    home.mkdir()
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    candidates = doctor.settings_candidates(project_dir, home=home)
    assert candidates, "fixture assumption: at least one candidate path"
    target = candidates[0]
    _raise_for(monkeypatch, "exists", target, PermissionError(errno.EACCES, "denied"))

    state, detail = doctor.merge_permission_state(project_dir, home=home)
    assert state == "unknown", (state, detail)


def test_merge_permission_state_genuinely_absent_candidates_stay_absent(tmp_path):
    """Must-not-fire control: no settings files at all must still resolve to
    `absent`, not `unknown`.
    """
    home = tmp_path / "home"
    home.mkdir()
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    state, detail = doctor.merge_permission_state(project_dir, home=home)
    assert state == "absent", (state, detail)


# ---------------------------------------------------------------------------
# The two narrow glob filters (~3505, ~3776): one bad candidate must not
# wipe every candidate already found.
# ---------------------------------------------------------------------------


def test_jit_hook_roots_survives_one_unreadable_candidate(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    version = "0.5.0"
    good = cache / "marketplace" / doctor.JIT_PLUGIN / version
    good.mkdir(parents=True)
    bad = cache / "other" / doctor.JIT_PLUGIN / version
    bad.mkdir(parents=True)

    _raise_for(monkeypatch, "is_dir", bad, PermissionError(errno.EACCES, "denied"))

    record = tmp_path / "installed-plugins.json"
    record.write_text(
        json.dumps(
            {
                "plugins": {
                    "{}@marketplace".format(doctor.JIT_PLUGIN): [
                        {"version": version}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    roots, resolved_version = doctor.jit_hook_roots(record=str(record), cache_root=str(cache))
    assert resolved_version == version, resolved_version
    assert good in roots, roots
    assert bad not in roots, roots


def test_jit_layer_verdict_survives_one_unreadable_dimension_candidate(monkeypatch, tmp_path):
    project_dir = tmp_path / "project"
    layer = "01-oss"
    good = project_dir / doctor.JIT_RULES_DIR / "vocabulary" / layer
    good.mkdir(parents=True)
    bad = project_dir / doctor.JIT_RULES_DIR / "paths" / layer
    bad.mkdir(parents=True)

    _raise_for(monkeypatch, "is_dir", bad, PermissionError(errno.EACCES, "denied"))

    # Before the fix, one candidate raising inside the glob filter propagates
    # out of the whole comprehension and is caught by the function's own
    # outer `except OSError`, which discards the readable candidate along
    # with the unreadable one and reports "would not be listed" -- would
    # raise/mis-report here if the per-candidate filter did nothing.
    state, detail = doctor._jit_layer_verdict(project_dir, layer, record=None, cache_root=None)
    assert not (state == "could-not-determine" and "would not be listed" in detail), (
        state,
        detail,
    )
