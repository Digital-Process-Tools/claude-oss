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

PRIORITY_RE = re.compile(r"^priority[-:]")
LANE_RE = re.compile(r"^lane[-:]")

# Ordered: the first entry whose marker file is present wins.
TEST_COMMANDS = [
    ("pyproject.toml", "pytest"),
    ("tests/run-all.sh", "bash tests/run-all.sh"),
    ("package.json", "npm test"),
    ("Cargo.toml", "cargo test"),
]


class ContainmentError(Exception):
    """A path derived from config or a branch name tried to leave its root."""


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

    ``probe`` carries only measurements: repo, default_branch, clone, labels,
    milestones, workflow_jobs, files. Anything absent from the probe comes out as an
    empty list or None -- never as a default, because the caller cannot tell a default
    from a finding once it is written to disk.
    """
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

    version_sites = [
        site
        for site in (".claude-plugin/plugin.json", "CHANGELOG.md", "README.md", "pyproject.toml")
        if site in files
    ]

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
        "changelog_dir": "changelog.d" if "changelog.d" in files else None,
        "docs_targets": docs_targets,
        "labels": {
            "priority": [label for label in labels if PRIORITY_RE.match(label)],
            "lanes": [label for label in labels if LANE_RE.match(label)],
        },
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
    # 127 is the shell's own "command not found", which is a different problem from a
    # suite that ran and failed.
    if done.returncode == 127:
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


def _main(argv=None):
    """CLI used by /oss:setup and /oss:doctor.

    `--validate` names every problem and exits non-zero; `--build` reads a probe as
    JSON on stdin and writes a config to stdout, so the measuring and the deriving
    stay separable and the derive half is testable without a network.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Read, validate and derive .oss.json.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--validate", metavar="PATH", help="validate an existing .oss.json")
    group.add_argument(
        "--build",
        action="store_true",
        help="read a probe as JSON on stdin, write the derived config to stdout",
    )
    args = parser.parse_args(argv)

    if args.validate:
        config, problems = load(args.validate)
        for problem in problems:
            print("FAIL {}".format(problem))
        if config is not None and not problems:
            print("OK {} validates".format(args.validate))
        return 1 if problems else 0

    try:
        probe = json.load(sys.stdin)
    except ValueError as exc:
        print("FAIL probe on stdin is not valid JSON ({})".format(exc))
        return 1
    config = build(probe)
    problems = validate(config)
    for problem in problems:
        print("FAIL derived config: {}".format(problem), file=sys.stderr)
    print(json.dumps(config, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(_main())
