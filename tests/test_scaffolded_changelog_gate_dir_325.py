"""#325: `scaffolded_changelog_gate` used to answer `present` from the gate FILE'S
EXISTENCE alone, so a repo whose gate polices a differently-named directory got a
version proposal computed from the wrong fragments, with `problem=None` -- no refusal,
no third state, just the wrong answer.

This exercises the whole path `release_version._fragment_dir` walks, not just the
`oss_config` function underneath it: the reproduction from the issue itself, with a real
fragment in the named directory and a stale one sitting in `changelog.d/` where the old
code would have silently looked.

Every directory below is benign, and that is now a deliberate division rather than the
whole of the coverage. All three tests here answer "does the gate's own directory get
used", and none of them asks "is that directory one this repo would accept" -- which is
why a guarded value and an unguarded one were indistinguishable to the suite until #343.
The hostile half lives in `tests/test_gate_dir_validated_343.py`, which drives the same
two functions with values the `.oss.json` entrance refuses. Read the two together: this
file is the must-not-fire half of that one.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import release_version  # noqa: E402


def _scaffolded_repo(tmp_path, named_dir, real_fragment_dir):
    """A repo carrying `oss-changelog.yml` policing `named_dir`, `changelog_dir` nulled
    -- exactly the reachable state #325 describes: adopted through scaffold, then
    the config key nulled by ordinary contribution."""
    workflow = tmp_path / ".github" / "workflows" / "oss-changelog.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: oss changelog\n"
        "jobs:\n"
        "  fragment:\n"
        "    steps:\n"
        "      - run: python3 .oss/assemble_changelog.py --check --dir '{0}' "
        "--changelog CHANGELOG.md\n"
        "      - run: |\n"
        "          python3 .oss/assemble_changelog.py --check-links --dir '{0}' "
        "--changelog CHANGELOG.md || status=$?\n".format(named_dir),
        encoding="utf-8",
    )
    (tmp_path / real_fragment_dir).mkdir(parents=True)
    (tmp_path / real_fragment_dir / "1.added.md").write_text(
        "- a real fragment (#325).\n", encoding="utf-8"
    )
    return tmp_path


def test_a_nulled_changelog_dir_resolves_to_the_gates_named_directory(tmp_path):
    """The positive half: `changelog_dir: null`, a gate on disk policing `docs/frags`,
    and a fragment sitting there for real. `_fragment_dir` must recover `docs/frags`
    from the gate's own `--dir` line, not fall back to `changelog.d`."""
    root = _scaffolded_repo(tmp_path, "docs/frags", "docs/frags")

    directory, problem = release_version._fragment_dir(root, None, {"changelog_dir": None})

    assert problem is None
    assert directory == root / "docs" / "frags"


def test_it_does_not_silently_read_a_stale_default_directory_instead(tmp_path):
    """The negative twin, same tree: a STALE `changelog.d/` sits beside the real
    `docs/frags/` -- the exact shape the issue reproduced, `changelog_dir='docs/frags'
    -> dir=changelog.d problem=None`. The resolved directory must not be the stale one,
    and nothing about a fragment planted only in the stale directory may be counted."""
    root = _scaffolded_repo(tmp_path, "docs/frags", "docs/frags")
    stale = root / "changelog.d"
    stale.mkdir()
    (stale / "2.added.md").write_text("- a stale fragment nobody should count.\n", encoding="utf-8")

    directory, problem = release_version._fragment_dir(root, None, {"changelog_dir": None})

    assert problem is None
    assert directory != stale
    assert directory == root / "docs" / "frags"


def test_a_gate_with_no_dir_line_still_falls_back_to_the_default(tmp_path):
    """Positive control for the pair above: when the gate on disk names no directory
    at all (an old-style workflow), the default fallback is still correct and must not
    be disturbed by #325's fix."""
    workflow = tmp_path / ".github" / "workflows" / "oss-changelog.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: oss changelog\n", encoding="utf-8")
    (tmp_path / "changelog.d").mkdir()

    directory, problem = release_version._fragment_dir(tmp_path, None, {"changelog_dir": None})

    assert problem is None
    assert directory == tmp_path / "changelog.d"
