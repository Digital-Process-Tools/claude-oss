"""Guards on the skill and agent prose.

The whole reason this plugin exists is that the maintainer loop was three diverged
copies, each carrying its own repo's facts. A hardcoded repo name here recreates
that: it would arrive in a brief with the same authority as something re-derived,
and be wrong for every repo but one.

These are content tests. They fail loudly when the regex matches nothing it was
meant to anchor on, because a pattern that matched nothing has checked nothing.
"""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = sorted((REPO_ROOT / "skills").rglob("SKILL.md"))
AGENTS = sorted((REPO_ROOT / "agents").glob("*.md"))
COMMANDS = sorted((REPO_ROOT / "commands").glob("*.md"))
PROSE = SKILLS + AGENTS
EXECUTABLE_PROSE = SKILLS + AGENTS + COMMANDS

# Spellings that would make a document true of exactly one repository.
HARDCODED = [
    (r"Digital-Process-Tools/claude-\w+", "a specific repo slug"),
    (r"~/Documents/(?:st|jit|rm)-wt", "a specific worktree root"),
    (r"~/Documents/claude-\w+", "a specific local clone"),
    (r"\bclaude-(?:supertool|remember|jit-context|5h-window-spread)\b", "a sibling repo name"),
    (r"\bfdaviddpt\b", "a specific GitHub handle"),
]


def _documents():
    return [(path, path.read_text(encoding="utf-8")) for path in PROSE]


def test_prose_files_exist():
    """A suite that silently found no documents would pass every check below."""
    assert SKILLS, "no skills/**/SKILL.md found -- the checks below would vacuously pass"
    assert AGENTS, "no agents/*.md found -- the checks below would vacuously pass"


def test_no_repo_specific_spellings_in_prose():
    offenders = []
    for path, text in _documents():
        for pattern, what in HARDCODED:
            for match in re.finditer(pattern, text):
                line = text[: match.start()].count("\n") + 1
                rel = path.relative_to(REPO_ROOT)
                offenders.append("{}:{}: {} ({!r})".format(rel, line, what, match.group(0)))
    assert not offenders, (
        "Repo-specific values belong in .oss.json, not in prose. A fact about one repo "
        "asserted here reaches a brief with the same authority as a re-derived one:\n  "
        + "\n  ".join(offenders)
    )


def test_skill_and_agents_declare_frontmatter():
    for path, text in _documents():
        rel = path.relative_to(REPO_ROOT)
        assert text.startswith("---\n"), "{}: no YAML frontmatter".format(rel)
        end = text.index("\n---\n", 3)
        block = text[4:end]
        for key in ("name:", "description:"):
            assert key in block, "{}: frontmatter is missing {}".format(rel, key)


def _granted_tools(agent_name):
    block = (REPO_ROOT / "agents" / agent_name).read_text(encoding="utf-8").split("\n---\n", 1)[0]
    tools = re.search(r"^tools:\s*(.+)$", block, re.MULTILINE)
    assert tools is not None, "{} declares no tools: line".format(agent_name)
    return {t.strip() for t in tools.group(1).split(",")}


def test_triager_cannot_write_files():
    """The triager labels and nothing else. That restriction is enforced by its tool
    grant, not by the prose telling it to behave -- prose is a request, frontmatter
    is the boundary.
    """
    forbidden = _granted_tools("triager.md") & {"Edit", "Write", "NotebookEdit"}
    assert not forbidden, (
        "triager must not be able to edit files; found {} in its tool grant".format(
            sorted(forbidden)
        )
    )


def test_agents_read_through_supertool_only():
    """No agent gets Read/Grep/Glob. Reading a repo one file per call is how a sweep
    becomes forty round-trips, and an agent that has the single-file tools will reach
    for them however the prose is worded. Removing them is what makes the batching
    instruction binding rather than advisory.
    """
    assert AGENTS, "no agents/*.md found -- this check would vacuously pass"
    for agent in AGENTS:
        leaked = _granted_tools(agent.name) & {"Read", "Grep", "Glob"}
        assert not leaked, (
            "{} grants {} -- reads go through supertool via Bash, so these must not be "
            "in the tool list".format(agent.name, sorted(leaked))
        )


def test_developer_stops_at_a_commit():
    """The publishing clause is unconditional on purpose: a brief phrased as 'do not
    push if something blocks you' is how an agent correctly pushed.
    """
    text = (REPO_ROOT / "agents" / "developer.md").read_text(encoding="utf-8")
    for phrase in ("Do not push", "Do not open a PR"):
        assert phrase in text, "developer.md no longer states: {}".format(phrase)


# --------------------------------------------------------------- recipe preconditions
#
# The shape these share: a recipe that depends on state the recipe itself has not
# established. Prose cannot be type-checked, but each of these is a mechanical fact
# about the text, and each one shipped once already.


def _executable_documents():
    return [(path, path.read_text(encoding="utf-8")) for path in EXECUTABLE_PROSE]


def test_executable_prose_exists():
    assert COMMANDS, "no commands/*.md found -- the checks below would vacuously pass"


# Every prefix below belongs to a shipped preset, so none of them load in a repo with
# no .supertool.json -- which is the state of every repo /oss:setup is aimed at.
PRESET_OP_RE = re.compile(r"supertool\s+'([^']*)'")
PRESET_OP_PREFIXES = ("gh-", "git-", "gl-", "radar", "dashboard", "channel")


def _preset_ops_called(text):
    """Preset-only ops invoked through supertool, with their line numbers."""
    found = []
    for match in PRESET_OP_RE.finditer(text):
        op = match.group(1).split(":", 1)[0]
        if op.startswith(PRESET_OP_PREFIXES):
            found.append((text[: match.start()].count("\n") + 1, op))
    return found


def test_the_preset_op_detector_detects_a_preset_op():
    """The positive control, and it is not decoration.

    #3's recipe no longer exists: #19 replaced the hand-assembled probe with
    `oss_config.py --probe | --build`, which shells out to `git` and `gh` through
    subprocess and touches supertool nowhere. So there is now no `supertool '...'` call
    in setup.md at all, and the check below would pass against a file with anything in
    it -- a pattern that matched nothing having checked nothing, which is the exact
    defect this suite exists to refuse.

    This pins the detector so the guard below stays a measurement.
    """
    sample = "```bash\nsupertool 'gh-labels' 'ls:.'\n```\n"
    assert _preset_ops_called(sample) == [(2, "gh-labels")]
    assert _preset_ops_called("```bash\nsupertool 'ls:.' 'read:x'\n```\n") == []


def test_setup_probes_the_repo_without_preset_only_ops():
    """#3: `/oss:setup` opened by calling `gh-labels`, which cannot run in a repo that
    has no `.supertool.json` -- and that is every repo setup is pointed at, so the first
    line of the first run failed. The command elsewhere forbids the tempting resolution,
    which is to write label names nobody observed.

    Fixed by another route before this landed. Kept as a regression guard, because the
    precondition did not change: whatever setup grows next still runs before
    `.supertool.json` exists.

    Scoped to setup.md deliberately. Every other command runs against a repo setup has
    already configured, so a preset op there has its precondition met.
    """
    text = (REPO_ROOT / "commands" / "setup.md").read_text(encoding="utf-8")
    offenders = ["setup.md:{}: {!r}".format(line, op) for line, op in _preset_ops_called(text)]
    assert not offenders, (
        "/oss:setup runs before .supertool.json exists, so preset ops are not loaded "
        "and these calls cannot run:\n  " + "\n  ".join(offenders)
    )


IDENTITY_PATH_RE = re.compile(r"((?:<repo>/|\.)[A-Za-z0-9_./<>-]*remember/identity[A-Za-z.]*\.md)")


def test_every_document_names_the_same_identity_file():
    """#4 and #9, which are one defect seen from two sides.

    `/oss:setup` said never write identity into the target repo; `/oss:doctor` warned it
    was missing and told you to write it. Separately the warning named `.remember/`
    while the check read `.claude/remember/`, so doing what it said changed nothing.
    Two documents disagreeing about one file is what a content test can hold still, and
    an instruction that cannot be satisfied gets worked around -- invisibly, because
    the workaround leaves no trace.

    Which path is correct is not decided here. That it is one path is.
    """
    seen = {}
    for path, text in _executable_documents():
        for match in IDENTITY_PATH_RE.finditer(text):
            found = match.group(1)
            leaf = found[found.index("remember/") :]
            seen.setdefault(leaf, []).append(path.relative_to(REPO_ROOT).as_posix())
    assert seen, (
        "no identity.md path found in any command or skill -- IDENTITY_PATH_RE no "
        "longer matches how they are written, and a pattern that matched nothing has "
        "checked nothing."
    )
    assert len(seen) == 1, (
        "the documents name more than one identity.md location, so at most one of them "
        "can be the file the memory plugin actually reads:\n  "
        + "\n  ".join(
            "{} <- {}".format(leaf, ", ".join(sorted(set(where))))
            for leaf, where in sorted(seen.items())
        )
    )


def test_scaffold_documents_every_file_it_writes():
    """#7: `/oss:scaffold` creates `.supertool.json`, the file that decides which
    supertool ops exist. The listing the running agent works from was captured before
    that file existed and is never refreshed, so the session that installs the config
    is the one that cannot see what it installed.

    The rule underneath: a command that writes a file the reader will have to reason
    about has to name it. Read off the script, so a new template cannot be added
    without the sentence that explains it.
    """
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import scaffold

    text = (REPO_ROOT / "commands" / "scaffold.md").read_text(encoding="utf-8")
    written = sorted(scaffold.TEMPLATES) + sorted(scaffold.OWNED)
    assert written, "scaffold.py declares no files -- this check would vacuously pass"
    missing = [name for name in written if name not in text]
    assert not missing, (
        "scaffold.py writes these into the repo and commands/scaffold.md never names "
        "them, so nobody reviewing the plan knows they arrived:\n  " + "\n  ".join(missing)
    )


def test_the_merge_instruction_carries_its_confirmation_gate():
    """#14: the loop is built around `gh-pr-merge`, and `gh-pr-merge` merges nothing
    without `|force` -- it previews the gate and exits non-zero. A tick reaches the
    merge step, spends the whole review, and only then cannot merge.

    A denied write is the moment an agent goes looking for another route, and both
    routes available are worse than the one blocked. So the document that names the op
    names the gate in the same breath.
    """
    named = []
    for path, text in _executable_documents():
        if "gh-pr-merge" not in text:
            continue
        rel = path.relative_to(REPO_ROOT)
        named.append(rel)
        assert "|force" in text, (
            "{}: names gh-pr-merge without naming the |force confirmation gate. "
            "Without it the op previews and merges nothing.".format(rel)
        )
    assert named, "no document names gh-pr-merge -- this check would vacuously pass"


def test_developer_notes_convention_is_pinned():
    """agents/developer.md#15: the long half of a report goes to a note file the maintainer
    queries, not into its context whole. Three things must hold together or the convention
    silently degrades back into "paste everything" or "note lives inside the diff":

    - the note lives outside every worktree (a sibling of the numbered worktree directories,
      never inside one -- that is what keeps it out of the diff with no .gitignore entry needed)
    - the report ends with the note's absolute path, so the maintainer can find it
    - the report states the split's cost, so the saving stays a measured claim rather than an
      adopted guess
    """
    text = (REPO_ROOT / "agents" / "developer.md").read_text(encoding="utf-8")
    assert "<worktree_root>/notes/" in text, (
        "developer.md must place notes under <worktree_root>/notes/, a sibling of the "
        "numbered worktree directories -- inside a worktree, a note risks entering the diff"
    )
    assert "absolute" in text.lower(), (
        "developer.md must tell the agent to report the note's absolute path"
    )
    assert "cost" in text.lower(), (
        "developer.md must ask the agent to state what the note/report split cost -- "
        "otherwise the saving this convention exists for is never checked"
    )
# ------------------------------------------------------------------- config scope (#34)


def _oss_config():
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import oss_config

    return oss_config


def test_setup_writes_both_halves_and_excludes_only_the_local_one():
    """#34: setup wrote one file and excluded it, so the `release` block -- tag spelling,
    merge method, version sites, triggers -- lived on one laptop. A second maintainer
    re-derived `tag_pattern` by being asked, and a repo tagging v1.2.3 can acquire 1.2.4.
    """
    oss_config = _oss_config()
    text = (REPO_ROOT / "commands" / "setup.md").read_text(encoding="utf-8")
    assert oss_config.LOCAL_CONFIG_NAME in text, (
        "setup.md must name the machine-scoped half; without it the maintainer writes "
        "one file again"
    )
    assert "--split" in text, "setup.md must invoke the split; a manual split is per-maintainer"


def test_no_document_asks_for_the_project_config_to_be_git_excluded():
    """The exclusion is the defect. A line that excludes `.oss.json` is the whole bug in
    one sentence, so it is checked line by line rather than by the file's overall shape.
    """
    oss_config = _oss_config()
    offenders = []
    for path, text in _executable_documents():
        for number, line in enumerate(text.splitlines(), 1):
            if "exclude" not in line:
                continue
            if oss_config.CONFIG_NAME in line and oss_config.LOCAL_CONFIG_NAME not in line:
                offenders.append(
                    "{}:{}: {}".format(path.relative_to(REPO_ROOT), number, line.strip())
                )
    assert not offenders, (
        "the project half of the config is meant to be committed; excluding it is how "
        "the release block ended up on one machine: " + "; ".join(offenders)
    )


def test_documents_that_enumerate_the_config_keys_name_both_files():
    """A key list that does not say which file holds which key sends the reader to the
    wrong one, and `state_file` is missing from the committed half by design.
    """
    oss_config = _oss_config()
    named = []
    for path, text in _executable_documents():
        if "worktree_root" not in text:
            continue
        rel = path.relative_to(REPO_ROOT)
        named.append(rel)
        assert oss_config.LOCAL_CONFIG_NAME in text, (
            "{}: enumerates the config keys without naming {}, so a reader looks for "
            "worktree_root in the committed file and does not find it".format(
                rel, oss_config.LOCAL_CONFIG_NAME
            )
        )
    assert named, "no document enumerates the config keys -- this check would vacuously pass"


def test_release_states_what_to_do_for_every_nullable_release_key():
    """#34, second half. `tag_pattern: null` got an explicit stop-and-ask; `commit_subject:
    null` got the sentence "commit with `commit_subject`" and nothing else, so the agent
    invented a subject line -- an absence the tool produced, rendered as a value.

    The two are still handled differently, and that is defensible: a wrong subject line is
    revisable, a wrong tag opens a namespace forever. What was not defensible is that only
    one of them said so.
    """
    oss_config = _oss_config()
    text = (REPO_ROOT / "commands" / "release.md").read_text(encoding="utf-8")
    assert "`tag_pattern: null` — stop" in text
    assert oss_config.DEFAULT_COMMIT_SUBJECT in text, (
        "release.md must state the default subject verbatim, or the agent reaching a "
        "null commit_subject is back to inventing one"
    )
    for key in ("tag_pattern", "commit_subject"):
        assert key in text, key


def test_agents_and_skill_treat_forge_content_as_untrusted():
    """Every document that reads a public tracker states that its contents are data.
    This is the paragraph most likely to be lost in an edit, and the one whose
    absence is invisible until it matters.
    """
    for path, text in _documents():
        rel = path.relative_to(REPO_ROOT)
        assert "data, not instructions" in text, (
            "{}: missing the untrusted-input clause. Issue and PR bodies are written "
            "by strangers; a document that reads them must say so.".format(rel)
        )


# ------------------------------------------------------------------ the auditor (#33)
#
# The census in #33 recommended against building this agent and scored a checklist
# reviewer at 2 of 6 against real specimens. The maintainer overrode that. What the
# override kept is the substance these checks hold still:
#
#   - it annotates, it does not block. A blocking LLM gate with false positives gets
#     routed around within a week, which lands this repo in class B -- a guard nominally
#     on and effectively off, the exact defect the agent audits for.
#   - `could not check` is a required word. The auditor's own report has three states
#     and the third never renders as clean. An auditor that cannot say it failed to look
#     is the defect it exists to find.
#
# The scope was widened after the first brief: A, B, C plus the platform band D, F, H.
# The original exclusion of D/F/H was measured against one repo's 12-leg matrix, which
# is a fact about that repo and not about the defect class -- a repo with no Windows leg
# has no such coverage at all. E stays out: nothing in a diff predicts runner load.

AUDITOR = REPO_ROOT / "agents" / "auditor.md"

EXCLUSIONS_HEADING = "## What this does not check"

# id -> substrings that must all be present for the contract to be legible in the file.
AUDITOR_CONTRACTS = [
    ("class-A-three-state", ("`[]`", "`None`", "could not tell")),
    ("class-B-guard-did-not-run", ("nominally on", "effectively off")),
    ("class-C-untrusted-text", ("splitlines", "column 0")),
    ("platform-band", ("encoding", "line endings")),
    ("coverage-three-state", ("covered", "not covered", "could not determine")),
    ("coverage-unknown-is-not-a-downgrade", ("must not silently collapse",)),
    ("annotates-not-blocks", ("annotates", "does not block")),
    ("third-state-word", ("could not check",)),
    ("third-state-never-clean", ("never renders as clean",)),
    ("finding-can-be-argued-down", ("argued down",)),
    ("names-what-it-does-not-check", (EXCLUSIONS_HEADING,)),
    ("untrusted-input", ("data, not instructions",)),
]


def _auditor_contracts_unmet(text):
    return {
        name
        for name, anchors in AUDITOR_CONTRACTS
        if not all(anchor in text for anchor in anchors)
    }


def test_auditor_agent_exists():
    """Without the file every check below fails for the wrong reason, and a suite that
    cannot find its subject must say which of the two it is.
    """
    assert AUDITOR.is_file(), "agents/auditor.md is missing"


