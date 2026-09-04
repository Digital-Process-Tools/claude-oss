"""What the generated fragment gate does when it is actually run.

The other workflow tests read the rendered text. This one extracts the gate's own
`run:` body out of the template, puts it in front of a real git repository with a real
base ref, and reads the exit status -- because the defect in #87 is not visible in the
text at all. `git diff --name-only` lists a **deletion** identically to an addition, so
a pull request that changed product code and removed somebody else's pending fragment
passed green, and the receipt named the file being deleted as the evidence that a
fragment was present.

The fix is not `--diff-filter=AM`. That closes the bypass and blocks every release cut,
because a release legitimately deletes every fragment it folds into `CHANGELOG.md` and
adds none. So the cases below are a matched set and have to be read together: the
release cut is the one that fails if somebody reaches for the one-flag fix.

Deliberately not a YAML parse -- the block this extracts is the block a maintainer
reads, and the assertion is about that text rather than about the structure a real
parser would build.

Python 3.9 compatible.
"""

import atexit
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scaffold  # noqa: E402


# ------------------------------------------------------------ finding a usable shell
#
# `subprocess.run(["bash", ...])` is not a question about bash. It is a question about
# whichever `bash` the machine happened to expose first, and on a GitHub Windows runner
# that is WSL's `bash.exe` in the system directory -- which CreateProcess reaches before
# anything on PATH. It spawns, prints "Windows Subsystem for Linux has no installed
# distributions." in UTF-16, and exits 1. Read as a return code that is the gate
# failing. It is not: it is the gate never having run, reported as a product verdict.
#
# So three states, not two: the gate ran and passed, the gate ran and failed, and no
# usable shell was available. The third is decided by MEASUREMENT -- every candidate is
# spawned and asked to behave like a shell -- because WSL's binary is called `bash.exe`
# too and a name match cannot tell them apart. There is no platform branch below: the
# same enumeration and the same probe run everywhere, and on POSIX the first candidate
# is still the `bash` on PATH.

# Asked of every candidate. Each line is its own claim, so a shell that exists but
# cannot reach one of the tools these steps need says which one. The interpreter check
# runs the interpreter rather than looking the name up: a `python3` that will not start
# is the same absence as no `python3` at all.
_PROBE = (
    "printf shell\n"
    "git --version >/dev/null 2>&1 && printf ' git'\n"
    "python3 -c pass >/dev/null 2>&1 && printf ' python3'\n"
    "echo x | grep -E x >/dev/null 2>&1 && printf ' grep'\n"
    "echo x | sed 's/x/y/' >/dev/null 2>&1 && printf ' sed'\n"
)


