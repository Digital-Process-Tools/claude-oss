"""#386: `gh` can be an x86_64 build running under Rosetta 2 from a stale Intel
Homebrew prefix while everything else on the machine is native arm64 -- the split
#367's interpreter probe was never asked to look at, because #367 answers the
question for the Python interpreter and `gh` is a binary it spawns, not the
interpreter running it.

Two lines, both pure given their inputs so every branch is assertable without
shelling out or owning a Rosetta machine: which architecture(s) `gh` resolved to
against the host's own, and `gh`'s own version beside the pointer to the
documented `gh-pr-edit` workaround (skills/manager/SKILL.md, cli/cli#13069) that
is bounded by a `gh` version and has nothing today comparing against it.

Three states throughout, and the third is the point: `gh` not on PATH is nothing
to check (OK, no invented finding); a platform or a probe that could not answer
is a WARN carrying why, never a silent `native`-shaped line; and a real mismatch
is the WARN this issue exists for.

`archs` is a TUPLE, never a single string -- this repository's own review round
caught the first version treating a universal/fat Mach-O's first-listed slice as
THE architecture, which would call a binary carrying a native `arm64` slice
"an x86_64 build ... every call runs under binary translation" whenever `file`
happened to list x86_64 first. `test_a_fat_binary_carrying_the_host_arch_is_a_match`
is that fixture, reproduced from this machine's own `/usr/bin/file`.
"""

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


# --- gh_binary_findings: the rendering, all injected ---


def test_gh_not_on_path_is_ok_with_nothing_invented():
    lines = doctor.gh_binary_findings("Darwin", None, None)
    assert _levels(lines) == ["OK"], lines
    assert "not on PATH" in _text(lines), lines


def test_off_darwin_architecture_is_not_probed_but_version_still_reports():
    """The must-not-fire half: a platform this check does not probe must not
    manufacture a WARN, and must not suppress the version line either.
    """
    lines = doctor.gh_binary_findings(
        "Linux", "/usr/bin/gh", "gh version 2.60.0 (2024-08-01)"
    )
    assert _levels(lines) == ["OK", "OK"], lines
    text = _text(lines)
    assert "not probed" in text, text
    assert "2.60.0" in text, text


def test_a_mismatched_architecture_is_the_warn_this_issue_exists_for():
    lines = doctor.gh_binary_findings(
        "Darwin",
        "/usr/local/bin/gh",
        "gh version 2.50.0 (2024-06-01)",
        host="arm64",
        archs=("x86_64",),
    )
    levels = _levels(lines)
    assert levels[0] == "WARN", lines
    text = _text(lines)
    assert "x86_64" in text and "arm64" in text, text
    assert "/usr/local/bin/gh" in text, text
    assert "translation" in text.lower(), text


def test_a_matching_architecture_is_ok_and_names_the_host():
    lines = doctor.gh_binary_findings(
        "Darwin",
        "/opt/homebrew/bin/gh",
        "gh version 2.60.0 (2024-08-01)",
        host="arm64",
        archs=("arm64",),
    )
    assert _levels(lines)[0] == "OK", lines
    assert "arm64" in _text(lines), lines


def test_a_fat_binary_carrying_the_host_arch_is_a_match():
    """The self-review finding: `file` on a universal Mach-O lists more than one
    slice (this machine's own `/usr/bin/file`: "Mach-O universal binary with 3
    architectures: [x86_64:...] [arm64:...] [arm64e:...]"). x86_64 listed FIRST
    must not read as a mismatch when the host's own arm64 slice is also there --
    the OS runs the native slice, not necessarily the first one `file` names.
    """
    lines = doctor.gh_binary_findings(
        "Darwin",
        "/usr/bin/file",
        "gh version 2.60.0 (2024-08-01)",
        host="arm64",
        archs=("x86_64", "arm64", "arm64"),
    )
    assert _levels(lines)[0] == "OK", lines
    text = _text(lines)
    assert "matches this host" in text, text
    assert "universal" in text.lower(), text