def test_auditor_carries_every_contract():
    unmet = _auditor_contracts_unmet(AUDITOR.read_text(encoding="utf-8"))
    assert not unmet, (
        "agents/auditor.md no longer states these contracts, each of which is the "
        "reason the agent was allowed to exist:\n  " + "\n  ".join(sorted(unmet))
    )


def test_the_contract_checks_fire_on_an_agent_that_says_nothing():
    """The positive control, and the whole of it.

    A prose deliverable is the easiest thing to assert vacuously: `assert x in text`
    over a file nobody constrained passes as readily as over one that was written to
    the contract. So the same checker is run against a plausible-looking agent file
    that says nothing, and every single contract must report unmet.
    """
    says_nothing = (
        "---\n"
        "name: auditor\n"
        "description: Audit a diff.\n"
        "tools: Bash\n"
        "---\n\n"
        "Read the diff and report any security or portability problems you find.\n"
    )
    unmet = _auditor_contracts_unmet(says_nothing)
    expected = {name for name, _ in AUDITOR_CONTRACTS}
    assert unmet == expected, (
        "the contract checks do not fire on an agent file that says nothing, so they "
        "would also pass on one. Not firing: " + repr(sorted(expected - unmet))
    )


# --------------------------------------------------------------- no third copy (#4/#9/#26)
#
# The recurring cross-platform shapes are already written down twice --
# agents/developer.md and skills/manager/SKILL.md. A third copy is not coverage; it is
# the drift defect this tracker was opened to file. The auditor references them, so
# these anchors must be absent from it and present in their source.
#
# No count is stated here on purpose. The list gained a sixth entry in #56, and the
# word "five" was by then sitting in documents that had no reason to know how long
# the list was.

PORTABILITY_SHAPES = (
    "drive letter",
    "POSIX literal",
    "spawn error",
    "narrow `except`",
    "codepage",
)


def _portability_shapes_copied_into(text):
    return [shape for shape in PORTABILITY_SHAPES if shape in text]


def test_the_portability_shapes_have_exactly_one_source_each():
    """The positive control for the check below: the shapes must be findable where the
    auditor points at them, or "absent from the auditor" is satisfied by their being
    absent everywhere.
    """
    developer = (REPO_ROOT / "agents" / "developer.md").read_text(encoding="utf-8")
    missing = [s for s in PORTABILITY_SHAPES if s not in developer]
    assert not missing, (
        "agents/developer.md no longer enumerates {} -- the auditor references that "
        "section, so a reference now resolves to nothing".format(missing)
    )
    assert _portability_shapes_copied_into(developer) == list(PORTABILITY_SHAPES)


def test_auditor_does_not_recopy_the_portability_checklist():
    copied = _portability_shapes_copied_into(AUDITOR.read_text(encoding="utf-8"))
    assert not copied, (
        "agents/auditor.md carries its own copy of {} -- that list already ships twice "
        "and a third copy drifts. Reference the section instead.".format(copied)
    )


# ------------------------------------------------------------------------- the wiring

AUDITOR_SUBAGENT = "oss:auditor"


def _wiring_unmet(text):
    unmet = set()
    if AUDITOR_SUBAGENT not in text:
        unmet.add("names-the-auditor-subagent")
    if "same message" not in text:
        unmet.add("spawned-alongside-the-reviewer")
    if "did not execute" not in text:
        unmet.add("a-review-that-did-not-execute-is-not-a-clean-review")
    if "did not run" not in text:
        unmet.add("a-spawn-that-did-not-run-is-reported")
    if "must not edit" not in text:
        unmet.add("spawned-agents-do-not-edit")
    if "Cross-platform is not your machine" not in text:
        unmet.add("hands-over-the-portability-section")
    return unmet


def test_developer_spawns_the_auditor():
    unmet = _wiring_unmet((REPO_ROOT / "agents" / "developer.md").read_text(encoding="utf-8"))
    assert not unmet, (
        "agents/developer.md does not wire the auditor in: " + repr(sorted(unmet))
    )


def test_the_wiring_check_fires_on_a_developer_that_spawns_only_the_reviewer():
    """Positive control. The state this replaced -- one generalist reviewer, no
    auditor -- must be reported as unwired, or the check above passes on it.
    """
    only_the_reviewer = (
        'After you commit, spawn one Sonnet reviewer:\n\n'
        'Agent(subagent_type: "general-purpose", model: "sonnet")\n'
    )
    unmet = _wiring_unmet(only_the_reviewer)
    assert unmet == {
        "names-the-auditor-subagent",
        "spawned-alongside-the-reviewer",
        "a-review-that-did-not-execute-is-not-a-clean-review",
        "a-spawn-that-did-not-run-is-reported",
        "spawned-agents-do-not-edit",
        "hands-over-the-portability-section",
    }, repr(sorted(unmet))


def test_the_wiring_check_fires_on_the_sentence_that_predates_this_change():
    """The narrower control the first one missed.

    `did not execute` was already in developer.md before the auditor existed, so an
    anchor on it alone reports the wiring as present in a file that never mentions the
    auditor's own per-class non-run. Deleting only the new sentence must be visible.
    """
    text = (REPO_ROOT / "agents" / "developer.md").read_text(encoding="utf-8")
    without_the_new_sentence = text.replace("did not run", "ran")
    assert "a-spawn-that-did-not-run-is-reported" in _wiring_unmet(without_the_new_sentence), (
        "the wiring check is satisfied by prose that predates this change, so it says "
        "nothing about whether the auditor's non-run is reported"
    )


# ------------------------------------------------- the release auditor (#48)
#
# The release gate has said, in two documents, that a security audit of the delta
# since the last tag must pass, with three outcomes -- and nothing performed it.
# So the gate's own third outcome was the permanent state and there was no way to
# notice: nothing ever tried, so nothing ever reported that it could not.
#
# This agent is deliberately not agents/auditor.md. They are split by slot: that
# one reads one PR's diff, annotates, and runs on every PR; this one reads the
# whole delta since the last tag, blocks, and runs once per release. Two agents
# whose false-positive costs are opposite -- an argument in a report versus a
# delayed release -- should not share a definition.
#
# What these hold still is the part that makes it a gate rather than an opinion:
#
#   - three verdicts, and `could not run` stops the release. Rendering it as clean
#     is the whole defect the gate was worded against.
#   - a two-round hard cap. Not a budget: a competent audit of any non-trivial
#     delta always finds something, so an unbounded "findings, therefore stop"
#     makes every release hostage to diminishing returns.
#   - a repo with no previous tag is a *named* state, not an empty diff. An empty
#     delta and an uncomputable one are the two things this gate keeps apart.

RELEASE_AUDITOR = REPO_ROOT / "agents" / "release-auditor.md"

RELEASE_AUDITOR_CONTRACTS = [
    ("blocks-rather-than-annotates", ("blocks",)),
    ("three-outcomes", ("clean", "findings", "could not run")),
    ("third-outcome-never-clean", ("never renders as",)),
    ("third-outcome-stops-the-release", ("stops the release",)),
    ("two-round-hard-cap", ("two rounds", "hard cap")),
    ("what-happens-after-round-two", ("next milestone",)),
    ("first-release-is-a-named-state", ("first release",)),
    ("the-range-is-computed-not-guessed", ("release_delta.py",)),
    # An unscoped range is the one way this gate can be wrong while looking right:
    # `describe` unmatched anchors on the newest tag of any namespace, the delta
    # computes, and `could not run` never fires. So the agent has to say `unscoped`
    # out loud -- and it must not read that as a fourth reason to stop, which would
    # block every repo that has not spelled its tags out.
    ("an-unscoped-range-is-named-and-does-not-block", ("unscoped", "does not stop")),
    ("reuses-the-class-vocabulary-by-reference", ("agents/auditor.md",)),
    ("the-delta-is-what-no-per-pr-review-can-see", ("individually clean",)),
    ("untrusted-input", ("data, not instructions",)),
    ("writes-nothing", ("writes nothing",)),
]


def _release_auditor_contracts_unmet(text):
    """Case-folded, because capitalisation is not the contract. "Two rounds" at the
    head of a sentence and "two rounds" mid-sentence are the same commitment, and a
    check that distinguishes them fails on a rewrite that changed nothing.
    """
    folded = text.lower()
    return {
        name
        for name, anchors in RELEASE_AUDITOR_CONTRACTS
        if not all(anchor.lower() in folded for anchor in anchors)
    }


def test_release_auditor_agent_exists():
    assert RELEASE_AUDITOR.is_file(), "agents/release-auditor.md is missing"


def test_release_auditor_carries_every_contract():
    unmet = _release_auditor_contracts_unmet(
        RELEASE_AUDITOR.read_text(encoding="utf-8")
    )
    assert not unmet, (
        "agents/release-auditor.md no longer states these, each of which is what "
        "makes it a gate rather than an opinion:\n  " + "\n  ".join(sorted(unmet))
    )


def test_the_release_auditor_contracts_fire_on_an_agent_that_says_nothing():
    """The positive control. `assert x in text` over prose nobody constrained passes
    exactly as readily as over prose written to the contract, so the same checker
    is run against a plausible-looking file that says none of it.
    """
    says_nothing = (
        "---\n"
        "name: release-auditor\n"
        "description: Audit a release.\n"
        "tools: Bash\n"
        "---\n\n"
        "Look over everything since the last release and report what you find.\n"
    )
    unmet = _release_auditor_contracts_unmet(says_nothing)
    expected = {name for name, _ in RELEASE_AUDITOR_CONTRACTS}
    assert unmet == expected, (
        "the contract checks do not fire on an agent file that says nothing, so "
        "they would also pass on one. Not firing: "
        + repr(sorted(expected - unmet))
    )


def test_no_agent_recopies_the_portability_checklist():
    """The no-third-copy rule is not about one file. Any agent that restates the
    shapes makes a third copy, and the copy that drifts is never the one anybody
    rereads.
    """
    offenders = {}
    for agent in AGENTS:
        if agent.name == "developer.md":
            continue
        copied = _portability_shapes_copied_into(agent.read_text(encoding="utf-8"))
        if copied:
            offenders[agent.name] = copied
    assert not offenders, (
        "these agents carry their own copy of the cross-platform shapes, which "
        "already ship twice. Reference the section instead: {}".format(offenders)
    )


# ------------------------------------------------------- the release gate is wired

RELEASE_AUDITOR_SUBAGENT = "oss:release-auditor"

RELEASE_DELTA_SCRIPT = "scripts/release_delta.py"


def _release_wiring_unmet(text):
    unmet = set()
    if RELEASE_AUDITOR_SUBAGENT not in text:
        unmet.add("names-the-release-auditor-subagent")
    if RELEASE_DELTA_SCRIPT not in text:
        unmet.add("computes-the-range-before-asking-for-a-judgement")
    if "stops the release" not in text:
        unmet.add("could-not-run-stops-the-release")
    if "first release" not in text:
        unmet.add("a-repo-with-no-tag-has-a-defined-state")
    return unmet


def test_release_command_wires_the_gate_to_something_that_runs():
    unmet = _release_wiring_unmet(
        (REPO_ROOT / "commands" / "release.md").read_text(encoding="utf-8")
    )
    assert not unmet, (
        "commands/release.md states the audit gate without wiring it to anything "
        "that performs it: " + repr(sorted(unmet))
    )


def test_the_release_wiring_check_fires_on_the_gate_as_it_was_stated_before():
    """The narrow positive control, and it is the actual prior text.

    This paragraph shipped for months and read as a satisfied gate every time a
    human read it and formed a judgement. Every wiring anchor must report unmet
    against it, or the check above says nothing about whether anything runs.
    """
    the_unwired_gate = (
        "3. **A security audit of the delta since the last tag passed.** Three "
        "outcomes: clean, findings, or **could not run**. An audit that did not "
        "execute must never render as an audit that found nothing. **Two rounds, "
        "hard cap**.\n"
    )
    unmet = _release_wiring_unmet(the_unwired_gate)
    assert unmet == {
        "names-the-release-auditor-subagent",
        "computes-the-range-before-asking-for-a-judgement",
        "could-not-run-stops-the-release",
        "a-repo-with-no-tag-has-a-defined-state",
    }, repr(sorted(unmet))


def test_the_skill_and_the_command_agree_that_the_gate_is_performed():
    """Two documents stated the same gate and neither named a performer. If only
    one gains the wiring, the other keeps sending its reader to a judgement call.
    """
    skill = (REPO_ROOT / "skills" / "manager" / "SKILL.md").read_text(encoding="utf-8")
    unmet = _release_wiring_unmet(skill)
    assert not unmet, (
        "skills/manager/SKILL.md states the audit gate but does not carry what "
        "commands/release.md now carries, so its reader is still sent to a "
        "judgement call: " + repr(sorted(unmet))
    )


PLUGIN_REF_RE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)")


def test_every_plugin_rooted_reference_in_an_agent_resolves():
    """The auditor points at a section in another file rather than copying it. A
    reference is only better than a copy while it resolves; a renamed file turns it into
    an instruction to read something that is not there, and the agent's fallback is to
    report the whole band as `could not check` -- silently losing the class.
    """
    referenced = []
    for path, text in _documents():
        for match in PLUGIN_REF_RE.finditer(text):
            target = REPO_ROOT / match.group(1)
            referenced.append(match.group(1))
            assert target.exists(), "{} points at {}, which does not exist".format(
                path.relative_to(REPO_ROOT), match.group(1)
            )
    assert referenced, (
        "no ${CLAUDE_PLUGIN_ROOT}/... reference found in any agent -- the auditor "
        "references the cross-platform section instead of copying it, so this pattern "
        "matching nothing means it has stopped doing that"
    )


# ------------------------------------------------- what the program prints (#56)
#
# Five of the six shapes are about what a program reads or invokes. The sixth is
# about what it writes, and it exists because the gap cost a release: an arrow in
# `assemble_changelog.py`'s receipt raised UnicodeEncodeError on the cp1252 console
# of the Windows runner, after the script had already written CHANGELOG.md and
# deleted every fragment. The agent that shipped it audited its change against all
# five items correctly and ran the full suite green -- the character prints fine on
# a UTF-8 console, so nothing local could have shown it.
#
# An item that does not exist is the one thing a checklist cannot report as
# unchecked, which is why the sixth is pinned here rather than left to prose review.
# Each anchor is a half of the item that would make it useless if it were dropped:
#
#   - the encoding is the console's, chosen at runtime, not the source file's;
#   - cp1252 specifically -- the bar tests/test_receipt_encoding.py deliberately
#     sets, since the em dashes that ship green through every Windows leg are valid
#     cp1252 and an ASCII rule would condemn them;
#   - the failure is an exception that kills the process, not a mangled glyph;
#   - it is about what is printed, which is what separates it from the other five;
#   - and it lands *after* the work, which is what makes it a platform item rather
#     than a cosmetic one.

CONSOLE_ENCODING_ANCHORS = [
    ("the-encoding-is-the-console's", ("codepage",)),
    ("the-bar-is-the-codepage-ci-measures", ("cp1252",)),
    ("it-kills-the-process", ("unicodeencodeerror",)),
    ("it-is-about-what-is-printed", ("stdout",)),
    ("the-crash-lands-after-the-work", ("after the work",)),
]

CONSOLE_ENCODING_SOURCES = [
    REPO_ROOT / "agents" / "developer.md",
    REPO_ROOT / "skills" / "manager" / "SKILL.md",
]


def _console_encoding_anchors_unmet(text):
    """Case-folded: capitalisation is not the contract, and the two documents word
    the item differently -- one runs it into a prose paragraph, the other carries it
    as a bullet in a list.
    """
    folded = text.lower()
    return {
        name
        for name, anchors in CONSOLE_ENCODING_ANCHORS
        if not all(anchor in folded for anchor in anchors)
    }


def test_both_copies_carry_the_console_encoding_item():
    """Both, and only these two. The no-third-copy guard above owns the other half:
    `codepage` is in PORTABILITY_SHAPES, so an agent that restates this item is
    reported as a third copy by the check that already exists.
    """
    for path in CONSOLE_ENCODING_SOURCES:
        assert path.is_file(), "{} is missing".format(path.relative_to(REPO_ROOT))
        unmet = _console_encoding_anchors_unmet(path.read_text(encoding="utf-8"))
        assert not unmet, (
            "{} does not carry the console-encoding shape: {}".format(
                path.relative_to(REPO_ROOT), sorted(unmet)
            )
        )


#: The list exactly as it stood before this change -- the checklist that was audited
#: against, correctly, on the day the cp1252 crash shipped.
THE_FIVE_ITEMS_AS_THEY_STOOD = """
- a suffix or separator match that behaves differently with backslashes than with forward slashes
- a Windows drive letter read as a hostname, because the colon precedes the first slash
- a hardcoded POSIX literal in a test assertion
- a platform raising a different exception type, so a narrow `except` never fires
- an unspawnable binary raising a spawn error instead of reaching its own "the tool failed" arm
"""


def test_the_console_encoding_check_fires_on_the_checklist_that_missed_it():
    """The positive control, and it is the whole value of the check above.

    `assert "codepage" in text` over a prose file passes as readily on prose nobody
    constrained as on prose written to the contract. So the same checker is run
    against the five-item list as it was worded when the defect shipped: every
    anchor must fire, or "the item is present" is a claim about nothing.
    """
    unmet = _console_encoding_anchors_unmet(THE_FIVE_ITEMS_AS_THEY_STOOD)
    expected = {name for name, _ in CONSOLE_ENCODING_ANCHORS}
    assert unmet == expected, (
        "the console-encoding anchors do not fire on the checklist that missed the "
        "defect, so they say nothing about the sixth item being there. Not firing: "
        + repr(sorted(expected - unmet))
    )


