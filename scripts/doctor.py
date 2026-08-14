"""Diagnose an oss-managed repo: config, dependencies, clone, worktree root, state.

Contract, and every line of it is load-bearing:

* **Exit code 0, always.** A diagnostic must print its findings, not fail to run.
* **Three states: OK / WARN / FAIL.** WARN is "the check ran and could not answer".
  A check that cannot answer must never render as a check that found nothing.
* **One VERDICT line, last.** Greppable, so a human can paste the tail. This holds for
  every diagnostic run. ``--help`` is the one invocation that is not one: it prints
  usage and no VERDICT, and still exits 0.
* **No colour.** Git Bash renders escapes as noise, and this output gets pasted.
* **Never echo a value that could be a credential** -- name the key, print nothing.
* **The tree being diagnosed does not get to write the diagnosis.** Every finding goes
  through ``report()``, which reduces it to one printable ASCII line. The files this
  script reads -- ``.oss.json``, ``.claude/settings.json`` -- are tracked in a managed
  repo and a contributor writes them; unflattened, an entry in one forged the VERDICT
  line above.

Python 3.9 compatible.
"""

import argparse
import difflib
import json
import os
import re
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

# Far above any message this file composes -- the only thing that can reach it is
# foreign text, and a diagnostic line long enough to scroll a terminal is already
# unreadable. Truncation is marked rather than silent: a finding cut off without
# saying so is a partial answer rendered as a whole one.
REPORT_LIMIT = 2000


def _one_line(text, limit=200):
    """Text from outside this script, reduced to one printable ASCII line.

    Adopted verbatim from ``release_delta.py``'s function of the same name, whose
    reasoning applies here unchanged: a newline in foreign text forges a line of
    this script's own output, and a control character can rewrite what a terminal
    has already printed.

    It is a copy rather than an import because both callers are security controls
    and neither may depend on an import that can fail. ``oss_config`` is imported
    here under a ``try`` -- a sanitiser living there would be silently absent on
    exactly the broken installs this script exists to diagnose, which is the
    check-that-never-ran defect one layer down.
    """
    flat = " ".join(str(text).split())
    safe = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in flat)
    return safe[:limit]


def report(state, message):
    """Every finding goes through here, and so does every sanitisation.

    Not at the call sites: the strings that reach this function are built from
    settings entries, paths, config values and subprocess stderr -- things the
    audited tree chooses. A sanitiser applied at one of several call sites leaves
    the next one to rediscover that the tree being diagnosed can write the
    diagnosis, including the VERDICT line this output is greppable for.
    """
    # One character past the limit, so "was it cut" is answered by measurement
    # rather than by an equality that a message exactly REPORT_LIMIT long also
    # satisfies -- that reading drops four real characters and then appends an
    # ellipsis claiming it dropped more.
    flat = _one_line(message, limit=REPORT_LIMIT + 1)
    if len(flat) > REPORT_LIMIT:
        flat = flat[: REPORT_LIMIT - 4] + " ..."
    FINDINGS.append((state, flat))
    print("{} {}".format(state, flat))


def plugin_version():
    """Read the manifest directly, with no path resolution in the way -- this line
    must print even when everything else has failed.
    """
    manifest = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("version", "unknown")
    except (OSError, ValueError):
        return "unreadable"


NO_CONFIG = "not checked -- .oss.json was not found, so there was nothing to check it against"


def unmeasured(label, reason=NO_CONFIG):
    """The third state, said out loud.

    A check that was skipped and a check that found nothing print the same thing --
    nothing -- unless one of them says which it was. Every caller of this prints a line
    where the code used to `return` in silence.
    """
    report("WARN", "{}: {}".format(label, reason))


NO_SCAFFOLD = (
    "not checked -- scripts/scaffold.py could not be imported, and the comparison lives there"
)


def same_directory(left, right):
    """Do two spellings name one directory? Symlinks resolved, never compared as text.

    `os.getcwd()` is resolved by the kernel and a path handed in on the command line is
    not, so on macOS `/tmp` and `/private/tmp` are the same directory under two names --
    and `Path(".") != Path("/abs")` however identical the two are.
    """
    try:
        return os.path.samefile(str(left), str(right))
    except OSError:
        return os.path.abspath(str(left)) == os.path.abspath(str(right))


