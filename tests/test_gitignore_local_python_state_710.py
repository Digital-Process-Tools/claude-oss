"""#710: `.gitignore` widened for common Python local-state shapes, proactively.

Recorded from the `0.16.0` release: a release commit made with `git commit --all` swept an
untracked `.venv/` into it -- 1390 files where 41 were intended, reset before it reached the
remote. `.gitignore` already recorded the identical accident against the `v0.3.0` release (a
different offender, `.claude/jit-context/.discovery/`), so the mitigation in place -- add each
offender to `.gitignore` after it bites -- is reactive by construction and only ever covers what
has already caused an incident.

This is the proactive half of the fix: the ordinary Python virtualenv/build-artifact directory
shapes that have not yet bitten this repo but are the obvious next offender, added ahead of an
incident rather than after one. It does not close the class -- an offender nobody has thought of
still gets through -- see #710's own route 3 for why a refusal that compares the staged set
against what the release should have touched is the only route that does, and why it is filed
separately rather than built here.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_common_python_local_state_shapes_are_ignored():
    """`.venv/` was already added reactively at 0.16.0 (#710). `venv/`, `env/`, `.tox/` and
    `*.egg-info/` are the same shape -- a local Python environment or build artifact, never part
    of the plugin -- added proactively rather than waiting for each to cause its own incident.
    """
    rules = [
        line.strip()
        for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    ]
    for pattern in (".venv/", "venv/", "env/", ".tox/", "*.egg-info/"):
        assert pattern in rules, (
            f"{pattern!r} is a common Python local-state shape that .gitignore does not yet "
            "cover -- exactly the reactive gap #710 files against."
        )


def test_the_must_fire_control_the_rule_above_would_otherwise_be_vacuous_against():
    """Without this, a `.gitignore` missing every rule above would satisfy the first test just
    as trivially as an empty file satisfies any `in` check that never runs. This proves the file
    carries unrelated rules too, so the first test is reading this repo's real `.gitignore`.
    """
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__" in text
