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


def _child_env(tmp_path, *, home, xdg_cache_home, fake_identity, windows=None):
    """The environment `_run_block`'s child gets, built where a test can read it.

    Split out of `_run_block` for #643. The `windows` branch below copies the
    whole ambient environment in, and setting HOME only when it is wanted
    left a PARENT's HOME standing when it was not -- WHERE the ambient
    environment carries one. That is real and reproducible on any platform
    whose `os.environ` sets `HOME` (macOS, Linux CI legs, a developer's own
    machine): `home=False` under the old logic produced a child with a home
    after all, the launcher then behaved correctly against that home, and a
    test asserting the no-home arm read the correct behaviour as a failure.

    IT IS NOT THE WHOLE STORY ON WINDOWS, and this docstring used to claim
    otherwise -- corrected after `fd9888a`'s own precondition assertion
    (`assert "HOME" in os.environ`) failed on GitHub's `windows-latest`
    legs: that runner's own Python `os.environ` carries no `HOME` at all, so
    there was never a parent HOME for this fixture to leak there. Absence
    still has to be established by removing the variable rather than
    declining to add one -- that principle does not change -- but on a
    Windows runner the pop this function performs is provably a no-op for
    `HOME` specifically, because the key was never present in the copied
    ambient environment to begin with. Whatever made #643's original Windows
    legs fail is therefore not (or not only) this mechanism; see
    `test_the_no_home_fixture_removes_home_it_does_not_merely_decline_to_add_it`
    and `test_neither_cache_dir_nor_home_is_set` for what is and is not
    established about the Git-Bash-synthesis alternative.

    `windows` is a parameter rather than a read of `sys.platform` so the branch
    that only runs on Windows is reachable from a test on any platform: the
    leak is a fact about the ambient environment, not about the OS, and a guard
    that can only run where the bug was found is a guard nobody re-runs. It
    remains useful for exactly that reason even though real Windows CI cannot
    exercise the HOME-leak case itself.
    """
    windows = sys.platform == "win32" if windows is None else windows
    env = {"PATH": os.environ.get("PATH", "")}
    if windows:
        # sh needs enough of the ambient environment to find an interpreter
        # and DLLs on Windows; POSIX runners do not need this branch.
        env.update(os.environ)
        env["PATH"] = os.environ.get("PATH", "")
    if home:
        env["HOME"] = str(tmp_path / "home")
    else:
        env.pop("HOME", None)
    if xdg_cache_home is not None:
        env["XDG_CACHE_HOME"] = str(xdg_cache_home)
    else:
        env.pop("XDG_CACHE_HOME", None)
    env["FAKE_PLUGIN_IDENTITY"] = fake_identity
    return env


#: Asks the child shell what IT resolves for the two variables, rather than
#: trusting that an environment without them produces a shell without them.
#: Git Bash's `sh` can synthesize a home from the Windows profile, and that is
#: a thing only the child can answer.
_HOME_PROBE = (
    'echo "HOME=${HOME:-<unset>}"\n'
    'echo "XDG_CACHE_HOME=${XDG_CACHE_HOME:-<unset>}"\n'
)