# ------------------------------------------------- Explore reviewer, not general-purpose (#82)
#
# A brief telling a `general-purpose` reviewer in prose not to edit is not a tool grant,
# and it did not hold: twice in one session a reviewer briefed that way had files written
# under it anyway -- once an unreviewed test reached a commit, once ~90 lines of core were
# rewritten. `Explore` has no Edit/Write, but it still has Bash -- a complete write path,
# already used mid-run to redden a concurrently-running suite -- so the fix is three
# sentences, not one: spawn Explore; still say "do not mutate the tree" because Bash
# remains; and tell the reader the author's own suite figures may be contaminated by a
# concurrent reviewer. That third sentence is the one most likely to get dropped.


def _explore_reviewer_unmet(text):
    folded = text.lower()
    unmet = set()
    if 'subagent_type: "explore"' not in folded:
        unmet.add("spawns-explore-not-general-purpose")
    if 'subagent_type: "general-purpose"' in folded:
        unmet.add("general-purpose-still-spawned")
    if "bash" not in folded:
        unmet.add("still-warns-about-bash")
    if "contaminat" not in folded:
        unmet.add("suite-figures-may-be-contaminated")
    return unmet


def test_developer_spawns_explore_not_general_purpose():
    text = (REPO_ROOT / "agents" / "developer.md").read_text(encoding="utf-8")
    unmet = _explore_reviewer_unmet(text)
    assert not unmet, (
        "agents/developer.md does not carry the Explore-reviewer fix: " + repr(sorted(unmet))
    )


def test_the_explore_reviewer_check_fires_on_the_general_purpose_spawn_it_replaced():
    """Positive control: the state before #82 -- general-purpose spawned, a brief
    sentence about not editing, nothing about Bash or contamination -- must be
    reported as unmet, or the check above is checking nothing.
    """
    before = (
        'Agent(subagent_type: "general-purpose", model: "sonnet", run_in_background: false)\n\n'
        'Tell it explicitly that it must not edit anything. It has Edit and Write.\n'
    )
    unmet = _explore_reviewer_unmet(before)
    assert unmet == {
        "spawns-explore-not-general-purpose",
        "general-purpose-still-spawned",
        "still-warns-about-bash",
        "suite-figures-may-be-contaminated",
    }, repr(sorted(unmet))


# ------------------------------------------------- reviewer return contract (#84)
#
# A reviewer spawn whose final message says only "findings reported above" returns
# empty to the caller -- everything it wrote before that line is invisible. An empty
# return currently reads as a clean review. The fix is a paragraph in the reviewer
# brief (the final message IS the return value; say NO FINDINGS and name what you
# checked, or say nothing) plus a rule for the caller: treat empty as `did not run`,
# never as clean.

REVIEWER_RETURN_ANCHORS = [
    ("final-message-is-the-return-value", ("final message", "return value")),
    ("no-findings-must-be-said-and-named", ("no findings",)),
    ("empty-return-is-did-not-run-not-clean", ("empty", "did not run")),
]


def _reviewer_return_unmet(text):
    folded = text.lower()
    return {
        name
        for name, anchors in REVIEWER_RETURN_ANCHORS
        if not all(anchor in folded for anchor in anchors)
    }


def test_developer_states_the_reviewer_return_contract():
    text = (REPO_ROOT / "agents" / "developer.md").read_text(encoding="utf-8")
    unmet = _reviewer_return_unmet(text)
    assert not unmet, (
        "agents/developer.md does not carry the reviewer-return contract: " + repr(sorted(unmet))
    )


def test_the_reviewer_return_check_fires_on_a_brief_that_never_states_it():
    """Positive control: prose that asks for findings and already states the
    did-not-run rule for a spawn that never ran, but never says the final message
    IS the return value and never mentions an empty one -- must be reported unmet.
    """
    before = (
        "Give each the diff and ask for findings.\n"
        "A review that did not execute must never render as a review that found "
        "nothing. Report did not run where it did not run.\n"
    )
    unmet = _reviewer_return_unmet(before)
    assert unmet == {
        "final-message-is-the-return-value",
        "no-findings-must-be-said-and-named",
        "empty-return-is-did-not-run-not-clean",
    }, repr(sorted(unmet))


# ------------------------------------- the ranking table, and the join to the search (#83)
#
# The plugin ran two class vocabularies and never joined them. `agents/auditor.md`
# searches by letter -- A an absence the caller cannot read, B a guard nominally on and
# effectively off, C untrusted text forging a boundary, D/F/H the platform band. The
# manager's table ranks by word -- `destroys`, `discloses`, `containment`, and the rest --
# and gate 3 decides what blocks a release out of those words.
#
# So a row could be ranked and never searched for. That is this repo's own defect class
# one layer over: a class ruled on, and not written where the brief is built from, is a
# class the next audit cannot find.
#
# The design these checks pin is *two vocabularies with one explicit join*, not one
# merged list. A search strategy and a severity are different things, and the map between
# them is many-to-many by construction: class A turns up findings that rank anywhere from
# `misreports` to `destroys`. So there is deliberately no per-letter-to-per-row assertion
# below -- a test asserting a fixed map would pin a design this change argues against.
#
# What is asserted is the join at the points where it can actually drift:
#
#   - the table is the single place the rows are written down, so no agent recopies it;
#   - every row carries a blocking verdict in one of exactly two recognised spellings,
#     because an unrecognised third spelling would otherwise read as "does not block";
#   - the release trigger names exactly the rows the table marks blocking -- add a row to
#     one and this goes red until you touch the other;
#   - both audit agents reference the table and separate `unranked` (classified, no row
#     fits) from `could not rank` (the table never reached me);
#   - the two-round cap does not quietly outrank the table.

MANAGER_SKILL = REPO_ROOT / "skills" / "manager" / "SKILL.md"
AUDIT_AGENTS = [REPO_ROOT / "agents" / "auditor.md", REPO_ROOT / "agents" / "release-auditor.md"]

RANKING_BLOCKS = "yes, unconditionally"
RANKING_FILES_IT = "can ship behind a filed issue"
RANKING_VERDICTS = (RANKING_BLOCKS, RANKING_FILES_IT)

# The table gained a second verdict column when release-blocking and embargo were split
# (#139): they are two questions and they disagree on one row. This file still checks the
# blocking column, which is what the release trigger joins against; the embargo column and
# the relationship between the two sets are checked in tests/test_embargo_routing.py. Said
# here rather than left out -- a column absent from a sweep reads like a column it cleared.
RANKING_HEADER = "| Class | Blocks a release? | Embargo when reported upstream? |"
RANKING_COLUMNS = 3
TRIGGER_MARKER = "marks blocking**"


def _ranking_table():
    """The rows as (name, verdict), or None if the table is not findable at all.

    None and [] are different answers and the callers below treat them that way: a
    table that moved is not a table with no rows.
    """
    lines = MANAGER_SKILL.read_text(encoding="utf-8").split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.strip() == RANKING_HEADER:
            start = i
            break
    if start is None:
        return None
    rows = []
    for line in lines[start + 2:]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            break
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) != RANKING_COLUMNS:
            break
        name = re.match(r"`([^`]+)`", cells[0])
        rows.append((name.group(1) if name else None, cells[1]))
    return rows


def _release_trigger_rows():
    """The rows the release trigger enumerates, or None if the marker is gone."""
    text = MANAGER_SKILL.read_text(encoding="utf-8")
    at = text.find(TRIGGER_MARKER)
    if at < 0:
        return None
    tail = text[at + len(TRIGGER_MARKER):]
    stop = tail.find("\n\n")
    segment = tail if stop < 0 else tail[:stop]
    return [m.group(1) for m in re.finditer(r"`([^`]+)`", segment)]


def test_the_ranking_table_is_findable_and_named():
    """Vacuity guard. Every check below reads this table; a table that moved would
    make them all pass over an empty list, which is the defect this plugin is named
    after arriving inside the suite meant to catch it.
    """
    rows = _ranking_table()
    assert rows is not None, (
        "no {!r} table in skills/manager/SKILL.md -- every ranking check below would "
        "pass vacuously".format(RANKING_HEADER)
    )
    assert len(rows) >= 5, "ranking table has {} rows, which is fewer than it had".format(len(rows))
    unnamed = [verdict for name, verdict in rows if name is None]
    assert not unnamed, "ranking rows with no `backticked` class name: {!r}".format(unnamed)
    names = [name for name, _ in rows]
    assert len(names) == len(set(names)), "duplicate ranking rows: {!r}".format(names)


def test_every_ranking_row_states_whether_it_blocks():
    """Two recognised spellings and no third. A row whose verdict is worded some new
    way is not a row that does not block -- it is a row nobody ruled on, and it must
    fail rather than be read as the lenient half.
    """
    rows = _ranking_table()
    assert rows is not None
    unruled = [(name, verdict) for name, verdict in rows if verdict not in RANKING_VERDICTS]
    assert not unruled, (
        "these ranking rows carry a verdict that is neither {!r} nor {!r}, so nothing "
        "can tell whether they block: {!r}".format(RANKING_BLOCKS, RANKING_FILES_IT, unruled)
    )


def _trigger_join_mismatch(rows, trigger):
    """Shared by the real check and its positive control."""
    if rows is None:
        return ("no ranking table",)
    if trigger is None:
        return ("no release trigger enumeration",)
    blocking = {name for name, verdict in rows if verdict == RANKING_BLOCKS}
    named = set(trigger)
    if not blocking and not named:
        # Two absences agreeing is not agreement. Symmetric difference cannot tell
        # "both parsers found nothing" from "both found the same thing", and the
        # first of those is a suite reporting a join it never looked at.
        return ("no blocking rows on either side",)
    return tuple(sorted(blocking ^ named))


def test_the_release_trigger_names_exactly_the_rows_that_block():
    """The join, and the reason it is worth more than the rows themselves.

    Two places in one file state the blocking set: the table's right-hand column and
    the release trigger. Nothing but this test makes the second follow the first, and
    a row added to the table alone is a class that blocks a release in the ranking and
    does not trigger one in the loop that reads it.
    """
    mismatch = _trigger_join_mismatch(_ranking_table(), _release_trigger_rows())
    assert not mismatch, (
        "the release trigger and the ranking table disagree about which classes block. "
        "In one and not the other: {!r}".format(mismatch)
    )


def test_the_trigger_join_fires_when_the_two_disagree():
    """Positive control. A set-equality assertion over two lists parsed out of the same
    file passes just as readily when both parsers return nothing, so the comparison is
    run against a pair that is wrong on purpose and must be reported.
    """
    rows = [
        ("destroys", RANKING_BLOCKS),
        ("ships-local-state", RANKING_BLOCKS),
        ("misreports", RANKING_FILES_IT),
    ]
    assert _trigger_join_mismatch(rows, ["destroys"]) == ("ships-local-state",)
    assert _trigger_join_mismatch(rows, ["destroys", "ships-local-state", "misreports"]) == (
        "misreports",
    )
    assert _trigger_join_mismatch(rows, ["destroys", "ships-local-state"]) == ()
    assert _trigger_join_mismatch(None, ["destroys"]) == ("no ranking table",)
    assert _trigger_join_mismatch(rows, None) == ("no release trigger enumeration",)
    # Both parsers finding nothing must not read as the two halves agreeing.
    assert _trigger_join_mismatch([], []) == ("no blocking rows on either side",)
    assert _trigger_join_mismatch(
        [("misreports", RANKING_FILES_IT)], []
    ) == ("no blocking rows on either side",)


def test_both_audit_agents_reference_the_ranking_table():
    """The structural half of #83. An agent that searches without ranking hands back
    findings the release gate cannot weigh; the reference is what makes the letters and
    the rows one system rather than two.
    """
    for path in AUDIT_AGENTS:
        text = path.read_text(encoding="utf-8")
        assert "${CLAUDE_PLUGIN_ROOT}/skills/manager/SKILL.md" in text, (
            "{} never points at the ranking table, so a finding it reports carries no "
            "row and gate 3 has nothing to weigh".format(path.relative_to(REPO_ROOT))
        )


def test_no_other_document_recopies_the_ranking_rows():
    """Same discipline as the portability shapes: the rows ship once. A copy anywhere
    else is the drift defect, and the copy that drifts is never the one anybody
    rereads. The control comes first -- if the rows were absent from the skill too,
    "absent from everywhere else" would be satisfied by their being absent everywhere.

    The sweep is every executable document except the skill that owns the table, not
    just the two audit agents. Scoping it to the agents that rank findings is how the
    copy in agents/triager.md survived the change that made it wrong: a guard aimed at
    the documents you were already thinking about reports nothing about the one you
    were not.
    """
    rows = _ranking_table()
    assert rows is not None
    names = [name for name, _ in rows]
    skill = MANAGER_SKILL.read_text(encoding="utf-8")
    missing = [n for n in names if "`{}`".format(n) not in skill]
    assert not missing, "rows unfindable in their own source: {!r}".format(missing)
    swept = 0
    for path in EXECUTABLE_PROSE:
        if path == MANAGER_SKILL:
            continue
        swept += 1
        text = path.read_text(encoding="utf-8")
        copied = [n for n in names if "`{}`".format(n) in text]
        assert not copied, (
            "{} carries its own copy of the ranking rows {!r} -- reference the table "
            "instead".format(path.relative_to(REPO_ROOT), copied)
        )
    assert swept, "swept no documents, so this checked nothing"


RANKING_STATE_ANCHORS = [
    # Named for what each actually checks. "names-the-table" and "finding-carries-a-row"
    # are two different claims and the first does not imply the second: a document can
    # mention the table exists and never say a finding must carry a row out of it.
    ("names-the-ranking-table", ("ranking table",)),
    ("finding-carries-a-row", ("ranking row",)),
    ("unranked-is-classified-and-no-row-fits", ("unranked",)),
    ("could-not-rank-is-the-table-never-arrived", ("could not rank",)),
]


def _flatten(text):
    """Fold case and collapse every run of whitespace to one space.

    Every anchor below is a multi-word phrase, and markdown wraps at 100 columns, so
    an anchor lands across a newline as soon as the paragraph is reflowed. Matching the
    raw text made this suite report "the document does not state the rule" for a
    document that stated it either side of a line break -- a checker whose finding is
    about its own reading, dressed as a finding about the file. It cost two rounds
    while this was being written.
    """
    return " ".join(text.lower().split())


def _ranking_states_unmet(text):
    folded = _flatten(text)
    return {
        name
        for name, anchors in RANKING_STATE_ANCHORS
        if not all(anchor in folded for anchor in anchors)
    }


def test_both_audit_agents_separate_unranked_from_could_not_rank():
    """Three states again, in the ranking rather than the search. "No row fits" is a
    finding worth the table gaining a row; "the table never reached me" is an audit
    that did not happen. They render identically as a missing row.
    """
    for path in AUDIT_AGENTS:
        unmet = _ranking_states_unmet(path.read_text(encoding="utf-8"))
        assert not unmet, "{}: {}".format(path.relative_to(REPO_ROOT), sorted(unmet))


def test_the_ranking_state_check_fires_on_a_brief_that_only_ranks():
    """Positive control: prose that asks for a ranking and even names the table, but
    offers no way to say the ranking could not be made, must report both third-state
    anchors unmet.
    """
    only_ranks = (
        "Rank every finding against the ranking table and report the row beside the "
        "class letter it was found by.\n"
    )
    assert _ranking_states_unmet(only_ranks) == {
        "finding-carries-a-row",
        "unranked-is-classified-and-no-row-fits",
        "could-not-rank-is-the-table-never-arrived",
    }
    # And a brief that says nothing at all must report every anchor unmet, or the
    # anchors are satisfied by prose rather than by the contract.
    assert _ranking_states_unmet("Read the diff and report what you find.") == {
        name for name, _ in RANKING_STATE_ANCHORS
    }


ROUND_CAP_ANCHOR = "not carry-forward material"
ROUND_CAP_DOCUMENTS = [
    MANAGER_SKILL,
    REPO_ROOT / "agents" / "release-auditor.md",
    REPO_ROOT / "commands" / "release.md",
]


def test_the_round_cap_does_not_quietly_outrank_the_table():
    """Gate 3, the release auditor and the release command all end round two by filing
    what remains and shipping over it. The table says some rows block unconditionally.
    Left unjoined the cap wins by being later, and a gate whose worst outcome is a filed
    issue is not a gate -- so every document that restates the cap must state the
    exception beside it. A document that carries only half of a rule is worse than one
    that carries neither, because it reads complete.

    The anchor is the whole clause rather than the word `carry-forward`, which any
    sentence about the cap contains and which would therefore pass forever.
    """
    for path in ROUND_CAP_DOCUMENTS:
        text = _flatten(path.read_text(encoding="utf-8"))
        assert ROUND_CAP_ANCHOR in text, (
            "{} states the two-round cap but never says a blocking row is {}".format(
                path.relative_to(REPO_ROOT), ROUND_CAP_ANCHOR
            )
        )


def test_the_round_cap_check_fires_on_the_cap_as_it_was_stated_before():
    """Positive control. The pre-#83 wording of the cap, which is what every one of
    those three documents said: complete, confident, and silent on the exception.
    """
    before = (
        "Two rounds, hard cap -- a competent audit of any non-trivial delta always "
        "finds something, so an unbounded findings-therefore-stop makes every release "
        "hostage to diminishing returns. After round two, file the rest against the "
        "next milestone and ship, carrying forward what is left."
    )
    assert ROUND_CAP_ANCHOR not in _flatten(before), (
        "the round-cap anchor is satisfied by the wording it was written to reject, "
        "so it would pass on all three documents unchanged"
    )


# ------------------------ a spawn that cannot resolve is could-not-run (#81)
#
# WHAT THESE DO NOT CHECK, said first because it is the whole reason they are shaped
# this way. Whether a shipped agent file *registers* as a spawnable `subagent_type` is
# a fact about the harness's agent registry. pytest cannot spawn an agent and cannot
# read that registry, so nothing below observes registration, and nothing below would
# have gone red while two of the four shipped agents were unreachable. These are a
# substitute for the test #81 asks for, and the substitution is the finding: a check
# asserting "four agent files ship and are well-formed" would have reported the broken
# state as healthy, which is the defect this repo is named after written a second time
# in the tool meant to detect it.
#
# What IS checkable is the consequence, and it is the half that blocks a release: a
# spawn whose name does not resolve must land in the third state and must have a
# defined next step, in the two documents that dispatch one.

