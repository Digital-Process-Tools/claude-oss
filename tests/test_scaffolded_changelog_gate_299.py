"""`changelog_dir: null` is ambiguous, and #299 is the cost of not telling the two
readings apart: `/oss:scaffold --apply` creates `changelog.d/` and its own gating
workflow WITHOUT writing `changelog_dir` into `.oss.json` (`commands/scaffold.md:210-213`
says so, deliberately -- the fallback is applied by both the command and the generated
workflow, so the two cannot drift). `release_version.py` and `commands/changelog.md`
both read `changelog_dir` and both, before this, treated null as "never adopted
fragments" -- which was true for a hand-maintained repo and false for one scaffold had
just finished setting up, with a required CI leg already gating on the fragments it
refused to find.

`oss_config.scaffolded_changelog_gate` is the shared answer both readers now consult:
does THIS repo's own scaffolded workflow exist, at the one path a forge will read it
from. Three states, and the third -- `unknown` -- must never render as either of the
other two: a wrong `absent` costs a caller nothing beyond the refusal it already gave
before #299; a wrong `present` would pick a directory nobody named, which is precisely
what `NO_DIRECTORY` in `release_version.py` exists to refuse.
"""

import contextlib
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402
import scaffold  # noqa: E402


def test_the_fallback_directory_is_one_constant_shared_by_both_modules():
    """Not just equal by coincidence -- `scaffold.py` reads its own default off
    `oss_config`, so a second literal cannot silently drift from the first (#299)."""
    assert scaffold.DEFAULT_FRAGMENTS_DIR is oss_config.DEFAULT_FRAGMENTS_DIR
    assert oss_config.DEFAULT_FRAGMENTS_DIR == "changelog.d"


def test_no_workflow_at_all_is_absent(tmp_path):
    state, detail = oss_config.scaffolded_changelog_gate(tmp_path)
    assert state == "absent"
    assert detail == ""


def test_the_scaffolded_workflow_present_is_recognised(tmp_path):
    """The positive control this whole function exists for: the exact path
    `scaffold.py` writes `.github/workflows/oss-changelog.yml` to."""
    workflow = tmp_path / ".github" / "workflows" / "oss-changelog.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: oss changelog\n", encoding="utf-8")

    state, detail = oss_config.scaffolded_changelog_gate(tmp_path)

    assert state == "present"
    assert detail == ""


def test_a_differently_named_workflow_is_not_mistaken_for_the_scaffolded_one(tmp_path):
    """The negative twin of the test above, same tree shape: some OTHER workflow at a
    different name must not be read as our fallback gate -- that would be exactly the
    silent-wrong-directory failure `NO_DIRECTORY` exists to refuse."""
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: ci\n", encoding="utf-8")

    state, detail = oss_config.scaffolded_changelog_gate(tmp_path)

    assert state == "absent"


# --------------------------------------- a tree this process cannot fully read (#124)


@contextlib.contextmanager
def _denied(path):
    """Deny reads on ``path``, or skip saying what went untested -- measured, not
    assumed: root ignores the mode bit, some filesystems ignore it, and Windows'
    ``os.chmod`` on a directory only toggles a read-only attribute that does not stop a
    listing. Same idiom as ``tests/test_scaffold.py``'s ``_denied`` (#124)."""
    os.chmod(str(path), 0o000)
    try:
        try:
            os.listdir(str(path))
        except PermissionError:
            pass
        except OSError as exc:
            pytest.skip(
                "chmod 000 on {} produced {} (errno {}) rather than a denied listing, "
                "so the unreadable arm could not be set up and went untested".format(
                    path, type(exc).__name__, exc.errno
                )
            )
        else:
            pytest.skip(
                "chmod 000 on {} still allows listing it -- running as root, or a "
                "filesystem/platform that does not enforce the mode bit. The unreadable "
                "arm went untested; the readable and absent arms still ran "
                "elsewhere.".format(path)
            )
        yield
    finally:
        os.chmod(str(path), 0o755)


def test_an_unreadable_workflows_directory_is_unknown_not_absent(tmp_path):
    """The third state, exercised: a workflow that could genuinely be there, sitting
    behind a directory this process cannot enter, must not be reported the same as a
    directory confirmed to hold nothing (#299) -- the exact defect class this repo's
    own CLAUDE.md is named after, one function down from where it usually bites."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "oss-changelog.yml").write_text("name: oss changelog\n", encoding="utf-8")

    with _denied(workflows):
        state, detail = oss_config.scaffolded_changelog_gate(tmp_path)
        assert state == "unknown"
        assert detail

    # Positive control, same tree, mode bit restored by the context manager.
    state, detail = oss_config.scaffolded_changelog_gate(tmp_path)
    assert state == "present"
