"""Read, validate and derive `.oss.json` -- the per-repo config for the maintainer loop.

Everything the loop used to hardcode lives here instead. Two rules shape this module:

1. **Nothing is invented.** A repo with no labels gets an empty list, never a plausible
   default. An invented value reaches a brief indistinguishable from a measured one.
2. **Absence is a stated outcome, not a silent pass.** Every function returns problems
   by name rather than falling back, because a config that "loaded fine" while missing
   half its keys is the same defect this whole loop exists to catch.

Python 3.9 compatible: no match statements, no `X | Y` annotations.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

REQUIRED_KEYS = {
    "repo",
    "default_branch",
    "clone",
    "worktree_root",
    "branch_pattern",
    "test_command",
    "version_sites",
    "changelog_dir",
    "docs_targets",
    "labels",
    "ci",
    "state_file",
}

OPTIONAL_KEYS = {"milestones", "notes", "release"}

# The config is two files because its keys have two different owners (#34).
#
# `.oss.json` is the *project's* answer: the repo slug, the tag spelling, what runs the
# tests, which files carry the version. Those are reviewed like any other repo fact and
# must be the same for everyone, so the file is tracked.
#
# `.oss.local.json` is *this machine's* answer: three keys, all of them a directory on
# one person's disk. It is git-excluded and never shared.
#
# The split was not cosmetic. Setup used to write one file and exclude it, so the whole
# `release` block lived on a single laptop. A second maintainer running /oss:release had
# no `tag_pattern`, the documented remedy for that is stop-and-ask, and a repo tagging
# `v1.2.3` can come back with `1.2.4` -- the second tag namespace this module warns
# about, opened by the tool that warns about it.
CONFIG_NAME = ".oss.json"
LOCAL_CONFIG_NAME = ".oss.local.json"

LOCAL_KEYS = {"clone", "worktree_root", "state_file"}

# What a repo does when it releases differs, so it is configured. What must NEVER be
# configured is the gate list -- default branch green at leg level, nothing mid-review,
# security audit passed, every version site bumped, the tag verified on the remote. A
# gate that can be switched off is switched off on the day it is inconvenient, which is
# the day it existed for. Keys that look like gates are refused, not ignored: an ignored
# key reads as an accepted setting.
RELEASE_KEYS = {
    "tag_pattern",
    "commit_subject",
    "merge_method",
    "triggers",
    "create_release",
    "draft",
    "latest",
}
MERGE_METHODS = {"squash", "merge", "rebase"}
TRIGGER_KEYS = {"merged_prs", "soak_hours"}

# Whether the tag becomes a GitHub Release, and what kind (#58).
#
# These are policy, not a gate, and they are policy about a *project* rather than
# about a machine -- every maintainer of a repo should publish the same way -- so they
# live in the tracked `.oss.json` and never in `.oss.local.json`.
#
# The shipped defaults are the conservative ones, and each is conservative about a
# different thing:
#
#   create_release: false  Some projects tag deliberately without releasing. More to
#                          the point, publishing is not this tool's decision to make
#                          on a repo that never asked for it.
#   draft: true            A draft is undoable; a published release has already
#                          notified everyone watching by the time you regret it.
#   latest: false          `Latest` changes what the repo's landing page shows, which
#                          is outward-facing and belongs to whoever owns the page.
#
# Unset is a third state and not a quiet `false`: `release_publish_policy` reports
# `stated`, and `release_publish.py` names the key in its skip reason, so a repo that
# never chose is told what it would set rather than silently not releasing forever.
PUBLISH_KEYS = ("create_release", "draft", "latest")
PUBLISH_DEFAULTS = {"create": False, "draft": True, "latest": False}

VERSION_PLACEHOLDER = "{version}"

# Tag schemes we can recognise from tags that already exist. Anything else stays null:
# guessing `v{version}` against a repo tagging `rel-1.2` opens a second tag namespace
# nobody notices until a release goes missing from it.
TAG_SCHEMES = [
    (re.compile(r"^v\d+\.\d+\.\d+$"), "v{version}"),
    (re.compile(r"^\d+\.\d+\.\d+$"), "{version}"),
]

# Keys whose value may honestly be null. `test_command` is null when the probe could
# not tell what runs the tests, and `changelog_dir` is null when the repo has not
# adopted fragments -- both are findings, and a guess would be worse.
#
# Everything else being null is a hole, not an answer: a config carrying `repo: null`
# passed validation until a test caught it, because the key was present and only its
# type was checked. A present-but-empty key is the same absence, one layer down.
NULLABLE_KEYS = {"test_command", "changelog_dir"}

KNOWN_KEYS = REQUIRED_KEYS | OPTIONAL_KEYS
PROJECT_KEYS = KNOWN_KEYS - LOCAL_KEYS

# The one nullable release key that gets a default rather than a stop (#34).
#
# The two nullable keys in the release block are deliberately not symmetric, and the
# asymmetry is the point rather than an oversight: a wrong commit subject is cosmetic and
# revisable in the next commit, while a wrong tag opens a namespace that exists forever.
# So `commit_subject` resolves to a stated default and `tag_pattern` stops and asks. What
# was wrong before was not the asymmetry -- it was that only one of the two said anything,
# so a null `commit_subject` reached an agent that invented a subject line.
#
# `{version}`, not `{tag}`: `_validate_release` refuses any subject without the {version}
# placeholder, so a default spelled the obvious way would be rejected by this same module.
DEFAULT_COMMIT_SUBJECT = "chore(release): {version}"
RELEASE_DEFAULTS = {"commit_subject": DEFAULT_COMMIT_SUBJECT}

# A config file is committed. Nothing in it may look like a credential, and an
# unfamiliar key that does is refused rather than ignored -- ignoring it is how a
# token ends up in git history with everyone assuming the schema rejected it.
SECRET_RE = re.compile(r"(token|password|passwd|secret|api[_-]?key|credential)", re.IGNORECASE)

REPO_RE = re.compile(r"^[^/\s]+/[^/\s]+$")

# `changelog_dir` is the one value in this file that becomes shell source. `scaffold.py`
# substitutes it into a `run:` line of the workflow it writes into somebody else's
# repository, so a value carrying `$(...)` is a command that runs in their CI -- and this
# module checked every other key and not that one (#31).
#
# The shape is one or more path segments of letters, digits, dot, dash and underscore.
# That admits `changelog.d`, `news.d` and a nested `docs/changelog.d` -- nesting works,
# the scaffold creates parent directories -- and admits nothing a shell, a regex or a
# path resolver reads as an instruction. Tighter than this refuses a legitimate repo to
# close a hole that quoting already closes; looser is theatre.
CHANGELOG_DIR_RE = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")


def changelog_dir_problem(value):
    """Why this `changelog_dir` cannot be used, or None when it is fine.

    Null is fine and means the repo has not adopted fragments. A non-string is not: it
    used to travel all the way to `str.replace()` and raise a TypeError from inside the
    renderer, which is a crash wearing the same hat as the gap above.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return (
            "changelog_dir: expected a relative directory path as a string, or null "
            "when the repo has no fragment practice; got {!r}.".format(value)
        )
    if not CHANGELOG_DIR_RE.match(value) or any(
        segment in (".", "..") for segment in value.split("/")
    ):
        return (
            "changelog_dir: expected a relative path of plain segments, such as "
            "'changelog.d' or 'docs/changelog.d'; got {!r}. This value is written into "
            "a `run:` line of the workflow generated for another repository, so a value "
            "a shell would read as an instruction is refused rather than quoted and "
            "hoped about.".format(value)
        )
    return None

