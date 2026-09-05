"""#400: an ABSENT `hw.nperflevels` is the answer "one performance level", not a
failed probe.

`c6b7acd` (#367) added `_sysctl(name) -> (value, errno)` and `_SYSCTL_ABSENT = 2`
precisely so those two could be told apart, and `translation_state()` uses both.
`cpu_topology()` reached for `_sysctl_int()` -- documented as being "for callers
that do not need to tell the two failure causes apart" -- and does need it, so an
absent sysctl became `unknown`, rendered as a WARN whose sentence ("the
hw.nperflevels probe did not answer") is false and which nothing can clear. A
verdict line permanently reading `usable with gaps` can no longer carry a real
warning, which is the argument `translation_state()`'s own docstring makes.

**Everything here runs against an injected `_sysctl`.** The machine this was
written on is arm64 Darwin, where `hw.nperflevels` answers `(2, 0)` -- measured,
not assumed -- so a test that read the host would assert nothing about the case
that matters. `system="Darwin"` is injected too, so every leg of the matrix
exercises the Darwin branch rather than skipping it.

The two halves are deliberately one fixture. Folding every failure into `"none"`
is the opposite bug and passes the absent-sysctl half on its own.
"""

import platform
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


def _inject(monkeypatch, answers):
    """Replace `_sysctl` with a table, and record what was asked.

    `_sysctl` is looked up as a module global at call time by every caller in
    `doctor.py`, so `setattr` on the module reaches them. That is the thing being
    relied on and it is the thing #174 says to measure rather than assume -- the
    caller returns `seen`, and every test below refuses to assert until
    `hw.nperflevels` appears in it.
    """
    seen = []

    def fake(name):
        seen.append(name)
        return answers[name]

    monkeypatch.setattr(doctor, "_sysctl", fake)
    return seen


def _require_injection(seen):
    if "hw.nperflevels" not in seen:
        pytest.skip(
            "UNTESTED here: the injection did not take -- doctor._sysctl was replaced "
            "on the module and cpu_topology never asked it for hw.nperflevels (asked "
            "for {!r}). Some callers capture a function at import rather than looking "
            "it up per call, and which of those pathlib and friends do varies by "
            "version, so this is measured rather than assumed. Interpreter {} on {}. "
            "What goes unchecked: whether an absent hw.nperflevels reports no split "
            "instead of a failed probe.".format(
                seen, platform.python_version(), platform.platform()
            )
        )


# `hw.logicalcpu` is injected in every case below so the count is the fixture's
# and not the runner's -- on a non-Darwin leg the real probe answers (None, None)
# and the assertions would be reading os.cpu_count().
_LOGICAL = {"hw.logicalcpu": (8, 0)}


def _answers(nperflevels):
    table = dict(_LOGICAL)
    table["hw.nperflevels"] = nperflevels
    return table


def test_an_absent_nperflevels_is_no_split_rather_than_a_failed_probe(monkeypatch):
    """errno 2 is `_SYSCTL_ABSENT`: the sysctl does not exist on this machine, so
    the machine has one performance level. That is the existing `"none"` arm, at OK.
    """
    seen = _inject(monkeypatch, _answers((None, doctor._SYSCTL_ABSENT)))
    logical, perf, eff, split = doctor.cpu_topology(system="Darwin")
    _require_injection(seen)

    assert split == "none", (split, seen)
    assert (logical, perf, eff) == (8, None, None), (logical, perf, eff)

    lines = doctor.worker_sizing(
        topology=(logical, perf, eff, split),
        workers=(8, "os.cpu_count()", ""),
        xdist_installed=True,
    )
    levels = [level for level, _ in lines]
    text = " | ".join(message for _, message in lines)
    assert levels == ["OK", "OK"], lines
    assert "reports no performance/efficiency core split" in text, text
    assert "did not answer" not in text, text


@pytest.mark.parametrize(
    "errno, why",
    [
        (None, "ctypes could not be used at all"),
        (1, "EPERM -- the call ran and was refused"),
        (22, "EINVAL -- the call ran and rejected the request"),
    ],
)
def test_a_genuinely_failed_nperflevels_probe_is_still_an_unknown_warn(
    monkeypatch, errno, why
):
    """The must-fire half, in the same fixture as the must-not-fire half above.

    A fix that folded every `_sysctl` failure into `"none"` would pass the test
    above and lose the distinction in the other direction -- which is the bug
    #363's self-review records committing. Only errno 2 means absent; anything
    else is a probe that ran and did not answer, and keeps its WARN.
    """
    seen = _inject(monkeypatch, _answers((None, errno)))
    logical, perf, eff, split = doctor.cpu_topology(system="Darwin")
    _require_injection(seen)

    assert split == "unknown", (split, errno, why)
    assert (logical, perf, eff) == (8, None, None), (logical, perf, eff)

    lines = doctor.worker_sizing(
        topology=(logical, perf, eff, split),
        workers=(8, "os.cpu_count()", ""),
        xdist_installed=True,
    )
    levels = [level for level, _ in lines]
    text = " | ".join(message for _, message in lines)
    assert levels == ["WARN", "OK"], lines
    assert "could NOT be determined" in text, text


def test_a_present_nperflevels_is_untouched_by_any_of_this(monkeypatch):
    """The third control: the arm that was never broken. `(2, 0)` is what this
    machine really answers, so the split must still be read out of the two
    perflevel sysctls rather than swallowed by either new branch.
    """
    table = _answers((2, 0))
    table["hw.perflevel0.logicalcpu"] = (5, 0)
    table["hw.perflevel1.logicalcpu"] = (3, 0)
    seen = _inject(monkeypatch, table)
    logical, perf, eff, split = doctor.cpu_topology(system="Darwin")
    _require_injection(seen)

    assert (logical, perf, eff, split) == (8, 5, 3, "split"), (
        logical,
        perf,
        eff,
        split,
    )


def test_one_performance_level_reported_as_a_number_is_still_no_split(monkeypatch):
    """`hw.nperflevels == 1` and the sysctl being absent must reach the same
    answer. They are the same fact stated two ways, and #400 is only about the
    second having taken a different path.
    """
    seen = _inject(monkeypatch, _answers((1, 0)))
    assert doctor.cpu_topology(system="Darwin")[3] == "none"
    _require_injection(seen)


def test_every_line_this_produces_survives_the_printable_ascii_fold():
    """doctor.py's contract, checked on the sentences this issue can reach."""
    for topology in ((8, None, None, "none"), (8, None, None, "unknown")):
        for _, message in doctor.worker_sizing(
            topology, (8, "os.cpu_count()", ""), True
        ):
            assert doctor._one_line(message, limit=4000) == message, message
