"""#761: whether `/oss:scaffold` scaffolding a CodeQL workflow would be right or
noise for THIS repo is a language question, and getting it wrong is worse than
shipping no scanner -- a default setup that only ever reports on files this
plugin itself owns and rewrites wholesale trains a maintainer to dismiss the
security tab, which is #760's own failure mode one layer up.

This module never scaffolds a workflow (the issue is explicit that this plugin
should not own one); it is `/oss:doctor` only, report-only, same contract as
every check in this family (#759, #760): no `--apply`.

Two GitHub facts and one local fact combine into one of four states:

* `GET /repos/{owner}/{repo}/languages` -- byte counts per Linguist language
  name, repo-wide. This is the only thing GitHub's API offers; it is NOT
  per-file, so it cannot itself answer "is the supported language inside or
  outside the paths this plugin owns" -- that subtraction is the whole point
  of this check and nothing generic can do it.
* CodeQL's supported-language list, hardcoded below as `CODEQL_LANGUAGE_
  FAMILIES` -- **this drifts**. CodeQL adds languages; this dict is a snapshot
  taken while writing this check, not a live query (GitHub publishes no
  API for "does CodeQL support language X"), so a real gap -- a language
  CodeQL learns to scan after this file was written -- renders here as "no
  supported language", the narrower of the two wrong answers, never as a
  silent claim that CodeQL covers something it does not.
* The presence of each supported language OUTSIDE the paths this plugin
  owns wholesale, answered locally by walking the checkout `doctor.py` is
  already running inside and matching file extensions against the same
  family table -- an extension sniff, not a Linguist reimplementation, so it
  can both over- and under-count relative to what GitHub's own `languages`
  call reports. It only has to answer one narrower question than Linguit
  does: "does at least one file of a GitHub-reported-present family sit
  outside the owned paths" -- not how many bytes, and not which language a
  borderline file really is.

Owned paths are the three CLAUDE.md names as "ours" -- replaced wholesale on
every `/oss:scaffold` run, so a CodeQL finding inside them is unfixable in
that tree without the fix being reverted at the next scaffold: `.oss/`
(`scaffold.OWNED_DIR`), `.github/workflows/oss-changelog.yml`, and
`.claude/jit-context/<dimension>/01-oss/`.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import doctor

try:
    import scaffold
except ImportError:  # pragma: no cover - mirrors doctor.py's own optional import
    scaffold = None


def _gh_api(path, run):
    """Verbatim copy of the sibling modules' own `_gh_api` -- see
    `doctor_check_security_settings._gh_api` for the shared shape and #1019's
    decode fix."""
    try:
        done = run(
            ["gh", "api", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=25,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "", "", exc
    stdout = (
        done.stdout.decode("utf-8", "replace")
        if isinstance(done.stdout, bytes)
        else (done.stdout or "")
    )
    stderr = (
        done.stderr.decode("utf-8", "replace")
        if isinstance(done.stderr, bytes)
        else (done.stderr or "")
    )
    return done.returncode, stdout, stderr, None


_GH_API_HTTP_STATUS_RE = re.compile(r"HTTP (\d+)")


def _classify_gh_api_status(returncode, stdout, stderr):
    if returncode == 0:
        return "ok"
    match = _GH_API_HTTP_STATUS_RE.search((stderr or "") + " " + (stdout or ""))
    if not match:
        return "unclassified"
    if match.group(1) == "404":
        return "not-found"
    if match.group(1) == "403":
        return "forbidden"
    return "unclassified"


def _resolve_slug(project_dir, config, run):
    """``(slug, reason)`` -- ``.oss.json``'s ``repo`` key, else the ``origin``
    remote, refused (#1055) when the resolved value is not a safe
    ``owner/name`` shape for a `gh api repos/{}/...` path segment -- see
    `doctor._malformed_repo`.
    """
    slug = (config or {}).get("repo") if config else None
    if slug is not None and not isinstance(slug, str):
        return None, "the repo value in .oss.json is not a string"
    if not slug:
        slug, reason = doctor._origin_slug(project_dir, run=run)
        if slug is None:
            return None, reason
    if doctor._malformed_repo(slug):
        return None, "repo {!r} is not a safe 'owner/name' shape".format(slug)
    return slug, None


#: Snapshot, not a live query -- see the module docstring's second bullet.
#: GitHub's `languages` endpoint keys, mapped to a CodeQL "family": several
#: Linguist names (Java/Kotlin, JavaScript/TypeScript, C/C++) share one CodeQL
#: analyser, so the family is what a finding should name, not the raw
#: Linguist string.
CODEQL_LANGUAGE_FAMILIES = {
    "C": "c-cpp",
    "C++": "c-cpp",
    "C#": "csharp",
    "Go": "go",
    "Java": "java-kotlin",
    "Kotlin": "java-kotlin",
    "JavaScript": "javascript-typescript",
    "TypeScript": "javascript-typescript",
    "Python": "python",
    "Ruby": "ruby",
    "Swift": "swift",
}

#: File extension -> the same family names above, used only to answer
#: "present outside the owned paths" locally -- see the module docstring's
#: third bullet for what this can and cannot claim.
_EXTENSION_FAMILIES = {
    ".c": "c-cpp",
    ".h": "c-cpp",
    ".cc": "c-cpp",
    ".cpp": "c-cpp",
    ".cxx": "c-cpp",
    ".hpp": "c-cpp",
    ".hxx": "c-cpp",
    ".cs": "csharp",
    ".go": "go",
    ".java": "java-kotlin",
    ".kt": "java-kotlin",
    ".kts": "java-kotlin",
    ".js": "javascript-typescript",
    ".jsx": "javascript-typescript",
    ".mjs": "javascript-typescript",
    ".cjs": "javascript-typescript",
    ".ts": "javascript-typescript",
    ".tsx": "javascript-typescript",
    ".py": "python",
    ".rb": "ruby",
    ".swift": "swift",
}

#: A directory this plugin never walks into at all -- large, third-party, or
#: itself a build artefact, so a match inside one would not be this repo's
#: own code regardless of which side of "owned" it falls on.
_SKIP_DIR_NAMES = frozenset((".git", "node_modules", "__pycache__", ".venv", "venv"))

#: A linter/scanner name this check knows to look for in a workflow file when
#: the majority language present has no CodeQL analyser at all -- itself a
#: snapshot, same caveat as `CODEQL_LANGUAGE_FAMILIES` above. `None` means no
#: specific recommendation is made for that language by this check.
_NON_CODEQL_LINTER_HINTS = {
    "Shell": "shellcheck",
    "Dockerfile": "hadolint",
}


def _default_owned_dir():
    if scaffold is not None and hasattr(scaffold, "OWNED_DIR"):
        return scaffold.OWNED_DIR
    # scaffold could not be imported -- the module docstring's own three
    # "ours" paths are named directly in CLAUDE.md, so the fallback below is
    # not a guess invented here; it is the literal value scaffold.OWNED_DIR
    # holds today, so the derivation degrades to a hardcoded fact only when
    # the derivation itself is unavailable.
    return ".oss"


def _owned_files_outside_owned_dir(owned_dir):
    """Every path in `scaffold.OWNED` that does not already sit under
    ``owned_dir`` -- today, exactly `.github/workflows/oss-changelog.yml`
    (CLAUDE.md's second "ours" row). Read off `scaffold.OWNED` itself rather
    than repeated as a second literal here, per this repo's own governing
    rule that a fact about the plugin lives in one place -- `scaffold.py`
    already carries this path as a dict key.
    """
    if scaffold is None or not hasattr(scaffold, "OWNED"):
        # scaffold could not be imported -- degrade to the one file CLAUDE.md
        # names, the same fallback shape `_default_owned_dir` uses above.
        return frozenset((".github/workflows/oss-changelog.yml",))
    return frozenset(
        path for path in scaffold.OWNED if not path.startswith(owned_dir + "/")
    )


_JIT_OWNED_RE = re.compile(r"^\.claude/jit-context/[^/]+/01-oss(?:/|$)")


def _is_owned_relpath(relpath, owned_dir, owned_files_outside_dir):
    """Is this repo-relative, ``/``-separated path (file or directory) one of
    the three CLAUDE.md names as wholesale-owned?
    """
    if relpath == owned_dir or relpath.startswith(owned_dir + "/"):
        return True
    if relpath in owned_files_outside_dir:
        return True
    if _JIT_OWNED_RE.match(relpath):
        return True
    return False


def _local_families_outside_owned(project_dir, owned_dir):
    """Every CodeQL family with at least one matching file extension outside
    the owned paths, walking the checkout `doctor.py` is already diagnosing.

    Returns ``(families, problem)`` -- ``problem`` is set when the walk
    itself could not run, so a genuinely-empty repo and an unreadable one
    are never both a bare empty set.
    """
    root = Path(project_dir)
    families = set()
    owned_files_outside_dir = _owned_files_outside_owned_dir(owned_dir)

    def _raise(exc):
        # `os.walk` defaults to `onerror=None`, which silently swallows every
        # `scandir`/`listdir` failure it hits mid-walk -- an unreadable
        # subtree then renders identically to a genuinely empty one, and the
        # `except OSError` below never fires (#1054). Passing this callback
        # is what makes that arm reachable: `os.walk` calls it instead of
        # swallowing the error, and re-raising here lets the `try/except`
        # around the walk catch it exactly as it already does for a failure
        # on the root itself.
        raise exc

    try:
        for dirpath, dirnames, filenames in os.walk(str(root), onerror=_raise):
            relroot = os.path.relpath(dirpath, str(root)).replace(os.sep, "/")
            if relroot == ".":
                relroot = ""
            pruned = []
            for name in dirnames:
                child = "{}/{}".format(relroot, name) if relroot else name
                if name in _SKIP_DIR_NAMES or _is_owned_relpath(
                    child, owned_dir, owned_files_outside_dir
                ):
                    pruned.append(name)
            for name in pruned:
                dirnames.remove(name)
            for name in filenames:
                child = "{}/{}".format(relroot, name) if relroot else name
                if _is_owned_relpath(child, owned_dir, owned_files_outside_dir):
                    continue
                family = _EXTENSION_FAMILIES.get(os.path.splitext(name)[1].lower())
                if family:
                    families.add(family)
    except OSError as exc:
        return set(), "{} could not be walked ({})".format(project_dir, exc)
    return families, None


def _workflow_files_mention(project_dir, needle):
    """``True`` / ``False`` / ``None`` -- does any `.github/workflows/*.y*ml`
    file's text contain ``needle`` (case-insensitive)? A coarse string sniff,
    not a YAML parse, which is enough to answer "does this already exist"
    without claiming to verify it actually runs correctly.

    Self-review finding: the earlier version of this function folded "the
    workflows directory could not be listed" (a permission error on the
    checkout, not "no workflows directory exists") into the same ``False`` a
    genuinely empty or absent directory returns -- exactly the defect class
    CLAUDE.md is named after, one function under a doctor check that exists
    to name it in others. ``None`` is that third state, said out loud: an
    absent directory (`FileNotFoundError`/`NotADirectoryError` -- there is
    nothing to search, which is a real ``False``) is distinguished from a
    directory that exists but could not be read (``None`` -- unknown, not "no
    match").
    """
    workflows_dir = Path(project_dir) / ".github" / "workflows"
    try:
        entries = os.listdir(str(workflows_dir))
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        return None
    needle_lower = needle.lower()
    unreadable = False
    for name in entries:
        if not (name.endswith(".yml") or name.endswith(".yaml")):
            continue
        try:
            text = (workflows_dir / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            unreadable = True
            continue
        if needle_lower in text.lower():
            return True
    return None if unreadable else False


def _default_setup_state(slug, run):
    """#1062: ``("configured", [languages])`` / ``("not-configured", None)`` /
    ``("unknown", reason)`` for ``GET /repos/{slug}/code-scanning/default-setup``.

    GitHub's **default setup** enables CodeQL with no workflow file in the
    repository at all, so the local walk this module performs cannot see it:
    a fully scanned repository and an unscanned one are byte-identical from
    inside the checkout. That is this repository's own named defect class --
    an absence produced by where the tool looked, read as an absence in the
    world -- and asking the forge is the only thing that separates them.

    The third state is never folded into either answer. A 403 from a
    permission-limited token, a call that would not run and a body that did
    not parse all answer ``unknown``: a read that could not see the setting
    must not render as a setting confirmed absent, the same rule
    `doctor_check_branch_protection.branch_protection_state` already follows.
    A clean 404 IS an answer -- the endpoint reports no default setup here --
    and is the issue's own second outcome.
    """
    rc, out, err, exc = _gh_api(
        "repos/{}/code-scanning/default-setup".format(slug), run
    )
    if exc is not None:
        return (
            "unknown",
            "gh api .../code-scanning/default-setup did not run ({})".format(exc),
        )
    status = _classify_gh_api_status(rc, out, err)
    if status == "not-found":
        return "not-configured", None
    if status == "forbidden":
        return (
            "unknown",
            "reading code-scanning/default-setup for {} returned a permission error "
            "(HTTP 403), which renders identically to a token that cannot see the "
            "setting on a repo where default setup IS configured".format(slug),
        )
    if status != "ok":
        return (
            "unknown",
            "reading code-scanning/default-setup for {} returned an unrecognised "
            "response ({})".format(slug, (err or out).strip()[:200]),
        )
    try:
        body = json.loads(out or "{}")
    except ValueError:
        return (
            "unknown",
            "the code-scanning/default-setup response did not parse as JSON",
        )
    if not isinstance(body, dict):
        return (
            "unknown",
            "the code-scanning/default-setup response was not a JSON object",
        )
    state = body.get("state")
    if state == "configured":
        languages = body.get("languages")
        if not isinstance(languages, list):
            return (
                "unknown",
                "code-scanning/default-setup reports state=configured for {} and carried "
                "no languages list, so which families it covers could not be read".format(
                    slug
                ),
            )
        return "configured", [
            name.lower() for name in languages if isinstance(name, str)
        ]
    if state == "not-configured":
        return "not-configured", None
    return (
        "unknown",
        "code-scanning/default-setup for {} carried no recognised state (got {!r})".format(
            slug, state
        ),
    )


def codeql_scan_state(project_dir, config=None, run=None):
    """``(state, detail)`` -- one of the issue's four named outcomes:

    * ``"uncovered-outside-owned"`` -- a supported language exists outside
      the owned paths and GitHub's code-scanning default setup does not
      cover it;
    * ``"default-setup-covers"`` (#1062) -- a supported language exists
      outside the owned paths and default setup already scans every one of
      them, so there is nothing to add;
    * ``"owned-only"`` -- the only supported language present is entirely
      inside the owned paths;
    * ``"no-supported-language"`` -- CodeQL has no analyser for anything
      GitHub reports here;
    * ``"could-not-tell"`` -- the languages call failed, or the token
      cannot read it.
    """
    run_ = subprocess.run if run is None else run
    if shutil.which("gh") is None:
        return "could-not-tell", "gh is not on PATH"
    slug, reason = _resolve_slug(project_dir, config, run_)
    if slug is None:
        return "could-not-tell", reason
    rc, out, err, exc = _gh_api("repos/{}/languages".format(slug), run_)
    if exc is not None:
        return "could-not-tell", "gh api repos/{}/languages did not run ({})".format(
            slug, exc
        )
    status = _classify_gh_api_status(rc, out, err)
    if status == "forbidden":
        return (
            "could-not-tell",
            "reading repos/{}/languages returned a permission error (HTTP 403)".format(
                slug
            ),
        )
    if status != "ok":
        return (
            "could-not-tell",
            "reading repos/{}/languages returned an unrecognised response ({})".format(
                slug, (err or out).strip()[:200]
            ),
        )
    try:
        languages = json.loads(out or "{}")
    except ValueError:
        return (
            "could-not-tell",
            "repos/{}/languages response did not parse as JSON".format(slug),
        )
    if not isinstance(languages, dict):
        return (
            "could-not-tell",
            "repos/{}/languages response was not a JSON object".format(slug),
        )

    supported_families = {
        CODEQL_LANGUAGE_FAMILIES[name]
        for name, byte_count in languages.items()
        if name in CODEQL_LANGUAGE_FAMILIES
        and isinstance(byte_count, int)
        and byte_count > 0
    }
    owned_dir = _default_owned_dir()
    #: Self-review finding: `CODEQL_LANGUAGE_FAMILIES` is a hardcoded
    #: snapshot (see the module docstring's second bullet) -- a language
    #: CodeQL has since learned to scan renders here exactly like a repo
    #: CodeQL genuinely cannot cover. That gap was documented in this
    #: module's source and nowhere in its printed output, so a maintainer
    #: skimming for WARN/FAIL would never see the one line that would tell
    #: them to go re-check. Carried into every `no-supported-language`
    #: detail string below instead, so the caveat travels with the finding
    #: rather than staying a fact only this file's own reader can see.
    _STALE_TABLE_CAVEAT = (
        " (this check's CodeQL-supported-language table is a hardcoded snapshot and may "
        "not include a language CodeQL has since learned to scan -- re-check GitHub's "
        "current supported-language list against the languages named above if in doubt)"
    )
    if not supported_families:
        top = None
        if languages:
            top = max(
                (name for name, count in languages.items() if isinstance(count, int)),
                key=lambda name: languages[name],
                default=None,
            )
        hint = _NON_CODEQL_LINTER_HINTS.get(top) if top else None
        mentions = _workflow_files_mention(project_dir, hint) if hint else None
        if hint and mentions is None:
            detail = (
                "no CodeQL-supported language found on {} (languages: {}); the largest "
                "language present, {}, has no CodeQL analyser -- whether a {} workflow "
                "already covers it could not be told (its workflows directory could not "
                "be read)".format(slug, sorted(languages), top, hint)
            )
        elif hint and mentions:
            detail = (
                "no CodeQL-supported language found on {} (languages: {}); the largest "
                "language present, {}, has no CodeQL analyser, and a {} workflow already "
                "appears to cover it".format(slug, sorted(languages), top, hint)
            )
        elif hint:
            detail = (
                "no CodeQL-supported language found on {} (languages: {}); the largest "
                "language present, {}, has no CodeQL analyser -- no {} workflow was found; "
                "consider adding one".format(slug, sorted(languages), top, hint)
            )
        elif top:
            detail = (
                "no CodeQL-supported language found on {} (languages: {}); this check has "
                "no linter recommendation for the largest language present, {}".format(
                    slug, sorted(languages), top
                )
            )
        else:
            detail = "no languages reported at all for {}".format(slug)
        return "no-supported-language", detail + _STALE_TABLE_CAVEAT

    local_families, problem = _local_families_outside_owned(project_dir, owned_dir)
    if problem is not None:
        return "could-not-tell", problem
    covered = sorted(supported_families & local_families)
    if covered:
        #: #1062: ask the forge before recommending a workflow. Default setup
        #: and advanced setup (a workflow file) are mutually exclusive on
        #: GitHub, so the WARN below, acted on by a maintainer whose repo is
        #: already scanned by default setup, either fails to enable or
        #: DISPLACES the scanner already running -- a remedy that leaves the
        #: repository worse than ignoring the line.
        setup_state, setup_payload = _default_setup_state(slug, run_)
        if setup_state == "unknown":
            return (
                "could-not-tell",
                "CodeQL-supported language(s) {} appear outside {}/, and whether GitHub's "
                "code-scanning default setup already covers them is unknown -- {}. Not read "
                "as uncovered: a workflow recommended here would displace a default setup "
                "that may be running".format(covered, owned_dir, setup_payload),
            )
        if setup_state == "configured":
            setup_languages = set(setup_payload or ())
            gap = [family for family in covered if family not in setup_languages]
            if not gap:
                return (
                    "default-setup-covers",
                    "GitHub's code-scanning default setup is configured on {} and covers "
                    "every CodeQL-supported language found outside {}/ ({}); it ships no "
                    "workflow file, which is why a checkout walk alone cannot see it".format(
                        slug, owned_dir, covered
                    ),
                )
            return (
                "uncovered-outside-owned",
                "GitHub's code-scanning default setup is configured on {} but does not list "
                "{}, found outside {}/ (it covers {})".format(
                    slug, sorted(gap), owned_dir, sorted(setup_languages) or "nothing"
                ),
            )
        existing = _workflow_files_mention(project_dir, "codeql")
        if existing is None:
            note = " (whether a CodeQL workflow already exists could not be told)"
        elif existing:
            note = (
                " (a workflow mentioning CodeQL already exists; this check does not verify "
                "what it scans)"
            )
        else:
            note = ""
        return (
            "uncovered-outside-owned",
            "CodeQL-supported language(s) {} appear outside {}/{}".format(
                covered, owned_dir, note
            ),
        )
    return (
        "owned-only",
        "the only CodeQL-supported language(s) present ({}) sit entirely inside {}, "
        "the path(s) this plugin owns and rewrites wholesale on every /oss:scaffold "
        "run".format(sorted(supported_families), owned_dir),
    )


def check_codeql_scan(project_dir, config=None, run=None):
    """Report only -- no `--apply`, same reasoning as every check in this
    family (#759, #760): scaffolding a scanner is a decision for the
    maintainer to make, never something this diagnostic writes.
    """
    state, detail = codeql_scan_state(project_dir, config=config, run=run)
    if state == "default-setup-covers":
        doctor.report("OK", "CodeQL coverage: {}".format(detail))
        return
    if state == "uncovered-outside-owned":
        doctor.report(
            "WARN",
            "CodeQL coverage: {} -- consider adding a CodeQL workflow scoped to those "
            "language(s).".format(detail),
        )
        return
    if state == "owned-only":
        doctor.report(
            "WARN",
            "CodeQL coverage: {} -- a default CodeQL setup would report only on vendored "
            "files. Recommend `languages: actions` (if any GitHub Actions workflows are "
            "real attack surface) or no CodeQL workflow at all.".format(detail),
        )
        return
    if state == "no-supported-language":
        doctor.report("OK", "CodeQL coverage: {}".format(detail))
        return
    doctor.report("WARN", "CodeQL coverage: could not tell -- {}".format(detail))
