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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_rules  # noqa: E402


def _layer(root, dimension):
    return root / ".claude" / "jit-context" / dimension / oss_rules.LAYER


#: Which column of an index row holds the entry FILENAME, per dimension. Measured against
#: claude-jit-context's `rebuild-tsv.sh` (see scripts/doctor.py's JIT_FILENAME_COLUMN,
#: which carries the same citation): tools rows are seven columns wide with the filename
#: third; paths and vocabulary are two columns with the filename second.
FILENAME_COLUMN = {"tools": 2, "paths": 1, "vocabulary": 1}

#: The one entry filename that is not an entry. The dependency's builder skips it by name in
#: every builder it has, and `doctor.JIT_ENTRY_SKIP` is the same constant on this side; a
#: layer uses it to carry something that is not a rule without the something becoming one.
NOT_A_RULE = "00-README.md"


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


def test_index_rows_are_shaped_per_dimension(tmp_path):
    """Paths and vocabulary are `pattern<TAB>filename`; tools is the seven-column shape
    `rebuild-tsv.sh` writes (see FILENAME_COLUMN above) -- a two-column assertion applied to
    a tools row would fail on a correctly built index, which is this test's own defect
    wearing the opposite sign.
    """
    oss_rules.install(tmp_path)
    for dimension in oss_rules.RULES:
        index = _layer(tmp_path, dimension) / "00-index.tsv"
        column = FILENAME_COLUMN[dimension]
        for line in index.read_text(encoding="utf-8").splitlines():
            fields = line.split("\t")
            assert len(fields) == (7 if dimension == "tools" else 2), line
            assert fields[0].strip(), line
            assert fields[column].endswith(".md"), line


def test_every_indexed_file_exists(tmp_path):
    """A row naming a file that is not there is the silent half of the same defect."""
    oss_rules.install(tmp_path)
    for dimension in oss_rules.RULES:
        layer = _layer(tmp_path, dimension)
        column = FILENAME_COLUMN[dimension]
        for line in (layer / "00-index.tsv").read_text(encoding="utf-8").splitlines():
            assert (layer / line.split("\t")[column]).is_file(), line


def test_every_rule_file_is_indexed(tmp_path):
    """And the other half: a file with no row never fires.

    `00-README.md` is exempt, and the exemption is not this suite's invention: the
    dependency's index builder skips that exact name in every one of its four builders, and
    `doctor.JIT_ENTRY_SKIP` skips it too. It is how a layer records something that is not a
    rule -- a deliberate gap, say -- without the record itself becoming one. Indexing it
    here would produce a row the next rebuild deletes, which reads as drift.

    The exemption is one name, not a pattern, so it cannot quietly grow to cover a rule that
    genuinely lost its row.
    """
    oss_rules.install(tmp_path)
    for dimension in oss_rules.RULES:
        layer = _layer(tmp_path, dimension)
        column = FILENAME_COLUMN[dimension]
        indexed = {
            line.split("\t")[column]
            for line in (layer / "00-index.tsv").read_text(encoding="utf-8").splitlines()
        }
        on_disk = {p.name for p in layer.glob("*.md")} - {NOT_A_RULE}
        assert on_disk, "{}: every entry was exempted -- nothing was checked".format(
            dimension
        )
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


# --- #109: a description: for every shipped entry, or summary injection has nothing to say ---


def test_every_shipped_entry_declares_a_description():
    """Under `JIT_CONTEXT_INJECT=summary`, a match injects `title:` plus `description:` only.
    An entry with no `description:` is named and not injected -- the content never reaches a
    session running that mode. All three population dimensions must carry one, and it must say
    something: an empty `description: ""` passes a bare substring check while reproducing the
    exact bug this guards against -- nothing useful injected under summary mode.
    """
    for dimension, rules in oss_rules.RULES.items():
        for name, body in rules.items():
            block = body.split("\n---\n")[0]
            line = [ln for ln in block.splitlines() if ln.startswith("description:")]
            assert line, (dimension, name)
            value = line[0].split(":", 1)[1].strip().strip('"')
            assert len(value) > 20, (dimension, name, value)


