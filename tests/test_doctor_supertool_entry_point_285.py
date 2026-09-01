"""#285 -- `OK supertool: available` answers PATH, and no brief asks about PATH.

Every developer brief this plugin issues says to call `./supertool`, and this repo's
own rule layer *blocks* Read/Edit/Write/Glob/Grep with a message naming the op that
replaces each. So the entry point is mandatory. It is also gitignored on purpose --
`scripts/scaffold.py` writes `/supertool` into a managed repo's `.gitignore` because
committing it would bake one developer's absolute path into every other clone.

Mandatory, and absent from every fresh clone by design. `check_tool("supertool", ...)`
says nothing about it: it answers *is the binary on PATH*, which a reader takes for
*does this repo have the entry point the brief named*. Two questions, one line, and the
remedies differ.

Observed while writing this, in the worktree the fix was written in: `ls -l ./supertool`
-> `No such file or directory`, while `which supertool` resolved. Both "OK" states of
the old check, in a tree where every op call through `./supertool` would have failed.

**Which component creates it is established here rather than left open**, which is the
half #285 filed as unknown and floated sending upstream. supertool's own
`hooks/session-start.sh` creates it, keyed on the session's cwd, and already handles all
three cases correctly -- it links when nothing is there, leaves a stranger untouched, and
refuses to link at all inside a supertool checkout. Nothing upstream is broken. What is
missing is entirely local: doctor never says which of those happened.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import doctor  # noqa: E402
import spawn_guard  # noqa: E402

MARKET = "dpt-plugins"
VERSION = "9.9.9"


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _cache(root, version=VERSION):
    """A plugin cache holding one supertool, plus the install record naming it active.

    Both, because ``active_versions`` reads the record and not the listing -- old
    versions stay unpacked and a glob returns whichever sorts last.
    """
    home = root / "cache"
    # Idempotent: a test that needs both a cache and a state calls this twice.
    (home / MARKET / "supertool" / version).mkdir(parents=True, exist_ok=True)
    entry = home / MARKET / "supertool" / version / "supertool.py"
    entry.write_text("# the plugin's entry point\n", encoding="utf-8")
    record = root / "installed_plugins.json"
    record.write_text(
        json.dumps({"plugins": {"supertool@" + MARKET: [{"version": version}]}}),
        encoding="utf-8",
    )
    return home, record, entry


def _link(where, target):
    """Symlink, or the sentence saying why this platform could not make one.

    Windows needs a privilege or Developer Mode for this, so the deny is measured by
    attempting it -- never assumed from ``sys.platform``.
    """
    try:
        os.symlink(str(target), str(where))
    except (OSError, NotImplementedError, AttributeError) as exc:
        return "this platform would not create a symlink ({})".format(exc)
    return None


def _state(project, root, **kw):
    home, record, entry = _cache(root)
    kw.setdefault("cache_root", str(home))
    kw.setdefault("record", str(record))
    return doctor.supertool_entry_point(project, **kw), entry


def test_absent_is_a_finding_and_names_what_creates_it(tmp_path):
    """The state of every fresh clone, and of every worktree an agent cuts mid-session:
    the hook fires on a session's cwd, and nothing fires when an agent cds into a
    directory that did not exist when the session opened."""
    project = tmp_path / "repo"
    project.mkdir()
    (state, detail), _ = _state(project, tmp_path)
    assert state == "absent", (state, detail)

    doctor.check_supertool_entry_point(project, cache_root=None, record=None)
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "./supertool" in message, message
    assert "session-start" in message, message


def test_the_plugins_own_link_is_the_passing_state(tmp_path):
    """Positive control. Without it every assertion in this file is satisfied by a
    check that returns a finding unconditionally."""
    project = tmp_path / "repo"
    project.mkdir()
    home, record, entry = _cache(tmp_path)
    refused = _link(project / "supertool", entry)
    if refused:
        pytest.skip(refused + "; what went untested is the matching-target arm")
    state, detail = doctor.supertool_entry_point(
        project, cache_root=str(home), record=str(record)
    )
    assert state == "ok", (state, detail)

    doctor.check_supertool_entry_point(project, cache_root=str(home), record=str(record))
    assert doctor.FINDINGS[-1][0] == "OK"


def test_reading_a_link_back_denotes_the_file_it_was_made_from(tmp_path):
    """The mechanism the Windows legs failed on, asserted without naming a platform.

    `os.readlink` on Windows returns the reparse point's substitute name, which carries
    the extended-length prefix -- the four characters backslash, backslash, question
    mark, backslash. `ntpath.realpath` then PRESERVES that prefix, measured in the
    stdlib source rather than inferred: `ntpath.py:683` sets `had_prefix =
    path.startswith(prefix)` and `:713` strips it only `if not had_prefix`. So one
    function applied to both sides of a comparison returns a prefixed string for the
    side that came through `readlink` and an unprefixed one for the side that did not,
    and a link pointing at exactly the right file compared unequal.

    **What is deliberately NOT asserted here is that the two strings differ, or that
    they match.** Either would be a platform assertion dressed up as a product one --
    true on Windows, false everywhere else -- and the repo rule is that a condition you
    cannot establish is skipped with what went untested rather than asserted from a
    table. What IS asserted is the question the code actually has to answer: do these
    two names denote the same file. That is a real assertion on every platform, and it
    is the one Windows was answering wrongly.
    """
    project = tmp_path / "repo"
    project.mkdir()
    home, record, entry = _cache(tmp_path)
    link = project / "supertool"
    refused = _link(link, entry)
    if refused:
        pytest.skip(refused + "; what went untested is the readlink round trip")

    target = os.readlink(str(link))
    resolved = os.path.realpath(os.path.join(str(link.parent), target))
    assert doctor._same_file(resolved, str(entry)) is True, (
        "the link was made from {!r} and reading it back reached {!r}, which the check "
        "does not recognise as the same file".format(str(entry), resolved)
    )


def _hardlink(where, target):
    """A second directory entry for one file, or the sentence saying why not.

    Measured by attempting it: hard links need the two paths on one volume, and some
    filesystems refuse them outright.
    """
    try:
        os.link(str(target), str(where))
    except (OSError, NotImplementedError, AttributeError) as exc:
        return "this filesystem would not create a hard link ({})".format(exc)
    return None


def test_the_comparison_is_identity_and_not_string_equality(tmp_path):
    """The positive control for the fix, and it has to be a hard link.

    The first draft of this used a symlinked *directory* and **passed against the broken
    code on macOS**, which is worth recording because it is the trap this test exists to
    avoid. On POSIX `os.path.realpath` genuinely canonicalises: every symlink hop is
    resolved away, so no symlink-shaped second spelling survives it and both
    implementations agree. The Windows defect is not "there is a second spelling", it is
    that `ntpath.realpath` is **not** a canonicaliser -- it preserves an extended-length
    prefix it was handed. A fixture built on symlinks therefore distinguishes the two
    implementations on exactly the platform this suite cannot run, which is a control
    that controls nothing.

    A hard link is the spelling that survives `realpath` everywhere: two directory
    entries, one inode, and `realpath` of each returns itself. So a string comparison
    calls this `other-target` on macOS, Linux and Windows alike, and only an identity
    comparison calls it `ok` -- which it is, since it is the same file.

    Correct behaviour as well as a control: a hard link to the plugin's own supertool.py
    is that file. Warning that it "points somewhere it should not" would be the exact
    harm CI caught, reached by a different route.
    """
    project = tmp_path / "repo"
    project.mkdir()
    home, record, entry = _cache(tmp_path)

    alias = tmp_path / "alias-supertool.py"
    refused = _hardlink(alias, entry)
    if refused:
        pytest.skip(refused + "; what went untested is whether the comparison is identity")
    refused = _link(project / "supertool", alias)
    if refused:
        pytest.skip(refused + "; what went untested is whether the comparison is identity")

    assert os.path.realpath(str(alias)) != os.path.realpath(str(entry)), (
        "the fixture did not produce two spellings -- realpath collapsed them, so this "
        "test cannot tell an identity comparison from a string one"
    )

    state, detail = doctor.supertool_entry_point(
        project, cache_root=str(home), record=str(record)
    )
    assert state == "ok", (
        "a link reaching the plugin's own supertool.py by a second directory entry was "
        "called {!r}; the comparison is still matching strings rather than asking which "
        "file each name denotes ({})".format(state, detail)
    )


def test_a_target_that_cannot_be_compared_is_not_reported_as_the_wrong_target(tmp_path):
    """`os.path.samefile` stats both sides, and a stat can fail. Falling through to
    `other-target` there would accuse a link nobody could check -- the same collapse in
    the same arm, one layer under the one CI caught."""
    project = tmp_path / "repo"
    project.mkdir()
    home, record, entry = _cache(tmp_path)
    refused = _link(project / "supertool", entry)
    if refused:
        pytest.skip(refused + "; what went untested is the undecidable-comparison arm")

    def _refuse(left, right):
        raise OSError(5, "Access is denied")

    saved = doctor.os.path.samefile
    doctor.os.path.samefile = _refuse
    try:
        state, detail = doctor.supertool_entry_point(
            project, cache_root=str(home), record=str(record)
        )
        assert state == "unknown-comparison", (state, detail)
        doctor.check_supertool_entry_point(
            project, cache_root=str(home), record=str(record)
        )
    finally:
        doctor.os.path.samefile = saved
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "unknown" in message or "could not" in message, message
    assert len(doctor.FINDINGS) == 1


def test_a_link_to_something_else_is_distinct_from_absent(tmp_path):
    """The second failure mode, and the one observed on this very repo -- supertool's
    session-start hook reported `./supertool already exists here and is not the plugin
    symlink -- leaving it untouched`. Its remedy is not the absent case's remedy, so it
    must not render as the absent case."""
    project = tmp_path / "repo"
    project.mkdir()
    stranger = tmp_path / "elsewhere.py"
    stranger.write_text("# not the plugin\n", encoding="utf-8")
    home, record, _ = _cache(tmp_path)
    refused = _link(project / "supertool", stranger)
    if refused:
        pytest.skip(refused + "; what went untested is the other-target arm")
    state, detail = doctor.supertool_entry_point(
        project, cache_root=str(home), record=str(record)
    )
    assert state == "other-target", (state, detail)
    assert "elsewhere.py" in detail, detail

    doctor.check_supertool_entry_point(project, cache_root=str(home), record=str(record))
    level, message = doctor.FINDINGS[-1]
    # #756: named, not judged -- the two states this cannot tell apart (a
    # deliberate local checkout, a stale link) are indistinguishable in
    # principle, so this stopped being a WARN. The target is still the point.
    assert level == "OK"
    assert "elsewhere.py" in message, message


def test_an_undeterminable_plugin_path_is_not_reported_as_a_wrong_target(tmp_path):
    """The third state, and the reason this is a function rather than an `==`.

    With no readable cache there is no answer to compare against. Reporting
    `other-target` there would accuse a link that may be perfectly correct; reporting
    `ok` would clear one that may not be. Neither is measured, so neither is said.
    """
    project = tmp_path / "repo"
    project.mkdir()
    stranger = tmp_path / "somewhere.py"
    stranger.write_text("x\n", encoding="utf-8")
    refused = _link(project / "supertool", stranger)
    if refused:
        pytest.skip(refused + "; what went untested is the unknown-plugin-path arm")
    state, detail = doctor.supertool_entry_point(
        project, cache_root=str(tmp_path / "no-cache"), record=str(tmp_path / "no-record")
    )
    assert state == "unknown-plugin-path", (state, detail)

    doctor.check_supertool_entry_point(
        project,
        cache_root=str(tmp_path / "no-cache"),
        record=str(tmp_path / "no-record"),
    )
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "unknown" in message or "could not" in message, message
    assert "somewhere.py" in message, message


def _executable(path, body):
    """A regular file made executable, or the sentence saying why not.

    #742's three states are established by RUNNING the file, so the fixture has to
    actually run -- a mode fixture is a measurement, not a given (this repo's own
    CLAUDE.md). Windows has no execute bit and `os.chmod` there does not make an
    arbitrary script runnable by name, so this attempts the exact operation
    (`<path> version`) rather than asserting a POSIX fact as a product verdict.
    """
    path.write_text(body, encoding="utf-8")
    try:
        os.chmod(str(path), 0o755)
    except OSError:
        pass
    # #716: a raw `subprocess.run` with a timeout and nothing catching
    # `TimeoutExpired` reports whatever this fixture's caller would have asserted
    # about the answer instead of reporting that a slow runner produced none.
    # `spawn_guard.run` skips the whole test on that timeout rather than letting it
    # render as a failure about the wrong thing.
    try:
        completed = spawn_guard.run(
            [str(path), "version"],
            subject="whether this fixture's executable answers `version` at all",
            timeout=10,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        return str(exc)
    if completed.returncode != 0 or b"supertool" not in completed.stdout:
        return "the executable fixture did not answer `version` as expected here ({!r})".format(
            completed.stdout
        )
    return None


def test_a_regular_file_that_cannot_be_run_is_unknown_not_a_pass_or_a_warning(tmp_path):
    """Not a symlink at all, and not runnable either -- `readlink` has nothing to
    say, calling it absent would be wrong in the direction that gets acted on, and
    calling it a confirmed pass or fail would claim a measurement that was never
    taken (#742's third acceptance criterion)."""
    project = tmp_path / "repo"
    project.mkdir()
    (project / "supertool").write_text("not a script\n", encoding="utf-8")
    (state, detail), _ = _state(project, tmp_path)
    assert state == "not-a-symlink-unknown", (state, detail)

    doctor.FINDINGS.clear()
    home, record, _ = _cache(tmp_path)
    doctor.check_supertool_entry_point(project, cache_root=str(home), record=str(record))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", message
    assert "unknown" in message, message


def test_a_regular_file_reporting_the_installed_version_does_not_warn(tmp_path):
    """#742's first acceptance criterion: a regular file at that name, answering at
    the installed version, must not WARN -- it reaches the tool the briefs mean just
    as well as a correct symlink does."""
    project = tmp_path / "repo"
    project.mkdir()
    refused = _executable(
        project / "supertool", "#!/bin/sh\necho \"supertool {}\"\n".format(VERSION)
    )
    if refused:
        pytest.skip(refused + "; what went untested is the not-a-symlink-ok arm")
    state, detail = _state(project, tmp_path)[0]
    assert state == "not-a-symlink-ok", (state, detail)
    assert VERSION in detail, detail

    doctor.FINDINGS.clear()
    home, record, _ = _cache(tmp_path)
    doctor.check_supertool_entry_point(project, cache_root=str(home), record=str(record))
    level, message = doctor.FINDINGS[-1]
    assert level == "OK", message


def test_a_regular_file_reporting_a_different_version_warns_and_names_both(tmp_path):
    """#742's second acceptance criterion: a mismatch WARNs and the line names both
    versions -- the fact the old sentence's "whatever this is" was only guessing at."""
    project = tmp_path / "repo"
    project.mkdir()
    refused = _executable(project / "supertool", "#!/bin/sh\necho \"supertool 1.0.0\"\n")
    if refused:
        pytest.skip(refused + "; what went untested is the not-a-symlink-mismatch arm")
    state, detail = _state(project, tmp_path)[0]
    assert state == "not-a-symlink-mismatch", (state, detail)
    assert "1.0.0" in detail and VERSION in detail, detail

    doctor.FINDINGS.clear()
    home, record, _ = _cache(tmp_path)
    doctor.check_supertool_entry_point(project, cache_root=str(home), record=str(record))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", message
    assert "1.0.0" in message and VERSION in message, message


def test_a_dangling_link_is_not_the_same_as_no_link(tmp_path):
    """A symlink pointing at a checkout that has been moved or deleted. Present, wrong,
    and its remedy is re-linking rather than creating."""
    project = tmp_path / "repo"
    project.mkdir()
    refused = _link(project / "supertool", tmp_path / "gone" / "supertool.py")
    if refused:
        pytest.skip(refused + "; what went untested is the dangling arm")
    (state, detail), _ = _state(project, tmp_path)
    assert state == "dangling", (state, detail)


def test_a_supertool_checkout_is_not_told_to_create_a_wrapper(tmp_path):
    """Transcribed from supertool's own session-start hook rather than invented here:
    inside a tree carrying its own `.supertool.json` and `supertool.py`, the hook
    deliberately creates NO wrapper, because one pointing at the plugin install would
    run the plugin core against this tree's presets -- the mix every custom op declines.

    claude-supertool is itself managed by this loop, so without this arm doctor would
    fire a confident wrong warning in the one repository the tool comes from.
    """
    project = tmp_path / "claude-supertool"
    project.mkdir()
    (project / ".supertool.json").write_text("{}\n", encoding="utf-8")
    (project / "supertool.py").write_text("# core\n", encoding="utf-8")
    (state, detail), _ = _state(project, tmp_path)
    assert state == "own-tree", (state, detail)
    # The second instance of the comparison defect CI caught, bound here rather than
    # left incidental: the walk starts at realpath(project_dir), so the core is spelled
    # in resolved form while the caller holds the raw path. Displaying it against the
    # raw project_dir made relative_to raise and fall back to an absolute path --
    # /tmp against /private/tmp here, an extended-length prefix on Windows. Asserting
    # the result is relative is the assertion that fails if that regresses, and it
    # names no platform.
    assert detail == "supertool.py", (
        "the own-tree core was displayed as {!r} rather than relative to the tree root "
        "it was found under".format(detail)
    )
    assert not os.path.isabs(detail), detail

    home, record, _ = _cache(tmp_path)
    doctor.check_supertool_entry_point(project, cache_root=str(home), record=str(record))
    level, message = doctor.FINDINGS[-1]
    assert level == "OK", message
    assert "supertool.py" in message, message


def test_a_wrapper_inside_a_supertool_checkout_is_its_own_state(tmp_path):
    """The stranger case of the arm above, and not a hypothetical: running this check
    against the maintainer's claude-supertool clone printed it. The hook leaves anything
    already at that name untouched, so a wrapper made before the tree became its own
    supertool checkout stays there -- and through it every custom op answers "comes from
    a different supertool tree" and exits 1. Present, looks right, works for nothing.

    Flagged by the review of this diff as an untested state. It is testable, so it is
    tested rather than argued down.
    """
    project = tmp_path / "claude-supertool"
    project.mkdir()
    (project / ".supertool.json").write_text("{}\n", encoding="utf-8")
    (project / "supertool.py").write_text("# core\n", encoding="utf-8")
    home, record, entry = _cache(tmp_path)
    refused = _link(project / "supertool", entry)
    if refused:
        pytest.skip(refused + "; what went untested is the own-tree-stranger arm")

    state, detail = doctor.supertool_entry_point(
        project, cache_root=str(home), record=str(record)
    )
    assert state == "own-tree-stranger", (state, detail)

    doctor.check_supertool_entry_point(project, cache_root=str(home), record=str(record))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN", message
    assert "supertool.py" in message, message
    # Distinct from the plain own-tree arm, which is an OK. Without this the two could
    # share a message and the test above would still pass.
    assert len(doctor.FINDINGS) == 1


def test_the_check_prints_exactly_one_line_in_every_state(tmp_path):
    """doctor's contract is one line per check. A state that printed none would be the
    silence this whole file is about, and a state that printed two would scroll."""
    home, record, entry = _cache(tmp_path)
    seen = set()
    for name in ("absent", "not-a-symlink-unknown", "own-tree"):
        project = tmp_path / ("case-" + name)
        project.mkdir()
        if name == "not-a-symlink-unknown":
            (project / "supertool").write_text("x\n", encoding="utf-8")
        if name == "own-tree":
            (project / ".supertool.json").write_text("{}\n", encoding="utf-8")
            (project / "supertool.py").write_text("x\n", encoding="utf-8")
        doctor.FINDINGS.clear()
        doctor.check_supertool_entry_point(project, cache_root=str(home), record=str(record))
        assert len(doctor.FINDINGS) == 1, (name, doctor.FINDINGS)
        seen.add(name)
    assert seen == {"absent", "not-a-symlink-unknown", "own-tree"}
