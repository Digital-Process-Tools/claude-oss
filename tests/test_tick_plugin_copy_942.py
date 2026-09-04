"""#942: the loop can run a release behind the repository it manages when that repo
IS this plugin itself -- `${CLAUDE_PLUGIN_ROOT}` resolves to the installed cache, not
the checkout, and `commands/tick.md`'s existing identity check (#477/#677) only ever
compares one tick's plugin identity to the previous tick's, so it cannot see this.

The fix is not a new check: `doctor.py`'s own `check_plugin_copy` already compares the
checkout being diagnosed against the installed copy that answered, byte for byte, and
names both manifests' declared versions the moment they disagree (`plugin_provenance`,
verified directly against two synthetic plugin trees below). `commands/tick.md` used to
run doctor.py for exactly that comparison and then discard everything but the `OK oss
plugin version` line via `sed`. This guards that the discarded line is read instead.
"""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402

TICK = REPO_ROOT / "commands" / "tick.md"


def _text():
    return TICK.read_text(encoding="utf-8")


def test_tick_no_longer_discards_the_full_doctor_output():
    """The old pipeline ran doctor.py straight into the `IDENTITY` sed with no
    intermediate variable, which is exactly what made the plugin-copy line
    unrecoverable a moment later. Capturing it once, in `$DOCTOR_OUTPUT`, is what
    the plugin-copy extraction below needs to exist at all.
    """
    text = _text()
    assert 'DOCTOR_OUTPUT="$(python3 "$DOCTOR_ROOT/scripts/doctor.py" --root .' in text


def test_tick_extracts_the_plugin_copy_line():
    text = _text()
    assert "PLUGIN_COPY=" in text
    assert "plugin copy: " in text


def test_tick_does_not_use_gnu_only_alternation_in_the_extraction():
    """BSD sed (macOS -- the platform this plugin is developed on) does not
    implement alternation in a basic regular expression; it is a GNU extension.
    That spelling would silently match nothing on macOS. -E is the portable
    answer, and this is the regression guard for it.
    """
    text = _text()
    fences = re.findall(r"```bash\n(.*?)```", text, re.DOTALL)
    code = "\n".join(fences)
    assert r"\(OK\|WARN\)" not in code, (
        "a bash code block in commands/tick.md runs sed with a GNU-sed-only "
        "alternation; BSD sed on macOS silently matches nothing with it. The "
        "prose explaining why this was avoided is allowed to mention the "
        "rejected spelling -- only the executable block must not use it."
    )
    assert "sed -nE" in code or "sed -n -E" in code


def test_tick_names_942_and_the_narrow_scope():
    text = _text()
    assert "#942" in text
    assert "not a checkout of this plugin" in text


# --- the mechanism this prose points at actually answers the question -----------


def _write_plugin(root, version):
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "oss", "version": version}), encoding="utf-8"
    )
    (root / "marker.txt").write_text("v={}".format(version), encoding="utf-8")


def test_plugin_provenance_names_both_versions_on_a_lagging_install(tmp_path):
    """Positive control: an installed copy behind the checkout it is diagnosing must
    produce a SKEW line naming both declared versions -- the exact fact #942 says
    nothing answers today.
    """
    installed = tmp_path / "installed-0.19.0"
    checkout = tmp_path / "checkout-0.20.0"
    installed.mkdir()
    checkout.mkdir()
    _write_plugin(installed, "0.19.0")
    _write_plugin(checkout, "0.20.0")

    lines = doctor.plugin_provenance(
        installed, checkout, attested=str(installed), attested_source="CLAUDE_PLUGIN_ROOT"
    )
    copy_lines = [msg for _level, msg in lines if msg.startswith("plugin copy: ")]
    assert copy_lines, "no 'plugin copy:' line at all: {!r}".format(lines)
    assert "SKEW" in copy_lines[0]
    assert "0.19.0" in copy_lines[0] and "0.20.0" in copy_lines[0]


def test_tick_names_the_same_tree_shape_as_clean_not_ambiguous():
    """Self-review finding: an earlier draft of this prose enumerated only three
    non-SKEW shapes and fell through to could-not-tell for the fourth --
    doctor.py answering from the SAME directory it is diagnosing, which is
    exactly what a maintainer developing this plugin against its own working
    tree looks like (the literal scenario #942 is about). That must read as
    clean, not as an ambiguity to report.
    """
    text = _text()
    assert "no installed-copy/" in text and "clone split to report here" in text
    assert "could-not-tell: this is what a maintainer developing this plugin" in text


def test_plugin_provenance_reports_the_same_tree_case_as_clean(tmp_path):
    """Positive control for the finding above, against the real mechanism rather
    than only the prose: doctor.py's own plugin_provenance() must actually
    produce the "no installed-copy/clone split" sentence when script_root and
    project_dir are the same directory, not a SKEW or a could-not-tell shape.
    """
    _write_plugin(tmp_path, "0.20.0")
    lines = doctor.plugin_provenance(
        tmp_path, tmp_path, attested=str(tmp_path), attested_source="CLAUDE_PLUGIN_ROOT"
    )
    copy_lines = [msg for _level, msg in lines if msg.startswith("plugin copy: ")]
    assert copy_lines, "no 'plugin copy:' line at all: {!r}".format(lines)
    assert "no installed-copy/clone split to report here" in copy_lines[0]
    assert "SKEW" not in copy_lines[0]


def test_plugin_provenance_is_quiet_on_an_unrelated_repo():
    """Negative control: a repo that is not a checkout of this plugin must not be
    told it is "behind" anything -- #942 itself says the scope is narrow.
    """
    installed = Path("scripts").parent  # this repo's own plugin root
    lines = doctor.plugin_provenance(
        REPO_ROOT, Path("/nonexistent-unrelated-repo-942"),
        attested=str(REPO_ROOT), attested_source="CLAUDE_PLUGIN_ROOT",
    )
    copy_lines = [msg for _level, msg in lines if msg.startswith("plugin copy: ")]
    assert copy_lines
    assert "not a checkout of this plugin" in copy_lines[0]
