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
    stdout = done.stdout.decode("utf-8", "replace") if isinstance(done.stdout, bytes) else (done.stdout or "")
    stderr = done.stderr.decode("utf-8", "replace") if isinstance(done.stderr, bytes) else (done.stderr or "")
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
    slug = (config or {}).get("repo") if config else None
    if slug is not None and not isinstance(slug, str):
        return None, "the repo value in .oss.json is not a string"
    if slug:
        return slug, None
    return doctor._origin_slug(project_dir, run=run)


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
    ".c": "c-cpp", ".h": "c-cpp", ".cc": "c-cpp", ".cpp": "c-cpp",
    ".cxx": "c-cpp", ".hpp": "c-cpp", ".hxx": "c-cpp",
    ".cs": "csharp",
    ".go": "go",
    ".java": "java-kotlin", ".kt": "java-kotlin", ".kts": "java-kotlin",
    ".js": "javascript-typescript", ".jsx": "javascript-typescript",
    ".mjs": "javascript-typescript", ".cjs": "javascript-typescript",
    ".ts": "javascript-typescript", ".tsx": "javascript-typescript",
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
    try:
        for dirpath, dirnames, filenames in os.walk(str(root)):
            relroot = os.path.relpath(dirpath, str(root)).replace(os.sep, "/")
            if relroot == ".":
                relroot = ""
            pruned = []
            for name in dirnames:
                child = "{}/{}".format(relroot, name) if relroot else name
                if name in _SKIP_DIR_NAMES or _is_owned_relpath(child, owned_dir, owned_files_outside_dir):
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
    """Does any `.github/workflows/*.y*ml` file's text contain ``needle``
    (case-insensitive)? Used both to note an existing CodeQL workflow and to
    check for a language-appropriate linter already running -- a coarse
    string sniff, not a YAML parse, which is enough to answer "does this
    already exist" without claiming to verify it actually runs correctly.
    """
    workflows_dir = Path(project_dir) / ".github" / "workflows"
    try:
        entries = os.listdir(str(workflows_dir))
    except OSError:
        return False
    needle_lower = needle.lower()
    for name in entries:
        if not (name.endswith(".yml") or name.endswith(".yaml")):
            continue
        try:
            text = (workflows_dir / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if needle_lower in text.lower():
            return True
    return False


def codeql_scan_state(project_dir, config=None, run=None):
    """``(state, detail)`` -- one of the issue's four named outcomes:

    * ``"uncovered-outside-owned"`` -- a supported language exists outside
      the owned paths;
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
        return "could-not-tell", "gh api repos/{}/languages did not run ({})".format(slug, exc)
    status = _classify_gh_api_status(rc, out, err)
    if status == "forbidden":
        return "could-not-tell", "reading repos/{}/languages returned a permission error (HTTP 403)".format(slug)
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
        return "could-not-tell", "repos/{}/languages response did not parse as JSON".format(slug)
    if not isinstance(languages, dict):
        return "could-not-tell", "repos/{}/languages response was not a JSON object".format(slug)

    supported_families = {
        CODEQL_LANGUAGE_FAMILIES[name]
        for name, byte_count in languages.items()
        if name in CODEQL_LANGUAGE_FAMILIES and isinstance(byte_count, int) and byte_count > 0
    }
    owned_dir = _default_owned_dir()
    if not supported_families:
        top = None
        if languages:
            top = max(
                (name for name, count in languages.items() if isinstance(count, int)),
                key=lambda name: languages[name],
                default=None,
            )
        hint = _NON_CODEQL_LINTER_HINTS.get(top) if top else None
        if hint and _workflow_files_mention(project_dir, hint):
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
        return "no-supported-language", detail

    local_families, problem = _local_families_outside_owned(project_dir, owned_dir)
    if problem is not None:
        return "could-not-tell", problem
    covered = sorted(supported_families & local_families)
    if covered:
        existing = _workflow_files_mention(project_dir, "codeql")
        note = (
            " (a workflow mentioning CodeQL already exists; this check does not verify "
            "what it scans)" if existing else ""
        )
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
