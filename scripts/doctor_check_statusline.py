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
import shutil
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


def _statusline_windows_gap(command, windows=None, sh_available=None):
    """The POSIX-only syntax found in `command`, or `""` if none, on THIS platform.

    Only fires when `windows` is true, which defaults to `os.name == "nt"` -- the
    syntax is unremarkable and correct on every platform this plugin actually runs the
    command on, and a check that warned on POSIX too would be noise on every run there.
    `windows` is a parameter rather than read from `os.name` unconditionally so a test
    can drive both branches without monkeypatching `os.name` itself, which `pathlib`
    also reads and which breaks `Path()` construction the moment it is patched.

    `os.name == "nt"` alone found this repository's own second instance of its own
    defect class (#495): a Windows user whose `statusLine` runs under Git Bash --
    where `$VAR` syntax works exactly as written -- was warned about a status line
    that runs correctly, contradicting this function's own principle that a
    diagnostic must not warn about a working status line. `os.name` cannot tell those
    two Windows machines apart; `sh_available` can, and is a real measurement rather
    than another inference: `shutil.which("sh")` asks THIS machine, right now,
    whether a POSIX-capable shell is even resolvable. It is not a proof that
    `statusLine` itself runs under it -- that remains reasoned, not observed, exactly
    as #487 already says -- but a machine with no `sh` on PATH at all is one where the
    POSIX-syntax gap is real, and a machine that does have one is exactly the "Git
    Bash on PATH" case this WARN must not fire on.
    """
    if windows is None:
        windows = os.name == "nt"
    if not windows or not command:
        return ""
    if sh_available is None:
        sh_available = shutil.which("sh") is not None
    if sh_available:
        return ""
    match = _POSIX_VAR_RE.search(command)
    return match.group(0) if match else ""


def _statusline_entry(path):
    """Read one settings file's own `statusLine` key, in isolation (#642).

    Three outcomes, and the third is the one #642 is about: this is called once for
    `.claude/settings.json` and once for `.claude/settings.local.json`, and neither call
    knows about the other -- combining them, including which one wins when both carry a
    key, is `check_statusline`'s job below, not this helper's.

    * absent -- `exists=False`. Ordinary; most repos have no `settings.local.json` at all.
    * present but unreadable/unparseable -- `unreadable=True`. Must never collapse into
      `has_key=False`, because that renders identically to "no key", and a reader would
      be told to add one that may already be there.
    * present and readable -- `has_key` and `command` say what it found, `has_key=False`
      meaning read fine, no `statusLine` key (a settings.local.json that exists for some
      other reason entirely, most commonly).
    """
    if not doctor._safe_is_file(path):
        return {"exists": False, "unreadable": False, "has_key": False, "command": ""}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"exists": True, "unreadable": True, "has_key": False, "command": ""}
    if not isinstance(document, dict) or "statusLine" not in document:
        return {"exists": True, "unreadable": False, "has_key": False, "command": ""}
    entry = document.get("statusLine")
    command = str(entry.get("command") or "") if isinstance(entry, dict) else ""
    return {"exists": True, "unreadable": False, "has_key": True, "command": command}


