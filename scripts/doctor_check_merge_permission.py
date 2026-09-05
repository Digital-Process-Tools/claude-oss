"""``check_merge_permission`` -- moved out of ``scripts/doctor.py`` (#497).
``check_supertool_permission`` -- added here, not moved, by #609.

`doctor.py` keeps `main()`, the check registry and the shared contract (exit 0
always, one VERDICT line, `report()` / `unmeasured()`); this module holds two
settings-permission checks, their shared scanning helper
(`_permission_rule_state`), their own private helpers and constants, and
nothing else. Every shared name -- `report` -- is reached through `doctor`
imported as a module (`import doctor`), never `from doctor import name`, the
same reason spelled out in full in `scripts/doctor_check_statusline.py`: a
name looked up this way is always the current value in `doctor`'s own
namespace, which is what keeps a test's `monkeypatch.setattr(doctor, ...)`
reaching code that used to be inline in `doctor.py`.

`doctor.py` imports `check_merge_permission` and `check_supertool_permission`
back out of this module immediately after this docstring's own code is
defined, so `doctor.check_merge_permission` keeps answering exactly as it did
before the move -- a pure relocation, not a rewrite; see #497 -- and
`doctor.check_supertool_permission` answers the sibling question #609 adds:
does any settings rule name the `supertool` call itself, the one thing every
agent here needs on its very first tool call rather than roughly once a
tick. `MERGE_OP` moves with it: `doctor.py` still needs the name after the
move (it feeds `PUBLISH_OP_PRESETS`, which stays in `doctor.py` beside
`check_publish_confirm` and `check_watch_channel` -- not self-contained
enough to move in this lane), and `doctor.py`'s own import of this module
keeps that reference valid.
"""

import json
import re
from pathlib import Path

import doctor

# The op the maintainer loop merges with. Matching is on the literal command
# string, so this substring is what an allow rule has to contain in some form --
# `Bash(./supertool 'gh-pr-merge:*')`, an absolute-path spelling of the same, or
# a per-call entry naming one exact merge.
MERGE_OP = "gh-pr-merge"
MERGE_RULE_FILE = ".claude/settings.local.json"


def settings_candidates(project_dir, home=None):
    """Where a permission rule can live. Project scope first, then user scope --
    a rule in either one is a rule, and reading only the project's would WARN at
    a maintainer who already arranged it in their home settings.
    """
    candidates = [
        Path(project_dir) / ".claude" / "settings.json",
        Path(project_dir) / ".claude" / "settings.local.json",
    ]
    if home is None:
        try:
            home = Path.home()
        except RuntimeError:
            # No HOME / USERPROFILE to resolve. User scope is then unreadable, but
            # this is a diagnostic: it exits 0 and reports, it does not traceback.
            return candidates
    return candidates + [
        Path(home) / ".claude" / "settings.json",
        Path(home) / ".claude" / "settings.local.json",
    ]


def _permission_entries(data, key):
    permissions = data.get("permissions")
    if not isinstance(permissions, dict):
        return []
    entries = permissions.get(key)
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, str)]


def _entry_count(count, key, path):
    """`2 allow entries in /path/to/settings.json` -- the count and the file, and
    nothing the file's author wrote."""
    return "{} {} {} in {}".format(
        count, key, "entry" if count == 1 else "entries", path
    )


def _permission_rule_state(project_dir, matches_entry, home=None):
    """Is there a settings rule matching ``matches_entry``? Four answers, not two.

    `present` / `denied` / `absent` / `unknown`, and the last one is the reason
    this is not a boolean. A settings file that could not be parsed produces no
    matching entry, which looks exactly like a file that was read and had none --
    and the two send a maintainer to opposite places.

    A rule that WAS read settles the question, so an unreadable neighbour does not
    drag a found rule back to `unknown`.

    The detail names how many entries matched and which file they are in, never
    the entry text. The text was never needed -- the question is "is there a rule,
    and where do I go to change it" -- and printing it handed a tracked,
    contributor-writable file the ability to write this script's own output
    lines. Counts and paths answer the question and carry nothing chosen by the
    tree being diagnosed except a path it already had to be told about.

    Shared by `merge_permission_state` (substring match on `MERGE_OP`) and
    `supertool_permission_state` (a spelling-anchored regex) -- #609. The only
    thing that varies between the two checks is which entries count, never how
    the settings files are read or how the four states are decided.
    """
    unreadable = []
    allowed = []
    denied = []
    for path in settings_candidates(project_dir, home=home):
        try:
            found_here = path.exists()
        except OSError:
            # #363: an unreadable candidate must land in the `unknown` bucket
            # this function already has, not be silently skipped as though
            # it were simply not there.
            unreadable.append(str(path))
            continue
        if not found_here:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            unreadable.append(str(path))
            continue
        if not isinstance(data, dict):
            unreadable.append(str(path))
            continue
        for key, found in (("allow", allowed), ("deny", denied)):
            matches = [e for e in _permission_entries(data, key) if matches_entry(e)]
            if matches:
                found.append(_entry_count(len(matches), key, path))
    # Every candidate is read before anything is decided, and deny wins. Returning
    # on the first allow would report `present` while holding, already parsed, a deny
    # rule for the same op -- an OK built on evidence the function had in hand and
    # dropped, which is worse than not looking.
    if denied:
        return "denied", "; ".join(denied)
    if allowed:
        return "present", "; ".join(allowed)
    if unreadable:
        return "unknown", "; ".join(unreadable)
    return "absent", ""


