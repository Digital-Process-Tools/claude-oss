"""#367: doctor reports the interpreter architecture and what `-n auto` will ask for.

Two facts that were decisive in an incident and that nothing printed: the Python
running the suites was an x86_64 build under Rosetta 2 on an Apple M3 Pro (~3x on
interpreter startup, ~3.4x on the CPU cost of a subprocess spawn), and `pytest -n
auto` sized itself against all 11 logical cores while only 5 were performance
cores -- with four agents doing that independently.

**Every rendering assertion here runs against injected values.** The machine this
was written on is native arm64 with no Rosetta, so a test that measured the host
would have tested the hardware and asserted nothing about the case that matters.
The one case that cannot be injected -- whether the real probe can answer at all
-- is a separate, loudly-skipping test at the bottom.

The three-state rule is the subject rather than a side condition: an emulated
interpreter reports the *emulated* architecture, so `platform.machine()` alone
cannot tell native from translated. When the probe cannot answer, the line must
say so and must not read as `native`.
"""

import platform
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


def _levels(lines):
    return [level for level, _ in lines]


def _text(lines):
    return " | ".join(message for _, message in lines)


# --- the architecture line, all three states, injected ---


def test_translated_is_a_warn_naming_both_architectures():
    """The case this issue exists for, and the one that cannot be produced here."""
    lines = doctor.interpreter_architecture(
        machine="x86_64", system="Darwin", translation=("translated", "arm64", "")
    )
    assert _levels(lines) == ["WARN"], lines
    text = _text(lines)
    assert "x86_64" in text and "arm64" in text, text
    assert "translation" in text.lower(), text


def test_native_is_an_ok_line_that_says_native():
    """The must-not-fire half, and the positive control for the assertion below
    that an unprobed line never says `native`.
    """
    lines = doctor.interpreter_architecture(
        machine="arm64", system="Darwin", translation=("native", "arm64", "")
    )
    assert _levels(lines) == ["OK"], lines
    assert "native" in _text(lines), lines


def test_a_probe_that_could_not_look_is_a_warn_that_carries_its_reason():
    """A check that could not look must not render as a check that looked and
    found nothing -- so this is WARN, not OK, and it carries the reason.

    The fixture is `Darwin` + `unknown` because that is the only pairing the
    product can actually produce. It used to be `Linux` + `unknown`, written when
    the two gap states were one; after the split that composite is unreachable,
    and a test asserting against an input nothing can generate passes no matter
    what the code does with the real one.
    """
    lines = doctor.interpreter_architecture(
        machine="x86_64",
        system="Darwin",
        translation=("unknown", None, "sysctl.proc_translated could not be read (errno 1)"),
    )
    assert _levels(lines) == ["WARN"], lines
    text = _text(lines)
    assert "sysctl.proc_translated could not be read (errno 1)" in text, text


def test_neither_gap_state_ever_claims_native():
    """The negative half, over BOTH gap states rather than one.

    The split doubled this obligation: an interpreter whose translation state is
    unread must not be readable as a clean native one, and that has to hold for
    the WARN gap and the OK gap alike -- the OK one more so, since it spends no
    warning. Paired with `test_native_is_an_ok_line_that_says_native`, which fails
    if the word can never appear at all, so this is not vacuous.
    """
    for system, translation in (
        ("Darwin", ("unknown", None, "sysctl.proc_translated could not be read (errno 1)")),
        ("Linux", ("not-probed", None, "no translation probe is implemented for Linux")),
    ):
        lines = doctor.interpreter_architecture(
            machine="x86_64", system=system, translation=translation
        )
        assert "native" not in _text(lines).lower(), (system, lines)


def test_an_unreadable_host_probe_is_not_rendered_as_a_host_architecture():
    """A self-review finding. `hw.optional.arm64` returns nothing both when the
    machine genuinely is not arm64 and when the sysctl call failed, and folding
    the second into the first prints `host architecture x86_64` about a host
    nobody read -- this repository's own defect class, inside the check written
    to avoid it.
    """
    lines = doctor.interpreter_architecture(
        machine="arm64", system="Darwin", translation=("native", None, "")
    )
    text = _text(lines)
    assert "x86_64" not in text, text
    assert "could not be read" in text, text
    # Still OK, and still `native`: `sysctl.proc_translated` answered, and that
    # is a complete answer about THIS process whatever the host turns out to be.
    assert _levels(lines) == ["OK"], lines
    assert "natively" in text, text


