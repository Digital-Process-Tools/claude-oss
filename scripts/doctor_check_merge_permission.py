"""``check_merge_permission`` -- moved out of ``scripts/doctor.py`` (#497).

`doctor.py` keeps `main()`, the check registry and the shared contract (exit 0
always, one VERDICT line, `report()` / `unmeasured()`); this module holds one
check, its own private helpers and constants, and nothing else. Every shared
name -- `report` -- is reached through `doctor` imported as a module
(`import doctor`), never `from doctor import name`, the same reason spelled
out in full in `scripts/doctor_check_statusline.py`: a name looked up this
way is always the current value in `doctor`'s own namespace, which is what
keeps a test's `monkeypatch.setattr(doctor, ...)` reaching code that used to
be inline in `doctor.py`.

`doctor.py` imports `check_merge_permission` back out of this module
immediately after this docstring's own code is defined, so
`doctor.check_merge_permission` keeps answering exactly as it did before the
move -- a pure relocation, not a rewrite; see #497. `MERGE_OP` moves with it:
`doctor.py` still needs the name after the move (it feeds
`PUBLISH_OP_PRESETS`, which stays in `doctor.py` beside `check_publish_confirm`
and `check_watch_channel` -- not self-contained enough to move in this lane),
and `doctor.py`'s own import of this module keeps that reference valid.
"""

import json
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


def merge_permission_state(project_dir, home=None):
    """Is there a settings rule naming the merge op? Four answers, not two.

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
            matches = [e for e in _permission_entries(data, key) if MERGE_OP in e]
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
