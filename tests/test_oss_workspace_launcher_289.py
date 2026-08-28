"""#289/#288 -- the launcher on PATH, checked against the running plugin.

#289: `~/.local/bin/oss-workspace` is a symlink resolved once, at install time, into a
version-scoped plugin cache directory. Nothing re-points it on a later release, and
nothing checked it -- a stale target that still exists behaves exactly like a current
one. The maintainer's own machine hit this twice: pinned at 0.1.0 for an unknown
span, then re-pointed by hand and stale again one release later, the second time
losing a security fix landed in the very file the symlink names (#324/#323). The
issue's own comment shows why a *path*-only check is not enough: the stale target on
the second occurrence was a git clone pulled mid-release, so its directory read
"0.5.0" while its content matched no tag at all -- a version-segment comparison would
have called that "matched".

#288: a plugin install's `$PWD` is not knowable in advance, so the documented
`ln -sf "$PWD/bin/oss-workspace" ...` line is only correct for someone standing in the
checkout. The plugin's own installed location is knowable at runtime (`PLUGIN_ROOT`,
already used throughout doctor.py) and must never be hardcoded -- that is a fact about
one machine's layout.

So this file tests `doctor.oss_workspace_launcher_state` in five states -- matched,
mismatched, not-resolvable, own-copy-unreadable, unresolved-target -- and that
`check_oss_workspace_launcher` names the *current* install in its remedy line rather
than a path that would be wrong next release.

A sixth state, `path-unreadable`, was added by #333 and is covered in
`tests/test_launcher_path_unreadable_and_platform_remedy_333_330.py` alongside #330's
platform-appropriate remedy. The `not-resolvable` assertions here are the must-not-fire
control for it: they are what would catch a sixth state that fired for an ordinary miss.
"""

import os
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


def _plugin_root(tmp_path, content=b"# the running install\n", version="9.9.9"):
    root = tmp_path / "plugin"
    (root / "bin").mkdir(parents=True)
    entry = root / "bin" / "oss-workspace"
    entry.write_bytes(content)
    os.chmod(str(entry), 0o755)
    manifest_dir = root / ".claude-plugin"
    manifest_dir.mkdir()
    (manifest_dir / "plugin.json").write_text(
        '{"name": "oss", "version": "%s"}' % version, encoding="utf-8"
    )
    return root


def _names_the_path(message, path):
    """Is `path` named in `message`, whichever separator each of them rendered?

    The subject of the assertion this backs is #288's, and only that: **the remedy
    must name THIS install's own resolved location rather than `$PWD`.** The
    separator was never that assertion's subject and was never chosen there -- it
    arrived as a side effect of spelling the expectation `str(Path)`, which on
    POSIX is identical to `Path.as_posix()` and on Windows is not. #340 is the
    bill: the remedy's Windows arm renders forward slashes deliberately, because
    that line has to paste into Git Bash, and the accidental half of this
    assertion failed all four Windows legs while all ten POSIX legs stayed green.

    **Folding separators does not weaken the location check**, which is the thing
    a separator fix could plausibly trade away. That claim is not left as prose:
    `test_the_location_check_survives_a_platform_rendering_its_own_separator` and
    `test_the_location_check_does_not_match_a_wrong_directory_by_suffix` hold it
    as must-not-fire controls, and every caller below pairs its positive assertion
    with a negative one against a sibling directory.

    **The match must begin and end at a component boundary, and the first version
    of this helper did not require that.** This diff's own reviewer produced the
    counterexample: plain containment matches `plugin/bin/oss-workspace` inside
    `.../other-plugin/bin/oss-workspace`, so a wrong directory whose name is a
    SUFFIX of the right one passed -- and the near-miss control at the call site
    did not catch it, because `plugin-elsewhere` is not a suffix of `plugin` and
    so failed correctly for the wrong reason. The sentence above was therefore
    false in general while reading as a guarantee, which is worse than no
    guarantee. Every candidate position is now checked for a boundary on both
    sides; a relative path can no longer accidentally satisfy an absolute one.

    Two alternatives were considered and are recorded rather than left implied.
    Computing the platform's own rendering here (`as_posix()` on Windows, `str()`
    elsewhere) would reproduce the production branch inside the test, so the test
    would agree with the code whichever rendering the code picked -- it could no
    longer catch a wrong choice, only a missing one. Making the remedy carry both
    forms was the other, and it hands a Windows reader two paths where one is
    unpasteable, which is the `misdirects` shape #330 exists to remove. The
    deliberate forward-slash choice is instead pinned where it belongs, in
    `test_the_default_remedy_matches_the_platform_actually_running`, on the
    Windows leg where it is the only place it can be observed.
    """
    needle = str(path).replace("\\", "/")
    haystack = str(message).replace("\\", "/")
    if not needle:
        return False
    start = 0
    while True:
        found = haystack.find(needle, start)
        if found < 0:
            return False
        before = haystack[found - 1] if found else ""
        after = haystack[found + len(needle):found + len(needle) + 1]
        if not _is_path_char(before) and not _is_path_char(after):
            return True
        start = found + 1


