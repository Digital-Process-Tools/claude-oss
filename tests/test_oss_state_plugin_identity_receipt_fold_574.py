"""#574: the write-side `RECORDED plugin identity:` receipt bypassed `_receipt_line`,
so a newline in `--plugin-identity` forges a second receipt line at column 0 while only
one record is made.

Every sibling receipt (`RECORDED`/`NOT RECORDED`/`TREND`) routes through a renderer that
calls `_receipt_line` -- `intake_line`, `lane_models_line`, `cohort_freeze_line`,
`wait_line`. The write-side plugin-identity receipt at the old line 2163 did not: it
formatted `args.plugin_identity` straight into the `_say` call. The reading path
(`--check-plugin-identity`, via `plugin_identity_line`) already folded correctly and is
the positive control cited in the issue.

Paired in the same fixture with a clean value that must still produce its own line, so
"no second line" cannot pass on a renderer that printed nothing.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_state  # noqa: E402

STAMP = "2026-08-25T00:00:00Z"
FORGED = "0.14.0 abc\nRECORDED plugin identity: 9.9.9 forged"


def test_clean_plugin_identity_value_produces_its_own_receipt_line(tmp_path, capsys):
    """Positive control: a clean value must still be recorded and reported."""
    path = tmp_path / "state.json"
    rc = oss_state._main(
        [
            str(path),
            "--decision",
            "a tick",
            "--at",
            STAMP,
            "--plugin-identity",
            "0.14.0 clean",
        ]
    )
    assert rc == 0
    err = capsys.readouterr().err
    lines = [l for l in err.splitlines() if l.startswith("RECORDED plugin identity:")]
    assert len(lines) == 1
    assert "0.14.0 clean" in lines[0]


def test_a_newline_in_plugin_identity_cannot_forge_a_second_receipt_line(
    tmp_path, capsys
):
    path = tmp_path / "state.json"
    rc = oss_state._main(
        [str(path), "--decision", "a tick", "--at", STAMP, "--plugin-identity", FORGED]
    )
    assert rc == 0
    err = capsys.readouterr().err
    lines = [l for l in err.splitlines() if l.startswith("RECORDED plugin identity:")]
    # Exactly one record was made; the receipt must claim exactly one.
    assert len(lines) == 1
    # The value is still reported, folded -- not dropped. Everything from the
    # newline onward is still readable text (only the newline itself became `?`),
    # which is the point: the fold prevents a second receipt line, not disclosure.
    assert "?" in lines[0]
    assert (
        "RECORDED plugin identity: 0.14.0 abc?RECORDED plugin identity: 9.9.9 forged"
        == lines[0]
    )
