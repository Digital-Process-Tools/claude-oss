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

OPTIONAL_KEYS = {"milestones", "notes"}

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

    return problems


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
