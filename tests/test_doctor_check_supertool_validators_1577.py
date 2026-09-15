"""#1577: `/oss:doctor` said nothing about supertool validators, in any state.

Half one of #633 shipped three default validators into a scaffolded
`.supertool.json` (#684); half two -- reporting whether the toolchain a
configured validator dispatches to actually resolves here -- never landed,
and #633 was closed anyway with that half still open. This module holds
`doctor_check_supertool_validators.py`'s own tests, following the sibling
per-check-module test convention (`tests/test_doctor_channel_connection_1361.py`):
a fake `run` builds the exact text `op_doctor` prints, never a real subprocess.

Every negative assertion here is paired with a positive control in the same
fixture, per this repository's own rule: an assertion that a WARN did not
fire must not also pass when no check ran at all.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_supertool_validators as m  # noqa: E402

VERSION = "0.61.0"


def setup_function(_):
    doctor.FINDINGS.clear()


def _levels():
    return [level for level, _ in doctor.FINDINGS]


def _text():
    return "\n".join(message for _, message in doctor.FINDINGS)


def _fake_run(stdout, returncode=0):
    return lambda *a, **k: type("C", (), {"returncode": returncode, "stdout": stdout})()


def _state(
    stdout, returncode=0, version=VERSION, monkeypatch=None, active_versions_map=None
):
    if monkeypatch is not None:
        resolved_map = (
            {"supertool": version}
            if active_versions_map is None
            else active_versions_map
        )
        monkeypatch.setattr(
            doctor, "active_versions", lambda names, record=None: resolved_map
        )
    return m.supertool_validator_probe_state(
        ".",
        run=_fake_run(stdout, returncode),
        which=lambda _name: "/usr/bin/supertool",
        timeout=5,
    )


ALL_RESOLVE = (
    "## Toolchain validators (#1950)\n"
    "- 2 configured, 2 resolves, 0 absent, 0 could not tell, 0 not applicable\n"
    "- jsonlint (.claude-plugin/marketplace.json): resolves — ok=True, count=0\n"
    "- ruff (scripts/x.py): resolves — ok=True, count=0\n"
)

ONE_ABSENT_ONE_UNKNOWN = (
    "## Toolchain validators (#1950)\n"
    "- 3 configured, 1 resolves, 1 absent, 1 could not tell, 0 not applicable\n"
    "- jsonlint (.claude-plugin/marketplace.json): resolves — ok=True, count=0\n"
    "- tomllint (pyproject.toml): absent — tomllint not found on PATH\n"
    "- bash-check (hooks/batch-hint.sh): could not tell — probe returned no verdict\n"
)

NO_VALIDATORS_SECTION = (
    '## Toolchain validators (#1950)\n- no "validators" section in .supertool.json\n'
)

UNKNOWN_OP = "ERROR: unknown operation: doctor\nValid operations: append, ...\n"


# ------------------------------------------------------------- the parser


def test_all_resolving_validators_read_as_reported_with_zero_offenders(monkeypatch):
    state, detail = _state(ALL_RESOLVE, monkeypatch=monkeypatch)
    assert state == "reported"
    assert detail["configured"] == 2
    assert detail["resolves"] == 2
    assert detail["absent"] == 0
    assert detail["could_not_tell"] == 0
    assert detail["offending"] == []


def test_an_absent_and_an_unknown_validator_are_both_named_verbatim(monkeypatch):
    """Positive control for the substring scan in `_offending_rows`: paired
    with the all-resolve case above, which must NOT produce any offending
    rows -- an assertion that offending rows appear here would also pass if
    the scan matched everything, so the all-resolve test is what rules that
    out.
    """
    state, detail = _state(ONE_ABSENT_ONE_UNKNOWN, monkeypatch=monkeypatch)
    assert state == "reported"
    assert detail["absent"] == 1
    assert detail["could_not_tell"] == 1
    assert len(detail["offending"]) == 2
    assert any("tomllint" in row and "absent" in row for row in detail["offending"])
    assert any(
        "bash-check" in row and "could not tell" in row for row in detail["offending"]
    )
    # The resolving row must never be swept in alongside the real offenders.
    assert not any("jsonlint" in row for row in detail["offending"])


def test_no_validators_section_is_its_own_state_not_a_parse_failure(monkeypatch):
    """`op_doctor` prints no summary line at all for an empty config -- if this
    fell through to the generic "could not parse" arm, an ordinary repo with
    no validators configured would WARN on every doctor run for a shape that
    is not a defect.
    """
    state, detail = _state(NO_VALIDATORS_SECTION, monkeypatch=monkeypatch)
    assert state == "no-validators"
    assert "validators" in detail


def test_unrecognised_doctor_op_is_op_unavailable_not_could_not_run(monkeypatch):
    """#1577's own open question: this plugin pins no minimum supertool
    version, so an older active install may not know the `doctor` op at all.
    That must render as its own state, not as an ordinary failed call --
    the remedy (update supertool) is different from "investigate why the
    call failed".
    """
    state, detail = _state(UNKNOWN_OP, returncode=1, monkeypatch=monkeypatch)
    assert state == "op-unavailable"
    assert "doctor" in detail


def test_a_genuine_unparseable_section_is_could_not_run(monkeypatch):
    garbled = "## Toolchain validators (#1950)\nsomething unexpected\n"
    state, detail = _state(garbled, monkeypatch=monkeypatch)
    assert state == "could-not-run"


def test_not_installed_is_read_before_anything_is_run(monkeypatch):
    state, detail = _state(ALL_RESOLVE, monkeypatch=monkeypatch, active_versions_map={})
    assert state == "not-installed"


def test_no_executable_on_path_is_could_not_run(monkeypatch):
    monkeypatch.setattr(
        doctor, "active_versions", lambda names, record=None: {"supertool": VERSION}
    )
    state, detail = m.supertool_validator_probe_state(
        ".", run=_fake_run(ALL_RESOLVE), which=lambda _name: None, timeout=5
    )
    assert state == "could-not-run"
    assert "PATH" in detail


# --------------------------------------------------------------- the fold


def test_all_resolve_reports_ok_and_names_the_count(monkeypatch):
    monkeypatch.setattr(
        m,
        "supertool_validator_probe_state",
        lambda *a, **k: (
            "reported",
            {
                "version": VERSION,
                "configured": 2,
                "resolves": 2,
                "absent": 0,
                "could_not_tell": 0,
                "not_applicable": 0,
                "offending": [],
            },
        ),
    )
    m.check_supertool_validators(".")
    assert _levels() == ["OK"]
    assert "2 configured" in _text()


def test_an_absent_validator_warns_and_names_it(monkeypatch):
    """Positive control for the OK test above: the same fold function, fed a
    real gap, must WARN rather than silently agreeing with the all-resolve
    case.
    """
    monkeypatch.setattr(
        m,
        "supertool_validator_probe_state",
        lambda *a, **k: (
            "reported",
            {
                "version": VERSION,
                "configured": 3,
                "resolves": 1,
                "absent": 1,
                "could_not_tell": 1,
                "not_applicable": 0,
                "offending": ["tomllint (pyproject.toml): absent — not found"],
            },
        ),
    )
    m.check_supertool_validators(".")
    assert _levels() == ["WARN"]
    assert "tomllint" in _text()


def test_zero_resolves_with_everything_not_applicable_does_not_claim_all_resolve(
    monkeypatch,
):
    """Self-review finding: every configured validator can be `not_applicable`
    at once (a repo tracking none of the file types any of them match) -- the
    resolving-count branch must not claim a resolution that never happened
    for zero validators.
    """
    monkeypatch.setattr(
        m,
        "supertool_validator_probe_state",
        lambda *a, **k: (
            "reported",
            {
                "version": VERSION,
                "configured": 3,
                "resolves": 0,
                "absent": 0,
                "could_not_tell": 0,
                "not_applicable": 3,
                "offending": [],
            },
        ),
    )
    m.check_supertool_validators(".")
    assert _levels() == ["OK"]
    assert "all resolve" not in _text()
    assert "none in scope" in _text()


def test_op_unavailable_warns_via_unmeasured_never_silently(monkeypatch):
    monkeypatch.setattr(
        m,
        "supertool_validator_probe_state",
        lambda *a, **k: (
            "op-unavailable",
            "supertool 0.10.0 does not recognise doctor",
        ),
    )
    m.check_supertool_validators(".")
    assert _levels() == ["WARN"]
    assert "supertool validators" in _text()


def test_not_installed_reports_nothing_here(monkeypatch):
    """Deferred to `check_dependency_diagnostics`, which already carries this
    gap under its own heading -- paired with the WARN tests above as the
    positive control that this check does fire when it has something to say.
    """
    monkeypatch.setattr(
        m,
        "supertool_validator_probe_state",
        lambda *a, **k: ("not-installed", "supertool is declared but not installed"),
    )
    m.check_supertool_validators(".")
    assert doctor.FINDINGS == []