def test_a_fat_binary_missing_the_host_arch_is_still_a_mismatch():
    """The must-fire pair for the test above: a universal binary that does NOT
    carry the host's own slice is a real mismatch, several architectures or not.
    """
    lines = doctor.gh_binary_findings(
        "Darwin",
        "/usr/local/bin/gh",
        "gh version 2.50.0 (2024-06-01)",
        host="arm64",
        archs=("x86_64", "i386"),
    )
    assert _levels(lines)[0] == "WARN", lines
    assert "translation" in _text(lines).lower(), lines


def test_an_unreadable_host_is_a_warn_naming_the_gap_not_a_false_match():
    """`host is None` must never render as a silent OK-shaped match -- the same
    defect class `interpreter_architecture` was written to avoid, one layer over.
    """
    lines = doctor.gh_binary_findings(
        "Darwin", "/usr/local/bin/gh", "gh version 2.50.0 (2024-06-01)", host=None
    )
    assert lines[0][0] == "WARN", lines
    assert "unknown" in _text(lines).lower(), lines


def test_an_unreadable_architecture_probe_is_a_warn_carrying_the_reason():
    lines = doctor.gh_binary_findings(
        "Darwin",
        "/usr/local/bin/gh",
        "gh version 2.50.0 (2024-06-01)",
        host="arm64",
        archs=None,
        arch_reason="the `file` command is not on PATH here",
    )
    assert lines[0][0] == "WARN", lines
    assert "the `file` command is not on PATH here" in _text(lines), lines


def test_neither_gap_state_ever_claims_a_match():
    """The negative control paired with the two match tests above: a mismatch
    finding must not appear for either gap state, and a match finding must not
    either -- both would be a confident claim about an architecture nobody read.
    """
    for host, archs, reason in (
        (None, None, "not probed"),
        ("arm64", None, "the `file` command is not on PATH here"),
    ):
        lines = doctor.gh_binary_findings(
            "Darwin",
            "/usr/local/bin/gh",
            "gh version 2.50.0 (2024-06-01)",
            host=host,
            archs=archs,
            arch_reason=reason,
        )
        text = _text(lines).lower()
        assert "matches this host" not in text, (host, archs, lines)
        assert "every gh call runs under binary translation" not in text, (
            host,
            archs,
            lines,
        )


def test_an_unreadable_version_is_a_warn_rather_than_a_silent_omission():
    lines = doctor.gh_binary_findings(
        "Darwin", "/usr/local/bin/gh", None, host="arm64", archs=("arm64",)
    )
    assert lines[-1][0] == "WARN", lines
    assert "could not be read" in _text(lines), lines


def test_a_known_version_points_at_the_documented_workaround():
    lines = doctor.gh_binary_findings(
        "Darwin",
        "/usr/local/bin/gh",
        "gh version 2.50.0 (2024-06-01)",
        host="arm64",
        archs=("arm64",),
    )
    text = _text(lines)
    assert "2.50.0" in text, text
    assert "cli/cli#13069" in text, text
    assert "gh-pr-edit" in text, text


# --- tool_binary_architecture: the `file`-based probe, injected ---


class _FakeCompleted:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def test_tool_binary_architecture_reads_an_x86_64_mach_o():
    def fake_run(cmd, **kwargs):
        return _FakeCompleted(b"/usr/local/bin/gh: Mach-O 64-bit executable x86_64\n")

    def fake_which(name):
        return "/usr/bin/file" if name == "file" else None

    archs, reason = doctor.tool_binary_architecture(
        "/usr/local/bin/gh", run=fake_run, which=fake_which
    )
    assert archs == ("x86_64",), (archs, reason)
    assert reason is None, (archs, reason)