def _python3_shim():
    """A `python3` that is the interpreter running these tests, for a shell to find.

    It answers two things at once. A platform may ship the interpreter under another
    name -- Windows installs `python.exe`, and whether a `python3.exe` sits beside it
    is a fact about one installer rather than about the platform -- and the extracted
    step should run under the interpreter the suite is running under rather than
    whichever one the machine puts first.

    One file in its own directory, so pinning it moves nothing else. That it actually
    runs, and runs the right interpreter, is asserted below rather than assumed: a
    shim that does not start would otherwise turn into a skip that reads like a
    platform limit.
    """
    directory = tempfile.mkdtemp(prefix="oss-gate-shim-")
    atexit.register(shutil.rmtree, directory, True)
    shim = Path(directory) / "python3"
    shim.write_text(
        "#!/bin/sh\nexec '{}' \"$@\"\n".format(Path(sys.executable).as_posix()),
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return directory


_SHIM_DIR = _python3_shim()

#: An empty, isolated `gh` config directory (#777) -- see `_child_env`'s own comment
#: for why this is not simply "unset the token env vars".
_GH_CONFIG_DIR = tempfile.mkdtemp(prefix="oss-gate-gh-config-")
atexit.register(shutil.rmtree, _GH_CONFIG_DIR, True)


def _companion_dirs(shell):
    """Where the tools that ship WITH a given shell live, derived from where that
    shell actually is rather than from an install path guessed for a platform.

    `bash -c` is neither a login nor an interactive shell, so it reads no profile: the
    PATH it gets is exactly the one handed to it. Under Git for Windows that is the
    difference between reaching `grep` and `sed` and not -- they sit in the
    installation's own `usr/bin`, not beside `bash.exe`.
    """
    if not shell:
        return []
    home = Path(shell).resolve().parent
    found = [str(home)] if home.is_dir() else []
    # Ancestors, not just the parent: the shell can be `<root>/bin/bash.exe` or
    # `<root>/usr/bin/bash.exe`, and assuming the first spells `<root>` as `<root>/usr`
    # for the second -- putting the search one directory too high, which is a mistake
    # this repository has already made once in the changelog assembler.
    for root in list(home.parents)[:3]:
        for rel in ("usr/bin", "mingw64/bin", "bin"):
            candidate = root.joinpath(*rel.split("/"))
            if candidate.is_dir() and str(candidate) not in found:
                found.append(str(candidate))
    return found


def _child_env(shell=None, **extra):
    """The environment every shell started by this file gets.

    Inherited rather than pinned to POSIX literals. The pinned `/usr/bin:/bin` named
    directories that do not exist on Windows, so even the right shell would have found
    no git there -- and an env dict stripped of the platform's own variables is not one
    a Windows runner reliably starts a process with at all. The one thing still pinned
    is which `python3` wins: the interpreter running the tests, which is what pinning
    the PATH was for.

    The shell is passed in so a candidate is PROBED with the same environment it will
    later be RUN with. Probing under a richer PATH than the run gets is how a green
    probe turns into a red step.
    """
    env = dict(os.environ)
    # The shim directory holds one file, `python3`, so putting it first pins the
    # interpreter WITHOUT moving which git, grep or sed the script reaches. Prepending
    # the interpreter's own directory instead would have pinned all four, and a venv
    # or conda prefix carrying its own `git` would have been used without anything
    # saying so.
    env["PATH"] = os.pathsep.join(
        [_SHIM_DIR] + _companion_dirs(shell) + [env.get("PATH", "")]
    )
    # #777: the gate step now reads labels live via `gh api`, which reads credentials
    # from these two variables (or a `gh auth login` config this process does not
    # touch). Left inherited, a maintainer's own authenticated `gh` would make these
    # tests perform a REAL network call against a repo/PR number a fixture invented --
    # slow, flaky under no network, and answering from github.com rather than from the
    # fixture the test built. Stripped here so every test gets the fast, offline,
    # deterministic failure `gh` itself gives with no credentials (~30ms, no socket),
    # which is exactly the DEGRADE path the gate is required to have -- a test that
    # wants the LIVE path installs its own `gh` shim on PATH instead (#777).
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    # `GH_TOKEN`/`GITHUB_TOKEN` are not the only route to real credentials -- `gh auth
    # login` stores them under `GH_CONFIG_DIR` (`$XDG_CONFIG_HOME/gh` by default), and
    # the two env vars above take precedence over that store ONLY when set. Pointed at
    # an empty directory this process owns rather than left to default, so a machine
    # that has run `gh auth login` for its maintainer's own account cannot make `gh`
    # authenticate here either.
    env["GH_CONFIG_DIR"] = _GH_CONFIG_DIR
    # A `gh` shim that isn't reached at all (no network, no credentials) answers in
    # milliseconds, so this is a safety margin against a slow one, not a budget the
    # suite is meant to spend. A test exercising the LIVE path overrides it.
    env.setdefault("LABEL_READ_TIMEOUT", "5")
    env.update(extra)
    return env


def _bash_candidates():
    """Every plausible shell, best-first.

    Nothing here is an install path guessed for a platform: PATH is read, and Git's
    own shell is derived from where `git` actually is, so a runner that puts Git
    somewhere unusual is still covered.
    """
    seen = []

    def add(path):
        # A PATH entry does not have to be a well-formed path, and a Windows one
        # regularly is not. A candidate that cannot even be spelled is not a reason
        # for the whole file to error out before it has looked at the next one.
        try:
            if path and str(path) not in seen and Path(path).is_file():
                seen.append(str(path))
        except (OSError, ValueError):
            pass

    add(os.environ.get("OSS_TEST_BASH"))
    add(shutil.which("bash"))
    # Every bash on PATH, not only the first: on Windows the first is WSL's.
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry:
            for name in ("bash", "bash.exe"):
                add(Path(entry) / name)
    # Git ships a shell beside itself, and a Windows runner always has Git.
    git = shutil.which("git")
    if git:
        home = Path(git).resolve().parent
        for base in (home, home.parent):
            for rel in ("bash", "bash.exe", "bin/bash", "bin/bash.exe",
                        "usr/bin/bash", "usr/bin/bash.exe"):
                add(base / rel)
    return seen


def _probe_shell(candidate):
    """Spawn it and see. Returns (the tools it reached, a line saying what happened)."""
    try:
        done = subprocess.run(
            [str(candidate), "-c", _PROBE],
            env=_child_env(candidate),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            errors="replace",
            timeout=120,
        )
    except OSError as exc:
        return (), "not spawnable: {}".format(exc)
    except subprocess.TimeoutExpired:
        return (), "spawned and never answered"
    return _classify(done.returncode, done.stdout)


def _classify(returncode, stdout):
    """The verdict on one answer, split out so it can be tested against the exact
    reply a Windows runner produced without needing that runner."""
    # WSL answers in UTF-16; dropping the interleaved NULs is what makes its refusal
    # readable in the skip reason instead of a wall of nul bytes.
    said = " ".join((stdout or "").replace("\x00", "").split())
    if returncode != 0 or "shell" not in said.split():
        return (), "exit {}: {}".format(returncode, said[:120] or "(said nothing)")
    return tuple(said.split()), "ok, reached: " + said


_ATTEMPTS = [(candidate, _probe_shell(candidate)) for candidate in _bash_candidates()]


def _pick_shell(attempts):
    """The first shell that reached the most of what these steps call.

    Not the first one that started: on a Windows runner the first that starts may be
    the one that reaches nothing, and a suite run through it would be measuring the
    machine rather than the gate. `max` keeps the earliest of any tie, so on POSIX the
    `bash` on PATH is still what runs.
    """
    usable = [(c, tools) for c, (tools, _note) in attempts if tools]
    if not usable:
        return (None, ())
    return max(usable, key=lambda pair: len(pair[1]))


BASH, BASH_REACHED = _pick_shell(_ATTEMPTS)

# Named so the log says WHICH of the three states happened. A bare "no bash" fires
# identically on a platform where this is genuinely untestable and on one where the
# shell was merely looked for in the wrong place, and nobody could tell them apart.
# `-rs` is in this repo's addopts, so the reason reaches the CI log.
def _shell_report(attempts):
    if not attempts:
        return (
            "no usable shell: no candidate was found to try. PATH carries no bash, "
            "and git -- which ships one beside itself -- is at {}.".format(
                shutil.which("git") or "(nowhere on PATH)"
            )
        )
    return "no usable shell. Spawned each candidate and asked it to behave like one: " + (
        "; ".join("{} -> {}".format(c, note) for c, (_tools, note) in attempts)
    )


SHELL_REPORT = _shell_report(_ATTEMPTS)


def _require(tool):
    """Deliberately not a module-level `pytestmark`.

    A blanket skip on `BASH is None` would take the probe's OWN controls down with
    the steps that need a shell -- and those controls are the only thing standing
    between "no usable shell here" and "the probe has quietly started rejecting
    everything, everywhere". A skip that hides its own alarm is the defect this file
    is fixing, one level down. So the tests that read the rendered text and the tests
    that measure the probe always run, and only the ones that start a shell skip.

    A shell can also be usable and still not reach what a given step calls, so the
    reason names which tool and which shell rather than leaving a step that never ran
    looking like a step that passed.
    """
    if BASH is None:
        pytest.skip(SHELL_REPORT)
    if tool not in BASH_REACHED:
        pytest.skip(
            "the shell found ({}) cannot reach {}; it reached: {}".format(
                BASH, tool, " ".join(BASH_REACHED) or "nothing"
            )
        )


GENERATED_WORKFLOW = ".github/workflows/oss-changelog.yml"

GATE_STEP = "- name: A user-visible change carries a fragment"

LINKS_STEP = "- name: CHANGELOG.md's link refs agree with its release headings"


def _config(**overrides):
    config = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "worktree_root": "/src/name-wt",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": ["README.md"],
        "changelog_dir": "changelog.d",
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "state_file": ".max/oss-watch.json",
    }
    config.update(overrides)
    return config


