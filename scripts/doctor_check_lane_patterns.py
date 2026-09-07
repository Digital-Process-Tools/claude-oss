"""``check_lane_patterns`` -- its own module per the #497/#630 convention.

`doctor.py` keeps `main()`, the check registry and the shared contract (exit
0 always, one VERDICT line, `report()`/`unmeasured()`); this module holds one
check and its own private helpers. Every shared name -- `report`,
`unmeasured` -- is reached through `import doctor`, never `from doctor
import name`, the reason spelled out in full in `scripts/doctor_check_
statusline.py`: a name looked up this way is always the current value in
`doctor`'s own namespace, which is what keeps a test's
`monkeypatch.setattr(doctor, ...)` reaching this module too.

Wraps `scripts/lane_pattern_coverage.py`'s own three states (`ok` / `finding`
/ `not-configured`) in the doctor states the contract asks for
(`.claude/jit-context/paths/00-manual/doctor-check-contract.md`):

* `not-configured` is `NOTICE`, never `WARN` -- a repo that has never
  declared `labels.lane_patterns` cannot be checked at all, which is the
  structurally-unanswerable state NOTICE exists for (#764), reported on
  every run and never gating the VERDICT.
* `finding` is `WARN`, and every remedy below names an edit to `.oss.json`
  a session can make directly -- runnable, not only clickable, per the
  contract's own second test. Overlap is reported as a refactoring signal
  (per #1229's own maintainer ruling, restated in full in
  `lane_pattern_coverage.py`'s docstring) rather than as a dispatch-blocking
  claim -- the remedy text says so, so a reader does not treat clearing it
  as more urgent than it is.
* `ok` is `OK`.

`scripts/lane_pattern_coverage.py` is its own module rather than logic
inlined here, per the issue's own explicit requirement, so it stays
runnable by hand while editing `.oss.json` -- the exact moment somebody
wants the answer.
"""

import doctor
import lane_pattern_coverage


def _lane_patterns_from(config):
    labels = config.get("labels")
    if not isinstance(labels, dict):
        return None
    return labels.get("lane_patterns")


def check_lane_patterns(project_dir, config):
    if config is None:
        doctor.unmeasured("lane patterns")
        return
    lane_patterns = _lane_patterns_from(config)
    result = lane_pattern_coverage.lane_pattern_report(project_dir, lane_patterns)
    if result["state"] == "not-configured":
        doctor.report(
            "NOTICE",
            "lane patterns: labels.lane_patterns is not declared in .oss.json "
            "-- coverage and overlap cannot be checked. This is the ordinary "
            "state for a repo that has not adopted the lane-pattern "
            "convention, not a finding.",
        )
        return
    if result["state"] == "ok":
        doctor.report(
            "OK",
            "lane patterns: every declared pattern resolves, and no two "
            "lanes claim the same path.",
        )
        return
    parts = []
    for lane, pattern in result["dead_patterns"]:
        parts.append(
            "{0}'s pattern `{1}` matches no file on disk -- fix or remove it "
            "in .oss.json's labels.lane_patterns.{0}".format(lane, pattern)
        )
    for lane, pattern, detail in result["refused"]:
        parts.append(
            "{0}'s pattern `{1}` is malformed ({2}) -- fix it in .oss.json's "
            "labels.lane_patterns.{0}".format(lane, pattern, detail)
        )
    for path, lanes in result["overlaps"]:
        parts.append(
            "{} is claimed by both {} -- a refactoring signal, not a "
            "dispatch block (#1229): the file is doing more than one lane's "
            "job. Split it, or remove it from every lane's pattern in "
            ".oss.json but one.".format(path, " and ".join(lanes))
        )
    doctor.report("WARN", "lane patterns: " + " | ".join(parts))
