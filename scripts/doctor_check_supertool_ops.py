"""``check_supertool_ops`` -- does the supertool that resolves here carry the ops
this plugin's own shipped text names? (#582)

`doctor.py` already answers two neighbouring questions and neither is this one:
`check_tool` answers *is supertool on PATH*, and `check_supertool_entry_point`
answers *is `./supertool` the right entry point*. This plugin and the supertool
carrying the ops its commands call are two separately released artifacts on two
clocks, so a version of `oss` naming an op the installed supertool predates
fails loudly -- `unknown operation` -- but only mid-tick, at the step that
needed it, with nothing having asked first. That is #551's class one dependency
over: two mechanisms answering "am I current" from different sources, with the
diagnostic reporting whichever happened to be fine.

**Three states, and the third is the whole reason this is a function rather than
a set comparison at the call site.** `present`, `missing`, and `could-not-ask` --
the roster call itself did not answer, so nothing here knows. A `could-not-ask`
rendered as `present` is a confident answer to a question nobody put, which is
the defect class this repository is named after.

**The expected set is derived from the shipped text, never listed here.** A
constant beside the check goes silently narrower than its subject the moment
somebody adds a call -- the shape #547 records for `checklist_skew.py` pinning
to `skills/manager/SKILL.md` across the phase split. `scripts/manager_docs.py`
is the precedent this follows.

**There is a sibling, and it is named here rather than left for somebody to
discover.** `tests/test_shipped_op_spellings.py` (#197/#224) asks a closely
related question in the suite: every op spelling invoked in shipped prose must
appear in a hand-declared `OP_INVENTORY`, and where supertool is on
PATH those declarations are measured against `ops:roster` too. #582's own
pre-flight looked at `doctor.py` and correctly found nothing; it did not look at
`tests/`, so this overlap is real and was not known when the issue was written.

What each one answers is still different, which is why both exist rather than
one being deleted:

* that test runs in the suite and in CI, against a **declared** list a human
  maintains, and it can fail a pull request over a spelling nobody confirmed;
* this check runs on the machine being diagnosed, against a set **derived** at
  call time with nothing to maintain, and it is the only one a user of this
  plugin -- who never runs this repository's test suite -- ever sees.

They also disagree about scope on purpose: that test reads shipped prose plus
`bin/oss-workspace` and `scripts/doctor*.py`, because its subject is remedies a
reader pastes; this one reads `commands/`, `skills/` and `agents/`, because its
subject is calls a session makes. Whether the pair should be collapsed is a
maintainer's call and not one this lane made -- it is recorded here so the
question is visible from either file.

**Which directories are scanned is itself a measurement, not a preference.** A
whole-tree scan of this repository's markdown was tried first and derived three
op names that are not ops at all -- `write`, `op1` and `op2`, every one of them
out of `CHANGELOG.md`, where they appear inside prose describing a payload
shape. Narrative history is not instruction text a session executes, and three
spurious `missing` names would be a WARN telling a maintainer their supertool
is broken when it is not. So the scan is `OP_TEXT_ROOTS` below: the directories
whose markdown an agent runs. Each root reports its own state, and the check
says so, so the narrowing is visible rather than assumed.

Every shared name -- `report`, `_rglob_md`, `_dir_state`, `_one_line`,
`SUPERTOOL_ENTRY`, `PLUGIN_ROOT` -- is reached through `doctor` imported as a
module (`import doctor`), never `from doctor import name`, the same convention
`scripts/doctor_check_statusline.py` spells out in full: a name looked up this
way is always the current value in `doctor`'s own namespace, which is what keeps
a test's `monkeypatch.setattr(doctor, ...)` reaching this code.

Python 3.9 compatible.
"""

import re
import shutil
import subprocess
from pathlib import Path

import doctor

#: The directories under the plugin root whose markdown is instruction text a
#: session executes. Not a preference -- see the module docstring for the
#: measurement that ruled out scanning the whole tree.
OP_TEXT_ROOTS = ("commands", "skills", "agents")

