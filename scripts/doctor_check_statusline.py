"""``check_statusline`` -- moved out of ``scripts/doctor.py`` (#497).

`doctor.py` keeps `main()`, the check registry and the shared contract (exit 0
always, one VERDICT line, `report()` / `unmeasured()`); this module holds one
check, its own private helper and nothing else. Every shared name --
`report`, `unmeasured`, `NO_SCAFFOLD`, `scaffold`, `_safe_is_file` -- is
reached through `doctor` imported as a module (`import doctor`), never
`from doctor import name`, so a lookup happens at CALL time against
`doctor`'s own namespace rather than being frozen at import time.

That is not a style preference here: `tests/test_statusline_windows_gap_487.py`
does `monkeypatch.setattr(doctor, "_statusline_windows_gap", ...)` and expects
`doctor.check_statusline` to see the replacement. A `from doctor import
_statusline_windows_gap` at the top of this module would bind a private copy
of the name that the patch could never reach, so `check_statusline` below
calls it as `doctor._statusline_windows_gap(...)` even though the function is
defined a few lines above it, in this same file.

`doctor.py` imports `_POSIX_VAR_RE`, `_statusline_windows_gap` and
`check_statusline` back out of this module immediately after this docstring's
own code is defined, so `doctor.check_statusline` and friends keep answering
exactly as they did before the move -- a pure relocation, not a rewrite; see
#497.
"""

import json
import os
import re
from pathlib import Path

import doctor

#: POSIX shell variable expansion -- `$VAR` or `${VAR}`. cmd.exe, Windows's default
#: command interpreter, expands `%VAR%` instead and does not touch this syntax at all,
#: so a command written with it is a claim about a shell that may not be the one
#: running it (#487). This is the establishable half: the syntax is a fact about the
#: string. Which shell actually executes a `statusLine` command on Windows is not --
#: nobody has run one there to confirm -- so this flags the syntax gap without
#: asserting the command definitely fails.
_POSIX_VAR_RE = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?")


def _statusline_windows_gap(command, windows=None):
    """The POSIX-only syntax found in `command`, or `""` if none, on THIS platform.

    Only fires when `windows` is true, which defaults to `os.name == "nt"` -- the
    syntax is unremarkable and correct on every platform this plugin actually runs the
    command on, and a check that warned on POSIX too would be noise on every run there.
    `windows` is a parameter rather than read from `os.name` unconditionally so a test
    can drive both branches without monkeypatching `os.name` itself, which `pathlib`
    also reads and which breaks `Path()` construction the moment it is patched.
    """
    if windows is None:
        windows = os.name == "nt"
    if not windows or not command:
        return ""
    match = _POSIX_VAR_RE.search(command)
    return match.group(0) if match else ""


