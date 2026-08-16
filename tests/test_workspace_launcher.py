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


def run(cwd, args=(), with_claude=True, with_channel=False, mcp_get=None,
        watch_name_env=None, launcher=None):
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
    # Popped rather than left alone: the developer running this suite may well have
    # one exported, and the derivation under test is the branch that only runs when
    # nothing is. An inherited value would make every derivation assertion pass or
    # fail on a fact about the machine.
    env.pop("SUPERTOOL_WATCH_NAME", None)
    if watch_name_env is not None:
        env["SUPERTOOL_WATCH_NAME"] = watch_name_env
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
# `sys.stdout` is the stream that IS strict, and the one place foreign text
# reaches it -- `print("name=" + names[0])` in READ_NAME above -- is reported for
# filing rather than fixed here: it is a different defect (a declared name that
# kills the reader, so the launcher silently derives over a declaration that
# exists) and it wants its own change.


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