# Character class kept identical to doctor.py's AGENT_DISPATCH_RE on purpose. A test
# regex narrower than the production one goes dark silently: the first `oss:` name with
# an underscore or a capital would still be cross-referenced at runtime and would stop
# being seen here, and a guard that quietly stopped matching reports clean.
AGENT_DISPATCH_RE = re.compile(r'subagent_type:\s*"oss:([A-Za-z0-9_-]+)"')

# Each dispatching document, and the definition file its own fallback must point at.
DISPATCHING_DOCUMENTS = [
    (REPO_ROOT / "agents" / "developer.md", "agents/auditor.md"),
    (REPO_ROOT / "commands" / "release.md", "agents/release-auditor.md"),
]


def _unresolvable_spawn_unmet(text, definition_file):
    """Anchors on the contract, not on the wording of any one paragraph.

    `general-purpose` is matched as a bare name on purpose. `_explore_reviewer_unmet`
    forbids the literal `subagent_type: "general-purpose"` in developer.md -- the
    reviewer spawn must stay `Explore`, which carries no Edit/Write -- so the fallback
    is named in prose rather than written as a spawn call. Do not "fix" that by adding
    the spawn-call literal: it would satisfy this check and break that one, and the
    two are about different spawns.
    """
    # Backticks dropped as well as whitespace folded. Every one of these anchors is a
    # phrase a markdown author will code-span part of -- `general-purpose`, the file
    # path -- and an anchor that a code span breaks reports the rule as missing from a
    # document that states it. Same failure `_flatten` was written for, one punctuation
    # mark further down.
    folded = _flatten(text).replace("`", "")
    unmet = set()
    if "does not resolve" not in folded:
        unmet.add("names-the-name-that-does-not-resolve")
    if "could not run" not in folded:
        unmet.add("an-unresolvable-spawn-is-could-not-run")
    if "general-purpose" not in folded:
        unmet.add("names-the-fallback-dispatch")
    # The joined phrase, not the two halves separately. developer.md already says
    # "general-purpose" three times for an unrelated reason -- the reviewer spawn is
    # Explore *rather than* general-purpose -- so a bare-name anchor was satisfied by
    # prose arguing the opposite, and reported the fallback as documented in a file
    # that never mentioned it.
    if "general-purpose with a pointer to " + definition_file.lower() not in folded:
        unmet.add("points-the-fallback-at-the-definition-file")
    if "quote the spawn error" not in folded:
        unmet.add("the-spawn-error-is-quoted-not-summarised")
    return unmet


ALL_UNRESOLVABLE_SPAWN_ANCHORS = {
    "names-the-name-that-does-not-resolve",
    "an-unresolvable-spawn-is-could-not-run",
    "names-the-fallback-dispatch",
    "points-the-fallback-at-the-definition-file",
    "the-spawn-error-is-quoted-not-summarised",
}


def test_the_dispatching_documents_exist():
    """Anti-vacuity. Every check below reads a file by name; a rename makes them all
    pass by never running, which is the state they exist to make impossible.
    """
    for path, _ in DISPATCHING_DOCUMENTS:
        assert path.is_file(), "{} is gone -- the checks below would vacuously pass".format(
            path.relative_to(REPO_ROOT)
        )


def test_every_dispatching_document_handles_a_name_that_does_not_resolve():
    """Both documents in one report. Asserting inside the loop stops at the first
    failure, which hides whether the second document has the same gap or a different
    one -- and the whole point of #81 is that two documents were wrong at once.
    """
    gaps = {}
    for path, definition_file in DISPATCHING_DOCUMENTS:
        unmet = _unresolvable_spawn_unmet(path.read_text(encoding="utf-8"), definition_file)
        if unmet:
            gaps[str(path.relative_to(REPO_ROOT))] = sorted(unmet)
    assert not gaps, (
        "a document dispatches an oss: agent without saying what happens when the "
        "name does not resolve: {}".format(gaps)
    )


def test_the_unresolvable_spawn_check_fires_on_the_spawn_as_it_was_stated_before():
    """Positive control, and it is the actual prior text of both documents.

    Both already said a spawn that did not run is not a clean audit. Neither said what
    to do about a name that never resolves, so the reader hit an error with no defined
    next step -- and #81 is a release whose blocking gate dispatched to nothing for two
    versions. Every anchor must report unmet against these, or the check above says
    nothing about whether the gap was closed.
    """
    developer_before = (
        'Agent(subagent_type: "oss:auditor", model: "sonnet")\n\n'
        "A review that did not execute must never render as a review that found "
        "nothing. Treat an empty final message as did not run, never as clean.\n"
    )
    assert (
        _unresolvable_spawn_unmet(developer_before, "agents/auditor.md")
        == ALL_UNRESOLVABLE_SPAWN_ANCHORS
    ), repr(sorted(_unresolvable_spawn_unmet(developer_before, "agents/auditor.md")))

    # release.md's prior text already carried "could not run" for a different reason --
    # the gate's own third outcome -- so only that one anchor was met. Pinning the
    # difference keeps the check from being read as evidence about the other four.
    release_before = (
        'Agent(subagent_type: "oss:release-auditor", run_in_background: false)\n\n'
        "A spawn that did not run is could not run, never a clean audit -- if the "
        "agent fails to start or comes back empty, that is the third outcome and the "
        "same stop applies.\n"
    )
    assert _unresolvable_spawn_unmet(release_before, "agents/release-auditor.md") == (
        ALL_UNRESOLVABLE_SPAWN_ANCHORS - {"an-unresolvable-spawn-is-could-not-run"}
    ), repr(sorted(_unresolvable_spawn_unmet(release_before, "agents/release-auditor.md")))


def test_the_unresolvable_spawn_check_passes_on_prose_that_states_the_whole_contract():
    """The must-fire half of the pair.

    Every assertion above is that something is *absent* from a fixture, and an absence
    check passes just as well when the matcher is broken and matches nothing at all.
    One fixture that states the contract in different words must come back clean, or
    the five anchors above are unfalsifiable.
    """
    complete = (
        "If the spawn errors because the name does not resolve, that is could not "
        "run, not a clean audit. Quote the spawn error verbatim, then re-dispatch to "
        "general-purpose with a pointer to agents/auditor.md.\n"
    )
    assert _unresolvable_spawn_unmet(complete, "agents/auditor.md") == set()
    assert _unresolvable_spawn_unmet("", "agents/auditor.md") == ALL_UNRESOLVABLE_SPAWN_ANCHORS


# ------------------------------------- every dispatched name ships a definition (#81)


def _dispatched_agent_names(documents):
    """name -> the documents that spawn it. Scanned, never listed.

    Rendered with `as_posix()` rather than `str()`, because the document paths this
    returns are compared against literals written in this file. `str(Path("a/b.md"))`
    is `a\\b.md` on Windows, so a POSIX literal in an assertion fails there and only
    there -- which is what happened: all four Windows legs, on a helper whose own
    author graded "no hardcoded POSIX literals in the new assertions" as reasoned.
    Normalising at the producer fixes every assertion at once and cannot be
    reintroduced by the next literal somebody writes.
    """
    found = {}
    for path, text in documents:
        for name in AGENT_DISPATCH_RE.findall(text):
            found.setdefault(name, set()).add(Path(path).as_posix())
    return found


def test_this_scan_and_doctors_use_the_same_pattern():
    """A comment saying "keep these identical" is not a guard. doctor.py runs the same
    cross-reference at runtime; if the two patterns drift, one of them stops seeing a
    dispatch the other still sees, and the narrower one reports clean while checking
    less. Compared as text because the two live in different modules.
    """
    doctor_source = (REPO_ROOT / "scripts" / "doctor.py").read_text(encoding="utf-8")
    assert AGENT_DISPATCH_RE.pattern in doctor_source, (
        "scripts/doctor.py no longer contains this suite's dispatch pattern {!r}, so the "
        "two cross-references can disagree about what a dispatch looks like".format(
            AGENT_DISPATCH_RE.pattern
        )
    )


def test_the_dispatch_scan_finds_the_names_that_are_there():
    """Anti-vacuity for the cross-reference below: a regex that matched nothing would
    report every dispatched name as accounted for.
    """
    found = _dispatched_agent_names(_executable_documents())
    assert found, "no oss: agent dispatch found in any executable document"
    assert {"auditor", "release-auditor"} <= set(found), sorted(found)


def test_every_dispatched_agent_name_ships_a_definition_file():
    """A dispatch to a name with no file cannot work under any harness. This is green
    today and it is not evidence that the four register -- see the block comment above.
    """
    shipped = {path.stem for path in AGENTS}
    dispatched = _dispatched_agent_names(_executable_documents())
    missing = {name: sorted(where) for name, where in dispatched.items() if name not in shipped}
    assert not missing, "dispatched with no agents/<name>.md: {}".format(missing)


def test_the_dispatch_cross_reference_fires_on_a_name_with_no_file():
    """Positive control: a document spawning a name nothing ships must be reported."""
    fixture = [(Path("commands/made-up.md"), 'Agent(subagent_type: "oss:ghost")')]
    dispatched = _dispatched_agent_names(fixture)
    assert dispatched == {"ghost": {"commands/made-up.md"}}
    shipped = {path.stem for path in AGENTS}
    assert [name for name in dispatched if name not in shipped] == ["ghost"]


# ------------------------------------------- the install step names the reload (#140)
#
# An installed-but-unreloaded session resolves all seven skills and none of the four
# agents, which reads as a working plugin with a broken agents/ directory rather than
# as a missing step. That silence produced two wrong bug reports against this repo.
# The remedy is one command and it was documented nowhere.

# Each anchor is a phrase the pre-#140 README did not contain. A bare "agent" was the
# first attempt and it was inert: README.md already said "agent" twice, so that half of
# the pair passed against the unfixed file and only the command anchor was working. An
# anchor satisfied by prose that predates the change checks nothing, and the fabricated
# "before" fixture below could not reveal it, because it is one line rather than the
# whole file.
RELOAD_ANCHORS = [
    ("names-the-reload-command", "/reload-plugins"),
    ("names-what-goes-stale", "agent registry"),
    ("names-the-error-the-reader-will-actually-see", "agent type"),
]


def _reload_unmet(text):
    folded = _flatten(text)
    return {name for name, anchor in RELOAD_ANCHORS if anchor not in folded}


def test_the_readme_install_step_names_the_reload():
    readme = REPO_ROOT / "README.md"
    assert readme.is_file(), "README.md is gone -- this check would vacuously pass"
    unmet = _reload_unmet(readme.read_text(encoding="utf-8"))
    assert not unmet, "README.md's install step does not carry the reload: " + repr(sorted(unmet))


RELOAD_BLOCK_START = "**Then run `/reload-plugins`"
RELOAD_BLOCK_END = "Installing pulls in"


def test_the_reload_check_fires_on_the_readme_with_the_new_block_removed():
    """Positive control against the real file, not a fabricated line.

    A one-line "before" fixture cannot show that an anchor is carried by the new text
    rather than by something else already in README.md -- and one of these anchors was
    a bare "agent", which the unfixed README satisfied twice over. Cutting the added
    block out of the current file and requiring every anchor to go unmet is the claim
    that actually matters: the install step is where this lives, and deleting it is
    visible.
    """
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    start = text.index(RELOAD_BLOCK_START)
    end = text.index(RELOAD_BLOCK_END, start)
    without = text[:start] + text[end:]
    assert _reload_unmet(without) == {name for name, _ in RELOAD_ANCHORS}, (
        "an anchor survives deleting the whole install-step block, so it is satisfied "
        "by prose elsewhere in README.md and checks nothing"
    )
    # Must-fire half: prose carrying every anchor comes back clean, so the assertion
    # above is about the text rather than about a matcher that matches nothing.
    assert (
        _reload_unmet(
            "Run /reload-plugins: installing mid-session leaves the agent registry "
            "stale, and a spawn answers Agent type not found."
        )
        == set()
    )


# --------- a defect in a declared dependency is filed on that dependency's board (#143)
#
# The refusal this replaces was reasonable-sounding and cost a confirmed, reproduced
# cross-repo defect its filing: "that is a decision about somebody else's roadmap".
# Anchors are phrases only the new text carries -- each was grepped against the
# pre-change documents first, because an anchor the file already contained is a green
# tick over a sentence nobody wrote.

UPSTREAM_FILING_ANCHORS = [
    ("scoped-to-declared-dependencies", ("declared dependency",)),
    ("filing-is-part-of-the-job", ("part of finishing the work",)),
    ("the-arbitrary-third-party-case-is-bounded", ("third-party",)),
    ("a-blocking-class-does-not-go-to-a-public-tracker", ("embargo",)),
    # Not "deliberately not": the skill already contains that string, in "deliberately
    # not one list", so it passed against the unchanged file -- a green tick over a
    # sentence nobody had written. Caught by running the guard before the prose.
    ("deliberately-not-reported-is-a-decision-with-a-reason", ("is a decision with a reason",)),
]

UPSTREAM_FILING_DOCUMENTS = [
    MANAGER_SKILL,
    REPO_ROOT / "agents" / "developer.md",
]


def _upstream_filing_unmet(text):
    folded = _flatten(text)
    return {
        name
        for name, anchors in UPSTREAM_FILING_ANCHORS
        if not all(anchor in folded for anchor in anchors)
    }


def test_both_documents_state_the_upstream_filing_duty():
    for path in UPSTREAM_FILING_DOCUMENTS:
        unmet = _upstream_filing_unmet(path.read_text(encoding="utf-8"))
        assert not unmet, "{}: {}".format(path.relative_to(REPO_ROOT), sorted(unmet))


def test_the_manager_derives_the_tracker_rather_than_listing_it():
    """Which trackers those are is data. The derivation already exists; naming the
    functions is what stops a list of repo names being written into shared prose,
    which test_no_repo_specific_spellings_in_prose would reject anyway -- so the
    rule without the derivation is a rule with no way to be obeyed.
    """
    folded = _flatten(MANAGER_SKILL.read_text(encoding="utf-8"))
    for symbol in ("declared_dependencies", "dependency_repositories"):
        assert symbol.lower() in folded, (
            "the manager skill states the upstream filing rule but never says where "
            "the tracker comes from: {} is unnamed".format(symbol)
        )


def test_the_manager_separates_could_not_file_from_did_not_file():
    folded = _flatten(MANAGER_SKILL.read_text(encoding="utf-8"))
    assert "could not file" in folded, (
        "the filing outcome has two failure states -- the tracker did not resolve or "
        "the filing failed, versus a decision not to file -- and only the second one "
        "is written down"
    )


def test_the_developer_reports_upstream_rather_than_filing_itself():
    """The developer's publishing clause is unconditional, and opening an issue on
    another repo is publishing. So the duty lands as a report, not a filing.
    """
    folded = _flatten((REPO_ROOT / "agents" / "developer.md").read_text(encoding="utf-8"))
    assert "do not open the upstream issue" in folded, (
        "developer.md states the upstream duty without saying who performs it, which "
        "reads as permission to file against another repo mid-task"
    )


def test_the_upstream_filing_check_fires_on_the_refusal_it_replaces():
    """Positive control, both halves. The must-not-fire half is the sentence that
    actually shipped on the tracker; every anchor has to come back unmet, or the
    guard would have passed against the documents before this change.
    """
    refusal = (
        "Needs a companion issue on the dependency that owns the fix. Not filed yet "
        "-- filing there is a decision about somebody else's roadmap and belongs to "
        "whoever owns that board."
    )
    assert _upstream_filing_unmet(refusal) == {name for name, _ in UPSTREAM_FILING_ANCHORS}
    # Must-fire half: prose carrying every anchor comes back clean, so the assertion
    # above is about the text rather than about a matcher that never matches.
    carries_it = (
        "A defect you find in a declared dependency is filed on that dependency's "
        "tracker, and that is part of finishing the work. For an arbitrary "
        "third-party dependency it is a judgement rather than a duty. A finding in a "
        "blocking row goes to the embargo path, never to a public tracker. And "
        "deliberately not filed is a decision with a reason, never a default."
    )
    assert _upstream_filing_unmet(carries_it) == set()


# ------------------- a label PATCH replaces the whole set, and the freeze is a label (#137)

LABEL_WRITE_ANCHORS = [
    ("patch-replaces-rather-than-adds", ("replaces the whole label set",)),
    ("recount-after-the-last-write", ("after the last label write",)),
]


def _label_write_unmet(text):
    folded = _flatten(text)
    return {
        name
        for name, anchors in LABEL_WRITE_ANCHORS
        if not all(anchor in folded for anchor in anchors)
    }


def test_the_freeze_step_states_that_a_label_patch_replaces():
    """The cohort freeze is the backlog's only terminating condition, and a later
    priority write removes the cohort label with exit 0 and no error. A freeze that
    can be silently undone by the next write is not a freeze.
    """
    unmet = _label_write_unmet(MANAGER_SKILL.read_text(encoding="utf-8"))
    assert not unmet, "skills/manager/SKILL.md: {}".format(sorted(unmet))


def test_the_label_write_check_fires_on_the_freeze_step_as_it_was():
    before = (
        "At each release tag, label everything then-open as a frozen cohort in the "
        "same minute as the tag. Nothing joins a cohort, ever, so it can only shrink. "
        "Cohort labels are the maintainer's act, by hand; the triager must never "
        "write one."
    )
    assert _label_write_unmet(before) == {name for name, _ in LABEL_WRITE_ANCHORS}
    assert (
        _label_write_unmet(
            "PATCH replaces the whole label set, so add with POST and re-count the "
            "cohort after the last label write of the tick."
        )
        == set()
    )


# ------------------- a short sha answers [] and exits 0 (#137)

SHORT_SHA_ANCHORS = [
    ("resolve-the-sha-first", ("rev-parse",)),
    ("say-what-a-short-sha-does", ("40-character",)),
]


