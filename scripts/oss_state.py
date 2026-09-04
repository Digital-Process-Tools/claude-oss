"""The tick state file: what was decided, and the one reason for it.

Written every tick, read first every tick. Deliberately thin -- status only, never
diffs. Reasoning that only matters to a pull request belongs in that pull request.

Three decisions worth stating, because each of them is a refusal:

* **A corrupt file raises.** Starting fresh would destroy the history the file exists
  to keep, and the tick that did it would be indistinguishable from a first tick.
* **An over-long decision raises rather than truncating.** A truncation silently
  discards the half that mattered and leaves something that still reads as a record.
* **Nothing success-shaped is printed before the entry is on disk.** The intake sentence
  used to be computed and printed before the decision was validated, so a refused write
  reached the caller as a well-formed metric line with the ``FAIL`` underneath it -- and
  one tick filtered for the metric, saw it, and lost its entry (#222). The CLI's three
  labels keep the cases apart: ``RECORDED`` receipts an entry that landed, ``NOT
  RECORDED`` names a pair this run dropped and always follows the ``FAIL``, and ``TREND``
  marks the read-only sum that stores nothing. An exit code is the right mechanism and it
  is not sufficient when a human or an agent is reading the transcript.

Timestamps are arguments, never read from the clock in here. A function that reads the
clock cannot be tested for what it writes, and this file is evidence.

The same refusal is why ``intake`` takes its two counts as arguments rather than asking
the forge for them. Beside the decision, each entry can carry the tick's **intake**: how
many issues the loop filed per pull request it merged, as ``detail["intake"]``. The pair
is stored and the quotient derived, so a run of entries can be re-added -- 1/2 and 3/4 do
not average to the ratio over six pull requests. ``intake_trend`` does the re-adding and
``intake_line`` renders one, and both keep four states apart, of which the two that get
lost are ``could-not-count`` (never zero) and ``partial`` (a real sum that is not the
range's total).

Python 3.9 compatible.
"""

import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dispatch_rank as _dispatch_rank  # noqa: E402

MAX_DECISION = 200

# The intake metric: filings the loop made, per pull request it merged.
#
# Four states rather than two, and each one is a different sentence:
#
#   measured         both counts were taken and something was merged. A ratio of 0.0
#                    lives here -- "the loop filed nothing against three merged pull
#                    requests" is a finding, and a loud one.
#   no-denominator   both counts were taken and nothing was merged. 6/0 is not 6 and it
#                    is not 0. The numerator is still reported; the ratio is not.
#   could-not-count  a count was not taken -- the forge was unreachable, the state file
#                    was absent, a page cap was hit. This never renders as a ratio and
#                    never renders as zero, and it carries the reason.
#   partial          `intake_trend` only: some ticks in the range counted and some did
#                    not, so the sum is real but it is not the range's total. Its own
#                    state rather than a flag on `measured`, because anybody branching
#                    on `measured` would otherwise read a partial sum as a total -- the
#                    per-page aggregation trap, one indirection away.
INTAKE_MEASURED = "measured"
INTAKE_NO_DENOMINATOR = "no-denominator"
INTAKE_COULD_NOT_COUNT = "could-not-count"
INTAKE_PARTIAL = "partial"

# What `--filings unknown` parses to. A flag nobody passed is `None`; a count somebody
# tried to take and could not is this. Collapsing the two is the bug the metric exists
# to avoid, so they are not the same value even inside the parser.
UNKNOWN_COUNT = object()

# What a tick costs to *carry* (#694): a tick's own start context, the session's floor
# (its first tick's own start -- 45-125k rather than zero, per the spine/skill/system
# prompt every tick inherits), the inherited part between them, and the calls and
# context this one tick carried. Ranking ticks by dollar cost alone points at the wrong
# ones: ranking the same 48 ticks by context inherited at their start explained why
# twelve of them were expensive, and it was not that they did more work.
#
# Three states, same shape as `intake`'s -- a broken counter reporting zero must never
# render like a perfectly efficient tick, and a floor nobody could establish must never
# render like a tick that inherited nothing:
#
#   measured           start_ctx, calls and context_carried were all taken, AND the
#                      floor is known (either this is the session's own first tick, or
#                      an earlier tick in the same session already established one).
#                      `inherited` is derivable and a value of 0 lives here.
#   floor-unknown      start_ctx, calls and context_carried were all taken, but no
#                      floor could be established -- no earlier tick in this session
#                      recorded one, and this tick was not asserted as the session's
#                      first. `inherited` stays unknown rather than being guessed at
#                      from `start_ctx`, because a floor cannot be told from a genuine
#                      first tick and an earlier tick that ran before this metric
#                      existed. The raw reading is still kept, never discarded.
#   could-not-measure  one or more of start_ctx/calls/context_carried could not be
#                      read at all -- the harness gave no usage block, the transcript
#                      truncated. Never renders as zero, and it carries the reason.
#
# `cost` is a derived column only, never the primary key, and it never renders without
# saying it is a list-rate computation, not a billed amount (#694's own limit).
TICK_COST_MEASURED = "measured"
TICK_COST_FLOOR_UNKNOWN = "floor-unknown"
TICK_COST_COULD_NOT_MEASURE = "could-not-measure"

# The lane-model mix (#316): which model each dispatched developer lane ran on, and
# whether that was the shipped default or a per-lane override with a reason. Same three
# extra states as intake, for the same reason -- a tick that dispatched nothing and a
# tick that recorded nothing about its lanes must not render alike, and a mix somebody
# could not establish must never render as an empty one.
#
#   recorded            at least one lane was dispatched and every one of them carries
#                        a model, and an override carries its reason.
#   none-dispatched      the tick dispatched no developer lane. Not the same as the next
#                        state -- this is a fact somebody established, not a silence.
#   could-not-establish  nobody recorded what ran, or could not (a resumed session whose
#                        transcripts were reaped, for instance). Never zero lanes.
#   partial              `lane_model_trend` only: some ticks in the range recorded a mix
#                        and some did not, so the sum is real but not the range's total.
LANES_RECORDED = "recorded"
LANES_NONE_DISPATCHED = "none-dispatched"
LANES_COULD_NOT_ESTABLISH = "could-not-establish"
LANES_PARTIAL = "partial"

# A lane's own two-word vocabulary. Not checked against a list of model names -- which
# models exist is a fact about the harness, not about this repository, and an allow-list
# here would be a second copy of somebody else's roster (the class this repo is named
# after, pointed at its own config). What is checked is *why* a lane ran the model it
# ran: the shipped default needs no reason, and an override does, because an unexplained
# override is exactly the accretion #316 was filed about.
CHOICE_DEFAULT = "default"
CHOICE_OVERRIDE = "override"

# #862: the two agent definitions a dispatch is actually allowed to spawn as. This is
# not the model roster above -- there are only two of these in the whole plugin, they
# are named in this repository's own files, and a lane recorded outside the set is
# exactly the defect #862 was filed for (a lane dispatched as `general-purpose`, so the
# whole developer brief -- #765's rule included -- was simply absent for it). Recording
# `agent_type` is typed after the spawn, the same way the model choice above is: it
# makes a wrong dispatch observable, and does not, by itself, stop one from happening.
KNOWN_AGENT_TYPES = ("oss:developer", "oss:triager")

# #880: a tick performs exactly one dispatch. A lane's own agent is resumed via
# SendMessage on a red run or a moved base, never re-dispatched fresh at the same
# issue, unless that agent is genuinely gone -- context died, or resumed and silent
# twice, the same bar agents/developer.md sets its own review spawns. `dispatched` is
# the default (an ordinary fresh dispatch, and the value every entry recorded before
# this constant existed is read as); `resumed` records that this issue needed a
# mid-tick resume without representing a second dispatch event; `agent-unreachable` is
# the one state under which a second fresh spawn at the same issue is correct.
# `lane_models` refuses a `--decision` call in which the same issue is recorded
# `dispatched` more than once -- the receipt for the defect this issue was filed for --
# and requires `why` on `agent-unreachable`, because "the agent is gone" with no
# account of which of the two ways is indistinguishable from an excuse.
DISPATCH_STATE_DISPATCHED = "dispatched"
DISPATCH_STATE_RESUMED = "resumed"
DISPATCH_STATE_AGENT_UNREACHABLE = "agent-unreachable"
DISPATCH_STATES = (DISPATCH_STATE_DISPATCHED, DISPATCH_STATE_RESUMED, DISPATCH_STATE_AGENT_UNREACHABLE)

# A dispatched lane's own fill (#852): how many issues it carried, and -- when that is
# fewer than dispatch_rank.MAX_LANE -- why, from the same closed vocabulary
# dispatch_rank.SHORT_REASONS declares and dispatch_rank.check_lane already enforces
# for the dispatch decision itself. Recorded here so the rule commands/tick.md step 5
# states in prose -- "a lane dispatched with fewer says why" -- has something that can
# actually detect its own violation, rather than surviving only in free `--decision`
# prose (#337's own failure, one field over). Same four states as `lanes` above, for
# the same reason: a tick that dispatched nothing and a tick that recorded nothing
# about its lanes' fill must not render alike, and a fill nobody could establish must
# never render as an empty one.
LANE_FILL_RECORDED = "recorded"
LANE_FILL_NONE_DISPATCHED = "none-dispatched"
LANE_FILL_COULD_NOT_ESTABLISH = "could-not-establish"
LANE_FILL_PARTIAL = "partial"

# A cohort freeze count (#407): a frozen label re-counted right after the writes that
# made it. GitHub's label filter is an index and it lags the writes that feed it, so a
# single route -- the filtered query the manager skill's own rule re-counts with -- can
# read low at the exact instant nothing has actually gone missing. A freeze is the one
# measurement where that matters permanently: a cohort only ever shrinks, so a low
# count recorded as the baseline is never corrected by any later measurement.
#
# Three states, not two, for the same reason `intake`'s and `lane_models`'s are -- a
# low count and a correct count must never render alike:
#
#   measured          two or more routes were counted and they agree. That number is
#                      the freeze.
#   unknown            two or more routes were counted and they disagree. Neither
#                       number is kept over the other -- a lower count is not evidence
#                       of a smaller cohort, it is evidence of a stale index, and
#                       guessing which route to trust is exactly the bug #407 reports.
#   could-not-count    fewer than two routes were counted. A single route is exactly
#                       the situation #407 was filed about, so it is never enough by
#                       itself to freeze on. Not the same state as `unknown`, which
#                       means two routes disagreed rather than one route answering
#                       alone.
COHORT_MEASURED = "measured"
COHORT_UNKNOWN = "unknown"
COHORT_COULD_NOT_COUNT = "could-not-count"

# A recorded wait (#337): what a tick is blocked on, in a form a later tick can test
# rather than believe. "Blocked on audit completion" names no dispatch, no observable
# and no time, so no later turn can fail it -- and a wait that cannot fail is
# indistinguishable from one that is still true. `wait` records the claim; `check_wait`
# re-derives it, and the check itself must have a third state, same shape as `intake`'s
# and `cohort_freeze`'s: a wait that still holds and a wait nobody could test must not
# render alike, or the second reads as the first forever.
#
#   holds                the wait was recorded, or re-checked, and the condition it
#                        names has not been observed to clear.
#   cleared              re-checked, and the observable was seen -- `cleared_by` says
#                        what was seen, so a later reader can tell this from a guess.
#   could-not-evaluate   re-checked, but the observable could not be tested at all
#                        (the tracker was unreachable, the dispatch could not be
#                        found). Never the same rendering as `holds`: `holds` is a
#                        measurement that came back negative, this is no measurement.
WAIT_HOLDS = "holds"
WAIT_CLEARED = "cleared"
WAIT_COULD_NOT_EVALUATE = "could-not-evaluate"

# #855: when a triage sweep last completed, read back from history the same way
# `_last_wait` re-derives a wait -- scanning backward past any entry that recorded
# something else, never just the last entry in the file. Three states, the same
# shape every other reader in this file uses: `recorded` (an ISO timestamp really is
# on record), `never` (a real, established absence -- this history has never once
# recorded a sweep), and `could-not-read` (the state file itself could not be read,
# which must never render the same as `never`: one is a measurement, the other is no
# measurement at all).
TRIAGE_RECORDED = "recorded"
TRIAGE_NEVER = "never"
TRIAGE_COULD_NOT_READ = "could-not-read"

# A plugin identity comparison (#477): what a tick recorded about the install
# it ran under, read back against what THIS tick reads, so "has the version
# changed since last tick" is a question this system can answer at all --
# before this, one of its two operands was never written down.
#
# The compared value is the WHOLE string `doctor.plugin_identity()` returns --
# a manifest version folded with a content digest over the tracked files --
# never the version alone. #418 measured two installs that both read "0.9.0"
# sixteen commits apart: a manifest version is stable across exactly the
# window this check exists to catch, so a version-only comparison would ship
# a check that cannot fire for the most common real skew.
#
# Four states now, not three (#677). The original three assumed both readings
# came from the same route -- in practice, the same command run against the
# same path every time. That assumption broke twice within an hour on the
# machine that filed #677: a version-pinned `${CLAUDE_PLUGIN_ROOT}` reported
# `unchanged` straight through a real update (the path names a version, so it
# can never see that version move), and the very next comparison mixed a
# hand-recorded prior taken from the copy that actually answers with a current
# reading taken the old, pinned way -- producing `changed`, backwards, with
# nothing having happened. Both operands must come from the same route for
# `changed`/`unchanged` to mean anything at all.
#
#   changed          this tick's identity string differs from the prior
#                     tick's, AND the two were read by the same route. Could
#                     be the version, the content digest, or both -- the
#                     whole string is the operand, so this does not say which
#                     half moved.
#   unchanged         the two strings are identical, and the two were read by
#                     the same route.
#   could-not-tell    no prior tick ever recorded an identity (a first tick
#                      after this ships, or every earlier entry predates it),
#                      or the prior recorded was blank. This must never
#                      render as `unchanged` -- a loop that has never
#                      recorded a version would otherwise look exactly like
#                      one whose version has not moved, which is the absence
#                      this issue is named after.
#   route-mismatch   a prior WAS recorded, but it was read by a different
#                     route than this tick's own reading -- e.g. one came from
#                     a version-pinned path and the other from the copy that
#                     actually answers, or the route changed when this fix
#                     shipped. `changed`/`unchanged` between two different
#                     measurements describes nothing that occurred, so this is
#                     its own state rather than being decided either way.
#                     Recording no route at all (the pre-#677 shape) is treated
#                     as its own route rather than a wildcard, so a caller that
#                     never opts into route tracking keeps comparing exactly as
#                     it always did -- and a caller that starts routing for the
#                     first time gets `route-mismatch`, not a false `changed`,
#                     on the tick the mechanism changes.
PLUGIN_UNCHANGED = "unchanged"
PLUGIN_CHANGED = "changed"
PLUGIN_COULD_NOT_TELL = "could-not-tell"
PLUGIN_ROUTE_MISMATCH = "route-mismatch"

#: Sentinel used in place of an absent route, so "no route recorded" compares
#: as its own value rather than matching every real route by construction.
_PLUGIN_IDENTITY_ROUTE_UNRECORDED = "unrecorded"

# A within-tick plugin ROOT stability check (#565): does `${CLAUDE_PLUGIN_ROOT}`
# itself move between two points inside the SAME tick? This is a different
# question from the plugin identity comparison above, which is cross-tick and
# persists in the state file's own entry list. #565 asks about a single
# session's environment variable, not about a version recorded days apart --
# so this is deliberately a second, narrower mechanism: an ephemeral sidecar
# file beside the state file, written once at the top of a tick and consumed
# (read, then deleted) the first time it is checked, rather than a durable
# entry. A snapshot that outlived its own tick would answer a question about
# some earlier, unrelated tick, which is worse than answering nothing.
#
#   changed           the root read back differs from the one recorded
#                      earlier in this tick.
#   unchanged         the two are identical.
#   could-not-read    no snapshot was found (nothing was recorded earlier in
#                      this tick, or a prior check already consumed it), or
#                      the snapshot could not be parsed. Never rendered as
#                      `unchanged` -- see the module comment above for why
#                      that collapse is this repository's own defect class.
PLUGIN_ROOT_CHANGED = "changed"
PLUGIN_ROOT_UNCHANGED = "unchanged"
PLUGIN_ROOT_COULD_NOT_READ = "could-not-read"


class StateError(Exception):
    """The state file could not be read, or an entry was refused."""


# What `describe` answers, and the reason there are three of them rather than two.
#
#   ok           the file was read and holds a list of entries. `entries` is that list.
#   absent       there is no file. A first tick, and not an error.
#   unreadable   the file is there and the writer cannot use it -- unreadable bytes,
#                unparseable JSON, or a shape that is not a list of entries. This is
#                the state #149 was filed about: a pre-plugin state file is a dict
#                keyed `tick_<ISO>`, and reporting it as "no entries yet" invites a
#                maintainer to start fresh over a history they still have.
STATE_OK = "ok"
STATE_ABSENT = "absent"
STATE_UNREADABLE = "unreadable"

# Appended to the state file's own name for the copy `migrate` keeps.
BACKUP_SUFFIX = ".pre-migration"

MIGRATE_HINT = (
    "convert it with: python3 <plugin>/scripts/oss_state.py <state_file> --migrate"
)

# One receipt line, and the mark a cut one carries. Same figures as
# `lane_setup.py`'s, deliberately not imported: that module is a setup read and this
# is the state file, and neither should have to change because the other's did.
_RECEIPT_LINE_LIMIT = 2000
_TRUNCATION_MARK = " ... [truncated]"


def _receipt_line(text):
    """One assembled receipt line, folded so nothing in it can forge another (#382).

    Applied at the single point where each renderer joins its line, rather than to a
    list of fields. `window`, a `why` and a model name were measured forging lines
    here; the shape of the guard is the argument #372 already settled for
    `lane_setup.receipt()` -- a per-field guard closes the fields somebody enumerated
    and leaves the next field added to the renderer unguarded.

    The receipts this module prints are read by a maintainer and pasted into briefs,
    and `lane_models_line`'s own output goes back through `--model-trend` from a state
    file, so a forged line survives a round trip.

    Not `_one_line` -- there is none in this module to reuse, and importing another
    script's would couple a state file to a setup read. Its silent truncation would
    also be wrong here: a cut line rendering as a complete one is this repository's own
    defect class pointed at its own receipt, so truncation is **marked**. Its
    `" ".join(text.split())` is the half `lane_setup` refused because every row there is
    column-aligned; nothing in this module is aligned, so collapsing runs of spaces
    would have destroyed nothing -- it is simply not what a forging guard needs to do,
    and leaving spaces alone keeps a clean receipt byte-for-byte what it was.

    Every character outside printable ASCII becomes `?`, which covers newline, carriage
    return and the control sequences that repaint a line a terminal already printed.
    """
    safe = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in str(text))
    if len(safe) > _RECEIPT_LINE_LIMIT:
        keep = max(0, _RECEIPT_LINE_LIMIT - len(_TRUNCATION_MARK))
        safe = safe[:keep] + _TRUNCATION_MARK
    return safe


