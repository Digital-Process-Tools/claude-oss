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

    precomputed = server == CHANNEL_SERVER and env.get("OSS_WORKSPACE_MCP_CHECKED") == "1"
    returncode = None
    if precomputed:
        try:
            returncode = int(env.get("OSS_WORKSPACE_MCP_STATUS", ""))
        except ValueError:
            precomputed = False

    if precomputed:
        text = env.get("OSS_WORKSPACE_MCP_OUTPUT", "")
    else:
        if which("claude") is None:
            return "could-not-ask", "claude is not on PATH"
        try:
            completed = run(
                ["claude", "mcp", "get", server],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return "could-not-ask", "`claude mcp get {}` did not run ({})".format(server, exc)
        returncode = completed.returncode
        stdout = completed.stdout
        text = stdout.decode("utf-8", "replace") if isinstance(stdout, bytes) else str(stdout or "")

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
        return "could-not-ask", "the registered path could not be checked (embedded null byte)"
    except OSError as exc:
        return "target-unreadable", "{} ({})".format(target, exc.strerror or exc.__class__.__name__)
    return "registered", target



def check_mcp_channel_registration(server=None, run=None, which=None, env=None, precomputed=None):
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
    """
    state, detail = (
        precomputed if precomputed is not None
        else doctor.mcp_channel_registration_state(server=server, run=run, which=which, env=env)
    )
    label = server or CHANNEL_SERVER
    if state == "could-not-ask":
        doctor.report(
            "WARN",
            "channel MCP registration: {} ({}), so whether {} is registered is "
            "unknown -- not answered as unregistered, which would send you to "
            "register a server that may already be there.".format(
                detail, label, label
            ),
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
