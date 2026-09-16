#!/usr/bin/env python3
"""Position-weighted delegation cost accounting -- #1595.

Every turn re-sends the whole conversation as input, so the price of a
piece of work is the context depth it sits at, integrated over the turns
it takes. Billed input over a stretch from context ``A`` to context ``B``,
with ``T`` tokens added per turn:

    input_tokens = (B**2 - A**2) / (2*T)

``T`` cancels in any ratio, which is what makes every function below usable
without knowing a session's real per-turn growth rate.

## Three questions (#1595's own framing)

1. **What did this session actually pay?** ``per_turn_records`` and
   ``session_actual_cost`` read the real ``cache_read_input_tokens`` /
   ``cache_creation_input_tokens`` / ``input_tokens`` per assistant turn
   from a transcript and cost each one at what it actually paid -- no
   model needed, because the transcript already carries the real deltas.
2. **What did one delegation save, or cost?** ``delegation_cost`` compares
   the fresh agent's own quadratic cost (brief, then work, from an empty
   context) against the counterfactual of doing the same work inline at
   the orchestrator's own context.
3. **What is the break-even right now?** ``break_even_context`` /
   ``should_delegate`` -- the work has not happened yet, so this is where
   the model (not a transcript) is the only source.

``block_multiplier`` / ``multiplier_table`` / ``cached_multiplier_table``
answer the shape question the issue opens with: how much more expensive is
the nth 100K-token block than the first, uncached and with prompt caching's
read/write price split folded in.

## Three states, never two

``session_actual_cost`` and ``per_turn_records`` follow the same convention
as ``loop_cost_report.py``: ``measured`` (records exist after ``since``),
``nothing-in-window`` (the file was read, nothing qualified), and
``could-not-read`` (the file could not be opened at all). A window nobody
ran anything in and a window this script could not see must never render
the same way.

## Cache-miss detection

The cache misses on TTL expiry, on any edit to the prefix, and on a model
switch. A healthy turn past the first reads a large, already-cached prefix
and writes only what is new; a miss reads little or nothing and writes
something comparable to the whole prefix instead. ``detect_cache_misses``
uses the ratio the observation actually describes: on any turn after the
first, how much of the *previous* turn's total got read back from cache.
Comparing a turn's own write against its own read (an earlier version of
this rule) false-positives on an ordinary turn that legitimately reads a
large new tool result while the cache is still small -- a large write is
not itself a miss; a small read of what should already be cached is
(#1595 review).

## Open scope (#1595's own open question)

The issue asks whether this measurement belongs here or as a generic
supertool op beside ``claude-log-cost``, since the per-turn read
(``per_turn_records``, ``session_actual_cost``) is generic while the
delegation accounting (``delegation_cost``, ``break_even_context``) is
specific to this loop. Both the generic per-turn reader and the
loop-specific calculator are built here; what is **not** attempted is
joining ``per_turn_records`` automatically across a whole session's worth
of spawned-agent transcripts -- matching a subagent's start to the
parent's context at spawn time, the fully automatic form of question 2.
``delegation_cost`` is a calculator for one delegation whose brief and
work sizes are already known, not an automatic walk of a session's
transcript tree.

``per_turn_records``'s ``since`` filter is a raw string comparison against
each record's own ISO-8601 timestamp, not a parsed datetime comparison
like ``loop_cost_report.parse_since`` uses. This is correct as long as
every transcript timestamp is `Z`-suffixed UTC, where lexicographic order
matches chronological order (true of every transcript observed in this
repo) -- it is not correct against a non-`Z` offset or mixed precision,
which nothing in this ecosystem currently produces.
"""

import argparse
import json

DEFAULT_CACHED_WRITE_PREMIUM = 1.15  # #1595 comment: 150K uncached -> ~173K cached

STATE_MEASURED = "measured"
STATE_NOTHING_IN_WINDOW = "nothing-in-window"
STATE_COULD_NOT_READ = "could-not-read"


# ---------------------------------------------------------------- break-even


def break_even_context(
    work, brief, cached=False, cached_premium=DEFAULT_CACHED_WRITE_PREMIUM
):
    """The orchestrator context above which delegating ``work`` pays off.

    Delegating wins when ``(brief+work)**2 < (A+work)**2 - A**2`` (#1595),
    which solves to ``A > [(brief+work)**2 - work**2] / (2*work)``.

    ``cached`` is the **exact algebraic dual of ``delegation_cost``'s own
    cached branch** -- solving ``inline_cost(A) == delegated_cost`` for
    ``A`` when ``delegated_cost = cached_premium * (brief+work)**2`` gives
    ``A = [cached_premium*(brief+work)**2 - work**2] / (2*work)``. This
    keeps the two functions self-consistent: ``delegation_cost(threshold,
    brief, work, cached=True)["saved"]`` is 0 at the returned threshold, the
    same guarantee the uncached path already gives. An earlier version of
    this function instead scaled the *uncached* threshold by
    ``cached_premium`` directly, which is not this dual and disagreed with
    ``delegation_cost`` by a wide margin near the threshold (#1595 review).

    ``cached_premium`` is coarse by construction: it applies one flat
    multiplier to the whole delegated cost, where the issue's own comment
    derives a more granular model (the write premium applies only to the
    brief's own tokens, and amortises further across fan-out). For
    work=100K, brief=100K the comment's own worked number is ~173K; this
    exact dual lands at 180K for the same inputs -- both are real numbers
    for their own model, not the same model, and neither should be read as
    more than an order-of-magnitude adjustment.
    """
    if work <= 0:
        raise ValueError("work must be > 0")
    if brief < 0:
        raise ValueError("brief must be >= 0")
    if cached:
        return (cached_premium * (brief + work) ** 2 - work**2) / (2 * work)
    return ((brief + work) ** 2 - work**2) / (2 * work)


