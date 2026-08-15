"""Guards on the skill and agent prose.

The whole reason this plugin exists is that the maintainer loop was three diverged
copies, each carrying its own repo's facts. A hardcoded repo name here recreates
that: it would arrive in a brief with the same authority as something re-derived,
and be wrong for every repo but one.

These are content tests. They fail loudly when the regex matches nothing it was
meant to anchor on, because a pattern that matched nothing has checked nothing.
"""

import re
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

RANKING_HEADER = "| Class | Blocks a release? |"
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
        if len(cells) != 2:
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

AGENT_DISPATCH_RE = re.compile(r'subagent_type:\s*"oss:([a-z0-9-]+)"')

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
    """name -> the documents that spawn it. Scanned, never listed."""
    found = {}
    for path, text in documents:
        for name in AGENT_DISPATCH_RE.findall(text):
            found.setdefault(name, set()).add(str(path))
    return found


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

RELOAD_ANCHORS = [
    ("names-the-reload-command", "/reload-plugins"),
    ("says-the-agents-are-what-goes-missing", "agent"),
]


def _reload_unmet(text):
    folded = _flatten(text)
    return {name for name, anchor in RELOAD_ANCHORS if anchor not in folded}


def test_the_readme_install_step_names_the_reload():
    readme = REPO_ROOT / "README.md"
    assert readme.is_file(), "README.md is gone -- this check would vacuously pass"
    unmet = _reload_unmet(readme.read_text(encoding="utf-8"))
    assert not unmet, "README.md's install step does not carry the reload: " + repr(sorted(unmet))


def test_the_reload_check_fires_on_the_install_step_as_it_was_stated_before():
    """Positive control, and it is the actual prior text: correct as far as it went,
    and silent on the command that fixes the failure it was describing.
    """
    before = (
        "**Restart Claude Code afterwards.** Plugin registrations are read once at "
        "session start.\n"
    )
    assert _reload_unmet(before) == {name for name, _ in RELOAD_ANCHORS}
    # Must-fire half: prose carrying both anchors comes back clean, so the assertion
    # above is about the text rather than about a matcher that matches nothing.
    assert _reload_unmet("Run /reload-plugins or the agents will not register.") == set()