def _short_sha_unmet(text):
    folded = _flatten(text)
    return {
        name
        for name, anchors in SHORT_SHA_ANCHORS
        if not all(anchor in folded for anchor in anchors)
    }


def test_the_release_gate_resolves_the_sha_before_counting_workflows():
    """Gate 1 counts workflows on the exact commit being tagged. An abbreviated sha
    returns an empty run list and exits 0, which is indistinguishable from a commit no
    workflow ran on -- this repo's own defect class, sitting in the release gate.
    """
    unmet = _short_sha_unmet(MANAGER_SKILL.read_text(encoding="utf-8"))
    assert not unmet, "skills/manager/SKILL.md: {}".format(sorted(unmet))


def test_the_short_sha_check_fires_on_the_gate_as_it_was():
    before = (
        "The default branch is green at leg level for the exact commit being tagged "
        "-- and count the workflows, not just the runs. A workflow declared in the "
        "workflows directory but absent from the run list is UNKNOWN, never a pass."
    )
    assert _short_sha_unmet(before) == {name for name, _ in SHORT_SHA_ANCHORS}
    assert (
        _short_sha_unmet(
            "Pass the output of git rev-parse, never an abbreviated sha: the full "
            "40-character sha returns the runs and the short form returns nothing."
        )
        == set()
    )


# ------------------- the full suite is optional, the targeted red-green is not (#141)

SUITE_RULE_ANCHORS = [
    ("the-full-suite-is-optional", ("full suite is optional",)),
    ("a-rebase-makes-it-mandatory", ("after a rebase",)),
    ("never-re-run-to-re-read-a-failure", ("failure you have already seen",)),
]


def _suite_rule_unmet(text):
    folded = _flatten(text)
    return {
        name
        for name, anchors in SUITE_RULE_ANCHORS
        if not all(anchor in folded for anchor in anchors)
    }


def test_the_developer_states_when_the_full_suite_is_worth_the_wall_clock():
    """The optional half without the rebase clause reads as permission to skip the run
    that has caught the most: three pull requests went red the same day on a defect
    only the full suite on a rebased tree could see.
    """
    unmet = _suite_rule_unmet((REPO_ROOT / "agents" / "developer.md").read_text(encoding="utf-8"))
    assert not unmet, "agents/developer.md: {}".format(sorted(unmet))


def test_the_suite_rule_check_fires_on_the_instruction_it_replaces():
    before = (
        "Test first, and watch it fail. Run the repo's test_command. A test written "
        "after the fix asserts what the code happens to do. Report the red output and "
        "the green output separately, as the shortest decisive lines."
    )
    assert _suite_rule_unmet(before) == {name for name, _ in SUITE_RULE_ANCHORS}
    assert (
        _suite_rule_unmet(
            "The full suite is optional, and mandatory after a rebase onto the "
            "default branch. Never re-run it to watch a failure you have already seen."
        )
        == set()
    )


# ------------------- the tooling friction the agent is the only one who can see (#141)

FRICTION_ANCHORS = [
    ("the-duty-is-named", ("friction",)),
    ("it-is-signal-only-the-agent-has", ("signal nobody else can see",)),
    ("it-has-somewhere-to-go-in-a-fixed-schema", ("adjacent",)),
]


def _friction_unmet(text):
    folded = _flatten(text)
    return {
        name
        for name, anchors in FRICTION_ANCHORS
        if not all(anchor in folded for anchor in anchors)
    }


def test_the_developer_reports_tooling_friction():
    """A duty with no field to land in is a duty that evaporates at report time, so
    the check is the pair: the duty, and where it goes in a schema that refuses
    unknown keys.
    """
    unmet = _friction_unmet((REPO_ROOT / "agents" / "developer.md").read_text(encoding="utf-8"))
    assert not unmet, "agents/developer.md: {}".format(sorted(unmet))


def test_the_friction_check_fires_on_a_brief_that_only_reports_the_code():
    before = (
        "Unfiled findings go in adjacent: anything you found that nobody filed, with "
        "whether you fixed it or are handing it over to be filed."
    )
    assert _friction_unmet(before) == {
        "the-duty-is-named",
        "it-is-signal-only-the-agent-has",
    }
    assert _friction_unmet("Read the diff and report what you find.") == {
        name for name, _ in FRICTION_ANCHORS
    }
    assert (
        _friction_unmet(
            "Report every friction you hit using the ops, one line each, in adjacent "
            "-- for the length of this task that is signal nobody else can see."
        )
        == set()
    )


# ------------------- the bar on what a friction line has to have cost (#300)
#
# The duty above says report every friction; this says what qualifies. The two are
# checked separately on purpose: an edit that kept the duty and deleted the bar is
# exactly the regression, and a single anchor set covering both would still pass it.

FRICTION_BAR_ANCHORS = [
    ("the-bar-is-what-it-cost", ("cost this run something you can name",)),
    ("a-usable-op-is-not-friction", ("is not friction",)),
    ("a-preference-goes-nowhere", ("a preference is not reported anywhere",)),
    ("the-third-state-is-cannot-tell", ("tooling-unclear:",)),
]

REACHABILITY_ANCHORS = [
    ("the-class-must-be-reachable", ("the class is reachable",)),
    ("an-unreachable-class-is-not-a-filing", ("a class you cannot reach is not a filing",)),
    ("it-goes-in-the-pull-request", ("say it in the pull request",)),
]

# The meter check is the pair, and it has to be: asserting only that the disarming
# sentence is gone also passes against a document that lost the whole paragraph, and
# asserting only that the replacement arrived also passes against one carrying both.
METER_MUST_CARRY = [
    ("raising-the-bar-is-not-throttling", "raising the bar on what counts as a finding is not throttling"),
    ("the-number-is-not-inert", "the number is not a target and it is not inert"),
    ("the-two-render-identically", "render identically in the count"),
]
METER_MUST_NOT_CARRY = [
    ("the-licence-to-ignore-it-is-gone", "exists to be known, not optimised"),
]
# The anti-throttle rule is not what changed and must survive the edit.
METER_KEEPS = [
    ("discovery-is-still-not-throttled", "must not be throttled to make this number look better"),
]


def _unmet(text, anchors):
    folded = _flatten(text)
    return {
        name
        for name, anchor_group in anchors
        if not all(anchor in folded for anchor in anchor_group)
    }


def _meter_unmet(text):
    folded = _flatten(text)
    unmet = {name for name, phrase in METER_MUST_CARRY + METER_KEEPS if phrase not in folded}
    unmet |= {name for name, phrase in METER_MUST_NOT_CARRY if phrase in folded}
    return unmet


def test_a_friction_line_has_to_name_what_it_cost():
    """Without this, the duty above is a standing instruction to report anything
    noticed -- and an agent that finished every call cleanly still owes a list.
    """
    unmet = _unmet(
        (REPO_ROOT / "agents" / "developer.md").read_text(encoding="utf-8"),
        FRICTION_BAR_ANCHORS,
    )
    assert not unmet, "agents/developer.md: {}".format(sorted(unmet))


def test_the_friction_bar_check_fires_on_the_duty_without_the_bar():
    """Positive control. The text this replaced states the duty in full and states
    no bar at all, so every anchor must come back unmet -- an assertion that the bar
    is present also passes against a fixture where nothing was checked.
    """
    before = (
        "Every UX problem you hit while using the ops goes in the report, one line each: "
        "a field missing from an op, a second call needed to get what the first should have "
        "returned, an error naming what is wrong but not what to do. If you hit no friction, "
        "that is checked with no tooling: items, which is a claim."
    )
    assert _unmet(before, FRICTION_BAR_ANCHORS) == {name for name, _ in FRICTION_BAR_ANCHORS}


def test_the_class_clause_requires_a_reachable_class():
    unmet = _unmet(
        (REPO_ROOT / "agents" / "developer.md").read_text(encoding="utf-8"),
        REACHABILITY_ANCHORS,
    )
    assert not unmet, "agents/developer.md: {}".format(sorted(unmet))


def test_the_reachability_check_fires_on_the_bare_class_clause():
    """Positive control, and the fixture is the exact clause that shipped: a class
    with no reachability requirement is the door every claim-about-a-claim finding
    walked through.
    """
    before = (
        "File it when any one holds: it needs a design decision you were not briefed to "
        "make; it would double the diff; or what you are holding is the class rather than "
        "the instance."
    )
    assert _unmet(before, REACHABILITY_ANCHORS) == {name for name, _ in REACHABILITY_ANCHORS}


ISSUE_BODY_ANCHORS = [
    ("it-is-written-for-an-engineer", ("an issue body is tech to tech",)),
    ("the-four-parts-are-named", ("symptom", "mechanism", "what would settle it")),
    ("code-is-quoted-not-described", ("quote code, do not describe it",)),
    ("the-narrative-is-cut", ("how you found it",)),
    ("an-unfillable-part-is-said", ("a part you cannot fill is a sentence naming",)),
]


def test_an_issue_body_has_a_stated_form():
    """The loop's filings are read by whoever picks the item up months later, and a
    body that needs the story to be usable is paid on every read.
    """
    unmet = _unmet(
        (REPO_ROOT / "skills" / "manager" / "SKILL.md").read_text(encoding="utf-8"),
        ISSUE_BODY_ANCHORS,
    )
    assert not unmet, "skills/manager/SKILL.md: {}".format(sorted(unmet))


def test_the_issue_body_check_fires_on_a_skill_that_only_says_where_to_file():
    """Positive control. Naming the op that files is not stating what goes in the
    body -- the shape the skill carried before this rule.
    """
    before = "Filing goes through gh-issue-create:@FILE, which reads the repo from its payload."
    assert _unmet(before, ISSUE_BODY_ANCHORS) == {name for name, _ in ISSUE_BODY_ANCHORS}


def test_the_intake_meter_is_not_disarmed():
    """The ratio is measured with four states and was closed by a sentence that reads
    as do not act on it. Both halves are checked: the licence is gone, and the rule it
    was attached to -- do not throttle discovery -- survived.
    """
    unmet = _meter_unmet(
        (REPO_ROOT / "skills" / "manager" / "SKILL.md").read_text(encoding="utf-8")
    )
    assert not unmet, "skills/manager/SKILL.md: {}".format(sorted(unmet))


def test_the_meter_check_fires_in_both_directions():
    """Two fixtures, because one cannot cover both failure modes. The first carries
    the licence and none of the replacement; the second carries the replacement and
    dropped the anti-throttle rule with it -- an over-correction that reads as a fix.
    """
    shipped = (
        "The review layer is a discovery machine and must not be throttled to make this "
        "number look better. This number exists to be known, not optimised."
    )
    assert _meter_unmet(shipped) == {
        "raising-the-bar-is-not-throttling",
        "the-number-is-not-inert",
        "the-two-render-identically",
        "the-licence-to-ignore-it-is-gone",
    }
    overcorrected = (
        "Raising the bar on what counts as a finding is not throttling. The number is not "
        "a target and it is not inert: filings that cost somebody something and filings that "
        "cost nobody anything render identically in the count."
    )
    assert _meter_unmet(overcorrected) == {"discovery-is-still-not-throttled"}


# ------------- a convention change is not finished until the diagnostic reports it
#
# The failure this guards lives in the composition of two individually correct
# commits: scaffold learned to decline the owned trio and doctor went on reporting
# all three absent with the remedy "run the command that now declines". Neither diff
# was wrong on its own, which is why a rule about the pair has to be written down.

DOCTOR_CONVENTION_ANCHORS = [
    ("the-diagnostic-has-to-report-the-new-convention", ("reports the new convention",)),
]

DOCTOR_CONVENTION_DOCUMENTS = [
    MANAGER_SKILL,
    REPO_ROOT / "agents" / "developer.md",
]


def _doctor_convention_unmet(text):
    folded = _flatten(text)
    return {
        name
        for name, anchors in DOCTOR_CONVENTION_ANCHORS
        if not all(anchor in folded for anchor in anchors)
    }


def test_both_documents_tie_a_convention_change_to_the_diagnostic():
    for path in DOCTOR_CONVENTION_DOCUMENTS:
        unmet = _doctor_convention_unmet(path.read_text(encoding="utf-8"))
        assert not unmet, "{}: {}".format(path.relative_to(REPO_ROOT), sorted(unmet))


def test_the_developer_separates_an_edit_from_a_derivation_that_already_covers_it():
    """"Always edit doctor.py" would be the wrong rule: a key that flows through a
    derivation the diagnostic already consumes is reported without a line being added.
    Which of the two happened is the part a maintainer cannot re-derive from the diff,
    so the report has to say it and name the derivation.
    """
    folded = _flatten((REPO_ROOT / "agents" / "developer.md").read_text(encoding="utf-8"))
    assert "name the derivation" in folded, (
        "developer.md ties a convention change to the diagnostic but offers only one "
        "way to satisfy it, so a derivation that already covers the change reads as "
        "an unmet requirement"
    )


def test_the_developer_states_what_to_do_when_another_lane_holds_the_file():
    """The third arm, and the one that makes the rule survive a fleet: the diagnostic
    is one file, several agents run at once, and reaching into another lane's file is
    worse than the defect. Silently skipping it is worse again.
    """
    folded = _flatten((REPO_ROOT / "agents" / "developer.md").read_text(encoding="utf-8"))
    assert "held by another lane" in folded, (
        "developer.md requires the diagnostic to be updated and never says what to do "
        "when the file is out of bounds, which leaves reaching into it and dropping it "
        "as the two available readings"
    )


# ------------------------ the payload the developer writes is the payload the loop
# opens (#160)
#
# agents/developer.md states a four-field pull request payload and the report schema
# validates it, including that `head` is the branch the agent is on. skills/manager/
# SKILL.md is the document the loop loads on every tick, and it is the consumer. A
# contract stated in the producer and thin in the consumer is not a contract: the
# observed cost was a maintainer re-deriving `head` and `base` by hand on ten pull
# requests, on every one of which the payload was already right.
#
# The join is the check worth having, for the same reason it was worth having between
# the ranking table and the release trigger: two documents describing one shape drift,
# and the copy that drifts is never the one anybody rereads. The anchors beside it
# cover the three things the join cannot see -- that the fields must not be rewritten,
# that an unreadable payload is a third state, and that a maintainer's verification is
# a different voice from the agent's claims.

PR_PAYLOAD_PRODUCER = REPO_ROOT / "agents" / "developer.md"
PR_PAYLOAD_SCHEMA = REPO_ROOT / "schemas" / "agent-report.schema.json"
PR_PAYLOAD_CONSUMER_HEADING = "## Opening the pull request"


def _schema_payload_required():
    """The payload's required fields, from the schema -- the enforced authority.

    The join below runs against this rather than against the prose example, and the
    difference is the whole point: the example is a copy, and a join between two
    copies checks that they agree with each other while both drift away from the
    thing that is actually validated. `forge_payload` also *defines* optional fields
    (`draft`, `labels`); required is the set a consumer must know arrives filled in.

    None means `forge_payload` is not in the schema at all.
    """
    stack = [json.loads(PR_PAYLOAD_SCHEMA.read_text(encoding="utf-8"))]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if "forge_payload" in node:
                return sorted(node["forge_payload"].get("required", []))
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None


def _payload_fields():
    """The payload's field names out of the JSON example in agents/developer.md.

    Parsed as JSON off the fence rather than pattern-matched on `"title"` coming
    first. Anchoring on a key order made a legal reordering of the example return
    None, and None is rendered by the callers as "no example in the file" -- a
    tool-produced absence reported as an absence in the document, inside the block
    written to prevent exactly that.

    None means no parseable json fence carrying payload keys, which is a different
    answer from a fence with no fields, and the callers keep them apart.
    """
    text = PR_PAYLOAD_PRODUCER.read_text(encoding="utf-8")
    for block in re.findall(r"```json\s*(.*?)```", text, re.S):
        # A fence that does not parse is skipped rather than failing the run --
        # another fence may be the payload one.
        try:
            parsed = json.loads(block)
        except ValueError:
            continue
        if isinstance(parsed, dict) and "head" in parsed and "base" in parsed:
            return sorted(parsed)
    return None


def _payload_consumer_section():
    """The manager skill's consumer section, or None if the heading moved.

    The stop is a heading match rather than a substring search for a newline
    followed by two hashes, which additionally catches a heading at offset 0.

    It does NOT make this robust against the hazard worth naming, and saying so is
    the point: this section tells maintainers to write a literal
    "## Verified by the maintainer" heading into a pull request body. Written at the
    start of a line without a code span, that line is a `##` heading by every
    reasonable reading, and *any* heading-based extractor stops there -- measured,
    not assumed. Every anchor after it would then report "the document does not
    state the rule" about text sitting in the file, which is the failure `_flatten`
    was written for. What actually prevents it today is that the skill writes the
    heading inside a code span, and that is a property of the prose, not of this
    parser. `test_the_payload_contract_and_its_consumer_section_are_both_findable`
    therefore checks the section still reaches its last bullet, so a truncation
    fails loudly there instead of silently emptying the anchors.
    """
    text = MANAGER_SKILL.read_text(encoding="utf-8")
    at = text.find(PR_PAYLOAD_CONSUMER_HEADING)
    if at < 0:
        return None
    tail = text[at + len(PR_PAYLOAD_CONSUMER_HEADING):]
    stop = re.search(r"^## ", tail, re.M)
    return tail if stop is None else tail[:stop.start()]


def _payload_join_mismatch(fields, section):
    """Fields the producer defines and the consumer never names. Shared with its
    positive control, so the control exercises the comparison itself rather than a
    second implementation of it.
    """
    if fields is None:
        return ("no required field list in the schema",)
    if section is None:
        return ("no consumer section in skills/manager/SKILL.md",)
    if not fields:
        # An empty contract would make "the consumer names every field" true by
        # having nothing to name -- the vacuous pass this whole block exists to
        # refuse.
        return ("no fields on either side",)
    folded = _flatten(section)
    return tuple(f for f in fields if "`{}`".format(f) not in folded)