def _is_path_char(char):
    """Would `char` extend a path component rather than end it?

    Deliberately a character class rather than a list of the delimiters this
    repo's own messages happen to use (a quote, a space, end of string). A list
    of delimiters answers "did I remember every way a message can end a path",
    which nobody can check; a class answers "could this character be part of the
    name", which is decidable. Empty string -- start or end of the haystack -- is
    a boundary.
    """
    return bool(char) and (char.isalnum() or char in "-_.~+/")


def _link(where, target):
    """Symlink, or the sentence saying why this platform could not make one.

    Windows needs a privilege or Developer Mode for this, so the deny is measured
    by attempting it -- never assumed from `sys.platform` (same helper as
    `tests/test_doctor_supertool_entry_point_285.py`).
    """
    try:
        os.symlink(str(target), str(where))
    except (OSError, NotImplementedError, AttributeError) as exc:
        return "this platform would not create a symlink ({})".format(exc)
    return None


def _path_entry(tmp_path, name, content):
    """One directory on PATH holding a file called ``oss-workspace``.

    Not made executable: `doctor._locate_on_path` does not gate on the execute
    bit, deliberately -- see `test_a_non_executable_target_is_still_resolved`,
    which is the test that would catch a regression back to a permission-
    filtering resolver.
    """
    directory = tmp_path / name
    directory.mkdir()
    target = directory / "oss-workspace"
    target.write_bytes(content)
    return str(directory), target


def test_not_resolvable_is_distinct_from_mismatched(tmp_path):
    """PATH carrying no `oss-workspace` at all -- nothing was found to compare, so
    this must not render as a mismatch, which would name a target that does not
    exist."""
    plugin_root = _plugin_root(tmp_path)
    empty = tmp_path / "empty-path"
    empty.mkdir()
    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=str(empty)
    )
    assert state == "not-resolvable", (state, detail)

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=str(empty))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "not on PATH" in message, message


def test_matched_by_identity_is_the_positive_control(tmp_path):
    """Positive control for the mismatch tests below: PATH resolving to a symlink
    onto the running install's own bin/oss-workspace, the way `~/.local/bin`
    resolves in a real install. Without this, every "does not warn" assertion
    could pass on a check that never matches anything.

    #617: this used to point PATH straight at `plugin_root / "bin"` -- the
    plugin's own bin directory -- which is exactly the false positive the issue
    is about (see `test_the_plugins_own_bin_directory_is_not_a_reachable_install
    _617` below), so the positive control is now built the way a real install
    is: a link elsewhere on PATH resolving TO that directory's file, never the
    directory itself.
    """
    plugin_root = _plugin_root(tmp_path)
    local_bin = tmp_path / "local-bin"
    local_bin.mkdir()
    refused = _link(local_bin / "oss-workspace", plugin_root / "bin" / "oss-workspace")
    if refused:
        pytest.skip(refused + "; what went untested is the matched-by-identity arm")

    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=str(local_bin)
    )
    assert state == "matched", (state, detail)

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=str(local_bin))
    assert doctor.FINDINGS[-1][0] == "OK", doctor.FINDINGS[-1]


def test_the_plugins_own_bin_directory_is_not_a_reachable_install_617(tmp_path):
    """The must-fire half of #617: a session's own PATH always carries
    `<plugin_root>/bin`, which holds `oss-workspace` unconditionally -- it is
    this running install's own copy, sitting right there. Searching it made
    `matched` close to unconditional FROM INSIDE A SESSION and `not-resolvable`
    close to unreachable, while a plain login shell -- the one the README's
    install line is actually for -- was measured on the reporter's own machine
    to carry none of it (`grep -c dpt-plugins` on a clean `zsh -i -l` PATH: 0).
    So this check must answer about what the USER's shell can reach, not about
    the PATH of the process asking -- the same shape this repo's own
    `interpreter architecture` check exists to avoid one layer up. With PATH
    holding nothing but the plugin's own bin directory, the honest answer is
    `not-resolvable`, the same as an empty PATH."""
    plugin_root = _plugin_root(tmp_path)
    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=str(plugin_root / "bin")
    )
    assert state == "not-resolvable", (state, detail)

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=str(plugin_root / "bin"))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "not on PATH" in message, message