def config_search_path(project_dir):
    """``(path handed to oss_config, whether the clone will be searched)``.

    `resolve_config_path` deliberately never widens an absolute path -- one typed in
    full is an answer, not a starting point -- and it widens a relative one by appending
    it TO THE CLONE, exactly as given. Both halves matter here:

    * The absolute form makes the ``clone`` origin unreachable, so a doctor run from
      inside a git worktree reports the config missing while it sits in the clone one
      directory away. That is the case #53 was about, and it is why anything is passed
      relatively at all. Measured against this repo's own worktree: absolute answers
      ``missing``, ``.oss.json`` answers ``clone``.
    * Only a BARE name widens correctly. `<clone>/.oss.json` is where a config lives;
      `<clone>/sub/.oss.json`, which is what any relative path carrying directory
      components asks for, is not. `os.path.relpath` returns exactly such a path
      whenever the project dir is not the current directory -- and also when it merely
      reaches this process under a different spelling of it, which on macOS is the
      default, `/tmp` being a symlink to `/private/tmp`. That produced a five-level
      `../../../../..` search and a `not found` for a file sitting in the clone.

    So the bare name is used only when the project dir IS the current directory, proved
    with `samefile` rather than by comparing strings. Otherwise the absolute path, no
    widening -- and the second element of the return says so, because a search that was
    not made must not be reported as a search that found nothing.
    """
    absolute = os.path.abspath(str(Path(project_dir) / oss_config.CONFIG_NAME))
    if not Path(project_dir).is_dir():
        # The widening starts its git query from `.` when the directory the path points
        # into does not exist, so a --root that is not there searched the CALLER's clone
        # and named it in the finding: "Not in the enclosing clone at <somewhere else>
        # either". A sentence about a repository nobody asked about, inside a report
        # about one that does not exist.
        return absolute, False
    if same_directory(project_dir, os.getcwd()):
        return oss_config.CONFIG_NAME, True
    return absolute, False


def check_config(project_dir):
    if oss_config is None:
        report("FAIL", "scripts/oss_config.py could not be imported; config was not checked")
        return None
    display = Path(os.path.abspath(str(Path(project_dir) / oss_config.CONFIG_NAME)))
    search, widened = config_search_path(project_dir)
    config, problems, origin, resolved = oss_config.load_from(search)
    if config is None:
        prefix = "{}: ".format(search)
        for problem in problems:
            # load_from names the path it was given, which may be the bare file name.
            # This output gets pasted somewhere the cwd is not known, so say the
            # absolute one.
            if problem.startswith(prefix):
                problem = "{}: {}".format(display, problem[len(prefix):])
            report("FAIL", problem)
        if not widened:
            # The third state for the search itself. `Run /oss:setup to write it` is
            # wrong advice inside a worktree, whose config belongs in the clone, and
            # a clone that was never looked in must not read as a clone with nothing
            # in it.
            report(
                "WARN",
                "the enclosing clone was not searched for {}, because this run was "
                "pointed at {} rather than standing in it. If that is a git worktree, "
                "its config lives in the clone and this says nothing about it.".format(
                    oss_config.CONFIG_NAME, project_dir
                ),
            )
        return None
    if origin == "clone":
        report(
            "OK",
            ".oss.json read from the enclosing clone at {}, not from this directory. "
            "Every path it names is relative to that clone.".format(resolved.parent),
        )
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


def check_directory(label, value, config_found=True):
    if not config_found:
        unmeasured(label)
        return
    if not value:
        report("WARN", "{}: not set in config; cannot check it".format(label))
        return
    path = Path(os.path.expanduser(str(value)))
    if path.is_dir():
        report("OK", "{}: {}".format(label, path))
    else:
        report("WARN", "{}: {} does not exist".format(label, path))


def check_state_file(project_dir, config):
    if config is None:
        unmeasured("state_file")
        return
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


def _entry_count(count, key, path):
    """`2 allow entries in /path/to/settings.json` -- the count and the file, and
    nothing the file's author wrote."""
    return "{} {} {} in {}".format(
        count, key, "entry" if count == 1 else "entries", path
    )


def merge_permission_state(project_dir, home=None):
    """Is there a settings rule naming the merge op? Four answers, not two.

    `present` / `denied` / `absent` / `unknown`, and the last one is the reason
    this is not a boolean. A settings file that could not be parsed produces no
    matching entry, which looks exactly like a file that was read and had none --
    and the two send a maintainer to opposite places.

    A rule that WAS read settles the question, so an unreadable neighbour does not
    drag a found rule back to `unknown`.

    The detail names how many entries matched and which file they are in, never
    the entry text. The text was never needed -- the question is "is there a rule,
    and where do I go to change it" -- and printing it handed a tracked,
    contributor-writable file the ability to write this script's own output
    lines. Counts and paths answer the question and carry nothing chosen by the
    tree being diagnosed except a path it already had to be told about.
    """
    unreadable = []
    allowed = []
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
        for key, found in (("allow", allowed), ("deny", denied)):
            matches = [e for e in _permission_entries(data, key) if MERGE_OP in e]
            if matches:
                found.append(_entry_count(len(matches), key, path))
    # Every candidate is read before anything is decided, and deny wins. Returning
    # on the first allow would report `present` while holding, already parsed, a deny
    # rule for the same op -- an OK built on evidence the function had in hand and
    # dropped, which is worse than not looking.
    if denied:
        return "denied", "; ".join(denied)
    if allowed:
        return "present", "; ".join(allowed)
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


