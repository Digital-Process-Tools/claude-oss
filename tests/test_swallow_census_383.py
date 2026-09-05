"""#383: the swallow census. Two rglob walks in doctor.py rank first because the
swallow is invisible to the guard beside them -- `Path.rglob` swallows
`PermissionError` while it walks and silently yields nothing for the subtree it
could not enter (CLAUDE.md's `Path.rglob`/`Path.is_dir` bullet, #124), so an
`except OSError` wrapped around the call can never fire for the case it was
written for. Confirmed directly below, against a real filesystem, before either
fix: `sorted(Path.rglob(...))` over a mode-000 directory returns `[]`, not a
raise -- the top-level `except OSError` in the old `agent_dispatch` was dead
code for exactly the input it was written to catch.

Every case is exercised twice, per this repo's own convention (`CLAUDE.md`, "a
permission fixture is a measurement, not a given"): an *injected* raise via
`os.scandir`, which reproduces the defect on every interpreter and platform
regardless of whether the local mode bit is honoured, and a real `chmod`-based
fixture that self-skips with what went untested when the platform's own
permission model does not take it (root, some filesystems, Windows' read-only
attribute not stopping a listing).

Every "must not silently drop a subtree" case is paired with a "must still find
everything readable" control in the same fixture -- a fix that reports every
walk as unreadable would pass the must-fire half and still be wrong.
"""

import errno
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import release_delta  # noqa: E402
import rename_changelog_fragment  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _raise_scandir_for(monkeypatch, target, exc):
    """Patch `os.scandir` to raise `exc` only when called on `target`'s own
    path, and behave normally everywhere else -- self-verifying, since a
    fixture that patched every call would make the "must fire" and "must not
    fire" cases in the same tree indistinguishable. `os.walk` calls
    `os.scandir` directly (not through any `Path` method), so this is the
    call `os.walk(onerror=...)` itself makes, not a proxy for it.
    """
    real_scandir = os.scandir
    target = os.path.normpath(str(target))

    def fake(path="."):
        if os.path.normpath(os.fspath(path)) == target:
            raise exc
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", fake)


# ---------------------------------------------------------------------------
# The measurement this file's docstring claims, pinned rather than asserted
# in prose: rglob over a permission-denied directory returns [], not a raise.
# ---------------------------------------------------------------------------


def test_rglob_over_denied_directory_returns_empty_not_a_raise(tmp_path):
    """The reproduction. If this ever raises on some platform/version, the
    `except OSError` sites this issue is about were not dead code there and
    the rest of this file's premise needs re-checking on that platform.
    """
    denied = tmp_path / "denied"
    denied.mkdir()
    (denied / "x.md").write_text("x", encoding="utf-8")
    try:
        os.chmod(str(denied), 0o000)
    except OSError as exc:
        pytest.skip(
            "os.chmod would not set mode 000 ({}); what went untested is "
            "whether rglob swallows on this platform".format(exc)
        )
    try:
        if os.access(str(denied), os.R_OK):
            pytest.skip(
                "this process can read a 0o000 directory (root, or a "
                "filesystem without POSIX modes); what went untested is "
                "whether rglob swallows on this platform"
            )
        result = sorted(denied.rglob("*.md"))
    finally:
        os.chmod(str(denied), 0o700)
    assert result == [], (
        "rglob raised instead of swallowing -- the premise this file is "
        "built on does not hold on this platform"
    )


# ---------------------------------------------------------------------------
# check_jit_rules: a nested layer directory os.walk cannot enter must be
# reported, not silently missing from the layer count.
# ---------------------------------------------------------------------------


def _rules_tree(project_dir):
    rules_dir = project_dir / doctor.JIT_RULES_DIR
    good_layer = rules_dir / "vocabulary" / "01-oss"
    good_layer.mkdir(parents=True)
    (good_layer / "rule.md").write_text("rule", encoding="utf-8")
    (good_layer / doctor.JIT_INDEX).write_text("name\trule.md\n", encoding="utf-8")
    return rules_dir, good_layer