def describe(path):
    """Which of the three states this path is in. Never raises.

    Every caller that must not die on a bad file goes through here -- `read` for the
    message, `/oss:doctor` for the finding -- so the classification cannot drift into
    two versions that disagree about the same file.

    The exception in hand answers absence: `FileNotFoundError` is "not there" and every
    other `OSError` is "there and unusable". Asking the filesystem a second question to
    tell them apart is the bug that killed the release gate in #76 -- `Path.exists()`
    swallows some errnos and raises the rest, so the line added to explain a failed read
    becomes a second way to fail.
    """
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"state": STATE_ABSENT, "entries": None, "reason": None}
    except UnicodeDecodeError as exc:
        # Caught by name and before OSError, because it is neither: it is a ValueError,
        # so an `except OSError` around the read -- which is what this was -- lets it
        # through, and one stray byte reaches /oss:doctor as a traceback through a
        # contract that is exit 0 always. A pre-plugin loop writing with the console's
        # codepage rather than UTF-8 is the realistic way a state file gets one.
        return {
            "state": STATE_UNREADABLE,
            "entries": None,
            "reason": "could not decode it as UTF-8 ({})".format(exc),
        }
    except OSError as exc:
        return {
            "state": STATE_UNREADABLE,
            "entries": None,
            "reason": "could not read it ({})".format(exc),
        }
    try:
        entries = json.loads(raw)
    except ValueError as exc:
        return {
            "state": STATE_UNREADABLE,
            "entries": None,
            "reason": (
                "could not parse it ({}). Not resetting it -- the history is the "
                "point, and a silent reset looks exactly like a first tick.".format(exc)
            ),
        }
    if isinstance(entries, dict):
        return {
            "state": STATE_UNREADABLE,
            "entries": None,
            "reason": (
                "holds a JSON object, not a list of entries -- the shape a pre-plugin "
                "maintainer skill wrote, keyed by timestamp. The history is intact and "
                "nothing here will touch it: {}".format(MIGRATE_HINT)
            ),
        }
    if not isinstance(entries, list):
        return {
            "state": STATE_UNREADABLE,
            "entries": None,
            "reason": "holds a JSON {}, not a list of entries".format(
                type(entries).__name__
            ),
        }
    return {"state": STATE_OK, "entries": entries, "reason": None}


def read(path):
    """Return the entries, oldest first. A missing file is an empty history."""
    found = describe(path)
    if found["state"] == STATE_ABSENT:
        return []
    if found["state"] == STATE_UNREADABLE:
        raise StateError("{}: {}".format(Path(path), found["reason"]))
    return found["entries"]


# What `migrate` answers. `already-a-list` is not `migrated`: a caller that renders
# both as success cannot tell a converted file from one that never needed converting,
# and a caller that renders both as failure re-runs a conversion that already happened.
MIGRATED = "migrated"
ALREADY_A_LIST = "already-a-list"
CANNOT_MIGRATE = "cannot-migrate"

# The decision an entry gets when the shape it came from carried none. Stated rather
# than guessed: this file is evidence, and a plausible-looking decision nobody wrote is
# worse than an honest gap. The MAX_DECISION cap is deliberately not applied to a
# decision being carried over -- truncating somebody's record to satisfy a rule written
# after they wrote it discards the half that mattered.
NO_DECISION = "migrated from a pre-plugin entry that carried no decision field"


def _entry_from(key, value):
    """One pre-plugin `tick_<ISO>: {...}` pair as an entry.

    Lossless on purpose: the original object is kept whole under `detail`, so a fact
    this code does not understand survives the conversion. Only `at` and `decision` are
    derived, and `decision` is derived only when the source plainly carried one.
    """
    at = key[len("tick_"):] if key.startswith("tick_") else key
    decision = value.get("decision")
    if not isinstance(decision, str) or not decision.strip():
        decision = NO_DECISION
    return {"at": at, "decision": decision, "detail": value}


def _carry_mode(source, target):
    """Give ``target`` ``source``'s permission bits, best effort.

    A silence that is argued rather than shrugged at: `mkstemp` creates at 0600, which
    is stricter than any state file's mode, never looser. So a mode that cannot be
    carried leaves a file the owner can still read and nobody else gained access to --
    not worth refusing a conversion over, and not worth a receipt of its own. On
    Windows the bits are close to meaningless and this is close to a no-op.
    """
    try:
        os.chmod(str(target), stat.S_IMODE(os.stat(str(source)).st_mode))
    except OSError:
        return


def _discard(tmp):
    """Remove a temp file a failed write left behind. Returns what to say about it.

    An empty string when there is nothing to say, and a sentence naming the leftover
    when it could not be removed -- a stray file in the maintainer's state directory
    that nothing else will ever mention is a small mess with no receipt.
    """
    if tmp is None:
        return ""
    try:
        os.unlink(str(tmp))
    except FileNotFoundError:
        return ""
    except OSError as exc:
        return "; a partial copy was left at {} and can be deleted ({})".format(tmp, exc)
    return ""


def migrate(path):
    """Convert a timestamp-keyed object of entries into the list shape, in place.

    Three outcomes and each is a different sentence -- see `MIGRATED`. Nothing is
    written unless the whole document converts, and the original is kept beside it at
    ``<path>.pre-migration`` first, because the failure this guards against destroys a
    history that exists precisely because it cannot be recomputed.

    That copy is **read back and compared** before the original is touched, and the
    original is replaced by writing a sibling temp file and renaming it over the top.
    Both exist because the receipt on a failed write claims the original is unchanged:
    `write_text` truncates at open, so the claim was false on every path where the
    write failed after that point (#174), and a copy nobody read back is the same
    claim one level down.
    """
    path = Path(path)
    found = describe(path)
    if found["state"] == STATE_OK:
        return {
            "state": ALREADY_A_LIST,
            "entries": len(found["entries"]),
            "reason": None,
            "backup": None,
        }
    if found["state"] == STATE_ABSENT:
        return {
            "state": CANNOT_MIGRATE,
            "entries": None,
            "reason": "it is not there; the first tick will create it in the list shape",
            "backup": None,
        }

    try:
        # Bytes, not text: the backup below has to be the file as it stands, and
        # `read_text` translates newlines -- a CRLF original would be copied back with
        # its line endings rewritten, which is not the thing it is a copy of.
        original = path.read_bytes()
        document = json.loads(original.decode("utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "state": CANNOT_MIGRATE,
            "entries": None,
            "reason": "could not read it ({})".format(exc),
            "backup": None,
        }
    if not isinstance(document, dict):
        return {
            "state": CANNOT_MIGRATE,
            "entries": None,
            "reason": (
                "it is a JSON {}, and only an object keyed by timestamp "
                "converts".format(type(document).__name__)
            ),
            "backup": None,
        }

    bad = [key for key, value in document.items() if not isinstance(value, dict)]
    if bad:
        return {
            "state": CANNOT_MIGRATE,
            "entries": None,
            "reason": (
                "{} of {} values are not objects of facts ({!r} first), so an entry "
                "for them would have to be invented -- refusing rather than writing a "
                "record nobody wrote".format(len(bad), len(document), sorted(bad)[0])
            ),
            "backup": None,
        }

    # A dict carries no order, so one is imposed rather than inherited. Sorting by key
    # is chronological for the `tick_<ISO>` shape and deterministic for anything else,
    # which is the most that can be claimed without inventing a clock.
    entries = [_entry_from(key, document[key]) for key in sorted(document)]

    try:
        body = json.dumps(entries, indent=2) + "\n"
    except (TypeError, ValueError) as exc:
        return {
            "state": CANNOT_MIGRATE,
            "entries": None,
            "reason": "the converted history is not serialisable ({})".format(exc),
            "backup": None,
        }

    backup = Path(str(path) + BACKUP_SUFFIX)
    try:
        # Exclusive create: an existing backup is an earlier attempt's original, and
        # overwriting it is how a second run destroys the history the first one saved.
        with open(str(backup), "xb") as handle:
            handle.write(original)
    except FileExistsError:
        return {
            "state": CANNOT_MIGRATE,
            "entries": None,
            "reason": (
                "{} already exists -- an earlier attempt's original. Move it aside "
                "yourself; overwriting it is the one thing this must never do.".format(
                    backup
                )
            ),
            "backup": str(backup),
        }
    except OSError as exc:
        return {
            "state": CANNOT_MIGRATE,
            "entries": None,
            "reason": "could not write the backup {} ({})".format(backup, exc),
            "backup": None,
        }

    # Read the copy back before anything touches the original. A receipt naming a
    # backup nobody read is the same defect one layer out: `handle.write` returning
    # without raising is not evidence the bytes landed, and the history this is a copy
    # of cannot be recomputed. Neither branch below deletes the copy it distrusts --
    # a failed read-back is not proof the file is wrong, and removing the only other
    # copy of an unrecomputable history is the one thing this must never do. Neither
    # returns it as `backup` either: that field is what a caller offers as the copy to
    # fall back on, and a copy that did not verify is not one. The reason names the
    # path, as something to move aside.
    try:
        kept = backup.read_bytes()
    except OSError as exc:
        return {
            "state": CANNOT_MIGRATE,
            "entries": None,
            "reason": (
                "wrote the backup {} and could not read it back ({}), so nothing was "
                "written to the original -- it is untouched. Move that copy aside and "
                "run this again.".format(backup, exc)
            ),
            "backup": None,
        }
    if kept != original:
        return {
            "state": CANNOT_MIGRATE,
            "entries": None,
            "reason": (
                "the backup {} does not match the original ({} bytes written, {} read "
                "back), so nothing was written to the original -- it is untouched. "
                "Move that copy aside and run this again.".format(
                    backup, len(original), len(kept)
                )
            ),
            "backup": None,
        }

    # Written beside the original and moved onto it, rather than into it. `write_text`
    # truncates at open, so a failure part-way through left the original destroyed
    # while this receipt said it was unchanged (#174). `os.replace` either happens or
    # does not: POSIX `rename` is atomic, and on Windows a same-directory replace goes
    # through `MoveFileEx` with `MOVEFILE_REPLACE_EXISTING`, which fails outright --
    # typically `PermissionError`, when another process holds the destination open --
    # rather than half-writing. The temp file is a sibling on purpose: `os.replace`
    # across filesystems raises, and it is the same directory the backup was just
    # created in, so it introduces no permission the step above did not already need.
    tmp = None
    try:
        handle, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
        )
        os.close(handle)
        tmp = Path(tmp_name)
        tmp.write_text(body, encoding="utf-8")
        _carry_mode(path, tmp)
        os.replace(str(tmp), str(path))
    except OSError as exc:
        leftover = _discard(tmp)
        return {
            "state": CANNOT_MIGRATE,
            "entries": None,
            "reason": (
                "could not write the converted history ({}); the original is unchanged "
                "-- it is only ever replaced by an atomic rename -- and a copy of it is "
                "at {}{}".format(exc, backup, leftover)
            ),
            "backup": str(backup),
        }
    return {
        "state": MIGRATED,
        "entries": len(entries),
        "reason": None,
        "backup": str(backup),
    }


def append(path, at, decision, detail=None):
    """Add one entry. Returns the entry as written.

    The write is atomic -- a sibling temp file renamed over the history -- for the same
    reason ``migrate``'s is: a plain rewrite truncates at ``open`` and a failure after
    that point leaves a half-file where a history was. That matters more than it looks,
    because the failure arm below tells the caller the history is unchanged, and an
    atomic rename is what makes that sentence true rather than hopeful.

    The cost is stated rather than hidden: the rename needs the *directory* to be
    writable, where the old in-place rewrite needed only the file. A state file somebody
    can write inside a directory they cannot is now a refusal, and a loud one, rather
    than a write that risks the history.
    """
    if not decision or not decision.strip():
        raise StateError(
            "an entry needs a decision. A tick that records only that it happened "
            "reads as history while carrying none."
        )
    if len(decision) > MAX_DECISION:
        raise StateError(
            "decision is {} characters, over the {} cap. Keep the decision and the one "
            "reason for it; the rest belongs in the pull request.".format(
                len(decision), MAX_DECISION
            )
        )

    entry = {"at": at, "decision": decision}
    if detail is not None:
        entry["detail"] = detail

    entries = read(path)
    entries.append(entry)

    try:
        body = json.dumps(entries, indent=2) + "\n"
    except (TypeError, ValueError) as exc:
        # Serialise before touching the file, so a bad detail cannot leave a
        # half-written history behind.
        raise StateError("entry is not serialisable ({})".format(exc))

    path = Path(path)
    tmp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
        )
        os.close(handle)
        tmp = Path(tmp_name)
        tmp.write_text(body, encoding="utf-8")
        _carry_mode(path, tmp)
        os.replace(str(tmp), str(path))
    except OSError as exc:
        # A raise rather than a return, and a StateError rather than the OSError: every
        # other refusal in here is a StateError, and the CLI's one handler turns those
        # into a FAIL line. An OSError went straight through it as a traceback -- exit
        # non-zero, but no FAIL for a caller to watch for.
        leftover = _discard(tmp)
        raise StateError(
            "could not write the entry ({}); the history is unchanged -- it is only "
            "ever replaced by an atomic rename{}".format(exc, leftover)
        )
    return entry


def last(path):
    """The most recent entry, or None. An empty history is not an error."""
    entries = read(path)
    return entries[-1] if entries else None


def _count(value, label):
    """``value`` as a count, or ``None`` for a count nobody took."""
    if value is None:
        return None
    # `True` is an `int`, and would land in the history as one filing.
    if isinstance(value, bool) or not isinstance(value, int):
        raise StateError(
            "{} must be a whole number or None, not {!r}".format(label, value)
        )
    if value < 0:
        raise StateError("{} cannot be negative ({})".format(label, value))
    return value


def tick_cost(session, window, start_ctx, calls, context_carried, is_first=False,
              prior_floor=None, session_has_prior=False, why=None, rate=None):
    """What one tick cost to *carry* (#694): its own start context, calls, context
    carried, and -- when it can be told -- the session floor and what was inherited.

    ``session`` is an opaque identifier a later tick's floor lookup matches on. Without
    one, nothing could ever tell this tick's floor apart from a different session's.
    ``is_first`` is the caller's own assertion that this is the session's first tick --
    the same kind of self-report `intake`'s counts already are, and it is what lets the
    first tick's own start_ctx become the floor rather than staying unknown forever.
    ``prior_floor`` is a floor an earlier tick in the same session already established,
    read back by the CLI before this is called -- never read from the forge in here,
    for the same reason `intake` takes its counts as arguments. ``session_has_prior`` is
    a SEPARATE fact from ``prior_floor``: whether this session has ANY earlier tick-cost
    entry at all, resolved floor or not. A session whose earlier ticks all recorded
    floor-unknown has no ``prior_floor`` to conflict against, but it unambiguously
    already has history -- found by audit: without this flag, a resumed session (or a
    copy-pasted `--tick-cost-first`) could claim to be the session's first tick a second
    time and be accepted silently, manufacturing a false floor nothing later corrects.

    Any of ``start_ctx``/``calls``/``context_carried`` may be ``None`` for a reading
    that could not be taken, in which case ``why`` is required: an unexplained absence
    is indistinguishable from a measurement of nothing, which is this repository's
    founding defect class landing inside the instrument built to measure it. The
    ``is_first``/history conflict is checked BEFORE that could-not-measure branch and
    unconditionally on it -- found by review: the claim "this is the session's first
    tick" is about which tick this is, not about whether this tick's own counts could
    be read, so an unknown reading must not let a false claim slip through unchecked.

    ``rate`` is an optional list-rate, USD per million tokens. When given, the derived
    ``cost`` always carries a note that it is a list-rate computation and not a billed
    amount -- #694's own limit, stated once here so a renderer cannot drop it.
    """
    if not session or not str(session).strip():
        raise StateError(
            "a tick-cost record needs a session -- an opaque id so a later tick in the "
            "same run can find this one's floor. Without it, 'inherited' can never be "
            "told from a first tick's own zero."
        )
    if not window or not str(window).strip():
        raise StateError(
            "a tick-cost record needs a window -- what this reading covers, in words."
        )
    session = str(session).strip()
    window = str(window).strip()

    if prior_floor is not None:
        prior_floor = _count(prior_floor, "prior_floor")
    if is_first and (prior_floor is not None or session_has_prior):
        raise StateError(
            "this was asserted as session {!r}'s first tick, but this session already "
            "has an earlier tick-cost entry recorded -- either the session id was "
            "reused, or this is not really the first tick".format(session)
        )

    start_ctx = _count(start_ctx, "start_ctx")
    calls = _count(calls, "calls")
    context_carried = _count(context_carried, "context_carried")

    record = {
        "window": window,
        "session": session,
        "start_ctx": start_ctx,
        "calls": calls,
        "context_carried": context_carried,
        "floor": None,
        "inherited": None,
        "cost": None,
        "why": None,
    }

    if start_ctx is None or calls is None or context_carried is None:
        if not why or not str(why).strip():
            raise StateError(
                "a tick-cost reading that could not be taken needs a why. Without it, "
                "could-not-measure is an absence with no cause, which reads as a "
                "measurement of nothing."
            )
        record["state"] = TICK_COST_COULD_NOT_MEASURE
        record["why"] = str(why).strip()
        return record

    if rate is not None:
        if rate < 0:
            raise StateError("a list rate cannot be negative ({})".format(rate))
        record["cost"] = {
            "list_rate_usd": round(context_carried / 1000000.0 * float(rate), 4),
            "note": "list-rate at the given rate, not a billed amount",
        }

    if is_first:
        floor = start_ctx
    elif prior_floor is not None:
        floor = prior_floor
    else:
        floor = None

    if floor is None:
        record["state"] = TICK_COST_FLOOR_UNKNOWN
        record["why"] = (
            "no earlier tick in session {!r} recorded a floor, and this tick was not "
            "asserted as the session's first -- the floor cannot be told from a "
            "genuine first tick and an earlier tick that ran before this metric "
            "existed".format(session)
        )
        return record

    record["floor"] = floor
    record["inherited"] = start_ctx - floor
    record["state"] = TICK_COST_MEASURED
    return record


def _cost_suffix(record):
    """The list-rate disclaimer, appended wherever a cost is rendered -- #694's own
    limit is that a cost column read without it is quoted as a bill."""
    cost = record.get("cost")
    if not isinstance(cost, dict):
        return ""
    return ", ${:.4f} at list rate ({})".format(
        cost.get("list_rate_usd"), cost.get("note") or "list-rate, not a bill"
    )


def tick_cost_line(record):
    """One line a tick report can print. The state decides the sentence, not the
    caller -- same join as `intake_line`, so a caller cannot skip it by branching."""
    return _receipt_line(_tick_cost_sentence(record))


def _tick_cost_sentence(record):
    """`tick_cost_line`'s branches. Unfolded on purpose -- it has one caller."""
    if not isinstance(record, dict):
        raise StateError("tick_cost_line takes a tick_cost record, not {!r}".format(record))
    state = record.get("state")
    window = record.get("window") or "an unstated window"
    session = record.get("session") or "an unstated session"
    head = "tick cost {} ({}): ".format(window, session)

    if state == TICK_COST_COULD_NOT_MEASURE:
        return head + (
            "could not measure ({}) -- no start context, no calls, no context "
            "carried, and this is not zero".format(record.get("why") or "no reason recorded")
        )
    if state == TICK_COST_FLOOR_UNKNOWN:
        return head + (
            "start {} / {} calls / {} carried, floor unknown so inherited is not "
            "claimed -- {}{}".format(
                record.get("start_ctx"),
                record.get("calls"),
                record.get("context_carried"),
                record.get("why") or "no reason recorded",
                _cost_suffix(record),
            )
        )
    if state == TICK_COST_MEASURED:
        return head + (
            "start {} = floor {} + inherited {}, {} calls, {} carried{}".format(
                record.get("start_ctx"),
                record.get("floor"),
                record.get("inherited"),
                record.get("calls"),
                record.get("context_carried"),
                _cost_suffix(record),
            )
        )
    return head + "unrecognised tick-cost state {!r}, so nothing is claimed".format(state)


