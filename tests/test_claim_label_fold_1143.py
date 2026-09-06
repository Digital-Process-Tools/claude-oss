"""#1143: pick-the-work collapses four hand-composed steps into two calls.

`fleet_label`/`agent_call` are folded from the now-deleted `lane_setup_label.py`
directly into `lane_setup.py` (they keep their own tests, `test_fleet_label_539.py`
and `test_fleet_label_989.py`, updated to import `lane_setup` instead). This file
covers the new behaviour: `--claim` renders the fleet label (and, given a
subagent type, the whole `Agent(...)` call) from the issues the claim call
*actually holds*, never from the issues the caller requested, and refuses to
render the `Agent(...)` line when the brief it is about to dispatch fails one of
`lane_setup_brief_schema`'s four structural checks.

Every "must not" is paired with a "must" in the same fixture, per this
repository's own rule for a negative assertion.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402
import lane_setup_claim  # noqa: E402
import select_issues_claim_read as claim_read  # noqa: E402

GOOD_BRIEF = """
# Brief: fix the thing (#123)

Use `supertool` for every write, commit included. To change an existing file,
`supertool 'edit:@-'`; to create one, `supertool 'paste:@-'` -- a new file has no `old`,
and your changelog fragment is always one. Commit through `supertool 'git-commit:@-'`.
`cd <worktree_root>` on every write call leaving your branch directory, not once: a shell
cwd does not persist between calls.

The hidden judgment call: you will have to decide whether the guard belongs at the call
site or one layer down. Say which you chose and why.

Push back on any of this. The diagnosis below is a hypothesis with the evidence attached,
not a conclusion.

TDD in this order -- test, red, fix, green. Send the failing output before the
implementation exists.

Docs: the changelog fragment always; docs_targets if this reaches a user.

Live worktrees right now: ../wt-121 (issue #121), ../wt-122 (issue #122).

When you are done: commit, do not push, do not open a PR, do not comment on the issue.
"""


def _row(issue, state, **extra):
    row = {"issue": issue, "state": state}
    row.update(extra)
    return row


def _mixed_checker(fail_issue, fail_state=claim_read.STATE_COULD_NOT_CLAIM):
    """A claim/release checker where every issue but `fail_issue` succeeds --
    the shape a real forge call produces when one companion's write genuinely
    fails while the others' already landed (#1143's own example)."""

    def _checker(numbers, mode, repo=None):
        if mode == "claim":
            return [
                _row(n, fail_state, detail="boom") if n == fail_issue else _row(n, claim_read.STATE_CLAIMED)
                for n in numbers
            ]
        if mode == "release":
            return [_row(n, claim_read.STATE_RELEASED) for n in numbers]
        raise AssertionError("unexpected mode: {0}".format(mode))

    return _checker


def _always(state):
    def _checker(numbers, mode, repo=None):
        if mode == "claim":
            return [_row(n, state) for n in numbers]
        if mode == "release":
            return [_row(n, claim_read.STATE_RELEASED) for n in numbers]
        raise AssertionError(mode)

    return _checker


# --------------------------------------------------------------- fleet_label / agent_call live on lane_setup


def test_fleet_label_and_agent_call_are_defined_directly_on_lane_setup():
    """#1143: lane_setup_label.py is gone; nothing imports it any more."""
    assert not (REPO_ROOT / "scripts" / "lane_setup_label.py").exists()
    assert lane_setup.fleet_label(534, [534], "phrase") == "Lane 534  phrase"
    call = lane_setup.agent_call(534, [534], "phrase", "oss:developer")
    assert 'subagent_type: "oss:developer"' in call


# --------------------------------------------------------------- _claimed_issue_numbers: the core derivation


def test_full_success_counts_every_issue_requested(tmp_path):
    """Positive control: nothing failed and the registry write itself
    succeeds, so the held set is the full bundle."""
    checker = _always(claim_read.STATE_CLAIMED)
    result = lane_setup_claim.claim_and_register(
        str(tmp_path / "registry"), 1, "fix/1", str(tmp_path / "wt"),
        also_claim=[2, 3], checker=checker,
    )
    assert result["state"] == lane_setup_claim.CLAIM_STATE_CLAIMED
    held = lane_setup._claimed_issue_numbers(result)
    assert sorted(held) == [1, 2, 3]


