"""No count in this repository is aggregated per page (#137).

``gh api ... --paginate --jq "length"`` runs the filter **once per page** and prints one
number per page. Measured upstream: ``98`` then ``13``, against a real total of ``111``.
Whoever reads the first line gets a number smaller than the truth, correctly formatted,
at exit 0 -- a partial read rendering as a total, which is this plugin's own defect class
pointed at arithmetic.

**Today nothing that ships in this tree does it.** That is the finding, and it is worth
writing down rather than leaving as an unremarked green: a trap documented against code
that does not exist is one nobody recognises when it arrives. So this is a sweep and not
a comment. It runs over the tracked tree, it reports how many sources it read, and it
fails when the shape appears.

## What counts as a command, and why prose does not

``agents/triager.md`` documents this trap in a sentence containing both ``--paginate``
and ``length``. Flagging it would make the sweep punish its own documentation, and the
first fix anybody reached for would be to stop documenting the trap. So the scanner reads
**commands**: every line of a script or a workflow, and in Markdown only the lines inside
a fenced code block. A sentence about a command is not a command.

That is a real limit and it cuts both ways -- an aggregation described in prose outside a
fence, as something to run, is invisible here. Both arms are fixtured below, so the
boundary is a decision on record rather than an accident of a regex.

**And a command is a statement, not a neighbourhood.** The first cut of this scanner
asked whether a `--slurp` sat within 200 characters of a `--paginate`, which is wide
enough to span a wrapped argument list and therefore wide enough to reach the *next*
command: one fixed call two lines below a broken one silently cleared the broken one --
the shape a partial migration makes, and the exact case this file exists for. Markdown
had the mirror bug, dropping the prose between two fences until unrelated blocks were
adjacent. Both are gone: a group is one fenced block or one script, and a command inside
it runs until its brackets close.

## Exemptions are named, and a stale one fails

This file is itself full of the shape, on purpose. It is listed in ``EXEMPT`` with the
reason, and ``EXEMPT`` is checked in the other direction too: an entry that no longer
produces a finding is deleted rather than carried, because an exemption covering nothing
is a hole that reads like a decision.

## Three outcomes

  clean            sources were read, at least one existed, none aggregates per page
  findings         one or more command units aggregate a paginated listing
  could-not-scan   a source would not read, **or the scan found no sources at all**

The vacuity case belongs with the failure, not with the pass. A sweep over nothing is
trivially clean, and "clean" is exactly what it must not be allowed to say.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

CLEAN = "clean"
FINDINGS = "findings"
COULD_NOT_SCAN = "could-not-scan"

# label -> why the shape being there is correct. Nothing else may carry it.
EXEMPT = {
    "tests/test_paginated_counts.py": (
        "the fixtures below, and the docstring above, are the defect by construction -- "
        "they are what proves the scanner can see anything at all. "
        "`test_the_scanner_flags_its_own_bad_fixture` pins which line the exemption is "
        "covering, because an exemption satisfied by some other line in the same file "
        "is a hole wearing a decision's clothes"
    ),
}

# A statement that has not closed its brackets by this many lines is cut anyway. A
# bracket inside a string literal can leave the count permanently open, and an
# unterminated statement would swallow the rest of the file into one command -- which
# is the false-positive engine, not a conservative default.
_MAX_STATEMENT_LINES = 8

_PAGINATE = re.compile(r"--paginate")
# `--jq length`, `--jq '.[] | length'`, `-q length`, `| jq length`. Quoting varies and
# the filter is what matters, so this asks for a jq invocation and a `length` word.
_JQ = re.compile(r"(--jq|\|\s*jq\b|\s-q\s)")
_LENGTH = re.compile(r"\blength\b")
# `--slurp` collects every page into one array before the filter runs, which is the
# documented fix. A window carrying it is correct, not a finding.
_SLURP = re.compile(r"--slurp")

_MARKDOWN_SUFFIXES = (".md", ".markdown")
_SCRIPT_SUFFIXES = (".py", ".sh", ".yml", ".yaml", ".bash")


def command_groups(label, text):
    """The blocks of ``text`` that hold commands, each a list of ``(number, line)``.

    Markdown contributes **one group per fenced block**. Prose between fences is not a
    command, and two fences are two contexts -- collapsing them into one string brought
    unrelated blocks into each other's reach. Everything else is one group; a script is
    one context, and ``statements`` separates the commands inside it.
    """
    lines = text.splitlines()
    if not label.lower().endswith(_MARKDOWN_SUFFIXES):
        return [list(enumerate(lines, 1))]

    groups = []
    current = []
    fenced = False
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            if fenced:
                groups.append(current)
                current = []
            fenced = not fenced
            continue
        if fenced:
            current.append((number, line))
    if current:
        groups.append(current)
    return [group for group in groups if group]


def statements(group):
    """Split one group into commands, on bracket depth.

    A command is a line, unless its brackets are still open -- which is what an argument
    list wrapped across lines looks like, and the whole reason a line-local match was
    not enough. Proximity is *not* enough either, and that was the bug: a `--slurp` on
    the following command sat inside a 200-character window and cleared a genuine
    finding on the one above it. Adjacency in characters is not membership in a command.
    """
    commands = []
    current = []
    depth = 0
    for number, line in group:
        current.append((number, line))
        depth += sum(line.count(char) for char in "([{")
        depth -= sum(line.count(char) for char in ")]}")
        if depth <= 0 or len(current) >= _MAX_STATEMENT_LINES:
            commands.append(current)
            current = []
            depth = 0
    if current:
        commands.append(current)
    return commands


def scan(sources):
    """``sources`` is ``{label: text or None}``. ``None`` means it would not read.

    Returns ``{"state", "findings", "scanned", "unreadable"}``, where ``findings`` is a
    list of ``(label, line number, the line)``.
    """
    unreadable = sorted(label for label, text in sources.items() if text is None)
    readable = {label: text for label, text in sources.items() if text is not None}

    findings = []
    for label in sorted(readable):
        for group in command_groups(label, readable[label]):
            for command in statements(group):
                text = "\n".join(line for _, line in command)
                if not _PAGINATE.search(text) or _SLURP.search(text):
                    continue
                if not (_JQ.search(text) and _LENGTH.search(text)):
                    continue
                number, line = next(
                    (number, line)
                    for number, line in command
                    if _PAGINATE.search(line)
                )
                findings.append((label, number, line.strip()))

    if unreadable or not readable:
        state = COULD_NOT_SCAN
    elif findings:
        state = FINDINGS
    else:
        state = CLEAN
    return {
        "state": state,
        "findings": findings,
        "scanned": len(readable),
        "unreadable": unreadable,
    }


# ------------------------------------------------------------------ the scanner itself


BAD = "gh api repos/o/r/issues --paginate --jq 'length'"
GOOD_SLURPED = "gh api repos/o/r/issues --paginate --slurp --jq 'length'"
GOOD_PLAIN = "gh api repos/o/r/issues --paginate > all.json"


def test_the_scanner_finds_the_shape_it_is_looking_for():
    """The positive control. Without it, every green below could mean the regex matches
    nothing at all."""
    result = scan({"fixture.sh": BAD})
    assert result["state"] == FINDINGS
    assert result["findings"][0][0] == "fixture.sh"
    assert "--paginate" in result["findings"][0][2]


def test_slurped_and_plain_pagination_are_not_findings():
    """The negative control, in the same fixture as the positive one."""
    result = scan({"fixture.sh": GOOD_SLURPED + "\n" + GOOD_PLAIN})
    assert result["state"] == CLEAN
    assert result["findings"] == []


def test_an_argument_list_split_across_lines_is_still_one_command():
    source = (
        "ok, rows, detail = _gh_json(\n"
        "    root,\n"
        "    ['api', 'repos/o/r/issues', '--paginate',\n"
        "     '--jq', 'length'],\n"
        ")\n"
    )
    assert scan({"caller.py": source})["state"] == FINDINGS


def test_markdown_prose_documenting_the_trap_is_not_a_finding():
    prose = "A `--paginate` count aggregated with `--jq 'length'` prints one per page."
    assert scan({"guide.md": prose})["state"] == CLEAN


def test_markdown_inside_a_fence_is_scanned():
    """Otherwise the test above would be passing because Markdown is never read."""
    fenced = "Run this:\n```bash\n" + BAD + "\n```\n"
    result = scan({"guide.md": fenced})
    assert result["state"] == FINDINGS
    assert result["findings"][0][1] == 3


def test_a_slurp_on_a_neighbouring_command_does_not_excuse_this_one():
    """The shape a partial migration makes: one call fixed, the one above it not.

    Reviewed on this branch and reproduced -- a character window wide enough to span a
    wrapped argument list is also wide enough to reach the next command, so a `--slurp`
    two lines away silently cleared a genuine finding. Both arms in one fixture: the
    fixed call is not a finding and the broken one is.
    """
    script = "\n".join(
        [
            "count1=$(gh api repos/o/r/issues --paginate --jq 'length')",
            "count2=$(gh api repos/o/r/pulls --paginate --slurp --jq 'length')",
        ]
    )
    result = scan({"deploy.sh": script})
    assert result["state"] == FINDINGS
    assert [number for _, number, _ in result["findings"]] == [1]


def test_two_unrelated_fenced_blocks_are_not_one_command():
    """Markdown drops the prose between fences, which brought two independent blocks
    into each other's window. A bare `--paginate` in one and an unrelated `--jq length`
    in the other is not a per-page aggregation."""
    markdown = "\n".join(
        [
            "First:",
            "```bash",
            "gh api repos/o/r/issues --paginate > pages.ndjson",
            "```",
            "Then, separately:",
            "```bash",
            "gh api repos/o/r/labels --jq length",
            "```",
        ]
    )
    assert scan({"guide.md": markdown})["state"] == CLEAN


def test_the_scanner_flags_its_own_bad_fixture():
    """The exemption for this file has to cover the fixture it claims to cover.

    It was passing on the module docstring instead, while the fixture two lines below
    `GOOD_SLURPED` escaped -- an exemption that reads as covering one thing and covers
    another is a hole wearing a decision's clothes.
    """
    source = (REPO_ROOT / "tests" / "test_paginated_counts.py").read_text(
        encoding="utf-8"
    )
    lines = source.splitlines()
    bad_line = next(
        number
        for number, line in enumerate(lines, 1)
        if line.startswith("BAD = ")
    )
    flagged = {number for _, number, _ in scan({"self.py": source})["findings"]}
    assert bad_line in flagged, "the BAD fixture at line {} escaped".format(bad_line)


def test_a_source_that_would_not_read_is_could_not_scan_and_never_clean():
    result = scan({"fine.sh": GOOD_PLAIN, "broken.sh": None})
    assert result["state"] == COULD_NOT_SCAN
    assert result["unreadable"] == ["broken.sh"]


def test_a_finding_still_reports_could_not_scan_when_a_source_was_lost():
    """A sweep that could not look must not report a total, in either direction."""
    assert scan({"bad.sh": BAD, "broken.sh": None})["state"] == COULD_NOT_SCAN


def test_an_empty_scan_is_could_not_scan_rather_than_clean():
    assert scan({})["state"] == COULD_NOT_SCAN


# ---------------------------------------------------------------------- the shipped tree


def _tracked_sources():
    """``{path: text or None}`` over the tracked files this sweep can speak about."""
    # `--others --exclude-standard` as well as the cache: a sweep that read only what
    # is committed answers clean about a script somebody just wrote, which is the exact
    # shape of absence this file exists to refuse.
    try:
        done = subprocess.run(
            [
                "git",
                "-C",
                str(REPO_ROOT),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.SubprocessError):
        # A `git` that will not spawn has to reach this function's own "could not look"
        # answer. Left uncaught it raises out of the fixture at collection time, which
        # is a crash where a stated third state belongs.
        return None
    if done.returncode != 0:
        return None
    # Bytes, decoded here rather than by `universal_newlines=True`. What this call
    # carries is pathnames, which is the one place a byte the locale cannot decode is
    # ordinary rather than exotic -- and a strict decode would raise a UnicodeDecodeError
    # out of a sweep whose whole contract is three states (#112).
    names = [
        name
        for name in done.stdout.decode("utf-8", errors="replace").split("\0")
        if name
    ]
    wanted = [
        name
        for name in names
        if name.lower().endswith(_MARKDOWN_SUFFIXES + _SCRIPT_SUFFIXES)
        or name.startswith("bin/")
    ]
    sources = {}
    for name in wanted:
        try:
            sources[name] = (REPO_ROOT / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            sources[name] = None
    return sources


@pytest.fixture(scope="module")
def swept():
    sources = _tracked_sources()
    if sources is None:
        pytest.skip("git ls-files did not answer, so this sweep read nothing")
    return scan(sources)


def test_an_unspawnable_git_reaches_the_skip_rather_than_a_traceback(monkeypatch):
    """The platform band's own item: a binary that will not spawn must reach the "the
    tool failed" arm, not raise past it.

    Only `returncode` was handled, so a `PATH` without `git` -- a stripped container, a
    minimal image -- crashed at collection instead of skipping with a reason. No CI leg
    can catch this: every leg runs `actions/checkout`, which guarantees `git`.

    Both arms: the raising spawn skips, and a spawn that merely exits non-zero still
    returns `None` rather than an empty scan that would read as clean.
    """
    def raises(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory: 'git'")

    monkeypatch.setattr(subprocess, "run", raises)
    assert _tracked_sources() is None

    class Failed(object):
        returncode = 128
        stdout = b""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Failed())
    assert _tracked_sources() is None


def test_the_sweep_actually_read_the_tree(swept):
    """Reported before any verdict, so a clean answer over four files is visible as one."""
    assert swept["scanned"] > 20, "only {} sources were read".format(swept["scanned"])
    assert swept["unreadable"] == []


def test_the_sweep_read_the_file_that_documents_the_trap():
    """A named source, because a glob that quietly stopped matching would leave every
    assertion here trivially true."""
    sources = _tracked_sources()
    assert sources is not None
    assert "--paginate" in (sources.get("agents/triager.md") or "")


def test_every_exemption_still_covers_something(swept):
    """An exemption covering nothing is a hole that reads like a decision."""
    flagged = {label for label, _, _ in swept["findings"]}
    stale = sorted(set(EXEMPT) - flagged)
    assert stale == [], "these exemptions no longer cover anything: {}".format(stale)


def test_no_shipped_command_aggregates_a_count_per_page(swept):
    unexpected = [
        finding for finding in swept["findings"] if finding[0] not in EXEMPT
    ]
    assert unexpected == [], "per-page aggregation: {}".format(unexpected)

