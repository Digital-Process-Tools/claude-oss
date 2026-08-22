"""#418 -- a version string alone cannot tell two installs of the same plugin apart.

`.claude-plugin/plugin.json` keeps the last RELEASED version for the entire cycle
that follows: from the moment a release is tagged until the next one ships, a
plugin cache directory unpacked mid-cycle from `main` and the tag it is named
after both read the same manifest version while carrying different code. #418
measured this directly: a cache directory named `0.9.0` declared agent-report
contract 5 while the `v0.9.0` tag declared contract 4, both manifests reading
"0.9.0".

`plugin_identity()` answers with the version PLUS a content digest, built from
the same `plugin_tree_digest` / `_tree_identity` pair `plugin_provenance` already
uses to compare two trees -- so a single install now carries its own
discriminator without needing a second tree hanging around to diff against.

Two fixtures, paired as the issue asks: two roots that read the same manifest
version and differ in content must report different identities (the must-fire
half), and two roots that are byte-identical must report the same identity (the
must-not-fire control) -- so a check that always cries skew cannot pass this file.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402


def _make_root(tmp_path, name, version, body):
    root = tmp_path / name
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "oss", "version": version}), encoding="utf-8"
    )
    (root / "scripts").mkdir()
    (root / "scripts" / "doctor.py").write_text(body, encoding="utf-8")
    return root


def test_same_version_different_content_reports_different_identities(tmp_path):
    """The must-fire half: this is #418s exact reproduction, in miniature."""
    a = _make_root(tmp_path, "a", "9.9.9", "contract = 4\n")
    b = _make_root(tmp_path, "b", "9.9.9", "contract = 5\n")

    identity_a = doctor.plugin_identity(a)
    identity_b = doctor.plugin_identity(b)

    assert identity_a.startswith("9.9.9, "), identity_a
    assert identity_b.startswith("9.9.9, "), identity_b
    assert identity_a != identity_b, (identity_a, identity_b)


def test_identical_roots_report_the_same_identity(tmp_path):
    """The must-not-fire control: a check that always cries skew fails this."""
    a = _make_root(tmp_path, "a", "9.9.9", "contract = 4\n")
    b = _make_root(tmp_path, "b", "9.9.9", "contract = 4\n")

    assert doctor.plugin_identity(a) == doctor.plugin_identity(b)


def test_identity_folds_the_two_unreadable_manifest_states_like_plugin_version(tmp_path):
    """The failure states must never render as a version-shaped string (#350s rule,
    carried over here rather than reopened)."""
    root = tmp_path / "broken"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text("not json", encoding="utf-8")

    identity = doctor.plugin_identity(root)

    assert identity.startswith("unreadable, "), identity