def test_a_failed_companion_is_excluded_from_the_held_set(tmp_path):
    """The scenario named in #1143 itself: the third issue comes back
    could-not-claim-assignee, so the lane carries two, never three."""
    checker = _mixed_checker(fail_issue=3)
    result = lane_setup_claim.claim_and_register(
        str(tmp_path / "registry"), 1, "fix/1", str(tmp_path / "wt"),
        also_claim=[2, 3], checker=checker,
    )
    held = lane_setup._claimed_issue_numbers(result)
    assert sorted(held) == [1, 2]
    assert 3 not in held


def test_an_already_claimed_companion_is_excluded_too(tmp_path):
    checker = _mixed_checker(fail_issue=3, fail_state=claim_read.STATE_ALREADY_CLAIMED)
    result = lane_setup_claim.claim_and_register(
        str(tmp_path / "registry"), 1, "fix/1", str(tmp_path / "wt"),
        also_claim=[2, 3], checker=checker,
    )
    held = lane_setup._claimed_issue_numbers(result)
    assert sorted(held) == [1, 2]


def test_no_claim_result_at_all_holds_nothing():
    assert lane_setup._claimed_issue_numbers(None) == []


def test_a_rolled_back_assignee_is_no_longer_held(tmp_path):
    """The registry write fails after a fresh assignee write succeeded --
    `claim_and_register` releases it again, so it must not be counted as
    held even though the row itself still says `claimed`."""
    checker = _always(claim_read.STATE_CLAIMED)
    not_a_dir = tmp_path / "not-a-dir"
    not_a_dir.write_text("x")
    result = lane_setup_claim.claim_and_register(
        str(not_a_dir), 4, "fix/4", str(tmp_path / "wt"), checker=checker
    )
    assert result["state"] == lane_setup_claim.CLAIM_STATE_ASSIGNEE_ROLLED_BACK
    assert lane_setup._claimed_issue_numbers(result) == []


# --------------------------------------------------------------- compose_claim_label


def _payload(issue, claim_result):
    return {"issue": issue, "claim_result": claim_result}


def test_compose_claim_label_renders_x2_when_a_third_issue_fails(tmp_path):
    checker = _mixed_checker(fail_issue=3)
    result = lane_setup_claim.claim_and_register(
        str(tmp_path / "registry"), 1, "fix/1", str(tmp_path / "wt"),
        also_claim=[2, 3], checker=checker,
    )
    label = lane_setup.compose_claim_label(_payload(1, result), "auto-update path")
    assert label["state"] == "rendered"
    assert label["text"] == "Lane 1 x2  auto-update path"


def test_compose_claim_label_renders_x3_when_everything_claims(tmp_path):
    """Positive control paired with the test above."""
    checker = _always(claim_read.STATE_CLAIMED)
    result = lane_setup_claim.claim_and_register(
        str(tmp_path / "registry"), 1, "fix/1", str(tmp_path / "wt"),
        also_claim=[2, 3], checker=checker,
    )
    label = lane_setup.compose_claim_label(_payload(1, result), "auto-update path")
    assert label["state"] == "rendered"
    assert label["text"] == "Lane 1 x3  auto-update path"


def test_compose_claim_label_refuses_when_nothing_was_actually_held():
    label = lane_setup.compose_claim_label(_payload(1, None), "phrase")
    assert label["state"] == "no-claimed-issues"
    assert label["text"] is None


def test_compose_claim_label_refuses_when_the_primary_issue_is_not_held(tmp_path):
    checker = _mixed_checker(fail_issue=1)
    result = lane_setup_claim.claim_and_register(
        str(tmp_path / "registry"), 1, "fix/1", str(tmp_path / "wt"),
        also_claim=[2, 3], checker=checker,
    )
    label = lane_setup.compose_claim_label(_payload(1, result), "phrase")
    assert label["state"] == "primary-not-held"
    assert label["text"] is None