def _session_tick_cost_floor(path, session):
    """``(floor, has_prior)`` for ``session`` in the history at ``path``: the earliest
    recorded floor, or ``None`` if this session has never established one; and whether
    this session has ANY earlier tick-cost entry at all, resolved floor or not.

    Reads the file -- this is the CLI-support half, kept apart from `tick_cost` itself
    for the same reason `_last_wait`/`_last_plugin_identity` are: a function that reads
    the state file cannot be unit-tested for what it writes without also faking a disk.

    Once a floor is established for a session it does not move -- `start_ctx` keeps
    growing every later tick, so scanning for the first entry that already carries one
    is enough; a later entry's floor, if the session ever gets one, is the same value.

    ``has_prior`` is a separate return, not folded into ``floor is not None`` -- found
    by audit: a session whose earlier ticks all recorded floor-unknown has no floor to
    return, but scanning only for a floor let a later, falsely-first-claiming tick in
    that SAME session go unrefused, because nothing told `tick_cost` this session
    already had history at all.

    ``session`` is stripped here, the same way `tick_cost` strips it before writing --
    found by audit (#805): the write side already normalises whitespace, but this
    lookup used to compare against the caller's raw, unstripped id, so a session id
    differing only in surrounding whitespace found no matching history and
    `has_prior` read `False` even though a record for the "same" session already
    existed. That silently defeated the very refusal `has_prior` exists to drive.
    """
    session = str(session).strip()
    floor = None
    has_prior = False
    for entry in read(path):
        detail = entry.get("detail") if isinstance(entry, dict) else None
        record = detail.get("tick_cost") if isinstance(detail, dict) else None
        if not isinstance(record, dict):
            continue
        if record.get("session") != session:
            continue
        has_prior = True
        if floor is None and record.get("floor") is not None:
            floor = record.get("floor")
    return floor, has_prior


def intake(filings, merged_prs, window, why=None):
    """One tick's intake: filings made per pull request merged, over ``window``.

    Both counts are arguments, never read from the forge in here -- the same refusal
    that keeps the clock out of ``append``. A function that calls out cannot be tested
    for what it writes, and this file is evidence.

    ``window`` is required rather than defaulted. A ratio whose denominator nobody
    wrote down means nothing, and a default here would be one repository's counting
    rule living in shared code.

    Either count may be ``None`` for a count that could not be taken, in which case
    ``why`` says which and is required: an unexplained absence is indistinguishable
    from a measurement of nothing.

    The pair is what is stored. The quotient is derived and can be re-derived, which is
    what makes a run of these entries add up -- 1/2 and 3/4 do not average to the ratio
    over six pull requests.
    """
    if not window or not str(window).strip():
        raise StateError(
            "an intake record needs a window -- what the counts were taken over, in "
            "words. A ratio whose denominator nobody stated means nothing."
        )
    filings = _count(filings, "filings")
    merged_prs = _count(merged_prs, "merged_prs")

    record = {
        "window": str(window).strip(),
        "filings": filings,
        "merged_prs": merged_prs,
        "ratio": None,
        "why": None,
    }

    if filings is None or merged_prs is None:
        if not why or not str(why).strip():
            raise StateError(
                "a count that could not be taken needs a why. Without it, could-not-"
                "count is an absence with no cause, which reads as a measurement of "
                "nothing."
            )
        record["state"] = INTAKE_COULD_NOT_COUNT
        record["why"] = str(why).strip()
        return record

    if merged_prs == 0:
        record["state"] = INTAKE_NO_DENOMINATOR
        return record

    record["state"] = INTAKE_MEASURED
    record["ratio"] = filings / merged_prs
    return record


def intake_line(record):
    """One line a tick report can print. The state decides the sentence, not the caller.

    Rendering is where a third state gets lost: a caller formatting ``ratio or 0`` turns
    "could not count" into "zero", which is the finding it is not.

    The single join, so `_receipt_line` cannot be skipped by adding a branch below.
    """
    return _receipt_line(_intake_sentence(record))


def _intake_sentence(record):
    """`intake_line`'s branches. Unfolded on purpose -- it has one caller."""
    if not isinstance(record, dict):
        raise StateError("intake_line takes an intake record, not {!r}".format(record))
    state = record.get("state")
    window = record.get("window") or "an unstated window"
    head = "intake {}: ".format(window)

    if state == INTAKE_COULD_NOT_COUNT:
        return head + "could not count ({}) -- no ratio, and this is not zero".format(
            record.get("why") or "no reason recorded"
        )
    if state == INTAKE_NO_DENOMINATOR:
        return head + (
            "{} filings / 0 merged pull requests = no ratio; nothing merged in this "
            "window, which is not a ratio of zero".format(record.get("filings"))
        )
    if state == INTAKE_MEASURED:
        return head + (
            "{} filings / {} merged pull requests = {:.2f} filings per merged "
            "pull request".format(
                record["filings"], record["merged_prs"], record["ratio"]
            )
        )
    if state == INTAKE_PARTIAL:
        # Deliberately not the `measured` sentence with a caveat appended. A reader
        # skimming for the number would take the number and leave the caveat, which is
        # a partial sum read as a total -- the trap this metric is written under.
        return head + (
            "PARTIAL, {} filings / {} merged pull requests over the ticks that counted "
            "-- {}".format(
                record.get("filings"),
                record.get("merged_prs"),
                record.get("why") or "some ticks contributed no pair",
            )
        )
    return head + "unrecognised intake state {!r}, so nothing is claimed".format(state)


def intake_trend(entries):
    """Re-add the recorded pairs across a run of ticks.

    Three holes are counted rather than dropped, because each is an absence somebody is
    entitled to see the size of: a tick whose counts could not be taken, a tick that
    recorded no intake at all, and an entry carrying something that is not a record.
    The last two are folded together -- both mean this tick contributed no pair.

    Any hole makes the answer ``partial``. The sum is still returned, because a partial
    sum labelled partial is usable and a partial sum labelled total is the trap.
    """
    filings = 0
    merged_prs = 0
    counted = 0
    uncounted = 0
    without_record = 0

    for entry in entries or []:
        detail = entry.get("detail") if isinstance(entry, dict) else None
        record = detail.get("intake") if isinstance(detail, dict) else None
        if not isinstance(record, dict) or "state" not in record:
            without_record += 1
            continue
        if record.get("state") in (INTAKE_MEASURED, INTAKE_NO_DENOMINATOR):
            filings += record.get("filings") or 0
            merged_prs += record.get("merged_prs") or 0
            counted += 1
        else:
            uncounted += 1

    trend = {
        "window": "the ticks in this history",
        "filings": filings,
        "merged_prs": merged_prs,
        "ratio": None,
        "why": None,
        "ticks_counted": counted,
        "ticks_uncounted": uncounted,
        "ticks_without_record": without_record,
    }

    if counted == 0:
        trend["state"] = INTAKE_COULD_NOT_COUNT
        trend["filings"] = None
        trend["merged_prs"] = None
        trend["why"] = (
            "no tick in this history recorded a countable intake pair "
            "({} could not count, {} recorded none)".format(uncounted, without_record)
        )
        return trend
    if uncounted or without_record:
        trend["state"] = INTAKE_PARTIAL
        trend["why"] = (
            "{} of {} ticks contributed no pair, so this sum is real and it is not "
            "the range's total".format(
                uncounted + without_record, counted + uncounted + without_record
            )
        )
        if merged_prs:
            trend["ratio"] = filings / merged_prs
        return trend
    if merged_prs == 0:
        trend["state"] = INTAKE_NO_DENOMINATOR
        return trend

    trend["state"] = INTAKE_MEASURED
    trend["ratio"] = filings / merged_prs
    return trend


def lane_models(lanes, window, why=None):
    """One tick's lane-model mix (#316): what each dispatched developer lane ran on.

    ``lanes`` is a list of mappings, each carrying ``issue``, ``model`` and ``choice``
    (``CHOICE_DEFAULT`` or ``CHOICE_OVERRIDE``), plus ``why`` when the choice is an
    override. ``None`` means the mix could not be established -- a resumed session whose
    transcripts were reaped, for instance -- and then ``why`` is required for the same
    reason ``intake``'s is: an unexplained absence is indistinguishable from a measurement
    of nothing. An empty list means the tick dispatched no developer lane, and that is a
    fact somebody established, not the same state as not knowing.

    ``window`` is required, exactly as ``intake``'s is: a mix with no window attached is
    a ratio nobody can read six ticks later.

    The model name is never checked against a list of models. Which models exist is a
    fact about the harness, not about this repository -- an allow-list here would be a
    second copy of somebody else's roster. What is refused is an empty name, and a choice
    that is neither word, and an override with no reason: the accretion #316 was filed
    about, in one field.
    """
    if not window or not str(window).strip():
        raise StateError(
            "a lane record needs a window -- what this dispatch was, in words. A model "
            "mix whose window nobody stated cannot be read against any other tick."
        )
    window = str(window).strip()

    if lanes is None:
        if not why or not str(why).strip():
            raise StateError(
                "a lane mix that could not be established needs a why. Without it, "
                "could-not-establish is an absence with no cause, which reads as a mix "
                "of nothing."
            )
        return {
            "state": LANES_COULD_NOT_ESTABLISH,
            "window": window,
            "lanes": None,
            "why": str(why).strip(),
        }

    if not isinstance(lanes, list):
        raise StateError("lanes must be a list of mappings or None, not {!r}".format(lanes))

    if not lanes:
        return {"state": LANES_NONE_DISPATCHED, "window": window, "lanes": [], "why": None}

    normalized = []
    for position, lane in enumerate(lanes, start=1):
        if not isinstance(lane, dict):
            raise StateError("lane {} is not a mapping ({!r})".format(position, lane))

        issue = lane.get("issue")
        issue_blank = issue is None or (isinstance(issue, str) and not issue.strip())
        if isinstance(issue, bool) or issue_blank:
            # `True` is an `int` in Python, and would land in the history as lane
            # number one -- checked ahead of the blank check on purpose.
            raise StateError(
                "lane {}: issue is required and must not be a bool ({!r})".format(
                    position, issue
                )
            )

        model = lane.get("model")
        if not model or not str(model).strip():
            raise StateError("lane {}: model is required and must not be empty".format(position))

        choice = lane.get("choice")
        if choice not in (CHOICE_DEFAULT, CHOICE_OVERRIDE):
            raise StateError(
                "lane {}: choice must be {!r} or {!r}, not {!r}".format(
                    position, CHOICE_DEFAULT, CHOICE_OVERRIDE, choice
                )
            )

        lane_why = lane.get("why")
        if choice == CHOICE_OVERRIDE:
            if not lane_why or not str(lane_why).strip():
                raise StateError(
                    "lane {}: an override needs a reason -- an unexplained override is "
                    "exactly the accretion #316 was filed about".format(position)
                )
            lane_why = str(lane_why).strip()
        else:
            lane_why = str(lane_why).strip() if lane_why and str(lane_why).strip() else None

        agent_type = lane.get("agent_type")
        agent_type = str(agent_type).strip() if agent_type and str(agent_type).strip() else None

        # #880: `dispatch_state` is optional and defaults to DISPATCH_STATE_DISPATCHED
        # -- every entry recorded before this field existed is read as an ordinary
        # fresh dispatch, which is the only honest default for history this field
        # cannot retroactively ask a question of.
        dispatch_state = lane.get("dispatch_state")
        if dispatch_state is None:
            dispatch_state = DISPATCH_STATE_DISPATCHED
        elif dispatch_state not in DISPATCH_STATES:
            raise StateError(
                "lane {} (issue {}): dispatch_state must be one of {}, not "
                "{!r}".format(position, issue, ", ".join(DISPATCH_STATES), dispatch_state)
            )

        dispatch_why = lane.get("dispatch_state_why")
        if dispatch_state == DISPATCH_STATE_AGENT_UNREACHABLE:
            if not dispatch_why or not str(dispatch_why).strip():
                raise StateError(
                    "lane {} (issue {}): dispatch_state agent-unreachable needs a "
                    "dispatch_state_why -- context died, or resumed and silent twice, "
                    "are different facts and must not render the same way".format(
                        position, issue
                    )
                )
            dispatch_why = str(dispatch_why).strip()
        else:
            dispatch_why = (
                str(dispatch_why).strip() if dispatch_why and str(dispatch_why).strip() else None
            )

        normalized.append(
            {
                "issue": issue,
                "model": str(model).strip(),
                "choice": choice,
                "why": lane_why,
                "agent_type": agent_type,
                "dispatch_state": dispatch_state,
                "dispatch_state_why": dispatch_why,
            }
        )

    # #880: a tick performs exactly one dispatch. The whole of a tick's lane mix is
    # recorded in one call (commands/tick.md step 6), so a genuine re-dispatch of an
    # issue this same tick already dispatched shows up here as the same issue number
    # appearing more than once with dispatch_state DISPATCHED -- `resumed` and
    # `agent-unreachable` are not fresh dispatches (a resume needs no new --lane entry
    # at all, and agent-unreachable is the one state a second one is correct under),
    # so only DISPATCHED entries are counted. Refused outright, the same shape
    # `lane_fill` already refuses an unreasoned short lane in -- the receipt is the
    # check, not a repeated read of the prose this rule is stated in.
    # Keyed on str(issue), not the raw value (found by review): --lane's own CLI
    # parser converts an issue token to int when it can and leaves it a string
    # otherwise, so a caller building lane dicts directly -- a test fixture, a
    # future non-CLI caller -- can hand this function 880 and "880" for the same
    # issue, and a dict keyed on the unconverted value would count them as two
    # different issues and silently accept the exact re-dispatch #880 exists to
    # catch. The display side already treated int/str as equivalent (the
    # pre-existing `key=str` on the sort below); the counting side did not.
    dispatched_counts = {}
    dispatched_display = {}
    for lane in normalized:
        if lane["dispatch_state"] == DISPATCH_STATE_DISPATCHED:
            key = str(lane["issue"])
            dispatched_counts[key] = dispatched_counts.get(key, 0) + 1
            dispatched_display.setdefault(key, lane["issue"])
    redispatched = sorted(
        (dispatched_display[key] for key, count in dispatched_counts.items() if count > 1),
        key=str,
    )
    if redispatched:
        raise StateError(
            "issue(s) {} recorded as a fresh dispatch more than once in this tick "
            "(#880) -- a tick performs exactly one dispatch; resume the lane's own "
            "agent instead (dispatch_state resumed), or record dispatch_state "
            "agent-unreachable with why if it is genuinely gone".format(
                ", ".join(str(issue) for issue in redispatched)
            )
        )

    return {"state": LANES_RECORDED, "window": window, "lanes": normalized, "why": None}


def lane_models_line(record):
    """One line a tick report can print. The state decides the sentence, not the caller.

    Handles both a single tick's record (``lanes`` is a list) and a trend summed across
    a history (``lanes`` is a count, ``counts`` carries the mix) -- the two shapes
    ``lane_models`` and ``lane_model_trend`` return, so one renderer serves both call
    sites the way ``intake_line`` does not need to.

    The single join, so `_receipt_line` cannot be skipped by adding a branch below.
    """
    return _receipt_line(_lane_models_sentence(record))


def _lane_models_sentence(record):
    """`lane_models_line`'s branches. Unfolded on purpose -- it has one caller."""
    if not isinstance(record, dict):
        raise StateError("lane_models_line takes a lane record, not {!r}".format(record))
    state = record.get("state")
    window = record.get("window") or "an unstated window"
    head = "lane models {}: ".format(window)

    if state == LANES_NONE_DISPATCHED:
        return head + "dispatched no developer lane"
    if state == LANES_COULD_NOT_ESTABLISH:
        return head + "could not establish ({}) -- this is not zero lanes".format(
            record.get("why") or "no reason recorded"
        )
    if state in (LANES_RECORDED, LANES_PARTIAL):
        lanes = record.get("lanes")
        unexpected = []
        if isinstance(lanes, list):
            counts = {}
            overrides = 0
            for lane in lanes:
                model = lane.get("model") if isinstance(lane, dict) else None
                if model:
                    counts[model] = counts.get(model, 0) + 1
                if isinstance(lane, dict) and lane.get("choice") == CHOICE_OVERRIDE:
                    overrides += 1
                # #862: an agent_type recorded outside the closed set is the exact
                # shape that issue was filed for -- a lane dispatched as
                # `general-purpose`, never `oss:developer`/`oss:triager`. `None`
                # (nobody recorded one) is deliberately not an anomaly: that is the
                # third state, "not recorded", and flagging it here would make an
                # ordinary lane read as a finding.
                agent_type = lane.get("agent_type") if isinstance(lane, dict) else None
                if agent_type and agent_type not in KNOWN_AGENT_TYPES:
                    unexpected.append((lane.get("issue"), agent_type))
            # #880: resumed/agent-unreachable are worth surfacing in the sentence for
            # the same reason overrides already are -- a mix that reads as an ordinary
            # tick while quietly carrying a lane that needed a resume, or one whose
            # agent went unreachable, is exactly the silent absence this repository is
            # named after.
            resumed = sum(
                1 for lane in lanes
                if isinstance(lane, dict) and lane.get("dispatch_state") == DISPATCH_STATE_RESUMED
            )
            unreachable = sum(
                1 for lane in lanes
                if isinstance(lane, dict)
                and lane.get("dispatch_state") == DISPATCH_STATE_AGENT_UNREACHABLE
            )
        else:
            counts = record.get("counts") or {}
            overrides = record.get("overrides") or 0
            resumed = record.get("resumed") or 0
            unreachable = record.get("unreachable") or 0
            # #862: the trend shape (`lane_model_trend`'s own dict) carries its own
            # already-collected `unexpected` list, since `lanes` here is a count, not
            # the list this branch's own per-lane scan above needs.
            for issue, agent_type in record.get("unexpected") or []:
                unexpected.append((issue, agent_type))
        parts = ", ".join(
            "{} {}".format(count, model) for model, count in sorted(counts.items())
        )
        mix = head + "{} ({} override{})".format(
            parts or "no lanes", overrides, "" if overrides == 1 else "s"
        )
        if resumed or unreachable:
            mix += " ({} resumed, {} agent-unreachable)".format(resumed, unreachable)
        if unexpected:
            mix += " -- {} dispatched as {}, not {}".format(
                ", ".join("#{}".format(issue) for issue, _ in unexpected),
                "/".join(sorted(set(agent_type for _, agent_type in unexpected))),
                "/".join(KNOWN_AGENT_TYPES),
            )
        if state == LANES_PARTIAL:
            # Deliberately not the recorded sentence with a caveat appended -- a reader
            # skimming for the mix would take the mix and leave the caveat, which is a
            # partial sum read as a total (the same trap `intake_line` guards against).
            return "PARTIAL, " + mix[len(head):] + " -- {}".format(
                record.get("why") or "some ticks contributed no record"
            )
        return mix
    return head + "unrecognised lane models state {!r}, so nothing is claimed".format(state)


def lane_model_trend(entries):
    """Re-add the recorded lane mixes across a run of ticks.

    Three holes counted rather than dropped, same shape as ``intake_trend``: a tick whose
    mix could not be established, a tick that dispatched no lane at all (this one is not
    a hole -- it is a real zero, and is counted), and an entry carrying something that is
    not a lane record. Any hole among the first and third makes the answer ``partial``;
    the sum is still returned, because a partial sum labelled partial is usable and one
    labelled total is the trap.
    """
    counts = {}
    lanes_total = 0
    overrides = 0
    resumed_total = 0
    unreachable_total = 0
    counted = 0
    uncounted = 0
    without_record = 0
    # #862: unexpected agent_type sightings, carried across the whole history rather
    # than dropped -- `_lane_models_sentence`'s single-tick anomaly check only ever
    # sees a list of lanes, and a trend's own `lanes` is a count, not a list, so
    # without this the finding "a lane was dispatched outside oss:developer/
    # oss:triager" was visible on the one tick that recorded it and invisible on the
    # aggregate view (--model-trend) most likely to be read for a pattern across ticks.
    unexpected = []

    for entry in entries or []:
        detail = entry.get("detail") if isinstance(entry, dict) else None
        record = detail.get("lanes") if isinstance(detail, dict) else None
        if not isinstance(record, dict) or "state" not in record:
            without_record += 1
            continue
        state = record.get("state")
        if state == LANES_RECORDED:
            for lane in record.get("lanes") or []:
                if not isinstance(lane, dict):
                    continue
                model = lane.get("model")
                if model:
                    counts[model] = counts.get(model, 0) + 1
                lanes_total += 1
                if lane.get("choice") == CHOICE_OVERRIDE:
                    overrides += 1
                if lane.get("dispatch_state") == DISPATCH_STATE_RESUMED:
                    resumed_total += 1
                elif lane.get("dispatch_state") == DISPATCH_STATE_AGENT_UNREACHABLE:
                    unreachable_total += 1
                agent_type = lane.get("agent_type")
                if agent_type and agent_type not in KNOWN_AGENT_TYPES:
                    unexpected.append((lane.get("issue"), agent_type))
            counted += 1
        elif state == LANES_NONE_DISPATCHED:
            counted += 1
        else:
            uncounted += 1

    trend = {
        "window": "the ticks in this history",
        "counts": counts if counted else None,
        "lanes": lanes_total if counted else None,
        "overrides": overrides if counted else None,
        "resumed": resumed_total if counted else None,
        "unreachable": unreachable_total if counted else None,
        "unexpected": unexpected,
        "why": None,
        "ticks_counted": counted,
        "ticks_uncounted": uncounted,
        "ticks_without_record": without_record,
    }

    if counted == 0:
        trend["state"] = LANES_COULD_NOT_ESTABLISH
        trend["why"] = (
            "no tick in this history recorded a lane model mix ({} could not "
            "establish, {} said nothing about their lanes)".format(uncounted, without_record)
        )
        return trend
    if uncounted or without_record:
        trend["state"] = LANES_PARTIAL
        trend["why"] = (
            "{} of {} ticks contributed no lane record, so this sum is real and it is "
            "not the range's total".format(
                uncounted + without_record, counted + uncounted + without_record
            )
        )
        return trend
    if lanes_total == 0:
        # Every tick that contributed to this sum said the same thing: it dispatched no
        # developer lane. That is a real, established zero -- not the same rendering as
        # `recorded` with an empty mix, which would read as a lane count nobody took.
        trend["state"] = LANES_NONE_DISPATCHED
        return trend

    trend["state"] = LANES_RECORDED
    return trend


