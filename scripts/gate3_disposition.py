#!/usr/bin/env python3
"""Gate 3's own disposition -- computed, not re-derived from prose -- #1043.

`skills/manager/phases/release.md` and `commands/release.md` both already say:
round-one `findings` stop the tag, full stop; the round-two carry-forward rule
(a non-blocking finding may ship, filed against the next milestone) applies
only to round two; and a finding in a row the ranking table marks blocking
stops the tag in *either* round. That prose is correct. It was still
misread: a releaser tagged and published `Digital-Process-Tools/claude-
jit-context` v0.8.0 over a round-one `findings` verdict, reasoning "no
blocking finding, so nothing was on the release's critical path" -- which
is round two's own rule, applied one round early. A round-one `findings`
verdict rendered indistinguishable from `clean`, which is this repository's
own defect class reached through its own release gate.

This module does not replace the prose or the auditor's judgement about
what a finding *is* -- classifying it, ranking it, and deciding whether a
row is blocking all stay exactly where they are, in
`agents/release-auditor.md` and the ranking table it reads from. What this
closes is the one step after that: given the round number, the auditor's
own verdict word, and whether any finding in this round sits in a blocking
row, what happens to the tag. That step was pure human judgement under
narrative pressure at the point it was gotten wrong, and this makes it a
function with tests instead.

## The rule, as a table

  round  verdict         has_blocking  disposition
  -----  --------------  ------------  --------------------------
  any    could-not-run   n/a           stop-tag
  any    clean           n/a           proceed
  1      findings        n/a           stop-tag    (unconditional --
                                                     round one never
                                                     carries forward)
  2      findings        False         carry-forward-and-proceed
  2      findings        True          stop-tag
  2      findings        unknown       could-not-decide

`has_blocking` is read for round two only. A round-one `findings` verdict
stops the tag regardless of whether anything in it blocks, because round
one's whole job is to give the maintainer a chance to fix before round two
runs -- carrying forward is a round-two act, never a round-one one.

`has_blocking` is itself three-state, not two (#1158): `True`/`False` say a
rank was established either way, and `BLOCKING_UNKNOWN` says one never was
-- the ranking table never reached the auditor, or the caller never
checked. Passing that sentinel for a round-two `findings` verdict answers
`could-not-decide` rather than being folded into `False` (non-blocking).
Silently reading "unknown" as "no" is exactly the defect class this
repository is named after: an absence produced by the tool, rendered as an
absence in the world.

Three states, not two, for the whole decision as well: an input this module
does not recognise (a verdict word outside the three the auditor's report
format defines, or a round number outside 1/2) is `could-not-decide`, not a
default of either `proceed` or `stop-tag`. Guessing which one is the safer
failure invents a policy nobody wrote down; naming the unrecognised input is
a fact.

Exit codes, because a shell reads those and never reads prose:

  0   proceed
  1   stop-tag
  2   argparse usage error (also used when `could-not-decide` is reported
      from the CLI, since a usage-shaped input problem and a decision the
      script refuses to make are the same class of caller error)
  4   carry-forward-and-proceed
"""

import argparse
import sys

DISPOSITION_PROCEED = "proceed"
DISPOSITION_STOP_TAG = "stop-tag"
DISPOSITION_CARRY_FORWARD = "carry-forward-and-proceed"
DISPOSITION_COULD_NOT_DECIDE = "could-not-decide"

_KNOWN_VERDICTS = ("clean", "findings", "could-not-run")

# The third state for `has_blocking` (#1158): `True`/`False` say a rank was
# established either way, and this sentinel says one never was -- the table
# never reached the auditor (`could not rank`), or the caller simply never
# checked. `decide()` cannot tell those two apart from the value alone, and
# does not try; both mean the same thing here, which is that "not blocking"
# was never actually established and must not be assumed.
BLOCKING_UNKNOWN = "unknown"

EXIT_PROCEED = 0
EXIT_STOP_TAG = 1
EXIT_USAGE_ERROR = 2
EXIT_CARRY_FORWARD = 4


