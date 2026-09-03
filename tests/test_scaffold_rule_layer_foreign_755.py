"""#755: a foreign file in the 01-oss layer is a different claim than a retired one.

`plan_rules()` deletes the whole `01-oss` layer before rewriting it (`install()`'s own
contract), so a `remove` row fires on ANY file present in the layer today that this
version does not ship -- including a file this plugin has never written and never will,
because something else in the managed repo generates it into the same directory.

Observed in `Digital-Process-Tools/claude-jit-context`: that repo's own
`scripts/rebuild-tsv.sh` writes `01-paths.tsv` into `vocabulary/01-oss/`, a directory the
scaffold owns. `--apply` deletes it, the repo's own tooling writes it straight back, and
the changelog fragment from the run that "removed" it claims a deletion that never held.

The fix is report-only (the issue's own first suggested direction, weighed as safer than
scoping the delete): keep deleting everything in the layer -- narrowing what gets deleted
is the second, riskier direction the issue offers and is not taken here -- but say, per
row, which of two different claims is being made:

* **retired** -- the name is one this plugin's `install()` could have written (a `.md`
  rule file, or the layer's own index filename) and a previous version did; deleting it
  is exactly the ownership guarantee the layer exists for.
* **foreign** -- the name is not a shape `install()` has ever produced or ever will (see
  `oss_rules.install()`: it writes one `.md` file per rule and one file named
  `oss_rules.INDEX` per dimension, nothing else). Deleting it holds only until whatever
  wrote it runs again, so the reason has to say so rather than reading like a retirement.

`could-not-list-directory` is the third state the issue asks to stay separable from
these two, and it already exists (`plan_rules()["unreadable"]`) -- this is only the split
of the `remove` rows into the other two.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_rules  # noqa: E402
import scaffold  # noqa: E402


def _config(**overrides):
    config = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "worktree_root": "/src/name-wt",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": [".claude-plugin/plugin.json", "README.md"],
        "changelog_dir": "changelog.d",
        "changelog_untagged": ["0.1.0"],
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "state_file": ".max/oss-watch.json",
    }
    config.update(overrides)
    return config


def _row(entries, path):
    for entry in entries:
        if entry["path"].endswith(path):
            return entry
    raise AssertionError("no row for {!r} in {!r}".format(path, entries))


def test_a_retired_rule_file_is_reported_as_retired_not_foreign(tmp_path):
    layer = tmp_path / ".claude" / "jit-context" / "paths" / oss_rules.LAYER
    layer.mkdir(parents=True)
    (layer / "retired-rule.md").write_text("---\ntitle: old\n---\n", encoding="utf-8")

    result = scaffold.plan_rules(tmp_path, _config())
    row = _row(result["entries"], "paths/01-oss/retired-rule.md")

    # Must fire: a name this plugin's own layer format could have shipped reads as
    # retired, not as somebody else's file.
    assert row["action"] == "remove"
    assert "never" not in row["reason"], row
    assert "retired" in row["reason"] or "not shipped by this version" in row["reason"]


def test_a_file_no_plugin_version_could_have_written_is_reported_as_foreign(tmp_path):
    layer = tmp_path / ".claude" / "jit-context" / "vocabulary" / oss_rules.LAYER
    layer.mkdir(parents=True)
    # `install()` never writes a `.tsv` file, under any name: one `.md` rule file per
    # rule, one `oss_rules.INDEX` per dimension, nothing else -- see its own docstring.
    (layer / "01-paths.tsv").write_text("", encoding="utf-8")

    result = scaffold.plan_rules(tmp_path, _config())
    row = _row(result["entries"], "vocabulary/01-oss/01-paths.tsv")

    # Must fire: a name outside anything install() has ever produced says so, rather
    # than reading like an ordinary retirement.
    assert row["action"] == "remove"
    assert "never" in row["reason"] and "shipped" in row["reason"], row

    # Positive control, same fixture: the plugin's own index filename in that same
    # directory is still read as retired, not foreign -- the split is on the NAME's
    # shape, not on "everything in this directory that surprised the scan".
    (layer / oss_rules.INDEX).write_text("", encoding="utf-8")
    result = scaffold.plan_rules(tmp_path, _config())
    index_row = _row(result["entries"], "vocabulary/01-oss/{}".format(oss_rules.INDEX))
    assert "never" not in index_row["reason"], index_row
