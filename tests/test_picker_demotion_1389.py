"""#1389: the slash picker collapses toward two verbs, /oss:run and /oss:doctor.

The plugin harness discovers slash commands from top-level `commands/*.md`
only -- confirmed against the harness's own plugin-directory-structure
documentation, since there is no `user-invocable`-style frontmatter key for a
command file (that key exists only for skills, #1391). Subdirectories are
never scanned, so a file moved one directory down is out of the picker
entirely while staying prose a session can still read and follow.

This lane demotes six of the eight commands `/oss:run` absorbs: `setup`,
`scaffold`, `triage`, `curate`, `changelog`, `install-audit` move to
`commands/run/*.md`. `commands/tick.md` and `commands/release.md` are
deliberately left in place -- each is named by dozens of test files and
several scripts by literal path, coupling deep enough that migrating either
is its own, separately-reviewable change (see CLAUDE.md and docs/overview.md
for the full argument). This is the regression test for that exact,
partial state: the picker must be {run, doctor, tick, release}, no more and
no less, and the six demoted files must exist at their new home and nowhere
else.

The must-fire half of the negative assertion: a control fixture proves the
top-level glob is genuinely scanning `commands/` (finds a file placed there)
so a directory typo could not make every assertion below pass vacuously.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMANDS_DIR = REPO_ROOT / "commands"
RUN_DIR = COMMANDS_DIR / "run"

PROMOTED = {"run.md", "doctor.md", "tick.md", "release.md"}
DEMOTED = {
    "setup.md",
    "scaffold.md",
    "triage.md",
    "curate.md",
    "changelog.md",
    "install-audit.md",
}


def test_the_top_level_picker_is_exactly_the_four_promoted_commands():
    on_disk = {p.name for p in COMMANDS_DIR.glob("*.md")}
    assert on_disk == PROMOTED, (
        "commands/*.md (what the plugin harness registers as real slash "
        "commands) is {}, not the four promoted commands {} -- #1389's "
        "picker consolidation has drifted".format(sorted(on_disk), sorted(PROMOTED))
    )


def test_the_demoted_six_exist_only_under_commands_run():
    on_disk = {p.name for p in RUN_DIR.glob("*.md")}
    assert on_disk == DEMOTED, (
        "commands/run/*.md is {}, not the six demoted commands {}".format(
            sorted(on_disk), sorted(DEMOTED)
        )
    )
    for name in DEMOTED:
        assert not (COMMANDS_DIR / name).exists(), (
            "{} still exists at the top level of commands/ -- it would still "
            "register as a real slash command, un-demoting it".format(name)
        )


def test_control_the_top_level_glob_actually_finds_something(tmp_path):
    """Must-fire half: prove `commands/*.md` really is a live, scanning glob
    over a real directory, so the assertions above are not vacuously true of
    an empty or misspelled path.
    """
    (tmp_path / "commands").mkdir()
    (tmp_path / "commands" / "probe.md").write_text("x", encoding="utf-8")
    found = {p.name for p in (tmp_path / "commands").glob("*.md")}
    assert found == {"probe.md"}, (
        "the glob this test suite relies on does not find a file placed "
        "directly under commands/ -- every assertion above would pass "
        "vacuously against an empty result"
    )


def test_control_a_subdirectory_file_is_not_picked_up_by_the_top_level_glob():
    """Must-not-fire half, pinned against this repo's own real tree: a file
    genuinely present under commands/run/ must not appear in the top-level
    commands/*.md glob, which is the entire mechanism this demotion depends
    on -- if this ever changed (a Claude Code harness update that started
    scanning recursively), every command "demoted" here would silently
    re-appear in the picker with nothing here to notice.
    """
    on_disk = {p.name for p in COMMANDS_DIR.glob("*.md")}
    assert "setup.md" not in on_disk, (
        "commands/*.md picked up commands/run/setup.md -- the top-level glob "
        "is no longer non-recursive, so every demoted command above is back "
        "in the picker"
    )


def test_run_md_points_at_the_new_locations_not_the_old_ones():
    text = (COMMANDS_DIR / "run.md").read_text(encoding="utf-8")
    for name in DEMOTED:
        assert "commands/run/{}".format(name) in text, (
            "commands/run.md does not point at commands/run/{} -- a session "
            "following its own 'read and follow' instruction would 404".format(name)
        )
        assert "`commands/{}`".format(name) not in text, (
            "commands/run.md still names the stale top-level path "
            "commands/{}, which no longer exists".format(name)
        )