#: The op used to ask. `ops:roster` rather than `ops`, because the roster is the
#: complete list by contract: supertool's own descriptive `ops` listing stops
#: being complete once a project has enough ops to pass its SessionStart cap, and
#: an inventory read off a truncated listing would invent `missing` findings.
ROSTER_OP = "ops:roster"

#: Long enough for a cold start, short enough that a diagnostic still returns.
#: `check_tool` and `mcp_channel_registration_state` in `doctor.py` both use 20.
ROSTER_TIMEOUT = 20

#: An argument of a call, in the two spellings the shipped text uses. The bare
#: one is an auditor finding on this diff and its width is measured, not guessed:
#: requiring a colon in a bare argument derives exactly one thing across
#: commands/, skills/ and agents/ today -- `ops:roster`, out of a line this very
#: diff added to commands/doctor.md -- and nothing else. Dropping the colon
#: requirement instead derives eighteen English words (`and`, `that`, `is`,
#: `predates`, ...), because `the supertool that answers here` is a sentence, not
#: a call. So the colon stays, and the residual is stated rather than left to be
#: found: a bare op named with NO argument (`supertool ops`) is still invisible
#: to this derivation, and the eighteen words are why it has to be.
_QUOTED_ARG = r"'[^'\n]*'" + r'|"[^"\n]*"'
_BARE_ARG = r"[a-z][a-z0-9_-]*:[^\s`" + "'" + r'"]*'
_ARG_ALTERNATION = "(?:" + _QUOTED_ARG + "|" + _BARE_ARG + ")"

#: A supertool call in shipped text: the command (optionally as `./supertool` or
#: under `${CLAUDE_PLUGIN_ROOT}/`), then one or more op arguments. The lookahead
#: keeps `python3 supertool.py '...'` -- a filename, not the command -- from being
#: read as a call, and the matching lookbehind is not symmetry: a reviewer finding
#: on this diff measured that a bare word boundary is satisfied by a hyphen, so
#: `not-supertool 'fake-op'` in prose derived `fake-op` and would have produced a
#: `missing` line naming a call nobody makes. Both sides exclude `-` and `.`, not
#: only the word characters a boundary already covers.
_CALL_RE = re.compile(
    r"(?:\./|\$\{CLAUDE_PLUGIN_ROOT\}/)?(?<![\w.-])supertool(?![\w.-])[ \t]+"
    + "(" + _ARG_ALTERNATION + r"(?:[ \t]+" + _ARG_ALTERNATION + r")*)"
)

#: One argument out of a matched call. Written as concatenated raw strings so
#: neither quote character has to be escaped inside the other.
_ARG_RE = re.compile(
    r"'([^'\n]*)'" + r'|"([^"\n]*)"' + "|(" + _BARE_ARG + ")"
)

#: The op name is the leading segment of an op string, before its first colon.
#: An argument that does not start with one -- `@-`, `<N>`, a placeholder in
#: prose -- names no op and contributes nothing rather than being guessed at.
_OP_NAME_RE = re.compile(r"\A[a-z][a-z0-9_-]*")

#: One entry in the roster's own name block: an op name, optionally carrying the
#: safety class supertool annotates it with.
_ROSTER_TOKEN_RE = re.compile(r"\A[a-z][a-z0-9_-]*[*!]?\Z")

#: A token ordinary English prose does not produce: a compound name, or one
#: carrying supertool's declared safety class. See `_is_op_vocabulary`.
_COMPOUND_RE = re.compile(r"[-_]|[*!]\Z")


def ops_in_text(text):
    """Every op name named by a `supertool ...` call in `text`, in order."""
    found = []
    for call in _CALL_RE.finditer(text):
        for arg in _ARG_RE.finditer(call.group(1)):
            raw = next((group for group in arg.groups() if group is not None), "")
            name = _OP_NAME_RE.match(raw)
            if name is not None:
                found.append(name.group(0))
    return found