# Label vocabularies differ per repo and no pattern list covers every convention, so
# these are widened rather than made exhaustive -- and every label that matches none
# of them is reported by name. `priority/high` is GitHub's own documented spelling and
# used to match nothing, producing an empty priority list on a fully labelled board
# that read exactly like the measured empty list of a board with none.
PRIORITY_RES = (
    re.compile(r"^(?:priority|prio|p)[-:/ ]", re.IGNORECASE),
    re.compile(r"^p\d+$", re.IGNORECASE),
)
LANE_RES = (re.compile(r"^(?:lane|area|type)[-:/ ]", re.IGNORECASE),)

# A version-shaped string. Two-part versions are deliberately not matched: `3.9` in a
# README is far more often a Python floor than a release.
VERSION_RE = re.compile(r"\b\d+\.\d+\.\d+\b")

# Files that may carry the version, and how to look. The structured ones get a key
# lookup because a stray semver anywhere in a manifest is not the version; the prose
# ones get a regex because there is no key to read.
VERSION_CANDIDATES = (
    (".claude-plugin/plugin.json", "json"),
    ("package.json", "json"),
    ("Cargo.toml", "toml:package"),
    ("pyproject.toml", "toml:project"),
    ("CHANGELOG.md", "text"),
    ("README.md", "text"),
)

# Three states, not two. `none` is a measured negative -- the file was read and holds
# no version -- and dropping it silently is correct. `unreadable` is the tool failing
# to answer, which is a different fact and is reported rather than folded into `none`.
VERSION_EVIDENCE_STATES = {"version", "none", "unreadable"}

# The probe schema, in one place, because it had none: the key names were discoverable
# only by reading this file and the semantics of `files` were written down nowhere. A
# caller who guessed produced a schema-valid config that was confidently wrong, with no
# error at any layer. `merge_method` is the one key that may honestly be null.
PROBE_SCHEMA = (
    ("repo", (str,), False),
    ("default_branch", (str,), False),
    ("clone", (str,), False),
    ("files", (list,), False),
    ("tags", (list,), False),
    ("labels", (list,), False),
    ("milestones", (list,), False),
    ("workflow_jobs", (list,), False),
    ("merge_method", (str,), True),
    ("version_evidence", (dict,), False),
)

PROBE_KEYS = tuple(key for key, _, _ in PROBE_SCHEMA)

PROBE_SCHEMA_HELP = """the probe schema
----------------
`--probe REPO` measures a repo directory and writes this shape; `--build` reads it.
There is one implementation of the schema on purpose -- a hand-assembled probe was
the defect, not the workaround.

  repo              "owner/name"
  default_branch    "main"
  clone             absolute path to the local clone
  files             repo-relative paths exactly as `git ls-files` prints them,
                    nested ones included. NOT top-level directory entries: the
                    detectors match on strings like "tests/test_x.py" and
                    ".claude-plugin/plugin.json", so a list of directory names
                    silently detects nothing.
  tags              tag names as `git tag --list` prints them
  labels            label names as they are spelled on the repo
  milestones        milestone titles
  workflow_jobs     job names read out of .github/workflows/*
  merge_method      "squash" | "merge" | "rebase" | null when more than one is
                    allowed and the repo has not decided
  version_evidence  {candidate path: "version" | "none" | "unreadable"} for every
                    version candidate present in `files`. "none" means read and
                    carries none; "unreadable" means could not be read, which is
                    not the same answer and is reported rather than dropped.

Every key is required. Absent is not empty: `probe.get("files") or []` made a
typo'd key and an empty repo identical, and the config that came out said so with
the same authority as a measurement."""

# Ordered: the first entry whose marker file is present wins.
TEST_COMMANDS = [
    ("pyproject.toml", "pytest"),
    ("tests/run-all.sh", "bash tests/run-all.sh"),
    ("package.json", "npm test"),
    ("Cargo.toml", "cargo test"),
]


class ContainmentError(Exception):
    """A path derived from config or a branch name tried to leave its root."""


class ProbeError(Exception):
    """The probe handed to `build` is not the shape `build` reads.

    Raised rather than worked around, because the alternative is what this replaced:
    a missing key read as an empty measurement, and a config nobody could tell apart
    from a correct one.
    """


def classify_labels(labels):
    """Sort label names into priority, lane, and *what matched neither*.

    The third list is the point. An empty priority list is a legitimate measurement
    on a repo with no priority labels, and it is also what a pattern miss produces --
    the two are byte-identical in the config, so the miss has to be said out loud
    somewhere else.
    """
    classified = {"priority": [], "lanes": [], "unclassified": []}
    for label in labels or []:
        name = str(label)
        if any(pattern.match(name) for pattern in PRIORITY_RES):
            classified["priority"].append(name)
        elif any(pattern.match(name) for pattern in LANE_RES):
            classified["lanes"].append(name)
        else:
            classified["unclassified"].append(name)
    return classified


def _toml_section_version(text, section):
    """True when ``[section]`` in a TOML document carries a version-shaped value.

    A hand-rolled scan rather than a parser: tomllib is 3.11+ and this module is
    3.9-compatible. It reads one key in one section, which is the whole requirement.
    """
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].strip().strip('"')
            continue
        if current != section:
            continue
        match = re.match(r"""^version\s*=\s*["'](.+?)["']""", stripped)
        if match and VERSION_RE.search(match.group(1)):
            return True
    return False


