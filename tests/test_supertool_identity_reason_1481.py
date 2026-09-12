"""#1481: `_supertool_tree_identity_confirmed` (added by #1459) returned the
same bare `False` for a genuinely confirmed non-match (this tree's origin
names a different repository) as it did for every inconclusive input -- no
installed `supertool` dependency in the plugin cache, `git` off PATH, no
readable `origin`, an unrecognised remote form. `_origin_slug` already
computes a reason string for the inconclusive cases and the function
discarded it (`slug, _reason = ...`).

Fix: thread that reason through so a caller (`supertool_invocation`) can
render `own-tree declined: <reason>` for the inconclusive case, distinct
from the plain `not a supertool checkout` a confirmed non-match still
gets -- the same defect class this repo is named after, one function down
from the fix (#1459) that introduced it.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import doctor  # noqa: E402


def test_no_installed_dependency_is_reported_as_could_not_confirm_not_a_bare_mismatch(
    tmp_path,
):
    """#1481's own repro: no `supertool` entry in the installed dependency
    repos at all (an empty dict, not `None` -- forcing the real plugin-cache
    lookup would make this test depend on the machine it runs on) must
    render distinctly from a confirmed non-match, not fold into the same
    plain 'not a supertool checkout' text."""
    (tmp_path / ".supertool.json").write_text("{}")
    (tmp_path / "supertool.py").write_text("# stand-in core\n")

    argv, detail = doctor.supertool_invocation(tmp_path, dependency_repos={})
    assert argv == ["supertool"], (argv, detail)
    assert "own-tree declined:" in detail, detail
    assert "no installed supertool dependency" in detail, detail


def test_confirmed_non_match_still_reads_as_plain_not_a_supertool_checkout(tmp_path):
    """Positive control / regression guard: a genuinely confirmed non-match
    (origin resolves and simply names a different repository) is NOT an
    inconclusive input, and must keep reading as the plain, pre-existing
    'not a supertool checkout' text -- the #1459 test this pairs with."""

    def _fake_git_remote(argv, **kwargs):
        class _Result:
            returncode = 0
            stdout = "https://github.com/Digital-Process-Tools/claude-oss.git\n"
            stderr = ""

        return _Result()

    (tmp_path / ".supertool.json").write_text("{}")
    (tmp_path / "supertool.py").write_text("# a stray file\n")

    argv, detail = doctor.supertool_invocation(
        tmp_path,
        dependency_repos={
            "supertool": "https://github.com/Digital-Process-Tools/claude-supertool"
        },
        run=_fake_git_remote,
    )
    assert argv == ["supertool"], (argv, detail)
    assert detail == "not a supertool checkout", detail
    assert "declined" not in detail, detail


def test_genuine_own_tree_match_still_resolves_own_tree_correctly(tmp_path):
    """Positive control: the ordinary confirmed-match case (#1459's own
    scenario) must still resolve to the tree's own core, unaffected by
    threading the decline reason through the inconclusive branch."""

    def _fake_git_remote(argv, **kwargs):
        class _Result:
            returncode = 0
            stdout = "https://github.com/Digital-Process-Tools/claude-supertool.git\n"
            stderr = ""

        return _Result()

    (tmp_path / ".supertool.json").write_text("{}")
    (tmp_path / "supertool.py").write_text("# stand-in core\n")

    argv, detail = doctor.supertool_invocation(
        tmp_path,
        dependency_repos={
            "supertool": "https://github.com/Digital-Process-Tools/claude-supertool"
        },
        run=_fake_git_remote,
    )
    assert argv[0] == sys.executable, (argv, detail)
    assert argv[1].endswith("supertool.py"), (argv, detail)
    assert "own-tree" in detail
    assert "declined" not in detail


def test_identity_confirmed_helper_returns_a_reason_tuple(tmp_path):
    """The unit-level fix: `_supertool_tree_identity_confirmed` itself now
    returns `(confirmed, reason)`, `reason` being `None` on a confirmed
    answer (True or a real False) and a string on every inconclusive input
    -- the function `_origin_slug` already computed a reason for and this
    one used to discard (`slug, _reason = ...`)."""
    confirmed, reason = doctor._supertool_tree_identity_confirmed(
        tmp_path, dependency_repos={}
    )
    assert confirmed is False
    assert reason, "an inconclusive input must carry a stated reason, not None"
