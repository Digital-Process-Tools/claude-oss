"""``check_mcp_channel_registration`` and ``mcp_channel_registration_state`` --
moved out of ``scripts/doctor.py`` (#630, on the convention #497 established).

`doctor.py` keeps `main()`, the shared contract (exit 0 always, one VERDICT
line, `report()` / `unmeasured()`) and the checks not yet moved; this module
holds one check, the state function behind it and their two constants, and
nothing else. Every shared name -- `report`, `_one_line` -- is reached through
`doctor` imported as a module (`import doctor`), never `from doctor import
name`, the reason `scripts/doctor_check_statusline.py` spells out in full: a
name looked up this way is always the current value in `doctor`'s own
namespace, which is what keeps a test's `monkeypatch.setattr(doctor, ...)`
reaching code that used to be inline.

`doctor.py` imports all four names back out of this module -- `CHANNEL_SERVER`,
`_MCP_ARGS_RE`, `mcp_channel_registration_state` and
`check_mcp_channel_registration` -- so each keeps answering exactly as it did
before the move. The move is a pure relocation apart from two things, both stated
rather than left to be discovered: the shared names above are now reached through
`doctor.`, and the two top-level definitions are separated by the two blank lines
every other module here uses rather than the one they had inline.

`check_channel_consumer_pin` (#646) deliberately stays in `doctor.py`
for now and reads `mcp_channel_registration_state` through that re-export: it
depends on a chain of `doctor.py`'s own version-comparison helpers, so moving it
is its own individually reviewable change rather than a rider on this one. It is
declared in `PENDING` in `scripts/doctor_modules.py`, which is the record that it
is next rather than forgotten.

Python 3.9 compatible.
"""

import json
import os
import re
import shutil
import subprocess

import doctor


# The MCP registration that carries the channel into a session (#621). Named
# separately from CHANNEL_SERVER's own definition in `bin/oss-workspace` -- shell
# and Python cannot share one constant -- and kept identical to it by
# `tests/test_doctor_mcp_channel_registration_621.py`'s own sync check, rather than
# by inspection, for the reason #577's supertool-rule comparison gives: a fact
# duplicated across two files drifts, and the drift is invisible from either file
# alone.
CHANNEL_SERVER = "oss-channel"

_MCP_ARGS_RE = re.compile(r"^[ \t]*Args:[ \t]*(.*?)[ \t\r]*$", re.MULTILINE)