def merge_permission_state(project_dir, home=None):
    """Is there a settings rule naming the merge op? See `_permission_rule_state`
    for the four answers and why an unreadable neighbour never wins over a
    rule that was actually read."""
    return _permission_rule_state(project_dir, lambda e: MERGE_OP in e, home=home)


def check_merge_permission(project_dir, home=None):
    """Report the rule, and never more than the rule.

    This is a file read, not a probe of the harness. The harness decides at call
    time and an allowlist entry is one input to that decision -- so `present`
    cannot promise the merge will run, and `absent` cannot promise it will be
    denied. Both messages have to carry that limit, or the check becomes the
    defect it is here to prevent: an OK that reads as a guarantee nobody measured.
    """
    state, detail = merge_permission_state(project_dir, home=home)
    if state == "present":
        doctor.report(
            "OK",
            "a settings rule names {} ({}). This is a file read, not a probe of the "
            "harness: it says the rule exists, not that the merge call will be "
            "permitted.".format(MERGE_OP, detail),
        )
        return
    if state == "denied":
        doctor.report(
            "WARN",
            "the only settings rule naming {} is a deny rule ({}). The merge step will "
            "stop there.".format(MERGE_OP, detail),
        )
        return
    if state == "unknown":
        doctor.report(
            "WARN",
            "could not read {}, so whether a {} rule exists is unknown -- not answered "
            "as absent, because that would send you to add a rule you may already "
            "have.".format(detail, MERGE_OP),
        )
        return
    doctor.report(
        "WARN",
        "no settings rule names {}, so the merge step is the place you would find out. "
        "Add one to {} (machine scope, untracked) before the first tick. A rule is not "
        "the only thing that can allow or deny this call, so this is not a prediction "
        "that the merge will fail.".format(MERGE_OP, MERGE_RULE_FILE),
    )


# #609: every read this loop makes goes through supertool via Bash -- CLAUDE.md
# records that no agent here is granted Read, Grep or Glob -- so unlike
# MERGE_OP above (needed roughly once a tick), this permission is needed on
# the very first tool call of every session. A bare substring match on
# "supertool" is too promiscuous for that: this repository's own local
# settings carry entries such as
# `Bash(python3 -m pytest tests/test_supertool_entry_point_unreadable_341.py -q)`,
# which name a test file and grant nothing about invoking supertool itself.
# So this is anchored to the spellings that actually grant the call --
# `Bash(supertool:...)`, `Bash(./supertool:...)`, or an absolute-path form
# ending the same way -- at the start of the entry, right after `Bash(`.
#
# The absolute-path branch has to accept a Windows-native spelling too, not
# only a POSIX one -- a Windows contributor's own settings.local.json is
# written with backslashes and a drive letter (C:\Users\...\supertool:),
# never forward slashes (self-review finding, #609) -- and it has to survive
# a space inside the path, the ordinary shape of a Windows account-name home
# directory this repo's own CLAUDE.md already documents. `[/\\].*[/\\]`
# matches either separator on either side of an arbitrary (space-tolerant)
# middle, and `(?:[A-Za-z]:)?` accepts an optional leading drive letter.
SUPERTOOL_OP = "supertool"
SUPERTOOL_RULE_FILE = ".claude/settings.json"
SUPERTOOL_ENTRY_RE = re.compile(r"^Bash\((?:\./|(?:[A-Za-z]:)?[/\\].*[/\\])?supertool:")


def supertool_permission_state(project_dir, home=None):
    """Is there a settings rule naming the supertool call itself? See
    `_permission_rule_state` for the four answers and why an unreadable
    neighbour never wins over a rule that was actually read."""
    return _permission_rule_state(
        project_dir, lambda e: bool(SUPERTOOL_ENTRY_RE.match(e)), home=home
    )


def check_supertool_permission(project_dir, home=None):
    """Report the rule, and never more than the rule -- same caveat as
    `check_merge_permission`, carried over verbatim (#609): this is a file
    read, not a probe of the harness, and it must never claim more than the
    gh-pr-merge line above it does.
    """
    state, detail = supertool_permission_state(project_dir, home=home)
    if state == "present":
        doctor.report(
            "OK",
            "a settings rule names {} ({}). This is a file read, not a probe of the "
            "harness: it says the rule exists, not that the call will be "
            "permitted.".format(SUPERTOOL_OP, detail),
        )
        return
    if state == "denied":
        doctor.report(
            "WARN",
            "the only settings rule naming {} is a deny rule ({}). Every read this "
            "loop makes goes through supertool via Bash, so the very first tool call "
            "of a session will stop there.".format(SUPERTOOL_OP, detail),
        )
        return
    if state == "unknown":
        doctor.report(
            "WARN",
            "could not read {}, so whether a {} rule exists is unknown -- not answered "
            "as absent, because that would send you to add a rule you may already "
            "have.".format(detail, SUPERTOOL_OP),
        )
        return
    doctor.report(
        "WARN",
        "no settings rule names {}, so every read this loop makes -- every agent here "
        "is denied Read, Grep and Glob, and goes through supertool via Bash instead -- "
        "prompts until one is added. Add one to {} (tracked, portable) or "
        "{} (machine scope, untracked). A rule is not the only thing that can allow or "
        "deny this call, so this is not a prediction that a call will be "
        "denied.".format(SUPERTOOL_OP, SUPERTOOL_RULE_FILE, MERGE_RULE_FILE),
    )
