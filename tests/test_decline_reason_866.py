"""#866: a declined dispatch -- an issue parked or a lane left short on a reason
that is not `board-exhausted`/`no-adjacent`/`could-not-tell` -- is checkable by
shape, not by trusting the prose: the reason either names the call this tick ran
to establish it (a backtick-quoted op string or a script invocation) or it does
not, and an inherited or freehand reason with no such citation is not a reason.

Every "must refuse" case is paired with a "must accept" case in the same
fixture -- a refusal-only suite cannot tell a real refusal from a test that
never triggers the code path.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402


def _piped(argv):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "oss_state.py")] + argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


# --------------------------------------------------------- library-level


def test_a_reason_citing_an_op_string_is_cited():
    """The positive control: a reason naming a real call this tick ran."""
    record = oss_state.decline_reason_state(
        "`gh-issue:844` shows assignee jbkkz, filed by an external maintainer"
    )
    assert record["state"] == "cited"


def test_a_reason_citing_a_script_invocation_is_cited():
    record = oss_state.decline_reason_state(
        "`lane_setup.py --lane skills/manager/SKILL.md --against ...` shows the "
        "PR holding the files"
    )
    assert record["state"] == "cited"


def test_a_reason_citing_a_bare_op_string_with_no_colon_is_cited():
    """`gh-prs` -- no colon, only a hyphen -- is the second worked example
    `skills/manager/phases/dispatch.md` and `changelog.d/866.added.md` both
    cite. A colon-only first draft of the citation regex missed this one
    entirely (found by review): it must be exercised on its own."""
    record = oss_state.decline_reason_state(
        "`gh-prs` shows PR #900 already holding scripts/oss_state.py"
    )
    assert record["state"] == "cited"


def test_a_backtick_wrapped_timestamp_is_not_a_citation():
    """A colon alone is not a citation shape -- `14:32` is a timestamp, not an
    op string or a script invocation, even wrapped in backticks (found by
    review)."""
    record = oss_state.decline_reason_state(
        "queued after `14:32` UTC handoff, external maintainer"
    )
    assert record["state"] == "uncited"


def test_a_backtick_wrapped_ratio_is_not_a_citation():
    record = oss_state.decline_reason_state("ratio `3:1` in favor, park it")
    assert record["state"] == "uncited"


def test_a_backtick_wrapped_bare_url_is_not_a_citation():
    """A URL's scheme colon (`https://...`) is not an op or script invocation
    on its own -- only a hyphen elsewhere in the token, or a `.py` shape,
    counts (found by review)."""
    record = oss_state.decline_reason_state(
        "see `https://github.com/foo/bar/issues/900` for context"
    )
    assert record["state"] == "uncited"


def test_a_reason_with_no_citation_is_uncited():
    """The negative arm: a true-sounding but unmeasured reason must not pass as
    a citation just because it reads like one."""
    record = oss_state.decline_reason_state("belongs to an external maintainer")
    assert record["state"] == "uncited"


def test_an_inherited_reason_with_no_citation_is_uncited_even_if_true():
    record = oss_state.decline_reason_state("needs the maintainer's ruling")
    assert record["state"] == "uncited"


def test_empty_reason_refuses_rather_than_silently_uncited():
    with pytest.raises(oss_state.StateError, match="reason"):
        oss_state.decline_reason_state("")


def test_none_reason_refuses():
    with pytest.raises(oss_state.StateError, match="reason"):
        oss_state.decline_reason_state(None)


# --------------------------------------------------------- CLI-level


def test_cli_reports_cited(tmp_path):
    state_path = tmp_path / "state.json"
    result = _piped(
        [
            str(state_path),
            "--check-decline-reason",
            "`gh-prs` shows PR #900 already holding scripts/oss_state.py",
        ]
    )
    assert result.returncode == 0, result.stdout
    # Not `"CITED" in result.stdout` -- that substring is also inside the
    # literal word "UNCITED", so it would pass unchanged even if the CLI
    # always printed the opposite state (found by review). The JSON state
    # field is unambiguous between the two.
    assert '"state": "cited"' in result.stdout, result.stdout
    assert "UNCITED" not in result.stdout, result.stdout


def test_cli_reports_uncited():
    result = _piped(
        ["/nonexistent/state.json", "--check-decline-reason", "belongs to an external maintainer"]
    )
    assert result.returncode == 0, result.stdout
    assert '"state": "uncited"' in result.stdout, result.stdout
