"""#966: the release trigger, computed instead of remembered.

The verdict has three states and the load-bearing one is `could-not-tell`. A
delta that could not be read is not "no trigger" -- but a tick that cannot read
one has nothing to report except that no release happened, which is
indistinguishable from a repository that had nothing to release. That is the
quietest failure this loop can have: it stops releasing and nothing says why.

Every test below builds a real git repository rather than mocking git. The
counting rule is a claim about what `git log` prints for a squash merge and for
a merge commit, and a fake that returns whatever the test wants would assert
the claim against itself.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import release_trigger  # noqa: E402


def _git(repo, *args, check=True):
    proc = subprocess.run(
        ("git", "-C", str(repo)) + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            "git {0} failed: {1}".format(
                " ".join(args), proc.stdout.decode("utf-8", "replace")
            )
        )
    return proc.stdout.decode("utf-8", "replace")


@pytest.fixture
def repo(tmp_path):
    """A repository with one tagged commit, so a range exists to count over."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("start\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "initial")
    _git(root, "tag", "v0.1.0")
    return root


def _commit(repo, subject, path="file.txt", body="x"):
    target = Path(repo, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body + subject, encoding="utf-8")
    _git(repo, "add", str(path))
    _git(repo, "commit", "-qm", subject)


def _config(merged_prs=None, soak_hours=None):
    return {"release": {"triggers": {"merged_prs": merged_prs, "soak_hours": soak_hours}}}


# ------------------------------------------------------- the counting rule


def test_a_squash_merge_is_counted_and_a_plain_commit_is_not(repo):
    """The bug the first implementation had, pinned. `git rev-list --merges`
    counted zero on a squash-merging repository -- a trigger that can never
    fire -- so the rule reads the subject instead."""
    _commit(repo, "fix(x): something (#12)")
    _commit(repo, "chore: tidy up")
    _commit(repo, "feat(y): another (#13)")
    row = release_trigger.merged_prs_condition(repo, 2)
    assert row["state"] == release_trigger.MET
    assert row["count"] == 2


def test_a_real_merge_commit_is_counted_too(repo):
    """The other merge method, exercised against a real merge rather than a
    fabricated subject: the rule has to hold for both, since a range can span
    a change of method."""
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "side work")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--no-ff", "-q", "side", "-m", "Merge pull request #7 from side")
    row = release_trigger.merged_prs_condition(repo, 1)
    assert row["state"] == release_trigger.MET
    assert row["count"] == 1


def test_below_threshold_reports_how_far_short(repo):
    _commit(repo, "fix: one (#1)")
    row = release_trigger.merged_prs_condition(repo, 5)
    assert row["state"] == release_trigger.NOT_MET
    assert row["short_by"] == 4
    assert row["threshold"] == 5


def test_no_declared_threshold_is_not_met_not_a_failure(repo):
    row = release_trigger.merged_prs_condition(repo, None)
    assert row["state"] == release_trigger.NOT_MET