def test_the_payload_contract_and_its_consumer_section_are_both_findable():
    """Vacuity guard, first. Every check below reads one of these three."""
    required = _schema_payload_required()
    assert required, (
        "no `forge_payload` required list in {} -- the join below would pass over "
        "nothing".format(PR_PAYLOAD_SCHEMA.relative_to(REPO_ROOT))
    )
    assert _payload_fields() is not None, (
        "no parseable json payload example in agents/developer.md -- the producer "
        "check below would pass over nothing"
    )
    section = _payload_consumer_section()
    assert section is not None, (
        "no {!r} section in skills/manager/SKILL.md -- the loop's own document has "
        "nowhere the payload contract could be stated".format(PR_PAYLOAD_CONSUMER_HEADING)
    )
    # Truncation guard. A `##` heading written inside this section -- which is one
    # unbackticked edit away, since the section tells maintainers to write exactly
    # such a heading -- would cut the extractor short, and every anchor below would
    # then report the document as silent on rules it states. That must fail here,
    # loudly and once, rather than there, quietly and four times.
    assert _flatten(section).rstrip().endswith("it is the one that looks correct."), (
        "the {!r} section does not run to its last bullet, so the extractor stopped "
        "early and every anchor below is being checked against a fragment".format(
            PR_PAYLOAD_CONSUMER_HEADING
        )
    )


def test_the_producer_example_shows_every_field_the_schema_requires():
    """The example in agents/developer.md is what an agent copies, so a required
    field missing from it is a payload the validator refuses, written by an agent
    that followed its own instructions. Asserted one way only: the example may show
    an optional field (`draft`, `labels`) without that being a defect.
    """
    required = _schema_payload_required()
    fields = _payload_fields()
    assert required and fields is not None
    missing = sorted(set(required) - set(fields))
    assert not missing, (
        "the schema requires {!r} and the example in agents/developer.md does not "
        "show them, so an agent copying the example writes a payload the validator "
        "refuses".format(missing)
    )


def test_the_consumer_names_every_field_the_payload_contract_requires():
    """The join, and it runs against the schema rather than against the prose.

    `schemas/agent-report.schema.json` is the enforced authority; skills/manager/
    SKILL.md is what the loop actually reads each tick. A required field the
    consumer never names is a field the maintainer will supply by hand -- the
    observed defect -- and the hand-supplied value can be wrong in a way the
    validator would have caught. Joining the skill to developer.md's *example*
    instead would compare two copies and stay green while both drifted off the
    schema.
    """
    mismatch = _payload_join_mismatch(_schema_payload_required(), _payload_consumer_section())
    assert not mismatch, (
        "the schema requires these payload fields and skills/manager/SKILL.md never "
        "names them, so nothing tells the maintainer they arrive filled in: "
        "{!r}".format(mismatch)
    )


def test_the_payload_join_fires_when_the_two_documents_disagree():
    """Positive control. A containment assertion over text parsed from two files
    passes just as readily when one side is empty, so the comparison is run against
    pairs that are wrong on purpose and must be reported.
    """
    four = ["base", "body", "head", "title"]
    assert _payload_join_mismatch(four, "the payload carries `title` and `body`.") == (
        "base",
        "head",
    )
    assert _payload_join_mismatch(four, "carries `base` `body` `head` `title`") == ()
    assert _payload_join_mismatch(None, "anything") == (
        "no required field list in the schema",
    )
    assert _payload_join_mismatch(four, None) == (
        "no consumer section in skills/manager/SKILL.md",
    )
    # Two absences agreeing is not agreement.
    assert _payload_join_mismatch([], "") == ("no fields on either side",)


# Each anchor is a phrase the pre-change documents did not contain, and
# `test_the_payload_anchors_fire_on_the_documents_as_they_were` proves that against
# the wording they actually carried. An anchor satisfied by prose already on disk is
# a green tick over a sentence nobody wrote, which this suite has shipped before.
PR_PAYLOAD_ANCHORS = [
    # Not `re-derive`: the skill already says "re-derive rather than trust" twice
    # about config, so that word alone would pass forever.
    ("head-and-base-are-not-rewritten-by-hand", ("rewriting them by hand",)),
    # Two anchors, because "could not be read" on its own is close enough to this
    # repo's house vocabulary to be satisfied by accident. The second pins the
    # consequence, which is the half that matters.
    (
        "an-unreadable-payload-is-a-third-state",
        ("could not be read", "no pull request to open"),
    ),
    ("maintainer-verification-is-appended-not-merged", ("verified by the maintainer",)),
]

# Checked against the consumer section, not the whole file. A three-word substring
# anywhere in a 780-line document is the weakest assertion this block could make: the
# bullet could be moved anywhere, or deleted and the phrase reintroduced in an
# unrelated paragraph, and the check would keep passing. Scoping it to the section
# where the body is published is what makes it a claim about placement rather than
# about vocabulary.
PR_AUTOLINK_ANCHOR = "does not autolink"


def _payload_anchors_unmet(text):
    folded = _flatten(text)
    return {
        name
        for name, anchors in PR_PAYLOAD_ANCHORS
        if not all(anchor in folded for anchor in anchors)
    }


def test_the_consumer_section_states_what_must_not_be_re_derived():
    """`head` and `base` come out of the payload and the validator has already checked
    them. A maintainer rewriting them is doing redundant work at best, and at worst is
    hand-writing a value the validator would have refused.

    The third state is the same rule this repo is named for, one document over: a
    payload that could not be read is not a payload that was not written, and neither
    of them is "there is no pull request to open".
    """
    section = _payload_consumer_section()
    assert section is not None
    unmet = _payload_anchors_unmet(section)
    assert not unmet, "skills/manager/SKILL.md, {!r}: {}".format(
        PR_PAYLOAD_CONSUMER_HEADING, sorted(unmet)
    )


def test_the_skill_names_the_backtick_autolink_trap():
    """An issue number inside a code span creates no reference on the forge, so a body
    reading `Part of #137` in backticks links nothing while looking exactly like a body
    that does. It sits beside the `Closes #A B` trap, which is the same class: syntax
    that silently references less than it appears to.
    """
    section = _payload_consumer_section()
    assert section is not None
    assert PR_AUTOLINK_ANCHOR in _flatten(section), (
        "skills/manager/SKILL.md warns elsewhere that a closing reference can bind "
        "less than it looks like it binds, and the section where the body is actually "
        "published never says a backticked issue number references nothing at all"
    )


def test_the_payload_anchors_fire_on_the_documents_as_they_were():
    """Positive control, and the one that makes the four checks above worth their
    lines. This is the consumer section as #123 wrote it -- complete-reading,
    confident, and silent on all four points. Every anchor must be unmet against it,
    or the anchor was satisfied by wording the file already contained.
    """
    before = (
        "Pushing and opening is yours, and it is one read plus one call:\n"
        "1. Push the agent's branch.\n"
        "2. Read the body before you publish it. Not optional, and it is what makes "
        "this a saving rather than a trick: you stop writing a document you still have "
        "to read. A body published unread is your name on text you have not seen. If "
        "it is wrong, argue it in the pull request or send it back; do not quietly "
        "rewrite it, because the person who did the work writes the record.\n"
        "3. Hand the payload path to `gh-pr-create:@FILE`. Not `gh pr create`, and not "
        "a body of your own assembled from the report.\n"
        "If `pr_body` says `not-written`, it says why. Then the body is yours, and you "
        "are writing it from a report rather than from the work.\n"
    )
    assert _payload_anchors_unmet(before) == {name for name, _ in PR_PAYLOAD_ANCHORS}
    assert PR_AUTOLINK_ANCHOR not in _flatten(before)
    # And the join was unmet against it too: the section named none of the four,
    # `body` included -- it discussed "the body" in prose and never as the field.
    assert _payload_join_mismatch(
        ["base", "body", "head", "title"], before
    ) == ("base", "body", "head", "title")
    # Must-fire half, so a passing anchor set is reachable rather than merely absent.
    assert (
        _payload_anchors_unmet(
            "`head` and `base` arrive filled in and the validator has checked them, so "
            "rewriting them by hand is redundant work that can also be wrong. A payload "
            "that could not be read is its own state and is never no pull request to "
            "open. Append your own `## Verified by the maintainer` section."
        )
        == set()
    )
    assert PR_AUTOLINK_ANCHOR in _flatten("a backticked issue number does not autolink")


def test_the_doctor_convention_check_fires_on_the_documents_as_they_were():
    """Positive control. The docs requirement as both files stated it: complete about
    the repo's own documentation, silent about the diagnostic that describes it.
    """
    before = (
        "Docs are part of the change. The repo's docs_targets for anything "
        "user-facing, the changelog always. A change nobody can discover is not "
        "shipped. If the repo uses changelog fragments, add one; do not hand-edit the "
        "assembled file."
    )
    assert _doctor_convention_unmet(before) == {name for name, _ in DOCTOR_CONVENTION_ANCHORS}
    assert "name the derivation" not in _flatten(before)
    assert "held by another lane" not in _flatten(before)
    # Must-fire half.
    assert (
        _doctor_convention_unmet(
            "A convention change is finished when the diagnostic reports the new "
            "convention, whether by an edit or by a derivation it already consumes."
        )
        == set()
    )


# --- #195: the verification is written by the op that reads back what it wrote ---
#
# The section documented raw `gh pr edit --body-file` and stopped there. That call
# asks GraphQL for `projectCards`, which GitHub has sunset, so it exits non-zero
# and leaves the body unchanged -- and the error names a field the caller never
# asked for, so it reads as Projects noise rather than as an unwritten body. The
# supertool `gh-pr-edit` op exists for exactly this and does the half that matters:
# it re-parses the published body for the closing reference before it writes, and
# compares what came back against the bytes it sent afterwards, so a write that
# landed something else is never rendered as a success.
#
# The anchor is that the op is INVOKED IN A FENCE and that no raw route is fenced
# ahead of it. Three deliberate choices, each one a way an earlier draft of this
# check was shown to be satisfiable while the section still taught the bug:
#
#   * `gh-pr-edit:` carries the colon. The pre-#195 text contained the bare name --
#     inside a sentence asserting the op did not exist -- so an anchor on
#     "gh-pr-edit" alone would have been satisfied by the very wording it was
#     written to replace. That is the toothless prose test this file exists to
#     avoid, and it was one character away.
#   * Fences, not prose. A reviewer defeated the previous version by mentioning the
#     op in an aside and fencing raw `gh pr edit` as the thing to run. A call the
#     reader is handed is a fenced call; anything else is commentary. That evasion
#     is kept as test_naming_the_op_in_prose_does_not_satisfy_the_anchor rather than
#     as a comment, because a defeated check should fail if it is ever reinstated.
#   * Position, not mere presence. An earlier draft asked only that some read-back
#     token appear somewhere after the write; a section could satisfy that with an
#     unrelated later mention of `gh-pr:` and still teach the bug. Requiring the raw
#     routes to sit after the op means a raw call can only ever read as a fallback.
#
# And the helpers answer in three states rather than two: () clean, a tuple for the
# finding, None for a section that fences no call at all. That last is not the good
# case, and returning () for it is how this check would go quietly inert.

VERIFICATION_HEADING = "### Your verification is a different voice, so append it"

# The op that owns the write, named as a call rather than as a word.
VERIFIED_WRITE_CALL = "gh-pr-edit:"

# Routes that replace a body with nothing checking what landed. Both are
# whole-body writes; neither has a partial append, which is why an unread result
# is a lost record rather than a partial one.
RAW_BODY_WRITES = ("gh pr edit", "-X PATCH")


def _verification_section(text=None):
    """The section's text, or None if the heading moved.

    None and "" are different answers: a heading that moved is not a section with
    nothing in it, and the findability test below is what keeps the checks from
    passing over the first case.
    """
    text = MANAGER_SKILL.read_text(encoding="utf-8") if text is None else text
    at = text.find(VERIFICATION_HEADING)
    if at < 0:
        return None
    tail = text[at + len(VERIFICATION_HEADING):]
    stop = tail.find("\n## ")
    return tail if stop < 0 else tail[:stop]


def _fenced_write_routes(section):
    """Which fenced block of SECTION invokes which write route.

    Returns (op_at, raw_at) over fenced blocks only -- the index of the first
    fence invoking the verified op or None, and each raw route mapped to its
    first fence. Returns None when SECTION fences no write route at all.

    Three states, and the third is the point. A prose mention is not a call: a
    section can name the op in passing and still fence raw `gh pr edit` as the
    thing to run, which is the reported bug wearing the fix's clothes. And
    "nothing was fenced" is not "everything fenced is fine" -- collapsing those
    two is how the pre-#195 hole reopens the day the findability guard is edited.
    """
    fences = section.split("```")[1::2]
    op_at = None
    raw_at = {}
    for i, fence in enumerate(fences):
        if op_at is None and VERIFIED_WRITE_CALL in fence:
            op_at = i
        for call in RAW_BODY_WRITES:
            if call in fence and call not in raw_at:
                raw_at[call] = i
    if op_at is None and not raw_at:
        return None
    return op_at, raw_at


def _raw_writes_ahead_of_the_op(section):
    """Raw routes fenced before the op is, () if none, None if nothing is fenced.

    () is clean, a non-empty tuple is the finding, and None is "this section
    offers no runnable call at all" -- which is neither of the other two and must
    not render as the first.
    """
    found = _fenced_write_routes(section)
    if found is None:
        return None
    op_at, raw_at = found
    return tuple(
        call for call, at in sorted(raw_at.items()) if op_at is None or at < op_at
    )


def test_the_verification_section_is_findable_and_fences_a_write():
    """Vacuity guard for the two checks below, in both directions: the heading has
    to be there, and the section has to fence some write route at all. Without the
    second half, deleting every call would read as compliance.
    """
    section = _verification_section()
    assert section is not None, (
        "no {!r} in skills/manager/SKILL.md -- both checks below would pass over "
        "nothing".format(VERIFICATION_HEADING)
    )
    assert _fenced_write_routes(section) is not None, (
        "the verification section fences no way to write a body at all, so it "
        "documents no way to record a verification"
    )


def test_the_verification_section_invokes_the_verified_write_op():
    """#195. The documented append did not land and nothing in the section would
    have noticed. The op is what makes the record real -- it refuses a dropped
    closing reference before the write and compares what came back against what it
    sent after it -- so the section has to hand a maintainer that call, in a fence,
    as the thing to run.
    """
    section = _verification_section()
    found = _fenced_write_routes(section)
    assert found is not None
    op_at, _ = found
    assert op_at is not None, (
        "no fenced block in the verification section invokes {!r} -- without it "
        "the append is confirmed by a command's exit, and a verification nobody "
        "read back is indistinguishable from one nobody "
        "performed".format(VERIFIED_WRITE_CALL)
    )


def test_no_raw_body_write_is_fenced_ahead_of_the_verified_op():
    """A raw route may appear as a fallback and be worth explaining -- #195's whole
    argument is about which mechanism the skill teaches. It may not be the one the
    reader is handed first.
    """
    section = _verification_section()
    ahead = _raw_writes_ahead_of_the_op(section)
    assert ahead is not None, "nothing fenced; the findability guard should have caught this"
    assert ahead == (), (
        "the verification section fences {!r} before {!r}, so the route with no "
        "read-back reads as the mechanism".format(ahead, VERIFIED_WRITE_CALL)
    )


PRE_195_SECTION = (
    VERIFICATION_HEADING + "\n\n"
    "If you verified something the agent could not, append a `## Verified by "
    "the maintainer` section to the body -- never edit the agent's text into "
    "agreement with you.\n\n"
    "This happens at review time, not at creation time, and there is no op "
    "for it: `gh-pr-create` consumes the payload once and there is no "
    "`gh-pr-edit`. Use raw `gh`:\n\n"
    "```bash\n"
    "gh pr edit <N> --body-file <a file holding the agent's body plus your "
    "appended section>\n"
    "```\n\n"
    "Read the agent's body back out first rather than reconstructing it -- "
    "`--body-file` replaces the whole body, so an append built from memory "
    "silently truncates the record you were protecting.\n"
)


def test_the_anchors_fire_on_the_section_as_it_was():
    """Positive control, and the reason the two checks above are worth their lines.
    This is the section as it stood before #195 -- one raw call, correct about
    voice, and explicitly asserting that no op existed. Both anchors must be unmet
    against it, or they were satisfied by wording the file already had.
    """
    section = _verification_section(PRE_195_SECTION)
    assert section is not None, "the control lost its own heading"
    # The bare name is present in the sentence denying the op exists, and must not
    # count. This is the character the anchor turns on.
    assert "gh-pr-edit" in section
    op_at, raw_at = _fenced_write_routes(section)
    assert op_at is None
    assert raw_at == {"gh pr edit": 0}
    assert _raw_writes_ahead_of_the_op(section) == ("gh pr edit",)
    # Must-fire half, so a passing state is reachable rather than merely absent.
    after = (
        VERIFICATION_HEADING + "\n\n"
        "```bash\n"
        "supertool 'gh-pr-edit:<N>:@<FILE>'\n"
        "```\n\n"
        "Use the op rather than raw `gh pr edit`, which asks GraphQL for a sunset "
        "field and leaves the body unchanged.\n"
    )
    assert _raw_writes_ahead_of_the_op(_verification_section(after)) == ()


def test_naming_the_op_in_prose_does_not_satisfy_the_anchor():
    """The evasion a reviewer built against the first version of this check, kept
    as a case rather than as a note. An anchor on the op's presence anywhere is
    satisfied by an aside, leaving the raw call as the only thing fenced -- which
    is the reported bug wearing the fix's clothes.
    """
    evasion = (
        VERIFICATION_HEADING + "\n\n"
        "There has been talk of a `gh-pr-edit:` op for this; until then, run:\n\n"
        "```bash\n"
        "gh pr edit <N> --body-file <FILE>\n"
        "```\n"
    )
    section = _verification_section(evasion)
    op_at, raw_at = _fenced_write_routes(section)
    assert op_at is None, "a prose mention was counted as an invocation"
    assert raw_at == {"gh pr edit": 0}
    assert _raw_writes_ahead_of_the_op(section) == ("gh pr edit",)


