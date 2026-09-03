"""#777: the fragment gate reads the `no-changelog` label live, not off the event
payload -- so applying it after a red run and re-running actually clears it.

`.github/workflows/oss-changelog.yml`'s gate step used to be conditioned on
`if: ${{ !contains(github.event.pull_request.labels.*.name, 'no-changelog') }}`, which
is the label set as the run was CREATED. `Re-run failed jobs` replays that same
payload, so applying the label to a red run and re-running failed again, forever --
only a new commit moved the head sha far enough to get a fresh payload.

The fix (matched against `Digital-Process-Tools/claude-supertool#1722`, already shipped
there) reads the label set live via `gh api repos/{repo}/pulls/{n}`, falling back to the
event payload -- read as JSON via `jq`, never joined into a comma string, since a label
NAME may itself contain a comma -- when the live read fails for any reason. The two
tests below are the matched pair the fallback needs: the live path taking effect, and
the live path failing over to the payload without ever failing CLOSED (a `gh` outage
must never redden a board that was green a moment before).

Shares its shell-extraction harness with `tests/test_changelog_gate.py` rather than
duplicating it -- same reason `tests/test_bot_pull_request_293.py` does.
"""

import atexit
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import scaffold  # noqa: E402

from test_changelog_gate import (  # noqa: E402
    BASH,
    GENERATED_WORKFLOW,
    _child_env,
    _config,
    _gate_script,
    _pull_request,
    _require,
)

# A pull request that changes product code and adds no fragment: the exact shape the
# gate exists to refuse absent the escape hatch, so a skip below is legible as the
# label taking effect rather than as some other branch quietly firing.
NO_FRAGMENT = {"src.py": "value = 2\n"}


def _gh_shim(output_lines, exit_code=0):
    """A `gh` on PATH that answers `gh api ... --jq '.labels[].name'` with
    `output_lines`, one per line, and nothing else -- so a test can drive the LIVE
    branch without reaching a real forge or a real pull request.
    """
    directory = tempfile.mkdtemp(prefix="oss-gate-gh-shim-")
    atexit.register(shutil.rmtree, directory, True)
    out_file = Path(directory) / "gh.out"
    out_file.write_text("\n".join(output_lines) + ("\n" if output_lines else ""), encoding="utf-8")
    shim = Path(directory) / "gh"
    shim.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = api ]; then\n"
        "  cat '{}'\n"
        "  exit {}\n"
        "fi\n"
        "exit 1\n".format(out_file.as_posix(), exit_code),
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return directory


def _run_gate(repo, gh_dir=None, event_labels_json=None, author=None):
    for tool in ("git", "grep", "sed"):
        _require(tool)
    extra = {"BASE_REF": "main"}
    if author is not None:
        extra["PR_AUTHOR"] = author
    if event_labels_json is not None:
        extra["EVENT_LABELS_JSON"] = event_labels_json
    env = _child_env(BASH, **extra)
    if gh_dir is not None:
        # Ahead of the rest of PATH, including any real `gh`, so this shim is the one
        # `command -v gh` and the call itself both reach.
        env["PATH"] = os.pathsep.join([gh_dir, env["PATH"]])
    return subprocess.run(
        [BASH, "-c", _gate_script()],
        cwd=str(repo),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        errors="replace",
    )


def test_permissions_grants_pull_requests_read():
    """The scope the live label read actually needs (#777) -- `pulls`, not
    `issues/{n}/labels`, per the workflow's own comment on the endpoint choice."""
    body = scaffold.render_owned(GENERATED_WORKFLOW, _config())
    lines = body.splitlines()
    perm_lines = [i for i, line in enumerate(lines) if line.strip() == "permissions:"]
    assert len(perm_lines) == 1, lines
    start = perm_lines[0]
    block = []
    for line in lines[start + 1:]:
        if not line.strip() or line.startswith("  "):
            block.append(line)
            continue
        break
    joined = "\n".join(block)
    assert "contents: read" in joined, joined
    assert "pull-requests: read" in joined, joined


def test_the_gate_step_no_longer_carries_the_stale_payload_if_condition():
    """The defect itself: an `if:` evaluated once, at trigger time, cannot ever see a
    label applied after the run was created -- narrowing the STEP to a live read is
    what makes the escape hatch survive a re-run."""
    body = scaffold.render_owned(GENERATED_WORKFLOW, _config())
    assert (
        "if: ${{ !contains(github.event.pull_request.labels.*.name, 'no-changelog') }}"
        not in body
    ), body


# --------------------------------------------------------------- the matched pair


def test_a_label_applied_after_the_run_started_is_visible_on_a_live_read(tmp_path):
    """Must fire: the whole point of #777. A label that could never have been in the
    frozen event payload (the fixture never sets one) still clears the gate, because
    the live read is what is trusted first."""
    gh_dir = _gh_shim(["no-changelog"])
    done = _run_gate(
        _pull_request(tmp_path, NO_FRAGMENT), gh_dir=gh_dir, event_labels_json="[]"
    )
    assert done.returncode == 0, done.stdout
    assert "skipped" in done.stdout
    assert "read live" in done.stdout, done.stdout


def test_a_pull_request_carrying_neither_label_is_still_refused(tmp_path):
    """The must-not-fire half of the same pair, same fixture, same live path: an
    absent label is read live too, and does not forge a pass."""
    gh_dir = _gh_shim(["unrelated-label"])
    done = _run_gate(
        _pull_request(tmp_path, NO_FRAGMENT), gh_dir=gh_dir, event_labels_json="[]"
    )
    assert done.returncode == 1, done.stdout
    assert "No changelog fragment" in done.stdout