def _version_state(path, kind):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "unreadable"
    if kind == "json":
        try:
            payload = json.loads(text)
        except ValueError:
            return "unreadable"
        if not isinstance(payload, dict):
            return "unreadable"
        value = payload.get("version")
        if isinstance(value, str) and VERSION_RE.search(value):
            return "version"
        return "none"
    if kind.startswith("toml:"):
        return "version" if _toml_section_version(text, kind.split(":", 1)[1]) else "none"
    return "version" if VERSION_RE.search(text) else "none"


def inspect_version_sites(root, files):
    """Say, for every version candidate the repo has, whether it carries a version.

    Existence was being treated as proof, so `README.md` was listed as a version site
    on repos where it holds no version at all and `/oss:release` was told to bump a
    file with nothing to bump. Reading the file is the difference between a candidate
    and a site.
    """
    root = Path(root)
    evidence = {}
    for candidate, kind in VERSION_CANDIDATES:
        if candidate in files:
            evidence[candidate] = _version_state(root / candidate, kind)
    return evidence


def probe_problems(probe):
    """Return a list of sentences naming everything wrong with a probe."""
    if not isinstance(probe, dict):
        return ["probe: expected a JSON object, got {}".format(type(probe).__name__)]

    problems = []
    for key, types, nullable in PROBE_SCHEMA:
        if key not in probe:
            problems.append(
                "probe: missing key {!r}. Absent is not empty -- a missing key used to "
                "derive as though the repo had none of it. Produce a probe with "
                "--probe REPO rather than assembling one.".format(key)
            )
            continue
        value = probe[key]
        if value is None and nullable:
            continue
        if not isinstance(value, types):
            problems.append(
                "probe.{}: expected {}, got {!r}. See --help for the schema, or use "
                "--probe REPO.".format(key, " or ".join(t.__name__ for t in types), value)
            )

    for key in sorted(set(probe) - set(PROBE_KEYS)):
        problems.append(
            "probe.{}: unknown key (typo, or a schema change nobody wrote down). "
            "--probe REPO writes the shape --build reads.".format(key)
        )

    evidence = probe.get("version_evidence")
    files = probe.get("files")
    if isinstance(evidence, dict) and isinstance(files, list):
        for candidate, _ in VERSION_CANDIDATES:
            if candidate not in files:
                continue
            state = evidence.get(candidate)
            if state is None:
                problems.append(
                    "probe.version_evidence: nothing recorded for {}, which the probe "
                    "lists. 'could not answer' is not 'carries no version', so it is "
                    "refused rather than quietly dropped.".format(candidate)
                )
            elif state not in VERSION_EVIDENCE_STATES:
                problems.append(
                    "probe.version_evidence[{}]: {!r} is not one of {}".format(
                        candidate, state, ", ".join(sorted(VERSION_EVIDENCE_STATES))
                    )
                )

    return problems


def local_config_path(path):
    """The machine half that sits beside a given project config."""
    return Path(path).parent / LOCAL_CONFIG_NAME


def _enclosing_clone(start):
    """The working tree whose git dir ``start`` shares, as ``(path, why_not)``.

    ``path`` is None whenever the question could not be answered -- git absent, not a
    repository, a bare repo -- and ``why_not`` then says which, so no caller can print
    "there is no clone" for "I could not look".

    Git is asked rather than the layout being reconstructed: a worktree's ``.git`` is a
    *file* pointing into ``<clone>/.git/worktrees/<name>``, and hand-walking that back up
    is the kind of separator arithmetic that fails on exactly one platform.
    """
    ok, out, detail = _run(["git", "rev-parse", "--git-common-dir"], cwd=start)
    if not ok:
        return None, detail
    first = out.strip().splitlines()
    if not first or not first[0].strip():
        return None, "git rev-parse --git-common-dir printed nothing"
    common = Path(first[0].strip())
    if not common.is_absolute():
        common = Path(start) / common
    try:
        common = common.resolve()
    except OSError as exc:
        return None, "{} could not be resolved ({})".format(common, exc)
    if common.name != ".git":
        return None, "{} is not a .git directory, so this checkout has no working tree beside it".format(
            common
        )
    return common.parent, ""


def _anchored_elsewhere(given):
    """Would joining ``given`` onto a base directory throw that base away?

    Only Windows answers yes for a path that is not absolute. `C:x` is drive-relative,
    and a leading separator with no drive is relative to the current drive's root;
    pathlib joins both by discarding the left-hand side -- so an explicit `start` would
    silently revert to the process's own directory, which is the exact leak `start`
    exists to close. The branch is unreachable on a POSIX leg, so it is measured against
    `PureWindowsPath` directly rather than through a fixture no POSIX runner can build.
    """
    return bool(given.drive or given.root) and not given.is_absolute()


