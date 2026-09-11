"""#1441: `commands/doctor.md` named `/oss:tick` as the next step
regardless of what the report above it said, even when an actionable
`WARN`'s own remedy said to run `/oss:scaffold` first.

#1065 deliberately split the responsibility: `scripts/doctor.py`'s
`report_with_remedy()` and `owned_drift_summary()` already build a
paste-ready, per-finding remedy beside every `WARN` they print, and the
overall NEXT STEP for the whole session belongs on the surface that
instructs it -- `commands/doctor.md` -- never inside a diagnostic that
also runs mid-tick and before a release with no standing to say what
happens after. This module is the derivation that lives on that surface:
given the report's own printed text, which next step does it point at.

## Why the match is `Run /oss:scaffold`, not any mention of `/oss:scaffold`

`doctor.py`'s remedy text is free prose, not a closed enum, and it
mentions `/oss:scaffold` for reasons that are NOT "this is the fix":

* the fragments-README gap (`doctor_check_fragments_readme.py`) explicitly
  warns `/oss:scaffold will NOT fix it` -- a bare substring match on
  `/oss:scaffold` would misread this WARN as pointing at the very command
  its own text refuses;
* CodeQL's `owned-only` WARN (`doctor_check_codeql_scan.py`) mentions
  `/oss:scaffold` only to explain which directory is owned, while its real
  remedy is a `languages:` config change that has nothing to do with
  scaffold;
* a drifted owned file's remedy (`doctor.py`'s `_drift_detail`) and the
  statusline gap's remedy (`doctor_check_statusline.py`) ARE genuinely
  scaffold-actionable, but neither opens with the imperative `Run
  /oss:scaffold` -- they are out of scope for THIS derivation and are
  read and acted on by hand, the same as any other WARN this file does
  not classify.

So this module keys on the literal, paste-ready sentence opening `Run
/oss:scaffold` -- the phrase `owned_drift_summary()` in `scripts/doctor.py`
prints verbatim for the two unambiguous, absent-owned-file cases, which
end that sentence two different ways depending on whether the changelog
gate behind the file could be read: `Run /oss:scaffold.` (a plain owned
file, or one whose gate is a clean "declines"/"absent") and `Run
/oss:scaffold, which reports what it could not read.` (the gate itself
could not be determined). An earlier version of this module matched only
the first, period-terminated form -- a real bug caught in self-review
(#1441): the second, comma-continued sentence is one of the two cases
this derivation's own docstring already claimed to cover, and it silently
fell through to `"tick"`. Matching the shared `Run /oss:scaffold` prefix
rather than either full sentence catches both without touching the three
non-actionable mentions above, none of which opens with that imperative.
It is deliberately narrow rather than deliberately complete: it never
fires on a WARN merely mentioning `/oss:scaffold` in passing, and it
never contradicts a WARN that says the command will not help.
"""

SCAFFOLD_REMEDY = "Run /oss:scaffold"


def next_step(report_text):
    """Derive the next step from a doctor report's own printed text.

    Returns ``(state, matched_lines)``:

    * ``"scaffold"`` -- at least one ``WARN `` line carries the literal,
      imperative remedy ``Run /oss:scaffold`` (however that sentence ends);
      ``matched_lines`` names every one.
    * ``"tick"`` -- no ``WARN`` line carries that remedy: the report is
      clean, or every ``WARN`` present is informational or not fixed by
      ``/oss:scaffold``; ``matched_lines`` is empty.
    * ``"could-not-determine"`` -- there was nothing to derive a next step
      from: `report_text` is not a string, is empty or blank, or the run
      itself never completed (``VERDICT: could not run``). Naming either
      `/oss:scaffold` or `/oss:tick` here would be a claim about a report
      that was never actually produced.
    """
    if not isinstance(report_text, str) or not report_text.strip():
        return "could-not-determine", []
    if "VERDICT: could not run" in report_text:
        return "could-not-determine", []
    matched = [
        line
        for line in report_text.splitlines()
        if line.startswith("WARN ") and SCAFFOLD_REMEDY in line
    ]
    if matched:
        return "scaffold", matched
    return "tick", []
