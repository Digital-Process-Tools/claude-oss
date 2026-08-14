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

try:
    import scaffold
except ImportError:  # pragma: no cover - the module sits beside this file
    scaffold = None

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


MEMORY_CONFIG_DIR = ".claude/remember"


def memory_layout(project_dir):
    """Where the memory plugin keeps its config and its saved sessions.

    Two different places: `config.json` sits in `.claude/remember/`, while sessions go
    to the `data_dir` that config names (`.remember` by default).

    identity.md can sit in either, and which one is READ depends on the install layout,
    which is why this went round twice. Measured against the plugin's session-start
    hook rather than reasoned about: it tries `$REMEMBER_DIR/identity.md` (the data
    dir), then the data dir's parent, then the plugin's own directory. In a local
    install the plugin's own directory IS `<repo>/.claude/remember/`, so identity there
    is read -- as the last-resort fallback. In a marketplace or dependency install,
    which is how this plugin declares it, the plugin lives outside the repo entirely
    and `<repo>/.claude/remember/identity.md` is never read at all.

    So the data dir is the location that works in every layout, and it is also the safe
    one: the plugin writes a `.gitignore` containing `*` there, so the file cannot be
    committed by accident. `.claude/` is partly tracked in a scaffolded repo and is not
    safe in the same way.
    """
    root = Path(project_dir)
    config_dir = root / MEMORY_CONFIG_DIR
    data_dir = root / MEMORY_DIR
    try:
        doc = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
        if isinstance(doc, dict) and doc.get("data_dir"):
            data_dir = root / str(doc["data_dir"])
    except (OSError, ValueError):
        pass
    return config_dir, data_dir


def _display(project_dir, path):
    """A path the reader can act on, relative to the repo when it is inside it."""
    try:
        return path.relative_to(Path(project_dir)).as_posix()
    except ValueError:
        return str(path)


def check_memory(project_dir):
    """Is the memory plugin configured, or merely installed?

    Installed-and-unconfigured is the invisible state: it still runs and still saves.
    What is missing is the identity file, which records who the AGENT is in this repo
    and is injected at session start. Without it the loop still works and starts every
    session as nobody in particular.

    Not scaffolded silently. An identity asserts values and a voice, and writing one
    into somebody else's repository picks a persona they did not choose.
    """
    config_dir, store = memory_layout(project_dir)
    if not store.is_dir():
        report(
            "WARN",
            "{}: no memory store in this project. The remember plugin is installed as a "
            "dependency but has nothing here yet; it will create one on first save.".format(
                MEMORY_DIR
            ),
        )
        return
    # identity.md, specifically. An earlier version of this accepted core-memories.md
    # too, because two of our own repos have no identity.md and the warning was
    # inconvenient -- which is widening a check until a real gap disappears. Core
    # memories are what the agent LEARNED; identity is who it is, and it is the file
    # injected at session start. They are not substitutes.
    #
    # Data dir first, because that is the hook's first choice and the only location
    # read in every layout (see memory_layout).
    #
    # Not the same move as accepting core-memories.md, which widened WHAT counts until
    # an inconvenient gap vanished. This matches WHERE we look to where the reader
    # looks, and the config-dir branch below is a WARN precisely so that widening does
    # not turn a file nobody reads into a pass.
    identity = sorted(store.glob("identity*.md"))
    if identity:
        report(
            "OK",
            "memory store configured ({} in {})".format(
                identity[0].name, _display(project_dir, store)
            ),
        )
        return

    stray = sorted(config_dir.glob("identity*.md"))
    if stray:
        # Read only when the plugin is installed INTO the repo, which is what a
        # scripts/ directory beside config.json means. Otherwise the file exists, looks
        # deliberate, and is never injected -- the worst of the three, because every
        # signal says configured. Two of our own repos are in exactly this state.
        if (config_dir / "scripts").is_dir():
            report(
                "OK",
                "memory store configured ({} in {}, local install)".format(
                    stray[0].name, _display(project_dir, config_dir)
                ),
            )
            return
        report(
            "WARN",
            "{} exists but is never read. The plugin is not installed into this repo, so "
            "the session-start hook resolves identity against {} and the plugin's own "
            "directory -- never this one. It looks configured from every angle except the "
            "one that matters. Move it to {}/identity.md.".format(
                _display(project_dir, stray[0]),
                _display(project_dir, store),
                _display(project_dir, store),
            ),
        )
        return
    # Name the paths consulted. The previous message named MEMORY_DIR while the lookup
    # read the config dir, so following it to the letter left the warning byte-for-byte
    # unchanged and gave the reader nothing to tell "wrong place" from "wrong content".
    report(
        "WARN",
        "no identity.md in {} or {}. It records who the AGENT is here -- name, voice, "
        "working style -- and is injected at session start, so without it every session "
        "begins as nobody in particular. Saving still works, which is exactly what makes "
        "the gap invisible. Seed {}/identity.md from the memory plugin's "
        "identity.example.md and edit it -- that directory self-ignores, so the file "
        "cannot be committed by accident.".format(
            _display(project_dir, store),
            _display(project_dir, config_dir),
            _display(project_dir, store),
        ),
    )