def resolve_config_path(path, start=None):
    """Where the project config really is, as ``(resolved, origin, detail)``.

    ``start`` is the directory the question is asked *from*, defaulting to the process's
    own. A relative ``path`` is read against it and the widening anchors on it, so a
    caller pointed at a tree it is not standing in -- `/oss:doctor --root` -- can ask
    the question it means. Without it the only expressible question was about the
    current directory, and the alternative every caller reached for was to compute a
    relative path from cwd to the tree: ``os.path.relpath`` returns
    ``../../../../../clone/sub/.oss.json`` whenever the two differ, or merely arrive
    under different spellings of one directory, which on macOS is the default. That
    path is then appended to the clone and answers `not found` for a config sitting in
    it -- #53's bug reintroduced by the code adopting #53's fix. ``start`` exists so
    that no caller has to build such a path: nothing here is resolved against cwd.

    ``origin`` is one of:

    ``here``           ``path`` exists relative to ``start``, and nothing else is
                       consulted.
    ``clone``          absent there, present in the working tree of the enclosing clone.
                       This is the git-worktree case: `.oss.json` may be git-excluded,
                       so it lives in the clone and in none of its worktrees, and the
                       developer standing in a worktree is in the same repository.
    ``missing``        absent, and the widening ran: ``detail`` says how far it got.
    ``unsearchable``   absent, and the widening could NOT run -- there is no enclosing
                       clone to search, or git could not be asked whether there is one.
                       Split out from ``missing`` because "the clone has no config" and
                       "no clone was searched at all" are the two answers this whole
                       project exists to keep apart, and prose alone kept them apart
                       only for readers: a caller branching on ``origin`` saw one value.

    ``unsearchable`` deliberately does not subdivide further into "git is absent" and
    "this is no repository". ``_enclosing_clone`` draws the line it can measure -- git
    answered, or it did not -- and its ``why_not`` carries the rest as prose. Recovering
    that finer split would mean matching git's stderr text, which is version- and
    locale-dependent; a state derived from a string match is a state that goes wrong
    silently, which is the defect, not the fix.

    An absolute ``path`` is never widened, with or without ``start``: a path somebody
    typed in full is an answer, not a starting point, and it stays ``missing`` because
    nothing the caller asked about went unsearched.
    """
    given = Path(path)
    base = None if start is None else Path(start)
    if base is not None and _anchored_elsewhere(given):
        return (
            None,
            "unsearchable",
            "{} carries an anchor of its own, so it cannot be read relative to {} -- "
            "joining them would drop {} and search this process's directory instead. "
            "Pass the path in full, or pass one with no drive and no leading "
            "separator.".format(given, base, base),
        )
    here = given if (base is None or given.is_absolute()) else base / given
    if here.is_file():
        return here, "here", ""
    if given.is_absolute():
        return None, "missing", "Run /oss:setup to write it."
    if base is not None and not base.is_dir():
        # An explicit `start` that is not there must never fall back to the process's
        # directory the way the cwd form does below. That fallback is how a --root at a
        # path that does not exist came back describing the caller's own repository
        # (#62), and with `start` the fallback would be silent as well as wrong.
        return (
            None,
            "unsearchable",
            "{} is not a directory, so it is in no clone that could be searched.".format(base),
        )

    # git is asked from the directory the path points into, but that directory need not
    # exist here -- an excluded `configs/.oss.json` has no `configs/` in the worktree.
    # A non-existent cwd makes the subprocess fail to start, which would be reported as
    # "git could not answer" about a repository git can answer about perfectly well.
    probe = here.parent
    if not probe.is_dir():
        probe = base if base is not None else Path(".")
    clone, why_not = _enclosing_clone(probe)
    if clone is None:
        return (
            None,
            "unsearchable",
            "No enclosing clone could be checked ({}), so nowhere else was searched. "
            "Run /oss:setup to write it.".format(why_not),
        )
    try:
        same = clone.samefile(probe)
    except OSError:
        same = False
    if same:
        return None, "missing", "This directory is the clone. Run /oss:setup to write it."
    candidate = clone / given
    if candidate.is_file():
        return candidate, "clone", str(clone)
    return (
        None,
        "missing",
        "Not in the enclosing clone at {} either. Run /oss:setup to write it.".format(clone),
    )


def load_from(path, start=None):
    """`load`, plus where the file was found: ``(config, problems, origin, resolved)``.

    Callers that print to a human want the origin -- reading the clone's config from a
    worktree is correct and still worth saying out loud, because the config names paths
    that are now one directory away.

    ``start`` is passed straight through to `resolve_config_path`; a caller pointed at a
    tree it is not standing in names that tree here rather than building a path to it.
    """
    resolved, origin, detail = resolve_config_path(path, start=start)
    if resolved is None:
        return None, ["{}: not found. {}".format(path, detail)], origin, None
    config, problems = load(resolved)
    return config, problems, origin, resolved


def split(config):
    """Partition a config into ``(project, local)``.

    An unknown key goes to the project half on purpose. It is a typo or an undeclared
    schema change, and `validate` names it there; hidden in an untracked file it would
    be one maintainer's private mystery.
    """
    project = dict((key, value) for key, value in config.items() if key not in LOCAL_KEYS)
    local = dict((key, value) for key, value in config.items() if key in LOCAL_KEYS)
    return project, local


def _read_json_object(path):
    """``(document, problem)``. A file that is simply absent is neither."""
    path = Path(path)
    if not path.is_file():
        return None, None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, "{}: could not read ({})".format(path, exc)
    try:
        document = json.loads(raw)
    except ValueError as exc:
        return None, "{}: could not parse as JSON ({})".format(path, exc)
    if not isinstance(document, dict):
        return None, "{}: could not parse as a JSON object".format(path)
    return document, None


def _scope_problems(project, local, local_exists):
    """Where a key sits, as opposed to whether its value is any good.

    `validate` sees only the merged config and so cannot tell the two halves apart. This
    is the only place that can, and every finding here names the remedy: a scope problem
    that merely says "wrong" is a file the maintainer leaves exactly as it is.
    """
    problems = []

    for key in sorted(LOCAL_KEYS & set(project)):
        problems.append(
            "{}: machine-scoped key in the committed config. It names a directory on one "
            "person's disk, so it belongs in {}. Run `oss_config.py --split` to move it; "
            "the config still loads meanwhile.".format(key, LOCAL_CONFIG_NAME)
        )

    if local:
        for key in sorted(PROJECT_KEYS & set(local)):
            problems.append(
                "{}: project-scoped key overridden in {}. The committed value wins -- a "
                "project fact that differs per machine is how two maintainers cut two "
                "different releases from one repo.".format(key, LOCAL_CONFIG_NAME)
            )
    elif not local_exists and (LOCAL_KEYS - set(project)):
        problems.append(
            "{} is missing, so this machine has no {}. Run /oss:setup here -- the "
            "committed config is the project's half and never carries these.".format(
                LOCAL_CONFIG_NAME, ", ".join(sorted(LOCAL_KEYS - set(project)))
            )
        )

    return problems


def load(path):
    """Return ``(config, problems)`` for the two config halves taken together.

    ``config`` is the merge of the tracked project file and the git-excluded machine
    file, so every caller downstream keeps seeing one dictionary and the split stays a
    fact about storage. It is None only when the project half could not be read.

    Problems are sentences, not codes -- they are printed to a human by `doctor`.
    """
    path = Path(path)
    if not path.is_file():
        return None, ["{}: not found. Run /oss:setup to write it.".format(path)]
    project, problem = _read_json_object(path)
    if problem is not None:
        return None, [problem]

    local_path = local_config_path(path)
    local_exists = local_path.is_file()
    local, local_problem = _read_json_object(local_path)

    problems = []
    if local_problem is not None:
        problems.append(local_problem)
        local = None

    config = dict(project)
    for key, value in sorted((local or {}).items()):
        if key not in PROJECT_KEYS:
            config[key] = value

    problems.extend(_scope_problems(project, local, local_exists))
    problems.extend(validate(config))
    return config, problems