def _step_script(step, config=None):
    """One step's shell body, dedented, ready to hand to bash.

    `config` defaults to this module's own `_config()` -- the shape every existing
    caller already relied on -- but a caller that needs a non-default `.oss.json`
    key rendered into the workflow (`user_visible_paths` in #996, for example) can
    pass one instead of reimplementing this extraction against its own config.
    """
    body = scaffold.render_owned(GENERATED_WORKFLOW, config if config is not None else _config())
    lines = body.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == step]
    assert len(starts) == 1, "expected exactly one {!r} step, found {}".format(
        step, len(starts)
    )
    start = starts[0]
    runs = [i for i in range(start + 1, len(lines)) if lines[i].strip() == "run: |"]
    assert runs, "the gate step has no `run: |` block"
    head = runs[0]
    indent = len(lines[head]) - len(lines[head].lstrip())
    block = []
    for line in lines[head + 1:]:
        if not line.strip():
            block.append("")
            continue
        if len(line) - len(line.lstrip()) <= indent:
            break
        block.append(line)
    assert block, "the step's `run: |` block is empty"
    return textwrap.dedent("\n".join(block)) + "\n"


def _gate_script(config=None):
    return _step_script(GATE_STEP, config)


def _git(repo, *args):
    # The fixture repositories are built by this process, not by the extracted step,
    # so `git` missing here is a third state of its own -- and without this it would
    # arrive as a spawn error from deep inside a fixture, which reads like the gate
    # crashing. Every fixture funnels through this one call.
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH, so there is no repository to run the gate over")
    return subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        check=True,
    ).stdout


