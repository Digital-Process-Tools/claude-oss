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

# What a repo does when it releases differs, so it is configured. What must NEVER be
# configured is the gate list -- default branch green at leg level, nothing mid-review,
# security audit passed, every version site bumped, the tag verified on the remote. A
# gate that can be switched off is switched off on the day it is inconvenient, which is
# the day it existed for. Keys that look like gates are refused, not ignored: an ignored
# key reads as an accepted setting.
RELEASE_KEYS = {"tag_pattern", "commit_subject", "merge_method", "triggers"}
MERGE_METHODS = {"squash", "merge", "rebase"}
TRIGGER_KEYS = {"merged_prs", "soak_hours"}

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

# A config file is committed. Nothing in it may look like a credential, and an
# unfamiliar key that does is refused rather than ignored -- ignoring it is how a
# token ends up in git history with everyone assuming the schema rejected it.
SECRET_RE = re.compile(r"(token|password|passwd|secret|api[_-]?key|credential)", re.IGNORECASE)

REPO_RE = re.compile(r"^[^/\s]+/[^/\s]+$")

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


def load(path):
    """Return ``(config, problems)``.

    ``config`` is None when the file could not be read or parsed. Problems are
    sentences, not codes -- they are printed to a human by `doctor`.
    """
    path = Path(path)
    if not path.is_file():
        return None, ["{}: not found. Run /oss:setup to write it.".format(path)]
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, ["{}: could not read ({})".format(path, exc)]
    try:
        config = json.loads(raw)
    except ValueError as exc:
        return None, ["{}: could not parse as JSON ({})".format(path, exc)]
    if not isinstance(config, dict):
        return None, ["{}: could not parse as a JSON object".format(path)]
    return config, validate(config)


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