def mcp_channel_registration_state(server=None, run=None, which=None, env=None):
    """Is the channel MCP server registered, and does the path it stores exist?

    `watch_channel_state` above answers which channel NAME this repo resolves to;
    `radar_publish_state` answers whether a board is DECLARED. Neither asks whether
    any MCP server actually carries either into a session -- `grep mcp
    scripts/doctor.py` answered zero results for the whole life of this file, while
    `bin/oss-workspace:873-944` already asks exactly this question, at session-open,
    on stderr, where a maintainer running this diagnostic specifically because
    something is not working never sees it.

    Returns ``(state, detail)``. Six states, mirrored from `bin/oss-workspace`'s own
    three-state read of `claude mcp get` (registered-and-resolvable /
    registered-with-unresolvable-consumer-path / registered-with-unreadable-entry /
    not-registered) plus two this diagnostic needs that a session-opener does not,
    because it can be run when nothing is trying to open a session at all:

    * ``could-not-ask`` -- `claude` is not on PATH, or the call itself did not run.
      Not `not-registered`: that would claim an answer neither this process nor the
      reader's own shell was ever in a position to give.
    * ``not-registered`` -- `claude mcp get <server>` answered a nonzero exit, which
      is what it does for a name nothing has configured.
    * ``unreadable-entry`` -- the call answered 0 (a server config for this name
      exists) but no `Args:` line could be parsed out of it -- the shape
      `bin/oss-workspace`'s own comment names for a project-scope entry, which
      prints no Command/Args at all. Where it points is unknown, and this is not
      the same fact as absent: the comparison failed, the registration did not.
    * ``target-absent`` -- an `Args:` path was read and does not exist here.
      `bin/oss-workspace:873-879`'s own reasoning: `claude mcp get` answers 0 for
      any CONFIGURED server whether or not the file it names still exists, because
      the path `claude mcp add` stores is absolute and version-pinned and the
      plugin cache drops the old version directory on auto-update -- the
      registration outlives the file it names.
    * ``target-unreadable`` -- an `Args:` path was read and the filesystem would
      not say whether it exists (a permission-denied ancestor, an over-long
      component). Kept apart from `target-absent`: the exception in hand answers
      "could not tell", not "confirmed gone", and reporting the two the same way
      is the trap `release_delta.py`'s own `_read_config` was bitten by (#380).
    * ``registered`` -- an `Args:` path was read and exists.

    An embedded null byte in the stored path folds into ``could-not-ask`` -- `os.stat`
    raises `ValueError`, not `OSError`, for one, and that is a fact about the
    argument this function was handed rather than about the registration, the same
    distinction `_dir_state`'s own docstring draws for `.oss.json`.

    `run` and `which` are injected for the same reason `tool_binary_architecture`
    injects them: every branch is assertable without shelling out. This performs no
    registration and no removal -- `bin/oss-workspace` owns that, and this reads
    only, the same division `CLAUDE.md` draws for #610/#618's `.mcp.json`.

    #629: `bin/oss-workspace` already runs `claude mcp get {server}` at session-open,
    a few lines before it shells out to this diagnostic -- so a launcher-opened
    session paid for the identical subprocess call twice, and `claude` is not a
    cheap binary to start (~1.3s measured on this machine). When the launcher has
    already asked, it exports the raw answer (`OSS_WORKSPACE_MCP_CHECKED`,
    `_STATUS`, `_OUTPUT`) and this reads that instead of shelling out again.

    This is a relay, not a cache: the two calls happen seconds apart inside one
    session-open sequence, never across the kind of interval this repo's own
    `statusline.py` cache history warns about (a reading taken once and read as
    fresh much later). `env` defaults to `os.environ` and is injected for the same
    reason `run`/`which` are. The handoff is trusted only for `CHANNEL_SERVER`
    itself: `bin/oss-workspace` only ever pre-asks about its own hardcoded server,
    so a caller asking about a different `server` -- every test in this file, and
    any future caller -- always falls through to a real ask, never to a stale
    handoff answering the wrong question. A malformed `_STATUS` (not an integer)
    falls through the same way rather than guessing.
    """
    server = server or CHANNEL_SERVER
    env = os.environ if env is None else env
    which = shutil.which if which is None else which
    run = subprocess.run if run is None else run

    precomputed = (
        server == CHANNEL_SERVER and env.get("OSS_WORKSPACE_MCP_CHECKED") == "1"
    )
    returncode = None
    if precomputed:
        try:
            returncode = int(env.get("OSS_WORKSPACE_MCP_STATUS", ""))
        except ValueError:
            precomputed = False

    if precomputed:
        text = env.get("OSS_WORKSPACE_MCP_OUTPUT", "")
    else:
        # The RESOLVED path, not the bare name (#753/#810's own Windows CI
        # failure): `which()` performs the PATHEXT search that turns `claude`
        # into `claude.cmd`, but `subprocess.run(shell=False)` on Windows does
        # not -- it needs the extension already in hand. Asking `which()` and
        # then still handing `run()` the bare name gets exactly the "not
        # found" failure `which()` was called to rule out.
        claude_bin = which("claude")
        if claude_bin is None:
            return "could-not-ask", "claude is not on PATH"
        try:
            completed = run(
                [claude_bin, "mcp", "get", server],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return "could-not-ask", "`claude mcp get {}` did not run ({})".format(
                server, exc
            )
        returncode = completed.returncode
        stdout = completed.stdout
        text = (
            stdout.decode("utf-8", "replace")
            if isinstance(stdout, bytes)
            else str(stdout or "")
        )

    if returncode != 0:
        return "not-registered", ""
    match = _MCP_ARGS_RE.search(text)
    if match is None or not match.group(1).strip():
        return "unreadable-entry", doctor._one_line(text, limit=200)
    target = match.group(1).strip()
    try:
        os.stat(target)
    except (FileNotFoundError, NotADirectoryError):
        # Absence, stated by the exception itself -- the same pair
        # `_locate_on_path` and `supertool_entry_point` both already treat as
        # absence: `NotADirectoryError` says an ancestor of `target` is a plain
        # file, so no path under it can exist, which is exactly what "gone" means
        # here. No second question is asked of the filesystem to explain why the
        # first failed (same rule `_read_config` was bitten by in #380).
        return "target-absent", target
    except ValueError:
        # `os.stat` raises `ValueError`, not `OSError`, for a path carrying an
        # embedded null byte -- the same class `_dir_state`'s own docstring names
        # elsewhere in this file. `target` was parsed out of `claude mcp get`'s
        # output, which reflects `~/.claude.json`; that file is JSON, and JSON can
        # spell a null. This must not raise: doctor.py's whole contract is exit 0,
        # one VERDICT line, never a traceback out of a malformed registration.
        return (
            "could-not-ask",
            "the registered path could not be checked (embedded null byte)",
        )
    except OSError as exc:
        return "target-unreadable", "{} ({})".format(
            target, exc.strerror or exc.__class__.__name__
        )
    return "registered", target


def check_mcp_channel_registration(
    server=None, run=None, which=None, env=None, precomputed=None
):
    """One line, in every state -- see `mcp_channel_registration_state`.

    OK here never means "the board is live". This reads a registration and, when
    one exists, checks that the file it names is still there; it does not run
    `claude mcp get` against every scope, does not start the consumer, and does not
    establish that anything is listening on the socket -- the same limit
    `check_watch_channel` and `check_radar_publish` each state about their own
    reads. Together the three now cover name, declaration and transport; before
    this, the third was silent on both sides of it (#621).

    `precomputed` -- a `(state, detail)` pair from `mcp_channel_registration_state`,
    for a caller that already asked and wants to hand this check the answer
    rather than have it shell out to `claude mcp get` again. `main()` does
    NOT do this today: threading one answer to both this check and
    `check_channel_consumer_pin` was tried and reverted, because it made the
    real ask run even when a caller had stubbed one of the two checks
    specifically to avoid it (self-review finding). `main()` calls each
    check with no arguments, and each reads the registration independently.

    `env` is also read directly here, not only threaded through to
    `mcp_channel_registration_state` (#1307 self-review finding): when
    `bin/oss-workspace` arms the channel flag against an installed plugin's
    own server instead of `oss-channel` (#1307's own `plugin_channel_arm_
    decision`), `oss-channel` is correctly, deliberately left unregistered --
    and a bare re-ask of `claude mcp get oss-channel` a few lines later, in
    THIS diagnostic, would answer `not-registered` and print the ordinary
    "run bin/oss-workspace once, or claude mcp add ..." remedy, telling a
    maintainer to manually recreate the exact collision the launcher just
    avoided. `OSS_WORKSPACE_CHANNEL_ARM_TARGET`, exported by the launcher
    only in that branch, names the server actually carrying the channel;
    read here to render `not-registered` as `ok` with the real target named,
    rather than as the ordinary registration gap.
    """
    env = os.environ if env is None else env
    state, detail = (
        precomputed
        if precomputed is not None
        else doctor.mcp_channel_registration_state(
            server=server, run=run, which=which, env=env
        )
    )
    label = server or CHANNEL_SERVER
    arm_target = env.get("OSS_WORKSPACE_CHANNEL_ARM_TARGET", "")
    if state == "not-registered" and arm_target and arm_target != label:
        # #1344: `arm_target` is untrusted relay data -- a stale export left
        # over from an earlier session, or a value inherited from an
        # unrelated parent shell, would otherwise convert a genuine
        # `not-registered` finding into a clean `OK` forever, with nothing
        # here ever having asked `claude mcp get` whether that name actually
        # resolves. Verified the same way the primary label already was,
        # via the injected `run`/`which` rather than a second, independent
        # ask: three outcomes, not two -- confirmed, contradicted, or the
        # verification itself could not be made.
        arm_state, arm_detail = doctor.mcp_channel_registration_state(
            server=arm_target, run=run, which=which, env=env
        )
        if arm_state == "registered":
            doctor.report(
                "OK",
                "channel MCP registration: {} is not registered, but {} already "
                "provides the claude-channel consumer for this repo (an installed "
                "plugin's own .mcp.json), verified via claude mcp get -- nothing "
                "to register.".format(label, arm_target),
            )
            return
        if arm_state == "could-not-ask":
            doctor.report(
                "WARN",
                "channel MCP registration: {} is not registered, and "
                "OSS_WORKSPACE_CHANNEL_ARM_TARGET names {} as covering it, but "
                "whether that actually resolves could not be verified ({}) -- "
                "not answered as OK, which would trust an unverified "
                "relay.".format(label, arm_target, arm_detail),
            )
            return
        # Any other state (not-registered, unreadable-entry, target-absent,
        # target-unreadable) means the named arm target does NOT itself
        # amount to a verified registration -- the relay does not hold, and
        # this must not silently swallow the real gap it was reporting.
        doctor.report(
            "WARN",
            "channel MCP registration: {} is not registered, and "
            "OSS_WORKSPACE_CHANNEL_ARM_TARGET names {} as covering it, but "
            "claude mcp get {} answered {} rather than confirming a real "
            "registration -- treating {} as not registered rather than "
            "trusting an unverified relay. bin/oss-workspace registers it at "
            "session-open; run it once, or `claude mcp add -s local {} bun "
            "<path to claude-channel/channel.ts>`.".format(
                label, arm_target, arm_target, arm_state, label, label
            ),
        )
        return
    if state == "could-not-ask":
        doctor.report(
            "WARN",
            "channel MCP registration: {} ({}), so whether {} is registered is "
            "unknown -- not answered as unregistered, which would send you to "
            "register a server that may already be there.".format(detail, label, label),
        )
        return
    if state == "not-registered":
        doctor.report(
            "WARN",
            "channel MCP registration: {} is not registered, so nothing carries "
            "the watch channel into a session. bin/oss-workspace registers it at "
            "session-open; run it once, or `claude mcp add -s local {} bun "
            "<path to claude-channel/channel.ts>`.".format(label, label),
        )
        return
    if state == "unreadable-entry":
        doctor.report(
            "WARN",
            "channel MCP registration: {} answers for {}, but no Command or Args "
            "line could be read out of it ({}), so where it points is unknown and "
            "cannot be compared. Not the same as absent -- the comparison failed, "
            "the registration did not. `claude mcp remove {} -s local` and start a "
            "session again to have it registered from scratch.".format(
                label, label, detail, label
            ),
        )
        return
    if state == "target-absent":
        doctor.report(
            "WARN",
            "channel MCP registration: {} is registered pointing at {}, which does "
            "not exist. `claude mcp get` answers 0 for any configured server "
            "whether or not the file it names still exists -- the path is "
            "absolute and version-pinned, and the plugin cache drops the old "
            "version directory on update, so the registration outlives the file. "
            "`claude mcp remove {} -s local` and start a session again to have it "
            "re-registered at the current path.".format(label, detail, label),
        )
        return
    if state == "target-unreadable":
        doctor.report(
            "WARN",
            "channel MCP registration: {} is registered pointing at {}, and the "
            "filesystem would not say whether it exists -- so this is unknown, not "
            "confirmed gone.".format(label, detail),
        )
        return
    doctor.report(
        "OK",
        "channel MCP registration: {} is registered pointing at {}, which exists. "
        "This confirms the registration and the file; it does not confirm the "
        "consumer starts, that bun is on PATH, or that anything is listening on "
        "the socket.".format(label, detail),
    )


# --- pre-launch channel-consumer census (#810) --------------------------------
#
# `check_mcp_channel_registration` above answers whether THIS project's own
# `oss-channel` entry is registered and resolvable. It has nothing to say about
# whether some OTHER configured MCP server -- another project-scope `.mcp.json`,
# another local-scope registration nobody remembers making -- ALSO resolves to
# `notifiers/claude-channel/channel.ts`, the one script every claude-channel
# server runs. Two servers racing for that script's Unix socket is invisible from
# inside a session: one binds, the harness's connection to the other is refused,
# and `channel:health` can only report `CANNOT DETERMINE` -- `claude mcp get`
# cannot tell which server the harness actually holds a connection to. The
# launcher is the only place this is both visible (`claude mcp list` enumerates
# every configured server, regardless of which file declared it) and avoidable
# (before the flag that starts the race is armed). This mirrors that census so
# `/oss:doctor` reports the same collision without opening a session, per the
# issue's own step 3 -- the launcher and this diagnostic read `claude mcp list`
# through the SAME parser (`channel_consumer_names`, immediately below) so the
# two cannot disagree about the count.

#: Matches a claude-channel consumer's own script inside an MCP server's
#: command/args, on either separator: `claude mcp list` is read from THIS
#: machine's own claude installation, and a Windows entry stores backslashes
#: where a POSIX one stores forward slashes -- CLAUDE.md's own long-running
#: warning about reading a platform's separators out of one literal.
#:
#: NOT anchored at end-of-line ($) -- measured against a real `claude mcp
#: list` (2.1.219) rather than the issue's own illustrative example: every row
#: carries a trailing ` - <connection status>` after the args
#: (`... channel.ts - Failed to connect`), so an end-anchored version matched
#: zero rows against the actual shape this launcher runs against every day,
#: while passing every test built only from the issue's own clean example.
#: Matched instead by what follows the path: end of string, or whitespace --
#: never mid-word, so a path merely CONTAINING this fragment as a substring of
#: a longer filename cannot false-positive.
_CHANNEL_CONSUMER_SUFFIX_RE = re.compile(
    r"(?:/|\\)notifiers(?:/|\\)claude-channel(?:/|\\)channel\.ts(?:[ \t\r]|$)"
)

#: #1339: a `plugin:<key>:<server>` label's `key` and `server` segments are
#: both attacker-shapable data read verbatim out of files this process does
#: not control (the plugin registry's own JSON keys, and a plugin's own
#: `.mcp.json` server names). `bin/oss-workspace`'s `single` precheck arm
#: transports a label and its resolved target to the shell as two separate
#: `print()` lines, read back positionally with `sed -n '1p'`/`sed -n '2p'` --
#: an embedded newline lets a crafted plugin forge a THIRD line that gets
#: read back as the arm target instead of the real server name. Any other
#: C0 control character or DEL reaching that same two-line transport is the
#: identical class of defect even without a literal newline, so the whole
#: control-character range is rejected here, once, at the boundary -- never
#: only the one byte the issue's own repro happened to use.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")

#: `claude mcp list` prints one server per line, `name:` then whitespace then its
#: command and args -- `oss-channel:    bun /path/to/channel.ts`, padded so the
#: colons line up, which is why this is `[ \t]+` rather than a single space.
_MCP_LIST_LINE_RE = re.compile(r"^([^\s:][^:]*):[ \t]+(.*)$")

#: Where the harness records every currently installed plugin, keyed by
#: `name@marketplace`, each carrying its own `installPath`. Same file
#: `bin/oss-workspace`'s own `FIND_CONSUMER` heredoc reads to locate
#: supertool's consumer script -- see the module-level note below for why
#: this walks EVERY installed plugin rather than one hardcoded name.
_PLUGIN_REGISTRY_PATH = os.path.join(
    os.path.expanduser("~"), ".claude", "plugins", "installed_plugins.json"
)


def _entry_in_scope(entry, project_dir):
    """Is this ONE registry row actually loadable into a session opened over
    `project_dir`? Self-review finding on #1241's first version (an Explore
    reviewer spawn, against this machine's own real registry): the original
    `_plugin_install_paths` walked EVERY row under every plugin key with no
    scope filtering at all, and this machine's own registry demonstrates the
    shape that breaks -- the same plugin key carries many `"scope":
    "project"` rows, each pinned to a DIFFERENT `projectPath` (one per repo
    it was ever installed into), plus `"scope": "local"` rows and exactly one
    `"scope": "user"` row loaded everywhere. A row scoped to a project that
    is not this one can never be loaded into THIS session, so counting it
    toward this census is exactly the "population walked too broadly"
    mistake #886/#895's own wildcard-scoping already reasons about avoiding
    for a different check in this diff -- flagging an unrelated grant "would
    turn a genuine absent into a false" collision, and the same argument
    applies to an unrelated project's plugin install here.

    `scope == "user"` (or a missing/unrecognised scope -- conservatively
    in-scope, matching the "never silently narrow past what a shape nobody
    has seen yet might mean" caution the rest of this module already takes)
    is loaded regardless of which project a session opens over. `"project"`
    and `"local"` are loaded only for the ONE `projectPath` they name, so
    those are in scope only when it resolves to the same directory as
    `project_dir` -- compared as `os.path.normpath(os.path.abspath(...))`
    on both sides so `.`/a trailing slash/a relative spelling do not
    produce a false negative. When `project_dir` itself is not given (a
    caller with no directory to compare against), no filtering is applied
    at all -- every row is in scope, the pre-fix behaviour -- because
    excluding project-scoped rows with nothing to compare them to would
    silently narrow the population past what could actually be established,
    the same "unreadable neighbour must not send you to the wrong absence"
    principle this file's other helpers already state.
    """
    if project_dir is None:
        return True
    scope = entry.get("scope")
    if scope not in ("project", "local"):
        return True
    project_path = entry.get("projectPath")
    if not isinstance(project_path, str) or not project_path:
        # A project/local-scoped row with no recorded projectPath cannot be
        # compared -- conservatively in scope rather than silently dropped.
        return True
    try:
        return os.path.normpath(os.path.abspath(project_path)) == os.path.normpath(
            os.path.abspath(str(project_dir))
        )
    except (OSError, ValueError):
        return True


def _plugin_install_paths(registry_path=None, project_dir=None):
    """``(pairs, None)`` or ``(None, reason)`` -- every ``(plugin_key,
    installPath)`` the harness's own plugin registry records that is
    actually LOADABLE into a session opened over `project_dir` (see
    `_entry_in_scope` above), across ALL installed plugins, not only
    supertool.

    #1241: the harness loads a plugin's own `.mcp.json` servers directly --
    they are injected into the session under `plugin:<name>:<server>` and run
    as a child process of the `claude` session itself -- and **no `claude
    mcp` surface reports them**: `claude mcp list` omits them entirely, and
    `claude mcp get plugin:<name>:<server>` answers "No MCP server named
    ...". `channel_consumer_names` below, parsing `claude mcp list`, is
    therefore not reading an incomplete rendering of the population -- the
    population is not on that surface at all. This reads the SAME registry
    `bin/oss-workspace`'s `FIND_CONSUMER` heredoc already reads to find
    supertool's own consumer script, generalised past that one hardcoded
    plugin name: any installed plugin can ship a `.mcp.json` with a
    claude-channel consumer, and the census this module exists to run has no
    business assuming only supertool ever will.

    A registry that does not exist at all means no plugins are installed
    through this mechanism -- ``([], None)``, not an error, mirroring
    `FIND_CONSUMER`'s own treatment of the identical case. A registry that
    exists but cannot be read or parsed is a real gap in what this census can
    establish and must not silently read as "no plugins": ``(None, reason)``,
    so the caller can render the third state rather than a false `single`/
    `none`.
    """
    registry_path = registry_path or _PLUGIN_REGISTRY_PATH
    try:
        with open(registry_path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except FileNotFoundError:
        return [], None
    except OSError as exc:
        return None, "{} could not be read ({})".format(registry_path, exc)
    except ValueError as exc:
        return None, "{} is not valid JSON ({})".format(registry_path, exc)
    if not isinstance(doc, dict):
        return None, "{} is not a JSON object".format(registry_path)
    plugins = doc.get("plugins")
    if plugins is None:
        plugins = {}
    if not isinstance(plugins, dict):
        return None, '{}\'s "plugins" entry is not a JSON object'.format(registry_path)
    pairs = []
    for key, entries in plugins.items():
        if entries is None:
            continue
        if not isinstance(entries, list):
            return None, "{}'s {} entry is not a JSON array".format(registry_path, key)
        for entry in entries:
            if not isinstance(entry, dict):
                return (
                    None,
                    "{} lists an install entry for {} that is not a JSON object".format(
                        registry_path, key
                    ),
                )
            if not _entry_in_scope(entry, project_dir):
                continue
            install_path = entry.get("installPath")
            if isinstance(install_path, str) and install_path:
                pairs.append((key, install_path))
    return pairs, None


def _plugin_channel_consumer_names(plugin_registry_path=None, project_dir=None):
    """``(names, None)`` or ``(None, reason)`` -- one label per installed
    plugin, IN SCOPE for `project_dir` (see `_entry_in_scope`), whose OWN
    `.mcp.json` declares an MCP server resolving to the claude-channel
    consumer script (#1241). Best-effort per install: a plugin whose
    `.mcp.json` is simply absent contributes nothing (most plugins ship
    none); a plugin whose `.mcp.json` EXISTS but cannot be read or parsed is
    a real gap, and turns the whole result into ``(None, reason)`` rather
    than silently omitting just that one plugin -- a partial read of this
    population is exactly the shape #911 already named for the
    project-scope case, and the same caution applies here: an unreadable
    neighbour must not make the others look like the whole population.
    """
    pairs, reason = _plugin_install_paths(plugin_registry_path, project_dir=project_dir)
    if pairs is None:
        return None, reason
    # #1241 self-review finding (dogfooded against this machine's own real
    # registry): the registry records one row per PROJECT that ever
    # installed a plugin, plus every version ever installed, not one row per
    # currently-active server -- this machine's own `installed_plugins.json`
    # carries 17 rows for `supertool@dpt-plugins` alone, mostly repeating the
    # SAME installPath. Counting each row as a separate consumer turned a
    # real, single collision into a reported "18 servers", which is not a
    # fact about how many processes could ever actually race for the socket
    # -- only one version of one plugin is ever loaded into a given session.
    # Dedup on the label itself (`plugin:<key>:<server>`), first-seen order:
    # the SAME (key, server) name found via a different install-path row (a
    # different project's copy, or an older version whose `.mcp.json` still
    # declares the identical server) is one consumer, not several.
    names = []
    seen = set()
    for key, install_path in pairs:
        mcp_path = os.path.join(install_path, ".mcp.json")
        try:
            with open(mcp_path, encoding="utf-8") as handle:
                doc = json.load(handle)
        except FileNotFoundError:
            continue
        except OSError as exc:
            return None, "{} could not be read ({})".format(mcp_path, exc)
        except ValueError as exc:
            return None, "{} is not valid JSON ({})".format(mcp_path, exc)
        if not isinstance(doc, dict):
            return None, "{} is not a JSON object".format(mcp_path)
        servers = doc.get("mcpServers")
        if servers is None:
            continue
        if not isinstance(servers, dict):
            return None, '{}\'s "mcpServers" entry is not a JSON object'.format(
                mcp_path
            )
        for server_name, spec in servers.items():
            if not isinstance(spec, dict):
                continue
            parts = []
            command = spec.get("command")
            if isinstance(command, str):
                parts.append(command)
            args = spec.get("args")
            if isinstance(args, list):
                parts.extend(a for a in args if isinstance(a, str))
            if _CHANNEL_CONSUMER_SUFFIX_RE.search(" ".join(parts)):
                label = "plugin:{}:{}".format(key, server_name)
                # #1339: `key` (a plugin registry JSON key) and `server_name`
                # (a plugin's own `.mcp.json` server name) are both
                # attacker-shapable data this process does not control, and
                # EVERY caller of this function -- `plugin_channel_arm_decision`
                # below, and `channel_consumer_census_state` further down --
                # eventually hands a built label to a transport that reads a
                # multi-line report back positionally (`bin/oss-workspace`'s
                # `single`-arm `print()`/`sed` pair, and its `CHANNEL_CENSUS`
                # heredoc's own `collision` listing). A control character
                # (a newline, most directly) forges an extra line either
                # transport then reads back as real data. Rejected HERE, at
                # the one place a label is actually built, rather than once
                # per caller: a caller added later inherits the protection
                # instead of needing to remember it.
                if _CONTROL_CHAR_RE.search(label):
                    return None, (
                        "{} declares an MCP server name (or the installed-plugin "
                        "registry declares a key) containing a control character "
                        "and cannot be trusted".format(mcp_path)
                    )
                if label not in seen:
                    seen.add(label)
                    names.append(label)
    return names, None


def resolvable_plugin_server_name(label):
    """`_plugin_channel_consumer_names` reports `plugin:<key>:<server>`, built
    from the installed-plugin registry's own `<name>@<marketplace>` key --
    which is NOT the name `claude mcp get` or
    `--dangerously-load-development-channels server:NAME` resolve. Verified
    live against claude 2.1.261 (#1307's own first open question): `claude
    mcp get "plugin:supertool@dpt-plugins:claude-channel"` answers "No MCP
    server named ...", while `claude mcp get "plugin:supertool:claude-channel"`
    (the bare plugin name, no marketplace) resolves -- confirmed against
    `claude mcp list`'s own rendering of the identical server on the same
    machine.

    This strips the `@<marketplace>` segment out of the KEY segment only --
    split structurally on the label's own `plugin:<key>:<server>` shape,
    never a bare regex over the whole string. `<server>` is a JSON object
    key out of a plugin's own `.mcp.json` (`_plugin_channel_consumer_names`
    reads it verbatim, no shape check), so it is attacker-shapable data from
    a plugin that need not be well-formed -- a self-review finding: an
    earlier version matched the first `@...:`-shaped substring ANYWHERE in
    the label, which stripped a chunk out of `<server>` itself, not a
    marketplace qualifier, whenever the registry `key` carried no `@` (a
    legacy/malformed row) while `<server>` happened to contain one, e.g.
    `plugin:legacykey:weird@evil:server` -> the wrong
    `plugin:legacykey:weird:server`. Splitting on the label's own two
    delimiting colons, rather than scanning past them, makes that
    combination unreachable: only the key segment is ever touched, and the
    server segment (whatever it contains) is carried through unchanged.

    Kept separate from `_plugin_channel_consumer_names`'s own label format
    on purpose: that format is a REPORTING label, asserted verbatim by
    `tests/test_plugin_channel_consumer_census_1241.py` and rendered into
    doctor.py's own WARN text, and changing it there would be a much larger,
    unrelated blast radius for a fact only the arming decision below needs.
    A label not shaped like `plugin:<key>:<server>` at all (should not
    happen, since `_plugin_channel_consumer_names` always builds it this
    way, but nothing here assumes it cannot) is returned unchanged rather
    than guessed at.
    """
    prefix = "plugin:"
    if not label.startswith(prefix):
        return label
    key, sep, server_name = label[len(prefix) :].partition(":")
    if not sep:
        return label
    return prefix + key.split("@", 1)[0] + ":" + server_name


def plugin_channel_arm_decision(plugin_registry_path=None, project_dir=None):
    """What should `bin/oss-workspace` do about registering `oss-channel`,
    given the IN-SCOPE installed-plugin population, asked BEFORE that
    registration happens (#1307)?

    Registering `oss-channel` unconditionally and only asking the
    post-registration census afterward (`channel_consumer_census_state`,
    below) means that census counts the launcher's own just-added
    registration as a SECOND consumer whenever a plugin already ships one --
    disarming the channel over the collision the launcher itself just
    created. This is the same population `_plugin_channel_consumer_names`
    already derives for that census's own plugin half, asked earlier, before
    the registration decision rather than after it.

    Returns ``(state, detail)``, four states:

    * ``could-not-ask`` -- the plugin population could not be established
      (an unreadable or malformed registry, one plugin's own unreadable
      `.mcp.json`, or a label built from it carrying a control character --
      see below). `detail` is the reason. Falls back to registering
      `oss-channel` as before and letting the post-registration census
      decide -- an unreadable registry must not silently read as "no plugin
      consumer", which would stop registering the only one there is.
    * ``none`` -- zero in-scope plugin consumers. Register `oss-channel` as
      before; nothing else could ever collide with it.
    * ``single`` -- exactly one. `detail` is ``(label, resolvable_name)`` --
      `label` is `_plugin_channel_consumer_names`'s own reporting form,
      `resolvable_name` is `resolvable_plugin_server_name(label)`, the name
      to actually arm the flag against. Do NOT register `oss-channel`.
    * ``plural`` -- two or more in-scope plugin consumers already collide
      with each other, before `oss-channel` is even considered. `detail` is
      their labels. Do not register `oss-channel` either -- a third racer
      would not help -- but there is no single target to arm against, so the
      session opens without the flag.

    #1339: `key` (a plugin registry JSON key) and `server_name` (a plugin's
    own `.mcp.json` server name) are both attacker-shapable data, and
    `bin/oss-workspace`'s `single` arm transports `label`/`resolvable` to the
    shell as two bare `print()` lines read back positionally -- an embedded
    control character (a newline, most directly) forges an extra line the
    launcher then reads back as the arm target. `_plugin_channel_consumer_names`
    itself now refuses to build a label carrying one (self-review finding: an
    earlier version of this fix checked only here, downstream, which left
    `channel_consumer_census_state`'s own separate call to
    `_plugin_channel_consumer_names` -- reached via `bin/oss-workspace`'s
    `CHANNEL_CENSUS` heredoc -- still passing a tainted label through
    unprotected), so `names` below is never None for that reason alone --
    it is `(None, reason)`, the SAME `could-not-ask` shape an unreadable
    registry already produces, which this function only has to relay.
    """
    names, reason = _plugin_channel_consumer_names(
        plugin_registry_path, project_dir=project_dir
    )
    if names is None:
        return "could-not-ask", reason
    if not names:
        return "none", ""
    if len(names) == 1:
        label = names[0]
        return "single", (label, resolvable_plugin_server_name(label))
    return "plural", names


def channel_consumer_names(text):
    """Every MCP server name in `claude mcp list` output whose command/args end in
    the claude-channel consumer script (#810).

    A line that does not match the `name: rest` shape at all -- a continuation
    line, a blank line, a banner -- is skipped rather than guessed at; this is a
    census of what CAN be counted, not a best-effort parse of everything `claude
    mcp list` might ever print. Order is preserved and names are not deduplicated:
    two rows naming the same server would be a `claude mcp list` defect worth
    seeing in the count, not something to paper over here.
    """
    names = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        match = _MCP_LIST_LINE_RE.match(line)
        if match is None:
            continue
        name, rest = match.group(1).strip(), match.group(2)
        if _CHANNEL_CONSUMER_SUFFIX_RE.search(rest.rstrip("\r")):
            names.append(name)
    return names


def _mcp_list_consumer_names(run=None, which=None, env=None):
    """``(names, None)`` or ``(None, reason)`` -- the `claude mcp list`-visible
    half of the census, split out of `channel_consumer_census_state` so #1241's
    plugin-population half (below) can be folded in without duplicating the
    launcher-relay handling. Same relay contract as before: `env`'s
    `OSS_WORKSPACE_CENSUS_CHECKED`/`_REPORT` are read first, and a real `claude
    mcp list` call happens only when no relay is present or recognised.
    """
    env = os.environ if env is None else env
    relayed = env.get("OSS_WORKSPACE_CENSUS_CHECKED") == "1"
    if relayed:
        lines = env.get("OSS_WORKSPACE_CENSUS_REPORT", "").splitlines()
        state = lines[0].strip() if lines else ""
        rest = lines[1:]
        if state == "collision":
            return rest, None
        if state == "could-not-ask":
            return None, (rest[0] if rest else "")
        if state == "single":
            return (rest[0:1] if rest else []), None
        if state == "none":
            return [], None
        # An unrecognised or empty relay is not evidence of anything -- fall
        # through to a real ask rather than reporting a guess.
    which = shutil.which if which is None else which
    run = subprocess.run if run is None else run
    # The RESOLVED path, not the bare name -- see the identical comment and
    # incident in `mcp_channel_registration_state` above; both functions had
    # the same mismatch (ask `which()`, then still hand `run()` the bare
    # name), and both are fixed the same way.
    claude_bin = which("claude")
    if claude_bin is None:
        return None, "claude is not on PATH"
    try:
        completed = run(
            [claude_bin, "mcp", "list"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "`claude mcp list` did not run ({})".format(exc)
    if completed.returncode != 0:
        return None, "`claude mcp list` exited {}".format(completed.returncode)
    stdout = completed.stdout
    text = (
        stdout.decode("utf-8", "replace")
        if isinstance(stdout, bytes)
        else str(stdout or "")
    )
    return channel_consumer_names(text), None


def channel_consumer_census_state(
    run=None, which=None, env=None, plugin_registry_path=None, project_dir=None
):
    """How many MCP servers resolve to the claude-channel consumer script,
    across the TWO populations that can carry one -- never assumed from
    `oss-channel`'s own registration alone.

    Returns ``(state, detail)``. Three states, and the third is the one the
    issue names explicitly as never collapsing into the first: either half
    of the census failing to establish its own population must read as
    `could-not-ask`, never as "exactly one server" -- a crashed or refused
    probe is not evidence of a clean census, and reading it as one would
    silently arm a collision this check exists to catch.

    * ``could-not-ask`` -- either population could not be established:
      `claude` is not on PATH, the `claude mcp list` call itself did not
      run or exited non-zero, or the installed-plugin registry (or one
      installed plugin's own `.mcp.json`) could not be read or parsed.
      `detail` says which.
    * ``collision`` -- two or more servers across BOTH populations resolve
      to the consumer script. `detail` is their names, `claude mcp list`'s
      own order first, then the plugin population in registry order.
    * ``single`` -- exactly one, from either population. `detail` is that
      one name.
    * ``none`` -- zero in both. `detail` is empty.

    #1241: `claude mcp list` reports only servers configured on a `claude
    mcp` surface -- project or user scope. A server an INSTALLED PLUGIN
    ships in its own `.mcp.json` is loaded by the harness directly and
    appears on NO `claude mcp` surface at all (`claude mcp list` omits it;
    `claude mcp get plugin:<name>:<server>` answers "No MCP server named
    ..."), so the original single-population census could report `single`
    while a second, plugin-provided consumer silently held the socket --
    the issue's own repro. `_plugin_channel_consumer_names` (module-level,
    above) reads the SAME registry `bin/oss-workspace`'s `FIND_CONSUMER`
    heredoc already reads to answer this for supertool's own consumer,
    generalised to every installed plugin. `plugin_registry_path` threads
    through to it for the same reason `run`/`which`/`env` are injected here
    -- every branch assertable without touching the real filesystem.
    `project_dir`, when given, additionally scopes the plugin population to
    rows actually loadable into a session opened over it (`_entry_in_scope`)
    -- self-review finding: this machine's own real registry carries many
    `"scope": "project"` rows for the SAME plugin, each pinned to a
    different, unrelated project, and counting all of them toward this
    repository's own census would be exactly the "population walked too
    broadly" mistake this diff's own #886/#895 wildcard-scoping already
    reasons about avoiding for a different check.

    `bin/oss-workspace` already runs the `claude mcp list` half of this
    census, via `_mcp_list_consumer_names` above -- so a launcher-opened
    session paid for `claude mcp list` twice in the same session-open
    sequence (review finding on #810, the identical shape #629 already
    fixed for `mcp_channel_registration_state` above). When the launcher
    has already asked, it exports the raw multi-line report
    (`OSS_WORKSPACE_CENSUS_CHECKED`, `_REPORT`) and this reads that instead
    of shelling out again -- a relay, not a cache, on the same terms
    `mcp_channel_registration_state`'s own docstring states. The
    plugin-population half is NOT relayed (the launcher's own `FIND_CONSUMER`
    heredoc only ever answers about supertool's one install, not the full
    population this function needs) and is always read fresh here.
    """
    mcp_names, mcp_reason = _mcp_list_consumer_names(run=run, which=which, env=env)
    if mcp_names is None:
        return "could-not-ask", mcp_reason
    plugin_names, plugin_reason = _plugin_channel_consumer_names(
        plugin_registry_path, project_dir=project_dir
    )
    if plugin_names is None:
        return "could-not-ask", (
            "the claude mcp list population resolved ({} found), but the "
            "installed-plugin population could not be established: {}".format(
                len(mcp_names), plugin_reason
            )
        )
    names = list(mcp_names) + list(plugin_names)
    if len(names) >= 2:
        return "collision", names
    if len(names) == 1:
        return "single", names[0]
    return "none", ""


def check_channel_consumer_census(
    run=None, which=None, env=None, plugin_registry_path=None, project_dir=None
):
    """One line: is any OTHER server racing `oss-channel` for the same socket?

    Never OK on `could-not-ask` -- an unasked question is not a clean census, and
    rendering it as one would be exactly the absence this repository is named
    after landing on the check written to close a different instance of it.

    `env` threads through to `channel_consumer_census_state` for the launcher
    relay described there -- passed explicitly rather than only defaulting, the
    same shape `check_mcp_channel_registration`'s own `precomputed` parameter
    takes, so a caller can stub the relay independently of the real environment.
    `plugin_registry_path` threads through the same way for #1241's
    plugin-population half, and `project_dir` for that half's own project-scope
    filtering (`_entry_in_scope`) -- `doctor.py`'s own call site passes its
    `project_dir` here for exactly that reason.
    """
    state, detail = channel_consumer_census_state(
        run=run,
        which=which,
        env=env,
        plugin_registry_path=plugin_registry_path,
        project_dir=project_dir,
    )
    if state == "could-not-ask":
        doctor.report(
            "WARN",
            "channel MCP consumer census: {}, so whether a second configured MCP "
            "server, or an installed plugin's own claude-channel consumer, also "
            "resolves to the same script is unknown -- not the same as a census "
            "that found none.".format(detail),
        )
        return
    if state == "collision":
        doctor.report(
            "WARN",
            "channel MCP consumer census: {} MCP servers resolve to "
            "notifiers/claude-channel/channel.ts ({}) -- a session opened with the "
            "channel flag would race two servers for one Unix socket, and one is "
            "silently refused (channel:health degrades to CANNOT DETERMINE with no "
            "error surfaced). A `plugin:` prefixed name is an installed plugin's "
            "own `.mcp.json` server, loaded by the harness directly -- it appears "
            "on no `claude mcp` surface at all, so `claude mcp remove` cannot "
            "touch it; that plugin's own config is what declares it. "
            "bin/oss-workspace already declines to arm the flag when it sees "
            "this. Deleting or editing whichever config declared the extra one is "
            "not this diagnostic's call to make -- it names both and stops, per "
            "this repo's own ownership contract.".format(
                len(detail), ", ".join(detail)
            ),
        )
        return
    doctor.report(
        "OK",
        "channel MCP consumer census: {} MCP server(s) (configured or "
        "plugin-provided) resolve to notifiers/claude-channel/channel.ts, so no "
        "socket collision to declare.".format(1 if state == "single" else 0),
    )
