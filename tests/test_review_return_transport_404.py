"""#404 -- the reviewer's message is parsed by bash before any guard runs.

`agents/developer.md` tells the developer to hand a review spawn's final
message -- by this repository's own account the least trusted string in the
system -- to `scripts/review_return.py` by placing it at column zero of a
stream **bash** parses, closed by a fixed single-word terminator. Every
protection in that script operates on text it has already received; the
heredoc decides what it receives, and bash resolves that boundary before a
line of the script runs.

**Reachability does not need an adversary.** A reviewer reviewing a change to
`agents/developer.md` -- routine here -- quotes that code block, terminator
included. The audit's single invocation produced both harms at once: a line of
message text executed as a command, and the classifier returning
`referred-not-stated` over a review that referred to nothing. The instrument
manufacturing the failure it exists to measure.

## Why this test drives bash, when CLAUDE.md warns against tests that do

The trap recorded there is a test that *reconstructs* shell behaviour inside a
`bash -c` string and ends up measuring its own escaping. Here the shell's
parse is not a nuisance in the way of the subject -- it **is** the subject: the
question is whether bash ends the message where the message says to. So there
is no `-c` string and no nested quoting to get wrong. The documented block is
lifted out of `agents/developer.md` verbatim, written to a file, and run.

## What "substituting the message" means, and why it needs no interpretation

The block carries one placeholder line. Each line of the message is emitted at
**the placeholder's own indentation** -- which is the whole of what
substitution means, and is what a compliant agent does. That single mechanical
rule is what makes this test red before the fix and green after it without
either state being written into the test: while the placeholder sits at column
zero the message sits at column zero and forges the terminator; once the
placeholder is indented the message is indented and cannot.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BRIEF = REPO / "agents" / "developer.md"

PLACEHOLDER = "<the reviewer's final message"
CANARY = "CANARY-EXECUTED"


# -- the two messages -------------------------------------------------------
#
# The hostile one is not an attack. It is a reviewer reporting #404 and
# quoting the block it is reporting on, which is the ordinary route the issue
# names as the likely first instance. The redirection line stands in for
# whatever text happens to follow the quoted terminator; a bare `>` needs no
# external binary, so it behaves the same on every leg.

FORGING_MESSAGE = """FINDINGS: 2

1. `agents/developer.md` hands the message to bash. The block reads:

python3 "${CLAUDE_PLUGIN_ROOT}/scripts/review_return.py" - <<'MSG'
<the reviewer's final message, exactly as it reached you>
MSG

> CANARY-EXECUTED
2. The stdin branch of `_read_source` has no guard, so a closed stdin
raises instead of reaching `could-not-read`. That is #405."""

ORDINARY_MESSAGE = """FINDINGS: 2

1. `scripts/oss_config.py` anchors with `^...$`, which matches before a
trailing newline. A value ending in a newline validates.

2. `scripts/doctor.py` reports `none` for both an empty scan and an
unreadable one."""


def _extract_block():
    """The one fenced bash block in the brief that invokes the classifier."""
    text = BRIEF.read_text(encoding="utf-8")
    blocks = re.findall(r"^```bash\n(.*?)^```", text, re.S | re.M)
    hits = [b for b in blocks if "review_return.py" in b]
    assert len(hits) == 1, "expected exactly one documented transport, got {0}".format(
        len(hits)
    )
    return hits[0]


def _render(block, message):
    """Emit each message line at the placeholder's own indentation."""
    out = []
    seen = 0
    for line in block.splitlines():
        if PLACEHOLDER in line:
            seen += 1
            indent = line[: len(line) - len(line.lstrip(" "))]
            out.extend(indent + m for m in message.splitlines())
        else:
            out.append(line)
    assert seen == 1, "expected one placeholder line in the block, got {0}".format(seen)
    return "\n".join(out) + "\n"


def _run(tmp_path, message):
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip(
            "no bash on PATH, so the shell parse this test is about went "
            "untested on this leg"
        )
    block = _extract_block()
    # The brief spells the interpreter `python3`, which is not the name on
    # every leg. Substituting the running interpreter changes who is invoked,
    # never how the shell parses the stream -- which is the subject.
    interpreter = sys.executable.replace("\\", "/")
    block = block.replace("python3 ", '"' + interpreter + '" ', 1)

    script = tmp_path / "transport.sh"
    # write_bytes, not write_text(newline=...): the newline argument landed in
    # 3.10 and CI gates 3.9. Bytes also keep the LF the heredoc needs.
    script.write_bytes(_render(block, message).encode("utf-8"))

    env = dict(os.environ)
    # Forward slashes on every leg. A backslash inside a bash double-quoted
    # string is literal for most characters and an escape for a few, so a
    # Windows-shaped root is a coin toss on which segment it lands in --
    # unrelated to what this test measures. Windows accepts either form.
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO).replace("\\", "/")
    proc = subprocess.run(
        [bash, str(script)],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )
    return proc


def test_a_message_that_forges_the_terminator_is_carried_as_content(tmp_path):
    """The whole of #404, in one invocation, exactly as the audit ran it."""
    proc = _run(tmp_path, FORGING_MESSAGE)

    assert not (tmp_path / CANARY).exists(), (
        "a line of the reviewer's message ran as a command: the transport let "
        "untrusted text out of the stream and into bash.\n"
        "stdout:\n{0}\nstderr:\n{1}".format(proc.stdout, proc.stderr)
    )
    assert "VERDICT: states-findings" in proc.stdout, (
        "the classifier did not receive the whole message. This message states "
        "both of the findings its header claims, so any other verdict is the "
        "instrument manufacturing the failure it measures.\n"
        "stdout:\n{0}\nstderr:\n{1}".format(proc.stdout, proc.stderr)
    )
    assert "referred-not-stated" not in proc.stdout, proc.stdout