def test_check_jit_rules_unreadable_subtree_is_reported_injected(monkeypatch, tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    rules_dir, good_layer = _rules_tree(project_dir)
    bad_layer = rules_dir / "tools" / "01-oss"
    bad_layer.mkdir(parents=True)
    (bad_layer / "rule.md").write_text("rule", encoding="utf-8")

    _raise_scandir_for(monkeypatch, bad_layer, PermissionError(errno.EACCES, "denied"))

    doctor.check_jit_rules(project_dir)
    joined = " ".join(message for _, message in doctor.FINDINGS)

    # Must-fire half: the subtree os.walk could not enter is named, not
    # silently absent from the layer count.
    assert "could not fully walk" in joined, joined
    assert "denied" in joined, joined

    # Must-not-fire control, same fixture: the readable layer is still
    # found and reported, not swallowed along with the unreadable one.
    assert "vocabulary" in joined, joined
    assert not any(level == "FAIL" for level, _ in doctor.FINDINGS), doctor.FINDINGS


def test_check_jit_rules_unreadable_subtree_is_reported_real_chmod(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    rules_dir, good_layer = _rules_tree(project_dir)
    bad_layer_parent = rules_dir / "tools"
    bad_layer_parent.mkdir(parents=True)
    (bad_layer_parent / "01-oss").mkdir()
    (bad_layer_parent / "01-oss" / "rule.md").write_text("rule", encoding="utf-8")

    try:
        os.chmod(str(bad_layer_parent), 0o000)
    except OSError as exc:
        pytest.skip(
            "os.chmod would not set mode 000 ({}); what went untested is "
            "whether a real unreadable subtree is reported".format(exc)
        )
    try:
        if os.access(str(bad_layer_parent), os.R_OK):
            pytest.skip(
                "this process can read a 0o000 directory (root, or a "
                "filesystem without POSIX modes); what went untested is "
                "whether a real unreadable subtree is reported"
            )
        doctor.check_jit_rules(project_dir)
    finally:
        os.chmod(str(bad_layer_parent), 0o700)

    joined = " ".join(message for _, message in doctor.FINDINGS)
    assert "could not fully walk" in joined, joined
    assert "vocabulary" in joined, joined


def test_check_jit_rules_genuinely_clean_tree_reports_no_walk_warning(tmp_path):
    """Must-not-fire control on a tree with nothing hidden: no "could not
    fully walk" line when everything really is readable.
    """
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _rules_tree(project_dir)

    doctor.check_jit_rules(project_dir)
    joined = " ".join(message for _, message in doctor.FINDINGS)
    assert "could not fully walk" not in joined, joined
    assert "vocabulary" in joined, joined


# ---------------------------------------------------------------------------
# agent_dispatch: an unreadable DISPATCHING_DIRECTORIES entry must be
# reported as unreadable, not read as "nothing dispatches here".
# ---------------------------------------------------------------------------


def _fake_plugin(root, documents, agents):
    for relative, text in documents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    agent_dir = root / "agents"
    agent_dir.mkdir(parents=True, exist_ok=True)
    for name in agents:
        (agent_dir / (name + ".md")).write_text("name: " + name, encoding="utf-8")
    return root


def test_agent_dispatch_unreadable_directory_is_reported_injected(
    monkeypatch, tmp_path
):
    root = _fake_plugin(
        tmp_path,
        {
            "commands/release.md": 'Agent(subagent_type: "oss:developer")',
            "skills/manager/SKILL.md": 'Agent(subagent_type: "oss:triager")',
        },
        ["developer", "triager"],
    )
    bad = root / "commands"
    _raise_scandir_for(monkeypatch, bad, PermissionError(errno.EACCES, "denied"))

    lines = doctor.agent_dispatch(root)
    joined = " ".join(message for _, message in lines)

    # Must-fire half: before the fix, `Path.rglob` over a directory os.walk
    # cannot enter returns [] and no WARN names it -- the top-level
    # `except OSError` this replaces was dead code for exactly this input
    # (see the reproduction above).
    assert any(level == "WARN" for level, _ in lines), lines
    assert "commands" in joined, joined
    assert "denied" in joined, joined

    # Must-not-fire control, same fixture: the readable directory is still
    # scanned and its dispatch found.
    assert "oss:triager" in joined, joined


def test_agent_dispatch_unreadable_directory_is_reported_real_chmod(tmp_path):
    root = _fake_plugin(
        tmp_path,
        {
            "commands/release.md": 'Agent(subagent_type: "oss:developer")',
            "skills/manager/SKILL.md": 'Agent(subagent_type: "oss:triager")',
        },
        ["developer", "triager"],
    )
    bad = root / "commands"

    try:
        os.chmod(str(bad), 0o000)
    except OSError as exc:
        pytest.skip(
            "os.chmod would not set mode 000 ({}); what went untested is "
            "whether a real unreadable directory is reported".format(exc)
        )
    try:
        if os.access(str(bad), os.R_OK):
            pytest.skip(
                "this process can read a 0o000 directory (root, or a "
                "filesystem without POSIX modes); what went untested is "
                "whether a real unreadable directory is reported"
            )
        lines = doctor.agent_dispatch(root)
    finally:
        os.chmod(str(bad), 0o700)

    joined = " ".join(message for _, message in lines)
    assert any(level == "WARN" for level, _ in lines), lines
    assert "commands" in joined, joined
    assert "oss:triager" in joined, joined


def test_agent_dispatch_genuinely_absent_directory_still_scans_the_rest(tmp_path):
    """Must-not-fire control at the DISPATCHING_DIRECTORIES level itself: a
    genuinely absent directory must not be reported as unreadable -- that
    would be the opposite defect, an absence read as a permission finding.

    Self-review, #383: an earlier version of this test called
    `doctor.agent_dispatch(REPO_ROOT)`, on the belief that no `skills/`
    directory exists there, and it does -- this checkout ships
    `skills/manager/SKILL.md`. The assertion was an `or` that is true
    whenever no unreadable-directory message appears at all, which is the
    ordinary case on any readable tree regardless of whether this fix is
    applied -- reverting the whole commit leaves it passing unchanged. A
    fabricated root with `commands/` but no `skills/` or `agents/` at all is
    what the docstring actually claims to test.
    """
    root = _fake_plugin(
        tmp_path,
        {"commands/release.md": 'Agent(subagent_type: "oss:developer")'},
        ["developer"],
    )
    assert not (root / "skills").exists(), "fixture assumption: no skills/ dir"

    lines = doctor.agent_dispatch(root)
    joined = " ".join(message for _, message in lines)
    assert "could not" not in joined, lines
    assert "skills" not in joined, lines
    # And the must-fire half stays reachable in the same fixture: the one
    # directory that IS there and readable is still scanned and used.
    assert "oss:developer" in joined, joined


# ---------------------------------------------------------------------------
# plugin_supertool_entries: a bare `Path.is_file()` on one cache entry must
# not crash the whole scan (#383, adjacent to the two rglob sites -- same
# subsystem, same census).
# ---------------------------------------------------------------------------


def _raise_for(monkeypatch, method_name, target, exc):
    real = getattr(Path, method_name)

    def fake(self, *a, **kw):
        if self == target:
            raise exc
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, method_name, fake)


def test_plugin_supertool_entries_survives_one_unreadable_entry(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    # <root>/<market>/<SUPERTOOL_ENTRY>/<version>/<SUPERTOOL_CORE>, the layout
    # `plugin_supertool_entries` itself expects.
    base = cache / "marketplace" / doctor.SUPERTOOL_ENTRY
    good = base / "1.0.0"
    good.mkdir(parents=True)
    (good / doctor.SUPERTOOL_CORE).write_text("x", encoding="utf-8")
    bad = base / "2.0.0"
    bad.mkdir(parents=True)
    bad_entry = bad / doctor.SUPERTOOL_CORE
    bad_entry.write_text("x", encoding="utf-8")

    # Before the fix: this raises out of plugin_supertool_entries instead of
    # dropping the one bad candidate the way #363's other filter sites do.
    _raise_for(
        monkeypatch, "is_file", bad_entry, PermissionError(errno.EACCES, "denied")
    )

    found = doctor.plugin_supertool_entries(cache_root=str(cache))
    versions = [v for v, _ in found]
    assert "1.0.0" in versions, found
    assert "2.0.0" not in versions, found


# ---------------------------------------------------------------------------
# rename_changelog_fragment.rename: the source-file check must not raise for
# an unreadable source, mirroring `_destination_occupied`'s own reasoning
# about the destination (#383).
# ---------------------------------------------------------------------------


def test_rename_source_unreadable_is_refused_not_raised(monkeypatch, tmp_path):
    fragment = tmp_path / "12.fixed.md"
    fragment.write_text("fixed something (#12)", encoding="utf-8")

    real_stat = os.stat
    target = str(fragment)

    def fake_stat(path, *a, **kw):
        if os.fspath(path) == target:
            raise PermissionError(errno.EACCES, "denied")
        return real_stat(path, *a, **kw)

    monkeypatch.setattr(os, "stat", fake_stat)

    state, message, new_path = rename_changelog_fragment.rename(str(fragment), 34)
    assert state == rename_changelog_fragment.REFUSED, (state, message)
    assert "could not be examined" in message, message
    assert new_path is None, new_path


def test_rename_source_genuinely_absent_is_still_refused_as_no_such_file(tmp_path):
    fragment = tmp_path / "does-not-exist.fixed.md"

    state, message, new_path = rename_changelog_fragment.rename(str(fragment), 34)
    assert state == rename_changelog_fragment.REFUSED, (state, message)
    assert "no such file" in message, message


# ---------------------------------------------------------------------------
# release_delta._compute_range: `compute()` promises "never raises" and a
# bare `Path.is_dir()` broke that promise for an unreadable parent (#383).
# ---------------------------------------------------------------------------


def test_compute_range_unreadable_repo_path_does_not_raise(monkeypatch, tmp_path):
    """`_compute_range` was rewritten to call `os.path.isdir`, not
    `Path.is_dir` -- `genericpath.isdir` reaches `os.stat` directly, never
    through `pathlib`, so the injected raise has to sit on `os.stat` itself
    (self-review, #383: a first version of this test patched `Path.is_dir`,
    which the fixed code no longer calls at all, and passed only because the
    fixture target genuinely does not exist -- a guard with no positive
    control on the code path it claims to exercise).
    """
    target = tmp_path / "maybe-a-repo"
    real_stat = os.stat
    target_str = str(target)

    def fake_stat(path, *a, **kw):
        if os.fspath(path) == target_str:
            raise PermissionError(errno.EACCES, "denied")
        return real_stat(path, *a, **kw)

    monkeypatch.setattr(os, "stat", fake_stat)

    # Before the fix, `_compute_range` called `Path.is_dir()`, which raises
    # unguarded for exactly this fixture on at least 3.9/3.11/3.13 -- a crash
    # from a function `compute()`'s own docstring says never raises.
    payload = release_delta.compute(str(target))
    assert payload["state"] == release_delta.STATE_COULD_NOT_RUN, payload
    assert "could not be examined" in payload["reason"], payload


def test_compute_range_genuinely_absent_repo_path_still_could_not_run(tmp_path):
    target = tmp_path / "not-a-repo"

    payload = release_delta.compute(str(target))
    assert payload["state"] == release_delta.STATE_COULD_NOT_RUN, payload
    assert "not a directory" in payload["reason"], payload


# ---------------------------------------------------------------------------
# agent_dispatch's OWN comparison directory: `Path.glob("*.md")` over
# `agents/` swallows the same way `Path.rglob` does one level up (self-review
# finding, #383) -- the `except OSError` around it could never fire for the
# case it was written for.
# ---------------------------------------------------------------------------


def test_agent_dispatch_unreadable_agents_directory_is_reported_injected(
    monkeypatch, tmp_path
):
    root = _fake_plugin(
        tmp_path,
        {"commands/release.md": 'Agent(subagent_type: "oss:developer")'},
        ["developer"],
    )
    agents_dir = root / "agents"
    _raise_scandir_for(monkeypatch, agents_dir, PermissionError(errno.EACCES, "denied"))

    lines = doctor.agent_dispatch(root)
    joined = " ".join(message for _, message in lines)

    # Must-fire half: before the fix, `Path.glob` over `agents/` swallows the
    # PermissionError and returns [], so `shipped` becomes `{}` and every
    # dispatched name is reported FAIL-missing instead of WARN-could-not-tell.
    assert any(level == "WARN" for level, _ in lines), lines
    assert "agents/ could not be listed" in joined, joined
    assert not any(level == "FAIL" for level, _ in lines), lines


def test_agent_dispatch_unreadable_agents_directory_is_reported_real_chmod(tmp_path):
    root = _fake_plugin(
        tmp_path,
        {"commands/release.md": 'Agent(subagent_type: "oss:developer")'},
        ["developer"],
    )
    agents_dir = root / "agents"

    try:
        os.chmod(str(agents_dir), 0o000)
    except OSError as exc:
        pytest.skip(
            "os.chmod would not set mode 000 ({}); what went untested is "
            "whether a real unreadable agents/ is reported".format(exc)
        )
    try:
        if os.access(str(agents_dir), os.R_OK):
            pytest.skip(
                "this process can read a 0o000 directory (root, or a "
                "filesystem without POSIX modes); what went untested is "
                "whether a real unreadable agents/ is reported"
            )
        lines = doctor.agent_dispatch(root)
    finally:
        os.chmod(str(agents_dir), 0o700)

    # Before the fix (measured directly, real chmod, not just this suite):
    # the loop over DISPATCHING_DIRECTORIES already warns about agents/
    # being unreadable, but the separate `shipped` comparison still swallowed
    # the same directory via a bare `Path.glob` and reported a false FAIL
    # ("no agents/<name>.md ships it") for a name that is not missing, only
    # unreadable.
    assert not any(level == "FAIL" for level, _ in lines), lines
    assert any(level == "WARN" for level, _ in lines), lines


def test_agent_dispatch_readable_agents_directory_still_scans_clean(tmp_path):
    """Must-not-fire control, same fixture shape: an ordinary readable
    agents/ directory must still resolve normally -- this file's other test,
    `test_agent_dispatch_is_clean_on_this_plugin_and_still_states_what_it_cannot_know`,
    already covers the real plugin tree; this is the fabricated-fixture twin.
    """
    root = _fake_plugin(
        tmp_path,
        {"commands/release.md": 'Agent(subagent_type: "oss:developer")'},
        ["developer"],
    )
    lines = doctor.agent_dispatch(root)
    assert [level for level, _ in lines] == ["OK"], lines