def _write(repo, files):
    for name, content in files.items():
        target = repo / name
        if content is None:
            if target.exists():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


BASE = {
    "README.md": "# a repo\n",
    "CHANGELOG.md": "# Changelog\n\n## [Unreleased]\n",
    "src.py": "value = 1\n",
    "docs/guide.md": "a sentence\n",
    "changelog.d/906.added.md": "- somebody else's pending entry (#906).\n",
}


def _pull_request(tmp_path, head_files):
    """A repo whose HEAD differs from `origin/main` by exactly `head_files`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _write(repo, BASE)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    # The gate diffs against `origin/$BASE_REF`; no remote is needed for that ref to
    # exist, only the ref itself.
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    _write(repo, head_files)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "head")
    return repo


def _run_script(script, cwd, env):
    """Run `script` through BASH from a FILE, never via `bash -c "<script>"`.

    `bash -c "<script>"` makes Windows agree with itself twice: Python builds the
    child's command line with `subprocess.list2cmdline` (the MSVCRT /
    `CommandLineToArgvW` quoting convention), and Git-for-Windows' bundled MSYS2
    `bash.exe` then re-parses that reconstructed command line with its own,
    not-identical rules -- a second, independent quoting pass over a ~9KB script
    full of quotes, parens and semicolons. A bare path argument is the one shape
    both sides already agree on without either re-quoting anything, so the script
    is written to disk and run as `bash <path>` instead. This is the untested
    hypothesis from PR #992's own body, implemented so CI's real Windows legs can
    confirm or refute it, not a confirmed root cause.

    `newline="\n"` is deliberate: `Path.write_text`'s platform default would
    translate every embedded `\n` to `\r\n` on Windows, trading the CRLF
    corruption already ruled out for the in-memory `-c` string for a fresh one
    introduced by writing the file.
    """
    fd, path = tempfile.mkstemp(prefix="oss-gate-script-", suffix=".sh")
    try:
        with os.fdopen(fd, "w", newline="\n", encoding="utf-8") as handle:
            handle.write(script)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return subprocess.run(
            [BASH, path],
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            errors="replace",
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _run_gate(repo):
    for tool in ("git", "grep", "sed"):
        _require(tool)
    return _run_script(_gate_script(), repo, _child_env(BASH, BASE_REF="main"))


# ------------------------------------------------------- the shell probe's own controls
#
# The probe decides whether anything below ran at all, so it needs its own matched
# pair: an answer that must be rejected and an answer that must be accepted. Without
# the second, a probe that rejected everything would look like a careful probe.

# Byte for byte what a GitHub Windows runner replied when `bash` resolved to WSL's
# binary: UTF-16, read back through a text pipe, which is where the interleaved NULs
# in the CI log came from.
WSL_REFUSAL = (
    "Windows Subsystem for Linux has no installed distributions.\n"
    .encode("utf-16-le")
    .decode("latin-1")
)


def test_the_probe_rejects_the_answer_a_windows_runner_actually_gave():
    tools, note = _classify(1, WSL_REFUSAL)
    assert tools == (), note
    assert "Windows Subsystem for Linux" in note, note
    assert "\x00" not in note, "the reason is unreadable in the log: " + repr(note)


def test_the_probe_accepts_a_shell_that_answers():
    """The must-fire half of the pair above."""
    tools, note = _classify(0, "shell git python3")
    assert tools == ("shell", "git", "python3"), note


def test_a_shell_that_exits_clean_but_says_nothing_is_not_read_as_a_pass():
    """Exit 0 and silence is the shape a broken harness produces, and it must not be
    the shape a working shell is recognised by."""
    assert _classify(0, "")[0] == ()


def test_the_probe_rejects_a_spawnable_binary_that_is_not_a_shell():
    """Spawned, not name-matched. The interpreter running these tests starts fine and
    is not a shell; WSL's binary is called `bash.exe` and is not a shell either, and
    only one of those two facts is visible in a filename."""
    tools, note = _probe_shell(sys.executable)
    assert tools == (), note


def test_the_probe_accepts_the_shell_it_chose():
    """The must-fire half again, this time through a real spawn."""
    _require("shell")
    tools, note = _probe_shell(BASH)
    assert "shell" in tools, note


def test_the_probe_accepts_anything_this_test_independently_confirms_is_a_shell():
    """The alarm on the alarm, and the reason none of this is a module-level skip.

    A probe that started rejecting everything would make every step below SKIP -- on
    every platform, quietly, with the gate never executed and CI green. So each
    candidate is checked here by a measure the probe does not use: a shell, and only a
    shell, exits 7 when told to. Anything that passes that must pass the probe.
    """
    confirmed = []
    for candidate in _bash_candidates():
        try:
            done = subprocess.run(
                [candidate, "-c", "exit 7"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                errors="replace",
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if done.returncode != 7:
            continue
        confirmed.append(candidate)
        tools, note = _probe_shell(candidate)
        assert "shell" in tools, (
            "{} runs shell scripts, and the probe rejected it: {}".format(candidate, note)
        )
    if not confirmed:
        pytest.skip("nothing on this machine behaves like a shell. " + SHELL_REPORT)
    assert BASH is not None, (
        "a working shell was confirmed here and the file still chose none: " + SHELL_REPORT
    )


def test_the_shell_runs_the_interpreter_that_is_running_these_tests():
    """The shim is load-bearing on any platform without a `python3` of its own, and a
    shim that does not start would show up as a skip that reads like a platform limit.
    Measured rather than assumed."""
    _require("python3")
    done = subprocess.run(
        [BASH, "-c", "python3 -c 'import sys; print(sys.prefix)'"],
        env=_child_env(BASH),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        errors="replace",
    )
    assert done.returncode == 0, done.stdout
    assert done.stdout.strip() == sys.prefix, (
        "the shell reached a different interpreter: " + done.stdout
    )


def test_the_tools_beside_a_shell_are_found_from_either_install_layout(tmp_path):
    """Git for Windows keeps `grep` and `sed` in the installation's own `usr/bin`,
    which is neither beside `bash.exe` nor one directory above it. Deriving the root
    from the shell's parent alone works for `<root>/bin/bash` and silently searches
    `<root>/usr/usr/bin` for `<root>/usr/bin/bash` -- one directory too high, found by
    review."""
    root = tmp_path / "Git"
    for rel in ("bin", "usr/bin", "mingw64/bin"):
        (root / rel).mkdir(parents=True)
    for layout in ("bin/bash", "usr/bin/bash"):
        shell = root / layout
        shell.write_text("#!/bin/sh\n", encoding="utf-8")
        found = _companion_dirs(str(shell))
        for expected in ("usr/bin", "mingw64/bin", "bin"):
            # Resolved, because the derivation resolves and a temp directory is a
            # symlink on macOS -- a comparison against the unresolved path would fail
            # for a reason that has nothing to do with the layout under test.
            assert str(root.resolve().joinpath(*expected.split("/"))) in found, (
                "{}: {} missing from {}".format(layout, expected, found)
            )


def test_no_shell_means_no_companion_directories_rather_than_a_guess():
    assert _companion_dirs(None) == []


def test_a_candidate_that_is_not_there_is_reported_rather_than_raised():
    tools, note = _probe_shell(str(REPO_ROOT / "definitely-not-a-shell"))
    assert tools == ()
    assert note, "a candidate was dropped without saying why"


def test_no_usable_candidate_is_no_shell_at_all_rather_than_a_shell():
    """The third state itself. Every candidate spawned and none of them a shell has
    to end as `None`, because falling back to the last one tried would run the suite
    against WSL and report the result as the gate's verdict."""
    refused = [("C:/Windows/System32/bash.exe", ((), "exit 1: " + WSL_REFUSAL[:20]))]
    assert _pick_shell(refused) == (None, ())
    assert "no usable shell" in _shell_report(refused)
    assert "System32" in _shell_report(refused)


