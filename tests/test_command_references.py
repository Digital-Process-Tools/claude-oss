"""Every script a command promises must exist.

A command file is prose that gets executed. A path in it that resolves to nothing
fails at the worst moment -- mid-task, in someone else's session -- and the failure
reads as the plugin being broken rather than as a line nobody checked.

The regexes here are asserted to match something. A pattern that found no references
has not verified the commands; it has only failed to look.
"""

import re
import shlex
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMANDS = sorted((REPO_ROOT / "commands").glob("*.md"))

# ${CLAUDE_PLUGIN_ROOT}/... in a fenced command line.
PLUGIN_PATH_RE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)")


def test_commands_exist():
    assert COMMANDS, "no commands/*.md found -- the checks below would vacuously pass"


def test_every_command_declares_frontmatter():
    for path in COMMANDS:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n"), "{}: no frontmatter".format(path.name)
        block = text[4 : text.index("\n---\n", 3)]
        assert "description:" in block, "{}: no description".format(path.name)
        assert "allowed-tools:" in block, "{}: no allowed-tools".format(path.name)


def test_referenced_scripts_exist():
    references = []
    missing = []
    for path in COMMANDS:
        text = path.read_text(encoding="utf-8")
        for match in PLUGIN_PATH_RE.finditer(text):
            target = match.group(1)
            references.append((path.name, target))
            if not (REPO_ROOT / target).exists():
                missing.append(
                    "{}: references {} which does not exist".format(path.name, target)
                )

    assert references, (
        "no ${CLAUDE_PLUGIN_ROOT}/... references found in commands/. Either the commands "
        "stopped invoking scripts, or PLUGIN_PATH_RE no longer matches how they are written "
        "-- a pattern that matched nothing has checked nothing."
    )
    assert not missing, "\n  ".join([""] + missing)


