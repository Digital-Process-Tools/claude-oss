"""#1055: `_resolve_slug` in the four `doctor_check_*.py` modules that call
`gh api repos/{slug}/...` interpolated `.oss.json`'s `repo` (or the `origin`
remote fallback) after nothing but an `isinstance(str)` check. A
traversal-shaped slug -- `"../secret"`, `"..%2f/x"`, `"-X/POST"`, `"a/.."` --
passes `oss_config.repo_problem` today (it only forbids a slash, a backslash
and whitespace WITHIN a segment, never a literal `".."` segment) and would
reach `gh api` unchanged, silently addressing a different endpoint than the
one configured. #1035 closed the identical gap for `statusline.py` with
`_malformed_repo`; this closes it here with `doctor._malformed_repo`, reused
by all four `_resolve_slug` implementations rather than re-derived per file.

Every "must refuse" case below is paired with a "must still resolve
correctly" positive control in the same fixture, per CLAUDE.md's own rule --
a guard asserted only by its absence passes when the function does nothing
at all.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_branch_protection  # noqa: E402
import doctor_check_codeql_scan  # noqa: E402
import doctor_check_security_alerts  # noqa: E402
import doctor_check_security_settings  # noqa: E402


#: The four traversal-shaped slugs the issue exercises against
#: `oss_config.repo_problem` and finds accepted.
MALFORMED_SLUGS = ["../secret", "..%2f/x", "-X/POST", "a/.."]


def _no_run(*args, **kwargs):
    raise AssertionError("gh must not be invoked for a malformed slug")


# ------------------------------------------------------------- doctor._malformed_repo


@pytest.mark.parametrize("slug", MALFORMED_SLUGS)
def test_malformed_repo_rejects_traversal_shapes(slug):
    assert doctor._malformed_repo(slug) is True


def test_malformed_repo_accepts_well_formed_slug():
    """The must-fire control: a well-formed repo is not flagged malformed."""
    assert doctor._malformed_repo("owner/name") is False


# ------------------------------------------------------- per-module _resolve_slug


RESOLVE_SLUG_MODULES = [
    doctor_check_codeql_scan,
    doctor_check_security_settings,
    doctor_check_security_alerts,
    doctor_check_branch_protection,
]


@pytest.mark.parametrize("module", RESOLVE_SLUG_MODULES, ids=lambda m: m.__name__)
@pytest.mark.parametrize("slug", MALFORMED_SLUGS)
def test_resolve_slug_refuses_malformed_repo_before_gh_api(module, slug, tmp_path):
    """Negative control: each of the four listed malformed shapes is refused
    before it can reach `gh api`, for every module carrying `_resolve_slug`.
    """
    resolved, reason = module._resolve_slug(str(tmp_path), {"repo": slug}, _no_run)
    assert resolved is None
    assert "owner/name" in reason


@pytest.mark.parametrize("module", RESOLVE_SLUG_MODULES, ids=lambda m: m.__name__)
def test_resolve_slug_still_resolves_a_well_formed_repo(module, tmp_path):
    """Positive control: a well-formed slug still resolves and would reach
    `gh api` as before -- the must-fire case paired with the refusals above.
    """

    def run(cmd, **kwargs):
        raise AssertionError("resolving a well-formed slug must not call gh")

    resolved, reason = module._resolve_slug(str(tmp_path), {"repo": "owner/name"}, run)
    assert resolved == "owner/name"
    assert reason is None


@pytest.mark.parametrize("module", RESOLVE_SLUG_MODULES, ids=lambda m: m.__name__)
def test_resolve_slug_refuses_a_malformed_origin_fallback(
    module, tmp_path, monkeypatch
):
    """The guard applies uniformly regardless of which of `_resolve_slug`'s
    two sources produced the value -- not just the `.oss.json` path.
    """
    monkeypatch.setattr(
        doctor, "_origin_slug", lambda project_dir, run=None: ("../secret", None)
    )
    resolved, reason = module._resolve_slug(str(tmp_path), {}, _no_run)
    assert resolved is None
    assert "owner/name" in reason