def test_the_plugins_own_bin_directory_does_not_shadow_a_real_entry_further_on_617(
    tmp_path,
):
    """Must-not-fire control in the same fixture as the exclusion above: PATH
    carrying the plugin's own bin directory FIRST must not stop the search --
    a real, reachable launcher further down PATH is still found and still
    matches. Exclusion is a filter over which candidates count, not an early
    return the moment the plugin's own bin is seen."""
    plugin_root = _plugin_root(tmp_path)
    local_bin = tmp_path / "local-bin"
    local_bin.mkdir()
    refused = _link(local_bin / "oss-workspace", plugin_root / "bin" / "oss-workspace")
    if refused:
        pytest.skip(refused + "; what went untested is the does-not-shadow arm")

    search_path = os.pathsep.join([str(plugin_root / "bin"), str(local_bin)])
    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=search_path
    )
    assert state == "matched", (state, detail)


def test_matched_by_content_a_separate_copy_with_identical_bytes(tmp_path):
    """Two different files, same bytes -- content is the ground truth, not identity
    and not the path shape."""
    plugin_root = _plugin_root(tmp_path, content=b"same bytes\n")
    path_dir, _ = _path_entry(tmp_path, "on-path", b"same bytes\n")
    state, detail = doctor.oss_workspace_launcher_state(plugin_root=plugin_root, path=path_dir)
    assert state == "matched", (state, detail)


def test_mismatched_content_names_both_versions_when_the_shape_is_recognised(tmp_path):
    """The common case: PATH resolves into a `.../oss/<version>/bin/oss-workspace`
    cache layout whose content differs from the running install."""
    plugin_root = _plugin_root(tmp_path, content=b"new content\n", version="9.9.9")
    cache_dir = tmp_path / "cache" / "dpt-plugins" / "oss" / "0.1.0" / "bin"
    cache_dir.mkdir(parents=True)
    target = cache_dir / "oss-workspace"
    target.write_bytes(b"old content\n")
    os.chmod(str(target), 0o755)

    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=str(cache_dir)
    )
    assert state == "mismatched", (state, detail)
    resolved, theirs_version, ours_version = detail
    assert theirs_version == "0.1.0", detail
    # #350: this is the version of the plugin root that was HANDED IN, not of the
    # tree the test happens to be running inside. It came from `plugin_version()`
    # -- a global -- so the fixture's own `version=` was ignored and the assertion
    # was really `<this repo's current version> == <a literal>`, which passed until
    # the release bumped the manifest and then reddened the release itself.
    # `9.9.9` is a version this repository will not reach, so the assertion can no
    # longer be satisfied by coincidence.
    assert ours_version == "9.9.9", detail

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=str(cache_dir))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "0.1.0" in message and "9.9.9" in message, message
    # #288: the remedy must name the running install's own location, not $PWD.
    # Compared separator-insensitively (#340) -- see `_names_the_path` for why the
    # separator was never this assertion's subject, and why folding it does not
    # weaken the location check.
    assert _names_the_path(message, plugin_root / "bin" / "oss-workspace"), message
    # Must-not-fire, in the same fixture: the location check still discriminates.
    # A NEAR MISS on purpose -- same tmp_path parent, same trailing
    # `bin/oss-workspace`, one directory component different, which is the shape a
    # remedy built from `$PWD` would have. This fails if the assertion above has
    # been reduced to "some path-shaped thing appears".
    assert not _names_the_path(
        message, tmp_path / "plugin-elsewhere" / "bin" / "oss-workspace"
    ), message