def should_delegate(
    current_context,
    work,
    brief,
    cached=False,
    cached_premium=DEFAULT_CACHED_WRITE_PREMIUM,
):
    """Whether ``current_context`` is already past this delegation's break-even."""
    threshold = break_even_context(
        work, brief, cached=cached, cached_premium=cached_premium
    )
    return current_context > threshold


def delegation_cost(
    orchestrator_context,
    brief,
    work,
    cached=False,
    cached_premium=DEFAULT_CACHED_WRITE_PREMIUM,
):
    """One delegation's cost comparison -- #1595 Q2.

    ``inline_cost`` is the counterfactual of doing ``work`` more tokens of
    it inline, from the orchestrator's current context. ``delegated_cost``
    is the fresh agent's own cost of reaching ``brief + work`` starting
    from an empty context (the whole agent session, brief included).
    ``saved`` is positive when delegating was cheaper.
    """
    inline_cost = (orchestrator_context + work) ** 2 - orchestrator_context**2
    delegated_cost = (brief + work) ** 2
    if cached:
        delegated_cost *= cached_premium
    return {
        "inline_cost": inline_cost,
        "delegated_cost": delegated_cost,
        "saved": inline_cost - delegated_cost,
    }


# -------------------------------------------------------------- multipliers


def block_multiplier(n):
    """The nth 100K-token block's uncached marginal cost, relative to the first.

    #1595: "The nth block of 100K costs (2n-1) times the first."
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    return 2 * n - 1


def multiplier_table(total_tokens, block=100_000):
    """``[(stretch_label, multiplier), ...]`` over ``0..total_tokens`` in ``block`` steps."""
    if block <= 0:
        raise ValueError("block must be > 0")
    rows = []
    n = 1
    start = 0
    while start < total_tokens:
        end = start + block
        rows.append(("{}-{}".format(start, end), block_multiplier(n)))
        start = end
        n += 1
    return rows


def cached_multiplier_table(
    total_tokens, block=100_000, turn_tokens=2_000, write_premium=12.5
):
    """Approximate cache-on marginal multiplier per block (#1595 comment's model).

    Read tokens in block ``n`` grow as ``(2n-1) * block**2 / (2*turn_tokens)``
    (the average context over the block, times the number of turns in it);
    write tokens are flat at ``block`` per block (one new-token write per
    turn, ``turn_tokens`` each, summing to ``block`` over the block).
    ``write_premium`` is the cache write price as a multiple of the read
    price (12.5x measured for Opus 5, #1595 comment). This is an
    approximation of the comment's own worked table, not an exact
    reproduction of it -- the comment's own numbers carry edge effects
    from where in a block a turn actually lands.
    """
    if turn_tokens <= 0:
        raise ValueError("turn_tokens must be > 0")
    if block <= 0:
        raise ValueError("block must be > 0")
    rows = []
    n = 1
    start = 0
    first_cost = None
    while start < total_tokens:
        end = start + block
        read_tokens = block_multiplier(n) * (block**2) / (2 * turn_tokens)
        write_tokens = block
        cost = read_tokens + write_tokens * write_premium
        if first_cost is None:
            first_cost = cost
        rows.append(("{}-{}".format(start, end), cost / first_cost))
        start = end
        n += 1
    return rows


# -------------------------------------------------------------- per-turn read


def _usage_int(usage, key):
    value = usage.get(key, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _record_time(record):
    ts = record.get("timestamp")
    return ts if isinstance(ts, str) else None


def per_turn_records(path, since=None):
    """One transcript's per-turn usage, in order: ``(records, malformed)``.

    Mirrors ``loop_cost_report.read_transcript``'s field reads but keeps
    every assistant turn separate instead of folding it into one total --
    the position axis #1595 asks for is lost the moment turns are summed.
    A transcript that cannot be opened returns ``(None, [(0, why)])``.
    """
    records = []
    malformed = []
    try:
        handle = open(str(path), "r", encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, [(0, "could not open: {}".format(exc))]
    with handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError as exc:
                malformed.append((number, "not JSON: {}".format(exc)))
                continue
            if not isinstance(record, dict):
                malformed.append((number, "not a JSON object"))
                continue
            if record.get("type") != "assistant":
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                malformed.append((number, "assistant record has no message object"))
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                malformed.append((number, "assistant record has no usage object"))
                continue
            when = _record_time(record)
            if since is not None and (when is None or when < since):
                continue
            cache_read = _usage_int(usage, "cache_read_input_tokens")
            cache_creation = _usage_int(usage, "cache_creation_input_tokens")
            inp = _usage_int(usage, "input_tokens")
            out = _usage_int(usage, "output_tokens")
            records.append(
                {
                    "turn": len(records),
                    "timestamp": when,
                    "cache_read": cache_read,
                    "cache_creation": cache_creation,
                    "input": inp,
                    "output": out,
                    "context": cache_read + cache_creation + inp,
                }
            )
    return records, malformed


def detect_cache_misses(records, miss_ratio=0.5):
    """Turn indices past the first where the prefix was rewritten, not reused.

    See the module docstring's "Cache-miss detection" section for the rule.
    A turn is flagged when its own ``cache_read`` is less than
    ``miss_ratio`` of the *previous* turn's total context -- i.e. the
    previous turn's content should mostly have come back as a cache read,
    and did not. Comparing a turn's own write against its own read instead
    (an earlier version of this rule) flags an ordinary turn that reads a
    large new tool result while the cache is still small, even though
    nothing was invalidated; this ratio does not, since a legitimately
    large write does not by itself lower how much of the *prior* content
    got read back.
    """
    misses = []
    prior_total = None
    for record in records:
        total = record["cache_read"] + record["cache_creation"] + record.get("input", 0)
        if record["turn"] > 0 and prior_total:
            if record["cache_read"] < miss_ratio * prior_total:
                misses.append(record["turn"])
        prior_total = total
    return misses


def session_actual_cost(path, price_read, price_write, price_input, since=None):
    """What this transcript really paid, per turn and summed -- #1595 Q1.

    Prices are dollars per token, supplied by the caller (#1595: "Per-token
    prices belong in config. They drift."). Three states, never two: see
    the module docstring.
    """
    records, malformed = per_turn_records(path, since=since)
    if records is None:
        return {
            "state": STATE_COULD_NOT_READ,
            "why": malformed[0][1],
            "malformed": malformed,
        }
    if not records:
        return {"state": STATE_NOTHING_IN_WINDOW, "malformed": malformed}
    turns = []
    total = 0.0
    for record in records:
        cost = (
            record["cache_read"] * price_read
            + record["cache_creation"] * price_write
            + record["input"] * price_input
        )
        turn = dict(record)
        turn["cost"] = cost
        turns.append(turn)
        total += cost
    return {
        "state": STATE_MEASURED,
        "turns": turns,
        "total_cost": total,
        "cache_misses": detect_cache_misses(records),
        "malformed": malformed,
    }


# ------------------------------------------------------------------- CLI


def _render_break_even(args):
    threshold = break_even_context(args.work, args.brief, cached=args.cached)
    lines = ["break-even context: {:.0f}".format(threshold)]
    if args.context is not None:
        delegate = args.context > threshold
        lines.append(
            "current context {:.0f} -> {}".format(
                args.context, "DELEGATE" if delegate else "keep inline"
            )
        )
    return "\n".join(lines)


def _render_table(args):
    rows = multiplier_table(args.total, block=args.block)
    lines = ["{:<20} {:>8}".format("stretch", "multiplier")]
    for stretch, mult in rows:
        lines.append("{:<20} {:>7}x".format(stretch, mult))
    return "\n".join(lines)


def _render_session(args):
    result = session_actual_cost(
        args.transcript,
        args.price_read,
        args.price_write,
        args.price_input,
        since=args.since,
    )
    if args.json:
        return json.dumps(result, indent=2, sort_keys=True, default=str)
    lines = ["STATE: {}".format(result["state"])]
    if result["state"] != STATE_MEASURED:
        return "\n".join(lines)
    lines.append(
        "turns: {}  total cost: ${:.2f}".format(
            len(result["turns"]), result["total_cost"]
        )
    )
    if result["cache_misses"]:
        lines.append(
            "cache misses at turns: {}".format(
                ", ".join(str(t) for t in result["cache_misses"])
            )
        )
    else:
        lines.append("no cache misses detected")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Position-weighted delegation cost accounting (#1595)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_be = sub.add_parser(
        "break-even", help="the context above which delegating this job pays off"
    )
    p_be.add_argument("--work", type=float, required=True)
    p_be.add_argument("--brief", type=float, required=True)
    p_be.add_argument("--context", type=float, default=None)
    p_be.add_argument("--cached", action="store_true")

    p_table = sub.add_parser("table", help="marginal cost multiplier by 100K block")
    p_table.add_argument("--total", type=float, required=True)
    p_table.add_argument("--block", type=float, default=100_000)

    p_session = sub.add_parser("session", help="a transcript's real per-turn spend")
    p_session.add_argument("transcript")
    p_session.add_argument("--price-read", type=float, required=True)
    p_session.add_argument("--price-write", type=float, required=True)
    p_session.add_argument("--price-input", type=float, required=True)
    p_session.add_argument("--since", default=None)
    p_session.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "break-even":
        print(_render_break_even(args))
    elif args.cmd == "table":
        print(_render_table(args))
    elif args.cmd == "session":
        print(_render_session(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
