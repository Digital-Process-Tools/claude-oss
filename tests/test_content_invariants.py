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
    for agent in ("triager.md", "developer.md"):
        leaked = _granted_tools(agent) & {"Read", "Grep", "Glob"}
        assert not leaked, (
            "{} grants {} -- reads go through supertool via Bash, so these must not be "
            "in the tool list".format(agent, sorted(leaked))
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