# --- #108: the fragments rule must fire on CHANGELOG.md, the moment its warning applies ------


def _awk():
    return shutil.which("awk") or shutil.which("gawk")


def _ere_matches(pattern, subject):
    """The same test the hook applies: `match(subject, pattern)` under an awk ERE, run for
    real rather than approximated through Python's `re` -- a PCRE engine accepts syntax an
    awk ERE refuses or reads differently, so a Python-side pass is not evidence about the
    hook. `-v` passes both strings so neither is interpolated into the program text.

    A spawn that never answers within the timeout measures nothing about whether `pattern`
    matches `subject` -- it is neither a MATCH nor a NOMATCH -- so `subprocess.TimeoutExpired`
    is skipped rather than left to propagate as an assertion failure would (#712). Observed
    on `windows-latest`: Git for Windows' `awk.EXE` did not answer a one-line `BEGIN` block
    inside 10 seconds, and the uncaught exception reddened a release on a commit that never
    touched this rule, this pattern or this function. Widening the timeout would only move
    the threshold (`CLAUDE.md`'s "do not tune a test until it passes"); the fix is that a
    timeout must not render as the same outcome a wrong answer does. `pytest.skip` raises
    immediately, before the caller's next assertion runs -- which is what skips the whole
    test rather than one assertion, load-bearing for callers with a positive control after
    the first assertion that would otherwise report a false "must not fire" with nothing
    proving it can fire.
    """
    awk_path = _awk()
    program = 'BEGIN { print (subject ~ pattern) ? "MATCH" : "NOMATCH" }'
    try:
        result = subprocess.run(
            [awk_path, "-v", "subject=" + subject, "-v", "pattern=" + pattern, program],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.skip(
            "awk ({}) did not answer within {}s on {!r} -- this measures nothing about "
            "whether {!r} matches {!r}, and is not the same outcome as a NOMATCH "
            "(#712)".format(awk_path, exc.timeout, sys.platform, pattern, subject)
        )
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    return result.stdout.strip() == "MATCH"


def test_the_changelog_match_fires_on_changelog_md_and_still_fires_on_a_fragment():
    """The bug: `match: changelog.d/` never fired on `CHANGELOG.md`, the one moment its main
    instruction -- do not hand-edit this file -- applies. The widened pattern must fire on
    both, and a positive control (an unrelated path) must still not fire: a match that hits
    everything would pass the first half of this test for the wrong reason.
    """
    if _awk() is None:
        pytest.skip("no awk on PATH, so the widened ERE cannot be driven for real")
    body = oss_rules.RULES["paths"]["changelog-fragments.md"]
    match_line = [
        ln for ln in body.split("\n---\n")[0].splitlines() if ln.startswith("match:")
    ][0]
    pattern = match_line.split(":", 1)[1].strip()

    assert _ere_matches(pattern, "CHANGELOG.md"), "must fire: opening the file it warns about"
    assert _ere_matches(pattern, "docs/CHANGELOG.md"), "must fire: nested under a directory too"
    assert _ere_matches(pattern, "changelog.d/106.added.md"), "must still fire: a fragment"
    assert not _ere_matches(pattern, "src/CHANGELOG_notes.md"), (
        "must not fire: this is the positive control -- an unrelated file whose name merely "
        "contains the word must stay silent, or the pattern is matching everything"
    )


def test_ere_matches_skips_rather_than_fails_on_a_timeout(monkeypatch):
    """A `subprocess.TimeoutExpired` means the ERE was never measured -- neither a MATCH
    nor a NOMATCH -- so it must render as a skip of the whole test, not as the same
    failure a wrong answer produces (#712). `pytest.raises(Exception)` would not catch
    this: pytest's own skip exception derives from `BaseException` rather than
    `Exception` (the trap CLAUDE.md records), so the outcome type is pinned here rather
    than left to `Exception`, which would silently pass this test for the wrong reason
    if `_ere_matches` merely swallowed the timeout instead of skipping through it.
    """

    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["awk"], timeout=10)

    monkeypatch.setattr(subprocess, "run", _timeout)
    with pytest.raises(pytest.skip.Exception):
        _ere_matches("x", "y")