def test_a_section_that_fences_nothing_is_its_own_answer():
    """The third state. A section with no fenced call has not been checked and
    found clean -- there was nothing to check. It must not return () and read as
    the good case; the findability guard is what turns it into a failure.
    """
    silent = (
        VERIFICATION_HEADING + "\n\n"
        "Append a `## Verified by the maintainer` section. Say what you verified "
        "and how.\n"
    )
    section = _verification_section(silent)
    assert _fenced_write_routes(section) is None
    assert _raw_writes_ahead_of_the_op(section) is None


# ------------------------------------- the route to a file that does not exist yet (#250)
#
# Both documents that instruct an agent how to write a file named `edit` and nothing
# else. `edit` takes an `old`, a new file has none, and every pull request in this
# repository is required to add a changelog fragment -- which is always a new file. So
# the one mandatory write in every task had no documented op, and agents fell back to a
# raw heredoc: no post-write validator, no rollback, no receipt.
#
# The omission does not fail at the call the way a renamed op does. The heredoc runs.
# That is why this is a checked invariant rather than a thing anyone would notice: it
# reads as success. The jit rule that *does* name `paste` is `tool: Read|Edit|Write|Glob|
# Grep`, so a Bash heredoc never fires it -- the pointer route is unreachable for exactly
# this failure, which is the argument for naming the op in the brief instead.
#
# The paragraph is deliberately still in two places: agents/developer.md is the spawned
# agent's own brief, and the blockquote in skills/manager/SKILL.md is pasted verbatim
# into briefs for agents that never load developer.md. Neither can cite the other and
# still be self-contained. The cost of keeping two copies is paid here -- this check is
# the single copy of the *fact*, and it fails when either document loses it.

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_shipped_op_spellings import op_spellings  # noqa: E402

WRITE_ROUTE_DOCUMENTS = (
    REPO_ROOT / "agents" / "developer.md",
    REPO_ROOT / "skills" / "manager" / "SKILL.md",
)

#: Ops that can bring a file into existence. `paste` is the one supertool ships;
#: the tuple is the seam for a second, so a rename fails here rather than silently.
CREATING_OPS = ("paste",)


_BLOCKQUOTE_MARKER_RE = re.compile(r"(?m)^[ \t]*>[ \t]?")


def _collapse(text):
    """Blockquote markers dropped, then whitespace collapsed to single spaces.

    Case is left alone, unlike `_flatten`: op names are matched here, and folding
    case would let `PASTE` in a heading count as an invocation.

    The marker strip is not cosmetic. The paragraph in skills/manager/SKILL.md is a
    blockquote, so a wrap inside it inserts a `> ` and not just a newline -- with
    whitespace collapsed alone, a phrase split across that wrap comes back with a
    stray `>` wedged into the middle of it, and a document that says the right thing
    is reported as one that does not. That was observed while writing this check,
    against the wording this change lands, not reasoned about afterwards.
    """
    return " ".join(_BLOCKQUOTE_MARKER_RE.sub("", text).split())


def _write_route_unmet(text):
    """Findings about how a document tells an agent to write a file.

    Read off a whitespace-collapsed copy on purpose. These documents wrap at 100
    columns, and `supertool 'edit:@-'` already sits with the newline immediately
    before it in agents/developer.md; one more word on that line and the wrap falls
    between the command and its quoted argument, where a line-at-a-time reader sees
    no invocation at all and reports the document clean. That is the #229 trap --
    a checker whose finding is about its own reading -- and it is guarded below by a
    control rather than by this docstring.
    """
    collapsed = _collapse(text)
    ops = {op for op, _ in op_spellings(collapsed)}
    creating = ops.intersection(CREATING_OPS)
    unmet = set()
    if not creating:
        unmet.add("no-creating-op-is-named")
    if "edit" in ops and not creating:
        unmet.add("edit-is-named-with-no-way-to-create-a-file")
    if "`path` and `content`" not in collapsed:
        unmet.add("the-creating-op-s-payload-fields-are-not-named")
    return unmet


def test_both_write_route_documents_name_an_op_that_can_create_a_file():
    findings = {
        str(path.relative_to(REPO_ROOT)): sorted(
            _write_route_unmet(path.read_text(encoding="utf-8"))
        )
        for path in WRITE_ROUTE_DOCUMENTS
        if _write_route_unmet(path.read_text(encoding="utf-8"))
    }
    assert not findings, (
        "a document that instructs an agent to write files names no op that can "
        "create one, so the changelog fragment every pull request must add has no "
        "documented route and the agent falls back to a validator-free heredoc: "
        "{}".format(findings)
    )


def test_the_write_route_documents_exist():
    """A path that stopped resolving would make the check above vacuously green."""
    missing = [str(p) for p in WRITE_ROUTE_DOCUMENTS if not p.is_file()]
    assert not missing, missing


# The developer brief's paragraph as it stood before this change. Every anchor added
# above must fire on it, or the check passes on the wording it was written against.
PRIOR_WRITE_ROUTE = """
It is on PATH from any directory. Batch 6-7 ops per call -- `read`, `grep`, `glob`, `map`, `around`,
`between`, `tree` -- never one read per file. Pipe edits in as a TOML payload on stdin, with
`supertool 'edit:@-'` and a heredoc carrying `path`, `old` and `new` fields.
"""


def test_the_write_route_check_fires_on_the_pre_250_wording():
    assert _write_route_unmet(PRIOR_WRITE_ROUTE) == {
        "no-creating-op-is-named",
        "edit-is-named-with-no-way-to-create-a-file",
        "the-creating-op-s-payload-fields-are-not-named",
    }


# A document that says the right thing, wrapped so the newline falls between
# `supertool` and its quoted argument. Hand-wrapped prose does this; the reflow is
# not aware of the inline code span.
WRAPPED_CREATING_OP = (
    "To create a file, pipe a TOML payload into `supertool\n"
    "'paste:@-'` carrying `path` and `content`. To change an existing one, use\n"
    "`supertool 'edit:@-'` with `path`, `old` and `new`.\n"
)


def test_a_line_wrapped_invocation_is_not_read_as_an_omission():
    """Must-not-fire, with the two controls that stop it being a free pass.

    The middle assertion is the load-bearing one: read a line at a time, this text
    names no creating op at all. If the collapse were dropped, the check above would
    start reporting a correct document as broken -- and, worse, the wording that
    replaces it would be tuned until the line-based reader was happy.
    """
    assert _write_route_unmet(WRAPPED_CREATING_OP) == set()

    line_at_a_time = {op for op, _ in op_spellings(WRAPPED_CREATING_OP)}
    assert "paste" not in line_at_a_time, (
        "the wrap control no longer wraps across the invocation, so it proves "
        "nothing about the collapse: {}".format(sorted(line_at_a_time))
    )

    # Must-fire, in the same fixture: same wrapping, creating op taken back out.
    without_paste = WRAPPED_CREATING_OP.replace("`supertool\n'paste:@-'`", "a heredoc")
    assert _write_route_unmet(without_paste) == {
        "no-creating-op-is-named",
        "edit-is-named-with-no-way-to-create-a-file",
    }


# The same instruction inside a blockquote, wrapped mid-phrase -- the shape the
# manager skill's brief template actually has. The wrap inserts a `> ` here, not
# just a newline.
WRAPPED_INSIDE_A_BLOCKQUOTE = (
    "   > To create a file, `supertool 'paste:@-'` carrying `path` and\n"
    "   > `content`; to change one, `supertool 'edit:@-'` with `path`, `old` and\n"
    "   > `new`.\n"
)


def test_a_blockquote_wrap_does_not_read_as_a_missing_payload_field():
    """Must-not-fire. Found by running the check against the wording this change
    lands: collapsing whitespace alone left "`path` and > `content`", so the
    document was reported for omitting the very fields it names.
    """
    assert _write_route_unmet(WRAPPED_INSIDE_A_BLOCKQUOTE) == set()

    without_the_strip = " ".join(WRAPPED_INSIDE_A_BLOCKQUOTE.split())
    assert "`path` and `content`" not in without_the_strip, (
        "the blockquote control no longer wraps mid-phrase, so it proves nothing "
        "about the marker strip: {!r}".format(without_the_strip)
    )

    # Must-fire, same fixture: the payload fields taken back out.
    vague = WRAPPED_INSIDE_A_BLOCKQUOTE.replace("`path` and\n   > `content`", "a payload")
    assert _write_route_unmet(vague) == {"the-creating-op-s-payload-fields-are-not-named"}


def test_a_document_naming_neither_op_is_still_reported():
    """The third state. Prose that instructs no write at all must not come back
    clean just because it never mentioned `edit` -- the conditional anchor is
    satisfied by silence, and the unconditional one is what catches it.
    """
    silent = "Read the file, decide what it should say, and make it say that."
    assert _write_route_unmet(silent) == {
        "no-creating-op-is-named",
        "the-creating-op-s-payload-fields-are-not-named",
    }


# ---------------------------------------------------------------------------
# #247: the op table's heading hands a whole class of operations to one route,
# and rows of the table directly under it route that class the other way.
#
# Read a line at a time, which is the opposite of the collapse the #250 checks
# above need, and for a reason about the format rather than convenience: an ATX
# heading and a GFM table row are each terminated by a newline, so collapsing
# whitespace would fuse every row into one and destroy the structure being read.
# The wrap trap does not reach here -- there is no legal wrap inside a row to
# miss -- and `test_the_op_table_rows_are_found_at_all` fails if the row parser
# stops seeing the table, which is the way this check could go quiet.

MANAGER_SKILL = REPO_ROOT / "skills" / "manager" / "SKILL.md"

# `\r` is in both trailing classes, and it is not decoration. These are the
# suite's only `$`-anchored multiline patterns, and there is no `.gitattributes`
# here, so a Windows checkout is free to arrive as CRLF. Measured rather than
# argued: fed text that still carries a CR, `_routes_in_rows` returns `{}` and
# `_op_table_heading_unmet` returns `set()` -- a silent clean, this repository's
# own defect class. `Path.read_text` translates the newlines before either
# pattern sees them, so that path is unreachable through the callers above; the
# class is closed here anyway because one character is cheaper than a guard, and
# `test_a_crlf_document_is_read_the_same_as_an_lf_one` measures it.
_HEADING_RE = re.compile(r"(?m)^(#{1,6})[ \t]+(.*?)[ \t\r]*$")

# A heading sentence that hands a class of operations to a named route. The
# class span stops at `.`, `;` and `|` so two sentences in one heading are two
# claims, and a table row can never be read as the tail of a heading claim.
_ROUTE_CLAIM_RE = re.compile(
    r"\b(read|reads|reading|write|writes|writing)\b[^.;|]*?"
    r"\bgo(?:es)?\s+through\s+`?([A-Za-z][\w-]*)`?",
    re.IGNORECASE,
)

_CLASS_WORDS = {
    "read": "reads",
    "reads": "reads",
    "reading": "reads",
    "write": "writes",
    "writes": "writes",
    "writing": "writes",
}

_TABLE_ROW_RE = re.compile(r"(?m)^\|(?P<need>[^|\n]*)\|(?P<op>.*?)\|[ \t\r]*$")
_BACKTICK_RE = re.compile(r"`([^`]*)`")
_SUPERTOOL_OP_RE = re.compile(r"\A((?:gh|git)-[a-z0-9-]+)")

#: The trailing segment of an op name that makes the op a write. Named rather
#: than read off the row's `need` cell: that cell is English and drifts, while
#: an op name is a spelling the dependency owns. The control below asserts this
#: set still classifies the writes the table carries, so an op renamed out of
#: the set fails there rather than quietly reclassifying itself as a read.
WRITE_VERB_SUFFIXES = ("create", "edit", "merge", "close", "delete", "comment", "update")


def _sections(text):
    """[(heading text, body)] for every ATX heading in `text`."""
    headings = list(_HEADING_RE.finditer(text))
    sections = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        sections.append((heading.group(2), text[heading.end():end]))
    return sections


def _routes_in_rows(body):
    """{"reads"|"writes": {route, ...}} observed in `body`'s table rows.

    Only supertool op spellings are classified. A raw `gh ...` in a cell is left
    unclassified on purpose: guessing its class would let this check invent the
    contradiction it is looking for.
    """
    observed = {}
    for row in _TABLE_ROW_RE.finditer(body):
        for span in _BACKTICK_RE.findall(row.group("op")):
            op = _SUPERTOOL_OP_RE.match(span)
            if not op:
                continue
            name = op.group(1)
            klass = "writes" if name.rsplit("-", 1)[-1] in WRITE_VERB_SUFFIXES else "reads"
            observed.setdefault(klass, set()).add("supertool")
    return observed


def _op_table_heading_unmet(text):
    """Findings about a heading that routes a class the rows beneath it contradict.

    Two keys, and they are two different claims. The contradiction key is #247
    as filed: the heading and the rows disagree today. The taxonomy key is the
    rule the instance argues for -- a heading naming a route for a whole class
    is a second, coarser copy of what the table already answers per row, and the
    copy that drifts is the one that gets quoted. A correct taxonomy still fires
    it, deliberately: the per-row answer cannot drift from itself, so the heading
    should defer to the rows rather than restate them.
    """
    unmet = set()
    for heading, body in _sections(text):
        claims = list(_ROUTE_CLAIM_RE.finditer(heading))
        if not claims:
            continue
        rows = _routes_in_rows(body)
        for claim in claims:
            klass = _CLASS_WORDS[claim.group(1).lower()]
            claimed = claim.group(2).lower().strip("`")
            unmet.add("heading-routes-a-class-instead-of-deferring-to-the-rows")
            observed = rows.get(klass, set())
            if not observed:
                # The third state, and it is the one this check would otherwise
                # have produced itself. The claim loop used to sit behind an
                # `if not rows: continue`, so a heading routing a class over a
                # table that would not parse -- a malformed row, a fence, a
                # table that moved -- came back byte-identical to a heading with
                # nothing to answer for. `test_the_op_table_rows_are_found_at_all`
                # does not cover it: that guard is document-wide, so a second
                # table elsewhere in the file keeps it green while this section
                # goes unread.
                unmet.add(
                    "heading-routes-{}-but-no-row-under-it-could-be-read".format(klass)
                )
            elif claimed not in observed:
                unmet.add(
                    "heading-says-{}-go-through-{}-but-a-row-uses-{}".format(
                        klass, claimed, "-".join(sorted(observed))
                    )
                )
    return unmet


def test_the_op_table_heading_does_not_route_a_class_the_rows_contradict():
    findings = sorted(_op_table_heading_unmet(MANAGER_SKILL.read_text(encoding="utf-8")))
    assert not findings, (
        "the manager skill's op table is introduced by a heading that hands a whole "
        "class of operations to one route, while the rows under it answer per row -- "
        "the heading is the part that is skimmed and quoted, and it is the copy that "
        "drifts (#247): {}".format(findings)
    )


def test_the_op_table_rows_are_found_at_all():
    """Without this, the check above passes on a table the parser stopped seeing."""
    text = MANAGER_SKILL.read_text(encoding="utf-8")
    routes = {}
    for _, body in _sections(text):
        for klass, seen in _routes_in_rows(body).items():
            routes.setdefault(klass, set()).update(seen)
    assert routes.get("writes") == {"supertool"}, routes
    assert routes.get("reads") == {"supertool"}, routes


# The heading and the write rows exactly as this document carried them before
# #247, kept as a literal because CI checks out at depth 1.
PRE_247_OP_TABLE = r"""## Reads go through supertool. Writes go through `gh`.

| Need | Op |
| --- | --- |
| The board | `gh-issues`, `gh-labels` |
| Filing | `gh-issue-create:@FILE` |
| Opening a pull request | `gh-pr-create:@FILE` |
| Correcting a published body | `gh-pr-edit:N:@FILE` |
| Merging | `gh-pr-merge:N:squash\|force` |
"""


def test_the_route_claim_check_fires_on_the_pre_247_heading():
    """Positive control. Both keys, and the contradiction names both routes."""
    assert _op_table_heading_unmet(PRE_247_OP_TABLE) == {
        "heading-routes-a-class-instead-of-deferring-to-the-rows",
        "heading-says-writes-go-through-gh-but-a-row-uses-supertool",
    }


def test_a_heading_that_defers_to_the_rows_is_clean_and_the_rows_were_still_read():
    """Must-not-fire, with the control that stops it being a free pass.

    The second assertion is load-bearing: a heading naming no route is clean
    here whether the rows were parsed or not, so the same fixture has to show
    the row parser still classifying the writes it contains.
    """
    deferring = PRE_247_OP_TABLE.replace(
        "## Reads go through supertool. Writes go through `gh`.",
        "## Which call to make: the op table answers it, row by row",
    )
    assert _op_table_heading_unmet(deferring) == set()

    body = _sections(deferring)[0][1]
    assert _routes_in_rows(body) == {"reads": {"supertool"}, "writes": {"supertool"}}


def test_a_correct_taxonomy_in_the_heading_is_still_reported():
    """The third shape, and the decision #247 asked for, written down as a test.

    A heading that routes the class *correctly* is not a contradiction -- and it
    is still refused, because it is a second copy of an answer the rows already
    give. Only the taxonomy key fires, so the two findings stay distinguishable.
    """
    accurate = PRE_247_OP_TABLE.replace(
        "Writes go through `gh`.", "Writes go through supertool."
    )
    assert _op_table_heading_unmet(accurate) == {
        "heading-routes-a-class-instead-of-deferring-to-the-rows"
    }