def named_ops(plugin_root=None):
    """``(ops, roots)`` -- what this plugin's shipped text calls, and how each
    source root answered.

    ``ops`` maps an op name to the sorted relative paths naming it, so a
    ``missing`` finding can point at the call that will break rather than at a
    count. ``roots`` is one ``(name, state, detail)`` per entry of
    `OP_TEXT_ROOTS`, ``state`` being ``read`` / ``absent`` / ``unreadable``.

    **A root that could not be read is `unreadable`, never an empty
    contribution.** `_rglob_md` is used rather than `Path.rglob` for exactly
    that reason (#383): pathlib's recursive glob swallows `PermissionError`
    while it walks and yields nothing for the subtree, so a denied directory
    and an empty one are the same answer to it. `_dir_state` answers the
    top-level presence question separately, because `_rglob_md` deliberately
    reports an absent root as *nothing found*.
    """
    root = doctor.PLUGIN_ROOT if plugin_root is None else Path(plugin_root)
    ops = {}
    roots = []
    for name in OP_TEXT_ROOTS:
        directory = root / name
        state, detail = doctor._dir_state(directory)
        if state == "unreadable":
            roots.append((name, "unreadable", detail))
            continue
        if state != "dir":
            roots.append((name, "absent", ""))
            continue
        files, unreadable = doctor._rglob_md(directory)
        for path in files:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                # The file was listed and then would not open. That is a gap in
                # the derivation, not a file with no calls in it.
                unreadable.append(doctor._one_line(str(exc)))
                continue
            try:
                display = path.relative_to(root).as_posix()
            except ValueError:  # pragma: no cover - path is built from `root`
                display = path.name
            for op_name in ops_in_text(text):
                ops.setdefault(op_name, set()).add(display)
        if unreadable:
            roots.append((name, "unreadable", doctor._one_line("; ".join(unreadable))))
        else:
            roots.append((name, "read", "{} file(s)".format(len(files))))
    return dict((key, sorted(value)) for key, value in ops.items()), roots


def _is_op_vocabulary(tokens):
    """Does this contiguous run of name-shaped tokens look like an op vocabulary
    rather than a run of English words?

    **This is the half a reviewer defeated, and the fix is bounded rather than
    complete.** The first version accepted any indented line whose tokens all
    matched `_ROSTER_TOKEN_RE`, and lowercase prose with no punctuation matches
    that shape exactly: a two-line banner reading *"usage information for ops and
    other legacy commands is deprecated / please update your config to continue
    using this tool safely"* parsed to twenty English words, one of which was
    `ops` -- the very token `supertool_roster` uses as its control. A parse that
    can be satisfied by prose cannot be a control against prose.

    So a block additionally has to carry at least one token no English sentence
    produces: a compound name (`gh-pr-create`, `around_line`, `ops-compact`) or a
    declared safety class (`paste*`, `radar!`). That is a property of supertool's
    op namespace rather than a list of its op names -- a list here would go
    narrower than its subject the moment supertool adds an op, which is the whole
    thing #582 forbids.

    **The limit, stated rather than left to be discovered.** A supertool loading
    only single-word read-only ops would fail this test and be reported
    `could-not-ask`. That is over-refusal, and it is the safe direction: the
    answer is a WARN saying nothing was established, never a `present` clearing a
    gap nobody measured and never a `missing` naming ops that are really there.
    """
    return any(_COMPOUND_RE.search(token) for token in tokens)


