"""#626 -- bin/oss-workspace does not react to the oss plugin's own version
changing under a working install; only `/oss:tick` does (#477), and a QA
session, a review or an ordinary working session never reaches that step.

This drives the launcher's own plugin-identity block at the SHELL level, the
same way tests/test_ask_consumer_573.py drives ASK_CONSUMER: extract the whole
`if ... fi` wrapper verbatim and run it under `sh -eu`, which is what
bin/oss-workspace itself runs under. A python-only extraction of the heredoc
body would miss the exact `set -eu` interaction #588 was about.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "bin" / "oss-workspace"

BLOCK_START = (
    "# --- plugin identity: did it change since the last session here? (#626) -------"
)
BLOCK_END_MARKER = (
    "\n\n# --- the setup diagnostic, before the session starts working "
    "------------------"
)


def _extract_plugin_identity_block():
    launcher = LAUNCHER.read_text(encoding="utf-8")
    start = launcher.find(BLOCK_START)
    if start == -1:
        pytest.fail(
            "bin/oss-workspace no longer carries the plugin-identity block's "
            "opening marker -- and a block that went unchecked must not read "
            "as one that agreed"
        )
    end = launcher.find(BLOCK_END_MARKER, start)
    if end == -1:
        pytest.fail(
            "bin/oss-workspace's plugin-identity block no longer ends where "
            "expected, right before the setup-diagnostic section -- and a "
            "block that went unchecked must not read as one that agreed"
        )
    return launcher[start:end]


def _sh_single_quote(value):
    return "'" + value.replace("'", "'\\''") + "'"


#: A minimal fake plugin root: real doctor.py imports a lot this fixture does
#: not need, and a fake `plugin_identity()` lets each test control the
#: "current" reading directly rather than depending on the real tree digest
#: changing between two checkouts.
_FAKE_DOCTOR = """
import os


def plugin_identity(root):
    return os.environ.get("FAKE_PLUGIN_IDENTITY", "v1")
"""


def _fake_plugin_root(tmp_path):
    """Reused across two `_run_block` calls in the same test -- `exist_ok=True`
    so the second call does not fail on a directory the first already made.
    """
    root = tmp_path / "plugin"
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "doctor.py").write_text(_FAKE_DOCTOR, encoding="utf-8")
    return root


def _run_block(tmp_path, *, python_bin=None, home=True, xdg_cache_home=None,
                fake_identity="v1", plugin_root=None):
    """Run the extracted block under `sh -eu`.

    `home`/`xdg_cache_home` control which of HOME / XDG_CACHE_HOME the child
    process sees -- neither, only HOME, or an explicit XDG_CACHE_HOME -- so
    the "neither is set" arm is reachable without touching this process's own
    environment.
    """
    plugin_root = plugin_root or _fake_plugin_root(tmp_path)
    python_bin = sys.executable if python_bin is None else python_bin
    script = tmp_path / "run_block.sh"
    script.write_text(
        "set -eu\n"
        "plugin_root=%s\n"
        "python_bin=%s\n"
        "%s"
        % (
            _sh_single_quote(str(plugin_root)),
            _sh_single_quote(python_bin),
            _extract_plugin_identity_block(),
        ),
        encoding="utf-8",
    )
    env = {"PATH": os.environ.get("PATH", "")}
    if sys.platform == "win32":
        # sh needs enough of the ambient environment to find an interpreter
        # and DLLs on Windows; POSIX runners do not need this branch.
        env.update(os.environ)
        env["PATH"] = os.environ.get("PATH", "")
    if home:
        env["HOME"] = str(tmp_path / "home")
    if xdg_cache_home is not None:
        env["XDG_CACHE_HOME"] = str(xdg_cache_home)
    env["FAKE_PLUGIN_IDENTITY"] = fake_identity
    return subprocess.run(
        ["sh", str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        universal_newlines=True,
        timeout=60,
    )


def test_first_run_says_could_not_tell_and_records_the_identity(tmp_path):
    """No prior file yet -- the honest third state, never rendered as
    `unchanged`, and the identity must be there for the NEXT run to compare.
    """
    cache = tmp_path / "cache"
    result = _run_block(tmp_path, xdg_cache_home=str(cache), fake_identity="v1")
    assert result.returncode == 0, result.stderr
    assert "no prior oss plugin identity is recorded" in result.stderr, result.stderr
    assert "plugin changed" not in result.stderr, result.stderr
    prior_file = cache / "oss-workspace" / "last-plugin-identity"
    assert prior_file.read_text(encoding="utf-8") == "v1"


def test_second_run_with_the_same_identity_says_nothing(tmp_path):
    """The must-fire control's opposite number: unchanged is silence, not a
    line saying "unchanged" -- furniture on every healthy launch is how the
    line that matters (a real change) stops being read.
    """
    cache = tmp_path / "cache"
    _run_block(tmp_path, xdg_cache_home=str(cache), fake_identity="v1")
    result = _run_block(tmp_path, xdg_cache_home=str(cache), fake_identity="v1")
    assert result.returncode == 0, result.stderr
    assert result.stderr == "", result.stderr


def test_a_changed_identity_is_announced_loudly(tmp_path):
    """The must-fire case this whole issue is about: a version change under a
    working install must be said, not folded into a healthy VERDICT line
    somewhere else.
    """
    cache = tmp_path / "cache"
    _run_block(tmp_path, xdg_cache_home=str(cache), fake_identity="v1")
    result = _run_block(tmp_path, xdg_cache_home=str(cache), fake_identity="v2")
    assert result.returncode == 0, result.stderr
    assert "the oss plugin changed since your last session here (v1 -> v2)" in result.stderr, result.stderr
    prior_file = cache / "oss-workspace" / "last-plugin-identity"
    assert prior_file.read_text(encoding="utf-8") == "v2"


def test_no_working_python_says_could_not_tell_rather_than_nothing(tmp_path):
    result = _run_block(tmp_path, python_bin="", xdg_cache_home=str(tmp_path / "cache"))
    assert result.returncode == 0, result.stderr
    assert "could not be told" in result.stderr, result.stderr


def test_neither_cache_dir_nor_home_is_set(tmp_path):
    """The third open question in #626 answered defensively: with nowhere to
    keep a prior, this must say so rather than silently skip the whole check.
    """
    result = _run_block(tmp_path, home=False, xdg_cache_home=None)
    assert result.returncode == 0, result.stderr
    assert "neither XDG_CACHE_HOME nor HOME is set" in result.stderr, result.stderr


def test_a_broken_doctor_module_says_could_not_tell_rather_than_crashing(tmp_path):
    """`doctor.plugin_identity` is never assumed to exist or to succeed -- a
    plugin checkout mid-update, or one this fixture deliberately breaks, must
    still let the session open."""
    broken_root = tmp_path / "broken-plugin"
    (broken_root / "scripts").mkdir(parents=True)
    (broken_root / "scripts" / "doctor.py").write_text(
        "raise RuntimeError('broken on purpose')\n", encoding="utf-8"
    )
    result = _run_block(
        tmp_path,
        plugin_root=broken_root,
        xdg_cache_home=str(tmp_path / "cache"),
    )
    assert result.returncode == 0, result.stderr
    assert "could not be told" in result.stderr, result.stderr