def lane_fill(entries, window, why=None):
    """One tick's lane fill (#852): how many issues each dispatched lane carried, and
    why -- when fewer than ``dispatch_rank.MAX_LANE`` -- from the closed vocabulary
    ``dispatch_rank.SHORT_REASONS`` declares.

    ``entries`` is a list of mappings, each carrying ``primary`` (the lane's primary
    issue number) and ``count``, plus ``reason`` when the count is short. ``None`` means
    the fill could not be established, mirroring ``lane_models``'s own ``None`` case --
    and then ``why`` is required for the identical reason. An empty list means the tick
    dispatched no developer lane.

    Validation of ``count``/``reason`` together is not reimplemented here: it is the
    exact call the dispatch decision itself already had to make, so this delegates to
    ``dispatch_rank.check_lane`` -- a lane of ``count`` issues, checked against a
    ``reason`` -- rather than re-declaring the ceiling or the closed set a second time
    in this file. A lane whose fill this function refuses is a lane the dispatcher
    should have refused to dispatch in the first place.
    """
    if not window or not str(window).strip():
        raise StateError(
            "a lane fill record needs a window -- what this dispatch was, in words. A "
            "fill nobody can read against any other tick is not worth recording."
        )
    window = str(window).strip()

    if entries is None:
        if not why or not str(why).strip():
            raise StateError(
                "a lane fill that could not be established needs a why. Without it, "
                "could-not-establish is an absence with no cause, which reads as a "
                "fill of nothing."
            )
        return {
            "state": LANE_FILL_COULD_NOT_ESTABLISH,
            "window": window,
            "lanes": None,
            "why": str(why).strip(),
        }

    if not isinstance(entries, list):
        raise StateError(
            "lane fill entries must be a list of mappings or None, not {!r}".format(entries)
        )

    if not entries:
        return {"state": LANE_FILL_NONE_DISPATCHED, "window": window, "lanes": [], "why": None}

    normalized = []
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise StateError("lane fill {} is not a mapping ({!r})".format(position, entry))

        primary = entry.get("primary")
        primary_blank = primary is None or (isinstance(primary, str) and not primary.strip())
        if isinstance(primary, bool) or primary_blank:
            raise StateError(
                "lane fill {}: primary issue is required and must not be a bool "
                "({!r})".format(position, primary)
            )

        count = entry.get("count")
        if isinstance(count, bool) or not isinstance(count, int):
            raise StateError(
                "lane fill {} (issue {}): count must be a whole number, not "
                "{!r}".format(position, primary, count)
            )
        if count < 0:
            raise StateError(
                "lane fill {} (issue {}): a count cannot be negative ({})".format(
                    position, primary, count
                )
            )

        reason = entry.get("reason")
        if reason is not None and count == _dispatch_rank.MAX_LANE:
            # check_lane() silently drops a reason on a full lane rather than
            # refusing it -- correct for the dispatch decision, which only cares
            # whether a short lane was left unexplained. A recorded reason on a
            # full lane is a different defect: a claim about a constraint that
            # never bound, landing in the history looking like a measured one.
            raise StateError(
                "lane fill {} (issue {}): a full lane of {} needs no reason, but "
                "{!r} was given".format(position, primary, count, reason)
            )
        candidates = entry.get("candidates")
        if candidates is not None and (isinstance(candidates, bool) or not isinstance(candidates, int)):
            raise StateError(
                "lane fill {} (issue {}): candidates must be a whole number, not "
                "{!r}".format(position, primary, candidates)
            )

        # `range(count)`, not `list(range(count))`: check_lane() only ever calls
        # len() on its argument (see its own docstring/body), and a range's len() is
        # O(1) with no allocation -- materializing the list first meant an over-cap
        # count was still refused correctly, but only after building a list that
        # size first (#852, found by review).
        #
        # `candidates` (#871) is threaded straight through -- this is the exact
        # call the dispatch decision itself already had to make, and `check_lane`
        # is the single place a claimed 'board-exhausted' is checked against a
        # measured candidate count rather than merely typed.
        #
        # #918 routes that same optional fourth field to whichever parameter the
        # claimed reason is a statement about, rather than adding a fifth: the
        # field has always meant "the count that would refute this claim", and
        # which count that is follows from the word. 'board-exhausted' is refuted
        # by file-disjoint candidates still open; 'no-adjacent' is refuted by
        # candidates adjacent to the top issue. They are different measurements
        # and check_lane keeps them in different parameters -- routing here is
        # what stops a caller having to supply both when only one can apply.
        # 'did-not-search' and 'could-not-tell' take neither: a count says nothing
        # about a search that never ran or one that ran and failed, and passing a
        # number alongside either would be a measurement the caller does not have.
        if candidates is not None and count == _dispatch_rank.MAX_LANE:
            # A full lane makes no short-lane claim at all, so there is nothing a
            # count could refute. `check_lane` returns "ok" for size == MAX_LANE
            # before it ever looks at `short_reason` or either count, so this one
            # was accepted and dropped -- the record came back byte-identical to
            # one from a caller who measured nothing. The reason-on-a-full-lane
            # refusal above has existed since #852; this is its missing twin for
            # the count, found by review on PR #921's own fix for the same class.
            raise StateError(
                "lane fill {} (issue {}): a full lane of {} makes no claim a "
                "count could refute, but {} was given -- record it on the short "
                "lane it was measured for, or omit it (#918)".format(
                    position, primary, count, candidates
                )
            )
        if candidates is not None and reason in ("did-not-search", "could-not-tell"):
            # Neither reason is a claim a count can refute, so `check_lane` would
            # read this field for neither parameter and drop it -- and a dropped
            # measurement renders exactly like one nobody took, which is the
            # defect #918 is about. Refuse rather than discard silently (found by
            # review on PR #921: the two calls returned identical receipts).
            raise StateError(
                "lane fill {} (issue {}): {!r} takes no count, but {} was given "
                "-- a count refutes a claim, and this reason makes none: "
                "'board-exhausted' is refuted by file-disjoint candidates and "
                "'no-adjacent' by adjacent ones, while a search that did not run "
                "and one that could not be computed are refuted by neither "
                "(#918)".format(position, primary, reason, candidates)
            )
        if reason == "no-adjacent":
            check = _dispatch_rank.check_lane(range(count), reason, adjacent=candidates)
        else:
            check = _dispatch_rank.check_lane(range(count), reason, candidates=candidates)
        if check["state"] != "ok":
            raise StateError(
                "lane fill {} (issue {}): {}".format(position, primary, check["why"])
            )

        lane_record = {
            "primary": primary, "count": count, "reason": check["short_reason"],
        }
        # #953: `candidates` was used to validate the short-lane claim above and
        # then dropped here -- a claim corroborated against a measured 0 and one
        # for which no count was ever supplied produced byte-identical records.
        # Persisted only when a caller actually supplied one, so an existing
        # record with no `candidates` key (a full lane, or an older entry) stays
        # readable, and a corroborated claim now differs from an uncorroborated
        # one even when `count`/`reason` are identical.
        if candidates is not None:
            lane_record["candidates"] = candidates
        normalized.append(lane_record)

    return {"state": LANE_FILL_RECORDED, "window": window, "lanes": normalized, "why": None}


def lane_fill_line(record):
    """One line a tick report can print. Same shape as ``lane_models_line``, one
    field over -- the state decides the sentence, not the caller."""
    return _receipt_line(_lane_fill_sentence(record))


def _lane_fill_sentence(record):
    """`lane_fill_line`'s branches. Unfolded on purpose -- it has one caller."""
    if not isinstance(record, dict):
        raise StateError("lane_fill_line takes a lane fill record, not {!r}".format(record))
    state = record.get("state")
    window = record.get("window") or "an unstated window"
    head = "lane fill {}: ".format(window)

    if state == LANE_FILL_NONE_DISPATCHED:
        return head + "dispatched no developer lane"
    if state == LANE_FILL_COULD_NOT_ESTABLISH:
        return head + "could not establish ({}) -- this is not zero lanes".format(
            record.get("why") or "no reason recorded"
        )
    if state in (LANE_FILL_RECORDED, LANE_FILL_PARTIAL):
        lanes = record.get("lanes")
        if isinstance(lanes, list):
            counts = {}
            full = 0
            for lane in lanes:
                reason = lane.get("reason") if isinstance(lane, dict) else None
                if reason:
                    counts[reason] = counts.get(reason, 0) + 1
                else:
                    full += 1
        else:
            counts = record.get("counts") or {}
            full = record.get("full_lanes") or 0
        parts = ", ".join(
            "{} {}".format(count, reason) for reason, count in sorted(counts.items())
        )
        if full:
            parts = ", ".join(p for p in (parts, "{} full".format(full)) if p)
        mix = head + "{}".format(parts or "no lanes")
        if state == LANE_FILL_PARTIAL:
            # Deliberately not the recorded sentence with a caveat appended -- same trap
            # `lane_models_line`'s own PARTIAL arm guards against: a reader skimming for
            # the mix would take the mix and leave the caveat.
            return "PARTIAL, " + mix[len(head):] + " -- {}".format(
                record.get("why") or "some ticks contributed no record"
            )
        return mix
    return head + "unrecognised lane fill state {!r}, so nothing is claimed".format(state)


#: #866: a citation-shaped token inside a declined-dispatch reason -- a
#: backtick-quoted op string (`gh-issue:844`, `gh-prs`) or a script invocation
#: (`lane_setup.py --lane ...`). Three findings from two rounds of review
#: shaped this pattern, in order:
#:
#: 1. A hyphen or a colon is required, not either alone -- `gh-prs` (hyphen,
#:    no colon) and `gh-issue:844` (both) are the two worked examples this
#:    repository's own docs and changelog cite, and a colon-only first draft
#:    missed the first of them: `decline_reason_state("`gh-prs` shows the
#:    PR")` returned `uncited` against its own documented example.
#: 2. The pre-delimiter token must start with a letter, so a bare timestamp
#:    (`14:32`) or a ratio (`3:1`) inside backticks does not read as a
#:    citation just because it contains a colon.
#: 3. A colon immediately followed by `//` does not count on its own -- an
#:    ordinary URL scheme (`https://...`) is not a call, even wrapped in
#:    backticks, unless it also carries a hyphen somewhere in the token.
#:
#: What remains is a real, stated limit rather than a closed one: this
#: cannot tell a true citation from a fabricated one, only that
#: *something callable-shaped* is named -- the same bar the issue itself
#: states as "checkable". `gh-pr-merge:1208:squash` and `todo-fixme` both
#: still read as cited; nothing here verifies the cited call was run, or
#: that it says what the reason claims.
_DECLINE_CITATION_RE = re.compile(
    r"`[a-zA-Z][^`\s]*(?:-[^`\s]*|:(?!//)[^`\s]*)`|`[^`\s]*\.py\b[^`]*`"
)


def decline_reason_state(reason):
    """#866: a tick may decline to dispatch an issue, or shrink a lane below the
    default fill, only on a reason re-derived this tick -- not one carried
    forward from an earlier handoff or a prior tick's report. Checkable by
    shape rather than by trusting the prose: a reason naming the op or script
    invocation that established it this tick is ``cited``; a reason with no
    such citation is ``uncited``, even when it later turns out to be true --
    a true fact and a measured one are not the same claim, and only the
    second licenses declining to dispatch.

    This does not verify the cited call was actually run, or that it says
    what the reason claims -- it verifies only that a citation exists at
    all, the same limit ``review_return.py``'s classifier states for its own
    sentinel-shaped check.
    """
    if reason is None or not str(reason).strip():
        raise StateError(
            "a declined dispatch needs a reason to classify -- an empty reason "
            "is not cited and not uncited, it is nothing to check"
        )
    text = str(reason)
    cited = bool(_DECLINE_CITATION_RE.search(text))
    return {"state": "cited" if cited else "uncited", "reason": text}


def decline_reason_line(record):
    """One line a tick report can print, same shape as `lane_fill_line`."""
    if not isinstance(record, dict) or record.get("state") not in ("cited", "uncited"):
        raise StateError("decline_reason_line takes a decline_reason_state record, not {!r}".format(record))
    if record["state"] == "cited":
        return "CITED -- names a call made this tick; the decline stands"
    return "UNCITED -- no call cited; this is not a reason, the issue dispatches"


def lane_fill_trend(entries):
    """Re-add the recorded lane fills across a run of ticks (#852): the direct
    measure of how often a short lane's reason is ``could-not-tell`` rather than
    ``board-exhausted``/``no-adjacent`` -- the sibling sweep issue's own skip rate,
    made visible without needing that sweep to exist.

    Same three-hole shape as ``lane_model_trend``: a tick whose fill could not be
    established, a tick that dispatched no lane at all (a real zero, counted), and an
    entry carrying nothing that is a lane fill record. Any hole among the first and
    third makes the answer ``partial``.
    """
    counts = {}
    lanes_total = 0
    full_lanes = 0
    counted = 0
    uncounted = 0
    without_record = 0

    for entry in entries or []:
        detail = entry.get("detail") if isinstance(entry, dict) else None
        record = detail.get("lane_fill") if isinstance(detail, dict) else None
        if not isinstance(record, dict) or "state" not in record:
            without_record += 1
            continue
        state = record.get("state")
        if state == LANE_FILL_RECORDED:
            for lane in record.get("lanes") or []:
                if not isinstance(lane, dict):
                    continue
                reason = lane.get("reason")
                lanes_total += 1
                if reason:
                    counts[reason] = counts.get(reason, 0) + 1
                else:
                    full_lanes += 1
            counted += 1
        elif state == LANE_FILL_NONE_DISPATCHED:
            counted += 1
        else:
            uncounted += 1

    trend = {
        "window": "the ticks in this history",
        "counts": counts if counted else None,
        "lanes": lanes_total if counted else None,
        "full_lanes": full_lanes if counted else None,
        "why": None,
        "ticks_counted": counted,
        "ticks_uncounted": uncounted,
        "ticks_without_record": without_record,
    }

    if counted == 0:
        trend["state"] = LANE_FILL_COULD_NOT_ESTABLISH
        trend["why"] = (
            "no tick in this history recorded a lane fill ({} could not "
            "establish, {} said nothing about their lanes)".format(
                uncounted, without_record
            )
        )
        return trend
    if uncounted or without_record:
        trend["state"] = LANE_FILL_PARTIAL
        trend["why"] = (
            "{} of {} ticks contributed no lane fill record, so this sum is real "
            "and it is not the range's total".format(
                uncounted + without_record, counted + uncounted + without_record
            )
        )
        return trend
    if lanes_total == 0:
        # Every tick that contributed to this sum dispatched no developer lane. A real,
        # established zero -- not the same rendering as `recorded` with an empty mix,
        # which would read as a fill nobody took.
        trend["state"] = LANE_FILL_NONE_DISPATCHED
        return trend

    trend["state"] = LANE_FILL_RECORDED
    return trend


def cleanup_overrides(entries):
    """Cleanup overrides for one tick (#1007): a forced worktree removal that ran
    after ``gh-pr-merge``'s own ``|cleanup`` had already declined that worktree with
    ``cannot tell``. Each entry is a mapping carrying ``worktree`` and ``reason``,
    both required.

    Unlike ``lane_fill``, no entry here is ever reason-optional: the whole reason to
    record one at all is that a guard already said no and the tick pushed the
    removal through anyway, so there is always a reason to state -- naming why the
    tick judged the override safe (or accepted the risk). A forced removal with no
    stated reason is exactly the silent override #1007 was filed over: `|cleanup`'s
    refusal was a line in an op's output, the force-remove that followed was two
    ordinary git commands, and afterwards nothing distinguished that cleanup from a
    clean one.

    ``entries`` must be a non-empty list -- call this only when at least one
    override actually happened in this tick; an empty list is a claim nothing
    supports, not a state worth writing (contrast ``lane_fill``, which does record a
    real empty-dispatch zero).
    """
    if not isinstance(entries, list) or not entries:
        raise StateError(
            "cleanup_overrides needs a non-empty list of {worktree, reason} "
            "mappings; call it only when at least one forced cleanup actually "
            "happened this tick"
        )
    normalized = []
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise StateError(
                "cleanup override {} is not a mapping ({!r})".format(position, entry)
            )
        worktree = entry.get("worktree")
        if not isinstance(worktree, str) or not worktree.strip():
            raise StateError(
                "cleanup override {}: worktree is required and must be a "
                "non-blank string ({!r})".format(position, worktree)
            )
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise StateError(
                "cleanup override {}: reason is required and must be a "
                "non-blank string -- a forced removal with no stated reason is "
                "the silent override #1007 was filed over ({!r})".format(
                    position, reason
                )
            )
        normalized.append({"worktree": worktree.strip(), "reason": reason.strip()})
    return normalized


def cleanup_override_line(record):
    """One line a tick report can print for a cleanup-override record."""
    if not isinstance(record, list) or not record:
        raise StateError(
            "cleanup_override_line takes a non-empty list of records, not "
            "{!r}".format(record)
        )
    return _receipt_line(
        "cleanup override: {} worktree(s) force-removed over |cleanup's own "
        "refusal -- {}".format(
            len(record),
            "; ".join(
                "{} ({})".format(item["worktree"], item["reason"]) for item in record
            ),
        )
    )


