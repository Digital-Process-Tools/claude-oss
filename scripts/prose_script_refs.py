"""Does every ``scripts/<name>.py`` this plugin's own prose tells an agent to
run actually exist, and does every ``--flag`` it hands one accept that flag?
(#1070)

`agents/*.md`, `skills/manager/**` and `commands/*.md` are executed, not
read -- a session copies their command lines verbatim into a `Bash` call with
no way to check them first. `tests/test_unwired_scripts_253.py` already
guards the opposite direction, a script nothing references; nothing guarded
this one, so a rename or a dropped flag lands green and the first agent to
hit the stale call site pays for it mid-lane, at the worst possible moment.

**This exact mechanism already exists, one dependency over.**
`tests/test_shipped_op_spellings.py` and `scripts/doctor_check_supertool_ops.py`
both derive an expected set from shipped prose and compare it against
something real, for supertool op spellings (#197, #582). Neither looks at
**our own scripts**, which prose calls far more often than it calls a
supertool op. This module is the same shape aimed at that gap: derive both
sides, never carry a list. `real_scripts()` reads `scripts/` off disk;
`_document_text()` (via `doctor._rglob_md`) reads `agents/`, `skills/` and
`commands/` off disk -- the same `OP_TEXT_ROOTS` `doctor_check_supertool_ops`
already uses, imported rather than re-declared, because narrative text
outside those three roots (`CHANGELOG.md`, release notes) describes past
call shapes and is not something a session executes; that module's own
docstring records the whole-tree scan that was tried first and derived three
op names out of narrative prose.

## Two tiers, one deliberately left out

**Tier 1 -- existence.** Every `scripts/<name>.py` occurrence in the three
roots names a file that is actually on disk. Cheap and total.

**Tier 2 -- flags.** For each `scripts/<name>.py` occurrence that is inside a
documented command line -- a fenced code block or an inline backtick span,
never bare prose -- every `--flag`-shaped token in that same command line is
one the named script actually accepts.

**Tier 3 -- state-word vocabularies -- is explicitly out of scope,** per
#1070's own body: comparing `candidates`/`none-available`/`could-not-select`
and their kin between prose and script needs a locator for "this sentence is
enumerating that script's own states", and a heuristic that guesses wrong
there produces a red build on correct prose, which is worse than the gap it
closes. Not attempted here.

## Why "documented command line" means a backtick span, not a paragraph

A window measured in characters or blank lines was tried first, against this
plugin's own real corpus, and it produced a false positive within one run:
`skills/manager/phases/tick-order.md` mentions `scripts/select_issues.py`
(which "takes no flags; the payload is the whole input", per its own
docstring) and, several sentences later in the same paragraph, mentions
`` `--claim` `` -- a flag of a *different* script, `issue_claim.py`,
discussed two sentences on. A paragraph-wide window reads that as
`select_issues.py --claim` and fails a script that is correctly documented.

The corpus's own convention is the fix: every real invocation in this
repository's prose is written **inside its own backtick span** -- a fenced
```bash``` block, or a single-backtick inline span that MAY wrap across a
markdown source line (`` `python3 ".../scripts/preflight_check.py" --pattern\nPATTERN --path FILE_OR_DIR` ``
is one inline span split only by the file's own line wrap, not two
sentences). So the window is the span itself, never further out — a mention
that is not inside one is Tier 1 only, and contributes nothing to Tier 2.
Measured against this plugin's real corpus at the time this was written:
zero false positives once the window changed from "paragraph" to "backtick
span containing the mention".

A fenced block can carry more than one script's own command in sequence
(`skills/manager/phases/tick-order.md`'s `plugin_update.py` /
`doctor.py` / `oss_state.py` block is one), so a fenced block is split into
**logical lines** first -- physical lines joined across a trailing backslash
continuation (a line ending in a single ``\\``), the shell's own line-join -- and each logical line is
its own window, exactly like the inline-span case.

## Flags are derived from the script's own source, never hand-listed

Most scripts under `scripts/` build an `argparse.ArgumentParser` inside
`main()`; a few (`plugin_update.py`, `select_issues.py`, `fleet_label.py`)
parse `sys.argv` by hand and never construct one at all. Importing the module
and calling `main()` to read the built parser -- the literal reading of
"derived by importing the module" -- would run the script's own side
effects to get there, which a diagnostic must not do. `script_flags()`
instead parses the source with `ast` and collects every string literal
matching `--[a-z][a-z0-9-]*` anywhere in the file: that catches an
`add_argument("--repo", ...)` call and a bare `if arg == "--model":`
comparison identically, with no special-casing of which idiom a given script
happens to use. `--help`/`-h` are accepted for every script regardless: every
`ArgumentParser` in this tree is built with `add_help` left at its default,
so those two spellings are always valid and requiring every parser to
declare them by hand would be checking a fact argparse itself guarantees.

## Three states, not two (this repository's own subject)

`survey()` returns `(findings, roots)`. `roots` is one `(name, state,
detail)` per `OP_TEXT_ROOTS` entry -- `read` / `absent` / `unreadable` --
the same three states `doctor_check_supertool_ops.named_ops` reports and for
the identical reason: a root this process could not read is not a root with
nothing wrong in it, and `doctor._rglob_md` is used rather than
`Path.rglob` because the latter swallows `PermissionError` mid-walk and a
denied subtree renders as an empty one (#383). `script_flags()` itself
returns `(None, detail)` rather than an empty set when a script cannot be
read or fails to parse -- surfaced as a `could-not-derive-flags` finding
so a script that itself has a syntax error is never reported as passing
every flag check by default.

Python 3.9 compatible.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import doctor
from doctor_check_supertool_ops import OP_TEXT_ROOTS

#: A `scripts/<name>.py` mention anywhere in scanned text.
SCRIPT_MENTION_RE = re.compile(r"\bscripts/([A-Za-z0-9_]+\.py)\b")

#: A `--flag`-shaped token, for scanning inside a documented command line.
FLAG_TOKEN_RE = re.compile(r"--[a-z][a-z0-9-]*")

#: The same shape, anchored -- for testing a source string literal is
#: *exactly* a flag spelling, not merely contains one.
_FLAG_LITERAL_RE = re.compile(r"\A--[a-z][a-z0-9-]*\Z")

#: A fenced code block, language tag optional.
_FENCE_RE = re.compile(r"```[a-zA-Z0-9]*\n(.*?)```", re.DOTALL)

#: An inline backtick span. `[^`\n]*` twice joined by one optional embedded
#: newline is deliberate, not a general multi-line span: it is exactly wide
#: enough to catch a hard-wrapped single command (see the module docstring's
#: `preflight_check.py` example) without reaching across a blank line or a
#: whole paragraph, which is the failure mode this module was built to avoid.
_INLINE_RE = re.compile(r"`([^`\n]*(?:\n[^`\n]*)?)`")

#: Every `ArgumentParser` in this tree leaves `add_help` at its default, so
#: both spellings are always accepted -- see the module docstring.
_ALWAYS_ACCEPTED = frozenset({"--help", "-h"})


def real_scripts(scripts_dir):
    """Names (`foo.py`, not the full path) of every script actually on disk
    under `scripts_dir`. `None` if the directory could not be listed at all --
    distinct from an empty result, the same three-state shape as everywhere
    else in this module. `Path.glob` on a directory that is not there
    quietly yields nothing rather than raising, so that case is checked for
    explicitly rather than trusted to the `except` below.
    """
    directory = Path(scripts_dir)
    if not directory.is_dir():
        return None
    try:
        return frozenset(p.name for p in directory.glob("*.py"))
    except OSError:
        return None


def script_flags(path):
    """`(flags, error)` -- every `--flag`-shaped string literal in `path`'s
    own source, or `(None, detail)` when the file could not be read or does
    not parse as Python. See the module docstring for why this is a whole-file
    literal scan rather than an `ArgumentParser`-specific walk.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return None, "{0}: {1}".format(type(exc).__name__, exc)
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return None, "SyntaxError: {0}".format(exc)
    flags = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _FLAG_LITERAL_RE.match(node.value):
                flags.add(node.value)
    return flags, None


