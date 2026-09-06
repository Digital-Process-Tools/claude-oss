"""#1145 auditor round: a `gh api graphql` response can return exit 0 with a
valid, well-shaped envelope whose `data.repository.issues.nodes` is
`null` -- a GraphQL partial-error shape, not the missing-key shape the
existing mis-shaped-response test covers. `_fetch_board` must answer
`could-not-fetch` for this too, never crash with an uncaught `TypeError`.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import select_issues  # noqa: E402


def test_a_null_nodes_field_is_could_not_fetch_never_a_crash():
    def run(args, timeout=90):
        return (
            True,
            '{"data": {"repository": {"issues": {"pageInfo": {"hasNextPage": false}, '
            '"nodes": null}}}}',
            None,
        )

    result = select_issues._fetch_board("Digital-Process-Tools/claude-oss", run=run)
    assert result["state"] == "could-not-fetch"
    assert result["issues"] == []