def test_a_usable_shell_below_an_unusable_one_is_still_the_one_chosen():
    """The must-fire half: rejecting the first candidate must not end the search.
    This is the Windows runner's exact shape -- WSL first, Git for Windows after."""
    attempts = [
        ("C:/Windows/System32/bash.exe", ((), "exit 1: no installed distributions")),
        ("C:/Program Files/Git/bin/bash.exe", (("shell", "git", "python3"), "ok")),
    ]
    assert _pick_shell(attempts)[0] == "C:/Program Files/Git/bin/bash.exe"


def test_a_shell_that_reaches_the_tools_beats_one_that_merely_starts():
    attempts = [
        ("/first/bash", (("shell",), "ok")),
        ("/second/bash", (("shell", "git", "python3"), "ok")),
    ]
    assert _pick_shell(attempts)[0] == "/second/bash"


def test_a_shell_that_reaches_nothing_is_still_better_than_no_shell():
    """And the tests that need a tool it cannot reach skip by name, rather than the
    whole file going quiet."""
    attempts = [("/only/bash", (("shell",), "ok"))]
    assert _pick_shell(attempts) == ("/only/bash", ("shell",))


def test_the_report_with_no_candidate_at_all_says_where_it_looked():
    report = _shell_report([])
    assert "no candidate was found to try" in report, report
    assert "git" in report, report