def validate(config):
    """Return a list of problems. An empty list means the config is usable as-is."""
    problems = []

    for key in sorted(REQUIRED_KEYS - set(config)):
        problems.append("missing required key: {}".format(key))

    for key in sorted((REQUIRED_KEYS - NULLABLE_KEYS) & set(config)):
        if config[key] is None:
            problems.append(
                "{}: is null. Only test_command and changelog_dir may be null; "
                "everything else null means the probe found nothing and said "
                "nothing.".format(key)
            )

    for key in sorted(set(config) - KNOWN_KEYS):
        if SECRET_RE.search(key):
            problems.append(
                "{}: looks like a credential. This file is committed -- secrets never "
                "go here; gh holds its own auth.".format(key)
            )
        else:
            problems.append("{}: unknown key (typo, or a schema change nobody wrote down)".format(key))

    repo = config.get("repo")
    if repo is not None and not (isinstance(repo, str) and REPO_RE.match(repo)):
        problems.append("repo: expected 'owner/name', got {!r}".format(repo))

    labels = config.get("labels")
    if labels is not None:
        if not isinstance(labels, dict):
            problems.append("labels: expected an object with 'priority' and 'lanes'")
        else:
            for field in ("priority", "lanes"):
                if not isinstance(labels.get(field), list):
                    problems.append("labels.{}: expected a list (an empty one is fine)".format(field))

    ci = config.get("ci")
    if ci is not None:
        if not isinstance(ci, dict) or not isinstance(ci.get("required_checks"), int):
            problems.append("ci.required_checks: expected an integer")

    for field in ("version_sites", "docs_targets"):
        if field in config and not isinstance(config[field], list):
            problems.append("{}: expected a list".format(field))

    changelog_dir = changelog_dir_problem(config.get("changelog_dir"))
    if changelog_dir:
        problems.append(changelog_dir)

    if "release" in config:
        problems.extend(_validate_release(config["release"]))

    return problems


def _validate_release(release):
    """Validate the release block. Null fields are allowed and mean 'not observed'."""
    if not isinstance(release, dict):
        return ["release: expected an object, got {}".format(type(release).__name__)]

    problems = []

    for key in sorted(set(release) - RELEASE_KEYS):
        problems.append(
            "release.{}: unknown key. The release gates are not configurable -- green at "
            "leg level, nothing mid-review, audit passed, every version site bumped, tag "
            "verified on the remote -- so a key that reads like one is refused rather "
            "than ignored.".format(key)
        )

    for key in ("tag_pattern", "commit_subject"):
        value = release.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or VERSION_PLACEHOLDER not in value:
            problems.append(
                "release.{}: must contain {}, got {!r}. Without it every release "
                "produces the same string, and the second one collides with the "
                "first.".format(key, VERSION_PLACEHOLDER, value)
            )

    merge_method = release.get("merge_method")
    if merge_method is not None and merge_method not in MERGE_METHODS:
        problems.append(
            "release.merge_method: expected one of {}, got {!r}".format(
                ", ".join(sorted(MERGE_METHODS)), merge_method
            )
        )

    for key in PUBLISH_KEYS:
        value = release.get(key)
        if value is not None and not isinstance(value, bool):
            problems.append(
                "release.{}: expected true or false, got {!r}. Every non-empty string is "
                "truthy, so a value spelled like a decision publishes when it reads like "
                "a refusal.".format(key, value)
            )

    if release.get("draft") is True and release.get("latest") is True:
        problems.append(
            "release.latest: a draft cannot be marked Latest, so this pair states an "
            "outcome the release path can never produce. Set release.draft to false to "
            "publish and mark Latest, or release.latest to false to keep the draft."
        )

    triggers = release.get("triggers")
    if triggers is not None:
        if not isinstance(triggers, dict):
            problems.append("release.triggers: expected an object")
        else:
            for key in sorted(set(triggers) - TRIGGER_KEYS):
                problems.append("release.triggers.{}: unknown key".format(key))
            for key in sorted(TRIGGER_KEYS & set(triggers)):
                value = triggers[key]
                if value is not None and not isinstance(value, int):
                    problems.append(
                        "release.triggers.{}: expected a number, got {!r}".format(key, value)
                    )

    return problems


def release_commit_subject(config):
    """The subject line the release commit is made with.

    Null in the config is honest -- the probe cannot observe a house style it has never
    seen -- but a null still has to become a string before anything commits, and the
    only thing downstream of an undefined null is an agent writing whatever it likes.
    """
    release = config.get("release")
    if not isinstance(release, dict):
        release = {}
    value = release.get("commit_subject")
    if value is None:
        return DEFAULT_COMMIT_SUBJECT
    return value


def release_publish_policy(config):
    """Whether the tag becomes a GitHub Release, and what kind (#58).

    Returns `create`, `draft`, `latest` -- and `stated`, which is the one that keeps
    this honest. A repo that has never chosen and a repo that chose not to publish
    produce the same three booleans and must not produce the same sentence: the first
    is told which key would change it, the second is reported as the decision it is.
    """
    release = config.get("release") if isinstance(config, dict) else None
    if not isinstance(release, dict):
        release = {}

    policy = {
        "create": PUBLISH_DEFAULTS["create"],
        "draft": PUBLISH_DEFAULTS["draft"],
        "latest": PUBLISH_DEFAULTS["latest"],
        "stated": False,
    }

    for key, field in zip(PUBLISH_KEYS, ("create", "draft", "latest")):
        value = release.get(key)
        if isinstance(value, bool):
            policy[field] = value

    # `stated` is about `create_release` alone, and deliberately not a union over the
    # three keys. A repo that set only `draft` has said how it would publish, not
    # whether to -- and a union here reported that repo as having chosen not to
    # publish, in those words, which is a decision it never made rendered exactly like
    # one it did. That is this module's own defect class inside the accessor written
    # to prevent it.
    policy["stated"] = isinstance(release.get("create_release"), bool)

    return policy


def _infer_tag_pattern(tags):
    """Derive the tag spelling from tags that exist, or None when none are recognised."""
    for tag in tags or []:
        for pattern, template in TAG_SCHEMES:
            if pattern.match(str(tag)):
                return template
    return None


