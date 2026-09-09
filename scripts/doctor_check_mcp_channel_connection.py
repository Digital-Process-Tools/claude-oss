"""``check_mcp_channel_connection`` -- does the channel MCP server actually
connect, and is anything subscribed to the socket it binds (#1361)?

A new check, so it lives in its own module from the start rather than going
inline in ``doctor.py`` -- the convention block at the top of that file.

Every channel check that existed before this one answers a question strictly
upstream of delivery: `check_watch_channel` answers which NAME this repo
resolves to, `check_radar_publish` whether a board is DECLARED,
`check_mcp_channel_registration` whether a registration EXISTS and the file it
names is still on disk, `check_channel_consumer_pin` whether that file is the
current version, and `check_channel_consumer_census` whether two servers race
one socket. On the failure this check was written for, all of them were `OK` or
`WARN cosmetic` while nothing was delivered at all: a consumer spawned without
the project's channel name fell back to the machine-global default socket,
found another tool's consumer already holding it, refused to bind and exited.
The registration was present, the file was present, the version was current --
and the transport was dead.

`claude mcp list` already answers it. Its own rows carry the connection status
beside the command, so the same output the census parses for NAMES carries the
status this check reads:

    oss-channel: bun /path/to/channel.ts - ✘ Failed to connect — CONNECTION_CLOSED

Three states per server and never two, for the reason this repository is named
after: a status that could not be parsed is not a passing status.

Python 3.9 compatible.
"""

import os
import shutil
import subprocess

import re

import doctor
from doctor_check_mcp_channel_registration import _CHANNEL_CONSUMER_SUFFIX_RE

#: `claude mcp list`'s own row shape, and NOT
#: `doctor_check_mcp_channel_registration._MCP_LIST_LINE_RE`, which cannot parse
#: a `plugin:`-prefixed name: its name group stops at the first colon, so
#: `plugin:supertool:claude-channel: bun /path` never matches at all and every
#: plugin-declared server is invisible to it. That is a real gap in the #810
#: census's `claude mcp list` half -- filed separately rather than fixed here,
#: because widening that constant changes what the census counts and how it
#: dedups against its own plugin-registry half, which is a larger and separately
#: reviewable change than this check.
#:
#: Non-greedy up to the first `: ` (a colon followed by whitespace): a server
#: NAME may contain colons, its separator from the command may not.
_LIST_LINE_RE = re.compile(r"^([^\s].*?):[ \t]+(.*)$")

#: Substrings `claude mcp list` renders for a server that connected and one
#: that did not. Matched as substrings rather than by glyph: the check marks
#: are decoration and have already changed once across releases, while the
#: words have not. Order matters -- `Failed to connect` contains no `Connected`
#: but a future `Not connected` would, so the failing form is tested first.
_FAILED_MARKERS = ("Failed to connect", "✘")
_CONNECTED_MARKERS = ("Connected", "✔")

#: `claude mcp get` prints the harness's own reason on its own line under a
#: failed `Status:`. Read so a caller reports that reason rather than the word
#: `failed` alone.
_MCP_ISSUE_RE = re.compile(r"^[ \t]*Issue:[ \t]*(.*?)[ \t\r]*$", re.MULTILINE)


def channel_consumer_connections(text):
    """``[(name, state, detail), ...]`` for every `claude mcp list` row whose
    command resolves to the claude-channel consumer script.

    ``state`` is ``"connected"``, ``"failed"`` or ``"unknown"``. ``unknown`` is
    a real answer and never folded into either of the others: a row this parser
    did not recognise is a row whose status was not read, which is not the same
    fact as a server that failed, and reporting them alike is the defect class
    the module docstring names.

    ``detail`` carries whatever the row said after the command for a ``failed``
    row (the harness's own issue text, e.g. ``CONNECTION_CLOSED: Connection
    closed``), and the whole unrecognised remainder for an ``unknown`` one, so
    a reader is never told only that parsing failed.
    """
    rows = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        match = _LIST_LINE_RE.match(line)
        if match is None:
            continue
        name, rest = match.group(1).strip(), match.group(2)
        if not _CHANNEL_CONSUMER_SUFFIX_RE.search(rest):
            continue
        if any(marker in rest for marker in _FAILED_MARKERS):
            rows.append((name, "failed", doctor._one_line(rest, limit=200)))
        elif any(marker in rest for marker in _CONNECTED_MARKERS):
            rows.append((name, "connected", ""))
        else:
            rows.append((name, "unknown", doctor._one_line(rest, limit=200)))
    return rows