def check_statusline(project_dir):
    """Is the status line wired to something, and is it wired to ours (#479, #642)?

    Read twice, not once: `.claude/settings.json` (tracked) and
    `.claude/settings.local.json` (untracked, per-machine). #642 is the demonstration
    that reading only the tracked file makes "wired the local way" indistinguishable
    from "never wired at all" -- and for a repository like `claude-supertool`, which
    pins with its own tests that the `statusLine` key must NEVER appear in the tracked
    file, the local file is not a fallback, it is the only correct place, so doctor's
    old remedy (write the key into `settings.json`) reddens that repository's own CI if
    taken literally.

    The harness merges the two per-key -- `settings.local.json` overrides `settings.json`
    only for keys it actually carries, so a local file that exists for some unrelated
    reason (no `statusLine` key at all) does not shadow a tracked one. That merge is
    reproduced here rather than asserted about: `_effective` below is the local entry
    when the local file carries a `statusLine` key, else the tracked one.

    Four states now, and the fourth is still the reason this is a check rather than a
    scaffold fix -- `.claude/settings.json` is not ours; `scaffold.apply_settings` writes
    the key only when it is absent, so a repo that already had one keeps it:

    * the effective key names `<OWNED_DIR>/statusline.py` -- OK, naming which file
      answered. Wired in the tracked file is unchanged from before this fix; wired in
      `settings.local.json` alone is #642's own legitimate end state, not a lesser one --
      but the message says so explicitly, because contributors who clone this repo will
      not get it, and a reader deciding whether that is acceptable needs to know.
    * the effective key names something else -- OK with the command quoted, same file
      naming.
    * neither file carries the key (both absent, or present-and-readable-but-keyless) --
      the original WARN, unchanged in wording and remedy.
    * either file is PRESENT and unreadable/unparseable -- WARN, but `unknown`, never
      "sets no statusLine": that sentence sends the reader to add a key that may already
      be sitting in the file that failed to parse. This fires even when the other file
      parsed cleanly and even when it holds a valid key of its own, because which file's
      key would actually be effective cannot be established while the other is unread --
      reasoned conservatively rather than guessed.

    When both files carry the key and disagree, the message names the tracked file's own
    command too, because it is real text sitting in the repo that does not run, and a
    reader touching either file benefits from knowing the other one exists.

    A fifth thing this substring match used to miss (#487), folded into the "OK, ours" and
    "OK, not ours" branches rather than given a fifth of its own: `statusline.py`
    appearing in the command string is not the same claim as the command RUNNING here.
    The written command uses `$CLAUDE_PROJECT_DIR` (POSIX shell variable expansion) and a
    bare `python3`; on Windows, whose default command interpreter expands `%VAR%` rather
    than `$VAR`, that syntax does not resolve, so a repo can be graded `OK ... wired`
    about a status line that never runs. This is established from the syntax alone --
    nobody has run a status line on Windows to confirm it (reasoned, not observed) -- so
    the WARN below names that gap rather than asserting the command definitely fails.
    """
    if doctor.scaffold is None:  # pragma: no cover - guarded the same way the callers are
        doctor.unmeasured("statusline", doctor.NO_SCAFFOLD)
        return
    tracked_path = Path(project_dir) / ".claude" / "settings.json"
    local_path = Path(project_dir) / ".claude" / "settings.local.json"
    block = json.dumps({"statusLine": dict(doctor.scaffold.STATUSLINE_SETTING)}, indent=2)

    tracked = _statusline_entry(tracked_path)
    local = _statusline_entry(local_path)

    unreadable = [p for p, r in ((tracked_path, tracked), (local_path, local)) if r["unreadable"]]
    if unreadable:
        doctor.report(
            "WARN",
            "statusline: {} could not be read/parsed, so whether a status line is wired "
            "here is unknown -- not absent.".format(
                " and ".join(str(p) for p in unreadable)
            ),
        )
        return

    if local["has_key"]:
        source, command = local_path, local["command"]
    elif tracked["has_key"]:
        source, command = tracked_path, tracked["command"]
    else:
        source, command = None, None

    if source is None:
        doctor.report(
            "WARN",
            "statusline: neither {} nor {} sets a statusLine -- the loop's board, next "
            "tick and plugin currency are not on screen. /oss:scaffold writes this key "
            "into {} when the file has none: {}".format(
                tracked_path, local_path, tracked_path, block
            ),
        )
        return

    local_only_note = ""
    if source == local_path:
        local_only_note = (
            " -- wired in {} only (untracked; contributors who clone this repo will "
            "not get it)".format(local_path)
        )
    disagreement_note = ""
    if source == local_path and tracked["has_key"] and tracked["command"] != command:
        disagreement_note = (
            " ({} also sets a statusLine ({}), which does not run here because {} "
            "takes precedence)".format(tracked_path, tracked["command"], local_path)
        )

    unresolved = doctor._statusline_windows_gap(command)
    if "statusline.py" in command:
        if unresolved:
            # A remedy, not just a name for the gap: `statusLine` is left alone once a
            # key is present, so a reader who wants this WARN gone can replace the
            # `command` this plugin wrote with one of their own. `%CLAUDE_PROJECT_DIR%`
            # and a bare `python` are what cmd.exe's own variable syntax and Windows's
            # usual interpreter name would be IF cmd.exe is what actually runs this
            # string -- reasoned from Claude Code exporting the variable as ordinary
            # process environment, not observed by running a status line on Windows, so
            # it is offered as a thing to try rather than asserted as the fix.
            windows_try = (
                'python "%CLAUDE_PROJECT_DIR%"/' + doctor.scaffold.OWNED_DIR + "/statusline.py"
            )
            doctor.report(
                "WARN",
                "statusline: wired to {}{}{} -- this is POSIX shell syntax ({}); "
                "Windows's default command interpreter does not expand it, so this is "
                "reasoned from the syntax, not observed, but the status line may not be "
                "running here. Untested, offered as a thing to try rather than a "
                "confirmed fix: {}".format(
                    command, local_only_note, disagreement_note, unresolved, windows_try
                ),
            )
            return
        doctor.report(
            "OK",
            "statusline: wired to {}{}{}".format(command, local_only_note, disagreement_note),
        )
        return
    if unresolved:
        doctor.report(
            "WARN",
            "statusline: wired to a status line that is not ours ({}){}{} -- POSIX "
            "shell syntax ({}) that Windows's default command interpreter does not "
            "expand; reasoned from the syntax, not observed.".format(
                command, local_only_note, disagreement_note, unresolved
            ),
        )
        return
    doctor.report(
        "OK",
        "statusline: wired to a status line that is not ours ({}){}{} -- a decision, "
        "left alone.".format(command or "no command", local_only_note, disagreement_note),
    )