def build(probe):
    """Derive a config from what was actually observed on the repo.

    ``probe`` carries only measurements, in the shape `--probe` writes and `--help`
    documents. A probe that is not that shape raises `ProbeError` instead of deriving
    around the gap: absent used to read as empty, and the config that came out was
    indistinguishable from one that had been measured.

    Nothing here invents. Anything the probe measured as empty comes out empty.
    """
    problems = probe_problems(probe)
    if problems:
        raise ProbeError("\n".join(problems))

    labels = list(probe.get("labels") or [])
    files = list(probe.get("files") or [])
    jobs = list(probe.get("workflow_jobs") or [])

    test_command = None
    for marker, command in TEST_COMMANDS:
        if marker in files:
            test_command = command
            break
    if test_command is None and any(
        f.startswith("tests/") and f.endswith(".py") and "test" in f.rsplit("/", 1)[-1]
        for f in files
    ):
        # A plain unittest layout: no manifest to key on, tests plainly present. Found
        # by probing a real repo that reported null while its tests sat in tests/.
        test_command = "python3 -m unittest discover -s tests"

    # A candidate the probe read and found a version in. Existence is not evidence:
    # every repo has a README.md and most of them carry no version anywhere.
    evidence = probe.get("version_evidence") or {}
    version_sites = [
        candidate
        for candidate, _ in VERSION_CANDIDATES
        if candidate in files and evidence.get(candidate) == "version"
    ]

    classified = classify_labels(labels)

    docs_targets = [doc for doc in ("README.md",) if doc in files]

    repo_name = (probe.get("repo") or "/").split("/")[-1]

    return {
        "repo": probe.get("repo"),
        "default_branch": probe.get("default_branch"),
        "clone": probe.get("clone"),
        "worktree_root": "{}-wt".format(probe.get("clone")) if probe.get("clone") else None,
        "branch_pattern": "fix/{issue}",
        "test_command": test_command,
        "version_sites": version_sites,
        # A prefix, not a membership test: `git ls-files` prints files and never the
        # directories holding them, so asking whether "changelog.d" is in the list is
        # asking a question the answer can never be yes to.
        "changelog_dir": (
            "changelog.d"
            if any(name.startswith("changelog.d/") for name in files)
            else None
        ),
        "docs_targets": docs_targets,
        "labels": {"priority": classified["priority"], "lanes": classified["lanes"]},
        "milestones": list(probe.get("milestones") or []),
        "ci": {"required_checks": len(jobs)},
        "state_file": ".max/{}-watch.json".format(repo_name) if repo_name else ".max/oss-watch.json",
        "release": {
            # Both derived from what the repo already does. Null means the probe could
            # not tell, and /oss:release refuses on a null rather than inventing one.
            "tag_pattern": _infer_tag_pattern(probe.get("tags")),
            "merge_method": probe.get("merge_method"),
            # Not observable, and cosmetic: the subject line is written by whoever cuts
            # the release. Left null so it is a decision rather than a house style
            # arriving from a tool that has never read this repo's history.
            "commit_subject": None,
            # These two ARE defaults rather than measurements, and deliberately so: the
            # loop states them as decisions to be overridden, and they sit in the file
            # where they can be seen and argued with.
            "triggers": {"merged_prs": 10, "soak_hours": 48},
        },
    }


def _write_json(path, document):
    Path(path).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _repoint_git_exclude(root):
    """Exclude the machine half, stop excluding the project half.

    The exclusion is half the defect: `.git/info/exclude` is not copied by `git clone`,
    so the second maintainer inherits neither the file nor the reason it was hidden.
    Doing this by hand is the per-maintainer decision this whole change removes.
    """
    exclude = Path(root) / ".git" / "info" / "exclude"
    if not exclude.is_file():
        return [
            "no .git/info/exclude here, so the exclusion was not touched -- make sure "
            "{} is ignored before committing anything".format(LOCAL_CONFIG_NAME)
        ]
    before = exclude.read_text(encoding="utf-8")
    kept = [line for line in before.splitlines() if line.strip() != CONFIG_NAME]
    if LOCAL_CONFIG_NAME not in [line.strip() for line in kept]:
        kept.append(LOCAL_CONFIG_NAME)
    after = "\n".join(kept) + "\n"
    if after == before:
        return []
    exclude.write_text(after, encoding="utf-8")
    return [
        ".git/info/exclude: {} excluded, {} no longer".format(LOCAL_CONFIG_NAME, CONFIG_NAME)
    ]


def _ignore_rule(root, name):
    """Is ``name`` still ignored? ``(state, detail)`` -- clear, ignored, or unknown.

    `.git/info/exclude` is the only ignore source this script may rewrite; a `.gitignore`
    belongs to whoever maintains the repo. So repointing the exclude file does not
    establish that the project half can be committed, and saying so anyway reports the
    action taken rather than the state produced -- which is how this plugin's own repo
    ended up with a correct `.oss.json` that `git add` silently refused.

    `git check-ignore` exits 1 for "not ignored", so the shared `_run` helper cannot be
    used here: it folds every non-zero exit into failure, and that would render a clean
    answer as an unknown one.
    """
    command = ["git", "-C", str(root), "check-ignore", "-v", "--", name]
    try:
        done = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
    except OSError as exc:
        return "unknown", "git would not start ({})".format(exc)
    if done.returncode == 0:
        first = (done.stdout or "").strip().splitlines()
        return "ignored", first[0].split("\t")[0] if first else name
    if done.returncode == 1:
        return "clear", ""
    stderr = (done.stderr or "").strip().splitlines()
    return "unknown", stderr[-1] if stderr else "git check-ignore exited {}".format(done.returncode)


def split_config_file(path):
    """Migrate a combined config in place. Returns ``(problems, notes)``.

    Same command for both audiences, deliberately: the repo that already has a combined
    `.oss.json` and the fresh `/oss:setup` that has just written one run the identical
    step, so there is one migration to get right rather than a migration and a happy
    path that drift.

    Idempotent. A project half with no machine keys and a machine half already on disk is
    an already-split repo, and re-running must not rewrite either file -- a migration you
    are afraid to repeat is one nobody runs twice, including after a bad merge.
    """
    path = Path(path)
    if not path.is_file():
        return ["{}: not found. Run /oss:setup to write it.".format(path)], []
    document, problem = _read_json_object(path)
    if problem is not None:
        return [problem], []

    project, local = split(document)
    target = local_config_path(path)
    notes = []

    if not local and target.is_file():
        notes.append("{}: already split; no key moved.".format(path.name))
    else:
        _write_json(target, local)
        _write_json(path, project)
        notes.append(
            "{}: {} machine-scoped key(s) -- {}".format(
                target.name, len(local), ", ".join(sorted(local)) or "none"
            )
        )
        notes.append("{}: {} project-scoped key(s)".format(path.name, len(project)))

    notes.extend(_repoint_git_exclude(path.parent))

    state, detail = _ignore_rule(path.parent, path.name)
    if state == "clear":
        notes.append("{}: nothing ignores it, now safe to track".format(path.name))
    elif state == "ignored":
        notes.append(
            "{}: still ignored by {} -- that rule is yours to change, and until it does "
            "`git add` refuses the project half without saying so".format(path.name, detail)
        )
    else:
        notes.append(
            "{}: could not ask git whether anything ignores it ({}). Unchecked is not "
            "unignored -- run `git check-ignore -v {}` where the repo is".format(
                path.name, detail, path.name
            )
        )
    notes.append(
        "git add {} -- committing the project half is the point, and it is the one step "
        "this script leaves to you".format(path.name)
    )
    return [], notes