def test_compose_claim_label_refuses_agent_call_on_a_structural_brief_finding(tmp_path):
    """A brief missing `supertool` entirely fails a structural element --
    the Agent(...) line must not be rendered."""
    checker = _always(claim_read.STATE_CLAIMED)
    result = lane_setup_claim.claim_and_register(
        str(tmp_path / "registry"), 1, "fix/1", str(tmp_path / "wt"), checker=checker
    )
    brief = tmp_path / "brief.md"
    brief.write_text("nothing useful here at all", encoding="utf-8")
    label = lane_setup.compose_claim_label(
        _payload(1, result), "phrase", subagent_type="oss:developer", brief_path=str(brief)
    )
    assert label["state"] == "brief-structural-finding"
    assert label["text"] is None
    assert label["brief"]["state"] == "findings"


def test_compose_claim_label_renders_agent_call_despite_presence_only_findings(tmp_path):
    """Positive control: a brief missing only a presence-only element
    (`judgment_call`) still renders the Agent(...) call -- only the four
    structural elements gate dispatch."""
    checker = _always(claim_read.STATE_CLAIMED)
    result = lane_setup_claim.claim_and_register(
        str(tmp_path / "registry"), 1, "fix/1", str(tmp_path / "wt"), checker=checker
    )
    brief = tmp_path / "brief.md"
    text = "\n\n".join(
        p for p in GOOD_BRIEF.split("\n\n") if "hidden judgment call" not in p
    )
    brief.write_text(text, encoding="utf-8")
    label = lane_setup.compose_claim_label(
        _payload(1, result), "phrase", subagent_type="oss:developer", brief_path=str(brief)
    )
    assert label["state"] == "rendered"
    assert 'subagent_type: "oss:developer"' in label["text"]
    assert label["brief"]["state"] == "findings"
    assert "judgment_call" in label["brief"]["missing"]


def test_compose_claim_label_refuses_when_the_brief_could_not_be_read(tmp_path):
    checker = _always(claim_read.STATE_CLAIMED)
    result = lane_setup_claim.claim_and_register(
        str(tmp_path / "registry"), 1, "fix/1", str(tmp_path / "wt"), checker=checker
    )
    label = lane_setup.compose_claim_label(
        _payload(1, result), "phrase", subagent_type="oss:developer",
        brief_path=str(tmp_path / "absent.md"),
    )
    assert label["state"] == "brief-could-not-read"
    assert label["text"] is None


# --------------------------------------------------------------- end to end, through compute()


def test_compute_claim_with_a_failing_companion_composes_x2_end_to_end(tmp_path, monkeypatch):
    """The full pipeline: compute() with an injected checker, then
    compose_claim_label off its own claim_result -- the shape a dispatcher
    actually calls (#1143)."""
    import json
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    worktree_root = tmp_path / "worktrees"
    config = {
        "repo": "example/example",
        "default_branch": "main",
        "branch_pattern": "fix/{issue}",
        "test_command": "true",
        "docs_targets": [],
        "changelog_dir": "changelog.d",
    }
    (repo / lane_setup.CONFIG_NAME).write_text(json.dumps(config))

    monkeypatch.setattr(
        lane_setup,
        "resolve_base",
        lambda *a, **k: {
            "state": "resolved",
            "remote": "origin",
            "ref": "origin/main",
            "sha": "a" * 40,
            "detail": "",
        },
    )
    monkeypatch.setattr(lane_setup, "branch_occupancy", lambda *a, **k: (False, False))
    monkeypatch.setattr(
        lane_setup, "read_board", lambda repo: {"state": "ok", "lines": [], "detail": ""}
    )
    real_load = lane_setup.oss_config.load

    def fake_load(path):
        cfg, problems = real_load(path)
        if cfg is not None:
            cfg = dict(cfg)
            cfg["worktree_root"] = str(worktree_root)
        return cfg, problems

    monkeypatch.setattr(lane_setup.oss_config, "load", fake_load)

    checker = _mixed_checker(fail_issue=3)
    payload = lane_setup.compute(
        str(repo), 1, "origin", lane_patterns=["a.py"],
        claim=True, also_claim=[2, 3], claim_checker=checker,
    )
    label = lane_setup.compose_claim_label(payload, "auto-update path")
    assert label["state"] == "rendered"
    assert label["text"] == "Lane 1 x2  auto-update path"


