"""#1577: /oss:doctor said nothing about supertool validators, in any state.

Half one of #633 shipped in #684 -- three default validators in a scaffolded
`.supertool.json`. Half two -- `/oss:doctor` reporting whether the toolchain a
configured validator dispatches to actually resolves on this machine -- was
tracked in the same issue and never landed; #1577 reopened it after #633 was
closed anyway with that half still undone.

This is the fold: relay supertool's own `doctor:probe` -- which already
answers `resolves` / `absent` / `could not tell` per configured validator,
never a `shutil.which` sweep -- into `/oss:doctor`'s own findings. `CLAUDE.md`
says a dependency-owned classification is never restated here, only relayed;
`check_dependency_diagnostics` already runs `supertool doctor` as part of its
own per-dependency relay, but keeps only the trailing `VERDICT:` line
(`_last_nonblank_line`) -- the `## Toolchain validators` section that answers
THIS question is read and discarded on every run, which is this repository's
own defect class pointed at its own diagnostic yet again: a check that never
looked and a check that found nothing render identically.

**Why a second, separate call to `doctor:probe` rather than reusing the
existing relay's output**: `check_dependency_diagnostics` runs bare `doctor`
(scope only, no binary resolution -- see `op_doctor`'s own docstring: probing
is opt-in because it costs a subprocess per adapter), and its own contract is
"relay the dependency's verdict line", not "expose its own internal report
sections" -- reparsing that relay's output would couple this check to a
format contract the other one owns. `doctor:probe` is the addressable,
documented op this issue's own body names directly.

**Not established, from the issue's own body -- resolved by reading rather
than assumed:** *"Whether `doctor:probe` is available in every supertool
version this plugin declares as a dependency."* `.claude-plugin/plugin.json`
pins no minimum version for `supertool` (`"dependencies": ["supertool", ...]`
-- name only), so an older active install may predate `doctor:probe`
entirely (`op_doctor` shipped under #1857/#1950). `op-unavailable` is that
third state, kept apart from `could-not-run` -- the call reaching a real
supertool that ran and could not answer -- exactly as `dependency_diagnostic_
state` already keeps `not-installed` apart from `could-not-run` a few
functions up, for the identical reason.

**What this check does not attempt**, both flagged "Not established" in the
issue and left for a follow-up rather than guessed at here: a `NOTICE` for a
tracked file type with no configured validator at all (needs a corpus scan
this op does not perform), and a `WARN` for a validator that resolves but
carries no rule configuration for this tree (needs a second, per-tool lookup
the issue's own second comment says still wants its own design). Building
either without a settled shape risks the exact failure this repository is
named after -- a check that reports a false absence with confidence.

Python 3.9 compatible.
"""

import re
import subprocess

#: The header `op_doctor` always prints for this section, whether or not any
#: validators are configured (#1950's own `_supertool.py:op_doctor`).
_VALIDATORS_HEADER = "## Toolchain validators"

#: `"- {configured} configured, {resolves} resolves, {absent} absent, "
#: "{unknown} could not tell, {not_applicable} not applicable"` -- the one
#: line `op_doctor` composes from its own running counters, never re-derived
#: by summing the per-row lines below it.
_SUMMARY_RE = re.compile(
    r"^- (\d+) configured, (\d+) resolves, (\d+) absent, "
    r"(\d+) could not tell, (\d+) not applicable\s*$",
    re.MULTILINE,
)


def _offending_rows(section_text):
    """Every per-validator row reporting `absent` or `could not tell`, verbatim.

    Deliberately a substring scan over the section's own `- ` rows rather than a
    strict per-shape regex: `op_doctor` renders an absent/unknown validator in one
    of several literal shapes (`_doctor_classify_probe`'s "absent" / "could not
    tell", a crashed probe, an unparseable verdict, an unreadable `git ls-files`
    scope) and this only needs to surface them, not classify which shape fired --
    that classification already happened inside supertool, and restating it here
    is exactly the restatement `CLAUDE.md` says not to do. `not applicable` rows
    never match either substring and are excluded, matching #1577's own proposal:
    a validator with no in-scope file is not a finding.
    """
    rows = []
    for line in section_text.splitlines():
        if not line.startswith("- "):
            continue
        if ": absent" in line or ": could not tell" in line:
            rows.append(line[2:].strip())
    return rows


