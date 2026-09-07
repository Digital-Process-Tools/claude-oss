"""Restore the CPython 3.9 tool cache before `setup-python` on windows-latest (#1196).

`setup-python` reports `Version 3.9 was not found in the local cache` on
`windows-latest` and downloads and installs the interpreter -- measured at 44s of a
229s critical-path leg under xdist (#1177 landed first; before that this was 6% of a
serial leg and correctly out of scope). `Digital-Process-Tools/claude-supertool`'s own
#1127 already ships this pattern in its CI (confirmed via `gh api
repos/Digital-Process-Tools/claude-supertool/contents/.github/workflows/tests.yml`
rather than retyped from the issue body) and its own comment records the trap this
file also pins: the cached path is the VERSION directory
(`${{ runner.tool_cache }}/Python/<patch>`), not `.../x64` beneath it --
`@actions/tool-cache` records an installed tool with a sibling marker `x64.complete`
next to `x64/`, and caching only `x64/` produces a cache HIT that restores nothing
`setup-python` will find.

Windows-only and 3.9-only on purpose: the other three Windows legs and every other
platform's 3.9 leg already have the interpreter baked into the image, or are not the
critical path (#1196's own table: macOS 3.9 pays 22s but macOS tops out at 107s
against Windows' 266-305s).

Python 3.9 compatible.
"""

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"

try:
    import yaml
except ImportError:  # pragma: no cover - exercised by the guard test below
    yaml = None


def test_the_parser_this_file_needs_is_present_on_ci():
    """Mirrors tests/test_windows_defender_exclusion_938.py's own guard.

    A skip and a clean pass are the same tick from outside; CI installs pyyaml (see
    the comment beside it in tests.yml), so its absence there is a broken leg, not a
    contributor's laptop.
    """
    if yaml is not None:
        return
    if os.environ.get("CI") == "true":
        pytest.fail(
            "pyyaml is not importable and CI=true, so the tool-cache assertions in "
            "this file did not run on a runner."
        )
    pytest.skip("pyyaml is not installed here; the workflow installs it on CI")


needs_yaml = pytest.mark.skipif(yaml is None, reason="pyyaml is not installed here")


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


CACHE_STEP_NAME = None  # discovered by prefix match below, since it carries the pin


def _find_step_by_prefix(job, prefix):
    for step in job.get("steps", []):
        name = step.get("name") or ""
        if name.startswith(prefix):
            return step
    return None


def _find_step(job, name):
    for step in job.get("steps", []):
        if step.get("name") == name:
            return step
    return None


@needs_yaml
def test_cache_restore_step_is_present_and_windows_39_only():
    job = _workflow()["jobs"]["pytest"]
    step = _find_step_by_prefix(job, "Restore the CPython")
    assert step is not None, (
        "no step restoring the CPython 3.9 tool cache in the pytest job; steps are "
        "{!r}".format([s.get("name") or s.get("uses") for s in job["steps"]])
    )
    condition = step.get("if", "")
    assert "runner.os == 'Windows'" in condition, (
        "the cache-restore step must be gated to Windows, got if: {!r}".format(
            condition
        )
    )
    assert "'3.9'" in condition, (
        "the cache-restore step must be gated to the 3.9 leg only (macOS 3.9 pays a "
        "similar cost but is never the critical path -- see #1196), got if: {!r}".format(
            condition
        )
    )
    assert step.get("uses", "").startswith("actions/cache@"), (
        "expected actions/cache, got uses: {!r}".format(step.get("uses"))
    )


@needs_yaml
def test_cache_restore_step_caches_the_version_directory_not_x64():
    """The #1127 trap: caching only `.../x64` is a permanent no-op HIT.

    `@actions/tool-cache` writes a sibling marker `x64.complete` next to `x64/` and
    treats its absence as a miss regardless of what is under `x64/` itself, so the
    cached path must be the VERSION directory (one level above `x64`), never `x64`
    itself.
    """
    job = _workflow()["jobs"]["pytest"]
    step = _find_step_by_prefix(job, "Restore the CPython")
    assert step is not None
    with_block = step.get("with", {})
    path = with_block.get("path", "")
    assert "runner.tool_cache" in path, (
        "the cached path must be under runner.tool_cache, got {!r}".format(path)
    )
    assert not path.rstrip("/").endswith("x64"), (
        "caching only the x64/ subdirectory restores a tree setup-python's own "
        "find() still reports as a miss (the marker file sits beside it, not "
        "inside it) -- cache the VERSION directory instead, got path: {!r}".format(path)
    )
    key = with_block.get("key", "")
    assert key, "the cache step needs an explicit key"


@needs_yaml
def test_cache_restore_step_runs_before_set_up_python():
    job = _workflow()["jobs"]["pytest"]
    names = [s.get("name") or s.get("uses") for s in job["steps"]]
    cache_index = next(
        (i for i, n in enumerate(names) if n and n.startswith("Restore the CPython")),
        None,
    )
    setup_index = next(
        (i for i, n in enumerate(names) if n and n.startswith("Set up Python")),
        None,
    )
    assert cache_index is not None
    assert setup_index is not None
    assert cache_index < setup_index, (
        "the cache must be restored before setup-python runs, or the download it "
        "is meant to skip has already happened"
    )


@needs_yaml
def test_a_step_discloses_whether_the_cache_actually_hit():
    """The issue's own hidden judgment call: disclose hit/miss/skip, never infer it.

    A cache written on a PR branch is visible only to that branch -- the `push: main`
    run is what populates the key every other branch restores from -- so the first PR
    after this change lands may still pay the download. That is expected, not a
    failure, and #1196 asks that it be disclosed by a step that says which happened
    rather than left to be inferred from `Set up Python`'s own duration.
    """
    job = _workflow()["jobs"]["pytest"]
    step = _find_step_by_prefix(job, "Tool cache state")
    assert step is not None, (
        "no disclosure step reporting whether the toolcache actually hit; steps are "
        "{!r}".format([s.get("name") or s.get("uses") for s in job["steps"]])
    )
    run = step.get("run", "")
    env = step.get("env", {})
    haystack = run + " " + " ".join(str(v) for v in env.values())
    for expected in ("cache-hit", "toolcache"):
        assert expected in haystack, (
            "the disclosure step must mention {!r} (in its run body or its env "
            "block, e.g. reading steps.toolcache-39.outputs.cache-hit), got run: "
            "{!r} env: {!r}".format(expected, run, env)
        )