# --------------------------------------------------------------- review findings (#1143 self-review)


def test_brief_without_subagent_type_is_refused_at_the_argparse_level():
    """Self-review finding (Explore + oss:auditor, #1143): --brief's own help
    text says 'required together with --subagent-type', but only the reverse
    direction was ever enforced -- a --brief given without --subagent-type
    was silently accepted and never read at all, which contradicts the
    documented contract and gives no diagnostic that the brief was never
    checked."""
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "lane_setup.py"),
            "999",
            "--claim",
            "--lane",
            "a.py",
            "--phrase",
            "x",
            "--brief",
            "/does/not/matter.md",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    assert result.returncode == 2
    assert "--brief requires --subagent-type" in result.stdout


def test_phrase_and_subagent_type_without_brief_is_still_refused():
    """Positive control paired with the test above: the pre-existing
    direction (--subagent-type requires --brief) must not regress."""
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "lane_setup.py"),
            "999",
            "--claim",
            "--lane",
            "a.py",
            "--phrase",
            "x",
            "--subagent-type",
            "oss:developer",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    assert result.returncode == 2
    assert "--subagent-type requires --brief" in result.stdout


def test_claim_with_phrase_alone_is_not_refused_at_the_argparse_level():
    """Positive control: --claim --phrase with neither --subagent-type nor
    --brief is a legitimate call (label-only render) and must not be caught
    by either new refusal."""
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "lane_setup.py"),
            "999",
            "--claim",
            "--lane",
            "a.py",
            "--phrase",
            "x",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    assert result.returncode != 2


def test_main_end_to_end_refuses_the_agent_call_on_a_structural_brief_finding(
    tmp_path, monkeypatch
):
    """Self-review finding (Explore, #1143): the new argparse validation and
    the final print/exit-code block in main() had zero coverage through
    main()/argv -- only the library functions were exercised directly. This
    drives the whole CLI path, including the exit-code override, for the
    refusal case."""
    import json
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    worktree_root = tmp_path / "worktrees"
    config = {
        "repo": "example/example",
        "default_branch": "main",
        "branch_pattern": "fix/{issue}",
        "test_command": "true",
        "docs_targets": [],
        "changelog_dir": "changelog.d",
    }
    (repo / lane_setup.CONFIG_NAME).write_text(json.dumps(config))

    monkeypatch.setattr(
        lane_setup,
        "resolve_base",
        lambda *a, **k: {
            "state": "resolved",
            "remote": "origin",
            "ref": "origin/main",
            "sha": "a" * 40,
            "detail": "",
        },
    )
    monkeypatch.setattr(lane_setup, "branch_occupancy", lambda *a, **k: (False, False))
    monkeypatch.setattr(
        lane_setup, "read_board", lambda repo: {"state": "ok", "lines": [], "detail": ""}
    )
    real_load = lane_setup.oss_config.load

    def fake_load(path):
        cfg, problems = real_load(path)
        if cfg is not None:
            cfg = dict(cfg)
            cfg["worktree_root"] = str(worktree_root)
        return cfg, problems

    monkeypatch.setattr(lane_setup.oss_config, "load", fake_load)
    monkeypatch.setattr(
        lane_setup.select_issues_claim_read,
        "check",
        lambda numbers, mode, repo=None: (
            [_row(n, claim_read.STATE_CLAIMED) for n in numbers]
            if mode == "claim"
            else [_row(n, claim_read.STATE_RELEASED) for n in numbers]
        ),
    )

    brief = tmp_path / "brief.md"
    brief.write_text("nothing useful here at all", encoding="utf-8")

    exit_code = lane_setup.main(
        [
            "1",
            "--repo",
            str(repo),
            "--claim",
            "--lane",
            "a.py",
            "--phrase",
            "auto-update path",
            "--subagent-type",
            "oss:developer",
            "--brief",
            str(brief),
        ]
    )
    assert exit_code == lane_setup.EXIT_COULD_NOT_RUN