def test_tool_binary_architecture_normalises_aarch64():
    def fake_run(cmd, **kwargs):
        return _FakeCompleted(b"/opt/homebrew/bin/gh: Mach-O 64-bit executable arm64\n")

    def fake_which(name):
        return "/usr/bin/file" if name == "file" else None

    archs, reason = doctor.tool_binary_architecture(
        "/opt/homebrew/bin/gh", run=fake_run, which=fake_which
    )
    assert archs == ("arm64",), (archs, reason)


def test_tool_binary_architecture_reads_every_slice_of_a_universal_binary():
    """Reproduced from this machine's own `/usr/bin/file` -- `file` on itself:
    "Mach-O universal binary with 3 architectures: [x86_64:...] [arm64:...]
    [arm64e:...]". Every slice must come back, in the order `file` named them,
    with `arm64e` folded into `arm64` (it is not one of the four tokens this
    probe recognises, so a real run of this fixture would only find two -- the
    dedup here is exercised with an explicit duplicate `arm64` token instead so
    the ordering and dedup logic is tested without depending on that fold).
    """

    def fake_run(cmd, **kwargs):
        return _FakeCompleted(
            b"/usr/bin/file: Mach-O universal binary with 3 architectures: "
            b"[x86_64:Mach-O 64-bit executable x86_64] "
            b"[arm64:Mach-O 64-bit executable arm64] "
            b"[arm64:Mach-O 64-bit executable arm64]\n"
        )

    def fake_which(name):
        return "/usr/bin/file" if name == "file" else None

    archs, reason = doctor.tool_binary_architecture(
        "/usr/bin/file", run=fake_run, which=fake_which
    )
    assert archs == ("x86_64", "arm64"), (archs, reason)
    assert reason is None, (archs, reason)


def test_tool_binary_architecture_without_file_on_path_says_so():
    archs, reason = doctor.tool_binary_architecture(
        "/usr/local/bin/gh", run=None, which=lambda name: None
    )
    assert archs is None, (archs, reason)
    assert "not on PATH" in reason, reason


def test_tool_binary_architecture_an_unparseable_file_output_says_so_rather_than_guessing():
    def fake_run(cmd, **kwargs):
        return _FakeCompleted(b"some unexpected output with no architecture token\n")

    def fake_which(name):
        return "/usr/bin/file" if name == "file" else None

    archs, reason = doctor.tool_binary_architecture(
        "/usr/local/bin/gh", run=fake_run, which=fake_which
    )
    assert archs is None, (archs, reason)
    assert reason, reason


def test_tool_binary_architecture_a_dead_probe_says_so_rather_than_raising():
    def fake_run(cmd, **kwargs):
        raise OSError("boom")

    def fake_which(name):
        return "/usr/bin/file" if name == "file" else None

    archs, reason = doctor.tool_binary_architecture(
        "/usr/local/bin/gh", run=fake_run, which=fake_which
    )
    assert archs is None, (archs, reason)
    assert "boom" in reason, reason


# --- the real probe: loudly-skipping rather than asserting on this machine ---


def test_check_gh_binary_runs_without_raising():
    """doctor's whole contract is exit 0 always, one VERDICT line -- a check that
    raises takes the diagnostic down. This is the one assertion that holds on
    every machine regardless of what gh happens to be here.
    """
    findings_before = len(doctor.FINDINGS)
    doctor.check_gh_binary()
    assert len(doctor.FINDINGS) > findings_before


def test_a_real_probe_of_this_machines_gh_never_claims_a_match_on_a_read_failure():
    """Loudly-skipping positive control, mirroring test_doctor_interpreter_
    environment_367.py's own pattern: nothing is asserted about what this
    machine's gh IS, only that an unreadable state never renders as a match.
    """
    import shutil

    resolved = shutil.which("gh")
    if resolved is None:
        pytest.skip("gh is not on PATH on this machine -- nothing to probe")
    archs, reason = doctor.tool_binary_architecture(resolved)
    if archs is None:
        # Either `file` is absent or its output was unparseable -- both real,
        # both must not silently read as a match anywhere downstream.
        assert reason, "no architecture and no reason -- the third state broke"
