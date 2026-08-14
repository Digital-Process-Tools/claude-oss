"""`bin/oss-workspace` — clone a repo, run one command, be working.

It opens a session over **the repo you are standing in**, not over the plugin's own
checkout. That is the whole difference from the launcher this borrows its lessons from,
and it is why the plugin root is resolved from the script's location while the working
directory is left exactly where the caller put it.

Every test runs the real script with a stub `claude` on PATH that records its argv. A
launcher tested by reading it is a launcher nobody has run.
"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import shell_probe

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "bin" / "oss-workspace"

# The shell is chosen by MEASUREMENT, not by `shutil.which("bash")`. That answers
# with whatever is called `bash` first, and on a Windows runner that is regularly
# WSL's `bash.exe` out of System32 -- a real shell that has never heard of the `C:`
# paths this suite hands it. Every assertion below would then fail as a bug in
# `oss-workspace`, which is a red leg in a file that never claimed to be about
# binary resolution.
#
# The interpreter is a witness alongside the launcher because `run()` pins it onto
# the child's PATH by absolute path: a shell that cannot see it starves the launcher
# of a python, and the channel assertions fail against a fixture problem wearing a
# product bug's clothes.
_ATTEMPTS = shell_probe.attempts([LAUNCHER, Path(sys.executable)])
BASH = shell_probe.pick(_ATTEMPTS)
SHELL_REPORT = shell_probe.report(_ATTEMPTS)

# `git` is NOT probed, and that is the narrower claim rather than an oversight: it
# is run by THIS process to `git init` a fixture, never handed to the shell, and
# nothing in System32 is called `git`. Resolving it by name is measuring the right
# thing here.
GIT = shutil.which("git")


def _require_shell():
    """Deliberately not a module-level `pytestmark`.

    `test_the_script_is_posix_sh_not_bash` reads the launcher's source text and
    spawns nothing. A file-wide skip took it down with the rest, so a machine with
    no shell reported a green run that had measured nothing at all.
    """
    if BASH is None:
        pytest.skip(SHELL_REPORT)


def _require_git():
    if GIT is None:
        pytest.skip("no git on PATH, so no repository can be built to open a session over")


def _executable(path, text):
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _stub_claude(bindir, argv_log, mcp_get=None):
    """A `claude` that records argv and exits 0, so exec is observable.

    `claude mcp ...` is answered rather than recorded in the argv log: those calls
    are the script probing and configuring, not the session it opens, and mixing
    them into the argv log makes every assertion about the launch read the wrong
    list. They go to a log of their own instead, because whether a stale
    registration was re-pointed is only visible in what the script asked
    `claude mcp` to do -- the launch argv looks identical either way.

    `mcp_get` is the text `claude mcp get` prints. None makes it exit non-zero the
    way it does when nothing is registered yet, so the first-registration path is
    the one under test.
    """
    mcp_log = bindir / "mcp.txt"
    get_file = bindir / "mcp_get.txt"
    if mcp_get is None:
        if get_file.exists():
            get_file.unlink()
    else:
        get_file.write_text(mcp_get, encoding="utf-8")
    return _executable(
        bindir / "claude",
        '#!/bin/sh\n'
        'if [ "${1:-}" = "mcp" ]; then\n'
        '    for a in "$@"; do printf "%s\\n" "$a" >> "' + str(mcp_log) + '"; done\n'
        '    printf "%s\\n" "--" >> "' + str(mcp_log) + '"\n'
        '    if [ "${2:-}" = "get" ]; then\n'
        '        [ -f "' + str(get_file) + '" ] || exit 1\n'
        '        cat "' + str(get_file) + '"\n'
        '        exit 0\n'
        '    fi\n'
        '    exit 0\n'
        'fi\n'
        'for a in "$@"; do printf "%s\\n" "$a" >> "' + str(argv_log) + '"; done\n'
        'exit 0\n',
    )


def _mcp_get_output(args, command="bun"):
    """What `claude mcp get NAME` prints for a local-scope stdio entry, copied from
    claude 2.1.219 rather than imagined. Only Command and Args carry the comparison;
    the neighbouring lines are kept so a parser leaning on them is exercised too.
    """
    return (
        "oss-channel:\n"
        "  Scope: Local config (private to you in this project)\n"
        "  Status: Connected\n"
        "  Type: stdio\n"
        "  Command: %s\n"
        "  Args: %s\n"
        "  Environment:\n" % (command, args)
    )


def _consumer_path(cwd):
    """Where `_with_channel_consumer` plants the consumer, which is the path the
    launcher has to end up registered against.
    """
    return (
        Path(cwd) / "_home" / ".claude" / "plugins" / "cache" / "dpt-plugins"
        / "supertool" / "9.9.9" / "notifiers" / "claude-channel" / "channel.ts"
    )


def _mcp_calls(cwd):
    """Every `claude mcp ...` invocation the launcher made, as a list of argv lists."""
    log = Path(cwd) / "_stubbin" / "mcp.txt"
    if not log.exists():
        return []
    return [
        call.strip().split("\n")
        for call in log.read_text(encoding="utf-8").split("--\n")
        if call.strip()
    ]


def _with_channel_consumer(home, bindir):
    """Plant what the script needs to register a channel: a `bun`, and a supertool
    plugin whose install path holds the consumer.

    The path is read from installed_plugins.json rather than globbed out of the
    cache, so the fixture writes that registry -- a glob answers with whichever
    version sorts last, and that is a version the session is not running.
    """
    _executable(bindir / "bun", "#!/bin/sh\nexit 0\n")
    install = home / ".claude" / "plugins" / "cache" / "dpt-plugins" / "supertool" / "9.9.9"
    consumer = install / "notifiers" / "claude-channel" / "channel.ts"
    consumer.parent.mkdir(parents=True)
    consumer.write_text("// stub\n", encoding="utf-8")
    registry = home / ".claude" / "plugins" / "installed_plugins.json"
    registry.write_text(
        json.dumps({
            "version": 2,
            "plugins": {
                "supertool@dpt-plugins": [
                    {"scope": "user", "installPath": str(install), "version": "9.9.9"}
                ]
            },
        }),
        encoding="utf-8",
    )
    return consumer


def run(cwd, args=(), with_claude=True, with_channel=False, mcp_get=None):
    _require_shell()
    bindir = Path(cwd) / "_stubbin"
    bindir.mkdir(exist_ok=True)
    argv_log = Path(cwd) / "argv.txt"
    if with_claude:
        _stub_claude(bindir, argv_log, mcp_get=mcp_get)

    # HOME is pinned for the same reason PATH is: the consumer is looked up under
    # the user's real ~/.claude, so an unpinned HOME decides the channel assertions
    # by whether the developer running the suite happens to have supertool
    # installed -- green on the author's machine, red on a contributor's.
    home = Path(cwd) / "_home"
    (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
    if with_channel:
        _with_channel_consumer(home, bindir)

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env.pop("SUPERTOOL_WATCH_NAME", None)
    # Minimal PATH, deliberately: with the real claude reachable, the "missing
    # claude" case found it and EXECUTED it -- a test suite that launches a live
    # agent session in a temp directory. Only the stub, the interpreter and the
    # system utilities the script needs are on PATH here.
    #
    # The interpreter's directory is on it because the launcher needs a python to
    # read the channel name and find the consumer. `/usr/bin` and `/bin` are Git
    # Bash's on Windows and hold no python at all, so pinning to those alone
    # starved the launcher of one -- it then said so correctly, and the channel
    # assertions failed against a fixture problem wearing a product bug's clothes.
    env["PATH"] = os.pathsep.join(
        [str(bindir), str(Path(sys.executable).parent), "/usr/bin", "/bin"]
    )
    done = subprocess.run(
        [BASH, str(LAUNCHER), *args],
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    argv = argv_log.read_text(encoding="utf-8").splitlines() if argv_log.exists() else []
    return done, argv


def _repo(tmp_path, with_config=True):
    _require_git()
    subprocess.run([GIT, "init", "-q", str(tmp_path)], check=True)
    if with_config:
        (tmp_path / ".oss.json").write_text('{"repo": "owner/name"}', encoding="utf-8")
    return tmp_path


def test_refuses_outside_a_git_repository(tmp_path):
    """The directory is the selection. Somewhere that is not a repo is a mistake worth
    naming, not something to open a session over.
    """
    done, argv = run(tmp_path)
    assert done.returncode != 0
    assert "not a git" in done.stderr.lower()
    assert argv == []


def test_opens_the_repo_you_are_standing_in(tmp_path):
    done, argv = run(_repo(tmp_path))
    assert done.returncode == 0
    assert argv, done.stderr


def test_a_repo_with_config_starts_a_tick(tmp_path):
    _, argv = run(_repo(tmp_path))
    assert "/oss:tick" in argv


def test_a_repo_without_config_starts_setup_instead(tmp_path):
    """Ticking against a repo with no config would run on guessed values. Sending the
    first session to setup is the difference between "works after clone" and "works
    after clone, wrongly".
    """
    done, argv = run(_repo(tmp_path, with_config=False))
    assert "/oss:setup" in argv
    assert "/oss:tick" not in argv
    assert "no .oss.json" in done.stderr


def test_arguments_are_passed_through_and_the_prompt_is_not_appended(tmp_path):
    """`claude` reads only its FIRST positional as a prompt and silently ignores later
    ones, and a variadic option swallows whatever follows it. So a prompt appended after
    pass-through arguments is a promise kept in the argv and broken in the parse.
    """
    done, argv = run(_repo(tmp_path), args=["--model", "sonnet"])
    assert "--model" in argv and "sonnet" in argv
    assert "/oss:tick" not in argv


def test_not_appending_the_prompt_is_said_out_loud(tmp_path):
    """The third state. Dropping it silently is what makes the argv and the parse
    disagree with nobody watching.
    """
    done, _ = run(_repo(tmp_path), args=["--model", "sonnet"])
    assert "not appended" in done.stderr.lower()


def test_the_watch_channel_flag_is_passed_once_the_consumer_is_registered(tmp_path):
    """Without it the pollers still spawn and still emit and nothing reads them: a
    board that looks armed and delivers nothing.
    """
    _, argv = run(_repo(tmp_path), with_channel=True)
    assert any("development-channels" in a for a in argv)
    assert "server:oss-channel" in argv


def test_the_prompt_precedes_the_channel_flag(tmp_path):
    """The flag is variadic, so a positional written after it is read as one of its
    values and the launch is REFUSED, not degraded:

        --dangerously-load-development-channels entries must be tagged: /oss:tick

    which is how this script failed the first time it was run for real.
    """
    _, argv = run(_repo(tmp_path), with_channel=True)
    assert argv.index("/oss:tick") < argv.index("--dangerously-load-development-channels")


def test_no_consumer_means_no_flag_rather_than_no_session(tmp_path):
    """`--dangerously-load-development-channels server:NAME` resolves CONFIGURED
    servers only and refuses the launch outright when the name is not one. So a
    session that cannot have a channel opens without one and is told which half is
    missing; the alternative is no session at all.
    """
    done, argv = run(_repo(tmp_path))
    assert argv, done.stderr
    assert not any("development-channels" in a for a in argv)
    assert "channel consumer was not found" in done.stderr


def test_registering_the_consumer_is_said_out_loud(tmp_path):
    """It writes to the user's MCP config. Something that edits your config without
    saying so is something you cannot undo, so the removal command is named.
    """
    done, _ = run(_repo(tmp_path), with_channel=True)
    assert "registered MCP server oss-channel" in done.stderr
    assert "claude mcp remove oss-channel -s local" in done.stderr


def test_a_registration_pointing_at_a_dead_path_is_re_pointed(tmp_path):
    """`claude mcp add` stores an absolute, version-pinned path -- the installPath out
    of installed_plugins.json -- and the plugin cache drops the old version directory
    on auto-update. The entry outlives the file, so `claude mcp get` still answers 0;
    measured against claude 2.1.219, a registration whose target does not exist gets
    exit 0 and a "Failed to connect" status. Testing presence therefore reports a
    board that is armed and delivers nothing, which is the exact state the launcher's
    own header exists to prevent.
    """
    repo = _repo(tmp_path)
    stale = "/home/x/.claude/plugins/cache/dpt-plugins/supertool/0.1.0/notifiers/claude-channel/channel.ts"
    done, argv = run(repo, with_channel=True, mcp_get=_mcp_get_output(stale))

    calls = _mcp_calls(repo)
    assert ["mcp", "remove", "oss-channel", "-s", "local"] in calls, done.stderr
    assert [
        "mcp", "add", "-s", "local", "oss-channel", "bun", str(_consumer_path(repo))
    ] in calls, done.stderr
    assert "server:oss-channel" in argv


def test_the_replaced_path_and_its_replacement_are_both_named(tmp_path):
    """A silent re-point is the other half of the same defect: the config changed
    under the user and the output holds no way to find out what it used to be.
    """
    repo = _repo(tmp_path)
    stale = "/gone/supertool/0.1.0/notifiers/claude-channel/channel.ts"
    done, _ = run(repo, with_channel=True, mcp_get=_mcp_get_output(stale))
    assert stale in done.stderr
    assert str(_consumer_path(repo)) in done.stderr
    assert "claude mcp remove oss-channel -s local" in done.stderr


def test_a_registration_that_already_matches_is_left_alone(tmp_path):
    """The guard against the fix over-firing. A remove-and-add on every launch churns
    the user's MCP config for nothing, which is why presence was the test to begin
    with; comparing is meant to replace that test, not the idempotence it bought.
    """
    repo = _repo(tmp_path)
    done, argv = run(
        repo, with_channel=True, mcp_get=_mcp_get_output(str(_consumer_path(repo)))
    )
    verbs = [call[1] for call in _mcp_calls(repo) if len(call) > 1]
    assert "add" not in verbs, done.stderr
    assert "remove" not in verbs, done.stderr
    assert "server:oss-channel" in argv


def test_a_registration_whose_path_cannot_be_resolved_is_not_counted_as_ready(tmp_path):
    """The third state. With no working python, or a registry that cannot be read,
    there is no resolved path to compare the registration against -- and "it cannot be
    checked" is not "it is fine". The message must not blame a missing consumer
    either: the consumer may well be installed and merely unread.
    """
    repo = _repo(tmp_path)
    done, argv = run(repo, mcp_get=_mcp_get_output("/gone/channel.ts"))
    assert not any("development-channels" in a for a in argv), done.stderr
    assert "could not be resolved" in done.stderr


def test_a_registration_that_cannot_be_parsed_is_not_counted_as_ready(tmp_path):
    """`claude mcp get`'s output shape is nobody's contract. When the Command and Args
    lines are not in it, where the entry points is unknown -- and an unknown reported
    as armed is the defect itself, not a tolerable fallback.
    """
    repo = _repo(tmp_path)
    done, argv = run(
        repo,
        with_channel=True,
        mcp_get="oss-channel:\n  Scope: Local config\n  Status: Connected\n",
    )
    assert not any("development-channels" in a for a in argv), done.stderr
    assert "unknown" in done.stderr
    assert "claude mcp remove oss-channel -s local" in done.stderr


def test_it_survives_being_run_through_a_symlink(tmp_path):
    """The install route is a symlink into a bin directory, so `dirname $0` is that
    directory and not the checkout. Resolving the plugin root from an unwalked $0 is
    the classic way this breaks for everyone except its author.
    """
    _require_shell()
    repo = _repo(tmp_path)
    link = repo / "linked-oss-workspace"
    link.symlink_to(LAUNCHER)
    bindir = repo / "_stubbin"
    bindir.mkdir(exist_ok=True)
    _stub_claude(bindir, repo / "argv.txt")
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(
        [str(bindir), str(Path(sys.executable).parent), "/usr/bin", "/bin"]
    )

    done = subprocess.run(
        [BASH, str(link)],
        cwd=str(repo),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    assert done.returncode == 0, done.stderr


def test_a_repo_with_no_supertool_config_is_told_there_is_no_board(tmp_path):
    """The channel flag makes the session able to RECEIVE events. It does not make
    anything publish them. Saying "armed" when only half holds is the defect this
    plugin is named after, so the half that is missing is named.
    """
    done, _ = run(_repo(tmp_path))
    assert "no board to watch" in done.stderr


def test_a_repo_with_no_radar_tiers_is_told_the_channel_is_empty(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".supertool.json").write_text('{"presets": ["git"]}', encoding="utf-8")
    done, _ = run(repo)
    assert "nothing publishes to it" in done.stderr
    assert "channel:health" in done.stderr


def test_a_repo_with_radar_tiers_gets_no_warning(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".supertool.json").write_text(
        '{"ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}}', encoding="utf-8"
    )
    done, _ = run(repo)
    assert "no board to watch" not in done.stderr
    assert "nothing publishes to it" not in done.stderr


def test_a_missing_claude_is_a_named_failure(tmp_path):
    done, _ = run(_repo(tmp_path), with_claude=False)
    assert done.returncode != 0
    assert "claude" in done.stderr.lower()


def test_the_script_is_posix_sh_not_bash(tmp_path):
    """It runs on whatever the user has, including Git Bash and a stock macOS shell."""
    text = LAUNCHER.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh")
    # Matched at statement position rather than as a substring. `local ` occurs
    # inside `claude mcp add -s local ...` and inside prose about local scope, and
    # a substring check calls both a bashism. A test that is wrong in the direction
    # of stopping you is still wrong, and it gets edited around rather than heeded.
    for bashism in ("declare", "local", "function"):
        offender = re.search(r"^\s*%s\s" % bashism, text, re.MULTILINE)
        assert offender is None, "%s: %r" % (bashism, offender.group(0))
    assert re.search(r"\[\[", text) is None, "[[ is bash test syntax"