def mcp_channel_connection_state(run=None, which=None, env=None):
    """``(state, detail)`` -- does a channel consumer server actually connect?

    Five states:

    * ``could-not-ask`` -- `claude` is not on PATH, or the call did not run.
      Never `none`: an unasked question is not an absent server.
    * ``could-not-read`` -- the call answered but no row in its output resolved
      to the consumer script AND the output did not look like a server listing
      at all. Kept apart from `none` for the same reason.
    * ``none`` -- the listing was read and no configured server resolves to the
      consumer script. Nothing carries the channel; that is the registration
      checks' subject, not this one's, so this reports and does not duplicate
      their remedy.
    * ``connected`` -- at least one such server reports a live transport.
    * ``failed`` -- every such server reports a failed transport. `detail` is
      the rows, so the reader gets the harness's own reason rather than a
      restatement of it.

    `run` and `which` are injected for the same reason every sibling state
    function in `doctor_check_mcp_channel_registration.py` injects them: every
    branch is assertable without shelling out.

    This deliberately does NOT reuse the census relay
    (`OSS_WORKSPACE_CENSUS_CHECKED`/`_REPORT`): that relay carries names and a
    census verdict, not connection statuses, so reading it would answer a
    different question with a stale-looking confidence.
    """
    env = os.environ if env is None else env
    which = shutil.which if which is None else which
    run = subprocess.run if run is None else run

    # #1361: `bin/oss-workspace` asks `claude mcp list` once at session-open
    # and exports the raw answer, the same relay shape #629 and #810 already
    # use for the two asks either side of this one -- `claude` is ~1.3s to
    # start and the answer cannot have changed in the seconds between. A relay
    # that is absent or empty is not read as an empty listing: this falls
    # through to a real ask, so a launcher that could not run the command and a
    # machine with no consumer never render alike.
    relayed = env.get("OSS_WORKSPACE_MCP_LIST_OUTPUT", "")
    if relayed.strip():
        return _classify_listing(relayed)

    claude_bin = which("claude")
    if claude_bin is None:
        return "could-not-ask", "claude is not on PATH"
    try:
        completed = run(
            [claude_bin, "mcp", "list"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "could-not-ask", "`claude mcp list` did not run ({})".format(exc)
    stdout = completed.stdout
    text = (
        stdout.decode("utf-8", "replace")
        if isinstance(stdout, bytes)
        else str(stdout or "")
    )

    if completed.returncode != 0:
        # The exit code, not the shape of the output. A first draft of this
        # function asked instead whether ANY line parsed as a `name: rest` row,
        # reasoning that a listing which parsed proves the output was read --
        # and this file's own test caught it: `error: something went sideways`
        # matches that shape exactly, so a failed call read as a clean `none`.
        # A heuristic over prose cannot separate an error message from a row;
        # the exit code can, and was being discarded.
        return "could-not-read", doctor._one_line(text, limit=200)

    return _classify_listing(text)


def _classify_listing(text):
    """The verdict over one `claude mcp list` output, split out so the relayed
    and the freshly-asked paths cannot drift apart -- they are the same
    question over the same bytes, and two copies of this would be the
    duplicated-fact trap this repository forbids."""
    rows = channel_consumer_connections(text)
    if not rows:
        return "none", ""

    if any(state == "connected" for _, state, _ in rows):
        connected = [name for name, state, _ in rows if state == "connected"]
        return "connected", ", ".join(connected)
    if all(state == "failed" for _, state, _ in rows):
        return "failed", "; ".join(
            "{} -- {}".format(name, detail) for name, _, detail in rows
        )
    return "could-not-read", "; ".join(
        "{} [{}] {}".format(name, state, detail) for name, state, detail in rows
    )


def check_mcp_channel_connection(run=None, which=None, env=None):
    """One line, in every state -- see `mcp_channel_connection_state`.

    `OK` here means the transport is live. It does not mean an event reaches
    this session: subscription is a fact about the session that took the
    reading, which supertool's own `channel:health` answers and this does not
    duplicate.
    """
    state, detail = mcp_channel_connection_state(run=run, which=which, env=env)
    if state == "could-not-ask":
        # NOTICE, not WARN, when the reason is that `claude` is not on PATH at
        # all: there is no manual op and no `/oss:scaffold` run that clears it,
        # which by this repository's own doctor rule would make a WARN a bug in
        # the check rather than work. A CI runner is the standing example, and
        # it is where this first showed up -- a fully-scaffolded fixture
        # asserting `VERDICT: ok` went red on a check that could never answer
        # there. NOTICE is exactly #764's state for a check declaring itself
        # structurally unable to answer, and it does not gate the verdict.
        #
        # A call that RAN and failed is a different fact and stays a WARN:
        # something is wrong with an installation that has `claude` and cannot
        # ask it.
        doctor.report(
            "NOTICE" if "not on PATH" in detail else "WARN",
            "channel MCP connection: {}, so whether the channel consumer "
            "actually connects is unknown -- not answered as connected, which "
            "is the false OK this check exists to remove.".format(detail),
        )
        return
    if state == "could-not-read":
        # NOTICE for the same #764 reason as the arm above: this says the
        # listing's shape was not understood, which no manual op and no
        # `/oss:scaffold` run clears. The line drawn across this whole module:
        # WARN only where a fault is POSITIVELY established -- a failed
        # transport, no configured server, a consumer that is not delivering --
        # and NOTICE wherever nothing could be established at all. Warning on
        # the second kind invents work nobody can do, which is what took a
        # fully-scaffolded fixture asserting `VERDICT: ok` red on four CI legs.
        doctor.report(
            "NOTICE",
            "channel MCP connection: `claude mcp list` answered, but its "
            "connection status for the channel consumer could not be read "
            "({}) -- reported rather than passed, because a status that was "
            "not read is not a status that was OK.".format(detail),
        )
        return
    if state == "none":
        doctor.report(
            "WARN",
            "channel MCP connection: no configured MCP server resolves to the "
            "claude-channel consumer script, so there is no transport to "
            "check. Open a session through bin/oss-workspace, which registers "
            "or arms one at session-open.",
        )
        return
    if state == "failed":
        doctor.report(
            "WARN",
            "channel MCP connection: every MCP server resolving to the "
            "claude-channel consumer reports a failed transport ({}). The "
            "registration and the consumer file can both be fine and nothing "
            "still be delivered -- the usual cause is another claude-channel "
            "consumer already holding the socket this one would bind, which "
            "makes it exit without binding. Ask supertool which: `./supertool "
            "channel:health` names the holding pid in its `refused:` row, and "
            "`lsof /tmp/supertool-watch.sock` names the process. A consumer "
            "whose own session is gone is safe to kill; one belonging to "
            "another live tool is not this diagnostic's call to make.",
        )
        return
    doctor.report(
        "OK",
        "channel MCP connection: the channel consumer starts and speaks MCP "
        "when probed ({}). Read this narrowly, and narrower than the wording "
        "of a first draft of this check: `claude mcp list` FORKS ITS OWN "
        "consumer to produce that status and lets it exit, so this rules out a "
        "broken path, a missing interpreter and a consumer that cannot bind at "
        "all -- and says nothing about whether any consumer is live now, nor "
        "whether this session is subscribed to one. Both of those are "
        "per-session facts only `./supertool channel:health` answers, in its "
        "`consumer:` and `session:` rows, and `consumer: none` alongside this "
        "OK is a coherent pair rather than a contradiction.".format(detail),
    )


def check_channel_delivery(project_dir, resolve=None):
    """Is any consumer LIVE, and is anything subscribed to it (#1361)?

    The check above answers whether the consumer script can start. This
    answers the question every existing channel check skipped and the one that
    actually decides whether an event arrives: is a consumer running now, and
    does a session hear it. A registration is not a consumer, and a consumer is
    not a subscriber -- three separate facts that this repository's diagnostic
    reported as one `OK` for the whole life of the channel.

    Reuses the cached `channel:health` reading `check_channel_health_agreement`
    already resolves, at its own staleness bound and with no fresh probe, so
    this costs nothing: that reading was being taken and then used only to
    compare two instruments against each other, never reported on its own
    terms.

    `resolve` is injected for testing, and defaults to
    `doctor_check_channel_health_agreement.resolve_channel_health_reading`;
    imported inside the function rather than at module scope because both
    modules are imported by `doctor.py` and neither may depend on the other's
    import order.
    """
    if resolve is None:
        from doctor_check_channel_health_agreement import (
            resolve_channel_health_reading,
        )

        resolve = resolve_channel_health_reading
    raw_state, source, age = resolve(project_dir)
    aged = " ({:.0f}s old)".format(age) if isinstance(age, (int, float)) and age else ""
    if source in (None, "cached-stale"):
        # Neither arm establishes anything: `None` is no reading at all and
        # `cached-stale` is a reading too old to speak for the present. Both
        # are #764 NOTICEs, on the line this module draws throughout -- WARN
        # only where a fault is positively established. The remedy stays in the
        # text either way, so a reader who does want a reading knows how to
        # take one; what changes is that neither renders as work outstanding on
        # a machine that simply has no channel.
        doctor.report(
            "NOTICE",
            "channel delivery: no usable channel:health reading{} -- whether "
            "any consumer is live, and whether anything is subscribed to it, "
            "was not established. Not answered as delivering: this is the "
            "third state, not a pass. `./supertool channel:health` answers it "
            'directly, and `python3 "$CLAUDE_PROJECT_DIR"/scripts/statusline.py '
            '--refresh --root "$CLAUDE_PROJECT_DIR"` refreshes the cached '
            "reading this check prefers.".format(aged),
        )
        return
    if raw_state == "forwarding":
        doctor.report(
            "OK",
            "channel delivery: a consumer is live and forwarding{} -- the one "
            "state in which an emitted event actually reaches a "
            "session.".format(aged),
        )
        return
    if raw_state == "not_delivering":
        doctor.report(
            "WARN",
            "channel delivery: NOT DELIVERING{} -- no consumer is bound, so "
            "every event emitted right now is lost at the source. Every "
            "registration check can pass in this state and several do: a "
            "registration the harness never starts, or starts and lets exit, "
            "leaves nothing listening. A consumer is spawned at session-open "
            "and cannot be rebound from inside a running session -- reopen "
            "through bin/oss-workspace, which exports SUPERTOOL_WATCH_NAME so "
            "the consumer binds this project's own named socket.".format(aged),
        )
        return
    if raw_state == "not_subscribed":
        doctor.report(
            "WARN",
            "channel delivery: BOUND, NOT SUBSCRIBED{} -- a consumer is live, "
            "verified and counting, and no session is listening to it. Events "
            "are forwarded into nothing. Usually a consumer outliving the "
            "session that spawned it, or a session whose channel tag names a "
            "server the harness did not accept; `./supertool channel:health` "
            "names the pid in its `consumer:` row and the reason in its "
            "`session:` row.".format(aged),
        )
        return
    doctor.report(
        "WARN",
        "channel delivery: channel:health answered {}{}, which is neither a "
        "delivering nor a cleanly non-delivering state -- reported verbatim "
        "rather than folded into either, because a reading this check cannot "
        "speak for is not a reading that said things are fine.".format(
            raw_state if raw_state else "nothing recognisable", aged
        ),
    )


def arm_target_liveness(name, run=None, which=None, env=None):
    """``(state, detail)`` -- would arming the channel flag against `name`
    actually yield a consumer (#1361)?

    `plugin_channel_arm_decision` answers `single` when an installed plugin
    DECLARES a claude-channel consumer in its own `.mcp.json`, and
    `bin/oss-workspace` then declines to register `oss-channel` on top of it.
    That is correct whenever the declared server actually starts. When it does
    not -- disabled by the plugin, rejected by the harness, a cached connect
    failure never retried -- the two correct decisions compose to zero
    consumers, which is the state #1361 was filed from: nothing collided,
    nothing was misconfigured, and nothing was delivered.

    Four states, and the caller must treat only ``connected`` as a reason to
    decline registering its own server:

    * ``connected`` -- the harness reports a live transport for this name.
    * ``failed`` -- the harness reports this name with a FAILED transport.
      This is the only state a caller may act on, because it is the only one
      that positively establishes the declared consumer is not there.
    * ``not-listed`` -- `claude mcp get` did not answer for this name.
    * ``could-not-ask`` -- the call did not run, or its answer carried no
      readable status.

    The last two are deliberately NOT reasons to register a fallback server,
    and a first version of this gate that treated `not-listed` as one broke
    four existing #1307/#1343 launcher fixtures by falling back in exactly the
    environments where the declared consumer was fine and simply not visible to
    this ask. An answer that was not obtained is not evidence the declared
    consumer is dead, and acting on it recreates the collision #1307's decline
    exists to avoid -- so the conservative direction here is to decline as
    before and say why.

    `claude mcp get NAME` rather than `claude mcp list`: the launcher already
    asks `list` exactly once and relays that answer onward (#629/#810), and a
    second `list` here broke the test that guards that economy. `get` is a
    different, per-name ask that leaves the relay untouched, and it prints the
    same `Status:` line.
    """
    env = os.environ if env is None else env
    which = shutil.which if which is None else which
    run = subprocess.run if run is None else run

    claude_bin = which("claude")
    if claude_bin is None:
        return "could-not-ask", "claude is not on PATH"
    try:
        completed = run(
            [claude_bin, "mcp", "get", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "could-not-ask", "`claude mcp get {}` did not run ({})".format(name, exc)
    if completed.returncode != 0:
        return "not-listed", name
    stdout = completed.stdout
    text = (
        stdout.decode("utf-8", "replace")
        if isinstance(stdout, bytes)
        else str(stdout or "")
    )
    for raw in text.splitlines():
        line = raw.rstrip("\r").strip()
        if not line.startswith("Status:"):
            continue
        if any(marker in line for marker in _FAILED_MARKERS):
            issue = _MCP_ISSUE_RE.search(text)
            return "failed", doctor._one_line(
                issue.group(1) if issue else line, limit=200
            )
        if any(marker in line for marker in _CONNECTED_MARKERS):
            return "connected", name
        # A `Status:` line whose word this does not recognise. Not `connected`
        # and not `failed`: the third state, which the caller must not act on.
        return "could-not-ask", "status not readable: {}".format(
            doctor._one_line(line, limit=200)
        )
    return "could-not-ask", "no Status line in `claude mcp get {}`".format(name)
