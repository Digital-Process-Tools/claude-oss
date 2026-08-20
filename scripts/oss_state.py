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
import stat
import sys
import tempfile
from pathlib import Path

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
    """
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

        normalized.append(
            {"issue": issue, "model": str(model).strip(), "choice": choice, "why": lane_why}
        )

    return {"state": LANES_RECORDED, "window": window, "lanes": normalized, "why": None}


def lane_models_line(record):
    """One line a tick report can print. The state decides the sentence, not the caller.

    Handles both a single tick's record (``lanes`` is a list) and a trend summed across
    a history (``lanes`` is a count, ``counts`` carries the mix) -- the two shapes
    ``lane_models`` and ``lane_model_trend`` return, so one renderer serves both call
    sites the way ``intake_line`` does not need to.
    """
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
        if isinstance(lanes, list):
            counts = {}
            overrides = 0
            for lane in lanes:
                model = lane.get("model") if isinstance(lane, dict) else None
                if model:
                    counts[model] = counts.get(model, 0) + 1
                if isinstance(lane, dict) and lane.get("choice") == CHOICE_OVERRIDE:
                    overrides += 1
        else:
            counts = record.get("counts") or {}
            overrides = record.get("overrides") or 0
        parts = ", ".join(
            "{} {}".format(count, model) for model, count in sorted(counts.items())
        )
        mix = head + "{} ({} override{})".format(
            parts or "no lanes", overrides, "" if overrides == 1 else "s"
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
    counted = 0
    uncounted = 0
    without_record = 0

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

    # The intake pair and the lane record, each once it has been built and while the
    # entry carrying it has not landed. `refuse` reads both, so a refusal after either
    # was built can say what went nowhere -- otherwise something somebody measured is
    # dropped in silence, and `--trend`/`--model-trend` counts that tick as one that
    # recorded nothing. (#222, and #316 the same shape one field over)
    pending_intake = None
    pending_lanes = None

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
        return 1

    try:
        reading_mode = args.read or args.last or args.trend or args.migrate or args.model_trend
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
        if args.model_trend:
            trend = lane_model_trend(read(args.path))
            # Same three-label vocabulary as --trend, one metric over: TREND marks a
            # sum nobody asked to store, computed from a history that already exists.
            _say("TREND " + lane_models_line(trend), sys.stderr)
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
        if args.lane is not None:
            pending_lanes = lane_models(args.lane, window=args.lane_window)
        elif args.lanes == "none":
            pending_lanes = lane_models([], window=args.lane_window)
        elif args.lanes == "unknown":
            pending_lanes = lane_models(None, window=args.lane_window, why=args.lane_why)
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
        entry = append(args.path, args.at, args.decision, detail=detail)
        # After the write, never before. The line is a receipt for an entry that is on
        # disk, and a receipt printed ahead of the write it receipts is one that a
        # refusal, a crash or a filtered transcript turns into a false pass. (#222)
        if pending_intake is not None:
            _say("RECORDED " + intake_line(pending_intake), sys.stderr)
        if pending_lanes is not None:
            _say("RECORDED " + lane_models_line(pending_lanes), sys.stderr)
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
