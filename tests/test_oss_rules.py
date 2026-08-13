"""The `01-oss` rule layer.

Layers are the ownership boundary. `00-manual/` belongs to whoever maintains the repo;
`01-oss/` belongs to this plugin. That is what makes updating safe: we replace our layer
wholesale on every install, because nothing a human wrote lives in it, and we never look
at theirs.

A symlink into the plugin checkout would have been simpler and is refused by design --
git carries symlinks, so a clone could point rules anywhere. Copies into an owned layer
are the supported shape.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_rules  # noqa: E402


def _layer(root, dimension):
    return root / ".claude" / "jit-context" / dimension / oss_rules.LAYER


def test_there_are_rules_to_install():
    assert oss_rules.RULES, "no rules -- every check below would vacuously pass"


def test_install_writes_into_the_owned_layer_only(tmp_path):
    oss_rules.install(tmp_path)
    for dimension in oss_rules.RULES:
        assert _layer(tmp_path, dimension).is_dir()
        assert not (tmp_path / ".claude" / "jit-context" / dimension / "00-manual").exists()


def test_install_writes_an_index_beside_the_rules(tmp_path):
    """The matcher reads the index. Shipping rules without one delivers nothing."""
    oss_rules.install(tmp_path)
    for dimension in oss_rules.RULES:
        index = _layer(tmp_path, dimension) / "00-index.tsv"
        assert index.is_file()
        assert index.read_text(encoding="utf-8").strip(), "{}: empty index".format(dimension)


def test_index_rows_are_pattern_tab_filename(tmp_path):
    oss_rules.install(tmp_path)
    for dimension in oss_rules.RULES:
        index = _layer(tmp_path, dimension) / "00-index.tsv"
        for line in index.read_text(encoding="utf-8").splitlines():
            fields = line.split("\t")
            assert len(fields) == 2, line
            assert fields[0].strip(), line
            assert fields[1].endswith(".md"), line


def test_every_indexed_file_exists(tmp_path):
    """A row naming a file that is not there is the silent half of the same defect."""
    oss_rules.install(tmp_path)
    for dimension in oss_rules.RULES:
        layer = _layer(tmp_path, dimension)
        for line in (layer / "00-index.tsv").read_text(encoding="utf-8").splitlines():
            assert (layer / line.split("\t")[1]).is_file(), line


def test_every_rule_file_is_indexed(tmp_path):
    """And the other half: a file with no row never fires."""
    oss_rules.install(tmp_path)
    for dimension in oss_rules.RULES:
        layer = _layer(tmp_path, dimension)
        indexed = {
            line.split("\t")[1]
            for line in (layer / "00-index.tsv").read_text(encoding="utf-8").splitlines()
        }
        on_disk = {p.name for p in layer.glob("*.md")}
        assert on_disk <= indexed, "not indexed: {}".format(sorted(on_disk - indexed))


def test_reinstall_replaces_our_layer_wholesale(tmp_path):
    """The update story. Our layer is ours, so a stale file we no longer ship must not
    survive -- a rule nobody maintains still fires.
    """
    oss_rules.install(tmp_path)
    layer = _layer(tmp_path, "paths")
    stale = layer / "removed-in-a-later-version.md"
    stale.write_text("---\ntitle: old\nmatch: x\n---\n", encoding="utf-8")

    oss_rules.install(tmp_path)
    assert not stale.exists()


def test_reinstall_never_touches_the_human_layer(tmp_path):
    theirs = tmp_path / ".claude" / "jit-context" / "paths" / "00-manual"
    theirs.mkdir(parents=True)
    mine = theirs / "their-convention.md"
    mine.write_text("---\ntitle: theirs\nmatch: src/\n---\nhand written\n", encoding="utf-8")

    oss_rules.install(tmp_path)
    oss_rules.install(tmp_path)

    assert mine.read_text(encoding="utf-8") == "---\ntitle: theirs\nmatch: src/\n---\nhand written\n"


def test_install_reports_what_it_wrote(tmp_path):
    written = oss_rules.install(tmp_path)
    assert written
    assert all(str(p).endswith((".md", ".tsv")) for p in written)


def test_paths_rules_declare_a_match(tmp_path):
    for name, body in oss_rules.RULES["paths"].items():
        block = body.split("\n---\n")[0]
        assert "match:" in block, name


def test_vocabulary_rules_declare_keywords(tmp_path):
    for name, body in oss_rules.RULES.get("vocabulary", {}).items():
        block = body.split("\n---\n")[0]
        assert "keywords:" in block, name


def test_keywords_are_lowercase_ascii():
    """The index is written by us and read by an awk that case-folds its own way.
    Staying inside plain lowercase ASCII keeps our rows identical to what their
    rebuild would produce, so a regeneration is a no-op rather than a diff.
    """
    for name, body in oss_rules.RULES.get("vocabulary", {}).items():
        block = body.split("\n---\n")[0]
        line = [ln for ln in block.splitlines() if ln.startswith("keywords:")][0]
        for keyword in line.split(":", 1)[1].split(","):
            keyword = keyword.strip()
            assert keyword == keyword.lower(), (name, keyword)
            assert all(ord(c) < 128 for c in keyword), (name, keyword)


def test_a_changelog_rule_exists_and_fires_on_the_fragment_directory():
    """The worked example: someone opening changelog.d/ gets the convention then,
    rather than reading it in a command doc at a moment when it does not apply.
    """
    rows = "\n".join(oss_rules.RULES["paths"])
    assert any("changelog" in name for name in oss_rules.RULES["paths"]), rows
    body = [b for n, b in oss_rules.RULES["paths"].items() if "changelog" in n][0]
    assert "changelog.d" in body.split("\n---\n")[0]


def test_rules_name_no_specific_repo():
    for dimension, rules in oss_rules.RULES.items():
        for name, body in rules.items():
            for spelling in ("Digital-Process-Tools", "claude-supertool", "claude-remember"):
                assert spelling not in body, (dimension, name, spelling)


def test_install_refuses_a_root_that_is_not_a_directory(tmp_path):
    victim = tmp_path / "file"
    victim.write_text("x", encoding="utf-8")
    with pytest.raises(oss_rules.RulesError):
        oss_rules.install(victim)