def test_a_claim_over_an_unreadable_table_is_reported_not_skipped():
    """The third state, and it is the auditor's fixture rather than an invented one.

    A heading routes a class; the row that would answer it is malformed and does
    not parse; a second, unrelated table elsewhere in the document parses fine.
    Before this, the claim loop sat behind `if not rows: continue`, so this came
    back `set()` -- clean -- while `test_the_op_table_rows_are_found_at_all` also
    stayed green off the *other* table, because that guard is document-wide. Two
    checks, neither able to see the section that went unread.
    """
    unreadable = (
        "## Writes go through `gh`.\n"
        "\n"
        "| Need | Op |\n"
        "| --- | --- |\n"
        "  Merging | `gh-pr-merge:N` |\n"  # no leading pipe: not a row
        "\n"
        "## Something else entirely\n"
        "\n"
        "| Need | Op |\n"
        "| --- | --- |\n"
        "| Opening a pull request | `gh-pr-create:@FILE` |\n"
    )
    # Must-fire: the section whose table did not parse is named, not skipped.
    assert _op_table_heading_unmet(unreadable) == {
        "heading-routes-a-class-instead-of-deferring-to-the-rows",
        "heading-routes-writes-but-no-row-under-it-could-be-read",
    }

    # The two controls that make the above a finding rather than a coincidence.
    claiming, second = _sections(unreadable)[0], _sections(unreadable)[1]
    assert _routes_in_rows(claiming[1]) == {}, _routes_in_rows(claiming[1])
    assert _routes_in_rows(second[1]) == {"writes": {"supertool"}}

    # Same fixture, the row given its leading pipe back: the contradiction the
    # unreadable table was hiding is what the check reports instead.
    readable = unreadable.replace("  Merging |", "| Merging |")
    assert _op_table_heading_unmet(readable) == {
        "heading-routes-a-class-instead-of-deferring-to-the-rows",
        "heading-says-writes-go-through-gh-but-a-row-uses-supertool",
    }


def test_a_crlf_document_is_read_the_same_as_an_lf_one():
    """The platform control, and it is a measurement rather than a table.

    CI runs three operating systems and this repository ships no
    `.gitattributes`, so a Windows checkout may arrive CRLF. Rather than assert
    an outcome for a platform this never ran on, the same document is fed in
    both line endings and the two answers are compared -- which is a claim about
    the patterns, not about the runner. The must-fire half is the comparison
    itself: an LF answer of `set()` would make the equality meaningless, so the
    fixture is the pre-#247 table, whose LF answer is two findings.
    """
    lf = PRE_247_OP_TABLE
    crlf = lf.replace("\n", "\r\n")
    assert "\r" in crlf and crlf != lf

    assert _op_table_heading_unmet(lf) == _op_table_heading_unmet(crlf)
    assert len(_op_table_heading_unmet(crlf)) == 2, sorted(_op_table_heading_unmet(crlf))
    assert _routes_in_rows(_sections(crlf)[0][1]) == {
        "reads": {"supertool"},
        "writes": {"supertool"},
    }


def test_a_table_under_a_heading_that_claims_nothing_is_clean():
    """A document that says nothing about routing has nothing to contradict."""
    quiet = PRE_247_OP_TABLE.replace(
        "## Reads go through supertool. Writes go through `gh`.", "## The ops"
    )
    assert _op_table_heading_unmet(quiet) == set()


# ---------------------------------------------------------------------------
# #244: a tick that stops because the board is momentarily quiet reports the
# same closing line as a tick that stopped because there was nothing to do --
# and a tick that never read the board reports it too. Three endings, and the
# two that are not endings have to be unable to render as the one that is.
#
# Read off a whitespace-collapsed, blockquote-stripped copy, unlike the #247
# checks above: this is running prose in two documents that wrap at 100
# columns, so an anchor phrase straddles a line break as a matter of course.

#: (path, heading pattern). Two documents on purpose, and they are two
#: different things: the skill is the loop's own rules and the command is what
#: a maintainer invokes. #244 was observed against the skill; the command
#: carried the same sentence, so fixing one would have reached half the callers.
TICK_ENDING_DOCUMENTS = (
    (REPO_ROOT / "skills" / "manager" / "SKILL.md", r"loop mechanics"),
    (REPO_ROOT / "commands" / "tick.md", r"what ends a tick"),
)

#: Each key is a way the ending can render as an absence. The naming and
#: sourcing anchors are the load-bearing pair: without them "blocked" with no
#: item named and "nothing left" off a board nobody read are the same bytes as
#: a finished loop, which is this repository's own defect class pointed at its
#: own loop.
TICK_ENDING_ANCHORS = (
    ("the-work-started-ending-is-not-named", r"work started"),
    ("the-blocked-ending-is-not-named", r"\bblocked\b"),
    ("the-nothing-left-ending-is-not-named", r"nothing left"),
    (
        "blocked-does-not-require-every-remaining-item-named",
        r"named individually|names? (?:each|every) (?:remaining )?item|"
        r"a count is not a naming",
    ),
    (
        "nothing-left-is-not-sourced-from-a-read-that-answered",
        r"unread board|board (?:that|which) did not answer|did not answer",
    ),
    ("the-read-that-sources-nothing-left-is-not-named", r"`gh-issues`"),
    (
        "the-two-non-terminal-states-are-not-excluded-as-endings",
        r"not an end(?:ing)?\b|only the (?:last|third)",
    ),
)


def _tick_ending_unmet(text, heading_pattern):
    """Findings about how a document says a tick ends.

    Returns the section-absent key rather than an empty set when the heading
    cannot be found: a section that moved and a section that says the right
    thing must not render alike, which is the same rule this check exists to
    put into the prose.
    """
    body = None
    for heading, section in _sections(text):
        if re.search(heading_pattern, heading, re.IGNORECASE):
            body = section
            break
    if body is None:
        return {"the-tick-ending-section-is-absent"}
    collapsed = _collapse(body).lower()
    return {
        key for key, pattern in TICK_ENDING_ANCHORS
        if not re.search(pattern, collapsed)
    }


def test_both_documents_state_a_tick_ending_that_cannot_be_faked():
    findings = {}
    for path, heading in TICK_ENDING_DOCUMENTS:
        unmet = sorted(_tick_ending_unmet(path.read_text(encoding="utf-8"), heading))
        if unmet:
            findings[str(path.relative_to(REPO_ROOT))] = unmet
    assert not findings, (
        "a tick that idled, a tick that is blocked on named work, and a tick with "
        "nothing left all close on the same line, so the loop hands back to the "
        "maintainer and calls it done (#244): {}".format(findings)
    )


def test_the_tick_ending_documents_exist():
    """A path that stopped resolving would make the check above vacuously green."""
    missing = [str(p) for p, _ in TICK_ENDING_DOCUMENTS if not p.is_file()]
    assert not missing, missing


# The skill's *Loop mechanics* section as it stood before #244. Every anchor
# above must fire on it, or the check passes on the wording it replaced.
PRE_244_LOOP_MECHANICS = """## Loop mechanics

Arm the loop at the end of the first tick, every time, including when this skill was invoked
directly. A skill invocation does not create a loop.

Agent completions notify for free -- never poll for them. **CI is the only thing that needs a timer**,
sized to the observed matrix. Nothing outstanding but somebody else's work -> stop the loop
(`stop: true`) and say so out loud, because a loop that stops silently is indistinguishable from one
that was never armed.
"""


def test_the_tick_ending_check_fires_on_the_pre_244_wording():
    """Positive control: the sentence #244 was filed against fails every anchor."""
    assert _tick_ending_unmet(PRE_244_LOOP_MECHANICS, r"loop mechanics") == {
        key for key, _ in TICK_ENDING_ANCHORS
    }


def test_a_moved_heading_is_reported_rather_than_passing():
    """The third state. A section that is not there has not been checked."""
    assert _tick_ending_unmet(PRE_244_LOOP_MECHANICS, r"what ends a tick") == {
        "the-tick-ending-section-is-absent"
    }


# The anchors satisfied, wrapped so two of them straddle a line break inside a
# blockquote -- the shape a hand-wrapped bulleted list in these documents has.
WRAPPED_TICK_ENDING = (
    "## Loop mechanics\n"
    "\n"
    "> A tick ends in one of three states, and only the last is an end:\n"
    "> work started; blocked, with every remaining item named\n"
    "> individually and what it waits on; or nothing left, which `gh-issues`\n"
    "> and `gh-prs` both answered and both answered empty. An unread\n"
    "> board is not an empty one, a call that did not answer is unknown,\n"
    "> and unknown is not an ending.\n"
)


def test_a_wrapped_blockquoted_ending_is_not_read_as_an_omission():
    """Must-not-fire, with the two controls that stop it being a free pass."""
    assert _tick_ending_unmet(WRAPPED_TICK_ENDING, r"loop mechanics") == set()

    line_at_a_time = WRAPPED_TICK_ENDING.lower()
    assert "named individually" not in line_at_a_time, (
        "the wrap control no longer wraps across an anchor phrase, so it proves "
        "nothing about the collapse"
    )
    without_the_strip = " ".join(WRAPPED_TICK_ENDING.split()).lower()
    assert "named individually" not in without_the_strip, (
        "the blockquote control no longer wraps mid-phrase, so it proves nothing "
        "about the marker strip: {!r}".format(without_the_strip)
    )

    # Must-fire, same fixture: the naming requirement and the source taken out.
    vague = WRAPPED_TICK_ENDING.replace(
        "blocked, with every remaining item named\n> individually and what it waits on",
        "blocked",
    ).replace(
        "An unread\n> board is not an empty one, a call that did not answer is unknown,\n"
        "> and unknown is not an ending.",
        "Nothing else matters.",
    )
    assert _tick_ending_unmet(vague, r"loop mechanics") == {
        "blocked-does-not-require-every-remaining-item-named",
        "nothing-left-is-not-sourced-from-a-read-that-answered",
    }


# --------------------------- the one write the brief guarantees, and refuses (#266)
#
# Both documents require the report and the note to be written OUTSIDE every
# worktree -- a sibling of the numbered worktree directories -- so the evidence
# survives the tree being reaped. Both documents also require every file
# operation to go through supertool. Supertool refuses a path outside the
# current working directory:
#
#     ERROR: path escapes cwd: '<...>/reports/x.json' (resolved to '<...>')
#
# So an agent standing in its branch directory, doing exactly what both halves
# say, is refused on the one write the brief guarantees it will make. The
# refusal is correct and is not the defect. The defect is that nothing named the
# remedy, so each agent rediscovers it -- and the cost is a re-send of a large
# heredoc rather than a retry of a short command.
#
# The remedy is to move the cwd, not the guard: run the write from the worktree
# root. The refusal message itself offers two other routes -- an env var and an
# `allow_outside_cwd` key in `.supertool.json` -- and both widen every op for
# the rest of the session in somebody else's repository, which is why the
# documents name the cwd move and the check anchors on it.
#
# The anchor pair is deliberate. The refusal string alone would be satisfied by
# a document that describes the problem and not the fix; the remedy alone would
# be satisfied by a document whose instruction an agent has no reason to connect
# to the error it is staring at.
#
# Two copies again, for the same reason as #250 above: agents/developer.md is
# the spawned agent's own brief, and skills/manager/SKILL.md's material is
# pasted into briefs for agents that never load developer.md. Neither can cite
# the other and stay self-contained, so the fact lives once -- here.

OUT_OF_TREE_WRITE_DOCUMENTS = WRITE_ROUTE_DOCUMENTS

#: The sentence that puts a document under this obligation.
OUT_OF_TREE_TRIGGER = "outside every worktree"

#: What supertool actually prints, quoted so an agent recognises the refusal it
#: is looking at rather than reading it as a bug in its own path.
ESCAPES_CWD_REFUSAL = "path escapes cwd"

#: The remedy, backticked. The bare `cd <worktree_root>` is a substring of the
#: `cd <worktree_root>/NNN` already in developer.md's worktree fence, so an
#: unbackticked anchor would have been satisfied before a word was written --
#: a toothless anchor of exactly the kind the control below exists to catch.
CWD_REMEDY = "`cd <worktree_root>`"


def _requires_an_out_of_tree_write(text):
    return OUT_OF_TREE_TRIGGER in _collapse(text).lower()


def _out_of_tree_write_unmet(text):
    """Findings about a document that requires a write supertool will refuse.

    Conditional on purpose: a document that never asks for an out-of-tree write
    is under no obligation to explain one, and reporting it would be noise. The
    cost of a conditional predicate is that it goes quiet when the trigger
    wording moves, which is what
    `test_both_documents_still_require_an_out_of_tree_write` is for.
    """
    collapsed = _collapse(text).lower()
    if OUT_OF_TREE_TRIGGER not in collapsed:
        return set()
    unmet = set()
    if ESCAPES_CWD_REFUSAL not in collapsed:
        unmet.add("the-refusal-is-not-quoted")
    if CWD_REMEDY.lower() not in collapsed:
        unmet.add("the-cwd-remedy-is-not-named")
    return unmet


def test_both_documents_naming_an_out_of_tree_write_name_how_to_make_it():
    findings = {
        str(path.relative_to(REPO_ROOT)): sorted(
            _out_of_tree_write_unmet(path.read_text(encoding="utf-8"))
        )
        for path in OUT_OF_TREE_WRITE_DOCUMENTS
        if _out_of_tree_write_unmet(path.read_text(encoding="utf-8"))
    }
    assert not findings, (
        "a document requires a write outside every worktree and requires every "
        "write to go through supertool, without naming the refusal that "
        "combination produces or the cwd that avoids it: {}".format(findings)
    )


def test_both_documents_still_require_an_out_of_tree_write():
    """The must-fire half of the pair, and the way this check goes quiet.

    `_out_of_tree_write_unmet` returns an empty set for a document that never
    asks for the write. If the trigger wording is reworded away in either
    document, the check above starts reporting both documents clean while
    neither says anything -- an absence produced by the checker, read as an
    absence in the world.
    """
    silent = [
        str(path.relative_to(REPO_ROOT))
        for path in OUT_OF_TREE_WRITE_DOCUMENTS
        if not _requires_an_out_of_tree_write(path.read_text(encoding="utf-8"))
    ]
    assert not silent, (
        "no longer names the obligation the check above is conditional on, so "
        "that check is now vacuous for it: {}".format(silent)
    )


# The developer brief's report-path instruction as it stood before this change.
# Both anchors must fire on it, or they were satisfied by the wording they were
# written against.
PRIOR_OUT_OF_TREE_WRITE = """
1. Write it beside your note, at `<worktree_root>/reports/<branch>-<UTC timestamp>.json`.
   Derive `worktree_root` the same way you derived it to cut the worktree; never write a path you
   were not given. Outside every worktree, for the same reason the note is. **Flatten the branch
   name first** -- most `branch_pattern`s contain a slash, and a filename built from one silently
   becomes a directory, so `fix/12` names the file `fix-12-...`. That applies to the note beside it.
"""


def test_the_out_of_tree_check_fires_on_the_pre_266_wording():
    assert _out_of_tree_write_unmet(PRIOR_OUT_OF_TREE_WRITE) == {
        "the-refusal-is-not-quoted",
        "the-cwd-remedy-is-not-named",
    }


def test_the_pre_266_wording_would_have_been_read_as_triggering():
    """Control on the control. If the fixture above did not trigger the
    predicate, its two findings would be evidence about the trigger and not
    about the anchors.
    """
    assert _requires_an_out_of_tree_write(PRIOR_OUT_OF_TREE_WRITE)


def test_a_document_that_asks_for_no_out_of_tree_write_is_not_reported():
    """The third state, with its must-fire in the same fixture.

    Prose that never asks for the write is not clean and not broken -- it is
    simply not under the obligation. What must not happen is that this and a
    document under the obligation come back the same way, so the second half
    adds the trigger sentence back and asserts both findings appear.
    """
    unrelated = "Write the fragment, run the suite, and commit."
    assert _out_of_tree_write_unmet(unrelated) == set()

    triggered = unrelated + " The report goes outside every worktree."
    assert _out_of_tree_write_unmet(triggered) == {
        "the-refusal-is-not-quoted",
        "the-cwd-remedy-is-not-named",
    }


# The remedy said correctly, inside a blockquote, wrapped so both anchors
# straddle a line break -- the shape the manager skill's pasted material has.
WRAPPED_OUT_OF_TREE_REMEDY = (
    "   > The report lives outside every worktree, so run the write from the\n"
    "   > worktree root: `cd\n"
    "   > <worktree_root>` first, because supertool refuses a path outside the\n"
    "   > cwd with `ERROR: path escapes\n"
    "   > cwd`.\n"
)


def test_a_wrapped_blockquoted_remedy_is_not_read_as_an_omission():
    """Must-not-fire, with the controls that stop it being a free pass.

    Both anchors are split by the wrap here: `cd <worktree_root>` by a
    blockquote marker, `path escapes cwd` by a plain newline. A reader that
    dropped either half of `_collapse` would report a correct document as
    broken, and the wording would then be tuned until the broken reader was
    happy.
    """
    assert _out_of_tree_write_unmet(WRAPPED_OUT_OF_TREE_REMEDY) == set()

    line_at_a_time = WRAPPED_OUT_OF_TREE_REMEDY.lower()
    assert ESCAPES_CWD_REFUSAL not in line_at_a_time, (
        "the wrap control no longer wraps across the refusal string, so it "
        "proves nothing about the collapse"
    )
    without_the_strip = " ".join(WRAPPED_OUT_OF_TREE_REMEDY.split()).lower()
    assert CWD_REMEDY.lower() not in without_the_strip, (
        "the blockquote control no longer wraps across the remedy, so it "
        "proves nothing about the marker strip: {!r}".format(without_the_strip)
    )

    # Must-fire, same fixture: the remedy taken back out, trigger left in.
    vague = "   > The report lives outside every worktree. Write it there.\n"
    assert _out_of_tree_write_unmet(vague) == {
        "the-refusal-is-not-quoted",
        "the-cwd-remedy-is-not-named",
    }