def test_a_translated_line_with_an_unreadable_host_names_no_remedy_architecture():
    """The must-fire pair for the case above, on the arm that carries a remedy:
    "a native <host> python3" with no host read would name an architecture
    nobody measured, inside a sentence telling the reader what to install.
    """
    lines = doctor.interpreter_architecture(
        machine="x86_64", system="Darwin", translation=("translated", None, "")
    )
    text = _text(lines)
    assert _levels(lines) == ["WARN"], lines
    assert "could not be read" in text, text
    assert "native None" not in text and "native  python3" not in text, text
    assert "A native python3" in text, text


def test_a_known_host_still_names_the_remedy_architecture():
    """The must-not-fire control for the two above: the host, when it was read,
    must still reach the remedy. A fix that dropped it everywhere would pass both
    assertions above and lose the useful half.
    """
    lines = doctor.interpreter_architecture(
        machine="x86_64", system="Darwin", translation=("translated", "arm64", "")
    )
    assert "A native arm64 python3" in _text(lines), lines


# --- `no probe exists here` and `the probe did not answer` are two states ---
#
# They were one state (`unknown`, WARN) until CI answered. On every Linux and
# Windows leg that made `VERDICT: ok` unreachable forever, which does not add a
# finding -- it removes a signal, because a verdict that always reads `usable
# with gaps` can no longer carry a real WARN. That is this repository's own
# defect class pointed at the verdict line instead of at a check.


def test_a_platform_with_no_probe_at_all_is_ok_with_the_gap_named():
    """`not-probed`: nothing was attempted, because nothing here can attempt it.

    OK rather than WARN, following `agent_dispatch`'s shape in this same file --
    a sub-question that is unobservable in principle is named ON the line and
    does not spend the warning count. The gap is not softened: the line still
    says NOT probed and still never says `native`, which the pair below pins.
    """
    lines = doctor.interpreter_architecture(
        machine="x86_64",
        system="Linux",
        translation=("not-probed", None, "no translation probe is implemented for Linux"),
    )
    assert _levels(lines) == ["OK"], lines
    text = _text(lines)
    assert "NOT probed" in text, text
    assert "no translation probe is implemented for Linux" in text, text
    assert "native" not in text.lower(), text


def test_a_probe_that_ran_and_could_not_answer_is_still_a_warn():
    """The must-fire half, and the one that stops the change above from being a
    blanket downgrade. A platform that HAS a probe, whose probe ran and did not
    answer, is a gap with a cause worth chasing -- it stays a WARN and stays
    spending the warning count.
    """
    lines = doctor.interpreter_architecture(
        machine="arm64",
        system="Darwin",
        translation=("unknown", None, "sysctl.proc_translated could not be read (errno 1)"),
    )
    assert _levels(lines) == ["WARN"], lines
    text = _text(lines)
    assert "errno 1" in text, text
    assert "native" not in text.lower(), text


def test_off_darwin_the_state_is_not_probed_rather_than_unknown():
    lines_state = doctor.translation_state(system="Linux")
    assert lines_state[0] == "not-probed", lines_state
    assert lines_state[1] is None, lines_state
    assert "Linux" in lines_state[2], lines_state


def test_on_darwin_a_failing_sysctl_is_unknown_rather_than_not_probed(monkeypatch):
    """The must-fire pair for the test above: the WARN arm has to stay reachable
    on the platform that does have a probe, or the split has quietly deleted it.
    """
    monkeypatch.setattr(doctor, "_sysctl", lambda name: (None, 1))
    state, host, reason = doctor.translation_state(system="Darwin")
    assert state == "unknown", (state, host, reason)
    assert "errno 1" in reason, reason


def test_a_healthy_run_on_a_platform_with_no_probe_spends_no_warning(monkeypatch):
    """The CI failure itself, reproduced without a Linux runner.

    `tests/test_doctor_inprocess.py::test_verdict_says_ok_only_when_nothing_warned`
    asserts a fully healthy repo reaches `VERDICT: ok`. It went red on every
    ubuntu leg and green here, because this machine has a working
    sysctl.proc_translated and the WARN never fired locally.
    """
    monkeypatch.setattr(doctor.platform, "system", lambda: "Linux")
    doctor.FINDINGS.clear()
    try:
        doctor.check_interpreter_environment()
        levels = [level for level, _ in doctor.FINDINGS]
    finally:
        doctor.FINDINGS.clear()
    assert "WARN" not in levels, levels