def test_an_ordinary_message_still_classifies(tmp_path):
    """The control: a fix cannot pass this file by refusing everything."""
    proc = _run(tmp_path, ORDINARY_MESSAGE)

    assert "VERDICT: states-findings" in proc.stdout, (
        "an ordinary compliant message stopped classifying.\n"
        "stdout:\n{0}\nstderr:\n{1}".format(proc.stdout, proc.stderr)
    )
    assert not (tmp_path / CANARY).exists(), proc.stdout


# -- `unframe` in-process, where the return shape is visible ---------------
#
# The subprocess cases above are the demonstration; these pin the contract the
# rest of the module reads -- exactly one of ``(message, error)`` is None, so
# an unframing that failed can never be mistaken for one that read nothing.

sys.path.insert(0, str(REPO / "scripts"))

import review_return  # noqa: E402


def test_unframe_returns_exactly_one_of_message_and_error():
    message, error = review_return.unframe(
        "    NO FINDINGS\nEND OF MESSAGE\n"
    )
    assert error is None
    assert message == "NO FINDINGS"

    message, error = review_return.unframe("    NO FINDINGS\n")
    assert message is None
    assert error is not None


def test_unframe_discards_whatever_follows_the_sentinel():
    """A forged sentinel cannot be used to append content, because a message
    line carrying it is indented and so does not close the frame."""
    message, error = review_return.unframe(
        "    NO FINDINGS\nEND OF MESSAGE\nleftover\n"
    )
    assert error is None, error
    assert "leftover" not in message


def test_unframe_names_the_offending_line_folded():
    _, error = review_return.unframe(
        "    ok\nnot indented — and carrying an em dash\nEND OF MESSAGE\n"
    )
    assert error is not None
    assert "line 2" in error
    assert all(32 <= ord(c) <= 126 for c in error), error


# -- the two refusals, each against a control that must not refuse ---------


def _framed(text):
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "review_return.py"), "--framed", "-"],
        input=text.encode("utf-8"),
        capture_output=True,
    )
    return proc.returncode, proc.stdout.decode("utf-8", errors="replace")


WELL_FRAMED = (
    "    FINDINGS: 1\n"
    "\n"
    "    1. A finding, stated in full.\n"
    "END OF MESSAGE\n"
)


def test_a_well_framed_message_classifies():
    """The control for both refusals below."""
    code, out = _framed(WELL_FRAMED)
    assert out.startswith("VERDICT: states-findings"), out
    assert code == 0, out


def test_a_frame_that_never_closed_is_could_not_read():
    """What a message that ended its own stream early looks like from in here.

    The prefix that survives is a perfectly classifiable message -- it carries
    a header and a block -- which is exactly why the missing sentinel has to be
    the answer. Classifying it would be #404's second half.
    """
    code, out = _framed("    FINDINGS: 1\n\n    1. A finding, stated in full.\n")
    assert out.startswith("VERDICT: could-not-read"), out
    assert "framing never closed" in out, out
    assert code == 6, out


def test_an_unindented_line_is_could_not_read_and_is_named():
    """A half-applied prefix is not a verdict about the review."""
    code, out = _framed(
        "    FINDINGS: 1\n"
        "\n"
        "1. This line was never indented.\n"
        "END OF MESSAGE\n"
    )
    assert out.startswith("VERDICT: could-not-read"), out
    assert "line 3" in out, out
    assert code == 6, out


def test_the_indent_is_stripped_so_blocks_are_still_at_column_zero():
    """Not a restatement of the control: this is the failure mode where the
    guard reads as working and silently classifies everything as prose.

    `_BLOCK` counts at column zero, so a framed message that reached the
    classifier still wrapped would enumerate nothing and a real
    `FINDINGS: 2` return would come back `referred-not-stated`.
    """
    code, out = _framed(
        "    FINDINGS: 2\n"
        "\n"
        "    1. First, stated in full.\n"
        "    2. Second, stated in full.\n"
        "END OF MESSAGE\n"
    )
    assert "enumerable blocks: 2" in out, out
    assert code == 0, out


def test_relative_indentation_inside_the_message_survives():
    code, out = _framed(
        "    NO FINDINGS\n"
        "\n"
        "    Checked:\n"
        "        - scripts/review_return.py\n"
        "END OF MESSAGE\n"
    )
    assert out.startswith("VERDICT: no-findings"), out
    assert code == 0, out


def test_the_brief_does_not_place_untrusted_text_at_column_zero():
    """The placeholder is the whole of the construction, so pin it.

    A terminator of any length is forgeable by the ordinary route, because the
    route is a reviewer quoting the block *including its terminator*. What is
    not forgeable is a content line that cannot be a bare terminator by
    construction, which is what the indentation buys.
    """
    block = _extract_block()
    placeholder = [ln for ln in block.splitlines() if PLACEHOLDER in ln]
    assert len(placeholder) == 1, block
    assert placeholder[0].startswith("    "), (
        "the documented transport still puts the reviewer's message at column "
        "zero of a stream bash parses:\n" + block
    )