def test_the_report_names_every_candidate_and_what_it_answered():
    """The skip reason is the whole difference between `no bash` (which would fire
    identically forever on a platform where this is genuinely untestable) and a line
    saying what was searched and what each one said."""
    assert _ATTEMPTS, "not one bash candidate was enumerated on this machine"
    for candidate, (_tools, note) in _ATTEMPTS:
        assert candidate in SHELL_REPORT, SHELL_REPORT
        assert note in SHELL_REPORT, SHELL_REPORT


# ------------------------------------------------------------------ positive controls
#
# Every case below asserts about an exit status, and a gate that crashed on line one
# would produce a non-zero one for three of them. These two say the harness reaches the
# gate's own verdicts at all.


def test_the_gate_script_extracts_and_is_not_empty():
    script = _gate_script()
    assert "git diff" in script, script


def test_a_normal_pull_request_with_a_fragment_passes(tmp_path):
    repo = _pull_request(
        tmp_path,
        {"src.py": "value = 2\n", "changelog.d/925.fixed.md": "- a fix (#925).\n"},
    )
    result = _run_gate(repo)
    assert result.returncode == 0, result.stdout
    assert "925.fixed.md" in result.stdout


def test_a_pull_request_with_no_fragment_at_all_is_refused(tmp_path):
    repo = _pull_request(tmp_path, {"src.py": "value = 2\n"})
    result = _run_gate(repo)
    assert result.returncode != 0, result.stdout


