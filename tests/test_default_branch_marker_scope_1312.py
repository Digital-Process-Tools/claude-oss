"""#1312: the marker glued onto the repo name speaks only about the
`.oss.json`-declared default branch -- never about whichever branch or
worktree the statusline happens to be rendered from.

That was already this code's actual, structural behaviour: `_default_branch_marker`
(#856) takes no branch argument at all, only the already-computed `state`; the
render-time call passes `facts.get("default_branch_state")`, a field `gather()`
folds from the cache rather than from anything about the current checkout; and
`refresh()` -- the only place that ever asks the forge -- calls
`_gh_default_branch_state(repo, config.get("default_branch"))`, reading the
declared default out of `.oss.json`, never `branch_name(root)` (the function
that answers the OTHER, legitimately-current-branch field a few lines below it
in `render()`). Nothing said so in words, and nothing regression-tested it, which
is the gap this issue asks to close -- a documentation-and-guard gap, not a live
defect (confirmed by reading the call sites above before writing anything below).

Every "must not vary with X" assertion below carries a positive control (the
marker DOES move when the declared default's own state changes) and, per the
issue's own TDD instruction, a demonstration that a naive/broken variant --
one that *does* fold the current branch into the glyph -- fails the very
assertion the real code passes, so the guard is provably non-vacuous even
though nothing here needed fixing.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import statusline  # noqa: E402


# ------------------------------------------------------------- render(): the glyph itself


def _facts(**overrides):
    facts = {
        "model": "Opus",
        "percent": 42,
        "repo_name": "claude-oss",
        "branch": "main",
        "default_branch": "main",
        "version": "0.10.0",
        "board": {},
        "release": None,
        "traps": 0,
        "last": "23:47",
        "plugins": [],
        "channel": None,
        "default_branch_state": "green",
    }
    facts.update(overrides)
    return facts


def _identity_prefix(line, symbols):
    """The `{repo_name}{marker}` token -- the first space-delimited word of the
    identity block, the second `|`-delimited block on the line. Isolating it
    this way (rather than string-matching the marker glyph in isolation) means
    the assertion is about what actually ships: the rendered line, not a call
    to an internal function in isolation."""
    identity_block = line.split(symbols["sep"])[1]
    return identity_block.split(" ")[0]


def test_render_marker_is_identical_across_different_current_branches():
    """Three different `facts["branch"]` values -- the field that genuinely does
    report whichever branch/worktree this process happens to be running from --
    none equal to `default_branch`, so each renders its own branch token. The
    `{repo_name}{marker}` prefix in front of it must not move."""
    symbols = statusline._symbols(ascii_only=True)
    prefixes = {
        branch: _identity_prefix(
            statusline.render(_facts(branch=branch), ascii_only=True), symbols
        )
        for branch in ("fix/1312", "release-branch", "some-other-worktree-branch")
    }
    assert len(set(prefixes.values())) == 1, (
        "the repo-name marker changed with the current branch/worktree alone: {}".format(
            prefixes
        )
    )


def test_positive_control_the_marker_does_move_when_the_defaults_own_state_changes():
    """Same current branch throughout (so the control isolates one variable): the
    marker must move when `default_branch_state` -- the declared default's own
    reading -- changes. A test that only ever proves "must not move with branch"
    would also pass if the marker never moved at all."""
    symbols = statusline._symbols(ascii_only=True)
    green = _identity_prefix(
        statusline.render(_facts(default_branch_state="green"), ascii_only=True),
        symbols,
    )
    bad = _identity_prefix(
        statusline.render(_facts(default_branch_state="bad"), ascii_only=True),
        symbols,
    )
    assert green != bad, "the marker never moved even though the default's state did"


def test_the_invariant_check_is_non_vacuous_a_branch_sensitive_variant_fails_it():
    """Per the issue's own TDD instruction: if the fix is only a docstring and a
    test, the red step is still required, shown here by running the SAME
    "must not vary with the current branch" shape against a deliberately broken
    stand-in -- the exact defect class this guard exists to catch, so a future
    regression that reintroduces it would fail this test's own real cousin above.
    """
    symbols = statusline._symbols(ascii_only=True)

    def _broken_marker(default_branch_state, current_branch, symbols):
        key = statusline._DEFAULT_BRANCH_GLYPH_KEY.get(default_branch_state, "unk")
        if current_branch != "main":
            # The exact defect: folding the CURRENT branch/worktree into the glyph.
            key = "unk"
        return symbols[key]

    glyphs = {
        branch: _broken_marker("green", branch, symbols)
        for branch in ("main", "fix/1312", "release-branch")
    }
    assert len(set(glyphs.values())) > 1, (
        "the broken stand-in was supposed to be branch-sensitive, so this proves "
        "nothing about the real guard"
    )


# --------------------------------------------------- refresh(): the forge call site


def _stub_refresh_forge_calls(monkeypatch):
    monkeypatch.setattr(
        statusline, "_fork_refresh", lambda root, repo, session_id=None: None
    )
    monkeypatch.setattr(statusline, "_gh_count", lambda repo, kind: 0)
    monkeypatch.setattr(statusline, "_gh_external_issue_count", lambda repo, total: 0)
    monkeypatch.setattr(statusline, "_gh_unlabelled_issue_counts", lambda *a, **k: {})
    monkeypatch.setattr(statusline, "_gh_rollups", lambda repo: [])
    monkeypatch.setattr(statusline, "check_rollup_counts", lambda *a, **k: {})
    monkeypatch.setattr(statusline, "installed_plugins", lambda *a, **k: {})


def test_refresh_asks_the_forge_about_the_declared_default_never_the_checked_out_branch(
    tmp_path, monkeypatch
):
    """The only place that ever calls the forge about this field. `branch_name`
    (the function that answers the legitimately-current-branch field) is stubbed
    to a DIFFERENT, changing value on every call -- proving it plays no part --
    while the declared `default_branch` in `.oss.json` stays fixed at `"main"`."""
    _stub_refresh_forge_calls(monkeypatch)
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    seen = []
    monkeypatch.setattr(
        statusline,
        "_gh_default_branch_state",
        lambda repo, branch: seen.append(branch) or "green",
    )
    checked_out_branches = iter(
        ["fix/1312", "release-branch", "some-other-worktree-branch"]
    )
    monkeypatch.setattr(
        statusline, "branch_name", lambda root: next(checked_out_branches)
    )
    (tmp_path / ".oss.json").write_text(
        json.dumps({"repo": "owner/repo", "default_branch": "main"}),
        encoding="utf-8",
    )
    for _ in range(3):
        statusline.refresh(str(tmp_path), now=1_000.0)
    assert seen == ["main", "main", "main"], (
        "the forge was asked about something other than the declared default "
        "branch: {}".format(seen)
    )


def test_positive_control_refresh_follows_a_genuine_change_to_the_declared_default(
    tmp_path, monkeypatch
):
    """The companion control for the refresh-level guard above: change
    `default_branch` itself (a real config edit, not a change of current
    branch) and confirm the forge call follows it -- proving the parameter is
    genuinely read, not hardcoded to `"main"` by the stub wiring above."""
    _stub_refresh_forge_calls(monkeypatch)
    monkeypatch.setattr(statusline, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(statusline, "branch_name", lambda root: "main")
    seen = []
    monkeypatch.setattr(
        statusline,
        "_gh_default_branch_state",
        lambda repo, branch: seen.append(branch) or "green",
    )
    (tmp_path / ".oss.json").write_text(
        json.dumps({"repo": "owner/repo", "default_branch": "trunk"}),
        encoding="utf-8",
    )
    statusline.refresh(str(tmp_path), now=1_000.0)
    assert seen == ["trunk"]
