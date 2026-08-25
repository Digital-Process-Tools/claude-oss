"""A census of the places this repository states a fact whose authority is somewhere
else (#544).

`CLAUDE.md` states the rule, from #180: a transcription is a claim about something
outside the repo, so it is measured against that authority in a test, not asserted in
a comment. It was written as the lesson of one instance. Nothing enumerated the
instances, so a *new* site was never compared to the rule -- and the rule fired only
for the one site whose story happened to be written down. #533 is what that costs:
`oss_config.watch_name_problem`'s own docstring called itself "the single statement of
what a watch channel name may be", supertool disagreed, and nothing here knew to ask.

This module does not try to *detect* a borrowed-authority site by pattern -- #173
already showed that a sweep of patterns cannot see a value that never had one, and the
same argument applies here one level up: a rule about transcriptions cannot see a
transcription nobody wrote a story about. So the census is a hand-maintained list,
``SITES``, and what this module checks by machine is narrower and honest about being
narrower: that every censused entry is still shaped correctly (``validate_sites``),
and that the symbol it names has not silently moved or vanished (``resolve_sites``) --
drift, not discovery.

Three states per site, exactly as the issue asks for, and the third is load-bearing:

- ``derived`` -- fetched from the authority at the moment it is needed, so there is no
  copy to drift.
- ``measured`` -- a copy exists and a test compares it against the authority.
- ``unmeasured`` -- a copy exists, nothing compares it, and the ``note`` field says
  why (the authority cannot be queried from a test, a dependency may not be installed,
  or the site was only just found and a fix is out of this module's own scope). An
  ``unmeasured`` entry with an empty note is indistinguishable from a site nobody
  classified, which is exactly the fourth state the issue says must not exist -- so it
  is refused, not merely discouraged.

Python 3.9 compatible: no match statements, no ``X | Y`` annotations.
"""

import importlib
import sys

STATE_DERIVED = "derived"
STATE_MEASURED = "measured"
STATE_UNMEASURED = "unmeasured"
STATES = (STATE_DERIVED, STATE_MEASURED, STATE_UNMEASURED)

_REQUIRED_FIELDS = ("id", "module", "symbol", "claim", "authority", "state", "note")