# The op the maintainer loop merges with. Matching is on the literal command
# string, so this substring is what an allow rule has to contain in some form --
# `Bash(./supertool 'gh-pr-merge:*')`, an absolute-path spelling of the same, or
# a per-call entry naming one exact merge.
MERGE_OP = "gh-pr-merge"
MERGE_RULE_FILE = ".claude/settings.local.json"


def settings_candidates(project_dir, home=None):
    """Where a permission rule can live. Project scope first, then user scope --
    a rule in either one is a rule, and reading only the project's would WARN at
    a maintainer who already arranged it in their home settings.
    """
    candidates = [
        Path(project_dir) / ".claude" / "settings.json",
        Path(project_dir) / ".claude" / "settings.local.json",
    ]
    if home is None:
        try:
            home = Path.home()
        except RuntimeError:
            # No HOME / USERPROFILE to resolve. User scope is then unreadable, but
            # this is a diagnostic: it exits 0 and reports, it does not traceback.
            return candidates
    return candidates + [
        Path(home) / ".claude" / "settings.json",
        Path(home) / ".claude" / "settings.local.json",
    ]


def _permission_entries(data, key):
    permissions = data.get("permissions")
    if not isinstance(permissions, dict):
        return []
    entries = permissions.get(key)
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, str)]


def merge_permission_state(project_dir, home=None):
    """Is there a settings rule naming the merge op? Four answers, not two.

    `present` / `denied` / `absent` / `unknown`, and the last one is the reason
    this is not a boolean. A settings file that could not be parsed produces no
    matching entry, which looks exactly like a file that was read and had none --
    and the two send a maintainer to opposite places.

    A rule that WAS read settles the question, so an unreadable neighbour does not
    drag a found rule back to `unknown`.
    """
    unreadable = []
    denied = []
    for path in settings_candidates(project_dir, home=home):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            unreadable.append(str(path))
            continue
        if not isinstance(data, dict):
            unreadable.append(str(path))
            continue
        for entry in _permission_entries(data, "allow"):
            if MERGE_OP in entry:
                return "present", "{} in {}".format(entry, path)
        for entry in _permission_entries(data, "deny"):
            if MERGE_OP in entry:
                denied.append("{} in {}".format(entry, path))
    if denied:
        return "denied", "; ".join(denied)
    if unreadable:
        return "unknown", "; ".join(unreadable)
    return "absent", ""


