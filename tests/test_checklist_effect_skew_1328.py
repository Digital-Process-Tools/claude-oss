"""#1328: checklist_skew.py's `installed_version` is what plugin_update.py's
resolved root reports -- but a spawned `Agent(subagent_type: "oss:release-auditor")`
loads its own system prompt through the harness's own plugin registration, a
SEPARATE mechanism that can resolve to an older cached copy. Nothing compared
the two, and they diverged three times in one release cycle (v0.29.0 gate 3:
`checklist_skew.py` said `installed_version=0.27.1`, but the auditor's own
report said "checklist in effect: .../0.26.0/agents/auditor.md version
0.26.0" -- two minors behind, not one).

The auditor already reports a `checklist in effect: <file> <version>` line in
every round (agents/release-auditor.md, "checklist in effect" section). This
pins the mechanism that makes that line mechanically comparable against what
`checklist_skew.py` itself measured, rather than left as free text nobody
reads back: `checklist_skew.compare_effect(installed_version, effect_line)`.

Every case that reports one state also reports a different one in the same
shape, one mutation away -- a positive control beside each negative one.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

EFFECT_MATCHES = "effect-matches"
EFFECT_DIFFERS = "effect-differs"
EFFECT_COULD_NOT_TELL = "effect-could-not-tell"


def _module():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import checklist_skew

    return checklist_skew


def test_module_exposes_the_three_effect_states():
    checklist_skew = _module()
    assert checklist_skew.EFFECT_MATCHES == EFFECT_MATCHES
    assert checklist_skew.EFFECT_DIFFERS == EFFECT_DIFFERS
    assert checklist_skew.EFFECT_COULD_NOT_TELL == EFFECT_COULD_NOT_TELL


def test_matching_versions_report_effect_matches():
    checklist_skew = _module()
    line = "checklist in effect: agents/auditor.md version 0.28.0"
    payload = checklist_skew.compare_effect("0.28.0", line)
    assert payload["state"] == EFFECT_MATCHES
    assert payload["installed_version"] == "0.28.0"
    assert payload["effect_version"] == "0.28.0"


def test_the_v0_29_0_gate_3_incident_reproduced():
    """The actual numbers from the #1295 trap.d fragment: checklist_skew.py
    measured 0.27.1 installed, but the auditor's own report said it loaded
    0.26.0 -- two minors behind what the gate itself reported, not one. This
    is exactly the class this mechanism exists to catch: a real skew between
    what the gate measured and what the spawn actually loaded, made loud
    rather than left to be reasoned through separately each time (#1328).
    """
    checklist_skew = _module()
    line = (
        "checklist in effect: .../dpt-plugins/oss/0.26.0/agents/auditor.md "
        "version 0.26.0"
    )
    payload = checklist_skew.compare_effect("0.27.1", line)
    assert payload["state"] == EFFECT_DIFFERS
    assert payload["installed_version"] == "0.27.1"
    assert payload["effect_version"] == "0.26.0"
    assert "0.27.1" in payload["reason"]
    assert "0.26.0" in payload["reason"]


def test_differing_versions_are_the_positive_control_beside_matches():
    checklist_skew = _module()
    line = "checklist in effect: agents/auditor.md version 0.27.0"
    payload = checklist_skew.compare_effect("0.28.0", line)
    assert payload["state"] == EFFECT_DIFFERS
    assert payload["state"] != EFFECT_MATCHES


def test_missing_effect_line_is_could_not_tell_not_a_silent_match():
    """A negative assertion ('the gate did not report a skew') must not pass
    merely because nothing was checked -- an absent line is could-not-tell,
    never effect-matches by default.
    """
    checklist_skew = _module()
    payload = checklist_skew.compare_effect("0.28.0", "")
    assert payload["state"] == EFFECT_COULD_NOT_TELL
    assert payload["state"] != EFFECT_MATCHES


def test_auditor_reported_own_could_not_tell_is_relayed_not_masked():
    checklist_skew = _module()
    line = "checklist in effect: could not tell -- no plugin manifest reached me"
    payload = checklist_skew.compare_effect("0.28.0", line)
    assert payload["state"] == EFFECT_COULD_NOT_TELL
    assert payload["effect_version"] is None


def test_unknown_installed_version_is_could_not_tell():
    """Positive control beside the two could-not-tell cases above: here the
    effect line parses fine and it is `installed_version` itself that is
    unknown (e.g. checklist_skew.compute() itself returned could-not-tell) --
    a different cause landing in the same third state, not silently dropped.
    """
    checklist_skew = _module()
    line = "checklist in effect: agents/auditor.md version 0.28.0"
    payload = checklist_skew.compare_effect(None, line)
    assert payload["state"] == EFFECT_COULD_NOT_TELL
    assert payload["effect_version"] == "0.28.0"


def test_unparseable_effect_line_is_could_not_tell():
    checklist_skew = _module()
    payload = checklist_skew.compare_effect("0.28.0", "checklist in effect: dunno")
    assert payload["state"] == EFFECT_COULD_NOT_TELL
    assert payload["effect_version"] is None


def test_cli_compare_effect_flag(tmp_path):
    import subprocess
    import json

    script = REPO_ROOT / "scripts" / "checklist_skew.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--compare-effect",
            "--installed-version",
            "0.27.1",
            "--effect-line",
            "checklist in effect: agents/auditor.md version 0.26.0",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["state"] == EFFECT_DIFFERS
