"""#292 -- the one board the derivation cannot name is the one that owns the tooling.

`dependency_repositories()` resolves each declared dependency's tracker off the
`repository` key in that plugin's installed manifest. Nothing declares itself as its
own dependency, so this plugin's repository is absent from that mapping by
construction -- and it is the repository that owns everything the loop writes into
somebody else's tree. Meanwhile `agents/developer.md` forbids improvising: a
dependency must be named *by the name the manifest uses, never a repo slug you
inferred*. A destination that cannot be derived and a destination that does not exist
render identically at the call site.

**Correction to the issue, measured rather than argued.** #292 says "the fix is one
key" and proposes adding `repository` to `.claude-plugin/plugin.json`. That key has
been there since 0.1.0 -- in the tree and in every cached install. Nothing was missing
from the manifest; what was missing was a reader.

**And the design question the issue calls "the whole design question" is settled by
measurement, not taste.** Folding the loop's own repository into
`dependency_repositories()` does not leave every caller working unchanged. Its one
caller is `check_freshness`, which feeds the mapping through `published_versions` into
`dependency_findings`, and that function unions `declared | installed | latest`. `oss`
is in none of the first two, so folding makes doctor print:

    WARN oss: declared but not installed. Run `claude plugin install oss@dpt-plugins`

-- false, actionable and wrong, from a diagnostic, about the plugin printing it. So a
sibling accessor it is, and `test_the_loop_is_not_folded_into_the_dependency_map`
below is the guard that keeps it one.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _manifest(root, doc):
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    path = root / ".claude-plugin" / "plugin.json"
    if doc is None:
        path.write_text("{ not json", encoding="utf-8")
    else:
        path.write_text(json.dumps(doc), encoding="utf-8")
    return root


def test_the_real_manifest_answers(tmp_path):
    """Against this tree's own manifest, which is the invocation that matters.

    The value is read off disk exactly as the other three are -- no hardcoded slug, no
    new vocabulary, nothing about one repository living in shared code.
    """
    url, problem = doctor.loop_repository()
    assert problem is None, (url, problem)
    manifest = json.loads(
        (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert url == manifest["repository"]


def test_a_manifest_with_no_repository_key_is_not_no_tracker(tmp_path):
    """The state the issue names in as many words: three answers, not two, and *could
    not determine* must not render as *there is no tracker*.

    That collapse is the defect #292 is about. A fix that reproduced it one level up
    would pass every other assertion in this file.
    """
    root = _manifest(tmp_path, {"name": "oss", "version": "0.0.0"})
    url, problem = doctor.loop_repository(plugin_root=root)
    assert url is None
    assert problem == "no-repository-key", problem


def test_an_unreadable_manifest_is_its_own_answer(tmp_path):
    """Absent and malformed both land here, and neither is "no tracker" either."""
    absent, problem = doctor.loop_repository(plugin_root=tmp_path / "nothing")
    assert absent is None and problem == "unreadable", problem

    root = _manifest(tmp_path, None)
    malformed, problem = doctor.loop_repository(plugin_root=root)
    assert malformed is None and problem == "unreadable", problem


def test_a_non_string_repository_is_refused_rather_than_returned(tmp_path):
    """`plugin.json` is a tracked file a contributor writes. An object here would be
    formatted into a diagnostic line and into whatever a brief does with it, so the
    type is checked where it is read rather than where it is used."""
    root = _manifest(tmp_path, {"repository": {"url": "https://example.invalid"}})
    url, problem = doctor.loop_repository(plugin_root=root)
    assert url is None
    assert problem == "no-repository-key", problem


def test_the_loop_is_not_folded_into_the_dependency_map():
    """The design decision, held by a test rather than by a comment.

    Not stylistic purity about `dependency_repositories` meaning *dependencies*. Folding
    makes `check_freshness` emit `oss: declared but not installed. Run claude plugin
    install oss@dpt-plugins` -- measured, not reasoned. The union in
    `dependency_findings` is why.
    """
    names = doctor.declared_dependencies()
    repos = doctor.dependency_repositories(names)
    assert "oss" not in repos, (
        "the loop's own repository was folded into dependency_repositories(); "
        "check_freshness will now report it as declared-but-not-installed"
    )
    # And the reachable half: the sibling accessor answers where the map does not.
    url, problem = doctor.loop_repository()
    assert problem is None and url


def test_doctor_reports_it_in_all_three_states(tmp_path):
    """A sibling accessor that reaches no caller is a capability nobody can use. This is
    the caller, and it must print one line in each state -- including the two where it
    has no answer, which is the half a check written against a fixture never sees."""
    doctor.check_loop_repository()
    level, message = doctor.FINDINGS[-1]
    assert level == "OK", message
    assert "claude-oss" in message, message

    doctor.FINDINGS.clear()
    doctor.check_loop_repository(plugin_root=_manifest(tmp_path, {"name": "oss"}))
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "repository" in message, message
    assert len(doctor.FINDINGS) == 1

    doctor.FINDINGS.clear()
    doctor.check_loop_repository(plugin_root=tmp_path / "gone")
    level, message = doctor.FINDINGS[-1]
    assert level == "WARN"
    assert "could not" in message or "unknown" in message, message
    assert len(doctor.FINDINGS) == 1
