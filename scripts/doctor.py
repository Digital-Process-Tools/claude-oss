"""Diagnose an oss-managed repo: config, dependencies, clone, worktree root, state.

Contract, and every line of it is load-bearing:

* **Exit code 0, always.** A diagnostic must print its findings, not fail to run.
* **Three states: OK / WARN / FAIL.** WARN is "the check ran and could not answer".
  A check that cannot answer must never render as a check that found nothing.
* **One VERDICT line, last.** Greppable, so a human can paste the tail.
* **No colour.** Git Bash renders escapes as noise, and this output gets pasted.
* **Never echo a value that could be a credential** -- name the key, print nothing.

Python 3.9 compatible.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent

sys.path.insert(0, str(SCRIPT_DIR))

try:
    import oss_config
except ImportError:  # pragma: no cover - the module sits beside this file
    oss_config = None

FINDINGS = []


def report(state, message):
    FINDINGS.append((state, message))
    print("{} {}".format(state, message))


def plugin_version():
    """Read the manifest directly, with no path resolution in the way -- this line
    must print even when everything else has failed.
    """
    manifest = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("version", "unknown")
    except (OSError, ValueError):
        return "unreadable"


def check_config(project_dir):
    path = project_dir / ".oss.json"
    if oss_config is None:
        report("FAIL", "scripts/oss_config.py could not be imported; config was not checked")
        return None
    config, problems = oss_config.load(path)
    if config is None:
        for problem in problems:
            report("FAIL", problem)
        return None
    if problems:
        for problem in problems:
            # Problems name keys, never values: `problem` is built from key names
            # and type expectations only.
            report("FAIL", ".oss.json: {}".format(problem))
    else:
        report("OK", ".oss.json parsed and validated ({} keys)".format(len(config)))
    return config


def check_tool(name, probe):
    if shutil.which(name) is None:
        report("WARN", "{}: not on PATH; anything needing it will be skipped".format(name))
        return
    try:
        done = subprocess.run(
            probe,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        report("WARN", "{}: found on PATH but would not run ({})".format(name, exc))
        return
    if done.returncode == 0:
        report("OK", "{}: available".format(name))
    else:
        report("WARN", "{}: present but returned {}".format(name, done.returncode))


def check_directory(label, value):
    if not value:
        report("WARN", "{}: not set in config; cannot check it".format(label))
        return
    path = Path(os.path.expanduser(str(value)))
    if path.is_dir():
        report("OK", "{}: {}".format(label, path))
    else:
        report("WARN", "{}: {} does not exist".format(label, path))


def check_state_file(project_dir, config):
    value = config.get("state_file")
    if not value:
        report("WARN", "state_file: not set in config")
        return
    path = project_dir / str(value)
    if path.is_file():
        report("OK", "state_file: {}".format(path))
    else:
        report("WARN", "state_file: {} not written yet (first tick will create it)".format(path))


MEMORY_DIR = ".remember"
JIT_RULES_DIR = ".claude/jit-context"
JIT_INDEX = "00-index.tsv"


def check_memory(project_dir):
    """Is the memory plugin configured, or merely installed?

    Installed-and-unconfigured is the invisible state: it still runs and still saves.
    What it cannot do is say whose sessions these are.
    """
    store = Path(project_dir) / MEMORY_DIR
    if not store.is_dir():
        report(
            "WARN",
            "{}: no memory store in this project. The remember plugin is installed as a "
            "dependency but has nothing here yet; it will create one on first save.".format(
                MEMORY_DIR
            ),
        )
        return
    identity = list(store.glob("identity*.md"))
    if not identity:
        report(
            "WARN",
            "{}: no identity file. Sessions are being saved without recording whose they "
            "are, which looks like a working setup because saving is the half that "
            "works.".format(MEMORY_DIR),
        )
        return
    report("OK", "memory store configured ({})".format(identity[0].name))


def check_jit_rules(project_dir):
    """Rules on disk are not rules in effect.

    The matcher reads the index, not the markdown. A rule whose row is missing never
    fires, and a rule that never fires is indistinguishable from one that fired and had
    nothing to say -- so a missing or empty index is a FAIL, not a warning.
    """
    rules_dir = Path(project_dir) / JIT_RULES_DIR
    if not rules_dir.is_dir():
        report(
            "WARN",
            "{}: no rules for this repo. Project conventions are not being injected; "
            "nothing is broken, but nothing is being carried either.".format(JIT_RULES_DIR),
        )
        return

    rules = sorted(p for p in rules_dir.rglob("*.md") if p.is_file())
    if not rules:
        report("WARN", "{}: directory exists but holds no rules".format(JIT_RULES_DIR))
        return

    index = rules_dir / JIT_INDEX
    if not index.is_file():
        report(
            "FAIL",
            "{} rule(s) present and no {} -- the matcher reads the index, so none of them "
            "run, and that is indistinguishable from rules that matched nothing. "
            "Rebuild the index.".format(len(rules), JIT_INDEX),
        )
        return
    if not index.read_text(encoding="utf-8").strip():
        report(
            "FAIL",
            "{} is empty beside {} rule(s). An empty table is the same silence as a "
            "missing one, and it is the one that passes an existence check. "
            "Rebuild the index.".format(JIT_INDEX, len(rules)),
        )
        return

    index_mtime = index.stat().st_mtime
    newer = [p.name for p in rules if p.stat().st_mtime > index_mtime]
    if newer:
        report(
            "WARN",
            "{} is stale: {} changed after the last rebuild, so its row says something "
            "else. Rebuild the index.".format(JIT_INDEX, ", ".join(newer[:3])),
        )
        return

    report("OK", "{} rule(s) indexed and current".format(len(rules)))


def main():
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())

    report("OK", "oss plugin version {}".format(plugin_version()))
    # CLAUDE_PROJECT_DIR reaches hooks, not the Bash tool, so this is often a guess.
    # Say that it is one rather than presenting it as resolved.
    if not os.environ.get("CLAUDE_PROJECT_DIR"):
        report("WARN", "project dir guessed from cwd: {}".format(project_dir))
    else:
        report("OK", "project dir: {}".format(project_dir))

    config = check_config(project_dir)

    check_tool("gh", ["gh", "auth", "status"])
    check_tool("supertool", ["supertool", "version"])
    check_tool("git", ["git", "--version"])

    if config is not None:
        check_directory("clone", config.get("clone"))
        check_directory("worktree_root", config.get("worktree_root"))
        check_state_file(project_dir, config)

    # Declared dependencies install automatically; they do not configure themselves,
    # and the unconfigured state is the one that still appears to work.
    check_memory(project_dir)
    check_jit_rules(project_dir)

    fails = sum(1 for state, _ in FINDINGS if state == "FAIL")
    warns = sum(1 for state, _ in FINDINGS if state == "WARN")
    if fails:
        verdict = "not usable -- {} failure(s), {} warning(s)".format(fails, warns)
    elif warns:
        verdict = "usable with gaps -- {} warning(s)".format(warns)
    else:
        verdict = "ok"
    print("VERDICT: {}".format(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