# --------------------------------------------------------------------------- the bypass


def test_deleting_someone_elses_fragment_does_not_satisfy_the_gate(tmp_path):
    """#87 / upstream #925. Product code changes, a pending fragment disappears, and
    nothing is added. The gate used to print `Fragment present:` and name the file it
    was removing.
    """
    repo = _pull_request(
        tmp_path,
        {"src.py": "value = 2\n", "changelog.d/906.added.md": None},
    )
    result = _run_gate(repo)
    assert result.returncode != 0, result.stdout
    assert "Fragment present" not in result.stdout, (
        "the receipt named the deleted fragment as evidence one is present:\n"
        + result.stdout
    )


def test_adding_your_own_fragment_does_not_licence_deleting_somebody_elses(tmp_path):
    """What pins the branch ORDER inside the gate, and nothing else does.

    Found by review: with the deletion branch moved below the "was anything added"
    branch, every other test in this file still passed, and this shape went green
    printing `Fragment present:` over a receipt that named the entry it was dropping.
    A pull request may announce its own change and still not be entitled to remove
    somebody else's.
    """
    repo = _pull_request(
        tmp_path,
        {
            "src.py": "value = 2\n",
            "changelog.d/906.added.md": None,
            "changelog.d/925.fixed.md": "- a fix (#925).\n",
        },
    )
    result = _run_gate(repo)
    assert result.returncode != 0, result.stdout
    assert "906.added.md" in result.stdout, result.stdout
    assert "deleted" in result.stdout, result.stdout


def test_deleting_a_fragment_and_nothing_else_is_refused(tmp_path):
    """The plainest instance, and the one a `shipped`-paths gate would wave through:
    losing a fragment needs no code change to go with it.
    """
    repo = _pull_request(tmp_path, {"changelog.d/906.added.md": None})
    result = _run_gate(repo)
    assert result.returncode != 0, result.stdout


# ------------------------------------------------------- and why the one-flag fix fails


def test_a_release_cut_passes(tmp_path):
    """Deletions plus a rewritten CHANGELOG.md. This is the case `--diff-filter=AM`
    turns red, and it is why the fix has to be two diffs.
    """
    repo = _pull_request(
        tmp_path,
        {
            "CHANGELOG.md": "# Changelog\n\n## [1.0.0]\n\n- somebody else's entry.\n",
            "changelog.d/906.added.md": None,
        },
    )
    result = _run_gate(repo)
    assert result.returncode == 0, result.stdout
    # The receipt, not just the status: a gate that fell out of the "Fragment
    # present" branch by accident would also be zero here.
    assert "Release cut" in result.stdout, result.stdout
    assert "906.added.md" in result.stdout, result.stdout


def test_a_release_cut_that_also_carries_its_own_fragment_reports_both(tmp_path):
    """A release that also announces something is legitimate, and a receipt that prints
    only the half it added is the shape this gate exists to refuse.
    """
    repo = _pull_request(
        tmp_path,
        {
            "CHANGELOG.md": "# Changelog\n\n## [1.0.0]\n\n- somebody else's entry.\n",
            "changelog.d/906.added.md": None,
            "changelog.d/925.fixed.md": "- a fix (#925).\n",
        },
    )
    result = _run_gate(repo)
    assert result.returncode == 0, result.stdout
    assert "906.added.md" in result.stdout, result.stdout
    assert "925.fixed.md" in result.stdout, result.stdout