def cohort_freeze(cohort, counts, why=None):
    """One cohort freeze count (#407): a label's count taken from more than one route.

    ``counts`` maps a route name -- ``"filtered_query"``, ``"search_total_count"``,
    ``"per_issue_read"``, or whatever a caller wants to call each route -- to the
    count that route returned, or ``None`` for a route that was not attempted or
    could not be read.

    Fewer than two routes actually counted refuses to freeze on a lone number: a
    single filtered-query read is exactly the measurement #407 was filed about, so
    ``why`` is required for the same reason it is in ``intake`` -- an unexplained
    absence is indistinguishable from a measurement of nothing.

    Two or more counted routes that disagree return ``unknown`` with no count
    picked. GitHub's label filter is an index and it lags the writes that feed it,
    so a lower number is not evidence of a smaller cohort, it is evidence of a
    stale index -- and since a cohort can only shrink, a wrong number frozen here
    is never corrected by any later measurement. This refuses to guess between the
    routes rather than trusting the lower one, the higher one, or the first one
    given.

    Two or more counted routes that agree return ``measured`` with that count.
    """
    if not cohort or not str(cohort).strip():
        raise StateError(
            "a cohort freeze record needs the cohort's own label -- a count with "
            "no label attached cannot be read against any other freeze."
        )
    if not isinstance(counts, dict) or not counts:
        raise StateError(
            "counts must be a non-empty mapping of route name to count or None"
        )

    taken = {}
    for route, value in counts.items():
        if not isinstance(route, str) or not route.strip():
            raise StateError(
                "route name must be a non-empty string, not {!r}".format(route)
            )
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise StateError(
                "route {!r}: count must be a whole number or None, not {!r}".format(
                    route, value
                )
            )
        if value < 0:
            raise StateError(
                "route {!r}: count cannot be negative ({})".format(route, value)
            )
        taken[route] = value

    record = {
        "cohort": str(cohort).strip(),
        "counts": dict(counts),
        "count": None,
        "state": None,
        "why": None,
    }

    if len(taken) < 2:
        if not why or not str(why).strip():
            raise StateError(
                "fewer than two routes were counted, and a single route is "
                "exactly the situation #407 was filed about -- a why is required "
                "so this is not indistinguishable from a freeze nobody thought "
                "to check twice."
            )
        record["state"] = COHORT_COULD_NOT_COUNT
        record["why"] = str(why).strip()
        return record

    distinct = set(taken.values())
    if len(distinct) > 1:
        record["state"] = COHORT_UNKNOWN
        record["why"] = (
            "routes disagree ({}); a lower count is not evidence of a smaller "
            "cohort, it is evidence of a stale index, and this freeze can only "
            "shrink so a wrong number here is never corrected later".format(
                ", ".join(
                    "{}={}".format(route, value)
                    for route, value in sorted(taken.items())
                )
            )
        )
        return record

    record["state"] = COHORT_MEASURED
    record["count"] = next(iter(distinct))
    return record


def cohort_freeze_from_pairs(cohort, pairs, why=None):
    """`cohort_freeze`, from a raw list of ``(route, value)`` pairs rather than a dict.

    This is the CLI's entry point, and it exists for one reason: a plain ``dict(pairs)``
    silently keeps only the last value for a route named twice, which is exactly the
    failure #407 was filed about, one level removed -- a route re-counted after an
    earlier read disagreed with itself would have its own disagreement erased before
    ``cohort_freeze`` ever saw it, and the collapsed pair would look like a single
    clean count. So a repeated route name is refused here, before the collapse, rather
    than silently resolved by "last write wins".
    """
    seen = {}
    repeated = []
    for route, value in pairs or []:
        if route in seen and seen[route] != value:
            repeated.append(route)
        seen[route] = value
    if repeated:
        raise StateError(
            "route(s) {} were given more than once with different counts -- naming "
            "a route twice is likely a re-count after the first answer looked wrong, "
            "and collapsing it to 'the last one given' would silently erase exactly "
            "the disagreement this metric exists to catch. Give each route once, "
            "under a distinct name if you mean to keep both counts (e.g. "
            "'filtered_query_2')".format(", ".join(sorted(set(repeated))))
        )
    return cohort_freeze(cohort, dict(pairs or []), why=why)


def cohort_freeze_line(record):
    """One line a tick report can print. The state decides the sentence, not the caller.

    The single join, so `_receipt_line` cannot be skipped by adding a branch below.
    """
    return _receipt_line(_cohort_freeze_sentence(record))


def _cohort_freeze_sentence(record):
    """`cohort_freeze_line`'s branches. Unfolded on purpose -- it has one caller."""
    if not isinstance(record, dict):
        raise StateError(
            "cohort_freeze_line takes a cohort freeze record, not {!r}".format(record)
        )
    state = record.get("state")
    cohort = record.get("cohort") or "an unstated cohort"
    head = "cohort freeze {}: ".format(cohort)

    if state == COHORT_MEASURED:
        return head + "{} (routes agree)".format(record.get("count"))
    if state == COHORT_UNKNOWN:
        return head + "unknown -- {}".format(
            record.get("why") or "routes disagreed for no recorded reason"
        )
    if state == COHORT_COULD_NOT_COUNT:
        return head + (
            "could not count ({}) -- this is not a route count of zero, and it "
            "must not be frozen on".format(record.get("why") or "no reason recorded")
        )
    return head + "unrecognised cohort freeze state {!r}, so nothing is claimed".format(
        state
    )


def wait(dispatch, observable, at):
    """Record a fresh wait (#337): what a tick is blocked on, in a form the next tick
    can test rather than believe.

    ``dispatch`` names what was set in motion -- "gate 3 audit dispatched at 23:12Z" --
    and ``observable`` names what a later tick looks for to know it cleared -- "four
    output issues filed on the tracker". Neither is optional: a dispatch with no
    observable is a wait nothing can test, and an observable with no dispatch is a
    condition nobody can trace back to what it was waiting on.

    Always starts ``holds`` -- a wait is recorded at the moment the condition is judged
    not yet met. ``check_wait`` is what re-derives it on a later tick.
    """
    if not dispatch or not str(dispatch).strip():
        raise StateError(
            "a wait needs a dispatch -- what was set in motion. A wait with no "
            "dispatch is a claim nothing can trace back to what it is waiting on."
        )
    if not observable or not str(observable).strip():
        raise StateError(
            "a wait needs an observable -- what a later tick looks for to know it "
            "cleared. A wait with no observable is prose, not a claim that can fail."
        )
    if not at or not str(at).strip():
        raise StateError(
            "a wait needs an ISO timestamp for when it was recorded, not read from a "
            "clock in here."
        )
    return {
        "dispatch": str(dispatch).strip(),
        "observable": str(observable).strip(),
        "recorded_at": str(at).strip(),
        "state": WAIT_HOLDS,
    }


def check_wait(record, state, cleared_by=None, why=None):
    """Re-derive a recorded wait (#337): still holds, has cleared, or could not be
    evaluated at all.

    ``record`` is the wait record carried by a previous entry's ``detail["wait"]``.
    The dispatch, observable and original timestamp are carried over unchanged, so the
    history keeps what was originally waited on even after it clears.

    ``state`` must be one of the three. ``holds`` needs nothing more -- the condition
    was tested and not yet observed. ``cleared`` requires ``cleared_by``, what was
    actually observed, so a later reader can tell a real clearance from a guess.
    ``could-not-evaluate`` requires ``why`` -- the observable could not be tested at
    all, which must never render the same as ``holds``: ``holds`` is a measurement that
    came back negative, this is no measurement.
    """
    if not isinstance(record, dict) or not record.get("dispatch") or not record.get(
        "observable"
    ):
        raise StateError(
            "check_wait needs a wait record carrying dispatch and observable, not "
            "{!r}".format(record)
        )
    if state not in (WAIT_HOLDS, WAIT_CLEARED, WAIT_COULD_NOT_EVALUATE):
        raise StateError(
            "{!r} is not a recognised wait state ({}, {} or {})".format(
                state, WAIT_HOLDS, WAIT_CLEARED, WAIT_COULD_NOT_EVALUATE
            )
        )
    result = {
        "dispatch": record["dispatch"],
        "observable": record["observable"],
        "recorded_at": record.get("recorded_at"),
        "state": state,
    }
    if state == WAIT_CLEARED:
        if not cleared_by or not str(cleared_by).strip():
            raise StateError(
                "a cleared wait needs cleared_by -- what was actually observed. "
                "Reporting 'cleared' with nothing seen is the same unfalsifiable "
                "prose this exists to replace."
            )
        if why is not None and str(why).strip():
            raise StateError(
                "why is only for could-not-evaluate; a cleared wait's observation "
                "goes in cleared_by, not here"
            )
        result["cleared_by"] = str(cleared_by).strip()
    elif state == WAIT_COULD_NOT_EVALUATE:
        if not why or not str(why).strip():
            raise StateError(
                "could-not-evaluate needs why -- an unexplained 'could not check' is "
                "indistinguishable from a check that was simply skipped."
            )
        if cleared_by is not None and str(cleared_by).strip():
            raise StateError(
                "cleared_by is only for a cleared wait; could-not-evaluate means "
                "nothing was observed"
            )
        result["why"] = str(why).strip()
    elif cleared_by is not None or why is not None:
        # Neither belongs to `holds`. Silently dropping either one here is exactly
        # the failure this function exists to close one level up: a maintainer who
        # means --check-wait cleared and typos --check-wait holds would otherwise
        # get exit 0, a `still holds` receipt, and the observation text nowhere in
        # the stored entry.
        raise StateError(
            "cleared_by/why only apply to a cleared or could-not-evaluate wait; "
            "holds needs neither, and passing one would be silently discarded"
        )
    return result


def _last_wait(path):
    """The most recent entry that carries a wait record, scanning back past any
    entry that recorded something else entirely -- a cohort freeze (#407), a lane
    record, a plain intake -- rather than only looking at the last entry (#436).

    One-entry lifetime read a wait recorded in one tick as unreachable the moment any
    other entry landed after it, and printed exactly what it prints when no wait was
    ever recorded: the two absences were byte-identical. Returns
    ``(entry, record)`` for the most recent entry whose ``detail`` carries a ``wait``
    key -- even a malformed one, since the freshest statement about the wait is what a
    reader must see rather than an older, valid one behind it -- or ``(None, None)``
    if no entry in the whole history ever recorded one.
    """
    for entry in reversed(read(path)):
        if not isinstance(entry, dict):
            continue
        detail = entry.get("detail")
        if not isinstance(detail, dict):
            continue
        if "wait" in detail:
            return entry, detail["wait"]
    return None, None


def wait_line(record):
    """One line a tick report can print. The state decides the sentence, not the caller."""
    return _receipt_line(_wait_sentence(record))


def _wait_sentence(record):
    """`wait_line`'s branches. Unfolded on purpose -- it has one caller."""
    if not isinstance(record, dict):
        raise StateError("wait_line takes a wait record, not {!r}".format(record))
    state = record.get("state")
    dispatch = record.get("dispatch") or "an unstated wait"
    head = "wait on {}: ".format(dispatch)

    if state == WAIT_HOLDS:
        return head + "still holds -- watching for {}".format(
            record.get("observable") or "an unstated observable"
        )
    if state == WAIT_CLEARED:
        return head + "cleared -- {}".format(
            record.get("cleared_by") or "no reason recorded"
        )
    if state == WAIT_COULD_NOT_EVALUATE:
        return head + "could not evaluate -- {}".format(
            record.get("why") or "no reason recorded"
        )
    return head + "unrecognised wait state {!r}, so nothing is claimed".format(state)


def triage_recorded(at):
    """Record that a triage sweep completed at this tick (#855).

    A receipt for the spine's own Cadence section, which asks a tick to be able to
    say when the last sweep ran rather than assume it is fresh: three to four ticks,
    then a release, then a triage sweep, then three to four more -- and nothing
    before this recorded which of those a given tick was standing in.
    """
    if not at or not str(at).strip():
        raise StateError(
            "a triage record needs an ISO timestamp for when the sweep completed, "
            "not read from a clock in here -- the same reason every other recorder "
            "in this file takes ``at`` as an argument rather than calling one."
        )
    return {"recorded_at": str(at).strip()}


def last_triage(path):
    """The most recent triage sweep this history recorded (#855), in three states.

    ``(state, recorded_at, why)`` would spread one fact across three return values for
    no reason the callers of every other reader in this file need -- returns a mapping,
    the same shape ``_last_wait``'s caller builds by hand today and every other checker
    in this file returns directly.

    Scans backward past any entry that recorded something else -- a lane record, a
    cohort freeze, a plain intake -- the same shape ``_last_wait`` already uses,
    because the last entry in the history and the last entry that recorded a triage
    sweep are not the same entry in general. ``never`` is a real, established absence
    (this history has never once recorded a sweep) and must not render the same as
    ``could-not-read`` (the state file itself could not be read at all) -- an absence
    this process could not observe is not the same fact as one it looked for and did
    not find, the defect class this whole repository is named after, one reader over.
    """
    try:
        entries = read(path)
    except StateError as exc:
        return {"state": TRIAGE_COULD_NOT_READ, "recorded_at": None, "why": str(exc)}
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            continue
        detail = entry.get("detail")
        if not isinstance(detail, dict):
            continue
        if "triage" not in detail:
            continue
        # Stop at the FIRST entry (scanning backward) that carries a triage key at
        # all -- even a malformed one -- rather than skipping past it to an older,
        # valid record behind it (found by review): this is `_last_wait`'s own
        # discipline, stated in its docstring, and this function's docstring
        # already claimed to follow it without actually doing so. Falling through
        # to an older valid record would render a stale answer as the freshest
        # one, which is a subtler instance of the exact silent-absence defect
        # this repository is named after -- not "nothing was found" but "the
        # wrong thing was found and called current".
        triage = detail["triage"]
        if isinstance(triage, dict) and triage.get("recorded_at"):
            return {
                "state": TRIAGE_RECORDED,
                "recorded_at": triage["recorded_at"],
                "why": None,
            }
        return {
            "state": TRIAGE_COULD_NOT_READ,
            "recorded_at": None,
            "why": (
                "the most recent triage record ({!r}) is malformed -- not a "
                "mapping with a non-empty recorded_at -- and reading past it to "
                "an older, valid one would render a stale answer as the current "
                "one".format(triage)
            ),
        }
    return {"state": TRIAGE_NEVER, "recorded_at": None, "why": None}


def triage_line(record):
    """One line a tick report can print. The state decides the sentence, not the caller."""
    return _receipt_line(_triage_sentence(record))


def _triage_sentence(record):
    """`triage_line`'s branches. Unfolded on purpose -- it has one caller."""
    if not isinstance(record, dict):
        raise StateError("triage_line takes a triage record, not {!r}".format(record))
    state = record.get("state")
    if state == TRIAGE_RECORDED:
        return "last triaged: {}".format(record.get("recorded_at") or "an unstated time")
    if state == TRIAGE_NEVER:
        return "last triaged: never"
    if state == TRIAGE_COULD_NOT_READ:
        return "last triaged: could not read ({})".format(
            record.get("why") or "no reason recorded"
        )
    return "unrecognised triage state {!r}, so nothing is claimed".format(state)


def plugin_identity_check(current, prior, current_route=None, prior_route=None):
    """Compare this tick's plugin identity against the prior tick's recorded one (#477).

    ``current`` is this tick's own reading -- ``doctor.plugin_identity(PLUGIN_ROOT)``,
    which never raises and always returns a non-empty string, so a falsy value here is
    a caller error rather than a real reading and is refused. ``prior`` is whatever the
    previous entry that recorded one carried in ``detail["plugin_identity"]`` --
    ``_last_plugin_identity`` finds it -- or ``None`` when no earlier entry ever did.

    ``current_route``/``prior_route`` are each a short label for HOW that identity was
    obtained (e.g. ``"resolved-install"`` vs the version-pinned ``"pinned-root"`` --
    see ``commands/tick.md`` step 1) -- or ``None`` when the caller does not track
    routes at all. A missing route is treated as its own value (#677's comment: two
    readings taken by different routes are not the same measurement, and that
    includes "nobody recorded a route" versus "this one was routed"), so a caller
    that never opts in keeps comparing exactly as it always did, while the very tick
    a route starts being recorded gets ``route-mismatch`` rather than a false
    ``changed`` against the unrouted prior.

    Returns a record with ``current``, ``prior``, ``current_route``, ``prior_route``
    and ``state``; ``state`` is ``PLUGIN_CHANGED``, ``PLUGIN_UNCHANGED``,
    ``PLUGIN_COULD_NOT_TELL`` or ``PLUGIN_ROUTE_MISMATCH``, with a ``why`` filled in
    for every state except plain ``changed``/``unchanged``. See the module-level
    comment beside the four constants for what each means and why the comparison is
    over the whole string rather than a version alone.
    """
    if not current or not str(current).strip():
        raise StateError(
            "plugin_identity_check needs the current tick's identity; the caller "
            "always has one (doctor.plugin_identity() never raises), so an empty "
            "value here is a caller error rather than a real reading"
        )
    current = str(current).strip()
    current_route = str(current_route).strip() if current_route else None
    prior_route = str(prior_route).strip() if prior_route else None
    if prior is None or not str(prior).strip():
        return {
            "current": current,
            "prior": None,
            "current_route": current_route,
            "prior_route": prior_route,
            "state": PLUGIN_COULD_NOT_TELL,
            "why": (
                "no earlier tick recorded a plugin identity -- this must not "
                "render as unchanged, since a loop that has never recorded a "
                "version would otherwise look exactly like one whose version "
                "has not moved"
            ),
        }
    prior = str(prior).strip()

    cur_route_key = current_route or _PLUGIN_IDENTITY_ROUTE_UNRECORDED
    pri_route_key = prior_route or _PLUGIN_IDENTITY_ROUTE_UNRECORDED
    if cur_route_key != pri_route_key:
        return {
            "current": current,
            "prior": prior,
            "current_route": current_route,
            "prior_route": prior_route,
            "state": PLUGIN_ROUTE_MISMATCH,
            "why": (
                "this tick's identity was read via {!r}, the prior tick's via {!r} "
                "-- these are not the same measurement, so changed/unchanged "
                "between them would describe nothing that occurred".format(
                    current_route or "(no route recorded)",
                    prior_route or "(no route recorded)",
                )
            ),
        }

    if current == prior:
        return {
            "current": current,
            "prior": prior,
            "current_route": current_route,
            "prior_route": prior_route,
            "state": PLUGIN_UNCHANGED,
            "why": None,
        }
    return {
        "current": current,
        "prior": prior,
        "current_route": current_route,
        "prior_route": prior_route,
        "state": PLUGIN_CHANGED,
        "why": None,
    }


def plugin_identity_line(record):
    """One line a tick report can print. The state decides the sentence, not the caller."""
    return _receipt_line(_plugin_identity_sentence(record))


def _plugin_identity_sentence(record):
    """`plugin_identity_line`'s branches. Unfolded on purpose -- it has one caller."""
    if not isinstance(record, dict):
        raise StateError(
            "plugin_identity_line takes a plugin identity record, not {!r}".format(record)
        )
    state = record.get("state")
    head = "plugin identity: "
    if state == PLUGIN_UNCHANGED:
        return head + "unchanged ({})".format(record.get("current"))
    if state == PLUGIN_CHANGED:
        return head + "changed -- was {}, now {}".format(
            record.get("prior"), record.get("current")
        )
    if state == PLUGIN_COULD_NOT_TELL:
        return head + "could not tell -- {}".format(
            record.get("why") or "no reason recorded"
        )
    if state == PLUGIN_ROUTE_MISMATCH:
        return head + "route mismatch, not comparable -- {}".format(
            record.get("why") or "no reason recorded"
        )
    return head + "unrecognised plugin identity state {!r}, so nothing is claimed".format(
        state
    )


def _last_plugin_identity(path):
    """The most recent entry that recorded a plugin identity, scanning back past any
    entry that recorded something else -- an intake, a lane record, a cohort freeze,
    a wait -- rather than only looking at the last entry. Same shape as `_last_wait`
    and for the same reason (#436): a plugin identity recorded two ticks ago must
    still be found behind whatever landed after it.

    Returns ``(entry, identity, route)`` for the most recent entry whose ``detail``
    carries a ``plugin_identity`` key -- even a falsy one, since the freshest
    statement is what a reader must see -- or ``(None, None, None)`` if no entry
    ever recorded one. ``route`` is ``detail.get("plugin_identity_route")``, which
    is ``None`` for every entry written before #677 -- that absence is itself
    meaningful to `plugin_identity_check` and must not be papered over here.
    """
    for entry in reversed(read(path)):
        if not isinstance(entry, dict):
            continue
        detail = entry.get("detail")
        if not isinstance(detail, dict):
            continue
        if "plugin_identity" in detail:
            return entry, detail["plugin_identity"], detail.get("plugin_identity_route")
    return None, None, None


