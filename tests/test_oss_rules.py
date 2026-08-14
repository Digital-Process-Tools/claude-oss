"""The `01-oss` rule layer.

Layers are the ownership boundary. `00-manual/` belongs to whoever maintains the repo;
`01-oss/` belongs to this plugin. That is what makes updating safe: we replace our layer
wholesale on every install, because nothing a human wrote lives in it, and we never look
at theirs.

A symlink into the plugin checkout would have been simpler and is refused by design --
git carries symlinks, so a clone could point rules anywhere. Copies into an owned layer
are the supported shape.
"""

import shlex
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


# --- #68: the assembler path the changelog rule names -------------------------------
#
# The correct path differs between this repository (`scripts/assemble_changelog.py`) and
# a scaffolded one (`.oss/assemble_changelog.py`, vendored there because CI checks out
# the managed repo and nothing else). A single shared template string cannot be right for
# both, so the generator derives it from the tree it is writing into.
#
# These assert on the GENERATED rule, not on the template: a test that matches the
# template string passes for whatever the template happens to say.

VENDORED = ".oss/assemble_changelog.py"
IN_TREE = "scripts/assemble_changelog.py"


def _changelog_rule(root):
    return (_layer(root, "paths") / "changelog-fragments.md").read_text(encoding="utf-8")


def _assembler_command(body):
    """The one shell line that invokes the assembler, or None if the rule emits none."""
    found = [
        line.strip()
        for line in body.splitlines()
        if line.strip().startswith("python3 ") and "assemble_changelog.py" in line
    ]
    assert len(found) < 2, "more than one invocation to check: {}".format(found)
    return found[0] if found else None


def _script_argument(command):
    """The path token, as written. shlex handles the quoting, and the token is compared as
    text -- a backslash separator here is a Windows-only breakage a POSIX-only assertion
    never sees.
    """
    tokens = shlex.split(command)
    assert tokens[0] == "python3", command
    return tokens[1]


def _scaffolded(tmp_path):
    """A managed repo: the assembler is vendored into the owned directory."""
    root = tmp_path / "managed"
    (root / ".oss").mkdir(parents=True)
    (root / ".oss" / "assemble_changelog.py").write_text("# vendored\n", encoding="utf-8")
    return root


def _plugin_shaped(tmp_path):
    """This repository's shape: the assembler is the plugin's own script."""
    root = tmp_path / "plugin"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "assemble_changelog.py").write_text("# ours\n", encoding="utf-8")
    return root


def test_scaffolded_rule_names_an_assembler_that_exists_in_that_tree(tmp_path):
    root = _scaffolded(tmp_path)
    oss_rules.install(root)

    command = _assembler_command(_changelog_rule(root))
    assert command, "no invocation emitted for a tree that has an assembler"
    script = _script_argument(command)
    assert (root / script).is_file(), "{}: not in the tree it was written into".format(script)
    assert script == VENDORED, script


def test_this_repo_shaped_rule_names_an_assembler_that_exists_in_that_tree(tmp_path):
    """The other population. The two answers differ, and a test covering one of them
    passes while the other ships a path that is not there.
    """
    root = _plugin_shaped(tmp_path)
    oss_rules.install(root)

    command = _assembler_command(_changelog_rule(root))
    assert command, "no invocation emitted for a tree that has an assembler"
    script = _script_argument(command)
    assert (root / script).is_file(), "{}: not in the tree it was written into".format(script)
    assert script == IN_TREE, script


def test_the_two_populations_get_different_commands(tmp_path):
    """The positive control on derivation itself. Both assertions above are satisfied by a
    generator that emits a constant, if that constant happens to match one tree -- so hold
    the two generated rules against each other.
    """
    managed = _scaffolded(tmp_path)
    ours = _plugin_shaped(tmp_path)
    oss_rules.install(managed)
    oss_rules.install(ours)

    assert _assembler_command(_changelog_rule(managed)) != _assembler_command(
        _changelog_rule(ours)
    )


def test_a_tree_with_no_assembler_gets_no_invocation(tmp_path):
    """The third state, and the reason this file exists. A generator that cannot find the
    assembler must say so rather than emit a plausible path -- a command that fails on
    first use is the tool's absence read as the repo's.
    """
    root = tmp_path / "bare"
    root.mkdir()
    oss_rules.install(root)

    body = _changelog_rule(root)
    assert _assembler_command(body) is None, "guessed a path in a tree that has none"
    assert "assemble_changelog.py" not in body, body
    assert "could not" in body.lower(), "silent about being unable to look:\n" + body


def test_the_emitted_command_passes_dir_and_changelog(tmp_path):
    """The assembler derives its own root by walking up for a `.git` when it is given
    neither, which under a plugin finds the wrong repository.
    """
    root = _scaffolded(tmp_path)
    oss_rules.install(root)
    command = _assembler_command(_changelog_rule(root))
    assert "--dir" in command, command
    assert "--changelog" in command, command
    assert "--check" in command, command


def test_the_emitted_path_uses_forward_slashes(tmp_path):
    """Written on one platform, read and run on three. A backslash separator here is a
    Windows-shaped defect authored on POSIX; python3 accepts forward slashes on Windows.
    """
    for root in (_scaffolded(tmp_path), _plugin_shaped(tmp_path)):
        oss_rules.install(root)
        script = _script_argument(_assembler_command(_changelog_rule(root)))
        assert "\\" not in script, script


def test_the_fragments_directory_is_the_one_the_repo_uses(tmp_path):
    """`changelog.d` is a default, not a fact about every repository. The rule has to fire
    on the directory that repo actually keeps fragments in, or it never fires at all.
    """
    root = _scaffolded(tmp_path)
    oss_rules.install(root, fragments_dir="changes")

    body = _changelog_rule(root)
    assert "match: changes/" in body.split("\n---\n")[0], body
    assert "changes" in _assembler_command(body)


def test_the_committed_layer_in_this_repo_names_a_path_that_is_here():
    """The artifact, not the generator. The layer is committed, so a regeneration nobody
    ran leaves the old answer in the tree with every test above still green (#68).
    """
    body = (
        REPO_ROOT / ".claude" / "jit-context" / "paths" / "01-oss" / "changelog-fragments.md"
    ).read_text(encoding="utf-8")
    command = _assembler_command(body)
    assert command, "the committed rule emits no invocation, though this repo has one"
    script = _script_argument(command)
    assert (REPO_ROOT / script).is_file(), "{}: not in this repository".format(script)

    # And that it is the CURRENT rendering. Resolving is necessary and not sufficient: the
    # old committed string named a path that resolves here, which is precisely why the bug
    # was invisible from inside this repository.
    assert body == oss_rules.rules(REPO_ROOT)["paths"]["changelog-fragments.md"], (
        "the committed layer is stale -- rerun /oss:scaffold, or scripts/scaffold.py --apply"
    )


def test_the_fragment_default_matches_the_scaffold_that_creates_the_directory():
    """Two spellings of one default drift, and the rule then matches a directory the
    scaffold never made -- a rule that cannot fire, which is this repo's named defect.
    """
    import scaffold

    assert oss_rules.DEFAULT_FRAGMENTS_DIR == scaffold.DEFAULT_FRAGMENTS_DIR


def test_install_refuses_a_root_that_is_not_a_directory(tmp_path):
    victim = tmp_path / "file"
    victim.write_text("x", encoding="utf-8")
    with pytest.raises(oss_rules.RulesError):
        oss_rules.install(victim)