def test_the_location_check_survives_a_platform_rendering_its_own_separator():
    """The CI failure of #340, reproduced as a unit so it is observable off Windows.

    The remedy's Windows arm renders the install path with forward slashes on
    purpose -- that line has to paste into Git Bash (#330). The assertion in
    `test_mismatched_content_names_both_versions_when_the_shape_is_recognised`
    was written as `str(Path) in message`, and `str()` on a `WindowsPath` renders
    backslashes, so the two disagreed about a separator neither of them chose as
    its subject. It went red on all four Windows legs and green on all ten POSIX
    ones, because that is the platform where `str()` and `as_posix()` are the same
    string -- the assertion was only ever satisfiable where the bug is invisible.

    The strings below are the two renderings from that CI log, in shape. The
    second half is the must-not-fire control and is the reason folding separators
    is not a weakening: a remedy naming a DIFFERENT directory still fails, which
    is the whole of what #288 asks this assertion to protect.
    """
    message = (
        "oss-workspace launcher: SKEW -- ... Run it from this install's own "
        'checkout, inside Git Bash: sh "C:/Users/runneradmin/t/plugin/bin/oss-workspace"'
    )
    assert _names_the_path(
        message, "C:\\Users\\runneradmin\\t\\plugin\\bin\\oss-workspace"
    )
    assert not _names_the_path(
        message, "C:\\Users\\runneradmin\\t\\somewhere-else\\bin\\oss-workspace"
    )
    # And the POSIX rendering of the same location still matches, so this is not
    # a check that only works for the platform that broke it.
    assert _names_the_path(message, "C:/Users/runneradmin/t/plugin/bin/oss-workspace")


def test_the_location_check_does_not_match_a_wrong_directory_by_suffix():
    """Raised by this diff's own reviewer against the first version of
    `_names_the_path`, and it was right.

    A plain substring test does not require the differing component to be a whole
    path component, so a wrong directory whose name is a SUFFIX of the correct
    one matches: `plugin/bin/oss-workspace` is literally inside
    `.../other-plugin/bin/oss-workspace`. The near-miss control at the call site
    did not probe this -- `plugin-elsewhere` is not a suffix of `plugin`, so it
    failed correctly for the wrong reason and masked the gap.

    That mattered because of what the helper's docstring CLAIMS -- that two
    different directories cannot both satisfy it -- which is the sentence the
    whole separator fix rests on. A guarantee stated in prose and false in
    general is worse than no guarantee, so the match is now required to begin at
    a component boundary and the claim is pinned here rather than asserted there.
    """
    message = 'Run it from this install: sh "/home/dev/checkouts/other-plugin/bin/oss-workspace"'
    assert _names_the_path(message, "/home/dev/checkouts/other-plugin/bin/oss-workspace")
    # The must-not-fire that the first version got wrong.
    assert not _names_the_path(message, "plugin/bin/oss-workspace")
    # Same shape from the other end: a longer wrong path is not matched either.
    assert not _names_the_path(
        message, "/home/dev/checkouts/other-plugin/bin/oss-workspace-2"
    )


def test_mismatched_content_with_an_unrecognised_target_shape_does_not_invent_a_version(
    tmp_path,
):
    """The layout `.../oss/<version>/bin/oss-workspace` is one plugin manager's cache
    convention, not a contract. A target that does not have that shape must still be
    reported by content (mismatched, here), and must say a version could not be read
    from it rather than silently rendering as a clean match -- the failure mode #289's
    own body warns against."""
    plugin_root = _plugin_root(tmp_path, content=b"new content\n")
    flat = tmp_path / "somewhere-else"
    flat.mkdir()
    target = flat / "oss-workspace"
    target.write_bytes(b"old content\n")
    os.chmod(str(target), 0o755)

    state, detail = doctor.oss_workspace_launcher_state(plugin_root=plugin_root, path=str(flat))
    assert state == "mismatched", (state, detail)
    resolved, theirs_version, ours_version = detail
    assert theirs_version is None, detail

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=str(flat))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "no recognised" in message or "no known" in message, message


def test_own_copy_unreadable_is_unknown_not_matched_and_not_mismatched(tmp_path):
    """The running install's own bin/oss-workspace could not be read -- so nothing
    was compared, and that must not render as either OK or a skew accusation."""
    plugin_root = _plugin_root(tmp_path)
    # A directory where a file is expected: portable across platforms, no chmod
    # privilege required, and read_bytes() on it always raises OSError.
    (plugin_root / "bin" / "oss-workspace").unlink()
    (plugin_root / "bin" / "oss-workspace").mkdir()
    path_dir, _ = _path_entry(tmp_path, "on-path", b"whatever\n")

    state, detail = doctor.oss_workspace_launcher_state(plugin_root=plugin_root, path=path_dir)
    assert state == "own-copy-unreadable", (state, detail)

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=path_dir)
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "unknown" in message.lower(), message