def check_statusline(project_dir):
    """Is the status line wired to something, and is it wired to ours (#479)?

    Four states, and the fourth is the reason this is a check rather than a scaffold
    fix. `.claude/settings.json` is not ours -- `scaffold.apply_settings` writes the
    `statusLine` key only when it is absent -- so a repo that already had one keeps it,
    and this reports rather than repairs.

    * the key names `<OWNED_DIR>/statusline.py` -- OK, it is ours and it is running.
    * the key names something else -- OK with the command quoted. Somebody chose that,
      and a diagnostic that WARNs about a working status line is noise on every run.
    * no `statusLine` key, or no settings file -- WARN, and the remedy is the block to
      paste, because `/oss:scaffold` writes it only when the file has no key at all and
      a reader whose file was declined needs the text rather than the command.
    * the file could not be read or parsed -- `unknown`. Whether a status line is wired
      here was not established, which is not the same as it having none, and the row
      must not read as either of the two answers above.

    A fifth thing this substring match used to miss (#487), folded into the first two
    states above rather than given a fifth of its own: `statusline.py` appearing in the
    command string is not the same claim as the command RUNNING here. The written
    command uses `$CLAUDE_PROJECT_DIR` (POSIX shell variable expansion) and a bare
    `python3`; on Windows, whose default command interpreter expands `%VAR%` rather than
    `$VAR`, that syntax does not resolve, so a repo can be graded `OK ... wired` about a
    status line that never runs. This is established from the syntax alone -- nobody has
    run a status line on Windows to confirm it (reasoned, not observed) -- so the WARN
    below names that gap rather than asserting the command definitely fails.

    This fires on a freshly-scaffolded repo's own default, which is real rather than a
    test artifact: `/oss:doctor` on Windows now warns about the exact command
    `/oss:scaffold` just wrote, with no other statusLine present to fall back to, and
    that WARN needs a remedy a reader can act on rather than only naming the gap --
    `statusLine` is left alone once a key is present (second bullet above), so replacing
    the written command with one of the reader's own choosing silences it. The remedy
    offered uses `%CLAUDE_PROJECT_DIR%` and a bare `python`: correct IF `cmd.exe` is what
    actually runs the string, reasoned from Claude Code exporting the variable as
    ordinary process environment rather than doing its own substitution -- untested, so
    it is offered as a thing to try and said so in the message, not asserted as fixed.
    """
    if doctor.scaffold is None:  # pragma: no cover - guarded the same way the callers are
        doctor.unmeasured("statusline", doctor.NO_SCAFFOLD)
        return
    settings = Path(project_dir) / ".claude" / "settings.json"
    block = json.dumps({"statusLine": dict(doctor.scaffold.STATUSLINE_SETTING)}, indent=2)
    if not doctor._safe_is_file(settings):
        doctor.report(
            "WARN",
            "statusline: {} has no statusLine -- the loop's board, next tick and "
            "plugin currency are not on screen. /oss:scaffold writes this key when the "
            "file has none: {}".format(settings, block),
        )
        return
    try:
        document = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        doctor.report(
            "WARN",
            "statusline: {} could not be read ({}), so whether a status line is wired "
            "here is unknown -- not absent.".format(settings, exc),
        )
        return
    if not isinstance(document, dict) or "statusLine" not in document:
        doctor.report(
            "WARN",
            "statusline: {} sets no statusLine. To wire ours: {}".format(settings, block),
        )
        return
    command = ""
    entry = document.get("statusLine")
    if isinstance(entry, dict):
        command = str(entry.get("command") or "")
    unresolved = doctor._statusline_windows_gap(command)
    if "statusline.py" in command:
        if unresolved:
            # A remedy, not just a name for the gap: `statusLine` is left alone once a
            # key is present (this function's own docstring, second bullet), so a reader
            # who wants this WARN gone can replace the `command` this plugin wrote with
            # one of their own. `%CLAUDE_PROJECT_DIR%` and a bare `python` are what
            # cmd.exe's own variable syntax and Windows's usual interpreter name would
            # be IF cmd.exe is what actually runs this string -- reasoned from Claude
            # Code exporting the variable as ordinary process environment, not observed
            # by running a status line on Windows, so it is offered as a thing to try
            # rather than asserted as the fix.
            windows_try = (
                'python "%CLAUDE_PROJECT_DIR%"/' + doctor.scaffold.OWNED_DIR + "/statusline.py"
            )
            doctor.report(
                "WARN",
                "statusline: wired to {} -- this is POSIX shell syntax ({}); Windows's "
                "default command interpreter does not expand it, so this is reasoned "
                "from the syntax, not observed, but the status line may not be running "
                "here. Untested, offered as a thing to try rather than a confirmed fix: "
                "{}".format(command, unresolved, windows_try),
            )
            return
        doctor.report("OK", "statusline: wired to {}".format(command))
        return
    if unresolved:
        doctor.report(
            "WARN",
            "statusline: wired to a status line that is not ours ({}) -- POSIX shell "
            "syntax ({}) that Windows's default command interpreter does not expand; "
            "reasoned from the syntax, not observed.".format(command, unresolved),
        )
        return
    doctor.report(
        "OK",
        "statusline: wired to a status line that is not ours ({}) -- a decision, left "
        "alone.".format(command or "no command"),
    )