def test_nothing_changed_against_the_base_is_skipped_not_a_finding(tmp_path):
    """The third state. An empty diff is the gate being unable to look, not a pull
    request that forgot its fragment.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _write(repo, BASE)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    result = _run_gate(repo)
    assert result.returncode == 0, result.stdout
    assert "skipped" in result.stdout, result.stdout


# -------------------------------------------------------- the two guards lost in #88


def test_the_workflow_re_dispatches_when_the_escape_label_is_applied():
    """The failure message tells you to label the pull request `no-changelog`. With
    GitHub's default event set -- opened, synchronize, reopened -- applying it starts no
    run, and a re-run replays the original payload, so the label is invisible to that
    too. The remedy the gate prints has to be a remedy.
    """
    body = scaffold.render_owned(GENERATED_WORKFLOW, _config())
    assert "no-changelog" in body, "the escape hatch is not named -- this is vacuous"
    types = [line.strip() for line in body.splitlines() if line.strip().startswith("types:")]
    assert types, "`on: pull_request:` carries no `types:` -- " + body
    assert "labeled" in types[0], types
    assert "unlabeled" in types[0], types
    for required in ("opened", "synchronize", "reopened"):
        assert required in types[0], (
            "naming any type replaces the default set, so " + required + " has to be "
            "listed explicitly: " + types[0]
        )


def test_the_workflow_audits_the_changelog_link_refs():
    """`--check-links` is implemented in the assembler and was never invoked, so
    CHANGELOG.md's link-reference definitions stopped being audited per pull request and
    the run that found them stale became the run cutting the tag.
    """
    body = scaffold.render_owned(GENERATED_WORKFLOW, _config())
    assert "--check-links" in body, body


def _links_repo(tmp_path, changelog):
    """A repo carrying the vendored assembler where the generated step expects it."""
    repo = tmp_path / "repo"
    (repo / scaffold.OWNED_DIR).mkdir(parents=True)
    (repo / scaffold.OWNED_DIR / "assemble_changelog.py").write_text(
        (REPO_ROOT / "scripts" / "assemble_changelog.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repo / "changelog.d").mkdir()
    if changelog is not None:
        (repo / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return repo


def _run_links(repo):
    _require("python3")
    return _run_script(_step_script(LINKS_STEP), repo, _child_env(BASH))


STALE = """# Changelog

## [1.0.0] - 2026-01-01

- a thing.
"""

AUDITED = STALE + """
[Unreleased]: https://github.com/owner/name/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/owner/name/releases/tag/v1.0.0
"""


def test_a_stale_link_ref_table_is_a_finding(tmp_path):
    """The positive control, and the whole reason the step was added. Without it the
    two checks below could be passing because the step does nothing at all.
    """
    result = _run_links(_links_repo(tmp_path, STALE))
    assert result.returncode != 0, result.stdout
    assert "1.0.0" in result.stdout, result.stdout


def test_an_audited_link_ref_table_passes(tmp_path):
    result = _run_links(_links_repo(tmp_path, AUDITED))
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    "changelog", [None, "# Changelog\n\n## [Unreleased]\n"], ids=["absent", "pre-release"]
)
def test_a_repo_that_has_not_cut_a_release_is_skipped_not_red(tmp_path, changelog):
    """`check_links` returns SKIPPED (exit 1), not OK, when there is no `## [x.y.z]`
    heading to audit refs against or no CHANGELOG.md at all -- and the scaffold creates
    neither. A step that treated that as a finding would redden every pull request in a
    freshly scaffolded repo, and it sits above the fragment gate, so the gate this
    change exists to fix would never run there. Found by review.
    """
    result = _run_links(_links_repo(tmp_path, changelog))
    assert result.returncode == 0, result.stdout
    assert "skipped" in result.stdout, (
        "it passed without saying it could not look:\n" + result.stdout
    )


@pytest.mark.parametrize("mode", ["--check", "--check-links"])
def test_every_assembler_invocation_is_scoped_to_the_managed_repo(mode):
    """`assemble_changelog.py` derives its root by walking up for a `.git`, so a run
    given neither `--dir` nor `--changelog` can resolve somewhere else entirely. The
    added step has to carry the same arguments as the one beside it.
    """
    body = scaffold.render_owned(GENERATED_WORKFLOW, _config())
    lines = [line for line in body.splitlines() if mode + " " in line]
    assert lines, mode + " is never invoked"
    for line in lines:
        assert "--changelog CHANGELOG.md" in line, line