def _probe_child_home(tmp_path, env, name="home_probe.sh"):
    """What the child shell resolves for HOME / XDG_CACHE_HOME, as two strings.

    `<unset>` means the shell itself saw nothing there. Anything else is what
    it resolved, whether that came from `env` or from the shell synthesizing
    one -- which is the distinction the caller needs and the only one this can
    answer, since a shell that invents a home is indistinguishable from a
    parent that passed one once the child is running.
    """
    script = tmp_path / name
    script.write_text("set -eu\n" + _HOME_PROBE, encoding="utf-8")
    done = subprocess.run(
        ["sh", str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        universal_newlines=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    resolved = {}
    for line in done.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            resolved[key] = value
    return resolved.get("HOME"), resolved.get("XDG_CACHE_HOME")


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
    env = _child_env(
        tmp_path,
        home=home,
        xdg_cache_home=xdg_cache_home,
        fake_identity=fake_identity,
    )
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


def test_the_no_home_fixture_removes_home_it_does_not_merely_decline_to_add_it(
    tmp_path,
):
    """#643's actual defect, reproduced on every platform that has one.

    `windows=True` is passed explicitly rather than waited for: on a platform
    whose ambient `os.environ` carries `HOME`, `env.update(os.environ)`
    leaks the PARENT's HOME through `home=False`'s old "decline to add"
    logic, and this is that leak, forced regardless of host OS.

    THIS PRECONDITION WAS MEASURED WRONG ONCE ALREADY (#643 follow-up): the
    original commit here asserted `"HOME" in os.environ` outright, on the
    belief that every runner this suite runs on sets HOME. GitHub Actions'
    `windows-latest` disproved that directly -- its own Python `os.environ`
    carries no `HOME` at all, so the hard assertion failed on that leg with
    its own message ("this platform cannot exercise this test") as the
    failure text, which is a skip's message wearing a failure's exit code.
    Confirmed by reproducing the identical failure locally: running this
    file's suite with `HOME`/`XDG_CACHE_HOME` stripped from THIS process's
    own ambient environment (`env -u HOME -u XDG_CACHE_HOME python3 -m
    pytest ...`) reproduces the exact assertion text and line Windows CI
    reported.

    So the mechanism this test guards -- an ambient HOME leaking through a
    fixture that merely declines to add one -- is real and reproducible
    wherever HOME is ambiently set (macOS and Linux CI legs, and this
    developer's own machine), and is NOT the story on GitHub's Windows
    runners, which never had a HOME to leak in the first place. Whatever
    caused the original #643 Windows failures is therefore NOT (or not only)
    this leak; the leading remaining explanation is the sibling reviewer
    finding on Git Bash's `sh` synthesizing its own HOME from `USERPROFILE`
    / `HOMEDRIVE` / `HOMEPATH`, which this test does not scrub and does not
    attempt to guard -- `test_neither_cache_dir_nor_home_is_set` below is
    the one that probes for that, because probing the child is the only way
    to tell a real absence from a shell-synthesized one.

    Attempted, not assumed: precondition checked first, skip carrying the
    platform and what was observed when it fails, so a runner with no
    ambient HOME reads as untested rather than broken -- CLAUDE.md's own
    permission-fixture rule, one axis over.
    """
    if "HOME" not in os.environ:
        pytest.skip(
            "this platform's ambient os.environ has no HOME at all (platform "
            "{!r}), so home=False's old 'decline to add' behaviour and the "
            "fix's explicit removal are indistinguishable here -- there is "
            "nothing to leak and nothing to remove. UNTESTED here: whether "
            "the ambient-HOME-leak mechanism this test guards is what #643's "
            "Windows failures were ever caused by; see "
            "test_neither_cache_dir_nor_home_is_set for the Git-Bash-synthesis "
            "question this cannot answer.".format(sys.platform)
        )
    env = _child_env(
        tmp_path,
        home=False,
        xdg_cache_home=None,
        fake_identity="v1",
        windows=True,
    )
    assert "HOME" not in env, (
        "the ambient copy left a HOME standing under home=False, so the "
        "no-home arm would run against a home: {!r}".format(env.get("HOME"))
    )
    assert "XDG_CACHE_HOME" not in env, env.get("XDG_CACHE_HOME")


def test_the_fixture_still_passes_a_home_when_one_is_asked_for(tmp_path):
    """The positive control for the test above.

    `"HOME" not in env` also passes for a `_child_env` that lost the ability to
    set HOME at all, which would silently disarm every other test in this file.
    Same fixture, same `windows=True` branch, opposite expectation: the home
    that arrives must be the one this test named, never the parent's.
    """
    env = _child_env(
        tmp_path,
        home=True,
        xdg_cache_home=None,
        fake_identity="v1",
        windows=True,
    )
    assert env["HOME"] == str(tmp_path / "home"), env["HOME"]


def test_neither_cache_dir_nor_home_is_set(tmp_path):
    """The third open question in #626 answered defensively: with nowhere to
    keep a prior, this must say so rather than silently skip the whole check.

    The no-home condition is MEASURED before it is asserted on (#643). Removing
    both variables from the child's environment is necessary and may not be
    sufficient: Git Bash's `sh` can synthesize a home from the Windows profile,
    and a shell that invents one is indistinguishable, from inside, from a
    parent that passed one. So the child is asked what it actually resolved,
    and where it still has a home this skips carrying that value rather than
    failing -- the launcher's behaviour against a home it found is correct, and
    reporting it as a defect is what #643 was.

    Same rule as the permission and monkeypatch fixtures in CLAUDE.md, and the
    skip is a measurement rather than a platform test for the reason #380
    records: a runner that genuinely has no home still gets the real assertion,
    whatever its OS.
    """
    env = _child_env(tmp_path, home=False, xdg_cache_home=None, fake_identity="v1")
    resolved_home, resolved_cache = _probe_child_home(tmp_path, env)
    if resolved_home != "<unset>" or resolved_cache != "<unset>":
        pytest.skip(
            "the child shell resolved a home even with both variables removed "
            "from its environment (HOME={!r}, XDG_CACHE_HOME={!r}, platform "
            "{!r}) -- the shell synthesizes one here, so the no-home arm could "
            "not be established. UNTESTED here: that the launcher says "
            "'neither XDG_CACHE_HOME nor HOME is set' when it truly has "
            "nowhere to keep a prior.".format(
                resolved_home, resolved_cache, sys.platform
            )
        )

    result = _run_block(tmp_path, home=False, xdg_cache_home=None)
    assert result.returncode == 0, result.stderr
    assert "neither XDG_CACHE_HOME nor HOME is set" in result.stderr, result.stderr


def test_the_home_probe_reports_a_home_when_there_is_one(tmp_path):
    """The positive control for the skip above, and the reason it is a
    measurement rather than a table.

    A probe that answered `<unset>` unconditionally would send the test above
    straight into its assertion on every platform, and a probe that answered a
    path unconditionally would skip it on every platform -- both silently. This
    pins that the probe distinguishes the two cases, so the skip fires on what
    the child actually resolved and not on what this file assumed it would.

    This runs on EVERY platform, including the ones where the skip above fires,
    which is the half that makes the skip trustworthy: a skip whose own probe is
    only exercised where the answer was already informative proves nothing about
    the platform it actually fired on (#380's shape). On Windows this is the
    evidence that the `<unset>` reading there was a real reading.

    What is asserted is DISCRIMINATION -- a home that was passed reads as
    something other than `<unset>`, one that was not reads as `<unset>` -- and
    deliberately not the exact string. Git Bash may rewrite a Windows path on the
    way into the child (a drive-letter form against a `/c/`-style one), and that
    is a shell behaviour this repository has not measured; pinning the path form
    here would be asserting a platform fact nobody established, which is the
    defect one layer over from the one this test exists to guard.
    """
    env = _child_env(tmp_path, home=True, xdg_cache_home=None, fake_identity="v1")
    resolved_home, resolved_cache = _probe_child_home(
        tmp_path, env, name="home_probe_control.sh"
    )
    assert resolved_home not in (None, "", "<unset>"), (
        "the probe could not see a HOME that was explicitly passed, so its "
        "`<unset>` answers carry no information: {!r}".format(resolved_home)
    )
    assert resolved_cache == "<unset>", resolved_cache


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
