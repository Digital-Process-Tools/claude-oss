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

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "bin" / "oss-workspace"

BASH = shutil.which("bash")
GIT = shutil.which("git")

pytestmark = pytest.mark.skipif(
    BASH is None or GIT is None, reason="needs bash and git; on Windows CI this is Git Bash"
)


def _executable(path, text):
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _stub_claude(bindir, argv_log):
    """A `claude` that records argv and exits 0, so exec is observable.

    `claude mcp ...` is answered rather than recorded: those calls are the script
    probing and configuring, not the session it opens, and mixing them into the
    argv log makes every assertion about the launch read the wrong list. The probe
    reports "not registered", so the registration path is the one under test.
    """
    return _executable(
        bindir / "claude",
        '#!/bin/sh\n'
        'if [ "${1:-}" = "mcp" ]; then\n'
        '    [ "${2:-}" = "add" ] && exit 0\n'
        '    exit 1\n'
        'fi\n'
        'for a in "$@"; do printf "%s\\n" "$a" >> "' + str(argv_log) + '"; done\n'
        'exit 0\n',
    )


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


def run(cwd, args=(), with_claude=True, with_channel=False):
    bindir = Path(cwd) / "_stubbin"
    bindir.mkdir(exist_ok=True)
    argv_log = Path(cwd) / "argv.txt"
    if with_claude:
        _stub_claude(bindir, argv_log)

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


def test_it_survives_being_run_through_a_symlink(tmp_path):
    """The install route is a symlink into a bin directory, so `dirname $0` is that
    directory and not the checkout. Resolving the plugin root from an unwalked $0 is
    the classic way this breaks for everyone except its author.
    """
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
