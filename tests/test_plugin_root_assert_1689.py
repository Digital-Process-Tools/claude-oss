"""#1689: setup.md and the scheduler-step wrapper never asserted
`${CLAUDE_PLUGIN_ROOT}` resolves before trusting it, so a spawn run under
`--plugin-dir` (or any project-scoped install from another directory) can
silently probe the plugin checkout instead of the repo being managed.

Companion to test_script_path_resolution_647.py, which guards the PREFIX is
present; this guards that an empty/wrong prefix is caught before it is used.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETUP = REPO_ROOT / "commands" / "run" / "setup.md"
SCHEDULER_STEP = REPO_ROOT / "agents" / "scheduler-step.md"


def _flatten(text):
    return " ".join(text.lower().split())


def _unmet(text, anchors):
    folded = _flatten(text)
    return [anchor for anchor in anchors if anchor not in folded]


SETUP_ASSERT_ANCHORS = [
    "claude_plugin_root",
    "could-not-run",
    "scripts/oss_config.py",
]


def test_setup_asserts_plugin_root_before_probing():
    assert not _unmet(SETUP.read_text(encoding="utf-8"), SETUP_ASSERT_ANCHORS)


def test_the_setup_assert_fires_on_the_prior_probe_paragraph():
    """The document as it stood before #1689: it goes straight into `--probe`
    with no check that ${CLAUDE_PLUGIN_ROOT} resolved to anything real."""
    prior_probe_paragraph = (
        "## Probe\n\n"
        "**Do not assemble the probe by hand.** `--probe` measures the repo and "
        "writes it, and `--build` reads that and nothing else.\n\n"
        '```bash\npython3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_config.py" --probe . '
        '| python3 "${CLAUDE_PLUGIN_ROOT}/scripts/oss_config.py" --build\n```'
    )
    missing = _unmet(prior_probe_paragraph, SETUP_ASSERT_ANCHORS)
    assert missing, (
        "the setup-assert check passes against the document's prior probe "
        "paragraph, which never checks CLAUDE_PLUGIN_ROOT resolves: {}".format(missing)
    )


SCHEDULER_STEP_ASSERT_ANCHORS = [
    "claude_plugin_root",
    "could-not-run",
    "before reading",
]


def test_scheduler_step_asserts_plugin_root_before_reading_its_procedure():
    assert not _unmet(
        SCHEDULER_STEP.read_text(encoding="utf-8"), SCHEDULER_STEP_ASSERT_ANCHORS
    )


def test_the_scheduler_step_assert_fires_on_the_prior_what_you_do_paragraph():
    prior_paragraph = (
        "## What you do\n\n"
        "The prompt that spawned you names exactly one file under `commands/` or "
        "`commands/run/`. Read it, follow it precisely as written -- it already "
        "knows what to check, what to write and what to spawn, including its own "
        "`Agent` calls where it makes one (`commands/run/triage.md` delegates to "
        "`oss:triager`, for instance) -- and stop when it says you are done."
    )
    missing = _unmet(prior_paragraph, SCHEDULER_STEP_ASSERT_ANCHORS)
    assert missing, (
        "the scheduler-step assert check passes against the document's prior "
        "paragraph, which never checks CLAUDE_PLUGIN_ROOT resolves before "
        "reading: {}".format(missing)
    )