def ensure_worktree_root(config):
    """Create the worktree root if it is missing. Returns what happened.

    The rule this sits under: **create containers, never content.** An empty directory
    asserts nothing, so making one is free and removes a permanent warning. A file
    asserts something -- an identity file claims who somebody is, a state file claims a
    tick happened -- and inventing either is how a default becomes a lie.

    A path occupied by a file is refused rather than replaced: deleting somebody else's
    file to make room is not a default, it is a loss.
    """
    value = config.get("worktree_root")
    if not value:
        return "unset"
    path = Path(os.path.expanduser(str(value)))
    if path.is_dir():
        return "present"
    if path.exists():
        return "blocked"
    try:
        path.mkdir(parents=True)
    except OSError:
        return "blocked"
    return "created"


def verify_test_command(command, cwd, timeout=120):
    """Run the detected test command and say what happened.

    Detection reads a marker file and infers; this executes and measures. The states
    differ in remedy, so they are kept apart: `failed` is a suite to fix, `not-found`
    is a runner to install, and `timeout` is **unverified** rather than broken --
    reporting broken would send someone to debug a suite that is merely slow.
    """
    if not command:
        return {"state": "none", "detail": "no test command detected; nothing to verify"}

    # The runner is resolved before anything runs, because the shell's own
    # "command not found" code is not portable: POSIX shells answer 127, cmd.exe
    # answers 9009, and on a GitHub Windows runner it answered neither -- so a
    # runner that was never installed reported as a suite that ran and failed,
    # which is the one confusion these states exist to prevent. Only for a plain
    # command: with an operator in it the first word is not the whole story, and a
    # shell builtin resolves to no file at all.
    if not any(token in command for token in ("&&", "||", "|", ";", ">", "<", "$(", "`")):
        try:
            words = shlex.split(command, posix=os.name != "nt")
        except ValueError:
            words = []
        if words and shutil.which(words[0]) is None:
            return {
                "state": "not-found",
                "detail": "{!r}: {!r} is not on PATH".format(command, words[0]),
            }

    try:
        done = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "state": "timeout",
            "detail": "{!r} did not finish within {}s, so it is unverified -- which is "
            "not the same as broken.".format(command, timeout),
        }
    except OSError as exc:
        return {"state": "not-found", "detail": "{!r} would not start ({})".format(command, exc)}

    if done.returncode == 0:
        return {"state": "ok", "detail": "{!r} ran and passed".format(command)}

    tail = (done.stdout or "").strip().splitlines()[-1:] or [""]
    # 127 is the POSIX shell's own "command not found", and 9009 is cmd.exe's, which
    # is a different problem from a suite that ran and failed. Reading only 127 makes
    # every missing runner on Windows report as a failing suite -- the exact confusion
    # between "install this" and "fix this" the states exist to prevent.
    if done.returncode in (127, 9009):
        return {
            "state": "not-found",
            "detail": "{!r}: command not found ({})".format(command, tail[0]),
        }
    return {
        "state": "failed",
        "detail": "{!r} exited {} -- {}".format(command, done.returncode, tail[0]),
    }


def resolve_worktree(root, target):
    """Resolve a single worktree directory name under ``root``.

    A worktree target is a bare name. Absolute paths, drive prefixes, UNC paths,
    traversals and anything carrying a separator are refused **before** resolution,
    and the resolved path is checked to still sit under the root afterwards -- a
    symlink swapped between those two checks is exactly the gap this closes.

    Returns the resolved Path so the caller reuses this one value rather than
    re-deriving it from the raw name.
    """
    if not isinstance(target, str) or not target.strip():
        raise ContainmentError("worktree target is empty")
    if target in (".", ".."):
        raise ContainmentError("worktree target {!r} is a traversal".format(target))
    if "/" in target or "\\" in target:
        raise ContainmentError(
            "worktree target {!r} contains a path separator; expected a bare name".format(target)
        )
    if os.path.isabs(target) or re.match(r"^[A-Za-z]:", target):
        raise ContainmentError("worktree target {!r} is not relative".format(target))

    root = Path(root).resolve()
    resolved = (root / target).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ContainmentError(
            "worktree target {!r} resolves to {} which is outside {}".format(target, resolved, root)
        )
    return resolved


def _run(command, cwd=None):
    """Return ``(ok, stdout, detail)``. ``detail`` is why not, when not."""
    try:
        done = subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
    except OSError as exc:
        return False, "", "{} would not start ({})".format(command[0], exc)
    if done.returncode != 0:
        lines = (done.stderr or "").strip().splitlines()
        return (
            False,
            "",
            "{} exited {}: {}".format(
                " ".join(command[:3]), done.returncode, lines[-1] if lines else "no output"
            ),
        )
    return True, done.stdout, ""


def _git_lines(root, args):
    return _run(["git", "-C", str(root)] + list(args))


def _gh_json(root, args):
    """Run gh and parse its JSON. Seam: the tests replace this, not subprocess."""
    ok, out, detail = _run(["gh"] + list(args), cwd=root)
    if not ok:
        return False, None, detail
    try:
        return True, json.loads(out), ""
    except ValueError as exc:
        return False, None, "gh {} did not return JSON ({})".format(args[0], exc)