def decide(round_number, verdict, has_blocking):
    """Return ``{"disposition": ..., "reason": ...}`` for gate 3.

    ``round_number`` is ``1`` or ``2``. ``verdict`` is the auditor's own
    verdict word (``clean`` / ``findings`` / ``could-not-run``).
    ``has_blocking`` is whether any finding in *this round* sits in a row
    the ranking table marks blocking -- ``True``, ``False``, or
    ``BLOCKING_UNKNOWN`` when that was never established. Ignored for every
    verdict except a round-two ``findings``, where it is the only thing
    that decides whether the tag may proceed -- and ``BLOCKING_UNKNOWN``
    there decides ``could-not-decide`` rather than being read as ``False``.
    """
    if round_number not in (1, 2):
        return {
            "disposition": DISPOSITION_COULD_NOT_DECIDE,
            "reason": "round {0!r} is not 1 or 2 -- gate 3 runs at most two "
            "rounds, and a round outside that range is not a state this "
            "gate has a rule for".format(round_number),
        }
    if verdict not in _KNOWN_VERDICTS:
        return {
            "disposition": DISPOSITION_COULD_NOT_DECIDE,
            "reason": "verdict {0!r} is not one of {1} -- an unrecognised "
            "verdict is not safely read as either a pass or a "
            "stop".format(verdict, _KNOWN_VERDICTS),
        }

    if verdict == "could-not-run":
        return {
            "disposition": DISPOSITION_STOP_TAG,
            "reason": "could-not-run stops the tag in either round: the "
            "audit did not complete, so there is nothing to carry forward",
        }
    if verdict == "clean":
        return {
            "disposition": DISPOSITION_PROCEED,
            "reason": "clean: the audit found nothing in round {0}".format(
                round_number
            ),
        }

    # verdict == "findings"
    if round_number == 1:
        return {
            "disposition": DISPOSITION_STOP_TAG,
            "reason": "round-one findings always stop the tag, regardless "
            "of whether any of them block: round one exists to give the "
            "maintainer a chance to fix before round two runs, and "
            "carry-forward is a round-two act, never a round-one one",
        }
    if has_blocking == BLOCKING_UNKNOWN:
        return {
            "disposition": DISPOSITION_COULD_NOT_DECIDE,
            "reason": "has_blocking is unknown for round-two findings: "
            "whether anything in this round sits in a blocking row was "
            "never established, and an unranked or could-not-rank finding "
            "must never be read as non-blocking",
        }
    if has_blocking:
        return {
            "disposition": DISPOSITION_STOP_TAG,
            "reason": "round-two findings with a finding in a blocking row "
            "still stop the tag: the cap does not outrank the ranking",
        }
    return {
        "disposition": DISPOSITION_CARRY_FORWARD,
        "reason": "round-two findings with nothing in a blocking row may "
        "ship: file the rest against the next milestone and proceed",
    }


_EXIT_CODES = {
    DISPOSITION_PROCEED: EXIT_PROCEED,
    DISPOSITION_STOP_TAG: EXIT_STOP_TAG,
    DISPOSITION_CARRY_FORWARD: EXIT_CARRY_FORWARD,
    DISPOSITION_COULD_NOT_DECIDE: EXIT_USAGE_ERROR,
}


def _blocking_argument(text):
    folded = text.strip().lower()
    if folded in ("yes", "true", "1"):
        return True
    if folded in ("no", "false", "0"):
        return False
    if folded in ("unknown", BLOCKING_UNKNOWN):
        return BLOCKING_UNKNOWN
    raise argparse.ArgumentTypeError(
        "--blocking expects yes/no/unknown, got {0!r}".format(text)
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Compute gate 3's disposition for a release audit round, so a "
            "round-one findings verdict cannot be treated as clean (#1043)."
        )
    )
    parser.add_argument("--round", dest="round_number", type=int, required=True)
    parser.add_argument("--verdict", required=True, choices=_KNOWN_VERDICTS)
    parser.add_argument(
        "--blocking",
        type=_blocking_argument,
        required=True,
        help="yes/no/unknown -- does any finding in this round sit in a "
        "blocking row; unknown means that was never established (an "
        "unranked or could-not-rank finding), and must not be answered no "
        "on its behalf",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit JSON instead of prose"
    )
    args = parser.parse_args(argv)

    result = decide(args.round_number, args.verdict, args.blocking)

    if args.json:
        import json

        print(json.dumps(result))
    else:
        print("DISPOSITION: {0}".format(result["disposition"]))
        print("  {0}".format(result["reason"]))
    return _EXIT_CODES[result["disposition"]]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