JIT_ENTRY_SKIP = "00-README.md"

# The index columns each dimension's builder writes, and where the ENTRY FILENAME sits
# in them. Measured against claude-jit-context's `rebuild-tsv.sh`, not reasoned about:
#
#   tools       tool <TAB> match <TAB> filename <TAB> mode|remind <TAB> require <TAB> forbid
#   paths       match <TAB> filename
#   vocabulary  keyword <TAB> filename, one row per keyword
#
# #80's report said the tools columns were `tool, match, mode, require, forbid` -- five,
# with the filename absent. There are six and the filename is the third of them, which is
# why this table is derived from the builder rather than from the description of it.
JIT_FILENAME_COLUMN = {"tools": 2, "paths": 1, "vocabulary": 1}


def _jit_field(text, field):
    """`jit_frontmatter()` from claude-jit-context's `common.sh`, in Python.

    Mirrored deliberately, quirks included, because a reader that is merely *similar*
    produces drift findings that are about this function rather than about the index:
    the field is matched as a line PREFIX, only SPACES are eaten after the colon,
    `mode` loses every space, an unterminated frontmatter block keeps reading to EOF
    exactly as the awk state machine does -- and trailing whitespace is trimmed ONLY
    on the copy the wrapped-quote test looks at, never on the value returned.

    That last one is not a detail. awk trims into `v`, tests `v`, and prints `$0`, so
    `match: docs/ ` indexes the trailing space and a reader that trimmed it would
    derive `docs/`, find no such row, and print "rebuild the index" at a layer whose
    index is exactly what a rebuild writes -- #80's own defect, one case narrower.
    """
    depth = 0
    for line in text.split("\n"):
        if line == "---":
            depth += 1
            continue
        if depth != 1 or not line.startswith(field + ":"):
            continue
        value = line[len(field) + 1 :].lstrip(" ")
        if field == "mode":
            return value.replace(" ", "")
        trimmed = value.rstrip(" \t\r\n\v\f")
        if (
            len(trimmed) >= 2
            and trimmed[0] == '"'
            and trimmed[-1] == '"'
            and '"' not in trimmed[1:-1]
        ):
            return trimmed[1:-1]
        return value
    return None


def _jit_macro(value):
    """An invocation macro -- `~@invocation git push` -- is EXPANDED into the row, so the
    index legitimately does not carry the frontmatter's text. Expanding it here would be a
    second implementation of somebody else's anchor, and a wrong one is a confident wrong
    answer. Declining is the honest read.
    """
    # ONE leading tilde, the way `${raw#\~}` strips one: `~~@invocation ...` is not a
    # macro to the builder, it is literal text, and declining to check it would report
    # an entry as unchecked that could have been compared exactly.
    return (value[1:] if value.startswith("~") else value).startswith("@")


def _jit_keywords(value):
    """The vocabulary normaliser, which is the matcher's: lowercase, every byte outside
    `[a-z0-9 -]` to a space, collapse, trim. Returns None when it cannot be mirrored --
    the indexer folds Latin-1 accents to ASCII first, and `detail` derived from `detail`
    with an accent would come out as two words here and read as drift.
    """
    keywords = set()
    for raw in value.split(","):
        if any(ord(ch) > 127 for ch in raw):
            return None
        lowered = "".join(ch if ch in "abcdefghijklmnopqrstuvwxyz0123456789 -" else " "
                          for ch in raw.lower())
        collapsed = " ".join(lowered.split())
        if collapsed:
            keywords.add(collapsed)
    return keywords