def test_a_first_release_repository_does_not_fire_on_merged_prs(tmp_path):
    """No tag to count from. Counting everything would fire on a repository
    that has never released and may not be ready to."""
    root = tmp_path / "fresh"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "T")
    (root / "a.txt").write_text("a", encoding="utf-8")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-qm", "feat: first (#1)")
    row = release_trigger.merged_prs_condition(root, 1)
    assert row["state"] == release_trigger.NOT_MET
    assert "first release" in row["detail"]


def test_an_unreadable_delta_is_could_not_evaluate_not_not_met(tmp_path):
    """The whole point, at condition level: a range that could not be computed
    must not read as a threshold that was not reached."""
    row = release_trigger.merged_prs_condition(tmp_path / "not-a-repo", 1)
    assert row["state"] == release_trigger.COULD_NOT_EVALUATE


# ------------------------------------------------------------- the soak


def _fragment(repo, name, when=None):
    path = Path(repo, "changelog.d")
    path.mkdir(exist_ok=True)
    (path / name).write_text("- a change (#1)\n", encoding="utf-8")
    _git(repo, "add", "changelog.d/" + name)
    env_date = when.isoformat() if when else None
    if env_date:
        subprocess.run(
            ("git", "-C", str(repo), "commit", "-qm", "add " + name),
            env={
                "PATH": __import__("os").environ["PATH"],
                "HOME": str(repo),
                "GIT_AUTHOR_DATE": env_date,
                "GIT_COMMITTER_DATE": env_date,
                "GIT_AUTHOR_NAME": "T",
                "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "T",
                "GIT_COMMITTER_EMAIL": "t@example.invalid",
            },
            check=True,
            stdout=subprocess.DEVNULL,
        )
    else:
        _git(repo, "commit", "-qm", "add " + name)


def test_a_soaked_user_visible_fragment_fires(repo):
    old = datetime.now(timezone.utc) - timedelta(hours=72)
    _fragment(repo, "10.fixed.md", when=old)
    row = release_trigger.user_visible_soak_condition(
        repo, 48, Path(repo, "changelog.d")
    )
    # The row's own detail is in the failure message deliberately: this test
    # passed locally and failed on three CI legs with `could-not-evaluate`,
    # and the assertion as first written printed only the state -- so the
    # reason the fragment could not be dated had to be guessed at from a diff
    # of two words. An assertion about a three-state answer should print the
    # state's own reason when it fails.
    assert row["state"] == release_trigger.MET, row
    assert row["fragment"] == "10.fixed.md"
    assert row["soaked_hours"] >= 48


def test_a_fresh_fragment_does_not_fire_and_says_how_long_is_left(repo):
    _fragment(repo, "11.added.md")
    row = release_trigger.user_visible_soak_condition(
        repo, 48, Path(repo, "changelog.d")
    )
    assert row["state"] == release_trigger.NOT_MET, row
    assert row["short_by_hours"] > 47


def test_the_oldest_qualifying_fragment_sets_the_clock(repo):
    """Keying on the newest would reset the clock every time an unrelated fix
    landed, and a repository shipping steadily would never release."""
    _fragment(repo, "12.fixed.md", when=datetime.now(timezone.utc) - timedelta(hours=99))
    _fragment(repo, "13.added.md")
    row = release_trigger.user_visible_soak_condition(
        repo, 48, Path(repo, "changelog.d")
    )
    assert row["state"] == release_trigger.MET, row
    assert row["fragment"] == "12.fixed.md"


def test_a_missing_fragment_directory_is_could_not_evaluate(repo):
    """Not `not-met`: nobody looked. An absent directory on a repository that
    uses fragments is a broken checkout, not a quiet week."""
    row = release_trigger.user_visible_soak_condition(
        repo, 48, Path(repo, "no-such-dir")
    )
    assert row["state"] == release_trigger.COULD_NOT_EVALUATE


def test_an_empty_fragment_directory_is_not_met(repo):
    """The must-not-fire half of the check above: an empty directory is a real,
    established absence and must not be reported as an unreadable one."""
    Path(repo, "changelog.d").mkdir()
    row = release_trigger.user_visible_soak_condition(
        repo, 48, Path(repo, "changelog.d")
    )
    assert row["state"] == release_trigger.NOT_MET


def test_an_uncommitted_fragment_cannot_have_soaked(repo):
    """It has not landed, so it has not soaked -- and it is not a zero-hour
    soak either, which would make every uncommitted fragment fire the moment
    the threshold was small."""
    Path(repo, "changelog.d").mkdir()
    Path(repo, "changelog.d", "14.fixed.md").write_text("- x (#14)\n", encoding="utf-8")
    row = release_trigger.user_visible_soak_condition(
        repo, 48, Path(repo, "changelog.d")
    )
    assert row["state"] == release_trigger.COULD_NOT_EVALUATE
    assert "14.fixed.md" in row["detail"]


def test_a_chore_shaped_fragment_is_not_user_visible(repo):
    """The rule #966 records as a decision: the section name is what says
    whether a change is user-visible."""
    _fragment(repo, "15.chore.md", when=datetime.now(timezone.utc) - timedelta(hours=99))
    row = release_trigger.user_visible_soak_condition(
        repo, 48, Path(repo, "changelog.d")
    )
    assert row["state"] == release_trigger.NOT_MET


# --------------------------------------------------- the stamp parser


def test_a_utc_z_stamp_parses_on_every_supported_interpreter():
    """The bug three CI legs found and no local run could: git writes `%cI` as
    `...Z` when the committer timezone is UTC -- which a runner's is and a
    developer laptop's usually is not -- and `datetime.fromisoformat` rejects
    that suffix before Python 3.11.

    Asserted on the parser directly rather than through a repository, because
    a test that commits and reads back only reproduces this on a machine whose
    clock is already UTC. Pinning the string is what makes it fire on every
    interpreter and every runner timezone.
    """
    when = release_trigger._parse_stamp("2026-08-31T22:31:29Z")
    assert when is not None
    assert when.utcoffset() == timedelta(0)


def test_an_offset_stamp_still_parses():
    """The must-not-fire half: normalising the `Z` must not break the spelling
    that already worked, which is the one every local run produces."""
    when = release_trigger._parse_stamp("2026-08-31T22:31:29+02:00")
    assert when is not None
    assert when.utcoffset() == timedelta(hours=2)


def test_an_unparseable_stamp_is_none_not_an_exception():
    """`None` is what the caller turns into `could-not-evaluate`; a raise here
    would take the whole verdict down instead of one condition."""
    assert release_trigger._parse_stamp("not a date") is None
    assert release_trigger._parse_stamp("") is None


# ------------------------------------------------------ blocking findings


def test_no_findings_passed_is_not_supplied_and_never_not_met():
    """A tick that ran no audit must not be able to report that no blocking
    finding exists."""
    row = release_trigger.blocking_findings_condition(None)
    assert row["state"] == release_trigger.NOT_SUPPLIED


def test_an_audit_that_found_none_is_not_met():
    """The other side of the same distinction, which is the reason
    `not-supplied` has to exist at all."""
    row = release_trigger.blocking_findings_condition([])
    assert row["state"] == release_trigger.NOT_MET


def test_a_blocking_finding_fires():
    row = release_trigger.blocking_findings_condition(["destroys: rm -rf on an argument"])
    assert row["state"] == release_trigger.MET


# ----------------------------------------------------------- the verdict


def test_could_not_tell_wins_over_not_fired(repo):
    """A condition that could not be evaluated might have fired, so the verdict
    cannot be `not-fired`."""
    payload = release_trigger.compute(
        repo,
        config=_config(merged_prs=5, soak_hours=48),
        findings=[],
        fragment_dir=Path(repo, "no-such-dir"),
    )
    assert payload["state"] == release_trigger.STATE_COULD_NOT_TELL
    assert payload["unevaluated"] == ["user_visible_soak"]


def test_a_condition_that_actually_fired_still_wins_over_a_dark_one(repo):
    """`whichever comes first` -- one `met` settles it, and the unread
    condition is still named in the payload rather than dropped."""
    payload = release_trigger.compute(
        repo,
        config=_config(merged_prs=5, soak_hours=48),
        findings=["discloses: token in a log line"],
        fragment_dir=Path(repo, "no-such-dir"),
    )
    assert payload["state"] == release_trigger.STATE_FIRED
    assert payload["fired"] == ["blocking_finding"]
    assert payload["unevaluated"] == ["user_visible_soak"]
    assert "went unread" in release_trigger.receipt(payload)


def test_everything_evaluated_and_nothing_met_is_not_fired(repo):
    Path(repo, "changelog.d").mkdir()
    payload = release_trigger.compute(
        repo, config=_config(merged_prs=5, soak_hours=48), findings=[]
    )
    assert payload["state"] == release_trigger.STATE_NOT_FIRED


def test_the_receipt_prints_the_threshold_even_when_it_did_not_fire(repo):
    """The spine's own sentence: a threshold nobody can see arriving is
    indistinguishable from deciding on a whim."""
    Path(repo, "changelog.d").mkdir()
    payload = release_trigger.compute(
        repo, config=_config(merged_prs=5, soak_hours=48), findings=[]
    )
    text = release_trigger.receipt(payload)
    assert "threshold=5" in text and "threshold_hours=48" in text


# --------------------------------------------------------- the exit code


def test_exit_code_is_non_zero_for_could_not_tell(repo, capsys):
    """A caller reading only the code must not proceed as though the answer
    were "no release today"."""
    code = release_trigger.main(["--repo", str(repo), "--config", str(repo / "nope.json")])
    assert code == 1
    assert "could not tell" in capsys.readouterr().out


def test_exit_code_is_zero_for_not_fired(repo, tmp_path, capsys):
    config = tmp_path / "oss.json"
    config.write_text('{"release": {"triggers": {"merged_prs": 5, "soak_hours": 48}}}', encoding="utf-8")
    Path(repo, "changelog.d").mkdir()
    code = release_trigger.main(
        ["--repo", str(repo), "--config", str(config), "--no-blocking-findings"]
    )
    assert code == 0
    assert "not fired" in capsys.readouterr().out


def test_omitting_both_finding_flags_is_not_supplied(repo, tmp_path, capsys):
    """The CLI must not turn "you said nothing" into "an audit found nothing"."""
    config = tmp_path / "oss.json"
    config.write_text('{"release": {"triggers": {"merged_prs": 5, "soak_hours": 48}}}', encoding="utf-8")
    Path(repo, "changelog.d").mkdir()
    release_trigger.main(["--repo", str(repo), "--config", str(config)])
    assert "not-supplied" in capsys.readouterr().out