def test_no_awk_escape_that_compiles_to_nothing():
    """`\\s`, `\\d`, `\\w` and `\\b` compile to the bare letter or a backspace under an awk
    ERE and match nothing while awk exits 0 -- a silently dead rule. None of the three
    shipped `match:` patterns may contain one.
    """
    for dimension in ("paths", "tools"):
        for name, body in oss_rules.RULES.get(dimension, {}).items():
            block = body.split("\n---\n")[0]
            match_line = [ln for ln in block.splitlines() if ln.startswith("match:")]
            if not match_line:
                continue
            pattern = match_line[0].split(":", 1)[1].strip()
            for dead in ("\\s", "\\d", "\\w", "\\b"):
                assert dead not in pattern, (dimension, name, pattern)


# --- #106: a tools rule blocking Read, Edit, Write, Glob and Grep in favour of supertool -----


def test_tools_dimension_blocks_the_five_native_ops():
    rules = oss_rules.RULES.get("tools", {})
    assert rules, "no tools dimension shipped"
    # Named, not positional. This read `next(iter(rules.items()))` and so asserted about
    # whichever entry the dict happened to yield first -- which stopped being the only
    # entry the moment the layer began carrying a non-rule beside it. A dict-order change
    # would have turned this into an assertion about a file with no `tool:` line at all,
    # failing on an index error rather than on anything about the rule it is named for.
    body = rules["supertool-required.md"]
    block = body.split("\n---\n")[0]
    tool_line = [ln for ln in block.splitlines() if ln.startswith("tool:")][0]
    tools = set(tool_line.split(":", 1)[1].strip().split("|"))
    assert tools == {"Read", "Edit", "Write", "Glob", "Grep"}, tools
    mode_line = [ln for ln in block.splitlines() if ln.startswith("mode:")][0]
    assert mode_line.split(":", 1)[1].strip() == "block", (
        "a rule with no exception must block, not remind -- a remind on an absolute rule "
        "teaches the reader to dismiss it"
    )


def test_tools_rule_names_the_replacement_op():
    """A block whose message is only 'don't' costs the reader the round trip it was trying
    to save. The body must name the supertool op that replaces each blocked call.

    Derived from the frontmatter, and the op is checked against the shipped-spelling
    inventory rather than against the blocked tool's own name lowercased. The version of
    this test that looped over `("read:", "edit:", "write:", ...)` is how #197 shipped:
    it built the expected op out of the tool it replaces, so it asserted the presence of
    the very spelling that does not resolve, and would have passed just as happily
    against `frobnicate:PATH` on the Read row.
    """
    import test_shipped_op_spellings as spellings

    body = oss_rules.RULES["tools"]["supertool-required.md"]
    block = body.split("\n---\n")[0]
    tool_line = [ln for ln in block.splitlines() if ln.startswith("tool:")][0]
    tools = tool_line.split(":", 1)[1].strip().split("|")
    assert len(tools) == 5, tools
    for tool in tools:
        rows = [ln for ln in body.splitlines() if ln.startswith("- **{}**".format(tool))]
        assert len(rows) == 1, "{}: expected one bullet naming its replacement, got {}".format(
            tool, rows
        )
        named = [op for op, _ in spellings.op_spellings(rows[0])]
        assert named, "{}: the row names no supertool invocation: {}".format(tool, rows[0])
        undeclared = [op for op in named if op not in spellings.OP_INVENTORY]
        assert not undeclared, (
            "{}: the row sends a blocked reader to {}, which is not a declared op -- "
            "the remedy for a refusal has to resolve".format(tool, undeclared)
        )


