"""A machine-wide opt-out must not be shadowed by an ordinary managed repo's own config (#534).

Found by the v0.13.0 release audit, round 1: `opt_out` walks upward for #492, but stops at the
**first** ancestor directory holding either config file and returns "on" if that directory does
not itself declare the key -- it never keeps walking past it. In practice the nearest config is
always the managed repo's own `.oss.json`, which declares `repo` and nothing about `auto_update`,
so a machine-wide opt-out one or more directories above it is never reached.

The docstring at `plugin_update.py:18-21` names ".oss.json" or ".oss.local.json" as the opt-out
location without scoping it to the project root, and the upward walk exists specifically to look
above the project (#492's own reasoning, preserved in `opt_out`'s docstring). So a machine-wide
opt-out is a supported spelling, and the fix is: keep walking past a config that declares nothing,
and stop only at a declaration, an unreadable config, or the filesystem root.

The existing #492 coverage (`test_opt_out_walks_upward_from_a_subdirectory_492`) builds
`tmp_path/a/b/c` with **no intervening config** -- the one arrangement in which this bug cannot
show up, because there is nothing to shadow the ancestor. These tests build the shape #534 names:
an ordinary managed-repo config between `root` and the machine-wide opt-out.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import plugin_update  # noqa: E402


def test_ancestor_opt_out_is_not_shadowed_by_an_intervening_managed_repo_config(
    tmp_path,
):
    """A/B from the issue: an ordinary managed-repo `.oss.json` (declaring only `repo`,
    nothing about `auto_update`) sits between the search root and a machine-wide opt-out
    one directory further up. The opt-out must still be found."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".oss.local.json").write_text(
        json.dumps({"auto_update": False}), encoding="utf-8"
    )
    proj = home / "proj"
    proj.mkdir()
    (proj / ".oss.json").write_text(json.dumps({"repo": "a/b"}), encoding="utf-8")

    status, where = plugin_update.opt_out(proj, env={})
    assert status == "off"
    assert ".oss.local.json" in where


def test_must_fire_control_no_opt_out_anywhere_in_the_chain_is_still_on(tmp_path):
    """The must-fire control paired with the test above: with no opt-out anywhere in the
    ancestor chain -- including the intervening managed-repo config -- the walk must still
    complete and answer "on". Without this, a walk that always answers "off" once it starts
    passes the shadowing test vacuously."""
    home = tmp_path / "home"
    home.mkdir()
    proj = home / "proj"
    proj.mkdir()
    (proj / ".oss.json").write_text(json.dumps({"repo": "a/b"}), encoding="utf-8")

    status, where = plugin_update.opt_out(proj, env={})
    assert status == "on"
    assert where is None


def test_an_unreadable_sibling_config_is_not_masked_by_an_explicit_off(tmp_path):
    """Self-review finding on #534 (raised by the Explore review spawn): the
    inner loop used to return "off" the moment it hit `auto_update: false`,
    *before* the post-loop `if unreadable: return "unknown"` check ever ran --
    so a genuinely broken sibling config in the SAME directory was silently
    dropped whenever the other file in that directory happened to declare
    `false`. The symmetric case (an explicit `true` alongside a broken
    sibling) already returned "unknown" correctly, because that path does not
    return early inside the loop -- this is the must-fire half closing the gap
    between the two."""
    (tmp_path / ".oss.json").write_text("{not valid json", encoding="utf-8")
    (tmp_path / ".oss.local.json").write_text(
        json.dumps({"auto_update": False}), encoding="utf-8"
    )

    status, where = plugin_update.opt_out(tmp_path, env={})
    assert status == "unknown"
    assert ".oss.json" in where


def test_a_declaration_still_stops_the_walk_at_the_nearest_config(tmp_path):
    """When the nearest config genuinely declares the key, that remains authoritative --
    the walk must not skip past a real "on"-declaring or "off"-declaring config looking for
    something further up. Only an *undeclared* key continues the walk."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".oss.local.json").write_text(
        json.dumps({"auto_update": False}), encoding="utf-8"
    )
    proj = home / "proj"
    proj.mkdir()
    (proj / ".oss.json").write_text(
        json.dumps({"repo": "a/b", "auto_update": True}), encoding="utf-8"
    )

    status, where = plugin_update.opt_out(proj, env={})
    assert status == "on"
    assert where is None
