"""#699: `assemble_changelog.py --check --check-links` silently ran only the
links audit -- the mode dispatch is a chain of `if`/`return` and `check_links`
returned before `check` was ever reached, so a malformed fragment sat in the
directory while the run printed `ok` and exit 0. That combination is exactly
what `.claude/jit-context/paths/01-oss/changelog-fragments.md`'s own "Check
before pushing" block told a reader to run, so the documented pre-push command
was the one invocation that did not check.

Fixed by refusing the combination outright, the same shape as the existing
`--untagged`-outside-`--check-links` refusal a few lines below it in the same
function. This file pins the refusal and pairs it with a must-fire control:
each flag alone must keep auditing exactly what it always audited.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import assemble_changelog as ac  # noqa: E402


def _changelog_with_one_release(tmp_path, version="0.6.1"):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "## [{v}] - 2026-01-01\n\n"
        "### Fixed\n\n"
        "- something.\n\n"
        "[Unreleased]: https://example.invalid/compare/v{v}...HEAD\n"
        "[{v}]: https://example.invalid/releases/tag/v{v}\n".format(v=version),
        encoding="utf-8",
    )
    return path


def _fragment_dir_with_one_bad_fragment(tmp_path):
    d = tmp_path / "changelog.d"
    d.mkdir()
    (d / "999.notasection.md").write_text(
        "- an entry under an unknown section\n", encoding="utf-8"
    )
    return d


def test_check_and_check_links_together_is_refused(tmp_path, capsys):
    changelog = _changelog_with_one_release(tmp_path)
    directory = _fragment_dir_with_one_bad_fragment(tmp_path)

    code = ac.main(
        [
            "--check",
            "--check-links",
            "--dir",
            str(directory),
            "--changelog",
            str(changelog),
        ]
    )

    assert code == ac.REFUSED
    out = capsys.readouterr().out
    assert "refused" in out
    assert "--check" in out and "--check-links" in out


def test_check_alone_still_catches_the_bad_fragment(tmp_path, capsys):
    """Must-fire pair: the fragment audit itself is unaffected by the refusal
    above, and still finds the malformed fragment the combined call used to miss.
    """
    directory = _fragment_dir_with_one_bad_fragment(tmp_path)

    code = ac.main(["--check", "--dir", str(directory)])

    assert code == ac.REFUSED
    out = capsys.readouterr().out
    assert "notasection" in out or "999" in out


def test_check_links_alone_still_audits_the_table(tmp_path, capsys):
    """Must-fire pair: the links audit on its own is unaffected."""
    changelog = _changelog_with_one_release(tmp_path)

    code = ac.main(["--check-links", "--changelog", str(changelog)])

    assert code == ac.OK
    out = capsys.readouterr().out
    assert "assemble" in out