# The census. Four sites were named as "the start of the census rather than the
# census" when #544 was filed; two of those were already resolved by the time this
# module was written (watch-name by #533/#545, batch-hint-roster by #537), and are
# recorded here in their resolved state rather than re-litigated. The other two grew
# this census by two more: `statusline`'s Checks-API vocabulary and
# `report_schema`'s closing-keyword syntax, found by reading every module-level
# constant in `scripts/` for one that states a fact about a system outside this
# repository (git, GitHub, supertool) rather than a decision this repository made on
# its own -- `_LABEL_PAGE` in `scaffold.py` and the POSIX-variable pattern in
# `doctor_check_statusline.py` were read and left out for the same reason: neither
# transcribes an authority that could disagree with it. `_LABEL_PAGE` is a page size
# this repository chose for its own `gh` calls, not a cap `gh` imposes; the
# POSIX-variable pattern *is* POSIX variable syntax by definition and cannot drift
# out from under its own recognition of it.
SITES = (
    {
        "id": "watch-name",
        "module": "oss_config",
        "symbol": "watch_name_problem / watch_channel_name",
        "claim": "what a watch channel name may be, safe to export as a path "
        "component",
        "authority": "supertool's own accepted-name rule (length, first character), "
        "which is a fact about the installed dependency and not about this "
        "repository",
        "state": STATE_DERIVED,
        "note": "#533 was a name this function cleared that supertool refused, "
        "because an earlier docstring claimed to be the single statement of what a "
        "watch channel name may be, full stop. #545 fixed the actual gap: "
        "doctor.check_watch_channel and bin/oss-workspace now ask the installed "
        "supertool at run time (_consumer_watch_name_verdict) whether it will "
        "accept the derived name, rather than a second static copy of its rule. "
        "This module's own docstring now narrows the claim to what it can argue "
        "on its own.",
    },
    {
        "id": "batch-hint-roster",
        "module": "batch_hint",
        "symbol": "roster",
        "claim": "which supertool ops are read-only, mutating, or external",
        "authority": "supertool 'ops:roster'",
        "state": STATE_DERIVED,
        "note": "#537: was a hand-copied, dated snapshot of the roster's own "
        "output; now called live (memoized in-process, then cached to disk with a "
        "TTL) rather than asserted in a comment.",
    },
    {
        "id": "ref-name",
        "module": "oss_config",
        "symbol": "_REF_FORBIDDEN",
        "claim": "what characters a git ref name (a branch name written into a "
        "generated CLAUDE.md) may not contain",
        "authority": "git check-ref-format",
        "state": STATE_MEASURED,
        "note": "#180: tests/test_claude_md_injection.py runs the real "
        "`git check-ref-format` against a fixture of names and compares the "
        "verdicts, rather than asserting the transcription is correct.",
    },
    {
        "id": "github-notes-limit",
        "module": "release_publish",
        "symbol": "GITHUB_NOTES_LIMIT",
        "claim": "the maximum length, in characters, of a GitHub Release body over "
        "the REST API",
        "authority": "GitHub's REST API",
        "state": STATE_UNMEASURED,
        "note": "Declared with a citation and a date: observed cutting "
        "claude-supertool v0.49.0 on 2026-08-22 (HTTP 422, 'body is too long "
        "(maximum is 125000 characters)'). Nothing re-derives or measures it "
        "against a live call -- there is no read-only way to ask the API for this "
        "number without hitting the limit itself. Held by PR #552 at the time "
        "this census was written; not edited by this lane.",
    },
    {
        "id": "checks-rollup",
        "module": "statusline",
        "symbol": "ROLLUP_RED / ROLLUP_RUNNING / ROLLUP_GREEN",
        "claim": "the vocabulary GitHub's Checks API uses for a check run's "
        "`status` and `conclusion`",
        "authority": "GitHub's Checks API",
        "state": STATE_UNMEASURED,
        "note": "Found by this census (#544); no test compares this to GitHub's "
        "documented enum, and no reason or date is recorded beside the constants "
        "the way GITHUB_NOTES_LIMIT carries one. The design fails safe -- an "
        "unrecognised value falls to 'unknown' rather than 'green' (see "
        "rollup_state's own docstring) -- so a new GitHub conclusion would read as "
        "unknown, not as a false pass, but the vocabulary itself is still an "
        "unmeasured transcription. statusline.py is held by PR #552; not edited "
        "by this lane. Needs a follow-up issue.",
    },
    {
        "id": "closing-keyword",
        "module": "report_schema",
        "symbol": "_CLOSING_KEYWORD",
        "claim": "the words GitHub honours in a pull request body to auto-close an "
        "issue on merge (close/closes/closed, fix/fixes/fixed, "
        "resolve/resolves/resolved)",
        "authority": "GitHub's own closing-keyword syntax",
        "state": STATE_UNMEASURED,
        "note": "Found by this census (#544). Observed 2026-08-25 (#556): PR #554's "
        "body disclaimed closing #241 in prose and GitHub closed it anyway on "
        "merge, because a forge matches a closing keyword by its position relative "
        "to the reference, not by sentence meaning. Both call sites -- _binds and "
        "_ANY_CLOSING_REFERENCE -- are equally positional, so they agree with the "
        "forge in the negated case too, in both directions (see the comment beside "
        "_CLOSING_KEYWORD and tests/test_pr_body_closing_reference_274.py). This "
        "constant is used only as an absence detector, never to decide what a body "
        "will close, which is what makes the negation case harmless rather than a "
        "false negative. What remains unmeasured is the word list itself -- no "
        "test compares (close/closes/closed, fix/fixes/fixed, "
        "resolve/resolves/resolved) against GitHub's documented syntax, and there "
        "is no read-only way to query that syntax the way GITHUB_NOTES_LIMIT's own "
        "limit cannot be re-derived either.",
    },
)


class CensusError(ValueError):
    """The census itself, not a single site, is malformed."""


