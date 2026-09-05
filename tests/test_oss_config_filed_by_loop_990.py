"""#990: `/oss:setup` (`oss_config.build()`) must not leave `labels.filed_by_loop`
unemitted. `select_issues_rank.rank` (#798) refuses to rank anything when the key is
undeclared, and on every repository but this one -- where it was hand-added -- the key
never arrives, because `build()` never wrote it. Never invents a name not seen in the
probe (`commands/setup.md:101`): a match against the labels the probe already
collected, or an emitted `null` with the same visible-but-undeclared shape
`changelog_untagged` already uses, never a guessed default.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402

from test_oss_config import _probe  # noqa: E402


def test_a_loop_filed_label_in_the_probe_is_emitted():
    config = oss_config.build(_probe(labels=["priority-high", "filed-by-loop"]))
    assert config["labels"]["filed_by_loop"] == "filed-by-loop"


def test_the_underscore_spelling_is_recognised_too():
    config = oss_config.build(_probe(labels=["priority-high", "filed_by_loop"]))
    assert config["labels"]["filed_by_loop"] == "filed_by_loop"


def test_no_matching_label_emits_null_visibly_rather_than_omitting_the_key():
    config = oss_config.build(_probe(labels=["priority-high", "bug"]))
    assert "filed_by_loop" in config["labels"]
    assert config["labels"]["filed_by_loop"] is None


def test_a_bare_repo_with_no_labels_at_all_also_gets_the_visible_null():
    """Positive control for the null branch: nothing in the probe should ever make
    build() skip emitting the key, empty label list included.
    """
    config = oss_config.build(_probe(labels=[]))
    assert config["labels"] == {"priority": [], "lanes": [], "filed_by_loop": None}


def test_build_never_invents_a_spelling_not_in_the_probe():
    """Negative control: a probe that carries nothing resembling the loop-filed
    convention must never produce a guessed label name.
    """
    config = oss_config.build(
        _probe(labels=["priority-high", "lane-hooks", "bug", "wontfix"])
    )
    assert config["labels"]["filed_by_loop"] is None


def test_the_emitted_key_still_validates_clean():
    config = oss_config.build(_probe(labels=["priority-high", "filed-by-loop"]))
    assert oss_config.validate(config) == []
    null_config = oss_config.build(_probe(labels=["priority-high"]))
    assert oss_config.validate(null_config) == []


def test_null_filed_by_loop_prints_a_note_naming_the_select_issues_rank_consequence(capsys):
    config = oss_config.build(_probe(labels=["priority-high"]))
    oss_config._report_probe_notes(_probe(labels=["priority-high"]), config)
    printed = capsys.readouterr().err
    note_line = [line for line in printed.splitlines() if "filed_by_loop" in line]
    assert note_line, "no NOTE at all about the undeclared key: {!r}".format(printed)
    assert "select_issues_rank" in note_line[0]
    assert "could-not-rank" in note_line[0] or "cannot rank" in note_line[0]


def test_a_declared_filed_by_loop_prints_no_note(capsys):
    """Positive control for the note above: a repo that DID get the label must not
    see the same warning -- a note that fires regardless would be noise nobody could
    trust.
    """
    probe = _probe(labels=["priority-high", "filed-by-loop"])
    config = oss_config.build(probe)
    oss_config._report_probe_notes(probe, config)
    printed = capsys.readouterr().err
    assert "filed_by_loop" not in printed