def check_merge_permission(project_dir, home=None):
    """Report the rule, and never more than the rule.

    This is a file read, not a probe of the harness. The harness decides at call
    time and an allowlist entry is one input to that decision -- so `present`
    cannot promise the merge will run, and `absent` cannot promise it will be
    denied. Both messages have to carry that limit, or the check becomes the
    defect it is here to prevent: an OK that reads as a guarantee nobody measured.
    """
    state, detail = merge_permission_state(project_dir, home=home)
    if state == "present":
        report(
            "OK",
            "a settings rule names {} ({}). This is a file read, not a probe of the "
            "harness: it says the rule exists, not that the merge call will be "
            "permitted.".format(MERGE_OP, detail),
        )
        return
    if state == "denied":
        report(
            "WARN",
            "the only settings rule naming {} is a deny rule ({}). The merge step will "
            "stop there.".format(MERGE_OP, detail),
        )
        return
    if state == "unknown":
        report(
            "WARN",
            "could not read {}, so whether a {} rule exists is unknown -- not answered "
            "as absent, because that would send you to add a rule you may already "
            "have.".format(detail, MERGE_OP),
        )
        return
    report(
        "WARN",
        "no settings rule names {}, so the merge step is the place you would find out. "
        "Add one to {} (machine scope, untracked) before the first tick. A rule is not "
        "the only thing that can allow or deny this call, so this is not a prediction "
        "that the merge will fail.".format(MERGE_OP, MERGE_RULE_FILE),
    )


def check_jit_rules(project_dir):
    """Rules on disk are not rules in effect.

    The matcher reads the index, not the markdown. A rule whose row is missing never
    fires, and a rule that never fires is indistinguishable from one that fired and had
    nothing to say -- so a missing or empty index is a FAIL, not a warning.

    Rules are organised per dimension (vocabulary, paths, tools) and per layer inside
    it, and **each layer carries its own index**. Checking one index at the root would
    tell a correctly configured repo that none of its rules run.

    Every layer is reported separately. One indexed layer does not vouch for another:
    stopping at the first healthy one is how a whole dimension goes quiet unnoticed.
    """
    rules_dir = Path(project_dir) / JIT_RULES_DIR
    if not rules_dir.is_dir():
        report(
            "WARN",
            "{}: no rules for this repo. Project conventions are not being injected; "
            "nothing is broken, but nothing is being carried either.".format(JIT_RULES_DIR),
        )
        return

    layers = {}
    for rule in sorted(rules_dir.rglob("*.md")):
        if rule.is_file():
            layers.setdefault(rule.parent, []).append(rule)

    if not layers:
        report("WARN", "{}: directory exists but holds no rules".format(JIT_RULES_DIR))
        return

    for layer in sorted(layers):
        rules = layers[layer]
        name = layer.relative_to(rules_dir)
        index = layer / JIT_INDEX

        if not index.is_file():
            report(
                "FAIL",
                "{}: {} rule(s) and no {} -- the matcher reads the index, so none of "
                "them run, and that is indistinguishable from rules that matched "
                "nothing. Rebuild the index.".format(name, len(rules), JIT_INDEX),
            )
            continue
        if not index.read_text(encoding="utf-8").strip():
            report(
                "FAIL",
                "{}: {} is empty beside {} rule(s). An empty table is the same silence "
                "as a missing one, and it is the one that passes an existence check. "
                "Rebuild the index.".format(name, JIT_INDEX, len(rules)),
            )
            continue

        index_mtime = index.stat().st_mtime
        newer = [p.name for p in rules if p.stat().st_mtime > index_mtime]
        if newer:
            report(
                "WARN",
                "{}: {} is stale -- {} changed after the last rebuild, so its row says "
                "something else. Rebuild the index.".format(
                    name, JIT_INDEX, ", ".join(newer[:3])
                ),
            )
            continue

        report("OK", "{}: {} rule(s) indexed and current".format(name, len(rules)))


def compare_versions(installed, latest):
    """`current` / `behind` / `ahead` / `unknown`.

    Numeric comparison, because `"0.9.0" > "0.10.0"` lexically -- a string compare
    calls a stale install current for exactly the versions where it matters. Anything
    unparseable is `unknown` rather than a guess: reporting `behind` would send someone
    to run an update that changes nothing.
    """

    def parse(value):
        if not isinstance(value, str):
            return None
        parts = value.split(".")
        if not parts or not all(part.isdigit() for part in parts):
            return None
        return tuple(int(part) for part in parts)

    left, right = parse(installed), parse(latest)
    if left is None or right is None:
        return "unknown"
    if left == right:
        return "current"
    return "behind" if left < right else "ahead"