def parse_roster(text):
    """Every op name in a `supertool ops:roster` output.

    The roster's names arrive as an indented block of whitespace-separated
    tokens, each optionally carrying its safety class (`*`, `!`). A line joins a
    block only when it is indented AND every token on it is shaped like an op
    name; anything else ends the block. Blocks are kept **contiguous** rather
    than accumulated across a whole output, so scattered prose lines cannot pool
    into one apparent vocabulary, and a block is admitted only if
    `_is_op_vocabulary` recognises it -- see there for what that buys and what it
    does not.

    Nothing here knows the wording of any particular supertool version's header,
    which is deliberate: a parse anchored on a header sentence breaks silently
    the first time the header is reworded, and silence is the failure mode this
    module exists to avoid.
    """
    names = set()
    block = []

    def _flush():
        if block and _is_op_vocabulary(block):
            for token in block:
                names.add(token.rstrip("*!"))
        del block[:]

    for line in text.splitlines():
        tokens = line.split() if line[:1].isspace() else []
        if tokens and all(_ROSTER_TOKEN_RE.match(token) for token in tokens):
            block.extend(tokens)
            continue
        _flush()
    _flush()
    return names


def supertool_roster(run=None, which=None, cwd=None):
    """``(state, ops, detail)`` -- what the resolved supertool says it carries.

    ``state`` is ``read`` or ``could-not-ask``, and there is no third value on
    purpose: every way of failing to get an answer is the same answer, which is
    *nothing was measured*.

    ``cwd`` matters and is not decoration: which ops are loaded depends on the
    `presets` list in the `.supertool.json` that resolves from the calling
    directory, so asking from the plugin's own tree would answer a question
    about the wrong repository. `main()` passes the directory being diagnosed.

    **The parse carries its own positive control.** The roster is fetched by
    running an op, so that op must appear in what came back. An output the parse
    did not understand yields an empty or partial set that would otherwise be
    reported as "supertool carries nothing", inventing a `missing` finding for
    every op this plugin names. When the control op is absent, the answer is
    `could-not-ask` -- the honest one.

    `shutil.which`, deliberately, and not `doctor._locate_on_path`. That helper
    exists for a question this is not asking -- *does a file of this name exist
    on PATH so its bytes can be read* -- and it is right there precisely because
    `shutil.which` will not consider an extensionless name on Windows. Here the
    binary has to be **launched**, which is the question `shutil.which` answers,
    and `check_tool("supertool", ...)` in `doctor.py` already resolves it exactly
    this way. Keeping the two identical is the point: if supertool is unlaunchable
    on this machine, the PATH line above says so and this line says `could-not-ask`
    for the same reason, rather than the two disagreeing about the same binary.
    Reasoned for Windows, observed on macOS.
    """
    which = shutil.which if which is None else which
    run = subprocess.run if run is None else run
    control = ROSTER_OP.split(":")[0]

    if which(doctor.SUPERTOOL_ENTRY) is None:
        return (
            "could-not-ask",
            set(),
            "supertool is not on PATH, so nothing here could be asked which ops it carries",
        )
    argv = [doctor.SUPERTOOL_ENTRY, ROSTER_OP]
    kwargs = dict(
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=ROSTER_TIMEOUT,
    )
    if cwd is not None:
        kwargs["cwd"] = str(cwd)
    try:
        completed = run(argv, **kwargs)
    except (OSError, subprocess.SubprocessError) as exc:
        return "could-not-ask", set(), "`supertool {}` did not run ({})".format(ROSTER_OP, exc)
    if completed.returncode != 0:
        return (
            "could-not-ask",
            set(),
            "`supertool {}` exited {}".format(ROSTER_OP, completed.returncode),
        )
    # Bytes, decoded here rather than by asking `subprocess` for text mode:
    # text mode decodes with the runner's locale, and a roster carrying a
    # character that locale cannot decode raises `UnicodeDecodeError` -- a
    # `ValueError`, so the guard above would not catch it -- out of a script
    # contracted to exit 0. `check_tool` in `doctor.py` records the same trap.
    stdout = completed.stdout
    text = stdout.decode("utf-8", "replace") if isinstance(stdout, bytes) else str(stdout or "")
    available = parse_roster(text)
    if control not in available:
        return (
            "could-not-ask",
            set(),
            "`supertool {}` ran, and its output does not list `{}` -- the op used "
            "to ask it -- so the roster was not understood and must not be read as "
            "a complete inventory".format(ROSTER_OP, control),
        )
    return "read", available, ""


