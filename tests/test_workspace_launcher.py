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
# Stated rather than inherited, matching every other sibling import in this suite.
# pytest's default import mode puts this directory on sys.path as a side effect, so
# the bare import worked -- and stopped working under `--import-mode=importlib`,
# which is a collection error nobody would connect to this line.
sys.path.insert(0, str(REPO_ROOT / "tests"))

import shell_probe  # noqa: E402

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
    if os.name == "nt" and BASH is not None:
        # `bin/oss-workspace` runs under BASH (Git Bash), which launches this
        # extensionless `#!/bin/sh` stub directly -- shebang execution is a
        # shell feature, not something native Windows process creation has at
        # all. But three call sites (#753/#810) shell out to `claude` from
        # PYTHON instead, via `subprocess.run(shell=False)`, which uses plain
        # Windows process creation with no shebang support and no PATHEXT
        # search for a bare name either -- the exact mismatch fixed in
        # `scripts/plugin_update.py`'s `_run()` and in
        # `scripts/doctor_check_mcp_channel_registration.py`'s `which()`-then-
        # `run()` calls. Those fixes resolve `claude` via `shutil.which()`,
        # which on Windows only ever matches a PATHEXT-suffixed name (`.cmd`,
        # `.bat`, `.exe`, ...) -- never the bare extensionless file this stub
        # already is. A real Windows `claude` install ships as `claude.cmd`
        # for the identical reason, so a `.cmd` sibling that forwards to the
        # real (bash-launchable) stub is what makes this fixture resolvable
        # the same way a genuine install would be, rather than a Windows-only
        # gap nothing here could ever exercise.
        cmd_path = path.with_name(path.name + ".cmd")
        cmd_path.write_text(
            '@echo off\r\n"{}" "{}" %*\r\n'.format(BASH, path),
            encoding="utf-8",
        )
    return path