def dependency_findings(installed, latest, declared=None):
    """Judge each dependency. Pure: the fetching lives in its caller.

    Nothing here updates anything. A tool that changes underneath a running session
    changes behaviour mid-flight, and the runtime already owns installation.
    """
    names = sorted(set(declared or []) | set(installed) | set(latest))
    findings = []
    for name in names:
        have, want = installed.get(name), latest.get(name)
        if have is None:
            findings.append(
                {
                    "name": name,
                    "state": "missing",
                    "detail": "{}: declared but not installed. Run `claude plugin install "
                    "{}@dpt-plugins`, then /reload-plugins.".format(name, name),
                }
            )
            continue
        state = compare_versions(have, want)
        if state == "behind":
            detail = (
                "{}: {} installed, {} published. Run `claude plugin update {}` then "
                "/reload-plugins, or enable auto-update for the marketplace.".format(
                    name, have, want, name
                )
            )
        elif state == "unknown":
            detail = (
                "{}: {} installed; the published version could not be read, so this "
                "says nothing about whether it is current.".format(name, have)
            )
        elif state == "ahead":
            detail = "{}: {} installed, {} published — running unreleased code.".format(
                name, have, want
            )
        else:
            detail = "{}: {}".format(name, have)
        findings.append({"name": name, "state": state, "detail": detail})
    return findings


def owned_drift(repo_root, config, plugin_root=None):
    """Compare the files this plugin owns in a repo against what it ships today.

    `/oss:scaffold` replaces them on every run -- but an update to the plugin does not
    run the command, so a repo scaffolded months ago still holds the old copies. This
    is the check that makes that visible rather than assumed.
    """
    root = Path(repo_root)
    plugin_root = Path(plugin_root or SCRIPT_DIR.parent)

    # Without a usable plugin root there is nothing to compare against, and every
    # answer would be a statement about this checkout rather than about the repo.
    if not (plugin_root / "scripts").is_dir():
        return [
            {
                "path": name,
                "state": "unknown",
                "detail": "{}: the plugin's own files could not be read at {}, so no "
                "comparison was made".format(name, plugin_root),
            }
            for name in sorted(scaffold.OWNED)
        ]

    findings = []
    for name in sorted(scaffold.OWNED):
        target = root / name
        try:
            shipped = scaffold.render_owned(name, config, plugin_root)
        except (OSError, scaffold.ScaffoldError) as exc:
            findings.append(
                {
                    "path": name,
                    "state": "unknown",
                    "detail": "{}: could not render the shipped version ({})".format(
                        name, type(exc).__name__
                    ),
                }
            )
            continue

        if not target.is_file():
            findings.append(
                {
                    "path": name,
                    "state": "absent",
                    "detail": "{}: not in this repo. Run /oss:scaffold.".format(name),
                }
            )
            continue

        if target.read_text(encoding="utf-8") == shipped:
            findings.append({"path": name, "state": "current", "detail": name})
        else:
            findings.append(
                {
                    "path": name,
                    "state": "drifted",
                    "detail": "{}: differs from the version the plugin ships. Run "
                    "/oss:scaffold to replace it -- this file is ours, so nothing you "
                    "wrote is at risk.".format(name),
                }
            )
    return findings


def declared_dependencies():
    manifest = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8")).get("dependencies") or []
    except (OSError, ValueError):
        return []
    return [d if isinstance(d, str) else d.get("name") for d in raw if d]


INSTALL_RECORD = "~/.claude/plugins/installed_plugins.json"


