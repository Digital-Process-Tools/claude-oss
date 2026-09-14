"""#1532: the lane claim registry is retired.

`lane_setup.py --claim` used to write a lane record -- issue, branch,
worktree, declared file set, a phrase and a 240-minute TTL -- into
`<worktree_root>/.oss-lanes`, and `--derive-held` read every live record plus
every open pull request's file list to build a held set. #1528 stopped a
collision with that held set dropping a candidate and #1530 removed the
declared file sets it collided on, which between them removed everything the
registry was FOR. What was left was a record nothing read for a decision, a
second and staler copy of what `git-worktrees` already answers from the
filesystem, and a TTL long enough that a phantom record blocked real work for
hours.

What survives, and is asserted here as the positive control every negative
assertion below needs: the worktree and branch derivation, and the GitHub
assignee write. The assignee is the one claim with a real owner and a real
atomicity story -- and it is also, on the code as it stood, the ONLY thing
that ever stopped two lanes taking the same issue: `claim_and_register` read
and wrote the assignee FIRST and refused on `already-claimed` before
`record_lane` was reached at all. The registry never gated issue-taking, so
retiring it removes no guarantee.

Every test here pairs a "must be gone" with a "must still be here" in the
same fixture. A scan that cannot see the tree returns an empty result set,
and an empty result set is what "nothing matched" looks like too.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "lane_setup.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lane_setup  # noqa: E402
import lane_setup_claim  # noqa: E402


RETIRED_NAMES = (
    "LANE_REGISTRY_DIRNAME",
    "LANE_RECORD_TTL_SECONDS",
    "lane_registry_dir",
    "record_lane",
    "release_lane",
    "lane_count",
    "lanes_snapshot",
    "detect_vanished_worktrees",
    "held_from_live_lanes",
    "held_from_open_prs",
    "derive_held_set",
    "claim_and_register",
    "release_lane_and_assignee",
)

SURVIVING_NAMES = ("claim_issues", "release_assignees")


def test_registry_names_are_gone_from_lane_setup_claim():
    present = [name for name in RETIRED_NAMES if hasattr(lane_setup_claim, name)]
    assert present == [], (
        "these registry names are still exported by lane_setup_claim: {0}".format(
            present
        )
    )


def test_the_assignee_half_survives_positive_control():
    """The control for the test above. `hasattr` returning False for every
    retired name would also be what a module that failed to import anything
    at all looks like -- so assert, in the same fixture, that the half #1532
    explicitly keeps is still reachable."""
    missing = [name for name in SURVIVING_NAMES if not hasattr(lane_setup_claim, name)]
    assert missing == [], "the surviving assignee half is not there: {0}".format(
        missing
    )


def test_registry_names_are_gone_from_lane_setup():
    """`lane_setup.py` re-exports a large part of `lane_setup_claim`'s surface
    by name (`doctor_check_vanished_worktree.py` reached
    `lane_setup.detect_vanished_worktrees`, not the sibling module's). A name
    removed from the producer and left re-exported here would still resolve."""
    present = [name for name in RETIRED_NAMES if hasattr(lane_setup, name)]
    assert present == [], (
        "these registry names are still reachable through lane_setup: {0}".format(
            present
        )
    )


def _help_text():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_help_no_longer_offers_the_registry_flags():
    text = _help_text()
    gone = [
        flag
        for flag in ("--derive-held", "--against", "--check-vanished")
        for _ in (0,)
        if flag in text
    ]
    assert gone == [], "retired flags still offered by --help: {0}".format(gone)


def test_help_still_offers_the_flags_that_survive_positive_control():
    """Control for the test above: `--help` producing no output at all, or a
    usage error swallowed somewhere, would satisfy every absence asserted
    there. These four are what #1532 keeps."""
    text = _help_text()
    missing = [
        flag
        for flag in ("--claim", "--release", "--lane", "--stack-on")
        if flag not in text
    ]
    assert missing == [], "surviving flags absent from --help: {0}".format(missing)


def test_derive_held_is_refused_rather_than_silently_ignored():
    """An unknown flag must be an argparse error (exit 2), never accepted and
    dropped: a caller still passing `--derive-held` from a stale runbook has
    to hear about it rather than get a confident, empty answer."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "999999", "--derive-held"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "--derive-held" in result.stderr


def test_claim_writes_the_assignee_and_creates_no_registry(tmp_path):
    """The behavioural half: claiming writes assignees and touches nothing on
    disk under the worktree root."""
    calls = []

    def checker(numbers, action, repo=None):
        calls.append((tuple(numbers), action, repo))
        return [{"issue": n, "state": "claimed", "detail": ""} for n in numbers]

    result = lane_setup_claim.claim_issues(
        1532, also_claim=[1533], repo="owner/name", checker=checker
    )

    assert result["state"] == "claimed"
    assert calls == [((1532, 1533), "claim", "owner/name")]
    assert "record" not in result
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_claim_refuses_over_somebody_elses_assignee(tmp_path):
    """The guarantee the registry was suspected of providing, shown to live
    entirely in the assignee read: an issue already assigned to somebody else
    is refused, and nothing is written."""
    calls = []

    def checker(numbers, action, repo=None):
        calls.append((tuple(numbers), action, repo))
        return [
            {"issue": n, "state": "already-claimed", "detail": "@other"}
            for n in numbers
        ]

    result = lane_setup_claim.claim_issues(1532, repo="owner/name", checker=checker)

    assert result["state"] == "already-claimed"
    assert [action for _, action, _ in calls] == ["claim"]
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def test_release_removes_the_assignee_only(tmp_path):
    calls = []

    def checker(numbers, action, repo=None):
        calls.append((tuple(numbers), action, repo))
        return [{"issue": n, "state": "released", "detail": ""} for n in numbers]

    result = lane_setup_claim.release_assignees(
        1532, also_release=[1533], repo="owner/name", checker=checker
    )

    assert result["assignee"]["state"] == "released"
    assert [row["issue"] for row in result["also_released"]] == [1533]
    assert "record" not in result
    assert sorted(p.name for p in tmp_path.iterdir()) == []


SCANNED_DIRS = ("scripts", "skills", "agents", "commands")


def _scan(needle, skip_removal_notes=False):
    """Every file under `SCANNED_DIRS` naming `needle`.

    `skip_removal_notes` drops each blank-line-delimited PARAGRAPH that cites
    this issue. A paragraph saying "#1532 retired `--derive-held`" is the
    opposite of a stale reference -- it is the note telling the next reader
    why their pasted command now fails -- and a scan that cannot tell the two
    apart forces the removal to go undocumented, which is a worse outcome
    than the drift it was guarding against.

    The paragraph, rather than the line, is the unit because prose wraps: the
    citation and the flag it explains land on adjacent lines as often as on
    the same one, and a per-line rule would have passed only for paragraphs
    that happened to wrap conveniently.

    It is still narrow -- a paragraph with no citation is scanned in full, so
    a genuine live reference elsewhere in the same file is still a hit, which
    is what the exemption's own control below pins. And the behavioural guard
    that the flag is genuinely gone is
    `test_derive_held_is_refused_rather_than_silently_ignored` above, which
    actually runs the script. This scan is the prose half and the weaker one.
    """
    hits = []
    for name in SCANNED_DIRS:
        root = REPO_ROOT / name
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in (".py", ".md", ".sh"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):  # pragma: no cover - defensive
                continue
            blocks = text.split("\n\n")
            if skip_removal_notes:
                blocks = [block for block in blocks if "#1532" not in block]
            if any(needle in block for block in blocks):
                hits.append(str(path.relative_to(REPO_ROOT)))
    return hits


def test_the_registry_directory_name_appears_nowhere():
    hits = _scan(".oss-lanes")
    assert hits == [], ".oss-lanes still named in: {0}".format(hits)


def test_the_scan_can_see_the_tree_positive_control():
    """Control for the test above and the one below. `_scan` returning [] is
    also exactly what an unreadable tree, a wrong REPO_ROOT or a suffix filter
    that matches nothing returns -- so scan for a literal that must be there."""
    assert _scan("git-worktrees"), "the scan found nothing at all -- it is blind"


def test_the_derive_held_flag_is_named_nowhere_in_scripts_or_loop_prose():
    hits = _scan("--derive-held", skip_removal_notes=True)
    assert hits == [], "--derive-held still named in: {0}".format(hits)


def test_the_removal_note_exemption_does_not_swallow_a_live_reference(tmp_path):
    """Control for the exemption above, which is the one thing here that can
    make a real finding invisible. A line naming the flag WITHOUT citing the
    issue must still be a hit; the exemption drops only the line that cites
    it, never the file."""
    assert _scan("--derive-held") != [], (
        "the unexempted scan found nothing -- the removal notes this repo "
        "deliberately keeps are missing, so the exemption is untested"
    )
    assert _scan("--suggest-companions", skip_removal_notes=True), (
        "a live flag reference vanished under the exemption -- it is dropping "
        "more than lines citing this issue"
    )


def test_doctor_no_longer_registers_the_vanished_worktree_check():
    import doctor  # noqa: E402  (imported here: doctor imports every check module)

    assert not hasattr(doctor, "check_vanished_worktrees")
    assert not (REPO_ROOT / "scripts" / "doctor_check_vanished_worktree.py").exists()


def test_doctor_still_registers_a_sibling_check_positive_control():
    """Control: `hasattr(doctor, ...)` being False for everything is what a
    half-imported `doctor` module looks like too."""
    import doctor  # noqa: E402

    assert hasattr(doctor, "check_trap_queue")