def supertool_validator_probe_state(
    project_dir, record=None, timeout=None, run=None, which=None
):
    """Run `supertool doctor:probe` and read its own Toolchain validators section.

    Returns ``(state, detail)``:

    * ``not-installed`` -- supertool is declared but not active per the install
      record. Not a finding here: `check_dependency_diagnostics` already reports
      it, and reporting it again would double the same gap under two headings.
    * ``could-not-run`` -- supertool is active and on PATH, and the call itself
      still did not answer: no `supertool` executable found, a timeout, a nonzero
      exit for a reason other than the op not existing, or output with no
      Toolchain validators section / summary line this function can parse.
      `detail` is a message, never the raw dict `reported` carries.
    * ``op-unavailable`` -- supertool ran and answered "unknown operation:
      doctor", meaning the active install predates the `doctor`/`doctor:probe`
      op entirely (#1577's own open question, resolved as a real third state
      rather than folded into `could-not-run`, which would read as "a working
      supertool that failed" instead of "an install too old to ask").
    * ``no-validators`` -- the probe ran and reports zero validators configured.
      `detail` is a ready-to-report OK sentence, not a dict.
    * ``reported`` -- the probe ran and answered. `detail` is a dict:
      ``version``, ``configured``, ``resolves``, ``absent``, ``could_not_tell``,
      ``not_applicable``, ``offending`` (every absent/could-not-tell row,
      verbatim, from `_offending_rows`).

    `record`/`timeout`/`run`/`which` are the same dependency-injection seams
    `dependency_diagnostic_state` already threads through for its own supertool
    "op" spec -- this mirrors that call shape rather than inventing a second one,
    down to resolving the binary with `gh_which.safe_which` (#1172: a bare
    `shutil.which("supertool")` lets a same-named file planted at the inspected
    repo's own root win over a real PATH entry on Windows).
    """
    import doctor as _doctor  # lazy: see doctor-check-module-scope-import.md

    run = subprocess.run if run is None else run
    which = _doctor.gh_which.safe_which if which is None else which
    timeout = _doctor.DEPENDENCY_DIAGNOSTIC_TIMEOUT if timeout is None else timeout

    version = _doctor.active_versions(["supertool"], record).get("supertool")
    if not version:
        return "not-installed", "supertool is declared but not installed"

    exe = which("supertool")
    if exe is None:
        return "could-not-run", (
            "supertool {} is active, but no `supertool` executable is on PATH "
            "to run doctor:probe".format(version)
        )

    try:
        done = run(
            [exe, "doctor:probe"],
            cwd=str(project_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return (
            "could-not-run",
            "supertool {}'s doctor:probe timed out after {}s".format(version, timeout),
        )
    except OSError as exc:
        return "could-not-run", (
            "supertool {}'s doctor:probe could not be started ({})".format(
                version, exc.strerror or exc.__class__.__name__
            )
        )

    output = (
        done.stdout.decode("utf-8", "replace")
        if isinstance(done.stdout, bytes)
        else (done.stdout or "")
    )

    if done.returncode != 0:
        if "unknown operation: doctor" in output:
            return "op-unavailable", (
                "supertool {} does not recognise the `doctor` op -- this "
                "plugin declares no minimum version for supertool, and this "
                "install predates doctor:probe (#1857/#1950). Update "
                "supertool to get this check.".format(version)
            )
        return "could-not-run", "supertool {}'s doctor:probe exited {} -- {}".format(
            version, done.returncode, (output.strip().splitlines() or [""])[-1]
        )

    if _VALIDATORS_HEADER not in output:
        return "could-not-run", (
            "supertool {}'s doctor:probe ran but printed no {} section".format(
                version, _VALIDATORS_HEADER
            )
        )

    section = output.split(_VALIDATORS_HEADER, 1)[1]
    if "\n## " in section:
        section = section.split("\n## ", 1)[0]

    # `op_doctor` prints no summary line at all when `.supertool.json` has no
    # "validators" section -- it appends this one sentence and returns before
    # its own counters exist. Caught here, ahead of `_SUMMARY_RE`, or this
    # legitimate empty-config shape would fall through to "could not parse"
    # and WARN about a section that is doing exactly what it should.
    if 'no "validators" section' in section:
        return "no-validators", (
            'supertool {} -- no "validators" section in .supertool.json'.format(version)
        )

    match = _SUMMARY_RE.search(section)
    if match is None:
        return "could-not-run", (
            "supertool {}'s doctor:probe printed a {} section this check "
            "could not parse".format(version, _VALIDATORS_HEADER)
        )

    configured, resolves, absent, could_not_tell, not_applicable = (
        int(group) for group in match.groups()
    )
    if configured == 0:
        return (
            "no-validators",
            "supertool {} -- no validators configured in .supertool.json".format(
                version
            ),
        )

    return "reported", {
        "version": version,
        "configured": configured,
        "resolves": resolves,
        "absent": absent,
        "could_not_tell": could_not_tell,
        "not_applicable": not_applicable,
        "offending": _offending_rows(section),
    }


def check_supertool_validators(project_dir, record=None, run=None, which=None):
    """Fold `supertool_validator_probe_state` into a finding.

    `not-installed` reports nothing here -- `check_dependency_diagnostics`
    already carries that gap under its own heading, and reporting it twice
    would read as two separate problems rather than one. Every other state
    reports exactly once, on the same `could-not-*` third-state discipline
    every check in this file follows: `op-unavailable` and `could-not-run`
    are WARN, not OK and not silence, because both are real gaps with a real
    route to zero (update supertool; investigate the failed call) -- neither
    is the permanent, nothing-to-do case `NOTICE` exists for.
    """
    import doctor as _doctor  # lazy: see doctor-check-module-scope-import.md

    state, detail = supertool_validator_probe_state(
        project_dir, record=record, run=run, which=which
    )
    if state == "not-installed":
        return
    if state in ("could-not-run", "op-unavailable"):
        _doctor.unmeasured("supertool validators", detail)
        return
    if state == "no-validators":
        _doctor.report("OK", detail)
        return

    # state == "reported"
    d = detail
    if d["absent"] == 0 and d["could_not_tell"] == 0:
        _doctor.report(
            "OK",
            "supertool validators ({}): {} configured, all resolve ({} not "
            "applicable to this tree)".format(
                d["version"], d["configured"], d["not_applicable"]
            ),
        )
        return

    detail_rows = (
        "; ".join(d["offending"])
        if d["offending"]
        else ("see `supertool 'doctor:probe'` for the per-validator detail")
    )
    _doctor.report(
        "WARN",
        "supertool validators ({}): {} configured, {} resolve, {} absent, "
        "{} could not tell -- {}. A configured-but-absent validator reports "
        "could-not-tell on every write through it in this repo, forever, "
        "with nothing else announcing it (#1577). Install the missing "
        "toolchain, or run `supertool 'doctor:probe'` for the full "
        "detail.".format(
            d["version"],
            d["configured"],
            d["resolves"],
            d["absent"],
            d["could_not_tell"],
            detail_rows,
        ),
    )
