"""``check_script_call_survey`` -- one check, in its own module per the
#497/#630 convention.

A fact about the PLUGIN, not about the project being diagnosed -- same shape
as `check_agent_dispatch` a few lines away in `doctor.py`, needing no config
and no `project_dir`. Reported, never blocking: a script only prose names may
be a deliberate human-run tool, and this check lists, it does not judge
(#1416).
"""

import doctor
from script_call_survey import survey


def check_script_call_survey(plugin_root=None):
    """#1416: for every `scripts/<name>.py`, does anything under `commands/`,
    `agents/`, `skills/`, `bin/` or another script actually RUN it, or only
    describe it in prose? A `NOTICE`, never a `WARN`/`FAIL` -- this is the
    forcing function that makes the class visible, not a gate: the four
    things this issue was filed over (triage-after-release, the curation
    threshold-route, the cohort-freeze marker, the manager-in-the-picker key
    mismatch) were each individually correct and simply never called.
    """
    rows, roots, notes = survey(plugin_root)
    unreadable_roots = [
        "{}: {}".format(name, detail)
        for name, state, detail in roots
        if state == "unreadable"
    ]
    if unreadable_roots:
        doctor.report(
            "WARN",
            "script call survey: could not be checked -- {} -- so which "
            "scripts are called cannot be established for the whole "
            "corpus.".format("; ".join(unreadable_roots)),
        )
        return
    if not rows:
        doctor.report("WARN", "script call survey: scripts/ could not be listed at all")
        return
    called = [name for name, state, _detail in rows if state == "called"]
    mentioned = [name for name, state, _detail in rows if state == "mentioned-only"]
    unreadable_scripts = [
        name for name, state, _detail in rows if state == "could-not-tell"
    ]
    message = (
        "script call survey: {} script(s) called, {} mentioned-only, {} "
        "could-not-tell (of {} total).".format(
            len(called), len(mentioned), len(unreadable_scripts), len(rows)
        )
    )
    if mentioned:
        message += " Mentioned-only: {}.".format(", ".join(sorted(mentioned)))
    if unreadable_scripts:
        message += " Could-not-tell: {}.".format(", ".join(sorted(unreadable_scripts)))
    for note in notes:
        message += " " + note
    doctor.report("NOTICE", message)