# ------------------------------------------------------------ degrade, not fail-closed


def test_a_failed_live_read_degrades_to_the_event_payload_rather_than_failing_closed(tmp_path):
    """Must fire: `gh` reachable but erroring (a bad scope, an outage, no auth) must
    not redden a board that the payload alone would have kept green -- the read
    degrades to the frozen labels rather than treating a read failure as `no label`."""
    gh_dir = _gh_shim([], exit_code=1)
    done = _run_gate(
        _pull_request(tmp_path, NO_FRAGMENT),
        gh_dir=gh_dir,
        event_labels_json='["no-changelog"]',
    )
    assert done.returncode == 0, done.stdout
    assert "skipped" in done.stdout
    assert "read payload" in done.stdout, done.stdout
    # The degrade announces itself -- a check that could not look live says so,
    # rather than answering as though it had.
    assert "note" in done.stdout, done.stdout


def test_no_gh_on_path_at_all_also_degrades_to_the_payload(tmp_path):
    """The other route to the same degrade: `gh` missing outright rather than
    erroring. `_child_env` already strips real credentials and points `GH_CONFIG_DIR`
    at an empty directory, so the real `gh` on this machine's PATH answers exactly
    like this if this test is skipped for having no shim -- this asserts it directly."""
    done = _run_gate(
        _pull_request(tmp_path, NO_FRAGMENT),
        gh_dir=None,
        event_labels_json='["no-changelog"]',
    )
    assert done.returncode == 0, done.stdout
    assert "skipped" in done.stdout


def test_a_comma_inside_one_label_name_cannot_forge_the_hatch(tmp_path):
    """#777's own worked example: a label literally named `wontfix,no-changelog` is
    ONE label, and must not be readable as the two labels `wontfix` and
    `no-changelog` -- which a joined-and-split-on-comma representation cannot avoid,
    since Actions itself joins with a comma before the shell ever sees it. Reading
    labels as a JSON array (live: one per `jq` line; payload: `toJSON(...)` parsed by
    `jq`) sidesteps the ambiguity entirely rather than trying to escape a comma."""
    gh_dir = _gh_shim(["wontfix,no-changelog"])
    done = _run_gate(
        _pull_request(tmp_path, NO_FRAGMENT), gh_dir=gh_dir, event_labels_json="[]"
    )
    assert done.returncode == 1, done.stdout
    assert "No changelog fragment" in done.stdout


# --------------------------------------------------------------------- the remedy


def test_the_failure_message_says_re_run_when_the_read_was_live(tmp_path):
    gh_dir = _gh_shim(["unrelated-label"])
    done = _run_gate(
        _pull_request(tmp_path, NO_FRAGMENT), gh_dir=gh_dir, event_labels_json="[]"
    )
    assert done.returncode == 1, done.stdout
    assert "re-run" in done.stdout, done.stdout
    assert "push a" not in done.stdout, done.stdout


def test_the_failure_message_says_push_a_commit_when_the_read_degraded(tmp_path):
    gh_dir = _gh_shim([], exit_code=1)
    done = _run_gate(
        _pull_request(tmp_path, NO_FRAGMENT), gh_dir=gh_dir, event_labels_json="[]"
    )
    assert done.returncode == 1, done.stdout
    assert "push a" in done.stdout, done.stdout


# ------------------------------------------------------------ jq absent, not crashed


def _path_only(*tools):
    """A fresh directory holding ONE symlink per name in `tools`, resolved off the
    CURRENT `PATH` -- never the whole directory a wanted tool happens to live in,
    which is how the first cut of this fixture also removed `grep`: on this machine
    `jq` and `grep` are both under `/usr/bin`, so excluding jq's directory silently
    took grep with it. A directory that names exactly what it means to expose is the
    only way to leave `jq` out without an accident naming what else goes.
    """
    directory = tempfile.mkdtemp(prefix="oss-gate-path-only-")
    atexit.register(shutil.rmtree, directory, True)
    for tool in tools:
        found = shutil.which(tool)
        if found is None:
            pytest.skip("{} is not on PATH at all -- untested here".format(tool))
        (Path(directory) / tool).symlink_to(found)
    return directory


def test_a_missing_jq_does_not_crash_the_payload_fallback(tmp_path):
    """#777, found by review: the payload fallback pipes `EVENT_LABELS_JSON` through
    `jq`, unguarded, unlike the live path's own `command -v gh` check two lines above
    it. `jq` genuinely absent must not read as "the payload held no labels" -- see the
    must-fire pair below for that distinction -- but it must also not crash the step:
    `2>/dev/null || true` on the pipeline is what is asserted here."""
    gh_dir = _gh_shim([], exit_code=1)  # forces the payload fallback
    env = _child_env(BASH, BASE_REF="main", EVENT_LABELS_JSON='["no-changelog"]')
    for tool in ("git", "grep", "sed"):
        _require(tool)
    clean = _path_only("git", "grep", "sed")
    env["PATH"] = os.pathsep.join([gh_dir, clean])
    done = subprocess.run(
        [BASH, "-c", _gate_script()],
        cwd=str(_pull_request(tmp_path, NO_FRAGMENT)),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        errors="replace",
    )
    # Must not fire: no shell error (a `-c` script error is 2, never 0 or 1).
    assert done.returncode in (0, 1), done.stdout
    # Must fire: absent `jq` reads differently from a genuinely empty payload -- see
    # the two tests above (`test_a_failed_live_read_degrades_...` and
    # `test_the_failure_message_says_push_a_commit_...`) for the "payload present,
    # parsed, no label" case this must not be confused with.
    assert "jq" in done.stdout, done.stdout