def test_tools_index_row_is_the_seven_column_shape():
    """`tool<TAB>match<TAB>filename<TAB>mode<TAB>require<TAB>forbid<TAB>requires`,
    re-derived from claude-jit-context's rebuild-tsv.sh rather than trusted from the
    issue that named it (#80 found the same list wrong when someone only reasoned about
    it). The seventh column was added by #665: `requires` was declared in frontmatter by
    #570 and read by claude-jit-context 0.6.0's `jit_missing_requires()`, but nothing
    here ever emitted it, so the shipped index disagreed with the rule body it indexes.

    Per-row expectations are keyed by filename, not asserted blanket across every row --
    the tools dimension carries two indexed rules since #245 (`supertool-required.md` and
    `merge-gate.md`), and a blanket assertion here would fail on a correctly built index
    with a second row, which is this test's own defect wearing the opposite sign from the
    "Named, not positional" fix a few tests below.
    """
    rows = oss_rules.index_rows("tools", oss_rules.RULES["tools"])
    assert rows
    by_filename = {}
    for row in rows:
        fields = row.split("\t")
        assert len(fields) == 7, row
        tool, match, filename, mode, require, forbid, requires = fields
        assert match, "empty match -- the row would refuse to load"
        by_filename[filename] = (tool, mode, requires)

    assert by_filename["supertool-required.md"] == (
        "Read|Edit|Write|Glob|Grep",
        "block",
        "supertool",
    ), by_filename["supertool-required.md"]
    assert by_filename["merge-gate.md"] == ("Bash", "remind", ""), by_filename[
        "merge-gate.md"
    ]


def test_tools_match_fires_on_a_representative_payload_for_each_blocked_tool():
    """Driven for real against the actual ERE: the wildcard match must actually match a
    representative payload for each of the five tools' ordinary calls. (Bash is excluded
    from the blocked set by the `tool:` field, not by `match:` -- see
    test_tools_dimension_blocks_the_five_native_ops for that half.)
    """
    if _awk() is None:
        pytest.skip("no awk on PATH, so the tools match cannot be driven for real")
    body = oss_rules.RULES["tools"]["supertool-required.md"]
    match_line = [
        ln for ln in body.split("\n---\n")[0].splitlines() if ln.startswith("match:")
    ][0]
    raw = match_line.split(":", 1)[1].strip()
    # `~` marks this as a real ERE to the hook rather than a substring rule (common.sh);
    # strip it the same way before driving it through awk directly.
    pattern = raw[1:] if raw.startswith("~") else raw
    for payload in ("src/oss_rules.py", "README.md", "*.py", "TODO"):
        assert _ere_matches(pattern, payload), (pattern, payload)


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


def _assembler_commands(body):
    """Every shell line that invokes the assembler, in the order the rule prints them.

    Plural since #721. The rule used to publish a single command combining `--check`
    and `--check-links`; the assembler refuses that combination outright, so the rule
    publishes one invocation per audit.

    This helper asserts nothing about the count on purpose. The singular version did --
    `at most one` -- and seven callers below inherited a hard constraint on the *number*
    of audits from a helper whose subject is the *path* they name. How many invocations
    there should be is a question each caller answers for itself; answering it here
    answers it once, for all of them, in the file least likely to be read when the
    number changes.
    """
    return [
        line.strip()
        for line in body.splitlines()
        if line.strip().startswith("python3 ") and "assemble_changelog.py" in line
    ]


def _assembler_command(body, flag):
    """The single invocation carrying *flag*, or None if the rule emits none at all.

    Matched against the shlex-split tokens rather than the raw line: `--check` is a
    prefix of `--check-links`, so a substring test finds the other command and reports
    an agreement it never established.
    """
    commands = _assembler_commands(body)
    if not commands:
        return None
    found = [command for command in commands if flag in shlex.split(command)]
    assert len(found) == 1, "expected exactly one {} invocation, got {}".format(
        flag, found
    )
    return found[0]


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

    commands = _assembler_commands(_changelog_rule(root))
    assert commands, "no invocation emitted for a tree that has an assembler"
    # Every line, not the first. A second invocation naming a path that is not in the
    # tree is the identical defect, and it is the one a singular helper could not see.
    for command in commands:
        script = _script_argument(command)
        assert (root / script).is_file(), "{}: not in the tree it was written into".format(
            script
        )
        assert script == VENDORED, script


