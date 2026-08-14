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
# The five recurring cross-platform shapes are already written down twice --
# agents/developer.md and skills/manager/SKILL.md. A third copy is not coverage; it is
# the drift defect this tracker was opened to file. The auditor references them, so
# these anchors must be absent from it and present in their source.

PORTABILITY_SHAPES = (
    "drive letter",
    "POSIX literal",
    "spawn error",
    "narrow `except`",
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
    five shapes makes a third copy, and the copy that drifts is never the one
    anybody rereads.
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
    assert RELEASE_AUDITOR_SUBAGENT in skill, (
        "skills/manager/SKILL.md states the audit gate without naming what "
        "performs it"
    )
    assert "first release" in skill, (
        "skills/manager/SKILL.md must say what the gate does for a repo with no "
        "previous tag -- otherwise an empty delta reads as an audit that found "
        "nothing"
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
