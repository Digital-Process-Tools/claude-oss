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

#: `claude mcp list` prints one server per line, `name:` then whitespace then its
#: command and args -- `oss-channel:    bun /path/to/channel.ts`, padded so the
#: colons line up, which is why this is `[ \t]+` rather than a single space.
_MCP_LIST_LINE_RE = re.compile(r"^([^\s:][^:]*):[ \t]+(.*)$")


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


def channel_consumer_census_state(run=None, which=None, env=None):
    """How many configured MCP servers resolve to the claude-channel consumer
    script, for THIS machine's `claude` -- never assumed from `oss-channel`'s own
    registration alone.

    Returns ``(state, detail)``. Three states, and the third is the one the issue
    names explicitly as never collapsing into the first: `claude mcp list` failing
    to run, timing out, or exiting non-zero must read as `could-not-ask`, never as
    "exactly one server" -- a crashed or refused probe is not evidence of a clean
    census, and reading it as one would silently arm a collision this check exists
    to catch.

    * ``could-not-ask`` -- `claude` is not on PATH, the call itself did not run, or
      it exited non-zero. `detail` says which.
    * ``collision`` -- two or more servers resolve to the consumer script. `detail`
      is the list of their names, in the order `claude mcp list` printed them.
    * ``single`` -- exactly one. `detail` is that one name.
    * ``none`` -- zero. `detail` is empty. Distinct from `single` because a caller
      deciding whether it is safe to arm a channel flag needs "nothing configured
      at all" told apart from "the one server I expect and nothing else" --
      `check_channel_consumer_census` below folds both into the same OK line, but
      the state itself keeps them separate for a caller that cares which.

    `bin/oss-workspace` already runs THIS exact census, via THIS exact function,
    a few lines before it shells out to `doctor.sh` -- so a launcher-opened
    session paid for `claude mcp list` twice in the same session-open sequence
    (review finding on #810, the identical shape #629 already fixed for
    `mcp_channel_registration_state` above). When the launcher has already
    asked, it exports the raw multi-line report (`OSS_WORKSPACE_CENSUS_CHECKED`,
    `_REPORT` -- the census's own `state` line followed by its `collision`
    names or `could-not-ask` detail, exactly the shape this function's own
    embedded-python callers already print) and this reads that instead of
    shelling out again. This is a relay, not a cache, on the same terms
    `mcp_channel_registration_state`'s own docstring states: the two calls
    happen seconds apart inside one session-open sequence, never across an
    interval this repo's `statusline.py` cache history would call stale. A
    relayed report this function does not recognise (empty, or an unrecognised
    first line) falls through to a real ask rather than guessing.
    """
    env = os.environ if env is None else env
    relayed = env.get("OSS_WORKSPACE_CENSUS_CHECKED") == "1"
    if relayed:
        lines = env.get("OSS_WORKSPACE_CENSUS_REPORT", "").splitlines()
        state = lines[0].strip() if lines else ""
        rest = lines[1:]
        if state == "collision":
            return "collision", rest
        if state == "could-not-ask":
            return "could-not-ask", (rest[0] if rest else "")
        if state == "single":
            return "single", (rest[0] if rest else "")
        if state == "none":
            return "none", ""
        # An unrecognised or empty relay is not evidence of anything -- fall
        # through to a real ask rather than reporting a guess.
    which = shutil.which if which is None else which
    run = subprocess.run if run is None else run
    if which("claude") is None:
        return "could-not-ask", "claude is not on PATH"
    try:
        completed = run(
            ["claude", "mcp", "list"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "could-not-ask", "`claude mcp list` did not run ({})".format(exc)
    if completed.returncode != 0:
        return "could-not-ask", "`claude mcp list` exited {}".format(completed.returncode)
    stdout = completed.stdout
    text = stdout.decode("utf-8", "replace") if isinstance(stdout, bytes) else str(stdout or "")
    names = channel_consumer_names(text)
    if len(names) >= 2:
        return "collision", names
    if len(names) == 1:
        return "single", names[0]
    return "none", ""


def check_channel_consumer_census(run=None, which=None, env=None):
    """One line: is any OTHER server racing `oss-channel` for the same socket?

    Never OK on `could-not-ask` -- an unasked question is not a clean census, and
    rendering it as one would be exactly the absence this repository is named
    after landing on the check written to close a different instance of it.

    `env` threads through to `channel_consumer_census_state` for the launcher
    relay described there -- passed explicitly rather than only defaulting, the
    same shape `check_mcp_channel_registration`'s own `precomputed` parameter
    takes, so a caller can stub the relay independently of the real environment.
    """
    state, detail = channel_consumer_census_state(run=run, which=which, env=env)
    if state == "could-not-ask":
        doctor.report(
            "WARN",
            "channel MCP consumer census: {}, so whether a second configured MCP "
            "server also resolves to the claude-channel consumer script is "
            "unknown -- not the same as a census that found none.".format(detail),
        )
        return
    if state == "collision":
        doctor.report(
            "WARN",
            "channel MCP consumer census: {} configured MCP servers resolve to "
            "notifiers/claude-channel/channel.ts ({}) -- a session opened with the "
            "channel flag would race two servers for one Unix socket, and one is "
            "silently refused (channel:health degrades to CANNOT DETERMINE with no "
            "error surfaced). bin/oss-workspace already declines to arm the flag "
            "when it sees this. Deleting or editing whichever config declared the "
            "extra one is not this diagnostic's call to make -- it names both and "
            "stops, per this repo's own ownership contract.".format(
                len(detail), ", ".join(detail)
            ),
        )
        return
    doctor.report(
        "OK",
        "channel MCP consumer census: {} configured MCP server(s) resolve to "
        "notifiers/claude-channel/channel.ts, so no socket collision to "
        "declare.".format(1 if state == "single" else 0),
    )