def test_commands_use_the_plugin_root_variable_for_scripts():
    """A relative path works in whichever directory the author happened to be in."""
    offenders = []
    for path in COMMANDS:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not (stripped.startswith("python3 ") or stripped.startswith("bash ")):
                continue
            if "${CLAUDE_PLUGIN_ROOT}" not in stripped:
                offenders.append("{}:{}: {}".format(path.name, number, stripped))
    assert not offenders, (
        "script invocations must be rooted at ${CLAUDE_PLUGIN_ROOT}:\n  "
        + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------- #
# Prose facts the surfaces have to carry.
#
# These are the easiest assertions in the repo to write vacuously: "does this
# file mention X" passes on a file that mentions X while saying the opposite,
# and on a file long enough that everything is in it somewhere. So every
# predicate below is checked three ways -- against the real file, against a
# file that says nothing on the subject, and against the real file with the
# load-bearing lines deleted. A predicate surviving all three has looked.
# --------------------------------------------------------------------------- #

SETUP_MD = REPO_ROOT / "commands" / "setup.md"
SCAFFOLD_MD = REPO_ROOT / "commands" / "scaffold.md"
# #1037: TICK_FACTS below (step 2/4 content: the board read, the radar heal)
# moved out of commands/tick.md into its own phase file.
TICK_MD = REPO_ROOT / "skills" / "manager" / "phases" / "tick-order.md"
DOCTOR_MD = REPO_ROOT / "commands" / "doctor.md"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from manager_docs import ManagerLoop  # noqa: E402

#: The manager loop's whole prose -- SKILL.md plus every phase file it defers
#: to. The checks below ask "does the loop say X", never "does one file say
#: X"; pinned to the spine alone they would have gone quietly narrower than
#: their own subject the moment a paragraph moved into a phase file.
SKILL_MD = ManagerLoop(REPO_ROOT)
DEVELOPER_MD = REPO_ROOT / "agents" / "developer.md"
README_MD = REPO_ROOT / "README.md"
#: #795 moved the "scaffold is the second step" paragraph out of README.md and
#: into docs/install.md, along with the rest of the launcher-setup material it
#: sits beside -- README_FACTS below now reads from there instead.
INSTALL_DOC = REPO_ROOT / "docs" / "install.md"
RELEASE_MD = REPO_ROOT / "commands" / "release.md"

# Mentions no command, no settings file and no subject for identity.md.
SILENT = "# Setup\n\nProbe the repo and write the config. Then stop.\n"


def _without_lines_matching(text, pattern):
    return "\n".join(
        line for line in text.splitlines() if not re.search(pattern, line, re.I)
    )


def _names_the_agent_as_identity_subject(text):
    return "identity.md" in text and bool(re.search(r"who the agent is", text, re.I))


def _points_at_an_identity_example(text):
    return "identity.example.md" in text


def _names_scaffold_as_the_next_step(text):
    return "/oss:scaffold" in text and bool(re.search(r"tracked file", text, re.I))


def _names_tick_as_the_next_step(text):
    return "/oss:tick" in text and bool(re.search(r"furniture is in place", text, re.I))


def _names_tick_as_the_reopened_session_next_step(text):
    """#957: doctor.md's own version of the same hand-off, worded for a session that
    was *reopened* rather than one that just finished scaffolding -- see the doctor.py
    docstring the command's own prose quotes for why the diagnostic itself stays
    silent about this.
    """
    return "/oss:tick" in text and bool(re.search(r"reopen", text, re.I))


def _names_the_settings_file_for_the_merge_rule(text):
    return ".claude/settings.local.json" in text


def _covers_both_path_spellings(text):
    return "./supertool" in text and bool(re.search(r"absolute path", text, re.I))


def _says_the_two_merge_strings_differ(text):
    return "gh-pr-merge:N:squash|force" in text and bool(
        re.search(r"different .{0,40}string", text, re.I)
    )


def _says_the_harness_gate_is_a_fourth_one(text):
    return bool(re.search(r"fourth", text, re.I)) and bool(
        re.search(r"no_publish_confirm|three opt-outs", text, re.I)
    )


# --------------------------------------------------------------------------- #
# The release needs an answer for a call the harness refuses (#186).
#
# The plugin documents supertool's own confirmation gate and its three opt-outs
# and says nothing about the harness permission sitting in front of them, which
# can refuse the tag push or the publish -- after the fold has already deleted
# the fragments. A refusal is none of `release_publish.py`'s three verdicts:
# those are earned by running. So the predicates below require the file to say
# that, not merely to mention that denials happen. The distinction is the whole
# issue -- the same call has been denied and then permitted with no change, so a
# document that merely acknowledges denials exist leaves the loop with nothing
# to do when one lands mid-sequence.
# --------------------------------------------------------------------------- #


def _says_a_denial_is_not_one_of_the_three(text):
    return bool(re.search(r"\bdenied\b", text, re.I)) and bool(
        re.search(r"has no exit code", text, re.I)
    )


def _forbids_evading_a_denied_call(text):
    return bool(re.search(r"do not reword", text, re.I)) and bool(
        re.search(r"until the classifier relents", text, re.I)
    )


def _says_where_a_denied_release_resumes(text):
    return bool(re.search(r"where a denied release resumes", text, re.I)) and bool(
        re.search(r"never reports as released", text, re.I)
    )


# --------------------------------------------------------------------------- #
# The handoff is measured, not recommended (#136).
#
# `/oss:setup` used to close by *naming* `/oss:scaffold`. A setup that stopped
# there and a setup that completed render identically -- clean run, clean `git
# status`, half-furnished repo. The fix is that setup ends by running the
# read-only plan, so the furniture gap arrives as a measured list. Three things
# then have to stay true of the file, and prose alone would let any of them rot:
# the plan is actually invoked, it is never the writing invocation, and the
# outcomes it can produce are all three rather than two.
# --------------------------------------------------------------------------- #

# A `python3 ... scaffold.py ...` command line, wherever it appears in the prose.
SCAFFOLD_LINE_RE = re.compile(r"^\s*(?:python3?|py)\s+\S*scaffold\.py\b.*$")

WRITING_FLAGS = ("--apply", "--force-owned")


def _scaffold_invocations(text):
    """Every `scaffold.py` command line in *text*, as (line number, line)."""
    return [
        (number, line.strip())
        for number, line in enumerate(text.splitlines(), 1)
        if SCAFFOLD_LINE_RE.match(line)
    ]


def _writing_scaffold_invocations(name, text):
    """Which of those invocations would write into the repository.

    Tokenised rather than substring-matched, for the reason the assembler flags
    below are: a line whose comment mentions `--apply` is not a line that passes
    it, and a guard that reads a comment as a violation is as broken as one that
    reads a comment as compliance. A line that will not tokenise is its own
    finding -- an argument list nobody could read has not been checked.
    """
    offenders = []
    for number, line in _scaffold_invocations(text):
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError as error:
            offenders.append(
                "{}:{}: unparseable arguments ({}): {}".format(
                    name, number, error, line
                )
            )
            continue
        hit = [flag for flag in WRITING_FLAGS if flag in tokens]
        if hit:
            offenders.append(
                "{}:{}: passes {}: {}".format(name, number, " and ".join(hit), line)
            )
    return offenders


def _runs_the_scaffold_plan(text):
    """A read-only scaffold invocation is present -- the plan is run, not named."""
    return any(
        not _writing_scaffold_invocations("x", line)
        for _number, line in _scaffold_invocations(text)
    )


def _says_a_failed_plan_is_not_a_failed_setup(text):
    return bool(re.search(r"could not plan", text, re.I)) and bool(
        re.search(r"not a failed setup", text, re.I)
    )


def _separates_the_offline_plan_from_the_forge_read(text):
    return bool(re.search(r"read from the filesystem", text, re.I)) and bool(
        re.search(r"only line that asks the forge", text, re.I)
    )


def _says_the_tick_seam_cannot_be_previewed(text):
    return "/oss:tick" in text and bool(re.search(r"cannot be previewed", text, re.I))


# --------------------------------------------------------------------------- #
# The tick's board read has to order the two conditional readings (#187).
#
# `commands/tick.md` ordered one call -- `gh-prs`, `gh-issues`, `gh-branch` --
# and named neither `radar` nor `git-worktrees` anywhere in the file, while
# steps 3 and 5 went on to decide from both. Each omission produces an absence
# that reads as a clean result: a watcher fleet nobody checked renders as a
# quiet channel, a worktree board nobody read renders as no worktrees.
#
# The predicates below deliberately require an *invocation*, not a mention.
# That is the whole distinction #187 turned on -- the skill cautions against
# assuming `radar`, and the loop read the caution as permission to skip the
# reading. A "does this file say radar" predicate passes on the caution, which
# is why CAUTIONING below is a control in its own right and SILENT is not
# enough here.
# --------------------------------------------------------------------------- #


def _invokes_op(text, op):
    """A `supertool '<op>'` command line, wherever it appears in the prose."""
    return bool(re.search(r"^\s*supertool\s+.*" + re.escape(op), text, re.M))


def _orders_the_watcher_probe(text):
    """The read-only probe is run, not merely named as a thing that exists."""
    return _invokes_op(text, "radar:--state")


def _says_an_unread_channel_is_not_a_quiet_one(text):
    return bool(re.search(r"not a quiet channel", text, re.I)) and bool(
        re.search(r"forwarded is not delivered", text, re.I)
    )


# --------------------------------------------------------------------------- #
# The bare heal is a step of its own, with its own three outcomes (#208).
#
# #187 landed the read-only probe and stopped there: the file ordered
# `radar:--state`, then said "tiers are registered -- run bare `radar`" in
# prose and named no outcome for that run. So all three states the step carried
# were states of the *probe*, and a bare call that errored, a bare call that
# refused for want of a tier, and a bare call that healed nothing all left the
# tick with the same thing to report -- nothing. That is the absence this
# repository is named after, sitting inside the step written to close it.
#
# The predicates below require the write half to be invoked, its refusal to be
# stated as a non-failure, and the probe's channel-ownership line to be relayed
# rather than swallowed -- a step that forks pollers into a fleet whose name
# came from the environment is healing something that may not be this repo's.
# --------------------------------------------------------------------------- #

#: A bare `supertool 'radar'` line. Deliberately anchored on the whole argument:
#: `_invokes_op(text, "radar")` also matches the `radar:--state` probe, so the
#: loose spelling would certify the exact file #208 was filed against.
BARE_RADAR_RE = re.compile(r"^\s*supertool\s+'radar'\s*$", re.M)


def _orders_the_bare_radar_heal(text):
    """The write half is run, not described as a thing that exists."""
    return bool(BARE_RADAR_RE.search(text))


def _carries_the_bare_radar_outcomes(text):
    """The refusal is a state, and the failure to run is a different state."""
    return bool(re.search(r"could not raise", text, re.I)) and bool(
        re.search(r"must not be reported as a failure", text, re.I)
    )


def _relays_the_channel_ownership_warning(text):
    return "watch_name" in text and bool(re.search(r"another project's fleet", text))


def _says_an_empty_poller_list_is_not_an_absent_fleet(text):
    """`pollers : none` is what the probe prints for the case the heal exists for."""
    return bool(re.search(r"pollers\s*:\s*none", text, re.I)) and bool(
        re.search(r"the second answer, not the first", text, re.I)
    )


def _orders_the_worktree_board(text):
    return _invokes_op(text, "git-worktrees")


def _carries_the_three_state_worktree_rule(text):
    """`cannot tell` is not `idle`, and `merge unknown` is not `merged`.

    The skill states this at its cleanup gate, but nothing in the ordered steps
    reached it -- so a loop following the steps literally could produce a wrong
    reap without ever having read the rule that forbids it.
    """
    return bool(re.search(r"`cannot tell` is not `idle`", text)) and bool(
        re.search(r"`merge unknown` is not `merged`", text)
    )


# --------------------------------------------------------------------------- #
# The heal has to follow board membership, not sit at the top (#242).
#
# #187 added the read-only probe and #208 added the bare heal, and both landed
# in step 2 because that is where the board read was. Radar has no discovery
# feed -- its own footer says `discovery: radar ticks only` -- so a heal arms
# pollers for what was open at the moment it ran and nothing after. Every pull
# request the tick itself opened was therefore unwatched for its whole CI run,
# and the loop fell back to polling `gh-pr:N:status` without noticing why.
#
# The predicates below are positional and terminal on purpose. Every existing
# tick predicate is satisfied by the file this issue was filed against: it
# ordered `radar:--state`, ordered bare `radar`, and carried all three of the
# heal's outcomes -- at the top. So "does this file order a heal" cannot
# separate the fixed file from the broken one, and only *where* can.
# --------------------------------------------------------------------------- #

#: The step that opens the pull request. `_heals_after_the_pull_request_is_opened`
#: anchors on it rather than on a heading, because a step number is renumbered by
#: any insertion above it and the op is not.
PR_CREATE_RE = re.compile(r"^\s*supertool\s+'gh-pr-create:", re.M)


def _heals_after_the_pull_request_is_opened(text):
    """A bare `radar` *after* the op that opens the pull request.

    Position is the whole finding. `_orders_the_bare_radar_heal` above is
    satisfied by the step-2 heal alone, which is exactly the file #242 reports.
    """
    opened = PR_CREATE_RE.search(text)
    if not opened:
        return False
    return any(m.start() > opened.end() for m in BARE_RADAR_RE.finditer(text))


def _states_the_membership_rule_rather_than_a_list(text):
    """A rule about when membership changed, said to be a rule.

    A list of heal sites is easier to follow and rots as steps are added -- and
    it was already one entry long and already wrong. The file has to say which
    of the two it is, because a reader who cannot tell will treat the examples
    as the whole set.
    """
    return bool(re.search(r"changed what is open", text, re.I)) and bool(
        re.search(r"not a list of places", text, re.I)
    )


def _says_the_default_branch_has_no_poller_to_heal(text):
    """The fact that decides rule-versus-list, rather than a preference.

    Radar carries the default branch as a member row composed from `gh-branch`'s
    four states; `N watched` never counts it. So the red-default-branch case has
    nothing to arm, and no list of heal sites can ever cover it -- only reading
    the board again does.
    """
    return bool(re.search(r"no poller to heal", text, re.I)) and bool(
        re.search(r"`N watched` never counts it", text)
    )


def _ends_the_tick_on_the_boards_own_coverage_tokens(text):
    """The terminal measurement that keeps the rule from being skippable.

    Deliberately radar's own rendered tokens rather than a paraphrase: the board
    already prints all three states, so a tick that re-reads it computes nothing.
    A predicate keyed on prose about coverage would pass on a file that describes
    the check and names nothing a reader could match against the output.
    """
    return "[unwatched]" in text and "watch coverage UNKNOWN" in text


# The skill has to state its own authority (#185).
#
# `skills/manager/SKILL.md` said what to decide and how to evidence it, and never
# who decides. The omission has a direction: every ambiguity resolves toward
# stopping and asking, and three distinct stalls were observed in one day --
# asking a question the repository already answered, waiting for approval that
# the invocation already was, and deferring available work to a later tick.
#
# So the predicates below require the *boundary*, not a mood. A file can be full
# of decisive-sounding prose and still leave a reader unable to say which acts
# are theirs, which is why every fact here names something enumerable: the undo
# test, both sides of the list, the sentence that replaces "ask", the bound on
# when a question is right, and the third state.
#
# PROPOSING below is a control in its own right, for the same reason CAUTIONING
# is one above. SILENT never says "merge" or "maintainer" at all, so every
# predicate fails it for the wrong reason -- and the file this issue is about was
# not silent, it was decisive-sounding and unbounded.
# --------------------------------------------------------------------------- #


def _states_the_loop_decides_rather_than_proposes(text):
    return bool(re.search(r"decides and acts; it does not propose", text)) and bool(
        re.search(r"[Bb]eing invoked is the authority", text)
    )


def _names_the_undo_test(text):
    """Not "reversible" -- that rule mis-sorts a squash merge and an issue close."""
    return bool(re.search(r"who has to be involved to undo it", text, re.I)) and bool(
        re.search(r"reversible versus irreversible.{0,40}wrong one", text, re.I)
    )


def _forbids_a_direct_push_to_main_with_no_exception(text):
    """#976: a `git revert` being available does not make a direct, unreviewed
    push to the default branch the loop's own call -- and no content is exempt,
    `trap.d/` fragments included."""
    return bool(
        re.search(
            r"[Cc]ommitting anything to the default branch outside a pull request", text
        )
    ) and bool(re.search(r"no content exception, `trap\.d/` fragments included", text))


#: Acts the loop takes without asking, and acts it stops for. A principle without
#: a list is where the stalling comes back, so the list is what gets asserted.
ACTS_THE_LOOP_TAKES = ("merging on green", "closing and reopening", "reaping worktrees")
ACTS_THAT_STOP = (
    "Tagging a release",
    "Publishing a release object",
    "Force-pushing",
    "embargo path",
)


#: The two lead-ins that carry the polarity. Each act is required in the half its
#: own lead-in introduces, and required absent from the other.
LOOP_LIST_LEAD = "**The loop's, and it asks about none of them:**"
STOP_LIST_LEAD = "**Stops, and names which of these it is:**"


def _enumerates_both_sides_of_the_boundary(text):
    """Both lists, and every act on the side its lead-in claims.

    A membership test over the whole file was the first spelling and it was wrong:
    it passes on prose naming every act and putting each on the wrong side, which
    is not a hypothetical shape -- it is what this file becomes if the boundary is
    later edited the wrong way round, and it is indistinguishable from the correct
    file to any check that only asks whether the words are present. REVERSED_BOUNDARY
    below is that file, and it is a control rather than an illustration.
    """
    if LOOP_LIST_LEAD not in text or STOP_LIST_LEAD not in text:
        return False
    ours = text.split(LOOP_LIST_LEAD, 1)[1].split(STOP_LIST_LEAD, 1)[0]
    theirs = text.split(STOP_LIST_LEAD, 1)[1]
    return all(
        act in ours and act not in theirs for act in ACTS_THE_LOOP_TAKES
    ) and all(act in theirs and act not in ours for act in ACTS_THAT_STOP)


def _says_a_gate_is_not_a_question(text):
    """The constraint that keeps this from becoming a licence to skip gates."""
    return bool(re.search(r"gate the loop performs on itself", text)) and bool(
        re.search(r"stops it .{0,30}without asking", text, re.I)
    )


def _says_deciding_replaces_asking(text):
    return bool(
        re.search(r"Decide, state the assumption, act, and report it prominently", text)
    ) and bool(re.search(r"different instruction from", text))


def _bounds_when_a_question_is_right(text):
    return (
        bool(re.search(r"genuinely not in the repository and the two branches", text))
        and "tag_pattern: null" in text
    )


def _says_deferring_is_a_stall(text):
    return bool(re.search(r"stall wearing a schedule", text, re.I)) and bool(
        re.search(r"deferring to the next tick is not a decision", text, re.I)
    )


def _says_undetermined_is_not_declined(text):
    """The third state, pointed at the loop's own authority."""
    return bool(
        re.search(r"could not determine whether this was mine to decide", text)
    ) and bool(re.search(r"must never render as", text, re.I))


def _names_the_readonly_watcher_probe(text):
    """A caution against assuming an op has to name the probe that answers it.

    Deliberately an *invocation*, not a mention. The caution already named
    `radar`; what the loop did with it was read the warning as permission to skip
    the reading entirely, so a "does this file say radar" predicate would certify
    exactly the state being fixed.
    """
    return bool(re.search(r"^\s*supertool\s+.*radar:--state", text, re.M))


def _points_at_the_managers_authority_clause(text):
    """The agent's boundary was written down and the maintainer's was not (#185).

    A pointer, deliberately, and not a copy: the list lives in one place for the
    same reason the ranking table does -- a second copy drifts, and the copy that
    drifts is the one quoted afterwards.
    """
    return "Who decides" in text and bool(
        re.search(r"the list lives there and is not copied here", text)
    )


# --------------------------------------------------------------------------- #
# Gate 1 is stated over an op that answers in three states (#229).
#
# `gh-branch` separates "declared and could not have run on this commit" from
# "declared, should have run, and did not". The gate's prose had room for only
# the second, so a `pull_request`-only workflow -- which structurally never runs
# on a push commit -- read the same as a workflow that was silently skipped.
# Both collapses are wrong: as `UNKNOWN` it blocks every release this repository
# will ever cut, and waved through it takes the blocking state with it.
#
# So the predicates below require all three arms to be present and separable.
# A file naming only two of them fails, and so does one that names the middle
# arm and grades it a pass.
# --------------------------------------------------------------------------- #


def _states_gate_one_in_three_states(text):
    return (
        bool(re.search(r"could not have run on this commit", text))
        and bool(re.search(r"should have run, and did not", text))
        and "UNKNOWN" in text
        and bool(re.search(r"[Nn]ot a pass and", text))
        and bool(re.search(r"not a blocker", text))
    )


def _says_the_middle_state_adds_no_coverage(text):
    """Not a blocker is not the same as covered.

    The arm most likely to be written carelessly: "not a blocker" reads as
    "fine", and a commit whose every declared workflow lands here would then be
    green over zero workflows -- the gate counting nothing and reporting a pass,
    which is the failure the workflow-not-run rule exists for in the first place.
    """
    return bool(re.search(r"contributes no coverage", text)) and bool(
        re.search(r"uncovered, not green", text)
    )


def _requires_the_report_to_name_the_middle_state(text):
    return bool(
        re.search(r"[Nn]ame the middle state in the release report", text)
    ) and bool(re.search(r"where its coverage did come from", text))


def _forbids_remembering_the_trigger_verdict(text):
    """The middle state is a measurement of an `on:` block, so it can go stale.

    A workflow that gains a `push:` trigger moves from the middle arm to the
    blocking one with nothing announcing it, so a verdict carried forward from
    the last release waves through the exact case the gate exists for.
    """
    return bool(
        re.search(r"[Rr]e-read it from the op on every release", text)
    ) and bool(re.search(r"never carry the verdict forward", text))


def _reads_the_branch_op_in_three_states(text):
    return (
        bool(re.search(r"could not have run on this commit", text))
        and bool(re.search(r"should have run, and did not", text))
        and bool(re.search(r"contributes no coverage", text))
    )


def _reads_the_third_state_at_the_merge_check_too(text):
    """Same op, same third state, one step earlier in the loop.

    #229 was filed against the release gate, but the op prints the same line
    after every squash merge -- and there the middle arm is routinely misread as
    the default branch having gone red.
    """
    return bool(re.search(r"could not have run on the squash commit", text)) and bool(
        re.search(r"misread as a red default branch", text)
    )


# --------------------------------------------------------------------------- #
# The compatibility field is sourced where it is used (#225).
#
# `commands/release.md` claimed the bullet is "documented in
# `changelog.d/README.md`". True of this repository's copy and false of the file
# scaffold writes -- and the fragments README is a *default* under the ownership
# contract, created once and then the repo's own forever, so shared prose cannot
# know what it says. The path was wrong twice over: `changelog_dir` is per-repo,
# so `changelog.d` is a fact about this repository sitting in shared prose.
#
# Hence the negative half. Its positive control is PROMISING below, which
# satisfies both positive clauses and fails on the hardcoded path alone.
# --------------------------------------------------------------------------- #

FRAGMENTS_README_PATH_RE = re.compile(r"changelog[.]d/README[.]md")
COMPATIBILITY_BULLET = "- Compatibility: breaking|compatible - <reason>"


def _sources_the_compatibility_syntax_without_promising_a_readme(text):
    if FRAGMENTS_README_PATH_RE.search(text):
        return False
    return COMPATIBILITY_BULLET in text and bool(
        re.search(r"may not document it at all", text)
    )


# (label, predicate, pattern whose lines carry the fact)
SETUP_FACTS = [
    (
        "identity.md describes the agent",
        _names_the_agent_as_identity_subject,
        r"who the agent is",
    ),
    (
        "an identity example is pointed at",
        _points_at_an_identity_example,
        r"identity\.example\.md",
    ),
    (
        "scaffold is the next step",
        _names_scaffold_as_the_next_step,
        r"/oss:scaffold|tracked file",
    ),
    (
        "the merge rule's file is named",
        _names_the_settings_file_for_the_merge_rule,
        r"settings\.local\.json",
    ),
    (
        "both path spellings are covered",
        _covers_both_path_spellings,
        r"\./supertool|absolute path",
    ),
    (
        "the two merge strings differ",
        _says_the_two_merge_strings_differ,
        r"different .{0,40}string",
    ),
    (
        "the harness gate is the fourth",
        _says_the_harness_gate_is_a_fourth_one,
        r"fourth",
    ),
    ("the scaffold plan is run, not named", _runs_the_scaffold_plan, r"scaffold\.py"),
    (
        "a plan that could not run is not a failed setup",
        _says_a_failed_plan_is_not_a_failed_setup,
        r"could not plan|not a failed setup",
    ),
    (
        "the offline plan and the forge read are told apart",
        _separates_the_offline_plan_from_the_forge_read,
        r"read from the filesystem|only line that asks the forge",
    ),
]

SCAFFOLD_FACTS = [
    (
        "tick is the next step",
        _names_tick_as_the_next_step,
        r"/oss:tick|furniture is in place",
    ),
    (
        "the tick seam cannot be previewed",
        _says_the_tick_seam_cannot_be_previewed,
        r"cannot be previewed",
    ),
]

TICK_FACTS = [
    (
        "the watcher probe is run, not named",
        _orders_the_watcher_probe,
        r"radar:--state",
    ),
    (
        "an unread channel is not a quiet one",
        _says_an_unread_channel_is_not_a_quiet_one,
        r"not a quiet channel|forwarded is not delivered",
    ),
    (
        "the bare heal is run, not named",
        _orders_the_bare_radar_heal,
        r"supertool 'radar'",
    ),
    (
        "the bare run has its own three outcomes",
        _carries_the_bare_radar_outcomes,
        r"could not raise|must not be reported as a failure",
    ),
    (
        "the channel-ownership warning is relayed",
        _relays_the_channel_ownership_warning,
        r"watch_name|another project's fleet",
    ),
    (
        "an empty poller list is not an absent fleet",
        _says_an_empty_poller_list_is_not_an_absent_fleet,
        r"pollers\s*:\s*none|the second answer, not the first",
    ),
    (
        "the worktree board is run, not named",
        _orders_the_worktree_board,
        r"git-worktrees",
    ),
    (
        "the worktree verdicts are read in three states",
        _carries_the_three_state_worktree_rule,
        r"`cannot tell` is not `idle`|`merge unknown` is not `merged`",
    ),
    (
        "the heal follows the pull request it opened",
        _heals_after_the_pull_request_is_opened,
        r"supertool 'radar'|supertool 'gh-pr-create:",
    ),
    (
        "membership is the rule, not a list of places",
        _states_the_membership_rule_rather_than_a_list,
        r"changed what is open|not a list of places",
    ),
    (
        "the default branch has no poller to heal",
        _says_the_default_branch_has_no_poller_to_heal,
        r"no poller to heal|`N watched` never counts it",
    ),
    (
        "the tick ends on the board's own coverage tokens",
        _ends_the_tick_on_the_boards_own_coverage_tokens,
        r"\[unwatched\]|watch coverage UNKNOWN",
    ),
]

# The skill's statement of its own authority. Split out from SKILL_FACTS below
# only so the PROPOSING control can be parametrized over exactly these.
SKILL_AUTHORITY_FACTS = [
    (
        "the loop decides rather than proposes",
        _states_the_loop_decides_rather_than_proposes,
        r"decides and acts|invoked is the authority",
    ),
    (
        "the undo test is named, not reversibility",
        _names_the_undo_test,
        r"who has to be involved to undo it|reversible versus irreversible",
    ),
    (
        "both sides of the boundary are enumerated",
        _enumerates_both_sides_of_the_boundary,
        r"merging on green|Tagging a release",
    ),
    (
        "a gate is a check, not a question",
        _says_a_gate_is_not_a_question,
        r"performs on itself|without asking",
    ),
    (
        "deciding and reporting replaces asking",
        _says_deciding_replaces_asking,
        r"state the assumption, act|different instruction from",
    ),
    (
        "a question is bounded to what the repo does not answer",
        _bounds_when_a_question_is_right,
        r"genuinely not in the repository|tag_pattern: null",
    ),
    (
        "deferring to a later tick is a stall",
        _says_deferring_is_a_stall,
        r"stall wearing a schedule|deferring to the next tick is not a decision",
    ),
    (
        "undetermined authority is not a declined one",
        _says_undetermined_is_not_declined,
        r"could not determine whether this was mine to decide",
    ),
    (
        "a direct push to the default branch has no content exception",
        _forbids_a_direct_push_to_main_with_no_exception,
        r"Committing anything to the default branch outside a pull request|no content exception, `trap\.d/` fragments included",
    ),
]

# The caution against assuming a preset op has to name the probe that answers it.
SKILL_PROBE_FACTS = [
    (
        "the watcher probe is invoked, not just cautioned about",
        _names_the_readonly_watcher_probe,
        r"radar:--state",
    ),
]

# The skill states gate 1 and the post-merge branch check over the same op, so
# the same three states have to reach both (#229).
SKILL_GATE_FACTS = [
    (
        "the branch op is read in three states",
        _reads_the_branch_op_in_three_states,
        r"could not have run on this commit|contributes no coverage",
    ),
    (
        "the third state is read at the merge check too",
        _reads_the_third_state_at_the_merge_check_too,
        r"could not have run on the squash commit|misread as a red default branch",
    ),
]

SKILL_FACTS = SKILL_AUTHORITY_FACTS + SKILL_PROBE_FACTS + SKILL_GATE_FACTS

DEVELOPER_FACTS = [
    (
        "the manager's own authority clause is pointed at",
        _points_at_the_managers_authority_clause,
        r"Who decides|the list lives there and is not copied here",
    ),
]

README_FACTS = [
    (
        "scaffold is in the launcher path",
        _names_scaffold_as_the_next_step,
        r"/oss:scaffold|tracked file",
    ),
]

RELEASE_FACTS = [
    (
        "a denied call is none of the publisher's three verdicts",
        _says_a_denial_is_not_one_of_the_three,
        r"\bdenied\b|has no exit code",
    ),
    (
        "a denied call is not reworded past the classifier",
        _forbids_evading_a_denied_call,
        r"do not reword|classifier relents",
    ),
    (
        "a denied release says where it stopped",
        _says_where_a_denied_release_resumes,
        r"where a denied release resumes|never reports as released",
    ),
]

# Gate 1 in three states, and the compatibility field sourced where it is used.
RELEASE_GATE_FACTS = [
    (
        "gate 1 is stated in three states",
        _states_gate_one_in_three_states,
        r"could not have run on this commit|should have run, and did not",
    ),
    (
        "the middle state contributes no coverage",
        _says_the_middle_state_adds_no_coverage,
        r"contributes no coverage|uncovered, not green",
    ),
    (
        "the release report names the middle state",
        _requires_the_report_to_name_the_middle_state,
        r"[Nn]ame the middle state in the release report",
    ),
    (
        "the trigger verdict is re-read, never remembered",
        _forbids_remembering_the_trigger_verdict,
        r"never carry the verdict forward",
    ),
    (
        "the compatibility syntax is sourced, not pointed at",
        _sources_the_compatibility_syntax_without_promising_a_readme,
        r"may not document it at all|Compatibility: breaking",
    ),
]

RELEASE_FACTS = RELEASE_FACTS + RELEASE_GATE_FACTS

ALL_FACTS = (
    SETUP_FACTS
    + SCAFFOLD_FACTS
    + TICK_FACTS
    + SKILL_FACTS
    + DEVELOPER_FACTS
    + README_FACTS
    + RELEASE_FACTS
)

# (file, label, predicate, pattern whose lines carry the fact) for every carried fact,
# so a new surface joins both the real-file assertion and its deletion control at once.
CARRIED = (
    [(SETUP_MD,) + fact for fact in SETUP_FACTS]
    + [(SCAFFOLD_MD,) + fact for fact in SCAFFOLD_FACTS]
    + [(TICK_MD,) + fact for fact in TICK_FACTS]
    + [(SKILL_MD,) + fact for fact in SKILL_FACTS]
    + [(DEVELOPER_MD,) + fact for fact in DEVELOPER_FACTS]
    + [(INSTALL_DOC,) + fact for fact in README_FACTS]
    + [(RELEASE_MD,) + fact for fact in RELEASE_FACTS]
)
CARRIED_IDS = ["{}: {}".format(entry[0].name, entry[1]) for entry in CARRIED]


@pytest.mark.parametrize("path,label,predicate,_pattern", CARRIED, ids=CARRIED_IDS)
def test_the_surface_carries_the_fact(path, label, predicate, _pattern):
    assert predicate(path.read_text(encoding="utf-8")), "{}: {}".format(
        path.name, label
    )


@pytest.mark.parametrize(
    "label,predicate,_pattern", ALL_FACTS, ids=[f[0] for f in ALL_FACTS]
)
def test_a_silent_file_fails_every_prose_predicate(label, predicate, _pattern):
    """The negative control. Without it, every assertion above also passes on a
    file that says nothing about the subject at all."""
    assert not predicate(SILENT), (
        "{}: predicate passes on a file that says nothing".format(label)
    )


# A file that names both ops -- and only to warn about them. SILENT cannot catch
# the confusion #187 was actually made of, because SILENT never says "radar" at
# all: every "does the file mention radar" predicate fails it for the wrong
# reason. This fixture is the caution the loop misread as an instruction.
CAUTIONING = (
    "# Tick\n"
    "\n"
    "Read the board.\n"
    "\n"
    "Do not assume ops that a repo's `.supertool.json` does not declare. `radar` and\n"
    "`dashboard` live behind presets many repos never enable; check before writing an\n"
    "instruction that depends on one. `git-worktrees` boards every tree with an\n"
    "occupancy verdict, and the raw `git worktree` listing is refused.\n"
)


def test_the_cautioning_fixture_actually_names_both_ops():
    """The positive control for the control below. A fixture that stopped naming
    the ops would make the next test pass for the same reason SILENT does, and the
    discrimination it exists to prove would go untested while still reporting green.
    """
    assert "radar" in CAUTIONING
    assert "git-worktrees" in CAUTIONING


@pytest.mark.parametrize(
    "label,predicate,_pattern", TICK_FACTS, ids=[f[0] for f in TICK_FACTS]
)
def test_a_cautioning_file_fails_every_tick_predicate(label, predicate, _pattern):
    """Mentioning an op is not ordering it. `skills/manager/SKILL.md` cautions
    against assuming `radar`, correctly, and the loop read that as licence to skip
    the reading entirely -- so a predicate satisfied by a caution would certify the
    exact state #187 reports as fixed."""
    assert not predicate(CAUTIONING), (
        "{}: predicate passes on a file that only cautions about the op. "
        "A mention is not an instruction.".format(label)
    )


# A file that reads exactly as #185 describes: it names merging, releasing and the
# maintainer, sounds decisive about the work, and leaves the reader unable to say
# which acts are the loop's. SILENT cannot catch that, because SILENT never says
# "merge" or "maintainer" at all -- every authority predicate fails it for the
# wrong reason. This fixture is the file the issue was filed against.
PROPOSING = (
    "# Manager\n"
    "\n"
    "Read the board, decide what is worth building, delegate it, review it hard.\n"
    "\n"
    "Check with the maintainer before merging anything, and a release is theirs to\n"
    "approve. Where a call is not obvious, stop and ask -- the maintainer decides,\n"
    "and there is always the next tick.\n"
)

# The same shape one level down: the caution that names an op and no probe for it.
PROBELESS_CAUTION = (
    "Do not assume ops that a repo's `.supertool.json` does not declare. `radar` and\n"
    "`dashboard` live behind presets many repos never enable; check before writing an\n"
    "instruction that depends on one.\n"
)


# Every act named, and each one under the lead-in for the other side. This is not
# a silent file and not a vague one -- it is the file that results from editing the
# boundary the wrong way round, and a predicate that only asks whether the words
# appear cannot tell it from the real one.
REVERSED_BOUNDARY = (
    "## Who decides\n"
    "\n"
    "**The loop's, and it asks about none of them:** Tagging a release,\n"
    "Publishing a release object, Force-pushing a shared branch, the embargo path.\n"
    "\n"
    "**Stops, and names which of these it is:**\n"
    "\n"
    "| Stop | Why |\n"
    "| --- | --- |\n"
    "| **merging on green** | somebody ought to look at it first |\n"
    "| **closing and reopening** an issue | the maintainer's call |\n"
    "| **reaping worktrees** | ask before removing anything |\n"
)


def test_a_boundary_stated_the_wrong_way_round_is_caught():
    """The must-fire half for the one predicate whose subject is a *list*.

    Two assertions before the discrimination, because both of the ways this test
    can go quietly useless are invisible from its result:

    - the fixture might stop naming the acts, which is what a typo in it produces,
      and then the predicate fails it for the same reason it fails SILENT;
    - the fixture might not actually be adversarial, and a control that the
      superseded predicate ALSO rejected proves nothing about what replaced it.
      So the superseded spelling is written out here and asserted to pass on it.
    """
    for act in ACTS_THE_LOOP_TAKES + ACTS_THAT_STOP:
        assert act in REVERSED_BOUNDARY, act

    membership_only = all(
        act in REVERSED_BOUNDARY for act in ACTS_THE_LOOP_TAKES
    ) and all(act in REVERSED_BOUNDARY for act in ACTS_THAT_STOP)
    assert membership_only, "the fixture is not the one the old predicate accepted"

    assert not _enumerates_both_sides_of_the_boundary(REVERSED_BOUNDARY)
    # And the must-not-fire half, against the file that has it the right way round.
    assert _enumerates_both_sides_of_the_boundary(SKILL_MD.read_text(encoding="utf-8"))


def test_the_authority_controls_actually_name_their_subjects():
    """The positive control for the two controls below.

    A fixture that stopped naming its subject would make the tests under it pass
    for the same reason SILENT does, and the discrimination they exist to prove
    would go untested while still reporting green.
    """
    for term in ("merging", "maintainer", "release", "next tick"):
        assert term in PROPOSING, term
    assert "radar" in PROBELESS_CAUTION
    # And the deletion patterns are not vacuous: each must select at least one
    # line of the real file, or `test_deleting_the_carrying_lines_fails_the_predicate`
    # deletes nothing, asserts against an unmodified file, and passes on a fact the
    # surface never carried. Counted in LINES, not compared as strings: the first
    # spelling of this guard was `_without_lines_matching(text, pattern) != text`,
    # which is true of every file ending in a newline whatever the pattern selects,
    # because the join drops it -- a guard that could not fail, in the test written
    # to stop a guard that could not fail.
    for path, label, _predicate, pattern in CARRIED:
        text = path.read_text(encoding="utf-8")
        kept = _without_lines_matching(text, pattern)
        assert len(kept.splitlines()) < len(text.splitlines()), (
            "{}: {}: the pattern {!r} selects no line of the file, so its deletion "
            "control deletes nothing".format(path.name, label, pattern)
        )


@pytest.mark.parametrize(
    "label,predicate,_pattern",
    SKILL_AUTHORITY_FACTS,
    ids=[f[0] for f in SKILL_AUTHORITY_FACTS],
)
def test_a_proposing_file_fails_every_authority_predicate(label, predicate, _pattern):
    """Sounding decisive is not stating a boundary.

    Every stall #185 records was produced by a file full of confident prose that
    never said who decides, so a predicate satisfied by confident prose would
    certify the exact state being reported as fixed.
    """
    assert not predicate(PROPOSING), (
        "{}: predicate passes on a file that only sounds decisive and still "
        "defers every call to the maintainer.".format(label)
    )


def test_a_cautioning_file_fails_the_probe_predicate():
    """Mentioning an op is not naming the probe that answers whether it is there.

    The skill cautioned against assuming `radar`, correctly, and that caution was
    read as licence to skip the reading entirely -- so a predicate satisfied by
    the caution would certify the state this fix exists to change.
    """
    assert not _names_the_readonly_watcher_probe(PROBELESS_CAUTION)
    # The must-fire half, same fixture: with the probe invocation present it does.
    assert _names_the_readonly_watcher_probe(
        PROBELESS_CAUTION + "\n```bash\nsupertool 'radar:--state'\n```\n"
    )


# A file that names every subject of RELEASE_FACTS and settles none of them.
# SILENT cannot catch what #186 was made of: the old release.md was not silent
# about permissions, it was *adjacent* to them -- it ran the publisher and read
# its exit codes, while having no answer for a call that never reached the
# publisher at all. A predicate satisfied by a file that merely names the
# subject would certify exactly that state.
NARRATING = (
    "# Release\n"
    "\n"
    "Gates first, then the tag.\n"
    "\n"
    "The harness classifier is not stable and a call can come back denied. That is\n"
    "worth knowing before you push a tag. `release_publish.py` reports created,\n"
    "skipped or could-not-create, and the report says which one.\n"
)


def test_the_narrating_fixture_actually_names_every_release_subject():
    """The positive control for the control below. A fixture that stopped naming
    the subjects would make the next test pass for the same reason SILENT does,
    and the discrimination it exists to prove would go untested while reporting
    green."""
    for subject in ("denied", "classifier", "could-not-create", "report"):
        assert subject in NARRATING, subject


@pytest.mark.parametrize(
    "label,predicate,_pattern", RELEASE_FACTS, ids=[f[0] for f in RELEASE_FACTS]
)
def test_a_narrating_file_fails_every_release_predicate(label, predicate, _pattern):
    assert not predicate(NARRATING), (
        "{}: predicate passes on a file that names the subject and decides nothing. "
        "Naming the fragments is not sourcing the number, and knowing that denials "
        "happen is not having an answer for one.".format(label)
    )


# --------------------------------------------------------------------------- #
# Controls for the three-state gate (#229) and the sourced field (#225).
#
# SILENT and NARRATING cannot catch either one. The gate's old sentence was not
# silent about workflows -- it was *precise* about two of the three states, and
# a "does this file discuss workflows that did not run" predicate passes on it
# word for word. So the control is the superseded sentence itself, quoted.
# --------------------------------------------------------------------------- #

# Gate 1 exactly as it stood before #229: correct, and two states wide.
TWO_STATE_GATE = (
    "# Release\n"
    "\n"
    "1. **The default branch is green at leg level for the exact commit being tagged.**\n"
    "   Count the *workflows*, not the runs — one declared in `.github/workflows/` but\n"
    "   absent from the run list is `UNKNOWN`, never a pass. `supertool 'gh-branch'`,\n"
    "   which is conjunctive over every workflow on the head SHA.\n"
)

# The other collapse, and the one a maintainer in a hurry actually writes: the
# middle state named, and graded a pass. This fixture reaches the middle arm's
# own words, so a predicate that merely greps for them passes here and the
# three-state claim goes untested while reporting green.
WAVED_THROUGH = (
    "# Release\n"
    "\n"
    "1. **The default branch is green at leg level for the exact commit being tagged.**\n"
    "   `supertool 'gh-branch'`. A workflow with no push trigger\n"
    "   could not have run on this commit, so it is not `UNKNOWN` and the gate\n"
    "   passes over it.\n"
)

# #225's line, quoted, plus the sentence the fix adds. Everything the positive
# half of the predicate asks for is here -- the bullet in full and the warning
# that an older repo may not carry it -- so the ONLY thing this fixture fails on
# is the hardcoded README path. Without it the negative half never fires and
# nothing distinguishes the fix from the defect.
PROMISING = (
    "# Release\n"
    "\n"
    "The verdict is a declared field on the fragment,\n"
    "`- Compatibility: breaking|compatible - <reason>`, documented in `changelog.d/README.md`.\n"
    "Required on `removed`. A repo scaffolded earlier may not document it at all.\n"
)

GATE_CONTROL_FACTS = RELEASE_GATE_FACTS + SKILL_GATE_FACTS


def test_the_gate_controls_actually_name_their_subjects():
    """The positive control for the three controls below.

    Each fixture has to reach the words its predicate looks for, or the tests
    under it pass for the same reason SILENT does and prove nothing.
    """
    for subject in ("UNKNOWN", "gh-branch", "workflows", "run list"):
        assert subject in TWO_STATE_GATE, subject
    assert "could not have run on this commit" in WAVED_THROUGH
    assert COMPATIBILITY_BULLET in PROMISING
    assert "may not document it at all" in PROMISING


@pytest.mark.parametrize(
    "label,predicate,_pattern",
    GATE_CONTROL_FACTS,
    ids=[f[0] for f in GATE_CONTROL_FACTS],
)
def test_the_superseded_two_state_gate_fails_every_gate_predicate(
    label, predicate, _pattern
):
    """Precise about two states is what the defect looked like.

    A predicate satisfied by the sentence #229 was filed against would certify
    exactly the state being fixed.
    """
    assert not predicate(TWO_STATE_GATE), (
        "{}: predicate passes on the two-state sentence #229 was filed against.".format(
            label
        )
    )


@pytest.mark.parametrize(
    "label,predicate,_pattern",
    GATE_CONTROL_FACTS,
    ids=[f[0] for f in GATE_CONTROL_FACTS],
)
def test_a_waved_through_middle_state_fails_every_gate_predicate(
    label, predicate, _pattern
):
    """Naming the middle state is not separating it.

    The other half of the discrimination: this fixture says the middle arm's own
    words and then grades it a pass, which is the second of the two wrong
    collapses and the one no keyword search can tell from the fix.
    """
    assert not predicate(WAVED_THROUGH), (
        "{}: predicate passes on a file that names the middle state and grades "
        "it a pass.".format(label)
    )


def test_pointing_at_a_repos_own_readme_fails_the_compatibility_predicate():
    """The must-fire half of a negative assertion (#225).

    `_sources_the_compatibility_syntax_without_promising_a_readme` refuses a
    hardcoded fragments README path. Refusal is invisible from a green suite, so
    the fixture is built to satisfy everything else and fail on that alone.
    """
    assert not _sources_the_compatibility_syntax_without_promising_a_readme(PROMISING)
    # And the must-not-fire half, same fixture with the path taken out.
    without_the_path = PROMISING.replace(", documented in `changelog.d/README.md`", "")
    assert not FRAGMENTS_README_PATH_RE.search(without_the_path)
    assert _sources_the_compatibility_syntax_without_promising_a_readme(
        without_the_path
    )


# --------------------------------------------------------------------------- #
# The chain, not its edges.
#
# Each command doc is correct about itself. What nothing checked is that a
# maintainer following one surface end to end arrives where a maintainer
# following another one does: setup names scaffold, scaffold names tick. An
# edge asserted on its own passes while the chain still stops one link short.
# --------------------------------------------------------------------------- #

# (this command, its doc, the command it must hand off to, the predicate for that)
CHAIN = [
    ("/oss:setup", SETUP_MD, "/oss:scaffold", _names_scaffold_as_the_next_step),
    ("/oss:scaffold", SCAFFOLD_MD, "/oss:tick", _names_tick_as_the_next_step),
    # A second entry point rather than a third link -- #957. A reopened session runs
    # /oss:doctor, not /oss:scaffold, and has no furniture step to name; it hands off
    # to /oss:tick directly, worded for that path rather than reusing the scaffold
    # predicate above.
    (
        "/oss:doctor",
        DOCTOR_MD,
        "/oss:tick",
        _names_tick_as_the_reopened_session_next_step,
    ),
]


def _broken_links(texts):
    """Which links do not hand off. `texts` maps a command to the prose of its doc."""
    return [
        "{} does not name {} as the next step".format(source, target)
        for source, _path, target, predicate in CHAIN
        if not predicate(texts[source])
    ]


def _chain_texts():
    return {
        source: path.read_text(encoding="utf-8") for source, path, _target, _p in CHAIN
    }


def test_the_chain_is_wired_end_to_end():
    assert CHAIN, "no chain links declared -- this test would pass on an empty list"
    broken = _broken_links(_chain_texts())
    assert not broken, (
        "the documented path stops short:\n  "
        + "\n  ".join(broken)
        + "\nEach doc being correct about itself is what makes this invisible."
    )


def test_a_chain_with_a_missing_link_is_caught():
    """The positive control for the detector above, in the same fixture set. Its
    assertion also passes when `_broken_links` can never report anything -- so the
    reporting half is shown firing, both on a wholly silent chain and on a real one
    with exactly one link removed."""
    assert len(_broken_links({source: SILENT for source, *_ in CHAIN})) == len(CHAIN)

    partial = _chain_texts()
    partial["/oss:scaffold"] = SILENT
    assert _broken_links(partial) == [
        "/oss:scaffold does not name /oss:tick as the next step"
    ]


# A count of agents written out in prose is a fact about the filesystem, duplicated.
# It went stale silently the moment a third agent was drafted, and nothing failed --
# README said "two agents" and "both agents" while the tree was about to hold three.
# Either state the count and have it checked, or do not state one.
AGENT_COUNT_RE = re.compile(r"\b(one|two|three|four|five|both|\d+)\s+agents\b", re.I)
COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def _stated_agent_counts(text):
    """Every agent count the prose commits to, as integers. `both` means two."""
    counts = []
    for match in AGENT_COUNT_RE.finditer(text):
        word = match.group(1).lower()
        if word == "both":
            counts.append(2)
        elif word in COUNT_WORDS:
            counts.append(COUNT_WORDS[word])
        else:
            counts.append(int(word))
    return counts


def test_the_agent_count_detector_reads_words_and_digits():
    """The detector before the assertion that leans on it. A regex matching nothing
    would turn the check below into a check that never looked."""
    assert _stated_agent_counts(
        "one skill, two agents and both agents, plus 3 agents"
    ) == [2, 2, 3]
    assert _stated_agent_counts("the loop, its agents, the config layer") == []


def test_readme_states_no_agent_count_that_disagrees_with_the_tree():
    """Not "README must say three". A count is optional -- and when it is absent this
    test is deliberately quiet, because the drift-proof prose is the one that does not
    duplicate the filesystem. What is forbidden is stating a number that is wrong.
    """
    actual = len(sorted((REPO_ROOT / "agents").glob("*.md")))
    assert actual, "no agents/*.md found -- this check would compare against zero"
    stated = _stated_agent_counts(README_MD.read_text(encoding="utf-8"))
    wrong = [count for count in stated if count != actual]
    assert not wrong, (
        "README.md commits to {} agent(s) while agents/ holds {}. Either fix the "
        "number or drop it -- a count in prose is a fact about the filesystem, "
        "duplicated, and it goes stale without anything failing.".format(wrong, actual)
    )


def test_a_disagreeing_count_is_actually_caught():
    """The positive control for the test above. Its own assertion passes when README
    states no count at all, which is also what a broken detector produces -- so the
    catching half has to be shown firing on a fixture that does disagree."""
    stated = _stated_agent_counts("This packages the loop once: one skill, two agents.")
    assert [count for count in stated if count != 3] == [2]


# --------------------------------------------------------------------------- #
# The assembler is never invoked on a root it had to guess.
#
# `assemble_changelog.py` resolves its default root by walking up from its own
# location for a `.git`. Under a plugin that walk lands in the *plugin's* own
# repository, not the one the maintainer is standing in -- so a fold with no
# `--dir`/`--changelog` rewrites the wrong CHANGELOG.md and deletes the wrong
# fragments, confidently, under a receipt that says it worked.
#
# commands/changelog.md stated that rule four lines above a fold command that
# broke it (#65). Prose stating a rule does not enforce it; this does.
#
# The rule is deliberately every mode, not just `--version`. Mode parsing is one
# more thing to get wrong, and a `--check` against the wrong tree is also an
# answer about a repository nobody asked about.
#
# The surfaces swept are the ones that invoke the PLUGIN'S copy. `changelog.d/
# README.md` is deliberately outside it: it invokes this repo's own
# `scripts/assemble_changelog.py` from this repo's root, where the `.git` walk
# lands exactly where it should, so widening the sweep to it would fail a
# correct file. What makes the sweep safe over `commands/` is
# `test_commands_use_the_plugin_root_variable_for_scripts` above, which already
# forces every invocation there through `${CLAUDE_PLUGIN_ROOT}`.
#
# The scan is line-based. A bash line continuation putting the flags on the next
# line would be reported as missing them -- a false alarm, which is the
# direction to fail in, but rewrite this rather than dropping the flags.
# --------------------------------------------------------------------------- #

ASSEMBLER_LINE_RE = re.compile(r"^\s*(?:python3?|py)\s+\S*assemble_changelog\.py\b.*$")

REQUIRED_ASSEMBLER_FLAGS = ("--dir", "--changelog")


def _assembler_invocations(text):
    """Every `assemble_changelog.py` command line in *text*, as (line number, line)."""
    return [
        (number, line.strip())
        for number, line in enumerate(text.splitlines(), 1)
        if ASSEMBLER_LINE_RE.match(line)
    ]


def _missing_assembler_flags(line):
    """Which required flags this command line does not actually pass.

    Tokenised, not substring-matched. `--version X.Y.Z  # pass --dir and
    --changelog` contains both spellings and passes neither, and a guard that
    reads the comment as compliance is a guard that can be talked out of firing.

    A line that will not tokenise is its own finding, never a pass: an argument
    list nobody could read is not an argument list that was checked.
    """
    try:
        tokens = shlex.split(line, comments=True)
    except ValueError as error:
        return ["unparseable arguments ({})".format(error)]
    return [
        flag
        for flag in REQUIRED_ASSEMBLER_FLAGS
        if not any(token == flag or token.startswith(flag + "=") for token in tokens)
    ]


def _rootless_assembler_invocations(name, text):
    """Which of those invocations leave the assembler to guess its root."""
    offenders = []
    for number, line in _assembler_invocations(text):
        missing = _missing_assembler_flags(line)
        if missing:
            offenders.append(
                "{}:{}: missing {}: {}".format(
                    name, number, " and ".join(missing), line
                )
            )
    return offenders


def test_the_assembler_detector_sees_an_invocation_and_its_flags():
    """The detector before the assertion that leans on it. A regex matching nothing
    turns the sweep below into a sweep that never looked, and a flag check that never
    fires turns it into one that looked and could not report."""
    good = 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/assemble_changelog.py" --check --dir d --changelog CHANGELOG.md'
    bad = (
        'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/assemble_changelog.py" --version X.Y.Z'
    )
    assert len(_assembler_invocations(good + "\n" + bad)) == 2
    assert (
        _assembler_invocations("this paragraph mentions assemble_changelog.py in prose")
        == []
    )

    # The must-fire half: the flagless fold is reported, and located.
    offenders = _rootless_assembler_invocations("fixture.md", good + "\n" + bad)
    assert len(offenders) == 1, offenders
    assert offenders[0].startswith("fixture.md:2: missing --dir and --changelog: ")

    # The must-not-fire half, in the same fixture. Without it a detector that
    # flagged every line would still pass the assertion above.
    assert _rootless_assembler_invocations("fixture.md", good) == []

    # A comment naming both flags is not passing both flags.
    talked_out_of_it = bad + "  # yes, this one wants --dir and --changelog too"
    assert _missing_assembler_flags(talked_out_of_it) == ["--dir", "--changelog"]

    # `--dir=X` is passing --dir.
    assert (
        _missing_assembler_flags(
            "python3 a/assemble_changelog.py --version 1.0.0 --dir=d --changelog=CHANGELOG.md"
        )
        == []
    )

    # The third state. An argument list that would not tokenise is reported, not
    # waved through -- a line nobody could read has not been checked.
    unreadable = _missing_assembler_flags(
        'python3 a/assemble_changelog.py --dir "unclosed'
    )
    assert len(unreadable) == 1 and unreadable[0].startswith("unparseable arguments ")


def test_every_documented_assembler_invocation_passes_dir_and_changelog():
    surfaces = COMMANDS + [REPO_ROOT / "skills" / "manager" / "SKILL.md", README_MD]
    seen = 0
    offenders = []
    for path in surfaces:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        seen += len(_assembler_invocations(text))
        offenders += _rootless_assembler_invocations(path.name, text)

    assert seen, (
        "no assemble_changelog.py invocation found in commands/, skills/ or README.md. "
        "Either the surfaces stopped documenting it, or ASSEMBLER_LINE_RE no longer "
        "matches how they are written -- a pattern that matched nothing has checked nothing."
    )
    assert not offenders, (
        "these invocations leave the assembler to guess its root, which under a plugin "
        "is the plugin's own repository:\n  " + "\n  ".join(offenders)
    )


def test_the_scaffold_detector_sees_an_invocation_and_its_flags():
    """The detector before the two assertions that lean on it. A regex matching
    nothing turns both into checks that never looked, and a flag test that never
    fires turns the write-boundary sweep into one that looked and could not
    report."""
    plan = 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scaffold.py" --root . --config .oss.json'
    write = plan + " --apply"

    assert len(_scaffold_invocations(plan + "\n" + write)) == 2
    assert _scaffold_invocations("this paragraph mentions scaffold.py in prose") == []

    # The must-fire half: the writing invocation is reported, and located.
    offenders = _writing_scaffold_invocations("fixture.md", plan + "\n" + write)
    assert len(offenders) == 1, offenders
    assert offenders[0].startswith("fixture.md:2: passes --apply: ")

    # The must-not-fire half, in the same fixture. Without it a detector that
    # flagged every line would still pass the assertion above.
    assert _writing_scaffold_invocations("fixture.md", plan) == []

    # A comment naming the flag is not passing the flag.
    assert (
        _writing_scaffold_invocations("fixture.md", plan + "  # never --apply here")
        == []
    )

    # The third state. An argument list that would not tokenise is reported, not
    # waved through -- a line nobody could read has not been checked.
    unreadable = _writing_scaffold_invocations(
        "fixture.md", 'python3 a/scaffold.py --config "unclosed'
    )
    assert len(unreadable) == 1 and "unparseable arguments" in unreadable[0]

    # And the fact predicate reads that detector the right way round.
    assert _runs_the_scaffold_plan(plan)
    assert not _runs_the_scaffold_plan(write)
    assert not _runs_the_scaffold_plan("no invocation at all")


def test_setup_never_documents_a_writing_scaffold_invocation():
    """The write boundary, as a test rather than a paragraph. `/oss:setup` writes
    one untracked local file and nothing tracked, which is what makes it safe to
    run anywhere; the moment its prose carries `--apply`, a first run commits
    opinions into somebody's repository.

    The `seen` assertion is this test's positive control -- a sweep over zero
    invocations reports no offenders and reads exactly like a clean one. The
    reporting half is shown firing in the detector test above.
    """
    text = SETUP_MD.read_text(encoding="utf-8")
    seen = _scaffold_invocations(text)
    assert seen, (
        "commands/setup.md documents no scaffold.py invocation. Either setup stopped "
        "running the plan -- which is #136 reopening -- or SCAFFOLD_LINE_RE no longer "
        "matches how it is written; a pattern that matched nothing has checked nothing."
    )
    offenders = _writing_scaffold_invocations(SETUP_MD.name, text)
    assert not offenders, (
        "/oss:setup must only ever run the read-only plan:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("path,label,predicate,pattern", CARRIED, ids=CARRIED_IDS)
def test_deleting_the_carrying_lines_fails_the_predicate(
    path, label, predicate, pattern
):
    """The targeted control: the real file minus the lines carrying the fact. A
    predicate still passing here is matching something incidental."""
    mutated = _without_lines_matching(path.read_text(encoding="utf-8"), pattern)
    assert not predicate(mutated), (
        "{}: predicate passes with its own lines deleted".format(label)
    )


# --------------------------------------------------------------------------- #
# A flag the script accepts and the command file never mentions.
#
# `--untagged` shipped, was the only place a repository could declare its
# untagged releases, and `commands/changelog.md` did not name it -- so the one
# surface a maintainer reads before running the audit was silent about the one
# flag that changes its verdict (#101). Nothing caught that, because the guard
# above checks that documented invocations pass required flags and cannot see a
# flag that was never documented at all.
#
# Three states rather than two. A flag is documented, or it is exempt WITH A
# REASON WRITTEN DOWN, or it is a finding. An exemption list with no reasons is
# the same silence one indirection further away, and a flag added to the parser
# next year lands in the third state by default -- which is the point: the
# decision gets made, rather than defaulted into by nobody noticing.
# --------------------------------------------------------------------------- #

ASSEMBLER_SCRIPT = REPO_ROOT / "scripts" / "assemble_changelog.py"
CHANGELOG_MD = REPO_ROOT / "commands" / "changelog.md"

ADD_ARGUMENT_RE = re.compile(r"""add_argument\(\s*["'](--[A-Za-z0-9-]+)["']""")

#: flag -> why commands/changelog.md does not name it. Each of these is a
#: decision, and the reason is the part that makes it one.
UNDOCUMENTED_BY_DECISION = {
    "--date": (
        "the fold takes today's date and the command never overrides it; the "
        "flag exists so the test suite can pin a date"
    ),
    "--dry-run": (
        "a rehearsal of the fold. /oss:release runs the fold for real, gated, "
        "and a documented rehearsal invites folding twice"
    ),
    "--keep": (
        "keeps consumed fragments. The fold deleting them is the policy this "
        "command file states; a flag that undoes it does not belong beside it"
    ),
}


def _assembler_flags():
    """Every long flag the assembler's parser accepts, read off the source."""
    return sorted(
        set(ADD_ARGUMENT_RE.findall(ASSEMBLER_SCRIPT.read_text(encoding="utf-8")))
    )


def test_the_flag_detector_reads_the_parser():
    """The detector before the assertion. A regex matching nothing turns the
    check below into a check that never looked, and one matching everything
    turns it into a check that cannot report."""
    flags = _assembler_flags()
    assert flags, "no --flags found in " + ASSEMBLER_SCRIPT.name
    # The must-fire half: flags known to be there are found.
    for known in ("--check", "--check-links", "--dir", "--changelog", "--untagged"):
        assert known in flags, known
    # The must-not-fire half, same fixture: prose mentioning a flag is not a
    # parser accepting one.
    assert (
        ADD_ARGUMENT_RE.findall("the --nonesuch flag, as in add_argument, is prose")
        == []
    )
    # And every exemption names a flag that exists. An exemption for a flag
    # that was renamed is a silence nobody is accountable for any more.
    assert not set(UNDOCUMENTED_BY_DECISION) - set(flags), (
        "these exemptions name flags the parser no longer has: "
        + ", ".join(sorted(set(UNDOCUMENTED_BY_DECISION) - set(flags)))
    )


def test_every_assembler_flag_is_documented_or_exempt_with_a_reason():
    text = CHANGELOG_MD.read_text(encoding="utf-8")
    assert text.strip(), CHANGELOG_MD.name + " is empty -- nothing was checked"

    undocumented = [
        flag
        for flag in _assembler_flags()
        if flag not in text and flag not in UNDOCUMENTED_BY_DECISION
    ]
    assert not undocumented, (
        "{} accepts these flags and {} never names them: {}. Document them, or "
        "add each to UNDOCUMENTED_BY_DECISION with the reason it stays out -- "
        "a flag that changes the verdict and appears on no surface a maintainer "
        "reads is the shape #101 was filed about.".format(
            ASSEMBLER_SCRIPT.name, CHANGELOG_MD.name, ", ".join(undocumented)
        )
    )
    for flag, reason in sorted(UNDOCUMENTED_BY_DECISION.items()):
        assert reason.strip(), flag + ": exempt with no reason recorded"