def test_this_repo_shaped_rule_names_an_assembler_that_exists_in_that_tree(tmp_path):
    """The other population. The two answers differ, and a test covering one of them
    passes while the other ships a path that is not there.
    """
    root = _plugin_shaped(tmp_path)
    oss_rules.install(root)

    commands = _assembler_commands(_changelog_rule(root))
    assert commands, "no invocation emitted for a tree that has an assembler"
    for command in commands:
        script = _script_argument(command)
        assert (root / script).is_file(), "{}: not in the tree it was written into".format(
            script
        )
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

    assert _assembler_commands(_changelog_rule(managed)) != _assembler_commands(
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
    assert _assembler_commands(body) == [], "guessed a path in a tree that has none"
    assert "assemble_changelog.py" not in body, body
    assert "could not" in body.lower(), "silent about being unable to look:\n" + body


def test_the_emitted_commands_pass_dir_and_changelog(tmp_path):
    """The assembler derives its own root by walking up for a `.git` when it is given
    neither, which under a plugin finds the wrong repository.

    Per command since #721, and both flags on both: that is what
    `scaffold.CHANGELOG_WORKFLOW`'s two steps pass, and this rule closes by promising
    the reader that their command and the CI leg's cannot disagree. Asserting it of
    only one of the two lines would leave the other free to derive its own root.
    """
    root = _scaffolded(tmp_path)
    oss_rules.install(root)
    body = _changelog_rule(root)

    for flag in ("--check", "--check-links"):
        command = _assembler_command(body, flag)
        assert command, "no {} invocation emitted".format(flag)
        tokens = shlex.split(command)
        assert "--dir" in tokens, command
        assert "--changelog" in tokens, command


def test_the_emitted_path_uses_forward_slashes(tmp_path):
    """Written on one platform, read and run on three. A backslash separator here is a
    Windows-shaped defect authored on POSIX; python3 accepts forward slashes on Windows.
    """
    for root in (_scaffolded(tmp_path), _plugin_shaped(tmp_path)):
        oss_rules.install(root)
        for command in _assembler_commands(_changelog_rule(root)):
            script = _script_argument(command)
            assert "\\" not in script, script


def test_the_fragments_directory_is_the_one_the_repo_uses(tmp_path):
    """`changelog.d` is a default, not a fact about every repository. The rule has to fire
    on the directory that repo actually keeps fragments in, or it never fires at all.
    """
    root = _scaffolded(tmp_path)
    oss_rules.install(root, fragments_dir="changes")

    body = _changelog_rule(root)
    block = body.split("\n---\n")[0]
    match_line = [ln for ln in block.splitlines() if ln.startswith("match:")][0]
    assert "changes/" in match_line, match_line
    # The fragment audit is the one that takes a directory, so that is the invocation
    # the repo's own directory has to reach. Asked of whichever line happened to come
    # first, this passes on a rule that names the directory only where it is not read.
    assert "changes" in _assembler_command(body, "--check")


def test_the_committed_layer_in_this_repo_names_a_path_that_is_here():
    """The artifact, not the generator. The layer is committed, so a regeneration nobody
    ran leaves the old answer in the tree with every test above still green (#68).
    """
    body = (
        REPO_ROOT / ".claude" / "jit-context" / "paths" / "01-oss" / "changelog-fragments.md"
    ).read_text(encoding="utf-8")
    commands = _assembler_commands(body)
    assert commands, "the committed rule emits no invocation, though this repo has one"
    for command in commands:
        script = _script_argument(command)
        assert (REPO_ROOT / script).is_file(), "{}: not in this repository".format(script)

    # And that it is the CURRENT rendering. Resolving is necessary and not sufficient: the
    # old committed string named a path that resolves here, which is precisely why the bug
    # was invisible from inside this repository.
    #
    # Rendered from THIS repository's `.oss.json`, the way `scaffold.py --apply` renders
    # it, rather than from `rules()`'s defaults. Every per-repo input this rule takes has
    # to come from the same place the real caller takes it from, or the comparison
    # measures the defaults and passes on a layer built from something else. It held with
    # one input only because this repo's `changelog_dir` happens to equal the default;
    # `changelog_untagged` does not, and would not have been noticed by a test comparing
    # against a value neither side read (#101).
    import json

    config = json.loads((REPO_ROOT / ".oss.json").read_text(encoding="utf-8"))
    current = oss_rules.rules(
        REPO_ROOT,
        fragments_dir=config["changelog_dir"],
        untagged=config.get("changelog_untagged"),
    )["paths"]["changelog-fragments.md"]
    assert body == current, (
        "the committed layer is stale -- rerun /oss:scaffold, or scripts/scaffold.py --apply"
    )


def test_the_committed_tools_layer_in_this_repo_is_the_current_rendering():
    """The same staleness question one dimension over, where nothing was asking it.

    The check above covers `paths/changelog-fragments.md` alone, because that rule is the
    one with per-repo substitution in it. The tools rules have none -- they render from
    constants -- which is exactly what made them *easy* to leave stale: every generator
    test stays green while the committed copy, which is what this repository's own hook
    actually reads, keeps serving the previous text. #294 and #307 both rewrote a tools
    rule, and refreshing the committed copy was a manual step that happened to get done.

    Compared as a whole dimension rather than file by file, so a rule added to `rules()`
    and never written out is caught by the same assertion as one whose text moved.
    """
    layer = REPO_ROOT / ".claude" / "jit-context" / "tools" / oss_rules.LAYER
    current = oss_rules.RULES["tools"]
    committed = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(layer.glob("*.md"))
    }
    assert committed == current, (
        "the committed tools layer is not what oss_rules would write today -- rerun "
        "/oss:scaffold, or scripts/scaffold.py --apply. Names here but not generated: "
        "{}. Generated but not here: {}. Same name, different text: {}.".format(
            sorted(set(committed) - set(current)),
            sorted(set(current) - set(committed)),
            sorted(n for n in set(committed) & set(current) if committed[n] != current[n]),
        )
    )

    # The index beside them, held separately: the bodies can be current while the index
    # is a rebuild behind, and a row is what decides whether a rule is consulted at all.
    index = (layer / oss_rules.INDEX).read_text(encoding="utf-8")
    expected = "\n".join(oss_rules.index_rows("tools", current)) + "\n"
    assert index == expected, (
        "the committed tools index is not what index_rows() produces for these rules"
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


# --- #117: why the assembler is missing, when it is missing --------------------------
#
# `assembler_path()` returning None has more than one cause and they do not share a
# remedy. In a repo where /oss:scaffold declined the owned changelog trio because a gate
# already runs there under another name, the could-not-locate branch's remedy sentence --
# run /oss:scaffold and this rule is rewritten with the invocation -- names the command
# that just declined and will decline again. The clause is false in exactly the repo the
# decline produces, and it renders identically to the same sentence in a repo where it is
# true. So the caller tells the rule what it established about the gate, and the rule
# stops guessing why the script is not there.

DECLINED = ("found", "already present: .github/workflows/changelog.yml")
UNREADABLE = ("unknown", "could not read: packages/private")

#: The sentence the pre-#117 rule emitted for every missing assembler, and the one it
#: must now emit only when a gate was looked for and none was found.
VENDORING_REMEDY = "run that and this rule is rewritten with the invocation"

#: Emitted only when the caller established that a foreign gate is what is in the way.
DECLINED_ANCHOR = "will not put one here"


def _no_assembler(tmp_path, name):
    root = tmp_path / name
    root.mkdir()
    return root


def _flat(body):
    """The rule body with its line wrapping collapsed.

    Prose anchors are matched against this, not the raw text. A phrase that happens to
    span a wrap is absent from the file it is plainly in, and reflowing a paragraph then
    turns a real guard off with nothing failing -- the same absence-that-reads-as-clean
    this whole rule exists to prevent, in the test for it.
    """
    return " ".join(body.split())


def test_a_declined_repo_is_not_sent_back_to_the_command_that_declined(tmp_path):
    """Both arms on one pair of trees. Asserting only the declined arm passes if the
    remedy sentence stopped being emitted anywhere at all, which would break the far
    commoner repo -- the one that has no gate and is waiting to be handed the checker.
    """
    declined = _no_assembler(tmp_path, "declined")
    oss_rules.install(declined, gate=DECLINED)
    declined_body = _changelog_rule(declined)

    clean = _no_assembler(tmp_path, "clean")
    oss_rules.install(clean, gate=("none", ""))
    clean_body = _changelog_rule(clean)

    # Declined: no invocation, no false remedy, and the workflow that does run is named.
    assert _assembler_commands(declined_body) == [], declined_body
    assert DECLINED_ANCHOR in _flat(declined_body), declined_body
    assert ".github/workflows/changelog.yml" in declined_body, declined_body
    assert VENDORING_REMEDY not in _flat(declined_body), declined_body

    # No gate: the remedy is true here, and this is the arm that must keep firing.
    assert _assembler_commands(clean_body) == [], clean_body
    assert VENDORING_REMEDY in _flat(clean_body), clean_body
    assert DECLINED_ANCHOR not in _flat(clean_body), clean_body


def test_a_tree_that_could_not_be_read_is_not_reported_as_a_decline(tmp_path):
    """`_detect_changelog_gate` has three answers, not two. Folding `unknown` into the
    declined text would state as established the one thing that run failed to establish.
    """
    root = _no_assembler(tmp_path, "unreadable")
    oss_rules.install(root, gate=UNREADABLE)
    body = _changelog_rule(root)

    assert "packages/private" in body, body
    assert "unknown" in body.lower(), body
    assert DECLINED_ANCHOR not in _flat(body), body
    assert VENDORING_REMEDY not in _flat(body), body


def test_a_caller_that_did_not_look_says_so_rather_than_promising_a_rewrite(tmp_path):
    """The fourth answer, and the default. `rules()` is called with no gate by anything
    that only wants the structural shape, and by any caller predating the parameter --
    neither of which checked, so neither may promise what /oss:scaffold will do.
    """
    root = _no_assembler(tmp_path, "unlooked")
    oss_rules.install(root)
    body = _changelog_rule(root)

    assert "not established" in _flat(body), body
    assert DECLINED_ANCHOR not in _flat(body), body
    assert VENDORING_REMEDY not in _flat(body), body


def test_the_rest_of_the_layer_still_ships_into_a_declined_repo(tmp_path):
    """The shape this fix is not: omitting the changelog rule leaves the reader with no
    statement at all, and the other rules have nothing to do with the trio.
    """
    root = _no_assembler(tmp_path, "declined-layer")
    written = oss_rules.install(root, gate=DECLINED)

    for dimension, layer_rules in oss_rules.RULES.items():
        for name in layer_rules:
            assert (_layer(root, dimension) / name).is_file(), name
    assert len(written) == sum(len(r) for r in oss_rules.RULES.values()) + len(
        oss_rules.RULES
    )


def test_an_unrecognised_gate_state_is_refused_rather_than_rendered(tmp_path):
    """A state this module does not know cannot be rendered honestly, and the branch it
    would fall through to is the one that says nobody looked -- which would be false.
    """
    root = _no_assembler(tmp_path, "bogus")
    with pytest.raises(oss_rules.RulesError):
        oss_rules.install(root, gate=("probably", "who knows"))


def test_the_gate_detail_cannot_break_out_of_its_code_span(tmp_path):
    """The detail is built from filenames in somebody's repository. A backtick in one
    would end the span and spill the rest of the sentence into rendered markdown.
    """
    root = _no_assembler(tmp_path, "backtick")
    oss_rules.install(root, gate=("found", "already present: wf/`odd`.yml"))
    body = _changelog_rule(root)

    assert "odd" in body, body
    assert "`odd`" not in body, body