def test_a_failing_probe_on_darwin_does_spend_a_warning(monkeypatch):
    """The must-fire control for the test above. If the check could never emit a
    WARN, the assertion above would pass against a check that had stopped
    reporting anything at all.
    """
    monkeypatch.setattr(doctor.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(doctor, "_sysctl", lambda name: (None, 1))
    doctor.FINDINGS.clear()
    try:
        doctor.check_interpreter_environment()
        levels = [level for level, _ in doctor.FINDINGS]
    finally:
        doctor.FINDINGS.clear()
    assert "WARN" in levels, levels


def test_every_architecture_line_survives_the_printable_ascii_fold():
    """#376's contract, applied to #367's new lines: these go through `report()`,
    so anything they compose must already be one printable ASCII line.
    """
    for system, translation in (
        ("Darwin", ("translated", "arm64", "")),
        ("Darwin", ("native", "arm64", "")),
        ("Darwin", ("translated", None, "")),
        ("Darwin", ("native", None, "")),
        ("Darwin", ("unknown", None, "sysctl.proc_translated could not be read (errno 1)")),
        ("Linux", ("not-probed", None, "no translation probe is implemented for Linux")),
    ):
        lines = doctor.interpreter_architecture(
            machine="x86_64", system=system, translation=translation
        )
        assert lines, (system, translation)
        for _, message in lines:
            assert doctor._one_line(message, limit=4000) == message, message


# --- what `-n auto` would ask for ---


def test_the_env_var_wins_and_is_named_as_the_source():
    """`pytest_xdist_auto_num_workers` reads PYTEST_XDIST_AUTO_NUM_WORKERS before
    it counts anything, so a doctor that reported the core count here would state
    a number the machine will not use.
    """
    count, source, note = doctor.xdist_auto_workers(
        env={"PYTEST_XDIST_AUTO_NUM_WORKERS": "4"}, physical=11, affinity=11, logical=11
    )
    assert count == 4, (count, source)
    assert "PYTEST_XDIST_AUTO_NUM_WORKERS" in source, source
    assert note == "", note


def test_an_unparseable_env_var_falls_through_and_says_so():
    """The must-fire pair for the test above. xdist warns and ignores a
    non-numeric value, so the count comes from the cores after all -- and a
    doctor that silently reported the core count would leave the reader thinking
    their cap was in effect.
    """
    count, source, note = doctor.xdist_auto_workers(
        env={"PYTEST_XDIST_AUTO_NUM_WORKERS": "half"}, physical=11, affinity=11, logical=11
    )
    assert count == 11, (count, source)
    assert "psutil" in source, source
    assert note, "an ignored cap was not reported"
    assert "half" in note, note


def test_an_empty_env_var_is_not_a_cap():
    """`if env_var:` in xdist -- an empty string is falsy and is not a zero-worker
    request. Adjacent to the case above and easy to get wrong in the other
    direction.
    """
    count, source, _ = doctor.xdist_auto_workers(
        env={"PYTEST_XDIST_AUTO_NUM_WORKERS": ""}, physical=11, affinity=11, logical=11
    )
    assert count == 11, (count, source)
    assert "PYTEST_XDIST_AUTO_NUM_WORKERS" not in source, source


def test_psutil_beats_affinity_and_cpu_count():
    """xdist prefers psutil, and for `-n auto` (not `-n logical`) it asks for
    PHYSICAL cores. On an SMT machine that is half the logical count, so a doctor
    reporting `os.cpu_count()` would double the number on exactly the machines
    where the mistake is expensive.
    """
    count, source, _ = doctor.xdist_auto_workers(
        env={}, physical=8, affinity=16, logical=16
    )
    assert count == 8, (count, source)
    assert "psutil" in source, source


def test_affinity_beats_cpu_count_when_psutil_is_absent():
    count, source, _ = doctor.xdist_auto_workers(
        env={}, physical=None, affinity=4, logical=16
    )
    assert count == 4, (count, source)
    assert "affinity" in source, source


def test_no_source_at_all_is_unknown_rather_than_zero():
    """The third state again. `os.cpu_count()` returns None on platforms that
    cannot answer, and a zero or a one invented here would be a confident wrong
    number rather than a gap.
    """
    count, source, _ = doctor.xdist_auto_workers(
        env={}, physical=None, affinity=None, logical=None
    )
    assert count is None, count
    assert source == "unknown", source


# --- the composed lines ---


def test_the_split_is_reported_when_the_platform_exposes_it():
    lines = doctor.worker_sizing(
        topology=(11, 5, 6, "split"),
        workers=(11, "psutil.cpu_count(logical=False)", ""),
        xdist_installed=True,
    )
    text = _text(lines)
    assert _levels(lines) == ["OK", "OK"], lines
    assert "11" in text and "5 performance" in text and "6 efficiency" in text, text
    assert "PYTEST_XDIST_AUTO_NUM_WORKERS" in text, text


def test_no_split_degrades_to_a_plain_count_with_the_absence_named():
    """#367 leaves this open: on a platform with no performance/efficiency split
    the second line degrades to a plain core count -- and says that the split is
    absent rather than silently omitting half the sentence, which would read the
    same as a machine whose split nobody looked for.
    """
    lines = doctor.worker_sizing(
        topology=(8, None, None, "none"),
        workers=(8, "os.cpu_count()", ""),
        xdist_installed=True,
    )
    text = _text(lines)
    assert _levels(lines) == ["OK", "OK"], lines
    assert "8 logical" in text, text
    assert "performance" in text and "no" in text.lower(), text
    assert "efficiency core" not in text.replace("efficiency core split", ""), text


def test_an_unknown_core_count_is_a_warn_on_both_lines():
    lines = doctor.worker_sizing(
        topology=(None, None, None, "unknown"),
        workers=(None, "unknown", ""),
        xdist_installed=True,
    )
    assert _levels(lines) == ["WARN", "WARN"], lines


def test_an_unreadable_split_is_a_warn_distinct_from_no_split():
    """A self-review finding. `hw.nperflevels` returning nothing means either "one
    performance level" or "the probe failed", and the first version printed the
    same sentence -- "this platform reports no performance/efficiency core split"
    -- for both. The count is then sizing against cores of two different speeds
    while claiming it is not.
    """
    lines = doctor.worker_sizing(
        topology=(11, None, None, "unknown"),
        workers=(11, "os.cpu_count()", ""),
        xdist_installed=True,
    )
    assert _levels(lines) == ["WARN", "OK"], lines
    text = _text(lines)
    assert "could NOT be determined" in text, text
    assert "reports no performance/efficiency core split" not in text, text


def test_the_no_split_line_still_says_there_is_no_split():
    """The must-not-fire control for the test above: a fix that made every
    splitless machine say "could not be determined" would pass it and lose the
    distinction in the other direction.
    """
    lines = doctor.worker_sizing(
        topology=(8, None, None, "none"),
        workers=(8, "os.cpu_count()", ""),
        xdist_installed=True,
    )
    text = _text(lines)
    assert "reports no performance/efficiency core split" in text, text
    assert "could NOT be determined" not in text, text


def test_xdist_absent_is_said_rather_than_assumed():
    """The number is still worth printing -- an agent may run the suite under an
    environment that has xdist even when this one does not -- but claiming
    `-n auto will request 11` on a machine with no xdist is a claim about a tool
    that is not there.
    """
    lines = doctor.worker_sizing(
        topology=(11, 5, 6, "split"),
        workers=(11, "os.cpu_count()", ""),
        xdist_installed=False,
    )
    text = _text(lines)
    assert "not installed" in text or "not importable" in text, text


def test_an_ignored_cap_reaches_the_line():
    lines = doctor.worker_sizing(
        topology=(11, 5, 6, "split"),
        workers=(11, "psutil.cpu_count(logical=False)", "PYTEST_XDIST_AUTO_NUM_WORKERS is set to 'half', which is not a number: xdist warns and ignores it"),
        xdist_installed=True,
    )
    assert "ignores it" in _text(lines), lines


def test_every_worker_line_survives_the_printable_ascii_fold():
    for topology, workers in (
        ((11, 5, 6, "split"), (11, "psutil.cpu_count(logical=False)", "")),
        ((8, None, None, "none"), (8, "os.cpu_count()", "")),
        ((11, None, None, "unknown"), (11, "os.cpu_count()", "")),
        ((None, None, None, "unknown"), (None, "unknown", "")),
    ):
        for _, message in doctor.worker_sizing(topology, workers, True):
            assert doctor._one_line(message, limit=4000) == message, message


# --- the real probes, which can only be asserted where they can run ---


def test_the_sysctl_probe_agrees_with_the_stdlib_on_darwin():
    """The only assertion available about the probe itself: `hw.logicalcpu` must
    match `os.cpu_count()`. If it does not, the ctypes call is reading the wrong
    buffer and every number above it is fiction.
    """
    if platform.system() != "Darwin":
        pytest.skip(
            "sysctl is a Darwin interface. UNTESTED here: whether _sysctl_int reads an "
            "integer sysctl correctly -- it is not called on {}, where the topology "
            "falls back to os.cpu_count().".format(platform.system())
        )
    import os

    assert doctor._sysctl_int("hw.logicalcpu") == os.cpu_count()


# These two were ONE test until the `unknown`/`not-probed` split, and its
# non-Darwin arm was doing second duty as a cheap "the function answers at all"
# check -- so after the split it asserted the retired state name and went red on
# every ubuntu leg. Two platforms, two genuinely different claims, so two tests.
# Neither is the other's skip arm, which is what let the stale assertion hide.


def test_translation_state_reaches_a_verdict_on_darwin():
    """On macOS the probe must reach a verdict, not shrug.

    `sysctl.proc_translated` returning ENOENT is itself the answer `native`
    (Apple's own documented reading), so there is no macOS on which `unknown` is
    the honest result of a working call -- and `not-probed` is flatly wrong here,
    because a probe does exist on this platform.
    """
    if platform.system() != "Darwin":
        pytest.skip(
            "UNTESTED here: the Darwin sysctl.proc_translated probe, which is the only "
            "translation probe that exists. This platform is {}, whose own claim is the "
            "test below.".format(platform.system())
        )
    state, host, reason = doctor.translation_state()
    assert state in ("native", "translated"), (state, host, reason)
    assert host, (state, host, reason)


def test_translation_state_reports_not_probed_on_a_platform_with_no_probe():
    """The live counterpart, and a real claim rather than a shape check.

    `test_off_darwin_the_state_is_not_probed_rather_than_unknown` already pins the
    branch with `system` injected. This one pins the DISPATCH: that the real
    `platform.system()` on this machine routes to the branch that matches it. The
    two are different failures -- the branch being wrong, and the branch being
    right but never reached.

    `not-probed` rather than `unknown` is the load-bearing half. `unknown` means a
    probe ran here and did not answer; claiming it on a platform where no probe
    exists reports a fault where there is only a gap, and it costs a WARN that no
    remedy clears -- which is the whole of the CI round that produced this split.
    """
    if platform.system() == "Darwin":
        pytest.skip(
            "UNTESTED here: the no-probe dispatch. This platform is Darwin, which has a "
            "probe, so it exercises the test above instead. What goes unchecked on a mac "
            "is whether a platform without a probe reports not-probed rather than "
            "unknown -- only a Linux or Windows run can establish that, and CI does."
        )
    state, host, reason = doctor.translation_state()
    assert state == "not-probed", (state, host, reason)
    assert host is None, (state, host, reason)
    assert platform.system() in reason, reason
    # Never the fault state, and never a clearance either: the two ways this line
    # could lie, pinned together.
    assert state != "unknown", (state, host, reason)
    assert state not in ("native", "translated"), (state, host, reason)


def test_cpu_topology_returns_its_four_slots_on_this_platform():
    """A weak assertion on purpose: the values are the machine's, so only the
    shape and the internal consistency can be checked anywhere.
    """
    logical, perf, eff, split = doctor.cpu_topology()
    assert split in ("split", "none", "unknown"), split
    assert (split == "split") == (perf is not None and eff is not None), (split, perf, eff)
    if logical is None:
        pytest.skip(
            "UNTESTED here: this platform reported no logical core count, so the "
            "consistency check below has nothing to check."
        )
    assert logical >= 1
    if perf is not None and eff is not None:
        assert perf + eff == logical, (logical, perf, eff)