def _plugin_root_snapshot_path(path):
    """Where the within-tick root snapshot lives (#565): beside the state file,
    never inside it -- this is deliberately NOT an entry, so it must not
    accumulate in `--read`/`--trend`/history the way a real tick record does.
    """
    return Path(str(path) + ".plugin-root-snapshot.json")


def record_plugin_root(path, root):
    """Snapshot `root` for later comparison in THIS SAME tick (#565).

    Called once, early in a tick -- see `commands/tick.md` step 1. Overwrites
    whatever snapshot (if any) was left over from an earlier, presumably
    incomplete tick; a snapshot is only ever meant to answer for the tick that
    wrote it.
    """
    if not root or not str(root).strip():
        raise StateError(
            "record_plugin_root needs a non-empty root; an empty value here is a "
            "caller error, not a real reading"
        )
    root = str(root).strip()
    snapshot = _plugin_root_snapshot_path(path)
    tmp = snapshot.with_suffix(snapshot.suffix + ".tmp")
    try:
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({"root": root}), encoding="utf-8")
        tmp.replace(snapshot)
    except OSError as exc:
        # Self-review finding: `append()` above wraps its own write in exactly this
        # guard, with the same reasoning -- an OSError left to go straight through
        # here would be a raw traceback instead of the clean FAIL line every other
        # CLI mode in this file produces on error (a disk-full, a permission
        # refusal, an over-MAX_PATH component on Windows).
        try:
            tmp.unlink()
        except OSError:
            pass
        raise StateError(
            "could not record the plugin root snapshot ({})".format(exc)
        )
    return {"root": root}


def check_plugin_root(path, current):
    """Compare `current` against the root snapshot recorded earlier in this tick
    (#565), then consume the snapshot -- a snapshot answers for one tick only, so
    a second check without a fresh `record_plugin_root` in between must not find
    a leftover answer from whatever tick wrote it.

    Returns a record with ``current``, ``prior`` and ``state``; ``state`` is
    ``PLUGIN_ROOT_CHANGED``, ``PLUGIN_ROOT_UNCHANGED`` or
    ``PLUGIN_ROOT_COULD_NOT_READ``, with a ``why`` filled in for the third. See
    the module-level comment beside the three constants for what each means.
    """
    if not current or not str(current).strip():
        raise StateError(
            "check_plugin_root needs the current reading; an empty value here is "
            "a caller error, not a real reading"
        )
    current = str(current).strip()
    snapshot = _plugin_root_snapshot_path(path)
    try:
        text = snapshot.read_text(encoding="utf-8")
    except FileNotFoundError:
        # The exception in hand answers which fact this is (CLAUDE.md: never ask
        # the filesystem a second question to classify a read failure) -- this is
        # a genuine absence: nothing was ever recorded this tick, or an earlier
        # check already consumed it. `--record-plugin-root` is real advice here.
        return {
            "current": current,
            "prior": None,
            "state": PLUGIN_ROOT_COULD_NOT_READ,
            "why": (
                "no snapshot was recorded earlier in this tick (or an earlier "
                "check already consumed it) -- record one at the start of the "
                "tick with --record-plugin-root before checking"
            ),
        }
    except UnicodeDecodeError as exc:
        # Self-review finding (#686): caught by name and before OSError, exactly
        # as `describe()` above already does for its own read of a sibling
        # file (that fix was for #76) -- `UnicodeDecodeError` is a `ValueError`,
        # not an `OSError`, so an `except OSError` around this read lets it
        # through as a raw traceback instead of the clean COULD_NOT_READ record
        # every other reading mode in this file returns. A torn write or a
        # pre-plugin tool writing in the console's codepage is the realistic
        # way this snapshot gets one stray byte.
        return {
            "current": current,
            "prior": None,
            "state": PLUGIN_ROOT_COULD_NOT_READ,
            "why": "the snapshot at {} exists but could not be decoded as UTF-8 ({})".format(
                snapshot, exc
            ),
        }
    except OSError as exc:
        # Self-review finding (#686): a snapshot that EXISTS but could not be
        # read (a permission refusal, a transient lock) is a different fact
        # from the absence above, and telling this caller to run
        # --record-plugin-root is wrong advice -- there is already a snapshot;
        # the read itself failed. Name the path and the underlying error so a
        # maintainer can act, without turning the receipt into a traceback.
        return {
            "current": current,
            "prior": None,
            "state": PLUGIN_ROOT_COULD_NOT_READ,
            "why": "the snapshot at {} exists but could not be read ({})".format(
                snapshot, exc
            ),
        }
    try:
        snapshot.unlink()
    except OSError:
        # Self-review finding: a snapshot answers for ONE tick only (see this
        # function's own docstring above) -- if the delete itself fails (a
        # transient lock, common on Windows when another process briefly holds
        # the file open), a later, UNRELATED tick's own check_plugin_root call
        # would read this same leftover and answer for a comparison that tick
        # never made. Deletion failing is not something this call can force,
        # but scrubbing the content is a cheap best-effort second line: content
        # that fails to parse below falls into `could-not-read` here AND for
        # whatever later call finds this same leftover file, rather than
        # silently handing back a real-looking prior.
        try:
            snapshot.write_text("", encoding="utf-8")
        except OSError:
            pass
    try:
        doc = json.loads(text)
        prior = doc.get("root") if isinstance(doc, dict) else None
    except ValueError:
        prior = None
    if not prior or not str(prior).strip():
        return {
            "current": current,
            "prior": None,
            "state": PLUGIN_ROOT_COULD_NOT_READ,
            "why": "the recorded snapshot exists but could not be read as a root value",
        }
    prior = str(prior).strip()
    if current == prior:
        return {"current": current, "prior": prior, "state": PLUGIN_ROOT_UNCHANGED, "why": None}
    return {"current": current, "prior": prior, "state": PLUGIN_ROOT_CHANGED, "why": None}


def plugin_root_line(record):
    """One line a tick report can print. The state decides the sentence, not the caller."""
    if not isinstance(record, dict):
        raise StateError(
            "plugin_root_line takes a plugin root record, not {!r}".format(record)
        )
    state = record.get("state")
    head = "plugin root (within this tick): "
    if state == PLUGIN_ROOT_UNCHANGED:
        return _receipt_line(head + "unchanged ({})".format(record.get("current")))
    if state == PLUGIN_ROOT_CHANGED:
        return _receipt_line(
            head + "changed -- was {}, now {}".format(record.get("prior"), record.get("current"))
        )
    if state == PLUGIN_ROOT_COULD_NOT_READ:
        return _receipt_line(
            head + "could not read -- {}".format(record.get("why") or "no reason recorded")
        )
    return _receipt_line(
        head + "unrecognised plugin root state {!r}, so nothing is claimed".format(state)
    )


def _count_argument(text):
    """A CLI count: a whole number, or the literal ``unknown``.

    Anything else is refused rather than coerced. A count the parser guessed at is the
    one thing this metric cannot survive -- it would reach the history looking exactly
    like a count somebody took.
    """
    import argparse

    if text.strip().lower() == "unknown":
        # Not `None`: `None` is what argparse leaves behind for a flag nobody passed,
        # and "I could not count this" must not be indistinguishable from "I said
        # nothing about this" at the one boundary this metric is about.
        return UNKNOWN_COUNT
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "{!r} is neither a whole number nor 'unknown'".format(text)
        )
    if value < 0:
        raise argparse.ArgumentTypeError("a count cannot be negative ({})".format(value))
    return value


def _cohort_count_argument(text):
    """A CLI cohort route count: ``ROUTE=N``, or ``ROUTE=unknown`` for a route that
    was not attempted or could not be read.
    """
    import argparse

    if "=" not in text:
        raise argparse.ArgumentTypeError("{!r} is not ROUTE=N or ROUTE=unknown".format(text))
    route, _, value_text = text.partition("=")
    route = route.strip()
    if not route:
        raise argparse.ArgumentTypeError(
            "{!r}: a route name is required before '='".format(text)
        )
    value_text = value_text.strip()
    if value_text.lower() == "unknown":
        return (route, None)
    try:
        value = int(value_text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "{!r}: {!r} is neither a whole number nor 'unknown'".format(text, value_text)
        )
    if value < 0:
        raise argparse.ArgumentTypeError("{!r}: a count cannot be negative".format(text))
    return (route, value)


def _lane_argument(text):
    """A CLI lane: ``ISSUE=MODEL:CHOICE[:WHY]``.

    Only the shape is checked here -- an issue and a model present, a choice that is one
    of the two words. Whether an override actually carries its reason is left to
    ``lane_models``, which needs ``--lane-window`` too and is the single place that
    decision is made, at the CLI or from any other caller.
    """
    import argparse

    if "=" not in text:
        raise argparse.ArgumentTypeError(
            "{!r} is not ISSUE=MODEL:CHOICE[:WHY]".format(text)
        )
    issue_text, _, rest = text.partition("=")
    if not issue_text.strip():
        raise argparse.ArgumentTypeError(
            "{!r}: an issue number is required before '='".format(text)
        )
    if not rest.strip():
        raise argparse.ArgumentTypeError(
            "{!r}: MODEL:CHOICE is required after '='".format(text)
        )
    parts = rest.split(":", 2)
    if len(parts) < 2 or not parts[0].strip() or not parts[1].strip():
        raise argparse.ArgumentTypeError(
            "{!r} is not ISSUE=MODEL:CHOICE[:WHY]".format(text)
        )
    model, choice = parts[0].strip(), parts[1].strip()
    if choice not in (CHOICE_DEFAULT, CHOICE_OVERRIDE):
        raise argparse.ArgumentTypeError(
            "{!r}: choice must be {!r} or {!r}, not {!r}".format(
                text, CHOICE_DEFAULT, CHOICE_OVERRIDE, choice
            )
        )
    why = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
    try:
        issue = int(issue_text.strip())
    except ValueError:
        issue = issue_text.strip()
    lane = {"issue": issue, "model": model, "choice": choice}
    if why is not None:
        lane["why"] = why
    return lane


def _lane_agent_type_argument(text):
    """#862: which `subagent_type` a `--lane` issue was actually dispatched as.

    ``ISSUE=TYPE`` -- a separate flag from ``--lane`` rather than a fourth
    colon-delimited field on it, because ``WHY`` already absorbs everything after its
    own colon (``rest.split(":", 2)`` above) and a fourth field there would be
    ambiguous with a WHY that happens to contain a colon. Only the shape is checked
    here; whether TYPE is one of the two known agent definitions is
    ``lane_models_line``'s question, not this parser's -- an unrecognised type is the
    exact thing #862 needs recorded, not refused at the CLI.
    """
    import argparse

    if "=" not in text:
        raise argparse.ArgumentTypeError("{!r} is not ISSUE=TYPE".format(text))
    issue_text, _, type_text = text.partition("=")
    if not issue_text.strip():
        raise argparse.ArgumentTypeError(
            "{!r}: an issue number is required before '='".format(text)
        )
    if not type_text.strip():
        raise argparse.ArgumentTypeError(
            "{!r}: a subagent_type is required after '='".format(text)
        )
    try:
        issue = int(issue_text.strip())
    except ValueError:
        issue = issue_text.strip()
    return {"issue": issue, "agent_type": type_text.strip()}


def _lane_dispatch_state_argument(text):
    """#880: which of the three dispatch states a `--lane` issue is in --
    ``ISSUE=STATE[:WHY]``.

    A separate flag from `--lane`, matched by issue number, the same shape
    `--lane-agent-type` already uses and for the same reason: `WHY` on `--lane`
    already absorbs everything after its own colon, so a fifth colon-delimited field
    there would be ambiguous with a lane WHY that happens to contain a colon. Only the
    shape is checked here -- STATE present, ISSUE present; whether STATE is one of the
    three declared words and whether `agent-unreachable` actually carries a WHY is
    `lane_models`'s question, the single place that decision is made.
    """
    import argparse

    if "=" not in text:
        raise argparse.ArgumentTypeError("{!r} is not ISSUE=STATE[:WHY]".format(text))
    issue_text, _, rest = text.partition("=")
    if not issue_text.strip():
        raise argparse.ArgumentTypeError(
            "{!r}: an issue number is required before '='".format(text)
        )
    if not rest.strip():
        raise argparse.ArgumentTypeError(
            "{!r}: a dispatch state is required after '='".format(text)
        )
    parts = rest.split(":", 1)
    state = parts[0].strip()
    if not state:
        raise argparse.ArgumentTypeError(
            "{!r}: a dispatch state is required after '='".format(text)
        )
    why = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    try:
        issue = int(issue_text.strip())
    except ValueError:
        issue = issue_text.strip()
    entry = {"issue": issue, "dispatch_state": state}
    if why is not None:
        entry["dispatch_state_why"] = why
    return entry


def _lane_fill_argument(text):
    """A CLI lane fill: ``PRIMARY:COUNT[:REASON[:CANDIDATES]]`` (#852, #871).

    Only the shape is checked here -- a primary issue number present, a count that
    parses as a whole number, and a fourth field (#871) that parses as one too when
    given. Whether the count needs a reason, whether one given is from the closed
    vocabulary, whether the count itself is in range, and whether ``CANDIDATES``
    contradicts a claimed ``board-exhausted`` is left to
    ``lane_fill``/``dispatch_rank.check_lane``, the single place that decision is made,
    at the CLI or from any other caller.
    """
    import argparse

    parts = text.split(":", 3)
    if len(parts) < 2 or not parts[0].strip() or not parts[1].strip():
        raise argparse.ArgumentTypeError(
            "{!r} is not PRIMARY:COUNT[:REASON[:CANDIDATES]]".format(text)
        )
    primary_text, count_text = parts[0].strip(), parts[1].strip()
    try:
        primary = int(primary_text)
    except ValueError:
        primary = primary_text
    try:
        count = int(count_text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "{!r}: {!r} is not a whole number".format(text, count_text)
        )
    reason = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
    entry = {"primary": primary, "count": count}
    if reason is not None:
        entry["reason"] = reason
    # #871: the fourth, optional field -- how many file-disjoint candidates
    # the caller found still open on the board, so a claimed 'board-exhausted'
    # can be checked rather than merely typed. Only meaningful shaped here;
    # dispatch_rank.check_lane is where it is actually judged against the
    # reason, the same division of labour this function already keeps for
    # REASON itself (see its own docstring).
    if len(parts) > 3 and parts[3].strip():
        candidates_text = parts[3].strip()
        try:
            entry["candidates"] = int(candidates_text)
        except ValueError:
            raise argparse.ArgumentTypeError(
                "{!r}: {!r} is not a whole number".format(text, candidates_text)
            )
    return entry


def _cleanup_override_argument(text):
    """A CLI cleanup-override entry: ``WORKTREE=REASON`` (#1007).

    Split on the first ``=``, not ``:`` -- a worktree is a filesystem path, and a
    Windows path's drive letter (``C:`` at the front) already owns the first
    colon, so ``:`` cannot be the delimiter here the way it is for
    ``--lane-fill``'s ``PRIMARY:COUNT``. ``=`` mirrors ``--lane-dispatch-state``'s
    ``ISSUE=STATE`` for the same reason: the left side is freeform text that must
    not collide with the separator.

    Only the shape is checked here -- both sides present and non-blank. Nothing
    here treats a reason as optional; unlike a lane fill's count, there is no
    case where recording an override needs no reason, so the CLI type itself is
    the whole check and ``cleanup_overrides`` re-validates rather than trusting it,
    the same defence in depth ``lane_fill`` keeps for its own entries.
    """
    import argparse

    if "=" not in text:
        raise argparse.ArgumentTypeError("{!r} is not WORKTREE=REASON".format(text))
    worktree_text, _, reason_text = text.partition("=")
    worktree, reason = worktree_text.strip(), reason_text.strip()
    if not worktree or not reason:
        raise argparse.ArgumentTypeError(
            "{!r} is not WORKTREE=REASON -- both sides are required".format(text)
        )
    return {"worktree": worktree, "reason": reason}


def _say(text, stream=None):
    """Write one line that cannot die on the console's codepage.

    Anything printed is encoded with the console's encoding, not the source file's, and
    stdout's error handler is ``strict`` where stderr's is ``backslashreplace``. Every
    ``FAIL`` line here can carry a path -- an ``OSError``'s message names the file it
    could not write -- and a path can hold a character cp1252 has no room for, which is
    the ordinary case for a Windows account whose username is not Latin-1. The ``print``
    then raises before the line arrives, and the verdict this whole issue exists to
    guarantee is the one thing lost.

    Worse, and measured rather than argued: ``UnicodeEncodeError`` is a ``ValueError``,
    so the raise landed in ``_main``'s ``except ValueError`` and came out as ``FAIL
    --detail is not valid JSON`` on a run with no ``--detail`` at all. A crash would
    have been the loud failure; that is the quiet one.

    Reproduced with ``PYTHONIOENCODING=ascii`` and a state path holding one non-ASCII
    byte -- observed on POSIX, and the same mechanism on a Windows console, where it is
    reasoned rather than run.
    """
    stream = sys.stdout if stream is None else stream
    encoding = getattr(stream, "encoding", None)
    if encoding:
        # Round-tripped rather than written as bytes: the stream is a text stream and
        # this keeps it one. `backslashreplace` on the way out means an unrepresentable
        # character arrives as an escape somebody can read, not as a dropped line.
        text = text.encode(encoding, "backslashreplace").decode(encoding, "replace")
    print(text, file=stream)