def validate_sites(sites):
    """Shape and state problems in ``sites``, as a list of strings -- empty if none.

    Checked here rather than raised, for the same reason every other survey in this
    plugin returns a list: a caller printing a census wants every problem in one
    pass, not the first one an exception happened to hit.
    """
    problems = []
    for position, site in enumerate(sites):
        label = site.get("id", "site {}".format(position)) if isinstance(site, dict) else "site {}".format(position)
        if not isinstance(site, dict):
            problems.append("{}: not a mapping ({!r})".format(label, site))
            continue
        missing = [field for field in _REQUIRED_FIELDS if field not in site]
        if missing:
            problems.append("{}: missing field(s) {}".format(label, ", ".join(missing)))
            continue
        state = site["state"]
        if state not in STATES:
            problems.append(
                "{}: state {!r} is not one of {} -- an unrecognised state is the "
                "fourth state #544 says must not exist".format(label, state, STATES)
            )
            continue
        if state == STATE_UNMEASURED and not str(site.get("note") or "").strip():
            problems.append(
                "{}: state is 'unmeasured' but note is empty -- 'declared "
                "unmeasurable' needs the declaration, not just the word".format(label)
            )
        for field in ("module", "symbol", "claim", "authority"):
            if not str(site.get(field) or "").strip():
                problems.append("{}: {} is empty".format(label, field))
    return problems


def resolve_sites(sites):
    """Drift problems in ``sites``, as a list of strings -- empty if none.

    A censused symbol that moved or vanished without its census entry updating is
    the failure this function exists to catch: the census is only honest while it
    still points at something real. This imports each named module fresh (no
    execution of anything beyond module load) and checks every symbol named in
    ``symbol`` -- ``"A / B"`` means both ``A`` and ``B`` must resolve.
    """
    problems = []
    for site in sites:
        label = site.get("id", "?") if isinstance(site, dict) else "?"
        module_name = site.get("module") if isinstance(site, dict) else None
        symbol_field = site.get("symbol") if isinstance(site, dict) else None
        if not module_name or not symbol_field:
            # validate_sites already reports this shape problem; resolving a site
            # with no module or symbol would be asserting against nothing.
            continue
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            problems.append(
                "{}: module {!r} could not be imported ({})".format(
                    label, module_name, exc
                )
            )
            continue
        for name in [part.strip() for part in str(symbol_field).split("/")]:
            if not name:
                continue
            if not hasattr(module, name):
                problems.append(
                    "{}: {}.{} not found -- the census entry has drifted from the "
                    "code it describes".format(label, module_name, name)
                )
    return problems


def render(sites):
    """One line per site, clean or not -- #544's own constraint: a site found clean
    is reported as loudly as one found wanting, so a census that only lists problems
    cannot be mistaken for one that looked at everything.
    """
    lines = []
    drifted = set()
    for problem in resolve_sites(sites):
        # The drift message opens with "<id>: ", which is also how each site's own
        # line opens below -- reuse that prefix to mark the matching line rather
        # than re-deriving the id from the problem text a second way.
        prefix = problem.split(":", 1)[0]
        drifted.add(prefix)

    for site in sites:
        if not isinstance(site, dict):
            lines.append("? -- not a mapping ({!r})".format(site))
            continue
        site_id = site.get("id", "?")
        state = site.get("state", "?")
        module_name = site.get("module", "?")
        symbol = site.get("symbol", "?")
        if site_id in drifted:
            lines.append(
                "{} [DRIFT] {} -- {}.{} no longer resolves; the census entry is "
                "stale".format(site_id, state, module_name, symbol)
            )
            continue
        note = " -- {}".format(site["note"]) if state == STATE_UNMEASURED and site.get("note") else ""
        lines.append(
            "{} [{}] {}.{}{}".format(site_id, state, module_name, symbol, note)
        )
    return lines


def _main(argv=None):
    """CLI: print the census, one line per site, and exit non-zero on drift.

    Shape problems (``validate_sites``) are a bug in this module's own data and are
    printed too, ahead of the render, rather than raised -- a maintainer running this
    from a shell should see everything wrong in one pass.
    """
    argv = sys.argv[1:] if argv is None else argv
    exit_code = 0

    shape_problems = validate_sites(SITES)
    for problem in shape_problems:
        sys.stderr.write("CENSUS SHAPE: {}\n".format(problem))
    if shape_problems:
        exit_code = 1

    for line in render(SITES):
        print(line)

    if resolve_sites(SITES):
        exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(_main())