def _workflow_jobs(root, files):
    """Job names read out of the workflow files, as ``file:job``.

    A light scan rather than a YAML parse: this module has no third-party imports and
    the shape being read is two levels deep. A workflow that cannot be read is
    reported -- counting it as zero jobs would understate the required checks, which
    is the direction that lets a red leg through.
    """
    jobs = []
    problems = []
    for rel in sorted(files):
        if not rel.startswith(".github/workflows/") or not rel.endswith((".yml", ".yaml")):
            continue
        try:
            text = (Path(root) / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            problems.append("could not read {} ({})".format(rel, exc))
            continue
        stem = rel.rsplit("/", 1)[-1]
        in_jobs = False
        for line in text.splitlines():
            if re.match(r"^jobs:\s*$", line):
                in_jobs = True
                continue
            if not in_jobs:
                continue
            if line.strip() and not line.startswith((" ", "\t")):
                in_jobs = False
                continue
            match = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
            if match:
                jobs.append("{}:{}".format(stem, match.group(1)))
    return jobs, problems


def _merge_method(view):
    """The repo's merge method, or None when more than one is allowed.

    Two allowed methods is not a preference the repo has stated, so there is nothing
    to measure and null is the answer. /oss:release refuses on a null rather than
    picking one.
    """
    allowed = [
        name
        for flag, name in (
            ("squashMergeAllowed", "squash"),
            ("mergeCommitAllowed", "merge"),
            ("rebaseMergeAllowed", "rebase"),
        )
        if view.get(flag)
    ]
    return allowed[0] if len(allowed) == 1 else None


def gather(root):
    """Measure a repo directory into a probe. Returns ``(probe, problems)``.

    This exists so the schema has exactly one implementation. The slash command used
    to assemble the probe by hand, got `files` wrong in a way nothing could detect,
    and the derived config was confidently wrong at every layer.

    A probe is returned only when every field in it was measured. A half-measured
    probe is the underspecified probe this whole contract exists to refuse, and
    emitting one with the unmeasured half left empty is exactly the failure --
    "gh could not be reached" would reach disk spelled `"labels": []`.
    """
    root = Path(os.path.expanduser(str(root)))

    ok, out, detail = _git_lines(root, ["ls-files", "-z"])
    if not ok:
        return None, ["could not list the files: {}".format(detail)]
    files = [name for name in out.split("\0") if name]

    ok, out, detail = _git_lines(root, ["tag", "--list"])
    if not ok:
        return None, ["could not list the tags: {}".format(detail)]
    tags = [line.strip() for line in out.splitlines() if line.strip()]

    problems = []
    ok, view, detail = _gh_json(
        root,
        [
            "repo",
            "view",
            "--json",
            "nameWithOwner,defaultBranchRef,squashMergeAllowed,mergeCommitAllowed,"
            "rebaseMergeAllowed",
        ],
    )
    if not ok or not isinstance(view, dict):
        return None, ["could not read the repo from gh: {}".format(detail or view)]

    repo = view.get("nameWithOwner")
    ok, label_rows, detail = _gh_json(root, ["label", "list", "--json", "name", "--limit", "200"])
    if not ok:
        problems.append("could not read the labels from gh: {}".format(detail))
        label_rows = []

    ok, milestone_rows, detail = _gh_json(
        root, ["api", "repos/{}/milestones".format(repo), "--paginate"]
    )
    if not ok:
        problems.append("could not read the milestones from gh: {}".format(detail))
        milestone_rows = []

    jobs, job_problems = _workflow_jobs(root, files)
    problems.extend(job_problems)

    probe = {
        "repo": repo,
        "default_branch": (view.get("defaultBranchRef") or {}).get("name"),
        "clone": str(root.resolve()),
        "files": files,
        "tags": tags,
        "labels": [row.get("name") for row in label_rows or [] if row.get("name")],
        "milestones": [row.get("title") for row in milestone_rows or [] if row.get("title")],
        "workflow_jobs": jobs,
        "merge_method": _merge_method(view),
        "version_evidence": inspect_version_sites(root, files),
    }
    problems.extend(probe_problems(probe))
    if problems:
        return None, problems
    return probe, []


def _report_probe_notes(probe):
    """Say what the probe saw and could not classify. Neither is a failure.

    Both are absences the tool produced rather than absences in the world, and both
    are invisible in the config: unclassified labels leave `priority: []`, and an
    unreadable candidate leaves it off `version_sites`. Silence there reads as a
    measurement, so the difference is stated here instead.
    """
    unclassified = classify_labels(probe.get("labels") or [])["unclassified"]
    if unclassified:
        print(
            "NOTE {} of {} labels matched no priority or lane pattern, so they are "
            "unclassified: {}".format(
                len(unclassified),
                len(probe.get("labels") or []),
                ", ".join(unclassified),
            ),
            file=sys.stderr,
        )
    unreadable = sorted(
        name for name, state in (probe.get("version_evidence") or {}).items()
        if state == "unreadable"
    )
    if unreadable:
        print(
            "NOTE could not read, so not claimed as version sites: {}".format(
                ", ".join(unreadable)
            ),
            file=sys.stderr,
        )


def _main(argv=None):
    """CLI used by /oss:setup and /oss:doctor.

    `--validate` names every problem and exits non-zero; `--probe` measures a repo
    into a probe; `--build` reads a probe as JSON on stdin and writes a config to
    stdout, so the measuring and the deriving stay separable and the derive half is
    testable without a network.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Read, validate and derive .oss.json.",
        epilog=PROBE_SCHEMA_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--validate", metavar="PATH", help="validate an existing .oss.json")
    group.add_argument(
        "--split",
        metavar="PATH",
        help="split a combined .oss.json into the tracked project half and the "
        "git-excluded {} beside it, and repoint .git/info/exclude. Idempotent".format(
            LOCAL_CONFIG_NAME
        ),
    )
    group.add_argument(
        "--probe",
        metavar="REPO",
        help="measure a repo directory and write a probe as JSON on stdout "
        "(the only sanctioned way to build one -- see the schema below)",
    )
    group.add_argument(
        "--build",
        action="store_true",
        help="read a probe as JSON on stdin, write the derived config to stdout. "
        "A probe of the wrong shape is refused, not derived around",
    )
    args = parser.parse_args(argv)

    if args.validate:
        config, problems = load(args.validate)
        for problem in problems:
            print("FAIL {}".format(problem))
        if config is not None and not problems:
            print("OK {} validates".format(args.validate))
        return 1 if problems else 0

    if args.split:
        problems, notes = split_config_file(args.split)
        for problem in problems:
            print("FAIL {}".format(problem))
        for note in notes:
            print("OK {}".format(note))
        return 1 if problems else 0

    if args.probe:
        probe, problems = gather(args.probe)
        for problem in problems:
            print("FAIL {}".format(problem), file=sys.stderr)
        if probe is None:
            return 1
        print(json.dumps(probe, indent=2))
        return 0

    try:
        probe = json.load(sys.stdin)
    except ValueError as exc:
        print("FAIL probe on stdin is not valid JSON ({})".format(exc))
        return 1
    try:
        config = build(probe)
    except ProbeError as exc:
        for line in str(exc).splitlines():
            print("FAIL {}".format(line), file=sys.stderr)
        return 1
    _report_probe_notes(probe)
    problems = validate(config)
    for problem in problems:
        print("FAIL derived config: {}".format(problem), file=sys.stderr)
    print(json.dumps(config, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(_main())