def supertool_op_inventory(plugin_root=None, run=None, which=None, cwd=None):
    """``(state, detail)`` -- ``present`` / ``missing`` / ``could-not-ask``.

    The order the arms are tried in is a decision: a **confirmed** gap outranks a
    partial derivation, because an op that is named and demonstrably absent is a
    real finding whether or not some other directory could also be read. Only
    when nothing is missing does an unreadable root turn the answer back into
    `could-not-ask`, since `present` over a partial set is a claim about text
    that was never opened.

    Deriving **no** ops at all is `could-not-ask` too, with its own reason. An
    expected set of zero is vacuously satisfied by any roster, so reporting it as
    `present` is the same defect as reporting an unread roster as one.
    """
    named, roots = named_ops(plugin_root)
    unreadable = [(name, detail) for name, state, detail in roots if state == "unreadable"]

    state, available, detail = supertool_roster(run=run, which=which, cwd=cwd)
    if state != "read":
        return "could-not-ask", detail

    missing = sorted(name for name in named if name not in available)
    if missing:
        listed = ", ".join(
            "{} (named by {})".format(name, ", ".join(named[name])) for name in missing
        )
        clause = ""
        if unreadable:
            clause = " -- and {} source root(s) could not be read, so there may be more".format(
                len(unreadable)
            )
        return "missing", (
            "{} of {} op(s) this plugin's shipped text names are not carried by the "
            "supertool that resolves here: {}{}".format(
                len(missing), len(named), listed, clause
            )
        )
    if unreadable:
        return "could-not-ask", (
            "the supertool that resolves here was read, and {} source root(s) of "
            "this plugin were not, so whether every op it names resolves is "
            "unknown: {}".format(
                len(unreadable), "; ".join("{}: {}".format(n, d) for n, d in unreadable)
            )
        )
    if not named:
        # The per-root states are in the sentence rather than summarised away: a
        # root that is not there and a root that was read and holds no call are
        # the same empty contribution and are not the same fact, and this is the
        # one arm where nothing else in the line distinguishes them.
        return "could-not-ask", (
            "no supertool call was found in this plugin's own text ({}), so there "
            "was no expected set to check the roster against -- an empty "
            "expectation is satisfied by any roster and is not evidence".format(
                _roots_detail(roots)
            )
        )
    return "present", (
        "all {} op(s) named by {} of this plugin resolve in the supertool that "
        "answers here".format(len(named), _roots_phrase())
    )


def _roots_phrase():
    return ", ".join("{}/".format(name) for name in OP_TEXT_ROOTS)


def _roots_detail(roots):
    """One clause per source root, naming its state."""
    return "; ".join(
        "{}/: {}{}".format(name, state, " -- {}".format(detail) if detail else "")
        for name, state, detail in roots
    )


def check_supertool_ops(plugin_root=None, run=None, which=None, cwd=None):
    """One line, in every state -- see `supertool_op_inventory`.

    `OK` here does not mean a call will succeed: it means every op name this
    plugin's own text spells is one the resolved supertool lists. It does not
    run any of them, does not check their arguments, and says nothing about the
    forge credentials the `gh-*` family needs.
    """
    state, detail = supertool_op_inventory(
        plugin_root=plugin_root, run=run, which=which, cwd=cwd
    )
    if state == "present":
        doctor.report(
            "OK",
            "supertool op inventory: {}. This compares names against the roster; "
            "it runs none of them.".format(detail),
        )
        return
    if state == "missing":
        doctor.report(
            "WARN",
            "supertool op inventory: {}. Either the installed supertool predates "
            "the op, or the preset carrying it is not listed under `presets` in "
            "this repo's .supertool.json -- `supertool 'ops'` names which presets "
            "are loaded here and which are not.".format(detail),
        )
        return
    doctor.report(
        "WARN",
        "supertool op inventory: whether the supertool that resolves here carries "
        "the ops this plugin names is unknown -- {}. Not answered as carried, "
        "which would clear a gap nobody measured.".format(detail),
    )
