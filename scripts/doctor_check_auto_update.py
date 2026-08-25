"""``check_auto_update`` -- moved out of ``scripts/doctor.py`` (#497).

`doctor.py` keeps `main()`, the check registry and the shared contract (exit 0
always, one VERDICT line, `report()` / `unmeasured()`); this module holds one
check and nothing else. It borrows every shared name from `doctor` itself,
imported as a module (`import doctor`) rather than `from doctor import name`,
so a name looked up here is always the CURRENT value in `doctor`'s own
namespace rather than one frozen at import time -- the same reason every
moved check in this family does it this way, spelled out once in
`scripts/doctor_check_statusline.py` where a test actually depends on it.

`doctor.py` imports `check_auto_update` back out of this module immediately
after this docstring's own function is defined, so `doctor.check_auto_update`
keeps answering exactly as it did before the move -- a pure relocation, not a
rewrite; see #497.
"""

import shutil
import time

import doctor


def check_auto_update(project_dir, sh_available=None):
    """Did the SessionStart updater run, and what did it do (#480)?

    Five states, and the fifth is the one #492 added:

    * **off** -- switched off by the environment or by a config key. Reported at OK with
      the switch named, because a user who turned it off is not carrying a gap.
    * **opt-out status unknown** (#492) -- a config file exists but could not be read or
      parsed, so whether it declares an opt-out cannot be told. Reported at WARN, never
      folded into "off" (a guess that consent was withheld) or into "on" (a guess that it
      was not) -- `opt_out`'s own docstring is the source of that split.
    * **updated** -- with the versions it moved between, and the fact that this session
      is still running the old code until Claude Code restarts.
    * **current** / **could-not-check** -- the updater's own two answers, relayed. A run
      that could not reach the marketplace must never read as `current`, so the row does
      not collapse them.
    * **no receipt at all** -- the hook has not run in this install, or could not write.
      That is not "up to date": nothing has been established, and the row says so --
      UNLESS `sh` is not resolvable on PATH on this machine (#495): `hooks/hooks.json`
      runs the updater via `sh "$CLAUDE_PLUGIN_ROOT"/hooks/session-start-update.sh`,
      so on a machine with no POSIX-capable shell the hook can never have produced a
      receipt. That is not "nothing established yet before the next session" -- it is
      the state every session on that machine reports, and the row WARNs instead of
      reading it as the ordinary pre-first-run gap. Measured, not reasoned from a
      platform name: `shutil.which("sh")` is asked of THIS machine, so it answers
      correctly on a Windows machine that does have Git for Windows or WSL on PATH,
      not only on the population it was filed about.
    * **a receipt that exists and is broken** (#484) -- corrupt JSON, or a permission
      that changed underneath it. Told apart from "no receipt at all" by the exception
      `plugin_update.read_receipt` actually caught, never by asking the filesystem a
      second question; folding it into "no receipt" would report a broken receipt as
      the ordinary pre-first-run state.

    A `updated`/`current` receipt additionally carries `partial_failure` (#521): one
    scope succeeding is enough for either verdict to stand on its own terms (a
    deliberate decision this row does not second-guess), but a scope that was silently
    left behind must still reach the one surface a maintainer actually reads -- #521's
    own measured instance was `OK auto-update: oss already current` for a run where one
    of two scopes failed on a transient SSH error, with the failure named only in the
    receipt's `detail`, which this row never looked at. Both arms below WARN and quote
    `detail` when `partial_failure` is true, rather than rendering the same OK a clean
    run gets.
    """
    if doctor.plugin_update is None:
        doctor.unmeasured("auto-update", "scripts/plugin_update.py could not be imported")
        return
    status, where = doctor.plugin_update.opt_out(project_dir)
    receipt = doctor.plugin_update.read_receipt()
    if status == "off":
        doctor.report("OK", "auto-update: off -- {}".format(where))
        return
    if status == "unknown":
        doctor.report(
            "WARN",
            "auto-update: opt-out status unknown -- {} -- neither on nor off could be "
            "established, so nothing was touched until this is resolved.".format(where),
        )
        return
    if isinstance(receipt, doctor.plugin_update.ReceiptUnreadable):
        # A receipt that exists and is broken is not a receipt that was never written
        # (#484) -- the "ordinary state" arm below is only honest about absence, and
        # this is the exception in hand saying the opposite: something is there.
        doctor.report(
            "WARN",
            "auto-update: receipt at {} exists and could not be read ({}) -- this is "
            "not the ordinary before-the-next-session state; something was written "
            "and is now broken.".format(doctor.plugin_update.receipt_path(), receipt.detail),
        )
        return
    if not isinstance(receipt, dict):
        # #495: on a machine with no POSIX-capable shell resolvable, `hooks/hooks.json`'s
        # `sh "$CLAUDE_PLUGIN_ROOT"/hooks/session-start-update.sh` can never have run, so
        # "no receipt yet" is not the ordinary pre-first-run gap on that machine -- it is
        # the permanent state. Measured against THIS machine, not reasoned from a
        # platform name, so a Windows machine that does have Git for Windows or WSL on
        # PATH still reads the ordinary OK below.
        if sh_available is None:
            sh_available = shutil.which("sh") is not None
        if not sh_available:
            doctor.report(
                "WARN",
                "auto-update: no receipt at {} -- and `sh` is not resolvable on PATH on "
                "this machine. hooks/hooks.json runs the SessionStart updater via "
                'sh "$CLAUDE_PLUGIN_ROOT"/hooks/session-start-update.sh, so without a '
                "POSIX-capable shell the hook can never have produced a receipt here -- "
                "this is not the ordinary state before the next session starts, it is "
                "the state every session on this machine will report.".format(
                    doctor.plugin_update.receipt_path()
                ),
            )
            return
        # The ordinary state of a fresh install: the hook runs at the NEXT session
        # start, so every repo would carry this warning on the day it was set up. It
        # reports at OK and says in the text that nothing was established -- the same
        # shape `check_fragments_readme` uses for its absent arm, and for the same
        # reason: "not a finding" only if the wording does not read as a pass either.
        doctor.report(
            "OK",
            "auto-update: no receipt at {} -- the SessionStart hook has not run in this "
            "install yet, which is the ordinary state before the next session starts. "
            "Nothing here says the plugin is current; it says nothing was "
            "recorded.".format(doctor.plugin_update.receipt_path()),
        )
        return
    when = receipt.get("at")
    stamp = ""
    if isinstance(when, (int, float)):
        stamp = " ({:.0f} minute(s) ago)".format(max(0.0, (time.time() - when) / 60.0))
    state = receipt.get("state")
    partial = bool(receipt.get("partial_failure"))
    if state == "updated":
        message = (
            "auto-update: updated {} from {} to {}{} -- this session is still running "
            "the old copy. Run /reload-plugins to move the registry now (which agents, "
            "skills and commands resolve); a restart is still needed for command text "
            "already injected into this turn.".format(
                receipt.get("plugin"), receipt.get("from"), receipt.get("to"), stamp
            )
        )
        if partial:
            message += " But not every scope: {}".format(receipt.get("detail"))
        doctor.report("WARN", message)
        return
    if state == "current":
        if partial:
            doctor.report(
                "WARN",
                "auto-update: {} reports current{} -- but not every scope updated "
                "cleanly: {}".format(receipt.get("plugin"), stamp, receipt.get("detail")),
            )
            return
        doctor.report(
            "OK", "auto-update: {} already current{}".format(receipt.get("plugin"), stamp)
        )
        return
    doctor.report(
        "WARN",
        "auto-update: could not check{} -- {}. This is not a statement that the plugin "
        "is current.".format(stamp, receipt.get("detail")),
    )
