"""Are the declared dependencies actually configured?

Installing them is automatic; configuring them is not, and the difference is invisible.
A memory plugin with no identity still runs and still saves. A rule matcher whose index
was never rebuilt still runs and matches nothing -- and a rule that never fires looks
exactly like a rule that fired and had nothing to say.

So these are checks, not assumptions, and each has three outcomes rather than two.
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


@pytest.fixture(autouse=True)
def clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _states():
    return [state for state, _ in doctor.FINDINGS]


def _messages():
    return " ".join(message for _, message in doctor.FINDINGS)


# ------------------------------------------------------------------------- memory


def test_a_project_with_no_memory_store_warns_with_the_fix(tmp_path):
    """No `.claude/remember/config.json` here, so this is the one test in this file
    that falls through to the user-global layer (#614) -- isolate the real home
    directory, or the outcome would depend on whatever remember layout happens to be
    configured on the machine running the suite."""
    home = tmp_path / "isolated-home"
    doctor.check_memory(tmp_path, home=home)
    assert _states() == ["WARN"]
    assert "remember" in _messages()


def _memory(
    root, identity=True, data_dir=".remember", stray=False, local_install=False
):
    """The real layout: `config.json` in `.claude/remember/`, sessions in the `data_dir`
    that config names.

    identity.md is the part that went round twice. It can live in either directory and
    both are read -- but by different layouts, and the one this plugin's own dependency
    install uses is the DATA dir. Measured against the memory plugin's session-start
    hook: with identity.md in both places it injects the data dir's copy, and with the
    data dir's copy removed it injects neither, because the config dir is only the
    plugin's own directory in a LOCAL install and this was not one.

    So `identity=True` seeds the DATA dir, which is what a correctly configured repo
    looks like. `stray=True` seeds the config dir instead -- present, deliberate-looking
    and never injected.
    """
    config_dir = root / ".claude" / "remember"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text(
        json.dumps({"data_dir": data_dir}), encoding="utf-8"
    )
    (root / data_dir).mkdir(parents=True, exist_ok=True)
    if identity:
        (root / data_dir / "identity.md").write_text(
            "who the agent is\n", encoding="utf-8"
        )
    if stray:
        (config_dir / "identity.md").write_text("never injected\n", encoding="utf-8")
    if local_install:
        (config_dir / "scripts").mkdir(exist_ok=True)
    return config_dir


def test_a_memory_store_without_an_identity_is_reported(tmp_path):
    """Sessions save fine without one, which is what makes the gap invisible."""
    _memory(tmp_path, identity=False)
    doctor.check_memory(tmp_path)
    assert _states() == ["WARN"]
    assert "identity" in _messages().lower()


def test_a_configured_memory_store_is_ok(tmp_path):
    _memory(tmp_path)
    doctor.check_memory(tmp_path)
    assert _states() == ["OK"]


def test_identity_in_the_data_dir_satisfies_the_check(tmp_path):
    """The data dir is where the session-start hook looks FIRST, so a repo with only
    this copy is correctly configured and must not be told otherwise.

    This asserts the opposite of what it used to. The old version encoded the belief
    that the data dir was the wrong place; running the hook says it is the first place
    it reads, and the only one read in a dependency install.
    """
    _memory(tmp_path)
    doctor.check_memory(tmp_path)
    assert _states() == ["OK"]
    assert ".remember" in _messages()


def test_identity_only_beside_the_config_is_not_a_pass(tmp_path):
    """The state that reads as configured from every angle except the one that matters.

    Measured, not reasoned: with this exact layout -- `config.json` and `identity.md` in
    `.claude/remember/`, no plugin installed there -- the memory plugin's session-start
    hook injects nothing, because it resolves identity against the data dir, the data
    dir's parent, and the plugin's own directory. None of those is this one.

    Two of our own repos are in this state and the doctor called them configured, which
    is the tool producing an absence and the reader taking it for the world.
    """
    _memory(tmp_path, identity=False, stray=True)
    doctor.check_memory(tmp_path)
    assert _states() == ["WARN"]
    assert "never read" in _messages()


def test_identity_beside_the_config_is_a_pass_when_the_plugin_lives_there(tmp_path):
    """The positive control for the case above, and the reason it is not simply wrong to
    keep identity there: in a LOCAL install the plugin's own directory IS
    `.claude/remember/`, so the third fallback resolves and the file is injected.

    Without this pair the check above would pass just as well against a checker that
    warned unconditionally.
    """
    _memory(tmp_path, identity=False, stray=True, local_install=True)
    doctor.check_memory(tmp_path)
    assert _states() == ["OK"]


def test_the_data_dir_copy_wins_over_a_stray_one(tmp_path):
    """Both present is not ambiguous -- the hook reads the data dir first, so the doctor
    must not report the copy that loses.
    """
    _memory(tmp_path, stray=True)
    doctor.check_memory(tmp_path)
    assert _states() == ["OK"]
    assert "never read" not in _messages()


def test_the_identity_warning_names_both_directories_it_read(tmp_path):
    """The failure that made this worth fixing: the warning named `.remember` while the
    lookup read `.claude/remember`, so doing exactly what it said left it byte-for-byte
    unchanged and gave no way to tell a wrong path from wrong content.

    A checker that consulted a path must name that path, or its finding cannot be acted
    on -- which is the same three-states rule the rest of this file is about, applied to
    the message rather than the verdict.
    """
    _memory(tmp_path, identity=False)
    doctor.check_memory(tmp_path)
    assert _states() == ["WARN"]
    message = _messages()
    for named in (".remember", ".claude/remember"):
        assert named in message, "the warning does not name {}, which it read".format(
            named
        )


def test_a_custom_data_dir_from_the_config_is_honoured(tmp_path):
    """`data_dir` is configurable, so a hardcoded `.remember` reports a missing store
    for a repo that has one.
    """
    _memory(tmp_path, data_dir="memory-store")
    doctor.check_memory(tmp_path)
    assert _states() == ["OK"]


# ---------------------------------------------------------------------------- jit


def _layer(root, dimension="vocabulary", layer="00-manual"):
    """The real layout: rules live per dimension, per layer, and each layer carries
    its OWN index. An earlier version of this check looked for one index at the root
    of the rules directory, which does not exist -- so a correctly configured repo
    would have been told, permanently and confidently, that none of its rules run.
    """
    path = root / ".claude" / "jit-context" / dimension / layer
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_no_rules_directory_is_reported_as_absent_not_as_fine(tmp_path):
    doctor.check_jit_rules(tmp_path)
    assert _states() == ["WARN"]
    assert "no rules" in _messages().lower()


def test_rules_with_no_index_are_a_finding(tmp_path):
    """This is the failure worth catching: the rules exist, the matcher runs, and
    nothing ever fires because the table it reads is not there.
    """
    layer = _layer(tmp_path)
    (layer / "conventions.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    doctor.check_jit_rules(tmp_path)
    assert _states() == ["FAIL"]
    assert "index" in _messages().lower()


def test_a_layer_with_only_its_own_record_and_no_index_is_consistent(tmp_path):
    """#641: a layer holding ONLY its generated JIT_ENTRY_SKIP record has zero
    rule entries by construction -- an absent or empty index beside them is the
    correct rendering of "nothing to index", not the missing-table defect the
    FAIL arm above exists to catch. That defect requires entries to exist.
    """
    layer = _layer(tmp_path)
    (layer / doctor.JIT_ENTRY_SKIP).write_text("---\ntitle: x\n---\n", encoding="utf-8")
    doctor.check_jit_rules(tmp_path)
    assert _states() == ["OK"], _messages()


def test_a_layer_with_only_its_own_record_and_an_empty_index_is_consistent(tmp_path):
    """The twin of the test above, for the empty-index arm rather than the
    missing-index one."""
    layer = _layer(tmp_path)
    (layer / doctor.JIT_ENTRY_SKIP).write_text("---\ntitle: x\n---\n", encoding="utf-8")
    (layer / "00-index.tsv").write_text("", encoding="utf-8")
    doctor.check_jit_rules(tmp_path)
    assert _states() == ["OK"], _messages()


def test_a_layer_with_real_rules_and_an_empty_index_still_fails(tmp_path):
    """The must-fire control for both tests above: a layer that DOES have
    entries and an empty index is the real defect, and the zero-entries guard
    must not swallow it."""
    layer = _layer(tmp_path)
    (layer / "conventions.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    (layer / "00-index.tsv").write_text("", encoding="utf-8")
    doctor.check_jit_rules(tmp_path)
    assert _states() == ["FAIL"], _messages()
    assert "1 rule" in _messages()


def test_the_index_is_looked_for_inside_the_layer_not_at_the_root(tmp_path):
    """An index at the rules root does not satisfy a layer that has none of its own."""
    layer = _layer(tmp_path)
    (layer / "conventions.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    (tmp_path / ".claude" / "jit-context" / "00-index.tsv").write_text(
        "x\ty\n", encoding="utf-8"
    )
    doctor.check_jit_rules(tmp_path)
    assert _states() == ["FAIL"]


def test_each_dimension_is_checked_separately(tmp_path):
    """One indexed dimension does not vouch for another. Reporting OK because the
    first layer checked out is how a whole dimension goes quiet unnoticed.
    """
    indexed = _layer(tmp_path, "vocabulary")
    (indexed / "billing.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    (indexed / "00-index.tsv").write_text("billing\tx\n", encoding="utf-8")
    unindexed = _layer(tmp_path, "paths")
    (unindexed / "commands.md").write_text("---\ntitle: y\n---\n", encoding="utf-8")

    doctor.check_jit_rules(tmp_path)
    assert "FAIL" in _states()
    assert "paths" in _messages()


def _touched_after(index, *entries):
    """Entry files newer than the index, by an explicit stamp rather than by write order.

    A test that writes the index, sleeps, and writes the entry is measuring the
    filesystem's timestamp granularity as much as the code: one second on ext3 and on
    some network mounts, two on FAT. Setting both stamps says what the fixture means.
    """
    base = 1000000000
    os.utime(index, (base, base))
    for entry in entries:
        os.utime(entry, (base + 60, base + 60))


def test_a_body_edit_with_identical_rows_is_not_told_to_rebuild(tmp_path):
    """#80. mtime is evidence the index MIGHT be stale. It is not evidence that any
    row differs -- and the row is the thing the warning asserted.

    The bodies are what changed here; the indexed columns come from frontmatter, and
    they are byte-identical to what a rebuild would write. Paired with the drift test
    below, which shares this fixture and differs only in the frontmatter, because
    "is not told to rebuild" also passes when the check never runs at all.
    """
    layer = _layer(tmp_path, "paths")
    entry = layer / "conventions.md"
    entry.write_text("---\nmatch: docs/\n---\n\nrewritten body.\n", encoding="utf-8")
    index = layer / "00-index.tsv"
    index.write_text("docs/\tconventions.md\n", encoding="utf-8")
    _touched_after(index, entry)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["OK"], _messages()
    assert "rebuild" not in _messages().lower()


def test_frontmatter_the_index_does_not_carry_is_reported_as_stale(tmp_path):
    """The positive control: same fixture, same mtimes, a match: the row does not have."""
    layer = _layer(tmp_path, "paths")
    entry = layer / "conventions.md"
    entry.write_text("---\nmatch: handbook/\n---\n", encoding="utf-8")
    index = layer / "00-index.tsv"
    index.write_text("docs/\tconventions.md\n", encoding="utf-8")
    _touched_after(index, entry)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["WARN"], _messages()
    assert "rebuild the index" in _messages().lower()
    assert "conventions.md" in _messages()


def test_a_tools_row_is_compared_on_every_column_not_just_the_pattern(tmp_path):
    """A `block` downgraded to `remind` is a rule that reads as enforced and is not.
    The indexer writes six columns -- tool, match, filename, mode, require, forbid --
    so all six are what "the row says something else" has to mean.
    """
    layer = _layer(tmp_path, "tools")
    entry = layer / "no-force-push.md"
    entry.write_text(
        "---\ntool: Bash\nmatch: git push\nmode: block\n---\n", encoding="utf-8"
    )
    index = layer / "00-index.tsv"
    index.write_text("Bash\tgit push\tno-force-push.md\tremind\t\t\n", encoding="utf-8")
    _touched_after(index, entry)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["WARN"], _messages()
    assert "rebuild the index" in _messages().lower()


def test_a_tools_row_that_matches_every_column_is_current(tmp_path):
    """The control for the column comparison: the same six columns, agreeing."""
    layer = _layer(tmp_path, "tools")
    entry = layer / "no-force-push.md"
    entry.write_text(
        "---\ntool: Bash\nmatch: git push\nmode: block\n---\n", encoding="utf-8"
    )
    index = layer / "00-index.tsv"
    index.write_text("Bash\tgit push\tno-force-push.md\tblock\t\t\n", encoding="utf-8")
    _touched_after(index, entry)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["OK"], _messages()
    assert "rebuild" not in _messages().lower()


def test_a_seven_column_tools_row_from_a_newer_builder_is_not_read_as_drift(tmp_path):
    """#640: claude-jit-context 0.6.0's rebuild-tsv.sh writes a seventh
    `requires` column on the tools row (its own #203). Before the fix,
    `jit_index_drift` compared against a fixed six-column string, so every
    up-to-date repo's tools rows read as stale -- a widened index that adds
    nothing NEW is not drift, it is what the current builder writes.
    """
    layer = _layer(tmp_path, "tools")
    entry = layer / "no-force-push.md"
    entry.write_text(
        "---\ntool: Bash\nmatch: git push\nmode: block\n---\n", encoding="utf-8"
    )
    index = layer / "00-index.tsv"
    index.write_text(
        "Bash\tgit push\tno-force-push.md\tblock\t\t\t\n", encoding="utf-8"
    )
    _touched_after(index, entry)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["OK"], _messages()
    assert "rebuild" not in _messages().lower()


def test_a_populated_seventh_column_that_disagrees_is_still_drift(tmp_path):
    """The must-fire control for the test above: the seventh column carries a
    value, and it disagrees with the frontmatter -- normalising trailing empty
    fields must not swallow a real disagreement in a populated one.
    """
    layer = _layer(tmp_path, "tools")
    entry = layer / "no-force-push.md"
    entry.write_text(
        "---\ntool: Bash\nmatch: git push\nmode: block\nrequires: git\n---\n",
        encoding="utf-8",
    )
    index = layer / "00-index.tsv"
    index.write_text(
        "Bash\tgit push\tno-force-push.md\tblock\t\t\t\n", encoding="utf-8"
    )
    _touched_after(index, entry)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["WARN"], _messages()
    assert "rebuild the index" in _messages().lower()


def test_a_row_that_cannot_be_derived_is_named_rather_than_judged(tmp_path):
    """The third state. An invocation macro is expanded at index time, so the row is
    the expansion and the frontmatter is the shorthand -- this check does not expand
    macros, and the honest answer is that it could not look, naming which entry.

    What it must NOT do is fall back to the imperative it cannot support.
    """
    layer = _layer(tmp_path, "tools")
    entry = layer / "push-anchor.md"
    entry.write_text(
        "---\ntool: Bash\nmatch: ~@invocation git push\n---\n", encoding="utf-8"
    )
    index = layer / "00-index.tsv"
    index.write_text(
        "Bash\t(^|[;&|] *)git push\tpush-anchor.md\tremind\t\t\n", encoding="utf-8"
    )
    _touched_after(index, entry)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["WARN"], _messages()
    assert "push-anchor.md" in _messages()
    assert "macro" in _messages().lower()
    assert "rebuild the index" not in _messages().lower()


def test_a_dimension_with_no_known_derivation_is_declined_by_name(tmp_path):
    """The same third state from the other direction: the row format belongs to
    another tool, and a dimension this one has never heard of is not one it can
    re-derive. Say so, with the dimension named.
    """
    layer = _layer(tmp_path, "gadgets")
    entry = layer / "widget.md"
    entry.write_text("---\nmatch: docs/\n---\n", encoding="utf-8")
    index = layer / "00-index.tsv"
    index.write_text("docs/\twidget.md\n", encoding="utf-8")
    _touched_after(index, entry)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["WARN"], _messages()
    assert "gadgets" in _messages()
    assert "rebuild the index" not in _messages().lower()


def test_an_undecidable_entry_no_newer_than_its_index_is_still_said_out_loud(tmp_path):
    """Not a WARN -- nothing suggests this index is stale -- but it must never render
    as "checked and clean" either, which is the state this whole family of tools
    exists to keep visible.
    """
    layer = _layer(tmp_path, "tools")
    entry = layer / "push-anchor.md"
    entry.write_text(
        "---\ntool: Bash\nmatch: ~@invocation git push\n---\n", encoding="utf-8"
    )
    index = layer / "00-index.tsv"
    index.write_text("Bash\tanything\tpush-anchor.md\tremind\t\t\n", encoding="utf-8")
    _touched_after(entry, index)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["OK"], _messages()
    assert "1 not checked" in _messages()


def test_a_keyword_the_blacklist_drops_is_not_read_as_drift(tmp_path):
    """The vocabulary indexer skips generic single words, so a keyword in the
    frontmatter with no row is the documented behaviour, not staleness. Asserting
    equality there would report drift on a correctly built index.
    """
    layer = _layer(tmp_path, "vocabulary")
    entry = layer / "billing.md"
    entry.write_text("---\nkeywords: file, invoice\n---\n", encoding="utf-8")
    index = layer / "00-index.tsv"
    index.write_text("invoice\tbilling.md\n", encoding="utf-8")
    _touched_after(index, entry)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["OK"], _messages()


def test_a_keyword_the_frontmatter_no_longer_carries_is_drift(tmp_path):
    """The control for the asymmetry above: a row the frontmatter cannot produce is
    proof the index predates the edit, in the direction a blacklist cannot explain.
    """
    layer = _layer(tmp_path, "vocabulary")
    entry = layer / "billing.md"
    entry.write_text("---\nkeywords: invoice\n---\n", encoding="utf-8")
    index = layer / "00-index.tsv"
    index.write_text("invoice\tbilling.md\ndunning\tbilling.md\n", encoding="utf-8")
    _touched_after(index, entry)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["WARN"], _messages()
    assert "rebuild the index" in _messages().lower()


def test_an_entry_that_cannot_be_read_is_the_third_state_not_the_first(tmp_path):
    """An entry doctor cannot decode derives no rows -- and derives no verdict either.
    Silence there would render as "rows match", which is the one thing it is not.
    """
    layer = _layer(tmp_path, "paths")
    entry = layer / "conventions.md"
    entry.write_bytes(b"---\nmatch: docs/\xff\xfe\n---\n")
    index = layer / "00-index.tsv"
    index.write_text("docs/\tconventions.md\n", encoding="utf-8")
    _touched_after(index, entry)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["WARN"], _messages()
    assert "conventions.md" in _messages()
    assert "could not be read" in _messages()
    assert "rebuild the index" not in _messages().lower()


def test_an_index_that_cannot_be_read_is_unknown_rather_than_current(tmp_path):
    """It exists and it is not empty, so both earlier gates pass. Whether it is current
    is then a question nothing answered.
    """
    layer = _layer(tmp_path, "paths")
    entry = layer / "conventions.md"
    entry.write_text("---\nmatch: docs/\n---\n", encoding="utf-8")
    index = layer / "00-index.tsv"
    index.write_bytes(b"docs/\tconventions.md\xff\xfe\n")
    _touched_after(index, entry)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["WARN"], _messages()
    assert "unknown" in _messages().lower()


def test_a_non_ascii_keyword_is_declined_rather_than_folded_here(tmp_path):
    """The indexer folds Latin-1 accents to ASCII before normalising. Doing that fold a
    second time here, differently, would report drift about this function rather than
    about the index -- so the entry is named as unchecked instead.
    """
    layer = _layer(tmp_path, "vocabulary")
    entry = layer / "billing.md"
    entry.write_text("---\nkeywords: détail\n---\n", encoding="utf-8")
    index = layer / "00-index.tsv"
    index.write_text("detail\tbilling.md\n", encoding="utf-8")
    _touched_after(index, entry)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["WARN"], _messages()
    assert "billing.md" in _messages()
    assert "rebuild the index" not in _messages().lower()


def test_an_entry_the_builder_writes_no_row_for_is_not_drift(tmp_path):
    """A paths entry with no `match:` produces no row, by design and with a report of
    its own from the rebuild. Expecting one here would call every such layer stale.
    """
    layer = _layer(tmp_path, "paths")
    prose = layer / "notes.md"
    prose.write_text("---\ntitle: notes\n---\n", encoding="utf-8")
    entry = layer / "conventions.md"
    entry.write_text("---\nmatch: docs/\n---\n", encoding="utf-8")
    index = layer / "00-index.tsv"
    index.write_text("docs/\tconventions.md\n", encoding="utf-8")
    _touched_after(index, entry, prose)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["OK"], _messages()


def test_a_malformed_index_row_is_not_read_as_a_row_about_an_entry(tmp_path):
    """A row with no filename column names no entry, so it is evidence about nothing --
    and reading its first column as a filename would invent drift on a file called
    `stale`.
    """
    layer = _layer(tmp_path, "paths")
    entry = layer / "conventions.md"
    entry.write_text("---\nmatch: docs/\n---\n", encoding="utf-8")
    index = layer / "00-index.tsv"
    index.write_text("docs/\tconventions.md\nstale\n", encoding="utf-8")
    _touched_after(index, entry)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["OK"], _messages()


def test_a_quoted_match_is_unwrapped_the_way_the_indexer_unwraps_it(tmp_path):
    """The frontmatter reader strips a quote pair that wraps the whole value and leaves
    every other quote alone, because a `match:` is an ERE and `["]` is how an author
    anchors on a quoted argument. A reader that stripped every quote would report drift
    on a correct index -- and one that stripped none would too.
    """
    layer = _layer(tmp_path, "paths")
    entry = layer / "conventions.md"
    entry.write_text('---\nmatch: "docs/"\n---\n', encoding="utf-8")
    index = layer / "00-index.tsv"
    index.write_text("docs/\tconventions.md\n", encoding="utf-8")
    _touched_after(index, entry)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["OK"], _messages()


def test_trailing_space_in_a_match_is_kept_the_way_the_indexer_keeps_it(tmp_path):
    """The frontmatter reader trims trailing whitespace only on the copy it tests for
    wrapping quotes, so an unquoted `match: docs/ ` is indexed WITH the space. A
    reader that trimmed the returned value would derive `docs/`, find no such row and
    say "rebuild" at an index that is exactly what a rebuild writes.
    """
    layer = _layer(tmp_path, "paths")
    entry = layer / "conventions.md"
    entry.write_text("---\nmatch: docs/ \n---\n", encoding="utf-8")
    index = layer / "00-index.tsv"
    index.write_text("docs/ \tconventions.md\n", encoding="utf-8")
    _touched_after(index, entry)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["OK"], _messages()


def test_a_row_missing_that_trailing_space_is_still_drift(tmp_path):
    """The control for the fidelity above: the space is part of the pattern, so a row
    without it is a row that matches something else.
    """
    layer = _layer(tmp_path, "paths")
    entry = layer / "conventions.md"
    entry.write_text("---\nmatch: docs/ \n---\n", encoding="utf-8")
    index = layer / "00-index.tsv"
    index.write_text("docs/\tconventions.md\n", encoding="utf-8")
    _touched_after(index, entry)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["WARN"], _messages()
    assert "rebuild the index" in _messages().lower()


def test_a_row_for_an_entry_that_is_gone_is_drift(tmp_path):
    """Deleting a rule leaves its row behind, and the row is what runs."""
    layer = _layer(tmp_path, "paths")
    entry = layer / "conventions.md"
    entry.write_text("---\nmatch: docs/\n---\n", encoding="utf-8")
    index = layer / "00-index.tsv"
    index.write_text("docs/\tconventions.md\nold/\tremoved.md\n", encoding="utf-8")
    _touched_after(entry, index)

    doctor.check_jit_rules(tmp_path)
    assert _states() == ["WARN"], _messages()
    assert "removed.md" in _messages()


def test_rules_with_a_current_index_are_ok(tmp_path):
    """The row names the entry it came from. This fixture used to index `conventions`
    against a file `x` that was not in the layer -- a row no rebuild could produce, on
    an entry with no `keywords:` to produce it from, passing because nothing compared
    them.
    """
    layer = _layer(tmp_path)
    entry = layer / "conventions.md"
    entry.write_text("---\nkeywords: conventions\n---\n", encoding="utf-8")
    index = layer / "00-index.tsv"
    index.write_text("conventions\tconventions.md\n", encoding="utf-8")
    _touched_after(entry, index)
    doctor.check_jit_rules(tmp_path)
    assert _states() == ["OK"], _messages()


def test_an_empty_index_beside_real_rules_does_not_read_as_current(tmp_path):
    """An index file that exists and holds nothing is the same silence as no index,
    one layer down -- and it is the one that passes an existence check.
    """
    layer = _layer(tmp_path)
    (layer / "conventions.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    (layer / "00-index.tsv").write_text("", encoding="utf-8")
    doctor.check_jit_rules(tmp_path)
    assert _states() == ["FAIL"]
    assert "empty" in _messages().lower()


def test_the_finding_names_how_to_rebuild(tmp_path):
    layer = _layer(tmp_path)
    (layer / "conventions.md").write_text("---\ntitle: x\n---\n", encoding="utf-8")
    doctor.check_jit_rules(tmp_path)
    assert "rebuild" in _messages().lower()