def _logical_lines(block):
    """Physical lines of `block`, joined across a trailing `\\` backslash
    continuation -- the shell's own line-join, so a wrapped `python3 ... \\`
    command reads as the single logical command line it is, per the module
    docstring.
    """
    out = []
    buf = ""
    for line in block.split("\n"):
        buf = line if not buf else buf + " " + line.strip()
        stripped = buf.rstrip()
        if stripped.endswith("\\"):
            buf = stripped[:-1]
            continue
        out.append(buf)
        buf = ""
    if buf:
        out.append(buf)
    return out


def _tier2_windows(text):
    """Yield one string per documented command line in `text`: each logical
    line of every fenced code block, then every inline backtick span that
    is not itself inside one of those blocks (so a span is never scanned
    twice).
    """
    fenced_spans = []
    for match in _FENCE_RE.finditer(text):
        fenced_spans.append((match.start(), match.end()))
        for logical in _logical_lines(match.group(1)):
            yield logical
    for match in _INLINE_RE.finditer(text):
        if any(start <= match.start() < end for start, end in fenced_spans):
            continue
        yield match.group(1)


def check_text(text, scripts_dir):
    """Findings for one document's `text` against the real scripts under
    `scripts_dir`. Each finding is a dict with `kind` (`missing-script` /
    `missing-flag` / `could-not-derive-flags`), `script`, and `flag` (`None`
    save for `missing-flag`) and `detail` (`None` save for
    `could-not-derive-flags`).

    Tier 1 runs over the whole text; Tier 2 only over `_tier2_windows(text)`,
    and only for a script Tier 1 already found on disk -- a missing script is
    reported once, by Tier 1, never twice.
    """
    findings = []
    for match in SCRIPT_MENTION_RE.finditer(text):
        name = match.group(1)
        if not (Path(scripts_dir) / name).is_file():
            findings.append(
                {"kind": "missing-script", "script": name, "flag": None, "detail": None}
            )
    for window in _tier2_windows(text):
        for match in SCRIPT_MENTION_RE.finditer(window):
            name = match.group(1)
            path = Path(scripts_dir) / name
            if not path.is_file():
                continue  # already reported by tier 1, above
            flags, error = script_flags(path)
            if flags is None:
                findings.append(
                    {
                        "kind": "could-not-derive-flags",
                        "script": name,
                        "flag": None,
                        "detail": error,
                    }
                )
                continue
            for flag_match in FLAG_TOKEN_RE.finditer(window[match.end() :]):
                flag = flag_match.group(0)
                if flag in flags or flag in _ALWAYS_ACCEPTED:
                    continue
                findings.append(
                    {
                        "kind": "missing-flag",
                        "script": name,
                        "flag": flag,
                        "detail": None,
                    }
                )
    return findings


def survey(plugin_root=None):
    """`(findings, roots)` over the whole plugin: every finding from
    `check_text`, each carrying a `path` (relative to `plugin_root`) alongside
    its `kind`/`script`/`flag`/`detail`; `roots` is one `(name, state,
    detail)` per `OP_TEXT_ROOTS` entry, `state` being `read` / `absent` /
    `unreadable` -- see the module docstring's "Three states" section.
    """
    root = doctor.PLUGIN_ROOT if plugin_root is None else Path(plugin_root)
    scripts_dir = root / "scripts"
    findings = []
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
                unreadable.append(doctor._one_line(str(exc)))
                continue
            try:
                display = path.relative_to(root).as_posix()
            except ValueError:  # pragma: no cover - path is built from root
                display = path.name
            for finding in check_text(text, scripts_dir):
                finding = dict(finding)
                finding["path"] = display
                findings.append(finding)
        if unreadable:
            roots.append((name, "unreadable", doctor._one_line("; ".join(unreadable))))
        else:
            roots.append((name, "read", "{0} file(s)".format(len(files))))
    return findings, roots