def jit_index_drift(dimension, entries, index_text):
    """Do the rows on disk still say what the entries' frontmatter says?

    Returns `(drift, undecidable)`: entry names whose rows provably disagree, and
    `(name, reason)` pairs for the ones this could not derive at all.

    Two comparisons, and the asymmetry is the point:

    - `tools` and `paths` are compared as SET EQUALITY on the rows naming an entry.
      Every row those builders write comes from frontmatter and none of them is
      dropped, so a missing row and an extra row are both proof.
    - `vocabulary` is compared as a SUBSET -- an indexed keyword the frontmatter can no
      longer produce is proof, a frontmatter keyword with no row is not. The builder
      skips generic words against a blacklist that is project-configurable through
      `config.env`, so equality there would report drift on a correctly built index,
      which is this check's own defect wearing the opposite sign.

    A row naming an entry that is not on disk is drift in either dimension: deleting a
    rule leaves its row behind, and the row is what runs.
    """
    column = JIT_FILENAME_COLUMN.get(dimension)
    if column is None:
        reason = (
            "this check knows how a tools, paths or vocabulary row is derived and "
            "'{}' is none of them".format(dimension)
        )
        return [], [(name, reason) for name in sorted(entries)]

    by_file = {}
    for row in index_text.split("\n"):
        if not row.strip():
            continue
        columns = row.split("\t")
        if len(columns) <= column:
            continue
        by_file.setdefault(columns[column], set()).add(row)

    drift = sorted(set(by_file) - set(entries))
    undecidable = []

    for name in sorted(entries):
        try:
            text = entries[name].read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            undecidable.append((name, "the entry file could not be read"))
            continue
        indexed = by_file.get(name, set())

        if dimension == "vocabulary":
            value = _jit_field(text, "keywords")
            derived = _jit_keywords(value) if value else set()
            if derived is None:
                undecidable.append(
                    (name, "its keywords: carry non-ASCII, which the indexer folds first")
                )
                continue
            if {row.split("\t")[0] for row in indexed} - derived:
                drift.append(name)
            continue

        match = _jit_field(text, "match")
        tool = _jit_field(text, "tool") if dimension == "tools" else "-"
        if not match or not tool:
            expected = set()  # the builder writes no row, and neither do we
        elif _jit_macro(match):
            undecidable.append(
                (name, "its match: is an invocation macro, expanded at index time and "
                       "not expanded here")
            )
            continue
        elif dimension == "tools":
            expected = {"\t".join([
                tool, match, name,
                _jit_field(text, "mode") or "remind",
                _jit_field(text, "require") or "",
                _jit_field(text, "forbid") or "",
            ])}
        else:
            expected = {"{}\t{}".format(match, name)}

        if expected != indexed:
            drift.append(name)

    return sorted(set(drift)), undecidable


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

    Whether an index is CURRENT is a question about its rows, and it is answered by
    re-deriving them (#80). It used to be answered from mtime, which measures a proxy:
    an entry newer than its index was reported as an entry whose "row says something
    else", in the imperative, on repos where every row was byte-identical to what a
    rebuild would write. Only frontmatter is indexed, and a body edit moves the
    timestamp of a file whose row cannot have changed.

    Deriving rather than declining was the choice, and the alternative is worth naming
    because it is defensible: the index format belongs to `claude-jit-context`, whose
    `rebuild-tsv.sh` is not reachable from the repo being diagnosed, and a second
    implementation of somebody else's format drifts. What decided it is that a decline
    leaves the maintainer with the same mtime and no answer, while the columns that
    can be derived exactly are derived exactly and the ones that cannot -- an expanded
    invocation macro, a folded accent, a dimension this does not know -- are declined
    individually, by name. The blast radius of drift is then one entry reported as
    unchecked, not a false imperative about the whole layer.
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
        # Read once, and guarded: this used to be an unguarded `read_text` inside the
        # emptiness test, so an index holding a byte sequence that is not UTF-8 raised
        # out of a diagnostic whose whole contract is to exit 0 with a VERDICT line.
        # The tree being diagnosed chooses that file's bytes.
        dimension = name.parts[0] if name.parts else ""
        entries = {p.name: p for p in rules if p.name != JIT_ENTRY_SKIP}
        try:
            index_text = index.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            report(
                "WARN",
                "{}: {} exists and could not be read, so whether its rows are current "
                "is unknown -- which is not the same as fine.".format(name, JIT_INDEX),
            )
            continue

        if not index_text.strip():
            report(
                "FAIL",
                "{}: {} is empty beside {} rule(s). An empty table is the same silence "
                "as a missing one, and it is the one that passes an existence check. "
                "Rebuild the index.".format(name, JIT_INDEX, len(rules)),
            )
            continue

        # mtime is evidence the index MIGHT be stale. It is not evidence that any row
        # differs -- and the row was what the sentence here used to assert (#80). The
        # entries carry their own answer, so it is derived rather than inferred, and the
        # timestamps are demoted to what they are: the reason to look, and the only
        # evidence left when the derivation declines.
        index_mtime = index.stat().st_mtime
        newer = sorted(n for n, p in entries.items() if p.stat().st_mtime > index_mtime)

        drift, undecidable = jit_index_drift(dimension, entries, index_text)

        if drift:
            report(
                "WARN",
                "{}: {} is stale -- its row(s) for {} no longer match those entries' "
                "frontmatter, so the rule that runs is not the rule as written. "
                "Rebuild the index.".format(name, JIT_INDEX, ", ".join(drift[:3])),
            )
            continue

        # The third state, and it is only a WARN when the timestamps give a reason to
        # care. Undecidable-and-untouched is not a finding -- a notice that fires on
        # every layer using an invocation macro would tell its reader nothing -- but it
        # is never silent either, because a row this could not derive and a row it
        # derived and matched must not print the same.
        unchecked = [n for n, _ in undecidable]
        if unchecked and set(unchecked) & set(newer):
            first, reason = undecidable[0]
            report(
                "WARN",
                "{}: cannot say whether {} is current. {} changed after the last "
                "rebuild and could not be derived -- {}. Timestamps are all the "
                "evidence there is here.".format(
                    name, JIT_INDEX, ", ".join(sorted(set(unchecked) & set(newer))[:3]),
                    "{}: {}".format(first, reason),
                ),
            )
            continue

        current = "{}: {} rule(s) indexed, rows match their frontmatter".format(
            name, len(rules)
        )
        if unchecked:
            current += " ({} not checked -- {}: {})".format(
                len(unchecked), unchecked[0], undecidable[0][1]
            )
        if newer:
            current += (
                "; {} entry file(s) changed after the index was written, and every row "
                "{} holds is derived from frontmatter".format(len(newer), JIT_INDEX)
            )
        report("OK", current)


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


#: How many section names one drift line will carry. Past a handful this stops being a
#: sentence a maintainer reads and becomes the diff dump this check exists to replace.
MAX_EFFECT_SECTIONS = 4

#: Suffixes where a line is inert exactly when it is blank or a `#` comment. Anything
#: not listed here -- and not `.md`, handled separately -- is treated as behavioural,
#: because the failure to be silent about is the one that calls a real change cosmetic.
HASH_COMMENT_SUFFIXES = (".yml", ".yaml", ".py", ".sh", ".bash", ".toml", ".cfg", ".ini")


def _normalise_newlines(text):
    """CRLF is a checkout, not an edit.

    A Windows clone with `core.autocrlf=true` holds every owned file with CRLF where
    the plugin wrote LF. The bytes differ; the file does not. `Path.read_text` already
    translates on read, so in practice this is a second belt -- but a future change to
    `read_bytes` would otherwise turn every Windows repo into permanent drift, and a
    warning that fires always is a warning nobody reads.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _inert_lines(lines, suffix):
    """Per line: True when changing it cannot change what the file does.

    Deliberately crude, and deliberately crude in one direction. A Python docstring
    reads as behavioural here, which over-reports; a rewritten `run:` step reading as
    prose would under-report, and that is the failure this whole check exists to stop.
    """
    flags = []
    fence = None
    for raw in lines:
        line = raw.strip()
        if suffix == ".md":
            # Only the marker that opened a fence can close it. Toggling on either
            # marker let a literal ``` inside a ~~~ block close the tracker early, and
            # the real terminator then re-opened it -- every line after that classified
            # inside out, which turns prose into "behaviour" and code into "cosmetic".
            opener = line[:3] if line[:3] in ("```", "~~~") else None
            if opener and (fence is None or opener == fence):
                fence = opener if fence is None else None
                flags.append(True)
            else:
                flags.append(fence is None)
            continue
        if suffix in HASH_COMMENT_SUFFIXES:
            flags.append(not line or line.startswith("#"))
            continue
        flags.append(False)
    return flags


def _yaml_literal_lines(lines):
    """True where a line is block-scalar *content* rather than YAML.

    Everything indented under `run: |` is shell. A step that echoes `status: pending`
    is not declaring a key, and reading it as one names a path the document does not
    have -- a confident answer about a structure nobody wrote.
    """
    literal = [False] * len(lines)
    block_indent = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if block_indent is not None:
            if not stripped or indent > block_indent:
                literal[i] = True
                continue
            block_indent = None
        if re.search(r":\s*[|>][+-]?\d*\s*$", line):
            block_indent = indent
    return literal


def _section_at(lines, index, suffix, literal=None):
    """The name of the region a changed line sits in -- what the maintainer needs.

    A YAML key path (`on.pull_request.types`), a Python definition, a Markdown
    heading. Empty when the file type has no such notion or the line sits above the
    first one, which the caller renders by naming no section rather than a wrong one.
    """
    line = lines[index]
    if suffix == ".md":
        for i in range(index, -1, -1):
            match = re.match(r"^#+\s+(.*\S)\s*$", lines[i])
            if match:
                return match.group(1)
        return ""
    if suffix == ".py":
        indent = len(line) - len(line.lstrip())
        for i in range(index, -1, -1):
            match = re.match(r"^(\s*)(?:async\s+)?(?:def|class)\s+(\w+)", lines[i])
            if match and (i == index or len(match.group(1)) < indent):
                return match.group(2)
        return ""
    if suffix in (".yml", ".yaml"):
        if literal is None:
            literal = _yaml_literal_lines(lines)
        parts = []
        depth = len(line) - len(line.lstrip())
        own = None if literal[index] else re.match(r"^\s*-?\s*([\w.-]+):", line)
        if own:
            parts.append(own.group(1))
        for i in range(index - 1, -1, -1):
            candidate = lines[i]
            if not candidate.strip() or candidate.strip().startswith("#") or literal[i]:
                continue
            indent = len(candidate) - len(candidate.lstrip())
            if indent >= depth:
                continue
            match = re.match(r"^\s*-?\s*([\w.-]+):", candidate)
            if match:
                parts.append(match.group(1))
                depth = indent
                if indent == 0:
                    break
        return ".".join(reversed(parts))
    return ""


def owned_effect(current_text, shipped_text, path):
    """What re-running `/oss:scaffold` would do to this file, in three kinds.

    This is the answer #26 asks for, and the reason it is phrased as an effect rather
    than a provenance. From inside a managed repo this check holds exactly two
    artefacts: their bytes and ours. Nothing in the repo records which plugin version
    wrote their copy, so "yours is older than ours" and "yours has been edited" are
    *not measurable* here -- they are the same observation. Describing the effect of
    re-running is measurable from what is on hand, and stays true whichever of those
    two it was.

    * `same`      -- nothing to do.
    * `cosmetic`  -- comments and prose move; nothing the file does changes.
    * `behaviour` -- something it does changes, and `sections` names where.
    """
    suffix = Path(path).suffix.lower()
    theirs = _normalise_newlines(current_text).split("\n")
    ours = _normalise_newlines(shipped_text).split("\n")
    if theirs == ours:
        return {"kind": "same", "sections": []}

    yaml = suffix in (".yml", ".yaml")
    # (lines, inert flags, block-scalar flags), computed once per side rather than per
    # changed line -- and carried explicitly, because looking the flags back up by the
    # identity of the list they belong to is a correctness argument nobody should have
    # to reconstruct.
    theirs_side = (theirs, _inert_lines(theirs, suffix), _yaml_literal_lines(theirs) if yaml else None)
    ours_side = (ours, _inert_lines(ours, suffix), _yaml_literal_lines(ours) if yaml else None)

    sections = []
    behavioural = False
    matcher = difflib.SequenceMatcher(None, theirs, ours, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        for (lines, flags, literal), start, stop in ((theirs_side, i1, i2), (ours_side, j1, j2)):
            for index in range(start, stop):
                if flags[index]:
                    continue
                behavioural = True
                name = _section_at(lines, index, suffix, literal)
                if name and name not in sections:
                    sections.append(name)
    if not behavioural:
        return {"kind": "cosmetic", "sections": []}
    # `jobs.gate.steps.name` beside `jobs.gate.steps.name.run` is one region reported
    # twice: the shorter is the path the longer already walks. Keeping both spends two
    # of the four slots pointing at the same place.
    kept = [
        section
        for section in sections
        if not any(other != section and other.startswith(section + ".") for other in sections)
    ]
    # Truncation that does not say it truncated is this repo's own defect: a list of
    # four reads as the whole answer whether or not four was all there was, and the
    # region that got cut is as likely as any to be the one worth re-running for.
    return {
        "kind": "behaviour",
        "sections": kept[:MAX_EFFECT_SECTIONS],
        "more": max(0, len(kept) - MAX_EFFECT_SECTIONS),
    }


def _drift_detail(name, effect):
    """One sentence a maintainer decides "re-run or not" from.

    Not a diff. Forty lines of unified diff for a workflow file teaches less than the
    name of the key that changed, and the decision this line feeds is binary.

    Both wordings carry the same caveat, because it is true in both and because the
    old text got it backwards: it promised "nothing you wrote is at risk", which is a
    claim about provenance this check cannot make. Owned files are replaced wholesale
    -- that is the contract -- so an edit somebody made deliberately goes with the
    re-run, and they are the only one who knows whether they made one.
    """
    caveat = (
        "Owned files are replaced wholesale, so an edit you made here goes with it."
    )
    if effect["kind"] == "cosmetic":
        return (
            "{}: re-running /oss:scaffold would change comments and prose only -- "
            "nothing it does changes. {}".format(name, caveat)
        )
    named = list(effect["sections"])
    dropped = effect.get("more", 0)
    if dropped:
        named.append("and {} more".format(dropped))
    where = " -- {}".format(", ".join(named)) if named else ""
    return (
        "{}: re-running /oss:scaffold would change what it does{}. {}".format(
            name, where, caveat
        )
    )


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

        # The other half of the comparison lives in somebody else's repo, so it can
        # fail to be readable in ways ours cannot: a binary blob under the name, a
        # permission bit, an encoding that is not UTF-8. Uncaught, that was a
        # traceback out of a diagnostic whose whole contract is to exit 0 and print.
        try:
            current = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            findings.append(
                {
                    "path": name,
                    "state": "unknown",
                    "detail": "{}: your copy could not be read ({}), so no comparison "
                    "was made".format(name, type(exc).__name__),
                }
            )
            continue

        effect = owned_effect(current, shipped, name)
        if effect["kind"] == "same":
            findings.append({"path": name, "state": "current", "detail": name})
        else:
            findings.append(
                {
                    "path": name,
                    "state": "drifted",
                    "effect": effect["kind"],
                    "detail": _drift_detail(name, effect),
                }
            )
    return findings


def owned_drift_summary(findings):
    """Turn per-file findings into one line per distinct fact, naming every file it covers.

    Three owned files absent from a repo is one gap with one fix. Printed per file it
    was three warnings, each ending in the same `Run /oss:scaffold.`, counted three
    times in the verdict and read as three unrelated findings.

    Findings are grouped on what they actually say -- the detail with its own path
    prefix removed -- so identical facts collapse and different ones never do. That
    keeps the three states apart without the grouping needing to know them: `absent`,
    `drifted` and `unknown` say different things, and `unknown` is a check that could
    not look rather than a pass. `current` stays one OK line per file; a clean repo's
    output is not what was wrong here.

    Lines come out in first-appearance order: a group is emitted where its first member
    appeared, so grouping only ever pulls a later file up to an earlier one and never
    reorders the report around it. Emitting the OK lines as they were found and the
    grouped ones afterwards would have moved every clean file ahead of a gap listed
    before it, which is a reordering nobody asked for.

    What this deliberately does NOT do is name the next command when there is nothing
    to report. A line printed regardless of state carries no information, and the rest
    of this file holds to the opposite rule: a line appears only when a check has
    something to say, so its absence means clean. The advice belongs on the surface
    that instructs the work -- `commands/setup.md` names `/oss:scaffold` at its close
    whatever doctor said, and `commands/scaffold.md` names `/oss:tick` at its own --
    not in a diagnostic that also runs mid-tick and before a release.
    """
    groups = []  # (state, shared text, [paths]), in first-appearance order
    for finding in findings:
        detail = finding["detail"]
        prefix = "{}: ".format(finding["path"])
        shared = detail[len(prefix):] if detail.startswith(prefix) else detail
        if shared == finding["path"]:
            # A detail that is just the path says nothing beyond it -- that is what a
            # `current` finding carries -- and re-appending it would print it twice.
            shared = ""
        # A current file is its own group always: there is no gap to collapse, and
        # merging clean files would replace a readable list with a count.
        if finding["state"] != "current":
            for state, text, paths in groups:
                if state == finding["state"] and text == shared:
                    paths.append(finding["path"])
                    break
            else:
                groups.append((finding["state"], shared, [finding["path"]]))
            continue
        groups.append((finding["state"], shared, [finding["path"]]))

    lines = []
    for state, shared, paths in groups:
        level = "OK" if state == "current" else "WARN"
        if len(paths) == 1:
            body = "{}: {}".format(paths[0], shared) if shared else paths[0]
            lines.append((level, body))
        else:
            lines.append(
                (level, "{} owned files -- {}: {}".format(len(paths), ", ".join(paths), shared))
            )
    return lines


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
    if config is None:
        unmeasured("CI enforcement")
        return
    if scaffold is None:
        unmeasured("CI enforcement", NO_SCAFFOLD)
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

    if config is None:
        unmeasured("owned files")
        return
    if scaffold is None:
        unmeasured("owned files", NO_SCAFFOLD)
        return
    for state, message in owned_drift_summary(owned_drift(project_dir, config)):
        report(state, message)


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a bad flag. This one refuses to, because a mistyped argument
    must still produce a report -- exit 0 and one VERDICT line is the contract, and a
    usage message on stderr with neither is the diagnostic failing to run.
    """

    def error(self, message):  # pragma: no cover - exercised through parse_args
        raise ValueError(message)


def parse_args(argv):
    """``(root, problems)``. Never exits and never raises."""
    parser = _Parser(
        prog="doctor.py",
        description="Diagnose an oss-managed repo. Always exits 0.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="the repo to diagnose. Wins over CLAUDE_PROJECT_DIR and over the current "
        "directory; a path that is not a directory is reported, not raised.",
    )
    try:
        return parser.parse_args(list(argv)).root, []
    except ValueError as exc:
        return None, [
            "argument: {}. Falling back to CLAUDE_PROJECT_DIR or the current "
            "directory, so the tree below may not be the one you meant.".format(exc)
        ]


def resolve_project_dir(root, env_value, cwd):
    """Which tree this run is about, as ``(path, [(state, message), ...])``.

    Precedence is decided here rather than defaulted, in this order:

    ``--root``   wins outright. It is the only one of the three that somebody typed on
                 purpose, for this run.
    env          ``CLAUDE_PROJECT_DIR``, which is the previous behaviour and stays the
                 answer whenever no flag is given.
    cwd          last, and announced as a guess -- the source most likely to be wrong
                 and the least likely to say so, because a `cd` persists.

    A flag disagreeing with the environment is reported even though the flag wins. The
    disagreement is itself the finding: it is the shape in which somebody reads a
    well-formed answer about a repository they did not ask about.

    Nothing here raises. A root that is not a directory is a finding and the run
    continues, which is what makes every config-dependent check below report itself
    unmeasured rather than the process dying with no VERDICT line.
    """
    findings = []
    if root:
        chosen = Path(os.path.expanduser(str(root)))
        findings.append(("OK", "project dir: {} (--root)".format(chosen)))
        if env_value and not same_directory(os.path.expanduser(str(env_value)), chosen):
            findings.append(
                (
                    "WARN",
                    "--root and CLAUDE_PROJECT_DIR disagree. CLAUDE_PROJECT_DIR names "
                    "{}, --root won, and nothing below is about that other tree.".format(
                        Path(os.path.expanduser(str(env_value)))
                    ),
                )
            )
        if not chosen.is_dir():
            findings.append(
                (
                    "FAIL",
                    "--root {}: not a directory, so there is nothing here to "
                    "diagnose. Every check below reports itself unmeasured.".format(chosen),
                )
            )
        elif not (chosen / ".git").exists():
            # `.git` is a file in a worktree and a directory in a clone, so this asks
            # whether it exists rather than what kind of thing it is.
            findings.append(
                (
                    "WARN",
                    "--root {}: no .git here, so this is not a git repository or its "
                    "checkout is elsewhere. Findings below may not be about the tree "
                    "you meant.".format(chosen),
                )
            )
        return chosen, findings

    if env_value:
        chosen = Path(os.path.expanduser(str(env_value)))
        return chosen, [("OK", "project dir: {}".format(chosen))]

    # CLAUDE_PROJECT_DIR reaches hooks, not the Bash tool, so this is often a guess.
    # Say that it is one rather than presenting it as resolved.
    chosen = Path(cwd)
    return chosen, [("WARN", "project dir guessed from cwd: {}".format(chosen))]


def main(argv=None):
    """``argv`` defaults to nothing, NOT to ``sys.argv``.

    This module is imported and called in-process by its own suite, and reading the
    host's argv there made doctor parse pytest's command line and report every test
    path as an unrecognised argument. A library entry point does not get to read the
    process's arguments; the script entry point at the bottom passes them in.
    """
    root, arg_problems = parse_args([] if argv is None else argv)
    project_dir, resolution = resolve_project_dir(
        root, os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()
    )

    report("OK", "oss plugin version {}".format(plugin_version()))
    for problem in arg_problems:
        report("FAIL", problem)
    for state, message in resolution:
        report(state, message)

    config = check_config(project_dir)

    check_tool("gh", ["gh", "auth", "status"])
    check_tool("supertool", ["supertool", "version"])
    check_tool("git", ["git", "--version"])

    # Passed through even when the config is None: each of these prints its own
    # "not checked" line, and skipping the call would restore the silence #62 is about.
    found = config is not None
    check_directory("clone", config.get("clone") if found else None, config_found=found)
    check_directory(
        "worktree_root", config.get("worktree_root") if found else None, config_found=found
    )
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
    sys.exit(main(sys.argv[1:]))