def test_unresolved_target_is_unknown_not_matched_and_not_mismatched(tmp_path):
    """The resolved target could not be read. Exercised through a REAL PATH
    entry rather than the ``resolve`` testing seam: `doctor._locate_on_path`
    uses `os.lstat`, which succeeds on a directory too (unlike
    `shutil.which`, which refuses a directory candidate outright), so a
    directory named `oss-workspace` sitting on PATH is a real, reachable way
    to land here -- `_locate_on_path` finds it, and `Path(resolved).read_bytes()`
    then fails on it with `IsADirectoryError`."""
    plugin_root = _plugin_root(tmp_path)
    directory = tmp_path / "on-path-a-directory"
    directory.mkdir()
    (directory / "oss-workspace").mkdir()

    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=str(directory)
    )
    assert state == "unresolved-target", (state, detail)

    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=str(directory))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "unknown" in message.lower(), message


def test_a_dangling_symlink_earlier_on_path_does_not_shadow_a_working_one(tmp_path):
    """A stale, dead `oss-workspace` symlink left on an earlier PATH entry (an old
    `~/.local/bin` from a prior install layout, say) must not shadow a correct,
    reachable one further down PATH. `_locate_on_path` has to keep looking past a
    candidate that resolves to nothing, the same way `shutil.which` always did --
    `shutil.which`'s own `_access_check` runs `os.path.exists`, which follows a
    symlink and is False for a dangling one, so it silently continued to the next
    PATH directory. A naive existence-only walk does not: `os.lstat` succeeds on
    a dangling symlink too, so the first (broken) match would stop the search
    there and report `unresolved-target` for a launcher that is, one PATH entry
    later, actually present and matching. Since #333 the reachability question
    is asked as `os.stat` inside a `try`, so a target that could not be looked at
    at all is separated from one that is genuinely dangling."""
    plugin_root = _plugin_root(tmp_path, content=b"same bytes\n")
    earlier = tmp_path / "earlier-on-path"
    earlier.mkdir()
    try:
        os.symlink(str(tmp_path / "does-not-exist"), str(earlier / "oss-workspace"))
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip(
            "this platform would not create a symlink ({}); what went untested is "
            "whether a dangling symlink earlier on PATH is skipped rather than "
            "shadowing a working entry further down PATH".format(exc)
        )
    later_dir, _ = _path_entry(tmp_path, "later-on-path", b"same bytes\n")

    search_path = os.pathsep.join([str(earlier), later_dir])
    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=search_path
    )
    assert state == "matched", (state, detail)


def test_a_non_executable_target_is_still_resolved(tmp_path):
    """PATH resolution must not filter on properties irrelevant to a content
    comparison. `shutil.which`'s default `mode` requires `os.X_OK`, so a target
    that exists with the right bytes but lacks the execute bit was previously
    invisible to it -- this is the POSIX-observable proxy for the same class of
    bug the Windows PATHEXT case is (#329): `shutil.which` filters candidates by
    a property ("is this launchable") that has nothing to do with "does this
    file exist and what does it contain", which is the only question this check
    actually has. Without this fix, PATH resolution here silently degrades to
    `not-resolvable` for a launcher that is genuinely present."""
    plugin_root = _plugin_root(tmp_path, content=b"same bytes\n")
    directory = tmp_path / "on-path-no-exec"
    directory.mkdir()
    target = directory / "oss-workspace"
    target.write_bytes(b"same bytes\n")
    os.chmod(str(target), 0o644)  # deliberately NOT executable

    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=str(directory)
    )
    assert state == "matched", (state, detail)


def test_version_segment_parses_the_documented_cache_shape():
    # The version here is arbitrary -- this parses a path shape, not a release --
    # so it is deliberately one this repository will not reach. It read `0.6.0`
    # until #350, which was a coincidence rather than a choice, and a coincidence
    # is what the guard in `tests/test_no_test_pins_the_current_version_350.py`
    # cannot tell apart from the assertion that reddened the release.
    resolved = str(
        Path("home", "x", ".claude", "plugins", "cache", "dpt-plugins", "oss", "9.9.9", "bin", "oss-workspace")
    )
    assert doctor._oss_workspace_version_segment(resolved) == "9.9.9"


