"""``check_script_call_survey`` -- one check, in its own module per the
#497/#630 convention.

A fact about the PLUGIN, not about the project being diagnosed -- same shape
as `check_agent_dispatch` a few lines away in `doctor.py`, needing no config
and no `project_dir`. Reported, never blocking: a script only prose names may
be a deliberate human-run tool, and this check lists, it does not judge
(#1416).
"""

import doctor


def check_script_call_survey(plugin_root=None):
    """#1416: for every `scripts/<name>.py`, does anything under `commands/`,
    `agents/`, `skills/`, `bin/` or another script actually RUN it, or only
    describe it in prose? A `NOTICE`, never a `WARN`/`FAIL` -- this is the
    forcing function that makes the class visible, not a gate: the four
    things this issue was filed over (triage-after-release, the curation
    threshold-route, the cohort-freeze marker, the manager-in-the-picker key
    mismatch) were each individually correct and simply never called.

    `survey` is imported here, inside the function, rather than at module
    scope: `doctor.py` imports THIS module (the #497/#630 convention every
    check module follows), and `script_call_survey` itself imports `doctor`
    (via `prose_script_refs`) -- a module-scope `from script_call_survey
    import survey` here closes that into a circular import that crashes
    only when `script_call_survey` happens to be imported before `doctor`
    has finished its own top-level execution (an order-dependent failure a
    test importing `script_call_survey` directly, rather than via `doctor`,
    hits every time). Same convention `doctor_check_mcp_channel_
    registration._drop_dead_plugin_consumers` already documents for the
    identical shape.
    """
    from script_call_survey import survey

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
        # Reached only when every root above read cleanly (the branch just
        # above already returned on any `unreadable` root) and `scripts/`
        # itself was successfully listed with zero `.py` files in it -- a
        # real, empty-but-readable directory, never a read failure. Worded
        # to say that plainly rather than reusing "could not be listed",
        # which would misreport a genuinely empty scripts/ as unreadable
        # (self-review finding).
        doctor.report(
            "NOTICE", "script call survey: scripts/ is empty -- no scripts to survey"
        )
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
