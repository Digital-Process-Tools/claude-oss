"""An agent definition must not imply an effect boundary its tool grant does not hold.

`agents/auditor.md` summarises itself as *annotates, never blocks*. That is true of its
**output** -- no finding of its stops a merge -- and it was read as a statement about its
**effects**. During #242's self-review an audit spawn ran an acting supertool op against
the live watch channel of the session that dispatched it, while that session was depending
on that fleet to report CI (#251). Nothing in the frontmatter, the harness or the prose
distinguished a read from a write, because `Bash` is total and every write in this system
goes through `Bash`.

`agents/triager.md` had already worked this out for one route -- "Nothing but this
paragraph stops you, so this paragraph is the boundary -- not the frontmatter" -- and the
audit definitions carried no equivalent at all.

So this module guards the honest version rather than pretending to enforce the boundary.
There is no read-only `Bash` to grant: the harness grants tool names, and any per-agent
allow-list of permitted op strings would be a second copy of a classification supertool
already publishes (`ops:roster`), which is exactly the shape this repository's governing
rule forbids. What *is* enforceable from in here is that every definition granted `Bash`
says so plainly, labels the restraint as advice, and points at the published
classification instead of copying it.

Three layers, because the three questions have different answers on different machines:

  presence     Every agent granted `Bash` carries an advisory section. Runs everywhere.
  wording      That section is labelled as advice and cites `ops:roster` as the authority
               for what acts. Runs everywhere, including CI, which has no supertool.
  roster       Where `supertool` is on PATH, the advisories are measured against the ops
               actually loaded: the class marks they name must still be the ones the tool
               declares, and no advisory may have grown into a copy of the roster. This
               is the layer CI cannot run, and it skips naming what went unmeasured
               rather than passing quietly.

Scope, declared rather than left to be discovered. The rule is universal over
`Bash`-granted agents rather than scoped to the read-only ones, and that is deliberate:
scoping it would need a list of which agents are read-only, and a hand-kept list of exempt
agents is the same drifting second copy in a smaller costume. The developer agent writes
files for a living and its advisory says so; what it shares with the auditors is that its
"do not push, do not publish" is prose with nothing behind it.

Known limit, stated because an unstated one reads as coverage: the roster layer measures
against the ops **loaded on this machine**, and which ops load depends on which presets a
project enables. An acting op that is not loaded here cannot be counted, so the
enumeration check under-fires on a machine with fewer presets. It never over-fires.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"

#: The heading that opens the advisory. Keyed on the claim rather than on an exact string
#: so a definition may word the rest of the heading for its own job.
ADVISORY_HEADING = re.compile(r"^(?P<hashes>#{2,6})\s+.*\bgrant is total\b", re.IGNORECASE)

#: The label the advisory must carry. `annotates, never blocks` was read as a boundary
#: because nothing said it was not one; a section that reads as a guarantee while being a
#: request is the same defect one level up.
ADVICE_LABEL = "advice, not a boundary"

#: The authority the advisory must point at, rather than listing acting ops itself.
CLASSIFICATION_AUTHORITY = "ops:roster"

#: Above this many distinct acting ops named in one advisory, it has stopped illustrating
#: the class and started enumerating the members. The threshold is a judgement and is
#: written here to be argued with: one or two names read as examples, and a list that
#: needs a third is a copy of something `ops:roster` answers live.
MAX_ACTING_OPS_NAMED = 2

_CODE_SPAN = re.compile(r"`([^`]+)`")


def agent_paths():
    return sorted(AGENTS_DIR.glob("*.md"))


def granted_tools(path):
    """The frontmatter grant, or None when the file declares no `tools:` line."""
    block = path.read_text(encoding="utf-8").split("\n---\n", 1)[0]
    line = re.search(r"^tools:\s*(.+)$", block, re.MULTILINE)
    if line is None:
        return None
    return {tool.strip() for tool in line.group(1).split(",") if tool.strip()}


def advisory_section(text):
    """The advisory's body, or None when the definition carries no advisory.

    Ends at the next heading of the same level or shallower, so a nested subsection stays
    inside the advisory rather than truncating it.
    """
    lines = text.splitlines()
    start = None
    depth = 0
    for index, line in enumerate(lines):
        opened = ADVISORY_HEADING.match(line)
        if opened is not None:
            start = index
            depth = len(opened.group("hashes"))
            continue
        if start is not None:
            heading = re.match(r"^(#{1,6})\s", line)
            if heading is not None and len(heading.group(1)) <= depth:
                return "\n".join(lines[start:index])
    if start is None:
        return None
    return "\n".join(lines[start:])


def code_span_ops(section):
    """Every op name named as a code span in `section`, e.g. `radar` or `gh-pr:12`."""
    named = set()
    for span in _CODE_SPAN.findall(section):
        head = span.strip().split(":", 1)[0].strip()
        if re.match(r"\A[A-Za-z][A-Za-z0-9_.-]*\Z", head or ""):
            named.add(head)
    return named


def missing_advisory(paths):
    """The findings: a `Bash`-granted definition with no advisory, or a hollow one."""
    findings = []
    for path in paths:
        grants = granted_tools(path)
        if grants is None:
            findings.append("{}: declares no `tools:` line".format(path.name))
            continue
        if "Bash" not in grants:
            continue
        section = advisory_section(path.read_text(encoding="utf-8"))
        if section is None:
            findings.append(
                "{}: grants Bash and carries no advisory heading saying the grant is "
                "total".format(path.name)
            )
            continue
        if ADVICE_LABEL not in section:
            findings.append(
                "{}: the advisory does not label itself {!r}, so it reads as a "
                "boundary".format(path.name, ADVICE_LABEL)
            )
        if CLASSIFICATION_AUTHORITY not in section:
            findings.append(
                "{}: the advisory does not cite {!r}, so it asks the agent to work from a "
                "classification written down here".format(path.name, CLASSIFICATION_AUTHORITY)
            )
    return findings


def enumerated_acting_ops(paths, acting):
    """(findings, scanned) -- advisories that have grown into a copy of the roster.

    The count is returned rather than left implicit because without it this function
    answers `[]` twice over: once having read every advisory and found no copying, and
    once having found no advisory to read at all. Those are the two states this
    repository is named after, and at the call site the second arrives as a green line
    saying the shipped advisories do not copy the roster.
    """
    findings = []
    scanned = 0
    for path in paths:
        grants = granted_tools(path)
        if grants is None or "Bash" not in grants:
            continue
        section = advisory_section(path.read_text(encoding="utf-8"))
        if section is None:
            continue
        scanned += 1
        named = sorted(code_span_ops(section) & acting)
        if len(named) > MAX_ACTING_OPS_NAMED:
            findings.append(
                "{}: the advisory names {} acting ops ({}) -- that is an enumeration, and "
                "`{}` answers it live".format(
                    path.name, len(named), ", ".join(named), CLASSIFICATION_AUTHORITY
                )
            )
    return findings, scanned


def roster_classes():
    """({op: mark}, reason) -- what supertool declares here, or why it could not say.

    Never an empty mapping for "could not ask": an empty roster and an unreadable one are
    the two states this repository is named after, and they come back separately.
    """
    executable = shutil.which("supertool")
    if executable is None:
        return None, "supertool is not on PATH"
    try:
        # The resolved path, not the bare name: on Windows `which` honours PATHEXT and
        # finds a `.cmd`/`.exe` that a bare name would not reach without a shell.
        completed = subprocess.run(
            [executable, "ops:roster"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return None, "supertool ops:roster timed out"
    except OSError as exc:
        return None, "supertool ops:roster did not run: {}".format(exc)
    text = completed.stdout.decode("utf-8", "replace")
    classes = {}
    for line in text.splitlines():
        if not line.startswith("  ") or line.strip()[:1] in ("-", ">", "`", "#"):
            continue
        for token in line.split():
            bare = token.rstrip("*!")
            if not re.match(r"\A[A-Za-z][A-Za-z0-9_.-]*\Z", bare):
                continue
            classes[bare] = token[len(bare):] or ""
    if not classes:
        return None, "supertool ops:roster named no ops (exit {})".format(completed.returncode)
    return classes, None


# ---------------------------------------------------------------------------
# The extractors, and the controls that keep an absence from reading as a pass.
# ---------------------------------------------------------------------------


def test_the_scan_finds_agents_that_are_granted_bash():
    """A population of zero would make every assertion below vacuously true."""
    paths = agent_paths()
    assert paths, "no agents/*.md found -- every check in this module would pass empty"
    granted = [p.name for p in paths if (granted_tools(p) or set()) & {"Bash"}]
    assert len(granted) >= 3, (
        "only {} agent definition(s) grant Bash: {} -- if the grants really changed, this "
        "floor is what needs re-deriving".format(len(granted), granted)
    )


def test_an_advisory_is_found_when_present_and_missed_when_absent():
    """Must-fire and must-not-fire for the section extractor, in one fixture."""
    with_it = (
        "---\ntools: Bash,TodoWrite\n---\n\n# Head\n\n"
        "## Your `Bash` grant is total\n\nThis is advice, not a boundary. Ask "
        "`ops:roster`.\n\n## Next\n\nunrelated\n"
    )
    without = "---\ntools: Bash,TodoWrite\n---\n\n## How you read\n\nnothing here\n"
    found = advisory_section(with_it)
    assert found is not None, with_it
    assert ADVICE_LABEL in found
    assert "unrelated" not in found, "the section ran past its own heading:\n" + found
    assert advisory_section(without) is None


def test_a_nested_subsection_does_not_truncate_the_advisory():
    text = (
        "## Your `Bash` grant is total\n\nadvice, not a boundary; ask `ops:roster`\n\n"
        "### A detail\n\nstill inside\n\n## Elsewhere\n\noutside\n"
    )
    section = advisory_section(text)
    assert "still inside" in section, section
    assert "outside" not in section, section


def test_a_missing_or_hollow_advisory_is_a_finding_and_a_good_one_is_not(tmp_path):
    """The positive control for the silence assertion below.

    Five definitions: one clean, one with no advisory at all, one that reads as a
    guarantee because it never says it is advice, one that asks the agent to work from a
    classification written down in the file, and one that is not granted Bash at all.
    """
    files = {
        "good.md": (
            "---\ntools: Bash,TodoWrite\n---\n\n## Your `Bash` grant is total\n\n"
            "This is advice, not a boundary. Ask `ops:roster` for what acts.\n"
        ),
        "absent.md": "---\ntools: Bash,TodoWrite\n---\n\n## Something else\n\nno\n",
        "unlabelled.md": (
            "---\ntools: Bash,TodoWrite\n---\n\n## Your `Bash` grant is total\n\n"
            "You must never write. Ask `ops:roster`.\n"
        ),
        "no_authority.md": (
            "---\ntools: Bash,TodoWrite\n---\n\n## Your `Bash` grant is total\n\n"
            "This is advice, not a boundary. Do not run acting ops.\n"
        ),
        "no_bash.md": "---\ntools: TodoWrite\n---\n\n## Something else\n\nfine\n",
    }
    paths = []
    for name, body in sorted(files.items()):
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        paths.append(path)

    findings = missing_advisory(paths)
    flagged = sorted({f.split(":", 1)[0] for f in findings})
    assert flagged == ["absent.md", "no_authority.md", "unlabelled.md"], findings
    assert "grants Bash and carries no advisory" in "\n".join(findings)


def test_an_advisory_that_lists_acting_ops_is_a_finding_and_one_example_is_not(tmp_path):
    """The enumeration control, both directions, against a fixed acting set.

    Prose words are not op names: `edit` and `paste` are acting ops, and the word "edit"
    in a sentence is not naming one. Only code spans count, and this fixture says so.
    """
    acting = {"radar", "watch", "unwatch", "gh-pr-merge", "edit", "paste"}
    header = "---\ntools: Bash,TodoWrite\n---\n\n## Your `Bash` grant is total\n\n"
    body = "This is advice, not a boundary. Ask `ops:roster`.\n"

    listy = tmp_path / "listy.md"
    listy.write_text(
        header + body + "Never run `radar`, `watch`, `unwatch` or `gh-pr-merge`.\n",
        encoding="utf-8",
    )
    example = tmp_path / "example.md"
    example.write_text(
        header + body + "An acting op such as `radar` heals a live fleet.\n",
        encoding="utf-8",
    )
    prose = tmp_path / "prose.md"
    prose.write_text(
        header + body + "You may not edit, paste or watch anything here.\n",
        encoding="utf-8",
    )

    findings, scanned = enumerated_acting_ops([listy, example, prose], acting)
    assert scanned == 3, scanned
    assert len(findings) == 1, findings
    assert findings[0].startswith("listy.md: the advisory names 4 acting ops"), findings[0]


def test_no_copying_found_is_distinguishable_from_nothing_scanned(tmp_path):
    """The third state, in the same fixture as the two it sits between.

    Without the count, this function answers `[]` for both "read four advisories, none
    copies the roster" and "found no advisory to read", and at the call site the second
    arrives as a green line asserting the first. Reported by an audit of this very diff.
    """
    clean = tmp_path / "clean.md"
    clean.write_text(
        "---\ntools: Bash,TodoWrite\n---\n\n## Your `Bash` grant is total\n\n"
        "advice, not a boundary; ask `ops:roster`\n",
        encoding="utf-8",
    )
    nothing_to_scan = tmp_path / "nothing.md"
    nothing_to_scan.write_text(
        "---\ntools: TodoWrite\n---\n\n## Elsewhere\n\nnot granted Bash\n", encoding="utf-8"
    )

    scanned_clean = enumerated_acting_ops([clean], {"radar", "watch"})
    unscanned = enumerated_acting_ops([nothing_to_scan], {"radar", "watch"})
    assert scanned_clean == ([], 1), scanned_clean
    assert unscanned == ([], 0), unscanned
    assert scanned_clean != unscanned, (
        "a clean scan and an empty population came back identical -- the finding this "
        "check exists for"
    )


# ---------------------------------------------------------------------------
# The shipped definitions.
# ---------------------------------------------------------------------------


def test_every_bash_granted_agent_says_the_grant_is_total():
    """The layer that runs in CI, where there is no supertool to ask.

    `Bash` reaches the filesystem, the forge and shared state outside this repository
    altogether. A definition that describes its remit without saying that is asking the
    reader to infer a boundary from a summary of its output.
    """
    findings = missing_advisory(agent_paths())
    assert not findings, (
        "agent definitions imply an effect boundary their `Bash` grant does not hold:\n  "
        + "\n  ".join(findings)
    )


def test_the_shipped_advisories_do_not_copy_the_roster():
    """The layer only a machine carrying supertool can run -- and it says when it did not."""
    classes, reason = roster_classes()
    if classes is None:
        pytest.skip(
            "{} -- the shipped advisories went unmeasured against a live op "
            "classification".format(reason)
        )
    acting = {op for op, mark in classes.items() if mark in ("*", "!")}
    assert acting, "the roster declared no acting ops, so this check saw nothing to copy"
    findings, scanned = enumerated_acting_ops(agent_paths(), acting)
    assert scanned >= 3, (
        "only {} advisory section(s) were scanned against {} acting ops -- a clean result "
        "over an empty population is what this check is here to not "
        "produce".format(scanned, len(acting))
    )
    assert not findings, "\n  ".join([""] + findings)


def test_the_class_marks_the_advisories_name_are_the_ones_supertool_declares():
    """A second measurement, not a restatement.

    The advisories tell an agent to treat `*` and `!` as acting. Those two characters are
    supertool's vocabulary, not this repository's, so if the tool renames them the advice
    points at nothing while still reading as complete. Assert against the live roster
    rather than against a fixture of one, which is what #241 was about.
    """
    classes, reason = roster_classes()
    if classes is None:
        assert reason, "roster_classes() returned no classes and no reason"
        pytest.skip("{} -- the class marks went unmeasured".format(reason))
    marks = set(classes.values())
    assert "" in marks, "the roster declared no read-only ops: {}".format(sorted(marks))
    assert {"*", "!"} & marks, (
        "supertool's roster no longer marks any op `*` or `!`; the marks are now {} -- the "
        "advisories in agents/*.md name characters that classify nothing".format(sorted(marks))
    )