def test_version_segment_is_none_for_an_unrecognised_shape():
    assert doctor._oss_workspace_version_segment(str(Path("home", "x", "oss-workspace"))) is None
    assert doctor._oss_workspace_version_segment(str(Path("home", "x", "bin", "oss-workspace"))) is None


# --- #350: the version label must describe the plugin_root that was handed in ---


def test_our_version_that_could_not_be_read_is_none_and_never_renders_as_one(tmp_path):
    """The third state, and its positive control, in one fixture.

    `their_version` has had a "not available" answer since #289 -- `None`, with a
    clause of its own rather than a version-shaped string. `our_version` had no
    such answer: it came from `plugin_version()`, which folds an absent or
    unparseable manifest into the strings `"unknown"` and `"unreadable"` and hands
    them back where a version goes. That is fine for the one line at the top of
    `doctor`'s output, which says "oss plugin version unreadable" and is honest.
    It is not fine here, where the same value is formatted as `(version {})`
    beside a byte comparison: "version unreadable" reads as a version.

    Must-fire half first, so a harness that produced no message at all cannot
    pass the silent half below.
    """
    plugin_root = _plugin_root(tmp_path, content=b"new content\n", version="9.9.9")
    other = tmp_path / "somewhere-else"
    other.mkdir()
    target = other / "oss-workspace"
    target.write_bytes(b"old content\n")
    os.chmod(str(target), 0o755)

    # Must fire: a readable manifest is named, as a version, in the receipt.
    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=str(other)
    )
    assert state == "mismatched", (state, detail)
    assert detail[2] == "9.9.9", detail
    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=str(other))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "version 9.9.9" in message, message

    # Must not fire: the same install with no readable manifest. A directory where
    # the file goes is portable and needs no chmod privilege -- `read_text()` on it
    # raises OSError on every platform.
    manifest = plugin_root / ".claude-plugin" / "plugin.json"
    manifest.unlink()
    manifest.mkdir()

    state, detail = doctor.oss_workspace_launcher_state(
        plugin_root=plugin_root, path=str(other)
    )
    assert state == "mismatched", (state, detail)
    assert detail[2] is None, detail
    doctor.check_oss_workspace_launcher(plugin_root=plugin_root, path=str(other))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "9.9.9" not in message, message
    assert "None" not in message, message
    assert "no version could be read from its own manifest" in message, message
    # It must not assert WHICH of the two failure states this was -- the state is
    # not in `detail`, and a receipt that guesses is #350 one layer down.
    assert "absent, unparseable, or carries no version field" in message, message


def test_manifest_version_answers_in_three_states(tmp_path):
    """`read`, `no-version-field`, `unreadable` -- and the last two return no
    version rather than a string that looks like one."""
    root = tmp_path / "root"
    (root / ".claude-plugin").mkdir(parents=True)
    manifest = root / ".claude-plugin" / "plugin.json"

    manifest.write_text('{"name": "oss", "version": "9.9.9"}', encoding="utf-8")
    assert doctor._manifest_version(root) == ("read", "9.9.9")

    manifest.write_text('{"name": "oss"}', encoding="utf-8")
    assert doctor._manifest_version(root) == ("no-version-field", None)

    manifest.write_text('{"name": "oss", "version": 7}', encoding="utf-8")
    assert doctor._manifest_version(root) == ("no-version-field", None)

    manifest.write_text("not json at all", encoding="utf-8")
    assert doctor._manifest_version(root) == ("unreadable", None)

    # Valid JSON that is not an object. Before #350 this reached `.get` on a list
    # and raised AttributeError out of `plugin_version()` -- the one function whose
    # docstring says its line must print even when everything else has failed.
    manifest.write_text("[]", encoding="utf-8")
    assert doctor._manifest_version(root) == ("unreadable", None)

    manifest.unlink()
    assert doctor._manifest_version(root) == ("unreadable", None)


def test_plugin_version_still_describes_the_running_install():
    """The survey behind #350's product fix, pinned rather than left in prose.

    `plugin_version()` has two callers in `scripts/`: this check's label, which was
    wrong to use it, and `main()`'s `oss plugin version {}` header, which is right
    -- that line is about the install the reader is running. So the global was not
    given a `plugin_root` argument; a second, parameterised helper was added beside
    it and `plugin_version()` now delegates to it for the running root. This asserts
    the delegation rather than assuming it, so the two cannot drift apart.
    """
    state, version = doctor._manifest_version(doctor.PLUGIN_ROOT)
    assert state == "read", (state, version)
    assert doctor.plugin_version() == version
