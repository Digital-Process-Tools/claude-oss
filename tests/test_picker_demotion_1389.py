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

import re
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


def test_run_md_agent_spawns_resolve_against_a_fake_plugin_root(tmp_path):
    """The guard above only checks that the substring `commands/run/<name>`
    appears somewhere in commands/run.md's text -- it passes identically
    whether the path is anchored to ${CLAUDE_PLUGIN_ROOT} or left
    cwd-relative, because a cwd-relative path also contains that same
    substring. #1419: a cwd-relative
    `Agent(..., prompt: "Read and follow commands/run/<file>.md from
    here.")` resolves only inside this repository's own checkout, where
    this plugin's own source happens to live at that relative path -- in
    every *other* repo that installs this plugin, the spawned
    scheduler-step agent is pointed at a path that does not exist there.

    This test actually resolves each of the six spawn prompts' named path
    against a fake, temporary plugin root standing in for
    ${CLAUDE_PLUGIN_ROOT}, with no copy of the real commands/run/ tree
    anywhere nearby -- a positive control that only a real, anchored
    substitution can satisfy.
    """
    text = (COMMANDS_DIR / "run.md").read_text(encoding="utf-8")
    prompts = re.findall(r"Read and follow (\S+\.md) from here\.", text)
    assert len(prompts) == 6, (
        "expected exactly 6 'Read and follow ...' Agent spawn prompts in "
        "commands/run.md (setup + the five commands/run/*.md spawns), found "
        "{}: {}".format(len(prompts), prompts)
    )

    fake_plugin_root = tmp_path / "fake-plugin-root"
    for name in DEMOTED:
        target = fake_plugin_root / "commands" / "run" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stub", encoding="utf-8")

    for path_template in prompts:
        assert "${CLAUDE_PLUGIN_ROOT}" in path_template, (
            "Agent spawn prompt path {!r} in commands/run.md is not "
            "anchored to ${{CLAUDE_PLUGIN_ROOT}} -- it resolves only "
            "relative to the session's own cwd, which is this "
            "repository's own checkout and no other repo that installs "
            "this plugin".format(path_template)
        )
        resolved = path_template.replace("${CLAUDE_PLUGIN_ROOT}", str(fake_plugin_root))
        assert Path(resolved).exists(), (
            "Agent spawn prompt path {!r} does not resolve to a real file "
            "once ${{CLAUDE_PLUGIN_ROOT}} is substituted with a fake "
            "plugin root -- got {!r}".format(path_template, resolved)
        )


def test_run_md_every_read_and_follow_is_anchored_nearby_1421():
    """#1421: the exact-phrase guard above (`test_run_md_agent_spawns_
    resolve_against_a_fake_plugin_root`) only matches `Read and follow
    <path> from here.` where the sentence itself names a literal path --
    it is blind by construction to a paraphrase that instead points back
    at a document named earlier in the same paragraph with a pronoun.
    That was exactly commands/run.md's own `## dispatch` section before
    this fix: "This is `commands/tick.md`'s own procedure ... Read and
    follow it from here.", naming the target as a bare, cwd-relative path
    one sentence before the pronoun-phrased instruction that reads it.

    Rather than pin this test to the literal word "it" -- which the fix
    below removes entirely, by naming the target directly instead of by
    pronoun -- this widens the net to every "Read and follow" occurrence
    in the file, phrased however, and requires a ${CLAUDE_PLUGIN_ROOT}
    anchor somewhere in the same paragraph. That is a real positive
    control: run against the pre-fix text (a pronoun paragraph naming
    only a bare `commands/tick.md`), this fails exactly the same way the
    narrower, now-removed pronoun-literal assertion did.
    """
    text = (COMMANDS_DIR / "run.md").read_text(encoding="utf-8")

    spots = [m.start() for m in re.finditer(r"Read and\s+follow\b", text)]
    assert len(spots) >= 7, (
        "expected at least 7 'Read and follow' instructions in "
        "commands/run.md (the 6 scheduler-step spawns plus the dispatch "
        "step's own read of commands/tick.md) -- found {}".format(len(spots))
    )

    for idx in spots:
        paragraph_start = text.rfind("\n\n", 0, idx)
        paragraph_end = text.find("\n\n", idx)
        if paragraph_end == -1:
            paragraph_end = len(text)
        paragraph = text[paragraph_start:paragraph_end]
        assert "${CLAUDE_PLUGIN_ROOT}" in paragraph, (
            "a 'Read and follow' instruction in commands/run.md sits in a "
            "paragraph with no ${{CLAUDE_PLUGIN_ROOT}} anchor anywhere in "
            "it, however the instruction itself is phrased (literal path "
            "or pronoun) -- it resolves only relative to the session's "
            "own cwd. paragraph: {!r}".format(paragraph)
        )


def test_tick_md_self_read_instruction_is_anchored_1421():
    """#1421's second site: commands/tick.md:11 tells the reader to fetch
    the rest of itself with `supertool 'read:commands/tick.md:OFFSET:LIMIT'`
    -- harmless when tick.md is harness-injected directly as a slash
    command, but live when tick.md is instead reached from commands/run.md's
    dispatch step, where the session's cwd is the target repo rather than
    this plugin's own checkout and a bare `commands/tick.md` read resolves
    nowhere. It must be anchored to ${CLAUDE_PLUGIN_ROOT} the same way the
    six commands/run.md spawn prompts are.

    It must also be *double*-quoted, not single-quoted: this string is a
    literal, executable `supertool <quote>read:...<quote>` invocation (unlike
    commands/run.md's six spawn prompts, which are `Agent(..., prompt: "...")`
    tool-call arguments a session builds itself, never shell text). Bash
    performs no parameter expansion inside single quotes, so a self-review
    round on this exact lane found the first draft's fix -- `supertool
    'read:${CLAUDE_PLUGIN_ROOT}/commands/tick.md:OFFSET:LIMIT'` -- anchored
    in name only: run literally, ${CLAUDE_PLUGIN_ROOT} reaches supertool as
    that seven-character literal string, not the resolved plugin path. The
    established convention for a literal shell invocation elsewhere in this
    repo (`commands/run.md:34`, `commands/doctor.md:9`, both
    `bash "${CLAUDE_PLUGIN_ROOT}/scripts/..."`) always double-quotes the
    variable for exactly this reason.
    """
    text = (COMMANDS_DIR / "tick.md").read_text(encoding="utf-8")

    read_calls = re.findall(r"(['\"])read:(\S+?):OFFSET:LIMIT\1", text)
    assert read_calls, (
        "expected at least one 'read:<path>:OFFSET:LIMIT' self-read "
        "instruction in commands/tick.md -- if this fires because the "
        "prose changed, update this test to match the new phrasing"
    )
    for quote_char, path_template in read_calls:
        assert "${CLAUDE_PLUGIN_ROOT}" in path_template, (
            "commands/tick.md's own self-read instruction names {!r}, "
            "which is not anchored to ${{CLAUDE_PLUGIN_ROOT}} -- it "
            "resolves only relative to the session's own cwd, which is "
            "not this plugin's checkout when tick.md is reached from "
            "commands/run.md's dispatch step".format(path_template)
        )
        assert quote_char == '"', (
            "commands/tick.md's self-read instruction anchors "
            "${{CLAUDE_PLUGIN_ROOT}} inside single quotes ('{}') rather "
            "than double quotes -- this is a literal, executable shell "
            "invocation, and bash performs no parameter expansion inside "
            "single quotes, so the anchor is inert when this line is "
            "actually run outside this repository's own checkout".format(path_template)
        )