def _main(argv=None):
    """CLI for /oss:tick.

    The timestamp is an argument rather than something read here, for the same reason
    the library takes one: a clock inside this file makes what it writes untestable.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Read and append maintainer tick state.")
    parser.add_argument("path", help="the state file, from .oss.json's state_file")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--read", action="store_true", help="print the whole history")
    group.add_argument("--last", action="store_true", help="print the most recent entry")
    group.add_argument("--decision", help="append an entry with this decision")
    group.add_argument(
        "--trend",
        action="store_true",
        help="print the intake ratio re-added across the whole history",
    )
    group.add_argument(
        "--migrate",
        action="store_true",
        help=(
            "convert a pre-plugin state file -- an object keyed tick_<ISO> -- into the "
            "list shape, keeping the original at <path>" + BACKUP_SUFFIX
        ),
    )
    group.add_argument(
        "--model-trend",
        action="store_true",
        help="print the lane-model mix re-added across the whole history",
    )
    group.add_argument(
        "--lane-fill-trend",
        action="store_true",
        help="print the lane-fill reason distribution re-added across the whole "
        "history (#852) -- makes a run of could-not-tell a visible number",
    )
    group.add_argument(
        "--pending-wait",
        action="store_true",
        help="print the most recently recorded wait if anything is still pending "
        "-- holds or could-not-evaluate (#337, #436, #443) -- or 'no pending "
        "wait' if it was cleared or none was ever recorded",
    )
    group.add_argument(
        "--last-triage",
        action="store_true",
        help="#855: print when the last triage sweep completed -- recorded "
        "<ISO>, never (this history has never once recorded one, a real "
        "established absence), or could-not-read (the state file itself "
        "could not be read, never the same as never)",
    )
    group.add_argument(
        "--check-plugin-identity",
        metavar="IDENTITY",
        help="compare this tick's plugin identity (doctor.plugin_identity(PLUGIN_ROOT)) "
        "against the most recently recorded one (#477): changed, unchanged, "
        "could-not-tell if no prior tick ever recorded one, or route-mismatch if "
        "the prior was read by a different route (#677) -- pair with "
        "--plugin-identity-route to record/compare the route itself",
    )
    group.add_argument(
        "--record-plugin-root",
        metavar="ROOT",
        help="snapshot this tick's own resolved ${CLAUDE_PLUGIN_ROOT} for later "
        "comparison, within THIS SAME tick (#565); call once, early -- see "
        "commands/tick.md step 1. Pair with --check-plugin-root later in the "
        "same tick",
    )
    group.add_argument(
        "--check-plugin-root",
        metavar="ROOT",
        help="compare ${CLAUDE_PLUGIN_ROOT} against the snapshot --record-plugin-root "
        "took earlier in this tick (#565): changed, unchanged, or could-not-read "
        "if no snapshot was recorded (or one was already consumed). Consumes the "
        "snapshot -- answers for one tick only",
    )
    group.add_argument(
        "--check-decline-reason",
        metavar="TEXT",
        help="#866: classify a reason for declining to dispatch an issue, or for "
        "shrinking a lane below the default fill -- CITED when it names the op "
        "or script invocation this tick ran to establish it, UNCITED otherwise, "
        "which means it is not a reason and the issue dispatches. Advisory only "
        "(found by review): unlike --lane-fill, nothing here refuses --decision "
        "on an UNCITED reason -- there is no lane record for an issue that was "
        "never dispatched to attach a refusal to. Run it and report the result; "
        "the tick's own report is what makes an uncited decline visible. Takes "
        "no state file reading; path is still required but unused",
    )
    parser.add_argument("--at", help="ISO timestamp for the appended entry (required with --decision)")
    parser.add_argument("--detail", help="optional JSON object attached to the entry")
    parser.add_argument(
        "--filings",
        type=_count_argument,
        help="issues the loop filed in this window, or 'unknown'",
    )
    parser.add_argument(
        "--merged-prs",
        type=_count_argument,
        help="pull requests merged in this window, or 'unknown'",
    )
    parser.add_argument(
        "--window",
        help="what the two counts were taken over, in words -- 'since the last tick'",
    )
    parser.add_argument(
        "--intake-why", help="why a count is 'unknown'; required when either one is"
    )
    parser.add_argument(
        "--lane",
        action="append",
        type=_lane_argument,
        help="one dispatched lane, ISSUE=MODEL:CHOICE[:WHY]; repeatable",
    )
    parser.add_argument(
        "--lane-agent-type",
        action="append",
        type=_lane_agent_type_argument,
        help="#862: the subagent_type a --lane issue was actually dispatched as, "
        "ISSUE=TYPE; repeatable, needs a matching --lane for the same issue",
    )
    parser.add_argument(
        "--lane-dispatch-state",
        action="append",
        type=_lane_dispatch_state_argument,
        help="#880: which of dispatched/resumed/agent-unreachable a --lane issue is "
        "in, ISSUE=STATE[:WHY]; repeatable, needs a matching --lane for the same "
        "issue. Omit for an ordinary fresh dispatch -- dispatched is the default. "
        "The whole --decision call is refused if the same issue is recorded "
        "dispatched more than once in it.",
    )
    parser.add_argument(
        "--lanes",
        choices=("none", "unknown"),
        help="'none' if the tick dispatched no developer lane, 'unknown' if it could "
        "not be established -- use with --lane-why",
    )
    parser.add_argument(
        "--lane-window",
        help="what this lane dispatch was, in words -- required with --lane/--lanes",
    )
    parser.add_argument(
        "--lane-why", help="why the mix is 'unknown'; required when --lanes unknown is"
    )
    parser.add_argument(
        "--lane-fill",
        action="append",
        type=_lane_fill_argument,
        help="one dispatched lane's fill (#852), PRIMARY:COUNT[:REASON] -- REASON is "
        "required when COUNT is under dispatch_rank.MAX_LANE and must be one of "
        "dispatch_rank.SHORT_REASONS; repeatable",
    )
    parser.add_argument(
        "--lane-fills",
        choices=("none", "unknown"),
        help="'none' if the tick dispatched no developer lane, 'unknown' if its fill "
        "could not be established -- use with --lane-fill-why",
    )
    parser.add_argument(
        "--lane-fill-window",
        help="what this lane dispatch was, in words -- required with "
        "--lane-fill/--lane-fills",
    )
    parser.add_argument(
        "--lane-fill-why",
        help="why the fill is 'unknown'; required when --lane-fills unknown is",
    )
    parser.add_argument(
        "--cleanup-override",
        action="append",
        type=_cleanup_override_argument,
        metavar="WORKTREE=REASON",
        help="#1007: record a forced worktree cleanup that overrode "
        "gh-pr-merge's own |cleanup declining that worktree with 'cannot "
        "tell' -- WORKTREE=REASON, reason required, naming why the force "
        "was judged safe. Repeatable, one per forced worktree.",
    )
    parser.add_argument(
        "--cohort", help="the frozen cohort's label, e.g. cohort-6 -- required with --cohort-count"
    )
    parser.add_argument(
        "--cohort-count",
        action="append",
        type=_cohort_count_argument,
        help="one route's count, ROUTE=N or ROUTE=unknown; repeatable, at least two needed",
    )
    parser.add_argument(
        "--cohort-why",
        help="why fewer than two routes were counted; required when that happens",
    )
    parser.add_argument(
        "--wait-dispatch",
        help="record a fresh wait (#337): what was set in motion; use with "
        "--wait-observable",
    )
    parser.add_argument(
        "--wait-observable",
        help="what a later tick looks for to know the wait cleared; use with "
        "--wait-dispatch",
    )
    parser.add_argument(
        "--check-wait",
        choices=(WAIT_HOLDS, WAIT_CLEARED, WAIT_COULD_NOT_EVALUATE),
        help="re-derive the most recently recorded pending wait (#436): holds, "
        "cleared (needs --wait-cleared-by) or could-not-evaluate (needs --wait-why)",
    )
    parser.add_argument(
        "--wait-cleared-by",
        help="what was observed to clear the wait; required with --check-wait cleared",
    )
    parser.add_argument(
        "--wait-why",
        help="why the wait could not be evaluated; required with --check-wait "
        "could-not-evaluate",
    )
    parser.add_argument(
        "--plugin-identity",
        help="attach this tick's plugin identity to the entry made by --decision "
        "(#477); use with --decision only",
    )
    parser.add_argument(
        "--plugin-identity-route",
        help="how the plugin identity was obtained -- e.g. resolved-install or "
        "pinned-root (#677). Use with --check-plugin-identity (describes THIS "
        "tick's reading) or with --decision --plugin-identity (records it onto "
        "the entry, for the NEXT tick's comparison). A route mismatch between "
        "the current and prior readings is its own state, never folded into "
        "changed/unchanged",
    )
    parser.add_argument(
        "--triage-recorded",
        help="#855: attach that a triage sweep completed at this tick, as an ISO "
        "timestamp, to the entry made by --decision. --last-triage re-derives it "
        "on a later tick",
    )
    parser.add_argument(
        "--tick-cost-session",
        help="an opaque id for this session (#694), so a later tick's floor lookup "
        "matches on it; use with --decision",
    )
    parser.add_argument(
        "--tick-cost-window",
        help="what this tick-cost reading covers, in words -- 'this tick'",
    )
    parser.add_argument(
        "--tick-cost-start-ctx",
        type=_count_argument,
        help="input tokens at the moment this tick begins, or 'unknown' (#694)",
    )
    parser.add_argument(
        "--tick-cost-calls",
        type=_count_argument,
        help="tool calls this tick made, or 'unknown'",
    )
    parser.add_argument(
        "--tick-cost-context-carried",
        type=_count_argument,
        help="context tokens this tick carried across its calls, or 'unknown'",
    )
    parser.add_argument(
        "--tick-cost-first",
        action="store_true",
        help="this is the session's own first tick -- its start_ctx becomes the "
        "floor; refused if this session already has one recorded",
    )
    parser.add_argument(
        "--tick-cost-why",
        help="why start-ctx/calls/context-carried is 'unknown'; required when any is",
    )
    parser.add_argument(
        "--tick-cost-rate",
        type=float,
        help="optional list-rate, USD per million tokens -- renders a derived cost "
        "that always says it is list-rate, never a billed amount",
    )
    args = parser.parse_args(argv)

    intake_flags = [
        name
        for name, value in (
            ("--filings", args.filings),
            ("--merged-prs", args.merged_prs),
            ("--window", args.window),
            ("--intake-why", args.intake_why),
        )
        if value is not None
    ]
    lane_flags = [
        name
        for name, value in (
            ("--lane", args.lane),
            ("--lanes", args.lanes),
            ("--lane-window", args.lane_window),
            ("--lane-why", args.lane_why),
        )
        if value is not None
    ]
    lane_fill_flags = [
        name
        for name, value in (
            ("--lane-fill", args.lane_fill),
            ("--lane-fills", args.lane_fills),
            ("--lane-fill-window", args.lane_fill_window),
            ("--lane-fill-why", args.lane_fill_why),
        )
        if value is not None
    ]
    cleanup_override_flags = [
        name
        for name, value in (("--cleanup-override", args.cleanup_override),)
        if value is not None
    ]
    cohort_flags = [
        name
        for name, value in (
            ("--cohort", args.cohort),
            ("--cohort-count", args.cohort_count),
            ("--cohort-why", args.cohort_why),
        )
        if value is not None
    ]
    wait_flags = [
        name
        for name, value in (
            ("--wait-dispatch", args.wait_dispatch),
            ("--wait-observable", args.wait_observable),
            ("--check-wait", args.check_wait),
            ("--wait-cleared-by", args.wait_cleared_by),
            ("--wait-why", args.wait_why),
        )
        if value is not None
    ]
    plugin_identity_flags = [
        name
        for name, value in (("--plugin-identity", args.plugin_identity),)
        if value is not None
    ]
    triage_flags = [
        name
        for name, value in (("--triage-recorded", args.triage_recorded),)
        if value is not None
    ]
    tick_cost_flags = [
        name
        for name, value in (
            ("--tick-cost-session", args.tick_cost_session),
            ("--tick-cost-window", args.tick_cost_window),
            ("--tick-cost-start-ctx", args.tick_cost_start_ctx),
            ("--tick-cost-calls", args.tick_cost_calls),
            ("--tick-cost-context-carried", args.tick_cost_context_carried),
            ("--tick-cost-first", True if args.tick_cost_first else None),
            ("--tick-cost-why", args.tick_cost_why),
            ("--tick-cost-rate", args.tick_cost_rate),
        )
        if value is not None
    ]

    # The intake pair and the lane record, each once it has been built and while the
    # entry carrying it has not landed. `refuse` reads both, so a refusal after either
    # was built can say what went nowhere -- otherwise something somebody measured is
    # dropped in silence, and `--trend`/`--model-trend` counts that tick as one that
    # recorded nothing. (#222, and #316 the same shape one field over)
    pending_intake = None
    pending_lanes = None
    pending_lane_fill = None
    pending_cleanup_override = None
    pending_cohort = None
    pending_wait_record = None
    pending_tick_cost = None

    def refuse(message):
        """Print the verdict, then what the run did not record. In that order.

        Nothing success-shaped may reach the caller ahead of a FAIL. The refused run
        used to print the intake sentence first, and a caller filtering for the metric
        read it as a record that had landed. `NOT RECORDED` is deliberately a different
        string from the `RECORDED` receipt, rather than the same sentence with a caveat
        appended: a filter that catches one must not catch the other.
        """
        _say("FAIL {}".format(message))
        if pending_intake is not None:
            # The flush is the whole ordering guarantee, and printing in the right order
            # is not. stdout is block-buffered the moment it is a pipe rather than a
            # terminal, while stderr is not, so a FAIL printed first still surfaces
            # second under `2>&1 | tee` -- which is how a transcript is read. Verified
            # against a real pipe rather than a captured buffer; capsys keeps the two
            # streams apart and cannot see this at all.
            sys.stdout.flush()
            _say("NOT RECORDED " + intake_line(pending_intake), sys.stderr)
        if pending_lanes is not None:
            sys.stdout.flush()
            _say("NOT RECORDED " + lane_models_line(pending_lanes), sys.stderr)
        if pending_lane_fill is not None:
            sys.stdout.flush()
            _say("NOT RECORDED " + lane_fill_line(pending_lane_fill), sys.stderr)
        if pending_cleanup_override is not None:
            sys.stdout.flush()
            _say(
                "NOT RECORDED " + cleanup_override_line(pending_cleanup_override),
                sys.stderr,
            )
        if pending_cohort is not None:
            sys.stdout.flush()
            _say("NOT RECORDED " + cohort_freeze_line(pending_cohort), sys.stderr)
        if pending_wait_record is not None:
            sys.stdout.flush()
            _say("NOT RECORDED " + wait_line(pending_wait_record), sys.stderr)
        if pending_tick_cost is not None:
            sys.stdout.flush()
            _say("NOT RECORDED " + tick_cost_line(pending_tick_cost), sys.stderr)
        return 1

    try:
        reading_mode = (
            args.read
            or args.last
            or args.trend
            or args.migrate
            or args.model_trend
            or args.lane_fill_trend
            or args.pending_wait
            or args.last_triage
            # `is not None`, not plain truthiness: an empty string is still a
            # value somebody passed (`--check-plugin-identity ""`), and treating
            # it as absent used to fall all the way through to the --decision
            # path with a misleading "--at is required" refusal (found by
            # review) instead of naming the flag that was actually wrong.
            or args.check_plugin_identity is not None
            or args.record_plugin_root is not None
            or args.check_plugin_root is not None
            or args.check_decline_reason is not None
        )
        if reading_mode and intake_flags:
            # Accepting and dropping them would discard a count somebody took, at exit
            # 0, with the reading mode's own output looking entirely normal.
            _say(
                "FAIL {} are only recorded with --decision; a reading mode would "
                "accept them and drop them".format(", ".join(intake_flags))
            )
            return 1
        if reading_mode and lane_flags:
            _say(
                "FAIL {} are only recorded with --decision; a reading mode would "
                "accept them and drop them".format(", ".join(lane_flags))
            )
            return 1
        if reading_mode and lane_fill_flags:
            _say(
                "FAIL {} are only recorded with --decision; a reading mode would "
                "accept them and drop them".format(", ".join(lane_fill_flags))
            )
            return 1
        if reading_mode and cleanup_override_flags:
            _say(
                "FAIL {} are only recorded with --decision; a reading mode would "
                "accept them and drop them".format(", ".join(cleanup_override_flags))
            )
            return 1
        if reading_mode and cohort_flags:
            _say(
                "FAIL {} are only recorded with --decision; a reading mode would "
                "accept them and drop them".format(", ".join(cohort_flags))
            )
            return 1
        if reading_mode and wait_flags:
            # No carve-out for --pending-wait, unlike a plain reading mode with nothing
            # else set: --pending-wait itself sets none of wait_flags, so this only
            # fires when it is combined with a recording/checking flag -- which used to
            # succeed silently, printing the pending wait (or "no pending wait") while
            # dropping --check-wait/--wait-cleared-by/etc with no FAIL and no receipt.
            _say(
                "FAIL {} are only recorded with --decision; a reading mode would "
                "accept them and drop them".format(", ".join(wait_flags))
            )
            return 1
        if reading_mode and plugin_identity_flags:
            # --plugin-identity is only ever recorded with --decision, same rule as
            # every other X_flags list -- including against --check-plugin-identity
            # itself, which is a reading mode too (a value, not store_true, so it
            # needed adding to `reading_mode` above rather than being caught for
            # free by the generic check).
            _say(
                "FAIL {} are only recorded with --decision; a reading mode would "
                "accept them and drop them".format(", ".join(plugin_identity_flags))
            )
            return 1
        if reading_mode and triage_flags:
            _say(
                "FAIL {} are only recorded with --decision; a reading mode would "
                "accept them and drop them".format(", ".join(triage_flags))
            )
            return 1
        if reading_mode and tick_cost_flags:
            _say(
                "FAIL {} are only recorded with --decision; a reading mode would "
                "accept them and drop them".format(", ".join(tick_cost_flags))
            )
            return 1
        if (
            args.plugin_identity_route is not None
            and args.check_plugin_identity is None
            and args.plugin_identity is None
        ):
            return refuse(
                "--plugin-identity-route needs --check-plugin-identity (describing "
                "this tick's own reading) or --decision --plugin-identity (recording "
                "it onto the entry) -- it names nothing on its own"
            )
        if args.check_plugin_identity is not None:
            found_entry, prior, prior_route = _last_plugin_identity(args.path)
            record = plugin_identity_check(
                args.check_plugin_identity,
                prior,
                current_route=args.plugin_identity_route,
                prior_route=prior_route,
            )
            _say(plugin_identity_line(record), sys.stderr)
            print(json.dumps(record, indent=2))
            return 0
        if args.record_plugin_root is not None:
            record = record_plugin_root(args.path, args.record_plugin_root)
            _say(_receipt_line("RECORDED plugin root (within this tick): {}".format(record["root"])), sys.stderr)
            print(json.dumps(record, indent=2))
            return 0
        if args.check_plugin_root is not None:
            record = check_plugin_root(args.path, args.check_plugin_root)
            _say(plugin_root_line(record), sys.stderr)
            print(json.dumps(record, indent=2))
            return 0
        if args.check_decline_reason is not None:
            record = decline_reason_state(args.check_decline_reason)
            _say(decline_reason_line(record), sys.stderr)
            print(json.dumps(record, indent=2))
            return 0
        if args.pending_wait:
            found_entry, record = _last_wait(args.path)
            if found_entry is None:
                print("no pending wait")
                return 0
            if not isinstance(record, dict) or record.get("state") not in (
                WAIT_HOLDS,
                WAIT_CLEARED,
                WAIT_COULD_NOT_EVALUATE,
            ):
                # Found by audit: a malformed or unrecognised-state record used to
                # print "no pending wait", byte-identical to no wait ever having been
                # recorded -- the absence this whole file exists to guard against,
                # one branch away from the sibling `_wait_sentence`'s own explicit
                # "unrecognised wait state" arm three lines over. Branching on
                # `found_entry is None` rather than `record is None` (found by
                # audit, #436) keeps that guarantee even for a hand-authored entry
                # whose `detail.wait` key is present but literally `null`: `record`
                # is `None` there too, and checking `record` alone would silently
                # fold that case back into "nothing was ever recorded".
                return refuse(
                    "the most recently recorded wait's detail.wait is not a "
                    "recognised wait record ({!r}) -- this is not the same as no "
                    "wait ever being recorded, and must not print as one".format(
                        record
                    )
                )
            if record["state"] in (WAIT_HOLDS, WAIT_COULD_NOT_EVALUATE):
                # #443: could-not-evaluate is no measurement at all, exactly as
                # unresolved as holds -- neither is a negative measurement, so
                # `--pending-wait` answers *is anything pending* by putting both on
                # this side. They stay distinguishable because the printed record
                # itself carries a different `state` (and a `why` `holds` never
                # has), never collapsing to the same bytes -- this branch used to
                # fall to the `else` below, which is where `cleared` and no wait
                # ever having been recorded both correctly land, so a could-not-
                # evaluate wait rendered byte-identical to nothing being pending at
                # all, with `why` reaching nobody.
                print(json.dumps(record, indent=2))
            else:
                print("no pending wait")
            return 0
        if args.last_triage:
            record = last_triage(args.path)
            _say(triage_line(record), sys.stderr)
            print(json.dumps(record, indent=2))
            return 0
        if args.model_trend:
            trend = lane_model_trend(read(args.path))
            # Same three-label vocabulary as --trend, one metric over: TREND marks a
            # sum nobody asked to store, computed from a history that already exists.
            _say("TREND " + lane_models_line(trend), sys.stderr)
            print(json.dumps(trend, indent=2))
            return 0
        if args.lane_fill_trend:
            trend = lane_fill_trend(read(args.path))
            _say("TREND " + lane_fill_line(trend), sys.stderr)
            print(json.dumps(trend, indent=2))
            return 0
        if args.migrate:
            result = migrate(args.path)
            if result["state"] == MIGRATED:
                _say(
                    "OK {}: converted {} entries to the list shape; the original is at "
                    "{}".format(args.path, result["entries"], result["backup"])
                )
                return 0
            if result["state"] == ALREADY_A_LIST:
                # Not an error and not a conversion. Saying "converted" here would
                # report work that did not happen; saying FAIL would send a maintainer
                # looking for a problem that is not there.
                _say(
                    "OK {}: already the list shape, {} entries; nothing to "
                    "convert".format(args.path, result["entries"])
                )
                return 0
            _say("FAIL {}: {}".format(args.path, result["reason"]))
            return 1
        if args.read:
            print(json.dumps(read(args.path), indent=2))
            return 0
        if args.last:
            entry = last(args.path)
            print(json.dumps(entry, indent=2) if entry else "no entries yet")
            return 0
        if args.trend:
            trend = intake_trend(read(args.path))
            # The line goes to stderr and the record to stdout, so a caller piping this
            # into `jq` still gets JSON while a human still gets the sentence. The
            # sentence is the point: a caller formatting `ratio or 0` renders
            # could-not-count as zero, which is the finding it is not.
            #
            # `TREND`, because the same renderer serves two jobs and only one of them is
            # a receipt. This one is a computation over a history that already exists --
            # nothing was written by this call -- and an unlabelled sentence leaves that
            # to the reader. The three labels are the whole vocabulary: RECORDED for an
            # entry on disk, NOT RECORDED for a pair this run dropped, TREND for a sum
            # nobody asked to store. (#222)
            _say("TREND " + intake_line(trend), sys.stderr)
            print(json.dumps(trend, indent=2))
            return 0

        if not args.at:
            return refuse(
                "--at is required with --decision; the timestamp is not read from a clock"
            )
        if tick_cost_flags:
            # Built FIRST among the five pending-record types, ahead of lanes, cohort,
            # wait and intake -- found by review: a fully valid --tick-cost-* set used
            # to be built LAST, so an unrelated group's refusal (an incomplete intake
            # set, say) short-circuited the function before this block ever ran, and
            # the measured record vanished with no NOT RECORDED line at all. Building
            # it before anything else protects it the same way the lane record has
            # always been protected against intake's own "missing flags" refusal (see
            # the comment on that below) -- every tick records both, so this one must
            # not be the one silently exposed to the other four's failure modes.
            missing = [
                name
                for name in (
                    "--tick-cost-session",
                    "--tick-cost-window",
                    "--tick-cost-start-ctx",
                    "--tick-cost-calls",
                    "--tick-cost-context-carried",
                )
                if name not in tick_cost_flags
            ]
            if missing:
                # Each of start-ctx/calls/context-carried may legitimately be
                # 'unknown' -- but the flag still has to be PASSED for that, the same
                # rule --filings/--merged-prs already follow. A flag simply absent is
                # not the same claim as one spelling out 'unknown'.
                return refuse(
                    "a tick-cost record needs --tick-cost-session, --tick-cost-window, "
                    "--tick-cost-start-ctx, --tick-cost-calls and "
                    "--tick-cost-context-carried (each may be 'unknown', but not "
                    "absent); missing {}".format(", ".join(missing))
                )
            prior_floor, session_has_prior = _session_tick_cost_floor(
                args.path, args.tick_cost_session
            )
            pending_tick_cost = tick_cost(
                args.tick_cost_session,
                args.tick_cost_window,
                None if args.tick_cost_start_ctx is UNKNOWN_COUNT else args.tick_cost_start_ctx,
                None if args.tick_cost_calls is UNKNOWN_COUNT else args.tick_cost_calls,
                None
                if args.tick_cost_context_carried is UNKNOWN_COUNT
                else args.tick_cost_context_carried,
                is_first=args.tick_cost_first,
                prior_floor=prior_floor,
                session_has_prior=session_has_prior,
                why=args.tick_cost_why,
                rate=args.tick_cost_rate,
            )
        if args.lane_agent_type and args.lane is None:
            # #862: give this its own message, naming the issue(s), ahead of the
            # generic "--lane-window alone" refusal below -- that one never sees
            # which issue a recorded subagent_type was orphaned from.
            return refuse(
                "--lane-agent-type named issue(s) {} with no matching --lane "
                "entry -- a recorded subagent_type with no lane to attach to "
                "records nothing".format(
                    ", ".join(str(entry["issue"]) for entry in args.lane_agent_type)
                )
            )
        if args.lane_dispatch_state and args.lane is None:
            # #880: same shape as the --lane-agent-type check above, ahead of the
            # generic "--lane-window alone" refusal for the same reason.
            return refuse(
                "--lane-dispatch-state named issue(s) {} with no matching --lane "
                "entry -- a recorded dispatch state with no lane to attach to "
                "records nothing".format(
                    ", ".join(str(entry["issue"]) for entry in args.lane_dispatch_state)
                )
            )
        if args.lane is not None and args.lanes is not None:
            return refuse(
                "--lane and --lanes cannot both be given; use --lane for named lanes "
                "or --lanes none/unknown for the whole tick"
            )
        if lane_flags and args.lane is None and args.lanes is None:
            # `--lane-window`/`--lane-why` alone records nothing -- the same shape
            # `--window` alone (no `--filings`/`--merged-prs`) already gets from the
            # intake block below. Without this, an entry lands with no `lanes` key at
            # all and no receipt either way: a flag somebody passed, silently dropped.
            return refuse(
                "a lane record needs --lane or --lanes; {} alone records "
                "nothing".format(", ".join(lane_flags))
            )
        if (args.lane is not None or args.lanes is not None) and not args.lane_window:
            return refuse(
                "a lane record needs --lane-window -- what this dispatch was, in "
                "words. A mix with no window means nothing six ticks later."
            )
        # Every pending record is built before its own refusal can fire, and before
        # `--detail` is parsed -- the order is the point: a refusal raised while another
        # pending record was still unbuilt dropped something somebody had measured
        # without a line saying so, this issue's own defect one branch over (#222). The
        # lane record is built ahead of the intake "missing flags" check for exactly that
        # reason: a valid `--lane` must not go unreported just because an unrelated,
        # incomplete `--filings`/`--merged-prs`/`--window` set is refused first.
        if args.lane_agent_type:
            # #862: attach each recorded subagent_type to its own --lane entry by
            # issue number, refusing rather than silently dropping one that names an
            # issue --lane never mentioned -- an unattached agent_type is not a lane
            # record at all, and dropping it silently would be this repo's own
            # defect class one field over. `args.lane is None` is already refused
            # above, before this point, so nothing here re-checks it -- a second
            # `if not args.lane` here would be dead code (argparse's own
            # `action="append"` never produces an empty list, only `None` or a
            # populated one, and `None` already returned).
            by_issue = {}
            for entry in args.lane_agent_type:
                by_issue[entry["issue"]] = entry["agent_type"]
            known_issues = {lane["issue"] for lane in args.lane}
            unmatched = sorted(
                (str(issue) for issue in by_issue if issue not in known_issues),
                key=str,
            )
            if unmatched:
                return refuse(
                    "--lane-agent-type named issue(s) with no matching --lane "
                    "entry: {}".format(", ".join(unmatched))
                )
            for lane in args.lane:
                if lane["issue"] in by_issue:
                    lane["agent_type"] = by_issue[lane["issue"]]
        if args.lane_dispatch_state:
            # #880: same attach-by-issue shape as --lane-agent-type above, with one
            # difference -- an issue can legitimately have more than one --lane entry
            # (a dispatched entry an agent-unreachable spawn replaced), so this is a
            # FIFO queue per issue rather than a dict: the Nth --lane-dispatch-state
            # naming an issue is attached to the Nth --lane entry for that issue, in
            # the order both were given, rather than the last one silently winning.
            queues = {}
            for entry in args.lane_dispatch_state:
                queues.setdefault(entry["issue"], []).append(entry)
            known_issues = {lane["issue"] for lane in args.lane}
            unmatched = sorted(
                (str(issue) for issue in queues if issue not in known_issues), key=str
            )
            if unmatched:
                return refuse(
                    "--lane-dispatch-state named issue(s) with no matching --lane "
                    "entry: {}".format(", ".join(unmatched))
                )
            for lane in args.lane:
                queue = queues.get(lane["issue"])
                if queue:
                    entry = queue.pop(0)
                    lane["dispatch_state"] = entry["dispatch_state"]
                    if "dispatch_state_why" in entry:
                        lane["dispatch_state_why"] = entry["dispatch_state_why"]
            leftover = sorted(
                (str(issue) for issue, queue in queues.items() if queue), key=str
            )
            if leftover:
                return refuse(
                    "--lane-dispatch-state named issue(s) {} more times than they "
                    "appear in --lane -- each occurrence needs its own --lane entry "
                    "to attach to".format(", ".join(leftover))
                )
        if args.lane is not None:
            pending_lanes = lane_models(args.lane, window=args.lane_window)
        elif args.lanes == "none":
            pending_lanes = lane_models([], window=args.lane_window)
        elif args.lanes == "unknown":
            pending_lanes = lane_models(None, window=args.lane_window, why=args.lane_why)
        if args.lane_fill is not None and args.lane_fills is not None:
            return refuse(
                "--lane-fill and --lane-fills cannot both be given; use --lane-fill "
                "for named lanes or --lane-fills none/unknown for the whole tick"
            )
        if lane_fill_flags and args.lane_fill is None and args.lane_fills is None:
            return refuse(
                "a lane fill record needs --lane-fill or --lane-fills; {} alone "
                "records nothing".format(", ".join(lane_fill_flags))
            )
        if (
            args.lane_fill is not None or args.lane_fills is not None
        ) and not args.lane_fill_window:
            return refuse(
                "a lane fill record needs --lane-fill-window -- what this dispatch "
                "was, in words. A fill with no window means nothing six ticks later."
            )
        # Built here, same ordering discipline as the lane-model block above: a valid
        # --lane-fill must not go unreported just because an unrelated, incomplete set
        # is refused first (#222). lane_fill() itself raises StateError -- caught by
        # this function's own StateError handler below, which routes to refuse() --
        # for a short lane with no reason, an invalid reason or an out-of-range count:
        # the whole --decision call is refused outright, the same shape
        # --tick-cost-first already uses to refuse rather than silently writing a
        # false value.
        if args.lane_fill is not None:
            pending_lane_fill = lane_fill(args.lane_fill, window=args.lane_fill_window)
        elif args.lane_fills == "none":
            pending_lane_fill = lane_fill([], window=args.lane_fill_window)
        elif args.lane_fills == "unknown":
            pending_lane_fill = lane_fill(
                None, window=args.lane_fill_window, why=args.lane_fill_why
            )
        # #1007: cleanup_overrides() itself raises StateError on a blank worktree or
        # reason -- caught by this function's own StateError handler below, which
        # routes to refuse() the same as an invalid --lane-fill does, rather than
        # writing a half-stated override to disk.
        if args.cleanup_override is not None:
            pending_cleanup_override = cleanup_overrides(args.cleanup_override)
        if args.cohort_count:
            if not args.cohort:
                return refuse(
                    "a cohort freeze record needs --cohort -- the label being "
                    "frozen, so a count nobody can name a cohort for is not "
                    "recorded."
                )
            pending_cohort = cohort_freeze_from_pairs(
                args.cohort,
                args.cohort_count,
                why=args.cohort_why,
            )
        elif args.cohort:
            return refuse(
                "--cohort needs --cohort-count (at least two); --cohort alone "
                "records nothing."
            )
        if (args.wait_dispatch is not None or args.wait_observable is not None) and (
            args.check_wait is not None
        ):
            return refuse(
                "--wait-dispatch/--wait-observable (recording a fresh wait) and "
                "--check-wait (re-deriving the last one) cannot both be given in "
                "one call"
            )
        if args.wait_dispatch is not None or args.wait_observable is not None:
            if args.wait_dispatch is None or args.wait_observable is None:
                return refuse(
                    "a wait record needs both --wait-dispatch and --wait-observable; "
                    "either alone is a claim nothing can test"
                )
            pending_wait_record = wait(args.wait_dispatch, args.wait_observable, args.at)
        elif args.check_wait is not None:
            # `found_entry` is the sentinel, not `previous_wait` (found by audit,
            # #436): a hand-authored entry can carry a `detail.wait` key whose value
            # is literally `null`, which makes `previous_wait` itself `None` too --
            # checking `previous_wait is None` here would silently read that as "no
            # entry has ever recorded a wait", the exact absence #436 exists to close.
            found_entry, previous_wait = _last_wait(args.path)
            if found_entry is None:
                return refuse(
                    "--check-wait was given but no entry has ever recorded a wait; "
                    "there is nothing to re-derive"
                )
            if not isinstance(previous_wait, dict) or previous_wait.get("state") != WAIT_HOLDS:
                # The `{}` slot names the state actually found on disk, not the
                # required `WAIT_HOLDS` constant -- found by audit alongside #436: the
                # old message filled it with the literal `WAIT_HOLDS`, in a position
                # every reader takes as the state that was found, so a wait that had
                # already been checked `cleared` was reported as "state holds".
                found_state = (
                    previous_wait.get("state")
                    if isinstance(previous_wait, dict)
                    else previous_wait
                )
                return refuse(
                    "--check-wait was given but the most recently recorded wait "
                    "carries state {!r}, not {}; there is nothing to "
                    "re-derive".format(found_state, WAIT_HOLDS)
                )
            pending_wait_record = check_wait(
                previous_wait,
                args.check_wait,
                cleared_by=args.wait_cleared_by,
                why=args.wait_why,
            )
        elif args.wait_cleared_by is not None or args.wait_why is not None:
            return refuse(
                "--wait-cleared-by/--wait-why are only meaningful with --check-wait"
            )
        if intake_flags:
            missing = [
                name
                for name in ("--filings", "--merged-prs", "--window")
                if name not in intake_flags
            ]
            if missing:
                # Half a record is worse than none: a numerator with no denominator and
                # no window is a number nobody can read, sitting in the history looking
                # like one somebody can.
                return refuse(
                    "an intake record needs all of --filings, --merged-prs and "
                    "--window; missing {}".format(", ".join(missing))
                )
            record = intake(
                None if args.filings is UNKNOWN_COUNT else args.filings,
                None if args.merged_prs is UNKNOWN_COUNT else args.merged_prs,
                window=args.window,
                why=args.intake_why,
            )
            pending_intake = record
        detail = json.loads(args.detail) if args.detail else None
        if intake_flags:
            if detail is None:
                detail = {}
            if not isinstance(detail, dict):
                return refuse(
                    "--detail must be a JSON object when an intake record is attached"
                )
            if "intake" in detail:
                return refuse(
                    "--detail already carries an 'intake' key; pass one or the other"
                )
            detail["intake"] = record
        if pending_lanes is not None:
            if detail is None:
                detail = {}
            if not isinstance(detail, dict):
                return refuse(
                    "--detail must be a JSON object when a lane record is attached"
                )
            if "lanes" in detail:
                return refuse(
                    "--detail already carries a 'lanes' key; pass one or the other"
                )
            detail["lanes"] = pending_lanes
        if pending_lane_fill is not None:
            if detail is None:
                detail = {}
            if not isinstance(detail, dict):
                return refuse(
                    "--detail must be a JSON object when a lane fill record is "
                    "attached"
                )
            if "lane_fill" in detail:
                return refuse(
                    "--detail already carries a 'lane_fill' key; pass one or the "
                    "other"
                )
            detail["lane_fill"] = pending_lane_fill
        if pending_cleanup_override is not None:
            if detail is None:
                detail = {}
            if not isinstance(detail, dict):
                return refuse(
                    "--detail must be a JSON object when a cleanup override "
                    "record is attached"
                )
            if "cleanup_override" in detail:
                return refuse(
                    "--detail already carries a 'cleanup_override' key; pass "
                    "one or the other"
                )
            detail["cleanup_override"] = pending_cleanup_override
        if pending_cohort is not None:
            if detail is None:
                detail = {}
            if not isinstance(detail, dict):
                return refuse(
                    "--detail must be a JSON object when a cohort freeze record "
                    "is attached"
                )
            if "cohort_freeze" in detail:
                return refuse(
                    "--detail already carries a 'cohort_freeze' key; pass one or "
                    "the other"
                )
            detail["cohort_freeze"] = pending_cohort
        if pending_wait_record is not None:
            if detail is None:
                detail = {}
            if not isinstance(detail, dict):
                return refuse(
                    "--detail must be a JSON object when a wait record is attached"
                )
            if "wait" in detail:
                return refuse(
                    "--detail already carries a 'wait' key; pass one or the other"
                )
            detail["wait"] = pending_wait_record
        if args.plugin_identity is not None:
            if detail is None:
                detail = {}
            if not isinstance(detail, dict):
                return refuse(
                    "--detail must be a JSON object when a plugin identity is "
                    "attached"
                )
            if "plugin_identity" in detail:
                return refuse(
                    "--detail already carries a 'plugin_identity' key; pass one "
                    "or the other"
                )
            detail["plugin_identity"] = args.plugin_identity
            if args.plugin_identity_route is not None:
                if "plugin_identity_route" in detail:
                    return refuse(
                        "--detail already carries a 'plugin_identity_route' key; "
                        "pass one or the other"
                    )
                detail["plugin_identity_route"] = args.plugin_identity_route
        if args.triage_recorded is not None:
            if detail is None:
                detail = {}
            if not isinstance(detail, dict):
                return refuse(
                    "--detail must be a JSON object when a triage record is attached"
                )
            if "triage" in detail:
                return refuse(
                    "--detail already carries a 'triage' key; pass one or the other"
                )
            detail["triage"] = triage_recorded(args.triage_recorded)
        if pending_tick_cost is not None:
            if detail is None:
                detail = {}
            if not isinstance(detail, dict):
                return refuse(
                    "--detail must be a JSON object when a tick-cost record is "
                    "attached"
                )
            if "tick_cost" in detail:
                return refuse(
                    "--detail already carries a 'tick_cost' key; pass one or the "
                    "other"
                )
            detail["tick_cost"] = pending_tick_cost
        entry = append(args.path, args.at, args.decision, detail=detail)
        # After the write, never before. The line is a receipt for an entry that is on
        # disk, and a receipt printed ahead of the write it receipts is one that a
        # refusal, a crash or a filtered transcript turns into a false pass. (#222)
        if pending_intake is not None:
            _say("RECORDED " + intake_line(pending_intake), sys.stderr)
        if pending_lanes is not None:
            _say("RECORDED " + lane_models_line(pending_lanes), sys.stderr)
        if pending_lane_fill is not None:
            _say("RECORDED " + lane_fill_line(pending_lane_fill), sys.stderr)
        if pending_cleanup_override is not None:
            _say(
                "RECORDED " + cleanup_override_line(pending_cleanup_override),
                sys.stderr,
            )
        if pending_cohort is not None:
            _say("RECORDED " + cohort_freeze_line(pending_cohort), sys.stderr)
        if pending_wait_record is not None:
            _say("RECORDED " + wait_line(pending_wait_record), sys.stderr)
        if args.plugin_identity is not None:
            _say(
                "RECORDED plugin identity: " + _receipt_line(args.plugin_identity),
                sys.stderr,
            )
            if args.plugin_identity_route is not None:
                _say(
                    "RECORDED plugin identity route: "
                    + _receipt_line(args.plugin_identity_route),
                    sys.stderr,
                )
        if args.triage_recorded is not None:
            _say(
                "RECORDED triage sweep at " + _receipt_line(args.triage_recorded),
                sys.stderr,
            )
        if pending_tick_cost is not None:
            _say("RECORDED " + tick_cost_line(pending_tick_cost), sys.stderr)
        print(json.dumps(entry, indent=2))
        return 0
    except StateError as exc:
        return refuse(str(exc))
    except json.JSONDecodeError as exc:
        # The exact exception `json.loads` raises, not the `ValueError` it derives from.
        # A broad `ValueError` here caught `UnicodeEncodeError` -- raised by a `print`
        # whose text the console's codepage could not hold -- and rendered it as `FAIL
        # --detail is not valid JSON` on a run carrying no `--detail` at all. A verdict
        # about the wrong flag, stated with the same confidence as a right one. `_say`
        # stops that raise happening; this stops the next unrelated `ValueError` being
        # confidently misattributed, which is the half that keeps working when somebody
        # adds a line here later.
        return refuse("--detail is not valid JSON ({})".format(exc))


if __name__ == "__main__":
    sys.exit(_main())