def _stub_claude(bindir, argv_log, mcp_get=None, mcp_list=None, mcp_list_exit=0,
                  plugin_marketplace_exit=0):
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

    `mcp_list` / `mcp_list_exit` (#810): what `claude mcp list` prints and exits.
    None prints nothing and exits 0 -- an ordinary empty census, not a probe
    failure -- which is what every EXISTING caller of this stub gets unchanged,
    since none of them are about the census. `plugin_marketplace_exit` (#753)
    governs `claude plugin marketplace update`, called by the REAL
    scripts/plugin_update.py this launcher now shells out to synchronously; a
    caller that leaves auto-update on but never names this gets the ordinary
    success path.
    """
    mcp_log = bindir / "mcp.txt"
    get_file = bindir / "mcp_get.txt"
    list_file = bindir / "mcp_list.txt"
    if mcp_get is None:
        if get_file.exists():
            get_file.unlink()
    else:
        get_file.write_text(mcp_get, encoding="utf-8")
    if mcp_list is None:
        if list_file.exists():
            list_file.unlink()
    else:
        list_file.write_text(mcp_list, encoding="utf-8")
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
        '    if [ "${2:-}" = "list" ]; then\n'
        '        [ -f "' + str(list_file) + '" ] && cat "' + str(list_file) + '"\n'
        '        exit ' + str(mcp_list_exit) + '\n'
        '    fi\n'
        '    exit 0\n'
        'fi\n'
        'if [ "${1:-}" = "plugin" ]; then\n'
        '    exit ' + str(plugin_marketplace_exit) + '\n'
        'fi\n'
        'printf "%s" "${SUPERTOOL_WATCH_NAME-}" > "' + str(bindir / "watch_name.txt") + '"\n'
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


def _with_channel_consumer(home, bindir, naming=None):
    """Plant what the script needs to register a channel: a `bun`, and a supertool
    plugin whose install path holds the consumer.

    The path is read from installed_plugins.json rather than globbed out of the
    cache, so the fixture writes that registry -- a glob answers with whichever
    version sorts last, and that is a version the session is not running.

    `naming` is the text of the consumer's `presets/watch/naming.py`, which is where
    that version keeps the rule deciding whether it will accept a name at all (#231).
    None plants no such file, which is a third state rather than the absence of one:
    the launcher then has a consumer it cannot ask.
    """
    _executable(bindir / "bun", "#!/bin/sh\nexit 0\n")
    install = home / ".claude" / "plugins" / "cache" / "dpt-plugins" / "supertool" / "9.9.9"
    consumer = install / "notifiers" / "claude-channel" / "channel.ts"
    consumer.parent.mkdir(parents=True)
    consumer.write_text("// stub\n", encoding="utf-8")
    if naming is not None:
        rule = install / "presets" / "watch" / "naming.py"
        rule.parent.mkdir(parents=True)
        rule.write_text(naming, encoding="utf-8")
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


def run(cwd, args=(), with_claude=True, with_channel=False, mcp_get=None,
        watch_name_env=None, launcher=None, naming=None, env_extra=None,
        mcp_list=None, mcp_list_exit=0, plugin_marketplace_exit=0):
    _require_shell()
    bindir = Path(cwd) / "_stubbin"
    bindir.mkdir(exist_ok=True)
    argv_log = Path(cwd) / "argv.txt"
    if with_claude:
        _stub_claude(
            bindir, argv_log, mcp_get=mcp_get, mcp_list=mcp_list,
            mcp_list_exit=mcp_list_exit, plugin_marketplace_exit=plugin_marketplace_exit,
        )

    # HOME is pinned for the same reason PATH is: the consumer is looked up under
    # the user's real ~/.claude, so an unpinned HOME decides the channel assertions
    # by whether the developer running the suite happens to have supertool
    # installed -- green on the author's machine, red on a contributor's.
    home = Path(cwd) / "_home"
    (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
    if with_channel:
        _with_channel_consumer(home, bindir, naming=naming)

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    # Popped rather than left alone: the developer running this suite may well have
    # one exported, and the derivation under test is the branch that only runs when
    # nothing is. An inherited value would make every derivation assertion pass or
    # fail on a fact about the machine.
    env.pop("SUPERTOOL_WATCH_NAME", None)
    if watch_name_env is not None:
        env["SUPERTOOL_WATCH_NAME"] = watch_name_env
    # Off by default (#753): the launcher now shells out to `scripts/plugin_update.py`
    # synchronously, against the REAL module, before every launch. Left on, that call
    # reaches the stub `claude` for a marketplace-refresh and a per-plugin-update call
    # that no test here is about, adding a subprocess round-trip to every one of the
    # ~100 launcher tests in this file for a behaviour none of them assert on.
    # `tests/test_workspace_auto_update_753.py` and
    # `tests/test_workspace_channel_census_810.py` are the tests that ARE about it, and
    # they opt back in explicitly via `env_extra={"OSS_NO_AUTO_UPDATE": ""}` -- an empty
    # string, not an absent key, because `opt_out` reads "set to anything non-empty
    # means off" and `env.update` below runs AFTER this default, so an explicit empty
    # value is what overrides it rather than merely failing to set it.
    env.setdefault("OSS_NO_AUTO_UPDATE", "1")
    # `env_extra` is deliberately narrow rather than a general escape hatch: #271 is
    # about what a STRICT stdout does to a declared name, and PYTHONIOENCODING is the
    # only lever that establishes a strict stdout in a child interpreter. A test that
    # asserted on a codepage instead would be asserting on the runner.
    if env_extra:
        env.update(env_extra)
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
        [BASH, str(launcher or LAUNCHER), *args],
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

def test_a_malformed_supertool_json_is_unknown_not_no_tiers(tmp_path):
    """Invalid JSON is "I could not read this", not "the maintainer declared no
    tiers" -- two different facts that used to share one sentence (#652).
    """
    repo = _repo(tmp_path)
    (repo / ".supertool.json").write_text("{not json at all", encoding="utf-8")
    done, _ = run(repo)
    assert "UNKNOWN" in done.stderr, done.stderr
    assert "declares no radar tiers" not in done.stderr, done.stderr


def test_a_non_dict_supertool_json_is_unknown_not_no_tiers(tmp_path):
    """Valid JSON that is not an object -- a list, say -- is the same "could not
    read this the way I expect" fact as malformed JSON, not "no tiers declared".
    """
    repo = _repo(tmp_path)
    (repo / ".supertool.json").write_text("[1, 2, 3]", encoding="utf-8")
    done, _ = run(repo)
    assert "UNKNOWN" in done.stderr, done.stderr
    assert "declares no radar tiers" not in done.stderr, done.stderr


def test_unknown_radar_declaration_skips_the_never_spawned_check_loudly(tmp_path):
    """The composition #652 is actually about: an unreadable .supertool.json used
    to leave `radar_tiers_declared` at its 0 default, which silently switched off
    #627's never-spawned-board check with no receipt that it had been skipped.
    Now it must say so, and it must not claim "never existed" -- that would be a
    fact about a board this script never confirmed was declared at all.
    """
    repo = _repo(tmp_path)
    (repo / ".supertool.json").write_text("{not json at all", encoding="utf-8")
    never_existed = tmp_path / "never-existed-state-dir"
    done, argv = run(
        repo, with_channel=True, naming=_naming_with_resolve(never_existed)
    )
    assert argv, done.stderr
    assert "has never existed" not in done.stderr, done.stderr
    assert "UNKNOWN" in done.stderr, done.stderr
    assert "skipped" in done.stderr, done.stderr


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

# --- the watch name, and why it is derived rather than declared (#191) ----------
#
# A repo declaring nothing exported nothing, so its consumer bound the UNNAMED
# socket /tmp/supertool-watch.sock -- shared with every other repo that declares
# none, held by exactly one process, and the loser is never told. Measured on
# 2026-08-15: a second channel-capable server won that socket, five events were
# read and forwarded with zero dropped, and none of them reached the session.
#
# The assertions below read the value out of the process the launcher EXEC'd,
# never out of the script's text. An export nothing carries is not an export.


def _exported_watch_name(cwd):
    """What the launcher exported into the session it opened.

    Three answers, and the third is the one a bare falsy check destroys: `None`
    means the stub never ran at all (so nothing was measured), `""` means it ran
    and carried no name, and a string is a name. Folding the first two together
    turns "the launcher never got that far" into "the launcher exported nothing",
    which is the shape of bug this whole file exists to catch.
    """
    marker = Path(cwd) / "_stubbin" / "watch_name.txt"
    if not marker.exists():
        return None
    return marker.read_text(encoding="utf-8")


def _declare_watch_name(repo, name):
    (repo / ".supertool.json").write_text(
        json.dumps({"ops": {"radar": {"watch_name": name}}}), encoding="utf-8"
    )


def _declare_disagreeing_watch_names(repo, first, second):
    """Two op blocks naming two different channels.

    Both op keys contain `radar` so the fixture does not also trip the "no radar
    tiers" warning, which would put unrelated text into the stderr the
    disagreement assertions read.
    """
    (repo / ".supertool.json").write_text(
        json.dumps({"ops": {
            "radar": {"watch_name": first},
            "radar-slow": {"watch_name": second},
        }}),
        encoding="utf-8",
    )


def test_the_watch_name_is_derived_from_the_repo_when_nothing_declares_one(tmp_path):
    """`.oss.json` already carries `repo`: tracked, authoritative, read every tick.

    Not the directory basename -- that changes when somebody clones elsewhere, and
    two unrelated repositories cloned to the same basename collide silently, which
    is this defect reached by a different road.
    """
    repo = _repo(tmp_path)
    done, argv = run(repo, with_channel=True)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "owner-name", done.stderr


def test_a_declared_watch_name_still_wins_over_the_derivation(tmp_path):
    """The positive control for the test above, and a contract in its own right.

    Without this pair, a launcher that exported a hardcoded string would satisfy
    the derivation test, and a launcher that exported nothing at all would satisfy
    any assertion phrased as "the declaration is not overwritten".
    """
    repo = _repo(tmp_path)
    _declare_watch_name(repo, "declared-by-hand")
    done, argv = run(repo, with_channel=True)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "declared-by-hand", done.stderr


def test_an_existing_export_wins_over_the_derivation_and_says_so(tmp_path):
    """An exported value is one a running poller already captured, and moving the
    socket under a live fleet is a documented failure. So the export wins -- and the
    derivation losing quietly is the other half of the bug, so it is named.
    """
    repo = _repo(tmp_path)
    done, argv = run(repo, with_channel=True, watch_name_env="a-live-fleet")
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "a-live-fleet", done.stderr
    assert "a-live-fleet" in done.stderr
    assert "owner-name" in done.stderr


def test_nothing_to_derive_from_is_named_rather_than_silently_shared(tmp_path):
    """Falling back to the shared socket without saying so IS the reported state.

    A repo whose `.oss.json` carries no `repo` cannot be derived from. That is a
    third answer -- not a name, and not a declaration -- and it has to arrive as
    one, because the session still opens and the pollers still emit.
    """
    repo = _repo(tmp_path)
    (repo / ".oss.json").write_text('{"default_branch": "main"}', encoding="utf-8")
    done, argv = run(repo, with_channel=True)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "", done.stderr
    assert "SHARED DEFAULT" in done.stderr
    assert "declares no repo" in done.stderr


def test_the_derived_name_is_sanitised_into_something_a_socket_path_can_hold(tmp_path):
    """The name derives a filesystem path, so a slug reaches one. Every character
    outside [A-Za-z0-9._-] becomes `-`; the slash separating owner from name is the
    common case.

    Sanitising still has work to do AFTER the validator, which is why #207 kept it
    rather than replacing it: `repo_problem` accepts any pair of non-slash,
    non-whitespace runs, so `+` reaches here and a socket path should not carry it.
    The value this test used to carry -- `Org.Name/repo with spaces` -- moved to
    the refusal test below, because the validator refuses whitespace outright and
    a launcher sanitising what the rest of the plugin rejects is #207 itself.
    """
    repo = _repo(tmp_path)
    (repo / ".oss.json").write_text(
        '{"repo": "Org.Name/re+po"}', encoding="utf-8"
    )
    done, argv = run(repo, with_channel=True)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "Org.Name-re-po", done.stderr


# --- and the three states the derivation collapsed into two -------------------
#
# `READ_NAME` leaves the name empty in TWO distinct cases: nothing declared, and
# op blocks that declare different names. The derivation guard tested only for
# emptiness, so the refusal was printed and then overridden -- stderr said "none
# exported" while `SUPERTOOL_WATCH_NAME=owner-name` was exported.
#
# Declared-and-agreed, declared-and-contradictory and undeclared are three
# states, and the tests below hold them apart in both directions: the pair that
# must not derive, and the pair that must.


def test_disagreeing_op_blocks_do_not_fall_through_to_the_derivation(tmp_path):
    """The ops are already on different channels, so a derived third name would
    be one that nothing in this repo publishes to -- an uncontested socket, a
    green `channel:health`, and no events, which is a quiet wrong answer where
    the shared default is at least a loud one.

    `_exported_watch_name` is read rather than a falsy check on purpose: `None`
    would mean the launcher died before exec'ing anything, and an assertion that
    no name was exported must not be satisfiable by that.
    """
    repo = _repo(tmp_path)
    _declare_disagreeing_watch_names(repo, "alpha", "beta")
    done, argv = run(repo, with_channel=True)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "", done.stderr


def test_the_disagreement_receipt_says_what_the_code_actually_did(tmp_path):
    """A message that does not match the behaviour is the defect, not a cosmetic
    issue. Both declared names are named -- the positive half, which fails if the
    message never reaches stderr at all -- and the name that WOULD have been
    derived is absent, the negative half, which the test above pins to an
    observed export rather than to silence.
    """
    repo = _repo(tmp_path)
    _declare_disagreeing_watch_names(repo, "alpha", "beta")
    done, argv = run(repo, with_channel=True)
    assert argv, done.stderr
    assert "alpha" in done.stderr and "beta" in done.stderr, done.stderr
    assert "none exported" in done.stderr, done.stderr
    assert "SHARED DEFAULT" in done.stderr, done.stderr
    assert "owner-name" not in done.stderr, done.stderr


def test_an_undeclared_name_is_not_reported_as_a_disagreement(tmp_path):
    """The other side of the same seam, and the control that stops the fix from
    being "never derive": the undeclared state still derives, and still reads
    differently from the contradictory one.
    """
    repo = _repo(tmp_path)
    (repo / ".supertool.json").write_text(
        json.dumps({"ops": {"radar": {"tiers": []}}}), encoding="utf-8"
    )
    done, argv = run(repo, with_channel=True)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "owner-name", done.stderr
    assert "disagree" not in done.stderr, done.stderr


def test_an_unreadable_supertool_config_does_not_fall_through_to_the_derivation(tmp_path):
    """The fourth state, and the same seam one branch over.

    A `.supertool.json` that cannot be parsed has not declared nothing -- what it
    declares is UNKNOWN, and deriving there invents a name that the ops in that
    file may well contradict. The receipt already said "no channel name was
    exported and this session is on the default channel", so deriving one made
    the message false in the second way on the same commit.

    The control is the test above it: a repo with NO `.supertool.json` at all is
    absence rather than unknown, and must still derive. Without that pair this
    fix reads as "never derive", which deletes #191.
    """
    repo = _repo(tmp_path)
    (repo / ".supertool.json").write_text("{not valid json", encoding="utf-8")
    done, argv = run(repo, with_channel=True)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "", done.stderr
    assert "SHARED DEFAULT" in done.stderr, done.stderr
    assert "owner-name" not in done.stderr, done.stderr


# --- a repo value the validator refuses (#207) --------------------------------
#
# `DERIVE_NAME` folded every character outside [A-Za-z0-9._-] to a dash and
# exported whatever fell out, while `scaffold.repo_slug` and `doctor` both route
# the same value through `oss_config.repo_problem`. So `repo: ".."` -- refused by
# the validator in as many words -- derived the name `..`, and `../../etc`
# derived `..-..-etc`, and the launcher runs at SESSION START, before any of the
# consumers that would have refused it.
#
# Whether such a name TRAVERSES is a fact about the dependency's path
# construction rather than about this launcher, and #207 recorded it unestablished
# on purpose. Measured here against supertool 0.46.0 on 2026-08-16: it does not.
# That version applies a name pattern of its own to SUPERTOOL_WATCH_NAME, refuses
# `..` by name, and falls back to the default paths. So the harm that is OBSERVED
# is not traversal -- it is that the launcher hands its consumer a name the
# consumer then discards, putting the session on the shared default socket by a
# route nothing in this repository reports. Which of those two it is depends on a
# version of somebody else's package; that the value was never validated does not.
#
# The refusal is the FOURTH arm of a shape this file already has: no `.oss.json`,
# an unreadable one, and one declaring no repo each derive nothing, say so on
# stderr, and open the session anyway. A launcher that exited non-zero over a bad
# config would be a worse trade -- the channel is an enhancement and the session
# is the product -- and one that fell back to some other name would invent a
# private socket nobody publishes to, which is the quiet wrong state the block
# above already refuses. So every assertion below also checks the session opened.

REFUSED_REPO_VALUES = ["..", ".", "../../etc"]


@pytest.mark.parametrize("value", REFUSED_REPO_VALUES)
def test_a_repo_the_validator_refuses_derives_no_watch_name(tmp_path, value):
    """The three values #207 tabulates, asserted on the exported name.

    Read out of the process the launcher exec'd, never out of the script's text:
    before the fix these exported `..`, `.` and `..-..-etc` respectively, so the
    empty string here cannot be produced by a launcher that does nothing.
    """
    repo = _repo(tmp_path)
    (repo / ".oss.json").write_text(json.dumps({"repo": value}), encoding="utf-8")
    done, argv = run(repo, with_channel=True)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "", done.stderr
    assert "SHARED DEFAULT" in done.stderr, done.stderr
    # The validator's own sentence, not a second one invented at this call site:
    # two wordings for one fact is how a guard and its receipt drift apart.
    assert "expected 'owner/name'" in done.stderr, done.stderr
    assert repr(value) in done.stderr, done.stderr


def test_the_refusal_did_not_delete_the_derivation(tmp_path):
    """The must-fire half of the pair above.

    Without it, a launcher that simply stopped deriving anything at all would
    satisfy every assertion in `test_a_repo_the_validator_refuses_...`, and #191
    -- the whole reason the derivation exists -- would be silently deleted by the
    fix to #207.
    """
    repo = _repo(tmp_path)
    done, argv = run(repo, with_channel=True)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "owner-name", done.stderr
    assert "expected 'owner/name'" not in done.stderr, done.stderr


def test_a_repo_with_a_space_is_refused_rather_than_sanitised_into_a_name(tmp_path):
    """The one behaviour #207 deliberately drops, pinned so it is not an accident.

    `Org.Name/repo with spaces` used to derive `Org.Name-repo-with-spaces`. It is
    not a repository slug, `scaffold.repo_slug` has refused it since #173, and a
    launcher quietly accepting what the rest of the plugin rejects is the
    asymmetry the issue is about.
    """
    repo = _repo(tmp_path)
    (repo / ".oss.json").write_text(
        '{"repo": "Org.Name/repo with spaces"}', encoding="utf-8"
    )
    done, argv = run(repo, with_channel=True)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "", done.stderr
    assert "Org.Name-repo-with-spaces" not in done.stderr, done.stderr


# There is deliberately no test here asserting that these stderr receipts are
# ASCII, and the reason is worth writing down because a first pass at #207 added
# one and it was wrong in both directions.
#
# `sys.stderr` defaults to the `backslashreplace` error handler on every CPython
# 3, measured against PYTHONIOENCODING of ascii, cp1252 and cp437: a value the
# codepage cannot represent is escaped, never raised. So there is nothing to guard
# on this stream, and the `ascii_only()` helper written to guard it was deleted
# rather than kept as harmless -- code justified by a comment that is false is the
# defect this repository is named after, wearing a fix's clothes.
#
# The assertion itself was also platform-vacuous. `assert "中文" not in stderr`
# passes on a Windows leg, where the codepage forces the escape, and fails on
# macOS and Linux, where UTF-8 writes the character through. A test whose verdict
# is decided by the runner's locale reports coverage it does not have.
#
# `sys.stdout` is the stream that IS strict, and the one place foreign text reaches
# it -- the declared name printed by READ_NAME -- was filed as #271 and is fixed at
# the bottom of this file. It was a different defect on a different stream: not a
# receipt that mangles a value, but a TRANSPORT that drops one, so the launcher
# derived a name over a declaration that exists. This paragraph said "reported for
# filing rather than fixed here" for a whole release, and #271 exists because the
# decision was recorded in a test comment where nobody could find it.
#
# DERIVE_NAME's `print(name)` is the same stream and is NOT at risk, by construction
# rather than by luck: `oss_config.WATCH_NAME_UNSAFE_RE` folds everything outside
# [A-Za-z0-9._-] to a dash before the value is printed, so what reaches stdout there
# is ASCII whatever `repo` held.


# --- a DECLARED name the launcher exported verbatim (#230) --------------------
#
# `.supertool.json` is tracked too, so a declared `watch_name` arrives by ordinary
# contribution exactly the way `repo` does. #207 routed the DERIVED route through
# `oss_config`; the declared route three lines above it was left exporting whatever
# it read. Measured on this script before the fix: `../../../tmp/pwned` was exported
# as `../../../tmp/pwned`, and a name carrying a newline was exported carrying it.
#
# The fix is not "validate the declared name with the function the derived route
# uses" -- that function takes an `owner/name` slug and folds it, and a declared name
# is not a slug. It is that both routes now produce a value of the same KIND, a watch
# channel name, and there is one statement of what such a value may be
# (`oss_config.watch_name_problem`) with one call site in this script, after the two
# routes converge. A bypass is a route that does not reach the gate, and there is
# now nowhere else a name is produced.
#
# What the rule refuses is chosen from the harm this plugin can argue on its own:
# the consumer turns the name into a socket path and a state directory, so a value
# that is not usable as a path component is refused. It is deliberately NOT the
# consumer's `NAME_RE`, which also caps the length and constrains the first
# character. Refusing on those would take a working private channel away from a
# repository whose consumer accepts it -- a future supertool raising the cap, say.
# That question is asked of the consumer and reported instead (#231).

REFUSED_DECLARED_NAMES = [
    "../../../tmp/pwned",
    "..",
    "sub/dir",
    "has space",
]


@pytest.mark.parametrize("value", REFUSED_DECLARED_NAMES)
def test_a_declared_watch_name_that_is_not_a_path_component_is_refused(tmp_path, value):
    """Read out of the process the launcher exec'd, never out of the script's text.

    Before the fix each of these was exported verbatim, so the empty string here
    cannot be produced by a launcher that does nothing.
    """
    repo = _repo(tmp_path)
    _declare_watch_name(repo, value)
    done, argv = run(repo, with_channel=True)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "", done.stderr
    assert "SHARED DEFAULT" in done.stderr, done.stderr
    # The route is named, because a maintainer with both files has to know which one
    # to open -- and the derivation did not silently run in its place.
    assert ".supertool.json" in done.stderr, done.stderr
    assert _exported_watch_name(repo) != "owner-name", done.stderr


def test_a_declared_name_carrying_a_newline_is_refused(tmp_path):
    """Separate from the parametrised case so the value survives the fixture.

    A newline in a declared name reached the export intact before the fix. It is
    kept out of `REFUSED_DECLARED_NAMES` because a pytest test id built from it is
    unreadable, not because it is a different defect.
    """
    repo = _repo(tmp_path)
    _declare_watch_name(repo, "a" + chr(10) + "b")
    done, argv = run(repo, with_channel=True)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "", done.stderr
    assert "SHARED DEFAULT" in done.stderr, done.stderr


def test_the_refusal_did_not_delete_the_declared_route(tmp_path):
    """The must-fire half of the pair above, in the same fixture shape.

    Without it, a launcher that stopped honouring declarations altogether -- or one
    that refused every name -- would satisfy every assertion above, and the whole
    point of reading `.supertool.json` would be silently deleted by the fix.
    """
    repo = _repo(tmp_path)
    _declare_watch_name(repo, "declared-by-hand")
    done, argv = run(repo, with_channel=True)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "declared-by-hand", done.stderr
    assert "SHARED DEFAULT" not in done.stderr, done.stderr


def test_a_refusal_does_not_claim_the_shared_socket_when_an_export_already_won(tmp_path):
    """The gate refuses a name, and the session is on a private channel anyway.

    An already-exported SUPERTOOL_WATCH_NAME wins over both roads, so when the gate
    refuses what it holds, the session lands on the EXPORT -- not on the shared
    default socket. Saying "SHARED DEFAULT" there reports a state the process is
    demonstrably not in, which is the misreport this repository is named after
    pointed at its own receipt. Found by review; reproduced before it was fixed:
    the session ran on `a-live-fleet` while stderr said the shared socket.

    Worse than the wrong half is the missing half. Refusing blanks `$watch_name`,
    and the pre-existing "an export wins and both values are named" line only fires
    when `$watch_name` is non-empty -- so the reader was told the wrong thing and
    not told the right one.
    """
    repo = _repo(tmp_path)
    _declare_watch_name(repo, "../../../tmp/pwned")
    done, argv = run(repo, with_channel=True, watch_name_env="a-live-fleet")
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "a-live-fleet", done.stderr
    # Still refused, and still said out loud: the value is named so a maintainer
    # knows which file to fix even though it lost to the environment anyway.
    assert "watch name" in done.stderr, done.stderr
    assert "SHARED DEFAULT" not in done.stderr, done.stderr
    # And the channel it IS on is named, because the refusal alone reads as a repo
    # with no channel at all.
    assert "a-live-fleet" in done.stderr, done.stderr


def test_a_refusal_with_no_export_still_names_the_shared_socket(tmp_path):
    """The must-fire half of the pair above, same fixture, one variable changed.

    Without it, a fix that simply deleted the sentence from every refusal would
    satisfy the assertion above and take the true warning with it.
    """
    repo = _repo(tmp_path)
    _declare_watch_name(repo, "../../../tmp/pwned")
    done, argv = run(repo, with_channel=True)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "", done.stderr
    assert "SHARED DEFAULT" in done.stderr, done.stderr


def test_a_declared_name_cannot_be_checked_without_the_validator(tmp_path):
    """The third state, and it has to refuse rather than fall through.

    The gate imports `oss_config` from this plugin's own tree. A tree with no
    `scripts/` is "could not check", and exporting the declared name anyway there
    would make the guard disappear in exactly the case where it is missing -- the
    absence this repository is named after, one layer down. The name is a valid one
    on purpose: what is under test is the missing validator, not the value.
    """
    repo = _repo(tmp_path / "repo")
    _declare_watch_name(repo, "declared-by-hand")
    done, argv = run(
        repo, with_channel=True, launcher=_launcher_without_its_scripts(tmp_path)
    )
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "", done.stderr
    assert "SHARED DEFAULT" in done.stderr, done.stderr


# --- a name the consumer will discard, and nobody said so (#231) --------------
#
# `oss_config.watch_channel_name` folds `owner/name` into `owner-name` with no length
# and no leading-character constraint, and nothing in this plugin knows the
# consumer's own rule. Measured against this organisation's real slugs on 2026-08-16:
# `Digital-Process-Tools/claude-oss` derives a 32-character name that supertool
# accepts EXACTLY at its cap, and `claude-supertool` (38) and `claude-jit-context`
# (40) derive names it discards -- so the session lands on the shared default socket,
# the state #191 exists to eliminate, while the launcher's own output implies a
# private one. This repository works by one character, which is why nobody saw it.
#
# The fix is to REPORT, not to refuse, and not to transcribe. A copy of supertool's
# `NAME_RE` in this repository would drift, and refusing on a cap this copy carries
# would take a working channel away from a repo whose installed consumer accepts the
# name. So the launcher ASKS the consumer: it reads the rule out of the installed
# `presets/watch/naming.py` at run time, in three states -- accepted (silent),
# rejected (loud), and could not ask (loud, and the name and its length are printed
# so a reader can judge).
#
# Every fixture below plants a rule that is NOT supertool's, on purpose. A test whose
# fixture spells the real pattern is satisfied by a launcher carrying a copy of it,
# which is the one implementation this issue rules out. Only the last pair uses the
# real one, and it is labelled as a reproduction of the issue's table rather than as
# the rule under test.

#: A consumer rule deliberately unlike the real one: lower-case, at most 8. If the
#: launcher carried a copy of supertool's pattern instead of reading this file, the
#: rejected cases below would come back accepted.
#:
#: The `-` is in the class because the fold turns the slug's one slash into a dash,
#: so EVERY derived name carries one: a class without it can never accept anything
#: and the must-fire half of each pair below becomes vacuous. Found by that half
#: failing, which is the only reason it is in the fixture and not a live defect.
FIXTURE_NAMING = (
    "import re\n"
    "NAME_RE = re.compile(r'^[a-z-]{1,8}" + chr(92) + "Z')\n"
)


def test_a_name_the_consumer_will_discard_is_reported(tmp_path):
    """`owner-name` is 10 characters, and the planted rule caps at 8.

    Still exported: refusing here would be this plugin enforcing somebody else's
    rule, and the harm the issue measures is silence, not the export.
    """
    repo = _repo(tmp_path)
    done, argv = run(repo, with_channel=True, naming=FIXTURE_NAMING)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "owner-name", done.stderr
    assert "DISCARD" in done.stderr, done.stderr
    assert "owner-name" in done.stderr, done.stderr
    # The length, because "this name is too long" is unactionable without it, and
    # the issue's whole table is a length table.
    assert "10 characters" in done.stderr, done.stderr
    # The rule quoted back is the one read off disk, not one this repo carries.
    assert "[a-z-]{1,8}" in done.stderr, done.stderr


def test_a_name_the_consumer_accepts_is_not_reported(tmp_path):
    """The must-fire half, in the same fixture with the same planted rule.

    Without it every assertion above is satisfied by a launcher that prints the
    warning unconditionally -- which is a warning that has become furniture, and
    furniture on the healthy path is how a real one stops being read.
    """
    repo = _repo(tmp_path)
    (repo / ".oss.json").write_text('{"repo": "own/nam"}', encoding="utf-8")
    done, argv = run(repo, with_channel=True, naming=FIXTURE_NAMING)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "own-nam", done.stderr
    assert "DISCARD" not in done.stderr, done.stderr
    assert "could not ask" not in done.stderr, done.stderr


def test_a_consumer_with_no_naming_rule_is_could_not_ask_rather_than_accepted(tmp_path):
    """The third state, and the one this repository is named after.

    A consumer is installed and its rule is not where this launcher looks -- an
    older version, a moved file. Silence there is indistinguishable from a name the
    consumer accepts, so it says it could not ask and prints what it could not check.
    """
    repo = _repo(tmp_path)
    done, argv = run(repo, with_channel=True, naming=None)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "owner-name", done.stderr
    assert "could not ask" in done.stderr, done.stderr
    assert "owner-name" in done.stderr, done.stderr
    assert "10 characters" in done.stderr, done.stderr


def test_a_naming_rule_that_will_not_load_is_could_not_ask(tmp_path):
    """Reading the rule means executing the consumer's module, so it can fail.

    Failing into "accepted" would be the same absence one layer down. `SystemExit`
    is caught alongside `Exception` on purpose: a module that calls `sys.exit` on
    import must not take the launcher's session with it.
    """
    repo = _repo(tmp_path)
    done, argv = run(
        repo, with_channel=True, naming="raise RuntimeError('boom')\n"
    )
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "owner-name", done.stderr
    assert "could not ask" in done.stderr, done.stderr


def test_a_naming_module_that_exits_on_import_does_not_end_the_session(tmp_path):
    repo = _repo(tmp_path)
    done, argv = run(
        repo, with_channel=True, naming="import sys\nsys.exit(3)\n"
    )
    assert argv, done.stderr
    assert "could not ask" in done.stderr, done.stderr


def test_a_naming_module_with_no_rule_in_it_is_could_not_ask(tmp_path):
    """`NAME_RE` renamed or removed upstream. Not an acceptance."""
    repo = _repo(tmp_path)
    done, argv = run(repo, with_channel=True, naming="PATTERN = 'x'\n")
    assert argv, done.stderr
    assert "could not ask" in done.stderr, done.stderr


def test_no_consumer_at_all_says_nothing_here(tmp_path):
    """The consumer block already reports an absent supertool with its own remedy.

    A second line saying the name could not be checked adds nothing an absent
    consumer does not already imply, and a warning printed on a path where it is
    never actionable is the definition of furniture.
    """
    repo = _repo(tmp_path)
    done, argv = run(repo, with_channel=False)
    assert argv, done.stderr
    assert "could not ask" not in done.stderr, done.stderr
    assert "DISCARD" not in done.stderr, done.stderr


# The issue's own table, reproduced. The pattern here IS supertool's, copied from
# `presets/watch/naming.py` in versions 0.40.0 through 0.46.0 and measured on
# 2026-08-16 -- as a FIXTURE standing in for an installed dependency, which is what
# a fixture is for. It is not the rule under test: the tests above plant a different
# one, and they are what proves the launcher reads the file rather than carrying a
# copy. If this pattern goes stale, these two tests stop reproducing the issue and
# no shipped behaviour changes with it.
SUPERTOOL_NAMING = (
    "import re\n"
    "NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,31}" + chr(92) + "Z')\n"
)


def test_the_slug_this_plugin_is_deployed_on_that_derives_a_rejected_name(tmp_path):
    """`Digital-Process-Tools/claude-supertool` -> 38 characters, discarded."""
    repo = _repo(tmp_path)
    (repo / ".oss.json").write_text(
        '{"repo": "Digital-Process-Tools/claude-supertool"}', encoding="utf-8"
    )
    done, argv = run(repo, with_channel=True, naming=SUPERTOOL_NAMING)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "Digital-Process-Tools-claude-supertool"
    assert "DISCARD" in done.stderr, done.stderr
    assert "38 characters" in done.stderr, done.stderr


def test_the_slug_that_works_by_one_character_is_still_accepted(tmp_path):
    """`Digital-Process-Tools/claude-oss` -> 32, exactly at the cap.

    The must-fire half of the pair above and the reason nobody saw this: a check
    keyed on a real slug is the only fixture that could ever have caught it, and
    the suite's own `owner/name` is structurally incapable of it.
    """
    repo = _repo(tmp_path)
    (repo / ".oss.json").write_text(
        '{"repo": "Digital-Process-Tools/claude-oss"}', encoding="utf-8"
    )
    done, argv = run(repo, with_channel=True, naming=SUPERTOOL_NAMING)
    assert argv, done.stderr
    name = _exported_watch_name(repo)
    assert name == "Digital-Process-Tools-claude-oss", done.stderr
    assert len(name) == 32, name
    assert "DISCARD" not in done.stderr, done.stderr


# --- has anything EVER spawned on this channel? (#618) ------------------------
#
# `.supertool.json` declaring radar tiers only opens the door: the launcher
# registers the consumer, exports the name and the session runs "armed" whether
# or not a board has ever been raised on it. Found on a consumer repo where
# `channel:health` was FORWARDING, subscribed and verified throughout, while
# `watches` said the poller state directory "does not exist yet, so nothing has
# ever spawned on this channel" -- and the launcher's own one line about the
# board fired on the OPPOSITE case: no tiers (opted out) warned, tiers declared
# and never spawned (opted in, and blind) stayed silent.
#
# The fixture plants a `resolve()` on the consumer's own naming.py, the same
# shape `presets/watch/naming.py` ships (measured against supertool 0.51.0),
# with `state_dir` baked in directly rather than reconstructed from the name --
# what is under test here is the launcher reading `resolve()` off the installed
# module and stat-ing the path it returns, not supertool's own path formula.


def _naming_with_resolve(state_dir):
    return (
        "import re\n"
        "NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,31}" + chr(92) + "Z')\n"
        "class _Resolved:\n"
        "    def __init__(self, state_dir):\n"
        "        self.state_dir = state_dir\n"
        "def resolve(env=None):\n"
        "    return _Resolved(" + repr(str(state_dir)) + ")\n"
    )


def test_tiers_declared_and_a_never_spawned_channel_is_warned(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".supertool.json").write_text(
        '{"ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}}', encoding="utf-8"
    )
    never_existed = tmp_path / "never-existed-state-dir"
    done, argv = run(
        repo, with_channel=True, naming=_naming_with_resolve(never_existed)
    )
    assert argv, done.stderr
    assert "has never existed" in done.stderr, done.stderr
    assert "nothing has ever spawned" in done.stderr, done.stderr
    assert str(never_existed) in done.stderr, done.stderr


def test_tiers_declared_and_a_raised_channel_is_not_warned(tmp_path):
    """The must-fire half's pair, same fixture shape, one variable changed.

    Without it, a launcher that warns unconditionally whenever tiers are
    declared -- ignoring `resolve()` entirely -- would satisfy the assertion
    above and the new warning would be furniture on every healthy launch.
    """
    repo = _repo(tmp_path)
    (repo / ".supertool.json").write_text(
        '{"ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}}', encoding="utf-8"
    )
    existing = tmp_path / "existing-state-dir"
    existing.mkdir()
    done, argv = run(
        repo, with_channel=True, naming=_naming_with_resolve(existing)
    )
    assert argv, done.stderr
    assert "has never existed" not in done.stderr, done.stderr
    assert "nothing has ever spawned" not in done.stderr, done.stderr


def test_no_tiers_declared_is_not_told_about_a_never_spawned_channel(tmp_path):
    """The old warning (no tiers at all) must still fire, and the NEW one must
    not -- there is nothing to have spawned for a board that was never asked
    to publish anything in the first place.
    """
    repo = _repo(tmp_path)
    (repo / ".supertool.json").write_text('{"presets": ["git"]}', encoding="utf-8")
    never_existed = tmp_path / "never-existed-state-dir"
    done, argv = run(
        repo, with_channel=True, naming=_naming_with_resolve(never_existed)
    )
    assert argv, done.stderr
    assert "nothing publishes to it" in done.stderr, done.stderr
    assert "has never existed" not in done.stderr, done.stderr


def test_a_consumer_whose_naming_has_no_resolve_says_it_could_not_check(tmp_path):
    """An older installed consumer may carry `NAME_RE` and nothing else -- that
    is `could not check`, not a confident "never spawned" AND not silence.

    Found by review (#618): the first cut of this fix answered `could not
    check` with silence, which renders identically to "checked, and it is
    healthy" -- exactly the shape this file's own doctrine forbids for
    `cannot_ask()`'s identical question three states above this one.
    """
    repo = _repo(tmp_path)
    (repo / ".supertool.json").write_text(
        '{"ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}}', encoding="utf-8"
    )
    done, argv = run(repo, with_channel=True, naming=SUPERTOOL_NAMING)
    assert argv, done.stderr
    assert "has never existed" not in done.stderr, done.stderr
    assert "could not be checked" in done.stderr, done.stderr


def test_a_healthy_channel_says_nothing_at_all(tmp_path):
    """The must-fire pair's must-NOT-fire half: with a working `resolve()` and
    an existing state directory, NEITHER the never-spawned warning nor the
    could-not-check one may appear. Without this, a fix for the silence above
    that instead made the could-not-check warning fire unconditionally would
    satisfy every other assertion in this file.
    """
    repo = _repo(tmp_path)
    (repo / ".supertool.json").write_text(
        '{"ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}}', encoding="utf-8"
    )
    existing = tmp_path / "existing-state-dir"
    existing.mkdir()
    done, argv = run(
        repo, with_channel=True, naming=_naming_with_resolve(existing)
    )
    assert argv, done.stderr
    assert "has never existed" not in done.stderr, done.stderr
    assert "could not be checked" not in done.stderr, done.stderr


def test_a_resolve_that_raises_says_it_could_not_check(tmp_path):
    """`resolve()` is somebody else's code, executed at run time (#231's own
    justification for reading it live rather than transcribing it) -- so it
    can raise, and a raise must not read as "nothing to warn about" either.
    """
    repo = _repo(tmp_path)
    (repo / ".supertool.json").write_text(
        '{"ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}}', encoding="utf-8"
    )
    naming = (
        "import re\n"
        "NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,31}" + chr(92) + "Z')\n"
        "def resolve(env=None):\n"
        "    raise RuntimeError('boom')\n"
    )
    done, argv = run(repo, with_channel=True, naming=naming)
    assert argv, done.stderr
    assert "has never existed" not in done.stderr, done.stderr
    assert "could not be checked" in done.stderr, done.stderr
    assert "RuntimeError" in done.stderr, done.stderr


def _launcher_without_its_scripts(tmp_path):
    """A copy of the launcher under a plugin root carrying no `scripts/`.

    The validator is imported from the plugin's own tree, so "the validator could
    not be loaded" is a real third state rather than a hypothetical one, and it
    has to read as `could not check`: nothing derived, said out loud. Falling back
    to the unvalidated slug there would be the absence-produced-by-the-tool this
    repository is named after, one layer down.
    """
    fake = tmp_path / "_fakeplugin"
    (fake / "bin").mkdir(parents=True)
    dst = fake / "bin" / "oss-workspace"
    shutil.copy2(str(LAUNCHER), str(dst))
    return dst


def test_a_validator_that_cannot_be_imported_derives_nothing_and_says_so(tmp_path):
    repo = _repo(tmp_path / "repo")
    done, argv = run(
        repo, with_channel=True, launcher=_launcher_without_its_scripts(tmp_path)
    )
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "", done.stderr
    assert "SHARED DEFAULT" in done.stderr, done.stderr
    assert "owner-name" not in done.stderr, done.stderr

# --- every refusing arm names the channel the session is ACTUALLY on (#270) ----
#
# `7b2841c` fixed ONE arm -- the gate's -- by handing the winning export into it and
# computing one sentence for the state that is actually true. The reason only one got
# fixed is that every arm stated the sentence independently, so there was nothing to
# find and nothing to change in the other six.
#
# Six, not three. The issue names "DERIVE_NAME's refusals" as one arm; DERIVE_NAME
# has FIVE refusal sites, and one of them -- the validator that will not import --
# has its "SHARED DEFAULT" split across two source lines by string concatenation, so
# it is invisible to the obvious grep for the phrase. A count taken from that grep
# would have left it behind exactly the way the first three were left behind.
#
# Both directions, per arm, because a one-directional assertion passes against a fix
# that deletes the sentence everywhere -- which is a worse receipt than the wrong one.
# The must-fire half is the no-export run; the must-not-fire half is the export run.
# Each case also carries a sentence proving ITS OWN arm ran, so a fixture that quietly
# reached some other branch cannot satisfy the pair.


def _deep_json():
    """JSON nested deep enough that the parser gives up on it.

    `json.load` raises `RecursionError` here, which is a `RuntimeError` and so is
    caught by neither `except FileNotFoundError` nor `except (OSError, ValueError)`
    in either heredoc. The block then exits non-zero having printed nothing, the
    trailing `|| true` swallows it, and "the reader died" arrives at the shell as
    "the file declares none" -- the same swallow #271 is about, one exception over.
    """
    return "[" * 60000 + "]" * 60000


def _arm_read_conflict(tmp_path, repo):
    _declare_disagreeing_watch_names(repo, "alpha", "beta")
    return {}


def _arm_read_unreadable(tmp_path, repo):
    (repo / ".supertool.json").write_text("{not valid json", encoding="utf-8")
    return {}


def _arm_read_crashed(tmp_path, repo):
    (repo / ".supertool.json").write_text(_deep_json(), encoding="utf-8")
    return {}


def _arm_derive_no_config(tmp_path, repo):
    (repo / ".oss.json").unlink()
    return {}


def _arm_derive_unreadable_config(tmp_path, repo):
    (repo / ".oss.json").write_text("{not valid json", encoding="utf-8")
    return {}


def _arm_derive_crashed(tmp_path, repo):
    (repo / ".oss.json").write_text(_deep_json(), encoding="utf-8")
    return {}


def _arm_derive_no_repo(tmp_path, repo):
    (repo / ".oss.json").write_text('{"default_branch": "main"}', encoding="utf-8")
    return {}


def _arm_derive_refused_repo(tmp_path, repo):
    (repo / ".oss.json").write_text('{"repo": ".."}', encoding="utf-8")
    return {}


def _arm_derive_no_validator(tmp_path, repo):
    return {"launcher": _launcher_without_its_scripts(tmp_path)}


# (prepare, a sentence only THIS arm prints)
WATCH_REFUSAL_ARMS = [
    (_arm_read_conflict, "disagree about watch_name"),
    (_arm_read_unreadable, ".supertool.json could not be read"),
    (_arm_read_crashed, ".supertool.json ended with status"),
    (_arm_derive_no_config, ".oss.json, so nothing could be derived"),
    (_arm_derive_unreadable_config, ".oss.json could not be read"),
    (_arm_derive_crashed, ".oss.json ended with status"),
    (_arm_derive_no_repo, "declares no repo"),
    (_arm_derive_refused_repo, "expected 'owner/name'"),
    (_arm_derive_no_validator, "config validator could not be loaded"),
]

WATCH_REFUSAL_IDS = [
    "read_conflict",
    "read_unreadable",
    "read_crashed",
    "derive_no_config",
    "derive_unreadable_config",
    "derive_crashed",
    "derive_no_repo",
    "derive_refused_repo",
    "derive_no_validator",
]


def _require_json_recursion_crash(tmp_path):
    """Establish the condition rather than assert a limit from a table.

    The recursion limit is an interpreter fact, and a depth that overflows every build
    this suite has run on is still not a depth that overflows the next one. So the
    crash is MEASURED against this interpreter, and a build that survives it skips
    carrying what went untested.
    """
    deep = Path(tmp_path) / "_deep_probe.json"
    deep.write_text(_deep_json(), encoding="utf-8")
    probe = subprocess.run(
        [sys.executable, "-c", "import json,sys; json.load(open(sys.argv[1]))", str(deep)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    deep.unlink()
    if probe.returncode == 0:
        pytest.skip(
            "this interpreter parsed 60000-deep JSON without raising (rc=0), so the "
            "'the reader crashed and said nothing' arm of READ_NAME/DERIVE_NAME went "
            "untested here: what is unverified is that a crash is reported rather than "
            "read as 'this file declares none'"
        )
    if "RecursionError" not in probe.stderr:
        pytest.skip(
            "60000-deep JSON failed on this interpreter with %r rather than "
            "RecursionError, so the fixture is not establishing the uncaught-exception "
            "condition the crash arm is about, and that arm went untested"
            % probe.stderr.strip().splitlines()[-1:]
        )


def _maybe_require_crash(prepare, tmp_path):
    if prepare in (_arm_read_crashed, _arm_derive_crashed):
        _require_json_recursion_crash(tmp_path)


@pytest.mark.parametrize("prepare,fired", WATCH_REFUSAL_ARMS, ids=WATCH_REFUSAL_IDS)
def test_a_refusing_arm_names_the_export_the_session_landed_on(tmp_path, prepare, fired):
    """An already-exported SUPERTOOL_WATCH_NAME wins over both roads, so a refusal here
    costs nothing and the session stays on that channel. Saying "SHARED DEFAULT"
    reports a state the process is demonstrably not in -- and takes the true half with
    it, because refusing blanks `$watch_name` and the pre-existing "an export wins"
    line only fires while that variable is non-empty.

    Reproduced on all of these before the fix: the session ran on `a-live-fleet` while
    stderr claimed the shared socket.
    """
    _maybe_require_crash(prepare, tmp_path)
    repo = _repo(tmp_path / "repo")
    extra = prepare(tmp_path, repo)
    done, argv = run(repo, with_channel=True, watch_name_env="a-live-fleet", **extra)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "a-live-fleet", done.stderr
    # This arm ran. Without it the pair is satisfiable by a fixture that quietly
    # reached some other branch and refused there for a different reason.
    assert fired in done.stderr, done.stderr
    # `ASK_CONSUMER` also quotes the exported name, so the name alone proves nothing.
    # This sentence belongs to the refusal and exists only once the arm computes it.
    assert "already exported as" in done.stderr, done.stderr
    assert "SHARED DEFAULT" not in done.stderr, done.stderr


@pytest.mark.parametrize("prepare,fired", WATCH_REFUSAL_ARMS, ids=WATCH_REFUSAL_IDS)
def test_a_refusing_arm_with_no_export_still_names_the_shared_socket(tmp_path, prepare, fired):
    """The must-fire half, same fixture, one variable changed.

    Without it, a fix that deleted the sentence from every arm would satisfy the test
    above and delete the true warning along with the false one.
    """
    _maybe_require_crash(prepare, tmp_path)
    repo = _repo(tmp_path / "repo")
    extra = prepare(tmp_path, repo)
    done, argv = run(repo, with_channel=True, **extra)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "", done.stderr
    assert fired in done.stderr, done.stderr
    assert "SHARED DEFAULT" in done.stderr, done.stderr
    assert "already exported as" not in done.stderr, done.stderr


@pytest.mark.parametrize("prepare", [_arm_read_crashed, _arm_derive_crashed],
                         ids=["read_crashed", "derive_crashed"])
def test_a_reader_that_crashed_does_not_derive_over_what_it_could_not_read(tmp_path, prepare):
    """#271's mechanism reached by a different exception, and the reason `|| true` was
    narrowed rather than left alone.

    A `.supertool.json` the reader could not finish has NOT declared none, and a
    `.oss.json` the deriver could not finish has not failed to carry a repo. Before the
    fix the non-zero exit was swallowed, the empty stdout was read as `undeclared`, and
    the launcher derived `owner-name` over a file nobody had established the contents
    of -- silently, with no line on either stream.
    """
    _require_json_recursion_crash(tmp_path)
    repo = _repo(tmp_path / "repo")
    prepare(tmp_path, repo)
    done, argv = run(repo, with_channel=True)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "", done.stderr
    assert "owner-name" not in done.stderr, done.stderr


# --- a declared name this console cannot carry (#271) -------------------------
#
# `READ_NAME` prints the declared name to stdout and the shell reads it back. stdout is
# STRICT, so a name the stream's encoding cannot represent raises `UnicodeEncodeError`,
# `|| true` swallows it, and the launcher derives a name over a declaration that exists
# and is perfectly valid on the machine that wrote it. The platform axis is the point:
# cp1252 on Windows against a `.supertool.json` written on a UTF-8 machine, and
# `.supertool.json` is tracked, so the value arrives by ordinary contribution.
#
# Three candidate behaviours, and the honest one is the third state. Printing the name
# mangled is a receipt nobody can act on and an export nobody asked for; refusing to
# launch trades the product for an enhancement. *A name is declared and this stream
# cannot carry it* is neither, and it is the same shape as `conflict` and `unreadable`
# one branch over: export nothing, derive nothing, say so, open the session.
#
# The condition is ESTABLISHED, not asserted from a table of codepages: a strict
# encoding is forced onto the child interpreter and that interpreter is then asked
# whether an unencodable print actually raises. A run that cannot establish it skips
# carrying what went untested. Asserting on a runner whose locale happens to be UTF-8
# would be a verdict decided by the runner, which is the vacuous-on-one-platform shape
# the comment block above `REFUSED_DECLARED_NAMES` already had to delete once.

UNENCODABLE_NAME = "café-chaîne"
STRICT_ASCII = {"PYTHONIOENCODING": "ascii:strict"}


def _require_strict_unencodable_stdout():
    # `chr(233)` rather than the character in the source: the probe source is handed
    # to the child as an argv, and argv is decoded with the filesystem encoding, so a
    # literal here would make the fixture depend on the very thing under test.
    probe = subprocess.run(
        [sys.executable, "-c", "print(chr(233))"],
        env=dict(os.environ, PYTHONIOENCODING="ascii:strict"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if probe.returncode == 0:
        pytest.skip(
            "PYTHONIOENCODING=ascii:strict did not make this interpreter refuse to "
            "print chr(233) (rc=0, stdout=%r), so a stdout that cannot carry a declared "
            "name could not be established here and #271's arm went untested: what is "
            "unverified is that such a name is REPORTED rather than derived over"
            % probe.stdout
        )
    if "UnicodeEncodeError" not in probe.stderr:
        pytest.skip(
            "printing chr(233) under PYTHONIOENCODING=ascii:strict failed with %r "
            "rather than UnicodeEncodeError, so the fixture is not establishing the "
            "condition #271 is about and that arm went untested"
            % probe.stderr.strip().splitlines()[-1:]
        )


def test_a_declared_name_this_stream_cannot_carry_is_reported_not_derived_over(tmp_path):
    """Reproduced before the fix: `.supertool.json` declared the name below, the
    launcher exported `owner-name`, and stderr carried not one word about it.
    """
    _require_strict_unencodable_stdout()
    repo = _repo(tmp_path)
    _declare_watch_name(repo, UNENCODABLE_NAME)
    done, argv = run(repo, with_channel=True, env_extra=STRICT_ASCII)
    assert argv, done.stderr
    # The defect itself: a derivation ran on top of a declaration that exists.
    assert _exported_watch_name(repo) != "owner-name", done.stderr
    assert _exported_watch_name(repo) == "", done.stderr
    # The receipt names the file, the value, and the stream that could not carry it.
    assert ".supertool.json" in done.stderr, done.stderr
    assert "cannot carry" in done.stderr, done.stderr
    # `ascii()`, so the receipt is renderable on the very stream that refused the
    # value. Quoting it raw would kill the receipt with the thing it is reporting.
    assert r"caf\xe9" in done.stderr, done.stderr
    assert "SHARED DEFAULT" in done.stderr, done.stderr


def test_a_strict_stream_does_not_refuse_a_name_it_can_carry(tmp_path):
    """The must-fire half. Without it, a fix that refused every declared name under a
    strict stream -- or simply stopped exporting declarations at all -- would pass the
    test above, and the launcher would never open a private channel on Windows again.
    """
    _require_strict_unencodable_stdout()
    repo = _repo(tmp_path)
    _declare_watch_name(repo, "plain-declared-name")
    done, argv = run(repo, with_channel=True, env_extra=STRICT_ASCII)
    assert argv, done.stderr
    assert _exported_watch_name(repo) == "plain-declared-name", done.stderr
    assert "cannot carry" not in done.stderr, done.stderr


def test_a_non_ascii_declared_name_survives_a_stream_that_can_carry_it(tmp_path):
    """The other must-fire half, on the other axis: the refusal is a property of the
    STREAM, not of the name. A fix keyed on "does this name contain non-ASCII" would
    take a working channel away from a UTF-8 machine, which is most of them.

    The exported value is asserted as "neither empty nor the derived name" rather than
    by equality, deliberately: the stub reads the name back out of the environment as
    bytes, so an equality assertion would also be measuring the fidelity of an
    environment round-trip through the shell -- a different claim, on a different axis,
    and not the one this test is making.
    """
    repo = _repo(tmp_path)
    _declare_watch_name(repo, UNENCODABLE_NAME)
    done, argv = run(repo, with_channel=True, env_extra={"PYTHONIOENCODING": "utf-8"})
    assert argv, done.stderr
    assert _exported_watch_name(repo) not in ("", "owner-name"), done.stderr
    assert "cannot carry" not in done.stderr, done.stderr

# --- the landing sentence has a third state of its own ------------------------
#
# Computing the sentence once (#270) turns each heredoc into a program with an
# argument, and an argument has a missing case. These blocks are extracted and run by
# a second caller -- `tests/test_doctor_inprocess.py` runs DERIVE_NAME against its own
# fixtures to cross-check doctor's copy of the derivation rule -- and that caller has
# no session to report on.
#
# Defaulting to "this session is on the SHARED DEFAULT socket" would have put a
# confident wrong sentence in the mouth of every caller that forgot the argument,
# which is #270 reintroduced one layer down by its own fix. Crashing would have made a
# program that answers "is this derivable" answer with a traceback instead. So it is
# the third state, and this pair is what stops it silently becoming either of the
# other two.

HEREDOC_MARKERS = ["READ_NAME", "DERIVE_NAME", "CHECK_NAME"]


def _extract_heredoc(marker):
    launcher = LAUNCHER.read_text(encoding="utf-8")
    opening = "<<'" + marker + "'"
    closing = "\n" + marker + "\n"
    tail = launcher.split(opening, 1)[1] if opening in launcher else ""
    if "\n" not in tail or closing not in tail:
        pytest.fail(
            "bin/oss-workspace no longer carries a %s heredoc, so its short-argv "
            "behaviour went unchecked -- and a block that went unchecked must not read "
            "as one that agreed" % marker
        )
    return tail.split("\n", 1)[1].split(closing, 1)[0]


LANDING_SENTENCE = "LANDED-ON-A-CHANNEL-THIS-TEST-NAMED."


def _heredoc_argv(marker, tmp_path):
    """Everything each block takes EXCEPT the landing sentence, which is always last.

    The earlier arguments are chosen so that every block reaches a refusal arm and
    prints its sentence: a `.oss.json`/`.supertool.json` that will not parse, and a
    watch name (`..`) the gate refuses. A block that succeeded would print no sentence
    at all, and the assertion below would then be measuring nothing.
    """
    (tmp_path / "broken.json").write_text("{not valid json", encoding="utf-8")
    return {
        "READ_NAME": [str(tmp_path / "broken.json")],
        "DERIVE_NAME": [str(tmp_path / "broken.json"), str(REPO_ROOT / "scripts")],
        "CHECK_NAME": ["..", "declared in a test", str(REPO_ROOT / "scripts")],
    }[marker]


def _run_heredoc(marker, tmp_path, argv):
    script = tmp_path / (marker.lower() + ".py")
    script.write_text(_extract_heredoc(marker), encoding="utf-8")
    done = subprocess.run(
        [sys.executable, str(script)] + argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    return done.stdout + done.stderr


@pytest.mark.parametrize("marker", HEREDOC_MARKERS)
def test_a_block_given_no_landing_sentence_says_so_rather_than_naming_a_socket(tmp_path, marker):
    """Every argument the block takes except the last one -- which is exactly what
    `tests/test_doctor_inprocess.py` hands DERIVE_NAME today.
    """
    combined = _run_heredoc(marker, tmp_path, _heredoc_argv(marker, tmp_path))
    assert "Traceback" not in combined, combined
    assert "was not established" in combined, combined
    assert "SHARED DEFAULT" not in combined, combined


# --- the conflict receipt renders values nobody here wrote (#323) -------------
#
# `names` is `block["watch_name"]` straight out of `json.loads` of the MANAGED
# repo's `.supertool.json` -- tracked, so it arrives by ordinary contribution.
# The `conflict` arm returns before anything validates a name: `watch_name_problem`
# is never called on this route, so the only thing standing between that value and
# a column-0 line of the launcher's own receipt is how it is rendered.
#
# The sibling arm six lines up already answers this with `ascii()` (#271/#283); the
# `conflict` arm was rewritten in the same hunk without it. So the harm is not
# hypothetical text-mangling: a newline forges a second line that reads as the
# launcher speaking, and a CSI sequence erases and rewrites what the terminal has
# already printed -- the harm `release_version._one_line`'s docstring names.
#
# Driven against the EXTRACTED block rather than through a `bash -c` string: a test
# that rebuilds shell quoting measures its own escaping, and this repo deleted one
# for exactly that reason. Bytes rather than text, because `universal_newlines`
# translates a lone CR into a newline and would hide half of what is asserted.

# Three forgeries in one value, and the third is here because the first version of
# this fixture did not carry it. That version spelled the forged line
# `oss-workspace: VERDICT: ok`, which starts with the launcher prefix -- so the
# `startswith("VERDICT:")` assertion below could not fail on it, and evaluating the
# four assertions one at a time against the parent commit showed it PASSING on
# unfixed code. An assertion no red state reaches is this repo's own defect class
# wearing a tick. The impersonated line and the bare verdict line are now separate.
FORGED_TAIL = "\noss-workspace: reading that file found nothing wrong\nVERDICT: ok\r\x1b[2K"


def _run_heredoc_raw(marker, tmp_path, argv):
    script = tmp_path / (marker.lower() + "_raw.py")
    script.write_text(_extract_heredoc(marker), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(script)] + argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _launcher_lines(stderr):
    """Lines that CLAIM to be this launcher speaking -- column 0, not anywhere.

    Counting the substring instead was the first version of this and it was wrong
    in the direction that matters: once the value is neutralised, the escaped text
    `oss-workspace:` is still present INSIDE the quoted name, and a substring count
    would have called the fixed code a forgery. What is forged is a LINE, so a line
    is what is counted.
    """
    return len([
        line for line in stderr.splitlines() if line.startswith("oss-workspace:")
    ])


def _read_name_conflict(tmp_path, first, second):
    cfg = tmp_path / "supertool.json"
    cfg.write_text(
        json.dumps({"ops": {
            "radar": {"watch_name": first},
            "radar-slow": {"watch_name": second},
        }}),
        encoding="utf-8",
    )
    done = _run_heredoc_raw("READ_NAME", tmp_path, [str(cfg), LANDING_SENTENCE])
    return (
        done.stdout.decode("utf-8", "replace"),
        done.stderr.decode("utf-8", "replace"),
    )


def test_an_ordinary_conflict_still_produces_its_one_honest_line(tmp_path):
    """The positive control, and it is the load-bearing half of the pair below.

    Every assertion in `test_a_conflicting_watch_name_cannot_forge_a_receipt_line`
    is satisfied by a block that printed NOTHING AT ALL -- no forged line appears in
    an empty string. This one fails in that world: it requires the `conflict` tag on
    stdout, exactly one `oss-workspace:` line on stderr, and both declared names in
    it.
    """
    stdout, stderr = _read_name_conflict(tmp_path, "alpha", "beta")
    assert stdout.strip() == "conflict", (stdout, stderr)
    assert _launcher_lines(stderr) == 1, stderr
    assert len(stderr.strip().splitlines()) == 1, stderr
    assert "alpha" in stderr and "beta" in stderr, stderr


def test_a_conflicting_watch_name_cannot_forge_a_receipt_line(tmp_path):
    """One line out, whatever that file declared.

    The four assertions are four distinct harms, not one restated: a second line
    prefixed `oss-workspace:` is the launcher impersonated; a column-0 `VERDICT:`
    line is the shape the launcher itself awks a verdict out of further down, so
    the forgery is in a vocabulary this loop already reads; a bare ESC or CR
    rewrites output the terminal has already committed. And the names still have to
    REACH stderr -- that is what stops the fix from being "print less".

    No line number for that awk: the first version of this docstring cited one, and
    the comment block landing beside the fix in the same commit moved it. A
    reference a diff can invalidate belongs in neither half of a pair whose whole
    subject is a claim going stale beside its code.

    The message terminator is stripped before the control-character check, and that
    is a construction rather than an argument. Whether a child's `sys.stderr`
    translates its own LF to `os.linesep` is a question about CPython's std-stream
    setup that this suite cannot settle from one platform -- so it is not asked.
    Stripping CR and LF from the right removes a terminator of either shape and
    leaves an EMBEDDED CR alone, which is the one this test is about, so the
    assertion holds whichever way that question goes. It is unobserved on Windows
    and this is what stops that from mattering.
    """
    stdout, stderr = _read_name_conflict(tmp_path, "alpha", "beta" + FORGED_TAIL)
    assert stdout.strip() == "conflict", (stdout, stderr)
    assert "Traceback" not in stderr, stderr
    # Must fire: the receipt still names both channels the file declared.
    assert "alpha" in stderr and "beta" in stderr, stderr
    # Must not fire: one line, nothing impersonating the launcher, no verdict.
    assert len(stderr.strip().splitlines()) == 1, stderr
    assert _launcher_lines(stderr) == 1, stderr
    assert not [
        line for line in stderr.splitlines() if line.startswith("VERDICT:")
    ], stderr
    body = stderr.rstrip("\r\n")
    assert "\x1b" not in body and "\r" not in body, repr(stderr)


@pytest.mark.parametrize("marker", HEREDOC_MARKERS)
def test_a_block_given_a_landing_sentence_prints_that_one(tmp_path, marker):
    """The must-fire half. Without it, a block that had lost the argument entirely --
    and so said "was not established" on every real launch -- would pass the test
    above, and every receipt in this file would stop naming a channel.
    """
    argv = _heredoc_argv(marker, tmp_path) + [LANDING_SENTENCE]
    combined = _run_heredoc(marker, tmp_path, argv)
    assert "Traceback" not in combined, combined
    assert LANDING_SENTENCE in combined, combined
    assert "was not established" not in combined, combined
