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


def test_unprobed_is_a_warn_that_names_what_went_unprobed():
    """The third state. A check that could not look must not render as a check
    that looked and found nothing -- so this is WARN, not OK, and it carries the
    reason it could not look.
    """
    lines = doctor.interpreter_architecture(
        machine="x86_64",
        system="Linux",
        translation=("unknown", None, "no translation probe is implemented for Linux"),
    )
    assert _levels(lines) == ["WARN"], lines
    text = _text(lines)
    assert "no translation probe is implemented for Linux" in text, text


def test_an_unprobed_line_never_claims_native():
    """The negative half of the pair above: `x86_64` with no probe result must not
    be readable as a clean native interpreter. Paired with
    `test_native_is_an_ok_line_that_says_native`, which fails if the word can
    never appear at all.
    """
    lines = doctor.interpreter_architecture(
        machine="x86_64",
        system="Linux",
        translation=("unknown", None, "no translation probe is implemented for Linux"),
    )
    assert "native" not in _text(lines).lower(), lines


def test_every_architecture_line_survives_the_printable_ascii_fold():
    """#376's contract, applied to #367's new lines: these go through `report()`,
    so anything they compose must already be one printable ASCII line.
    """
    for translation in (
        ("translated", "arm64", ""),
        ("native", "arm64", ""),
        ("unknown", None, "no translation probe is implemented for Linux"),
    ):
        lines = doctor.interpreter_architecture(
            machine="x86_64", system="Linux", translation=translation
        )
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
        topology=(11, 5, 6), workers=(11, "psutil.cpu_count(logical=False)", ""), xdist_installed=True
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
        topology=(8, None, None), workers=(8, "os.cpu_count()", ""), xdist_installed=True
    )
    text = _text(lines)
    assert _levels(lines) == ["OK", "OK"], lines
    assert "8 logical" in text, text
    assert "performance" in text and "no" in text.lower(), text
    assert "efficiency core" not in text.replace("efficiency core split", ""), text


def test_an_unknown_core_count_is_a_warn_on_both_lines():
    lines = doctor.worker_sizing(
        topology=(None, None, None), workers=(None, "unknown", ""), xdist_installed=True
    )
    assert _levels(lines) == ["WARN", "WARN"], lines


def test_xdist_absent_is_said_rather_than_assumed():
    """The number is still worth printing -- an agent may run the suite under an
    environment that has xdist even when this one does not -- but claiming
    `-n auto will request 11` on a machine with no xdist is a claim about a tool
    that is not there.
    """
    lines = doctor.worker_sizing(
        topology=(11, 5, 6), workers=(11, "os.cpu_count()", ""), xdist_installed=False
    )
    text = _text(lines)
    assert "not installed" in text or "not importable" in text, text


def test_an_ignored_cap_reaches_the_line():
    lines = doctor.worker_sizing(
        topology=(11, 5, 6),
        workers=(11, "psutil.cpu_count(logical=False)", "PYTEST_XDIST_AUTO_NUM_WORKERS is set to 'half', which is not a number: xdist warns and ignores it"),
        xdist_installed=True,
    )
    assert "ignores it" in _text(lines), lines


def test_every_worker_line_survives_the_printable_ascii_fold():
    for topology, workers in (
        ((11, 5, 6), (11, "psutil.cpu_count(logical=False)", "")),
        ((8, None, None), (8, "os.cpu_count()", "")),
        ((None, None, None), (None, "unknown", "")),
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


def test_translation_state_answers_on_darwin():
    """On macOS the probe must reach a verdict, not fall through to `unknown` --
    `sysctl.proc_translated` returning ENOENT is itself the answer `native`
    (Apple's own documented reading), so there is no macOS on which this is
    allowed to shrug.
    """
    state, host, reason = doctor.translation_state()
    if platform.system() != "Darwin":
        assert state == "unknown", (state, host, reason)
        assert reason, "the unknown state carried no reason"
        pytest.skip(
            "UNTESTED here: the Darwin sysctl.proc_translated probe. This platform is "
            "{}, where doctor reports the third state and names it.".format(
                platform.system()
            )
        )
    assert state in ("native", "translated"), (state, host, reason)
    assert host, (state, host, reason)


def test_cpu_topology_returns_three_slots_on_this_platform():
    """A weak assertion on purpose: the values are the machine's, so only the
    shape and the internal consistency can be checked anywhere.
    """
    logical, perf, eff = doctor.cpu_topology()
    if logical is None:
        pytest.skip(
            "UNTESTED here: this platform reported no logical core count, so the "
            "consistency check below has nothing to check."
        )
    assert logical >= 1
    if perf is not None and eff is not None:
        assert perf + eff == logical, (logical, perf, eff)