def active_versions(names, record=None):
    """The version actually enabled, per dependency, from the install record.

    NOT from the cache directory listing. The first live run of this check reported
    `supertool 0.22.0 installed` while 0.40.0 was active, and `remember 0.13.0` -- a
    version not even in that marketplace's cache. Old versions stay unpacked on disk,
    more than one marketplace can carry the same plugin name, and a glob across them
    returns whichever sorts last. The listing says what was ever unpacked; the record
    says what is running.

    An unreadable record yields nothing rather than a fallback guess: every dependency
    then reports `missing`, which is loud, where a guessed version is quietly wrong.
    """
    path = Path(record or os.path.expanduser(INSTALL_RECORD))
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    plugins = doc.get("plugins") if isinstance(doc, dict) else None
    if not isinstance(plugins, dict):
        return {}

    found = {}
    for key, entries in plugins.items():
        name = key.split("@", 1)[0]
        if name not in names or not isinstance(entries, list):
            continue
        # One entry per scope; take the highest, which is the one that wins at load.
        versions = [e.get("version") for e in entries if isinstance(e, dict) and e.get("version")]
        for version in versions:
            if name not in found or compare_versions(found[name], version) == "behind":
                found[name] = version
    return found


def dependency_repositories(names):
    """Origin repo per dependency, read from each plugin's own installed manifest.

    Sourced from the artifact rather than a name-to-repo table in here: a hardcoded map
    is one more per-repo fact living in shared code, and it is wrong the first time a
    plugin moves.
    """
    repos = {}
    root = Path(os.path.expanduser("~/.claude/plugins/cache"))
    for name in names:
        for manifest in sorted(root.glob("*/{}/*/.claude-plugin/plugin.json".format(name))):
            try:
                doc = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if doc.get("repository"):
                repos[name] = doc["repository"]
    return repos


def published_versions(repos):
    """Latest published version per dependency, read off each repo's default branch."""
    latest = {}
    for name, url in repos.items():
        latest[name] = None
        if not url or shutil.which("gh") is None:
            continue
        slug = str(url).rstrip("/").replace("https://github.com/", "")
        try:
            done = subprocess.run(
                ["gh", "api", "repos/{}/contents/.claude-plugin/plugin.json".format(slug),
                 "--jq", ".content"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                universal_newlines=True,
                timeout=25,
            )
            if done.returncode != 0:
                continue
            import base64

            decoded = base64.b64decode(done.stdout.strip()).decode("utf-8")
            latest[name] = json.loads(decoded).get("version")
        except Exception:  # noqa: BLE001 - a diagnostic never dies on a probe
            continue
    return latest


def check_ci_enforcement(project_dir, config):
    """Does anything in CI run the tests, and does the config still describe the repo?

    A merge gate that passes because nothing ran is the worst of the three states: it
    reads exactly like a gate that passed because everything was checked.
    """
    if config is None or scaffold is None:
        return

    findings = scaffold.check_test_ci(project_dir, config)
    if not findings and config.get("test_command"):
        report(
            "OK",
            "test_command '{}' is executed by a workflow in .github/workflows/".format(
                config["test_command"]
            ),
        )
    for finding in findings:
        report("WARN", finding["detail"])

    for finding in scaffold.check_ci(project_dir, config):
        report("WARN", finding["detail"])


def check_freshness(project_dir, config):
    """Report, never update. A tool that changes underneath a running session changes
    behaviour mid-flight, and the runtime already owns installation.
    """
    names = declared_dependencies()
    if not names:
        report("WARN", "no dependencies declared in the manifest; nothing to compare")
    else:
        installed = active_versions(names)
        repos = dependency_repositories(names)
        for finding in dependency_findings(installed, published_versions(repos), declared=names):
            report("OK" if finding["state"] == "current" else "WARN", finding["detail"])

    if config is None or scaffold is None:
        return
    for finding in owned_drift(project_dir, config):
        report("OK" if finding["state"] == "current" else "WARN", finding["detail"])


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
        check_ci_enforcement(project_dir, config)

    # Declared dependencies install automatically; they do not configure themselves,
    # and the unconfigured state is the one that still appears to work.
    check_memory(project_dir)
    check_jit_rules(project_dir)
    # The merge permission is settled here or it is settled at the merge step,
    # with the whole review already spent.
    check_merge_permission(project_dir)
    check_freshness(project_dir, config)

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
