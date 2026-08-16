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
import hashlib
import json
import os
import re
import shutil
import stat
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

try:
    import oss_rules
except ImportError:  # pragma: no cover - the module sits beside this file
    oss_rules = None

try:
    import oss_state
except ImportError:  # pragma: no cover - the module sits beside this file
    oss_state = None

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
    """Is this dependency present, and does it run?

    The probe's output is captured and never read -- both arms below branch on
    ``returncode`` alone, and ``stderr`` is merged into the same pipe only to keep a
    banner off this script's own stdout, where it would forge a finding.

    So the pipe stays **bytes**. Text mode decodes with the *runner's* locale, and a
    ``--version`` banner is exactly where a byte that locale cannot decode turns up --
    a copyright sign, an accented author name. ``UnicodeDecodeError`` is a
    ``ValueError``, so the guard below does not catch it, and a diagnostic contracted
    to exit 0 with one VERDICT line died in a traceback instead of reaching its own
    "found on PATH but would not run" arm. Nothing downstream wants text, so the
    decode is removed rather than guarded: an ``except ValueError`` here would be
    unreachable, and would newly swallow a malformed ``probe`` -- a bug in this file --
    into a finding about the user's toolchain.
    """
    if shutil.which(name) is None:
        report("WARN", "{}: not on PATH; anything needing it will be skipped".format(name))
        return
    try:
        done = subprocess.run(
            probe,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
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


NO_STATE_MODULE = (
    "not checked -- scripts/oss_state.py could not be imported, and the shape it "
    "requires is defined there"
)


def check_state_file(project_dir, config):
    """Is the named state file readable *by the script that will write it*?

    Present was the old question and it is the wrong one (#149). A repo that ran a
    maintainer loop before this plugin existed has a state file shaped as an object
    keyed `tick_<ISO>`; `oss_state.read` wants a list, so every tick completes its work
    and then cannot record any of it. Doctor is the step that can say so before the
    work, which is the only place a maintainer can act on it.

    Nothing here raises. `oss_state.describe` answers in three states and swallows
    nothing into a fourth, so an unreadable file cannot arrive as a traceback through
    doctor's *exit 0 always, one VERDICT line* contract.
    """
    if config is None:
        unmeasured("state_file")
        return
    value = config.get("state_file")
    if not value:
        report("WARN", "state_file: not set in config")
        return
    path = project_dir / str(value)
    if oss_state is None:
        unmeasured("state_file", NO_STATE_MODULE)
        return
    found = oss_state.describe(path)
    if found["state"] == oss_state.STATE_OK:
        report("OK", "state_file: {} ({} entries)".format(path, len(found["entries"])))
    elif found["state"] == oss_state.STATE_ABSENT:
        report("WARN", "state_file: {} not written yet (first tick will create it)".format(path))
    else:
        report(
            "WARN",
            "state_file: {} is there and /oss:tick cannot use it -- {}".format(
                path, found["reason"]
            ),
        )


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


# The watch channel, and why this is a diagnostic rather than a setting (#150).
#
# `.supertool.json` is supertool's file, not ours. A non-reserved key in an op's
# block reaches that op's subprocess as a `SUPERTOOL_`-prefixed variable, so
# `{"ops": {"radar": {"watch_name": "oss"}}}` arrives as SUPERTOOL_WATCH_NAME with
# no plumbing on either side -- which is exactly why `.oss.json` has no business
# carrying the name. `.oss.json` describes a repo's release and review process; a
# watcher socket is neither, and a second home for one value is a second thing to
# disagree.
#
# What is missing is not configuration, it is visibility. The name derives
# /tmp/supertool-watch-<name>.sock and a poller slot directory held by exactly one
# process, so several repos resolving to one name share one fleet -- and a shared
# fleet renders in `watches` identically to a private one. That is this plugin's
# own defect class in somebody else's tool, and saying which of the states holds
# is the whole fix available from here.
#
# Read, never written. Nothing below creates or edits this file.
WATCH_CONFIG = ".supertool.json"
WATCH_NAME_ENV = "SUPERTOOL_WATCH_NAME"

# An explicit socket or state directory OVERRIDES the name -- not because an
# export is more authoritative, but because it is the value a running poller
# already captured and cannot migrate away from. So a name that agrees with its
# declaration still decides nothing while one of these is set, and reporting
# `agree` there would be a green line about a comparison with no effect.
WATCH_PATH_ENV = ("SUPERTOOL_WATCH_SOCK", "SUPERTOOL_WATCH_STATE_DIR")

# `.oss.json`, read here directly rather than through `oss_config` (#191).
#
# This answers one question -- can bin/oss-workspace derive a channel name from
# this repo? -- and the launcher answers it with a bare json.load and no schema in
# the way. Routing through the validator would make doctor say "no name derivable"
# for a config the launcher happily derives from, which is a disagreement invented
# by the reader rather than found in the repo.
OSS_CONFIG = ".oss.json"

# Does anything publish to this repo's board? (#191)
#
# `radar` reads its tiers from `ops.radar.radar_tiers` in this repo's own
# `.supertool.json`, and there is NO default -- supertool's `help:radar` says in as
# many words that with none configured radar refuses, "because an unconfigured
# radar that prints nothing is byte-identical to a healthy one". That is this
# plugin's own defect class, stated by the dependency about itself, and it is why
# the question is asked here.
#
# It lived until now only in `bin/oss-workspace` as one line of session-start
# stderr, decided by `grep -q radar` -- which also matches the string inside an
# unrelated key, a validator command, or a comment. A launcher warning fires once
# and scrolls; the diagnostic is where a maintainer goes to ask.
RADAR_OP = "radar"
RADAR_TIERS_KEY = "radar_tiers"

# Measured against the dependency rather than assumed. In a project whose
# `.supertool.json` enables no presets, `supertool 'radar:--state'` exits 1 with:
#
#   ERROR: op 'radar' is unavailable here, not unknown -- it is provided by the
#   shipped preset 'watch', which <path>/.supertool.json does not enable.
#
# (supertool 0.44.0, 2026-08-15.) A transcription is a claim about something
# outside this repo, so `tests/test_doctor_inprocess.py` re-measures it against the
# installed supertool and skips loudly when supertool is not on PATH, rather than
# leaving the claim asserted in this comment.
WATCH_PRESET = "watch"

# A second, independently composed copy of `scaffold.RADAR_REMEDY_CONFIG` -- and the
# comment that used to stand here said it was "the same remedy `scaffold.check_radar`
# names", which was false when it was written: scaffold's named the tiers and not the
# preset, so a maintainer who followed it landed in the `route-unknown` state this file
# refuses, and scaffold then called the result clean (#205).
#
# They now agree, and what holds them together is a measurement rather than a comment:
# `tests/test_scaffold.py::test_scaffolds_own_radar_remedy_satisfies_both_checkers`
# writes scaffold's mapping to disk and asks BOTH checkers about the result. One shared
# constant was the other option and it is not available: `doctor` imports `scaffold`
# optionally, with a stated fallback for when that import fails, so a constant reached
# through it degrades to a second value anyway, and the reverse import direction is a
# cycle. A prose claim that two values are equal is also the weaker guard -- it passes
# whenever both are wrong together, which is precisely how this one survived.
#
# The reason for naming the remedy rather than merging it in IS shared, and is a rule
# rather than a value: `.supertool.json` is never overwritten by this plugin, so an
# existing one is the repo's own, and a config file edited behind somebody's back is
# worse than a board they have to turn on. Composed from the constants above so a drift
# in one of them reaches the remedy rather than leaving it confidently telling a
# maintainer to add a key that no longer exists.
RADAR_REMEDY_CONFIG = {
    "presets": [WATCH_PRESET],
    "ops": {RADAR_OP: {RADAR_TIERS_KEY: {"gh-prs": {}}}},
}

# Rendered from the mapping above rather than typed, so the line a maintainer
# pastes is the same object a test reads back through `radar_publish_state`. A
# remedy is a claim about what would fix the thing, and the only way to find out
# that it does is to run the check over it -- asserting on its text would pass
# just as happily on a remedy that fixes nothing.
#
# The second sentence exists because the repo that most needs this line is one
# scaffolded before #191, which already HAS a `presets` list: a paste over it
# would silently drop `git` and `github`.
RADAR_REMEDY = (
    "Add {} -- and where `presets` is already there, add '{}' to the list it has "
    "rather than replacing it.".format(
        json.dumps(RADAR_REMEDY_CONFIG, sort_keys=True), WATCH_PRESET
    )
)


def _supertool_document(project_dir):
    """This repo's `.supertool.json` as a mapping, in three states rather than two.

    Returns `(doc, problem, detail)`. `(None, None, "")` is the file not being
    there, which is an answer; `"unreadable"` is a file that is there and the read
    or the parse failed; `"malformed"` is a file that read and parsed and is not
    an object. Folding absence into either renders a broken file as a repo that
    declares nothing, under a line saying nothing is wrong -- and folding the
    third into the second is #216: `[]` is valid JSON, the read succeeded, and
    reporting "could not be read" sends the maintainer to permissions, a lock or
    an encoding when the remedy is to fix the document's shape. Two failure
    states exist precisely because they send the reader somewhere different, so
    collapsing them costs exactly what having them buys.

    THREE and not four. "It parsed and the key we wanted is absent" is a real and
    common state, but it is not this function's to answer: the two callers want
    different keys (`ops.radar.radar_tiers` and `ops.*.watch_name`), and each
    already names that absence in its own vocabulary -- `no-tiers` for one,
    `default` / `declared-only` for the other. A fourth return here would have to
    know which key its caller wanted, which moves a caller's question into a
    shared helper and answers it for whoever did not ask.

    The exception in hand decides absence from unreadable: `FileNotFoundError` is
    absence, anything else is unreadable. Asking the filesystem a second question
    to explain why the first failed is how `Path.exists()` took the release gate
    down from inside the `except` that was meant to make it survive a bad read.
    The malformed arm needs no exception at all -- nothing failed.
    """
    path = Path(project_dir) / WATCH_CONFIG
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None, ""
    except (OSError, ValueError, UnicodeDecodeError):
        return None, "unreadable", "{} is there and could not be read".format(
            WATCH_CONFIG
        )
    if not isinstance(doc, dict):
        # Same sentence `scaffold.check_radar` already prints for this shape, and
        # for the same reason -- not because the two checkers are asserted to
        # agree, which would pass just as happily on two that are both wrong, but
        # because the shape itself earns it.
        return None, "malformed", "{} is not an object".format(WATCH_CONFIG)
    return doc, None, ""


def _declared_watch_names(project_dir):
    """The distinct `ops.*.watch_name` values in this repo's `.supertool.json`.

    Returns `(names, problem, detail)`. `problem` is None when the file was read
    and its shape was usable -- which includes the file not being there, because
    absence is an answer and a broken file is not. Otherwise it is `"unreadable"`
    or `"malformed"`, carried through from `_supertool_document` or decided here.
    """
    doc, problem, detail = _supertool_document(project_dir)
    if problem:
        return set(), problem, detail
    if doc is None:
        return set(), None, ""
    # Absent and malformed are not the same answer. `ops` missing entirely is a
    # repo that declares nothing, which is a real and common state; `ops` present
    # and the wrong shape is a file somebody edited and broke, and folding it into
    # the first renders that repo as `default` under a green line saying nothing is
    # wrong. The top-level document three lines up is already split that way, and
    # the asymmetry was the bug.
    if "ops" not in doc:
        return set(), None, ""
    ops = doc.get("ops")
    if not isinstance(ops, dict):
        # `malformed`, not `unreadable`. The comment above has said these are two
        # answers since it was written, and the line under it returned the third
        # one's name -- the file read and parsed perfectly. That is #216's row,
        # one caller over from the one it tabulated.
        return set(), "malformed", "`ops` in {} is not an object".format(WATCH_CONFIG)
    return {
        block["watch_name"]
        for block in ops.values()
        if isinstance(block, dict)
        and isinstance(block.get("watch_name"), str)
        and block["watch_name"]
    }, None, ""


def radar_publish_state(project_dir):
    """Does anything publish to this repo's board? Seven answers.

    `unreadable` / `malformed` / `no-config` / `no-tiers` / `no-route` /
    `route-unknown` / `publishes`, and the split is the point: from outside this
    function an empty board and a healthy one render identically. `watches` shows
    a fleet, `channel:health` reports FORWARDING, the session opens, and nothing
    has ever been published to it.

    Two independent halves have to hold, and each is silent about the other. A
    tier has to be REGISTERED (`ops.radar.radar_tiers`), and the op reading it has
    to be ROUTED here (its preset enabled). #191 measured this repository with
    neither, under a diagnostic that printed OK.

    The route half is answered from the same declaration rather than by running
    supertool: this must stay fast, must exit 0, and a subprocess that failed for
    its own reasons would arrive here as evidence about the repo. When `presets`
    is absent or not a list of strings the answer is `route-unknown` -- NOT
    `no-route`, which would send a maintainer to add a preset that may already be
    in effect.

    The detail names counts, keys and the config path -- never a tier name.
    `.supertool.json` is contributor-writable in a managed repo, which is how a
    tracked file gets to write a diagnostic's own output lines.
    """
    doc, problem, detail = _supertool_document(project_dir)
    if problem:
        # Both of the helper's failure names are already states of this function's
        # own vocabulary, and each carries the sentence its shape earned. Passing
        # them through rather than re-deciding here is what stops the two drifting
        # apart again: #216 was this line naming one state for both.
        return problem, detail
    if doc is None:
        return "no-config", "there is no {} here".format(WATCH_CONFIG)

    # Present-and-broken is not the same answer as never-declared at any of the
    # three levels, and the remedies differ: one is an edit to make, the other is
    # an edit to undo.
    ops = doc.get("ops")
    if "ops" in doc and not isinstance(ops, dict):
        return "malformed", "`ops` in {} is not an object".format(WATCH_CONFIG)
    block = ops.get(RADAR_OP) if isinstance(ops, dict) else None
    if block is not None and not isinstance(block, dict):
        return "malformed", "`ops.{}` in {} is not an object".format(
            RADAR_OP, WATCH_CONFIG
        )
    tiers = block.get(RADAR_TIERS_KEY) if isinstance(block, dict) else None
    if tiers is not None and not isinstance(tiers, dict):
        return "malformed", "`ops.{}.{}` in {} is not an object".format(
            RADAR_OP, RADAR_TIERS_KEY, WATCH_CONFIG
        )
    if not tiers:
        return "no-tiers", "`ops.{}.{}` in {} registers no tier".format(
            RADAR_OP, RADAR_TIERS_KEY, WATCH_CONFIG
        )

    registered = "{} tier(s) registered in `ops.{}.{}`".format(
        len(tiers), RADAR_OP, RADAR_TIERS_KEY
    )
    presets = doc.get("presets")
    if not isinstance(presets, list) or not all(
        isinstance(entry, str) for entry in presets
    ):
        return "route-unknown", registered
    if WATCH_PRESET not in presets:
        return "no-route", registered
    return "publishes", registered


def check_radar_publish(project_dir):
    """Say whether anything can publish, and say what that does not cover.

    OK here never means "your board is live". This reads one declaration; it does
    not run radar, does not reach a forge and cannot know whether a tier has ever
    emitted. Every message carries that limit, or the check becomes the shape it
    exists to report.
    """
    state, detail = radar_publish_state(project_dir)
    if state == "unreadable":
        report(
            "WARN",
            "radar board: {}, so whether anything publishes to this repo's board is "
            "unknown -- not answered as 'nothing does', because that sends you to "
            "register tiers you may already have.".format(detail),
        )
        return
    if state == "malformed":
        report(
            "WARN",
            "radar board: {}, so no tier could be read from it. That is a file "
            "somebody edited and broke rather than a repo that registers none, and "
            "the two have different remedies.".format(detail),
        )
        return
    if state == "no-config":
        report(
            "WARN",
            "radar board: {}, so no radar tier is registered and nothing publishes to "
            "this repo's board. The channel is still open and a session still runs; "
            "an empty board renders exactly like a live one. {}".format(
                detail, RADAR_REMEDY
            ),
        )
        return
    if state == "no-tiers":
        report(
            "WARN",
            "radar board: {}, so nothing publishes to it. supertool's `{}` refuses "
            "with none registered, and a board that prints nothing is "
            "byte-identical to a healthy one -- which is why this is asked here "
            "rather than left to one line of launcher stderr that scrolls away. "
            "{}".format(detail, RADAR_OP, RADAR_REMEDY),
        )
        return
    if state == "no-route":
        report(
            "WARN",
            "radar board: {}, but `presets` in {} does not enable '{}', which is what "
            "provides `{}` -- so the op has no route here and the registered tiers "
            "cannot run. Both halves are needed and each is silent about the "
            "other.".format(detail, WATCH_CONFIG, WATCH_PRESET, RADAR_OP),
        )
        return
    if state == "route-unknown":
        report(
            "WARN",
            "radar board: {}, but `presets` in {} is absent or not a list of strings, "
            "so whether `{}` has a route here could not be read -- answered neither "
            "as routed nor as unrouted.".format(detail, WATCH_CONFIG, RADAR_OP),
        )
        return
    report(
        "OK",
        "radar board: {}, and `presets` in {} enables '{}', so this repo registers a "
        "board and a route to it. This reads one declaration: it does not run `{}`, "
        "and it does not establish that any tier has ever "
        "emitted.".format(detail, WATCH_CONFIG, WATCH_PRESET, RADAR_OP),
    )


def _derivable_watch_name(project_dir):
    """Can `bin/oss-workspace` derive a channel name for this repo, and which?

    Returns `(state, name, why)`, state being `yes` / `no-config` / `unreadable` /
    `malformed` / `no-repo` / `refused` / `no-validator`. `name` is empty for
    everything but `yes`, so a caller cannot get a name out of a state that did not
    produce one, and `why` carries the validator's own sentence for `refused` and is
    empty for every other state.

    `malformed` is `unreadable`'s twin and arrived with #216, which filed the same
    fold against the two `.supertool.json` readers below. `[]` is valid JSON: the
    read succeeded and the parse succeeded, so answering "could not be read" sends
    the reader to permissions, a lock or an encoding when the remedy is to fix the
    document. Note this is the SEVENTH state and not a sixth spelling of one -- the
    two have different remedies, which is the whole reason `unreadable` was split
    off `no-config` in the first place.

    The launcher derives the name from `.oss.json`'s `repo` when nothing declares
    or exports one (#191), so "nothing declared" stopped meaning "the shared
    default socket" the moment that landed -- and the line saying `Nothing is
    broken` would have gone on saying it. This is the half of that change the
    diagnostic owes its reader.

    The non-`yes` answers are kept apart because they are different remedies, and
    because a caller comparing an export against a derivation needs to know it had
    nothing to compare against, rather than being handed an empty string that every
    export differs from.

    `refused` and `no-validator` arrived with #207, and this function no longer
    carries a second spelling of the fold. It used to: `_derive_watch_name`
    mirrored the launcher's `re.sub` because the rule had no shared home, and its
    own docstring said the single home was the eventual fix but that
    `bin/oss-workspace` was held by another lane. #207 held both, so the rule moved
    to `oss_config.watch_channel_name` and both sides read it now. The cross-check
    test stays and is not redundant: what it measures is the launcher's own
    PROGRAM -- its argv wiring, its import path, and that it refuses where this
    does -- which is still a second measurement rather than a second assertion.

    `no-validator` is this check's own third state. `oss_config` is imported
    optionally at the top of this module, and a diagnostic answering `no-repo`
    when it could not load the validator would report a hole in somebody's config
    for a hole in its own tooling.
    """
    if oss_config is None:
        return "no-validator", "", ""
    path = Path(project_dir) / OSS_CONFIG
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "no-config", "", ""
    except (OSError, ValueError, UnicodeDecodeError):
        return "unreadable", "", ""
    if not isinstance(doc, dict):
        # Nothing failed here -- no exception, no second question to the
        # filesystem. The file read and parsed and is the wrong shape, which is a
        # different remedy from a mode, a lock or an encoding (#216).
        return "malformed", "", ""
    repo = doc.get("repo")
    # Blank before invalid, matching the launcher arm for arm: "declares no repo"
    # and "declares one nobody can use" are two remedies, and the validator would
    # fold them into one sentence.
    if not isinstance(repo, str) or not repo.strip():
        return "no-repo", "", ""
    name, problem = oss_config.watch_channel_name(repo)
    if problem:
        # Folded here, at the single point that produces it. `repo` is somebody's
        # config value and the validator quotes it back with `{!r}`, so this is the
        # first watch-channel message that can carry a character the console's
        # codepage cannot represent.
        #
        # This is NOT what stops a UnicodeEncodeError -- `report()` already funnels
        # every finding through `_one_line`, which replaces anything outside
        # printable ASCII with `?`, and that guard is load-bearing and stays the
        # authority. What this adds is that the receipt still NAMES the value: a
        # CJK repo reduces to `repo-??` under `_one_line`, which reports that
        # something is wrong with a value it has just made unidentifiable, and the
        # remedy is to correct that exact value. `backslashreplace` first means
        # `_one_line` receives ASCII and changes nothing.
        return "refused", "", problem.encode("ascii", "backslashreplace").decode("ascii")
    return "yes", name, ""


def watch_channel_state(project_dir, env=None):
    """Which watch channel does this repo actually resolve to? Twelve answers.

    `unreadable` / `malformed` / `conflict` / `overridden` / `mismatch` /
    `undeclared-export` / `undeclared-export-unknown` / `derived-export` /
    `agree` / `declared-only` / `derived` / `default`, and the count is the point. The filed
    symptom -- four repos on one poller slot -- was NOT a repo whose declaration
    disagreed with its environment. It was four repos declaring nothing at all with
    one hand-copied export between them, so a check that only compared a
    declaration against an export would have rendered the reported case and a clean
    one the same way. `undeclared-export` is that case and it is separate from
    `default`, which is the same absence with nothing exported over it.

    `unreadable` is separate from every state above for the same reason: a file
    that could not be parsed yields no names, which looks exactly like a file that
    was read and declared none. `malformed` is separate from `unreadable` for the
    opposite reason -- the file WAS read, and naming a successful read as a failed
    one sends the reader to permissions instead of to the document (#216).

    The environment read is this process's, and that is the honest scope: a poller
    spawned from this session inherits it. It says nothing about a session already
    running elsewhere, and the messages say so rather than implying otherwise.

    The detail names counts, variables and the config path -- never a name. The
    value was never what the reader needs; both places to look are named, and the
    file is contributor-writable in a managed repo, which is how a tracked file
    gets to write a diagnostic's own output lines.
    """
    environ = os.environ if env is None else env
    names, problem, problem_detail = _declared_watch_names(project_dir)
    if problem:
        # `unreadable` and `malformed` both stop the read, and they are two answers
        # rather than one: the first sends the reader to permissions, a lock or an
        # encoding, the second to the document. Reporting the second as the first
        # is #216. Neither may fall through to the states below, where `default`
        # would tell a repo with a broken file that it declares nothing.
        return problem, problem_detail

    overrides = [key for key in WATCH_PATH_ENV if environ.get(key)]
    exported = environ.get(WATCH_NAME_ENV) or ""

    if len(names) > 1:
        # Two things can be wrong at once, and they have different remedies: the
        # file needs one name left in it, and the override needs unexporting.
        # Returning only the first drops the second, which is the state that
        # decides the paths -- so it travels in the detail rather than being
        # discarded for arriving second.
        detail = "{} op blocks in {} declare {} distinct names".format(
            len(names), WATCH_CONFIG, len(names)
        )
        if overrides:
            detail += ", and {} is set over them".format(", ".join(overrides))
        return "conflict", detail
    if overrides:
        return "overridden", ", ".join(overrides)

    declared = next(iter(names)) if names else ""
    if declared and exported:
        if declared == exported:
            return "agree", "declared in {} and exported as {}".format(
                WATCH_CONFIG, WATCH_NAME_ENV
            )
        return "mismatch", "declared in {}, exported as {}".format(
            WATCH_CONFIG, WATCH_NAME_ENV
        )
    if exported:
        # An export with no declaration beside it used to be one answer, and it
        # accused the reader of a hand-copied settings file. Since #192 that is the
        # ORDINARY state of every managed repo: the launcher derives a name from
        # `.oss.json` and exports it, with nothing in `.supertool.json` to show for
        # it. So the accusation has to be earned by a comparison rather than
        # inferred from an absence -- and the original case is real, so the state is
        # split rather than deleted.
        derivable, derived, why = _derivable_watch_name(project_dir)
        if derivable != "yes":
            # Neither answer is available. Reporting `undeclared-export` here would
            # accuse on no evidence, and reporting `derived-export` would clear on
            # none; this is the third answer and it says which fact was missing.
            return "undeclared-export-unknown", {
                "no-config": "there is no {} to compare it against".format(OSS_CONFIG),
                "unreadable": "{} is there and could not be read, so there was "
                "nothing to compare it against".format(OSS_CONFIG),
                # Separate from `unreadable` above: this one WAS read (#216).
                "malformed": "{} is not an object, so the launcher derives nothing "
                "to compare it against -- the file was read and it parsed, so the "
                "remedy is its shape".format(OSS_CONFIG),
                "no-repo": "{} carries no repo to compare it against".format(
                    OSS_CONFIG
                ),
                # The reason travels rather than being flattened into "no repo":
                # the remedy is to fix a value, not to add a key (#207).
                "refused": "{} carries a repo the config validator refuses ({}), so "
                "the launcher derives nothing to compare it against".format(
                    OSS_CONFIG, why
                ),
                "no-validator": "the config validator could not be imported, so "
                "nothing could be derived to compare it against -- this is a hole "
                "in the diagnostic, not in {}".format(OSS_CONFIG),
            }[derivable]
        if derived == exported:
            return "derived-export", "{} matches what {}'s repo derives to".format(
                WATCH_NAME_ENV, OSS_CONFIG
            )
        return "undeclared-export", "it is not what {}'s repo derives to".format(
            OSS_CONFIG
        )
    if declared:
        return "declared-only", "declared in {}".format(WATCH_CONFIG)

    # Nothing declared and nothing exported used to end here as one answer. Since
    # #191 the launcher derives a name from `.oss.json`'s `repo` at that point, so
    # this is two states: a repo that gets its own socket, and a repo that lands on
    # the SHARED one because there was nothing to derive from.
    derivable, _derived, why = _derivable_watch_name(project_dir)
    if derivable == "yes":
        return "derived", "nothing declared in {} and {} unset, and {} carries a repo".format(
            WATCH_CONFIG, WATCH_NAME_ENV, OSS_CONFIG
        )
    # One state, six remedies -- write a config, unblock a config, reshape a config,
    # add a key, correct a value, repair this tool. The reason travels in the detail
    # rather than being dropped for arriving second, the same way `conflict` carries
    # its override. "Unblock" and "reshape" are two of those six and not one (#216):
    # a file the process cannot read and a file it read and cannot use send the
    # reader to different places.
    return "default", {
        "no-config": "there is no {} to derive one from".format(OSS_CONFIG),
        "unreadable": "{} is there and could not be read, so nothing could be "
        "derived from it".format(OSS_CONFIG),
        # Separate from `unreadable` above: this one WAS read (#216).
        "malformed": "{} is not an object, so nothing could be derived from it -- "
        "the file was read and it parsed, so the remedy is its shape".format(
            OSS_CONFIG
        ),
        "no-repo": "{} carries no repo to derive one from".format(OSS_CONFIG),
        "refused": "{} carries a repo the config validator refuses ({}), and the "
        "launcher refuses it too rather than folding it into a socket path "
        "(#207)".format(OSS_CONFIG, why),
        "no-validator": "the config validator could not be imported, so whether a "
        "name is derivable is unknown -- this is a hole in the diagnostic, not in "
        "{}".format(OSS_CONFIG),
    }[derivable]


def check_watch_channel(project_dir, env=None):
    """Say which channel, and say what the answer does not cover.

    OK here never means "your fleet is private" -- this reads two places and
    compares them; it does not enumerate the pollers holding a slot. Every message
    that could be read as that promise carries the limit, or the check becomes an
    OK nobody measured, which is the shape it exists to report.
    """
    state, detail = watch_channel_state(project_dir, env=env)
    if state == "unreadable":
        report(
            "WARN",
            "watch channel: {}, so whether this repo declares a watch_name is unknown "
            "-- not answered as 'declares none', because that reads as a repo on the "
            "default channel.".format(detail),
        )
        return
    if state == "malformed":
        report(
            "WARN",
            "watch channel: {}, so no watch_name could be read from it. The file WAS "
            "read and it parsed -- this is a document somebody edited into the wrong "
            "shape, not a permission, a lock or an encoding, and not a repo that "
            "declares none. Fix the shape rather than the file's mode.".format(detail),
        )
        return
    if state == "conflict":
        report(
            "WARN",
            "watch channel: {}. The ops are on different channels and nothing resolves "
            "that -- bin/oss-workspace exports none of them. Leave one.".format(detail),
        )
        return
    if state == "overridden":
        report(
            "WARN",
            "watch channel: {} is set, which overrides the name entirely, so whatever "
            "{} and {} say decides nothing. That override is deliberate -- it is the "
            "path a running poller already captured -- but it means this repo's "
            "declaration is not what its pollers use.".format(
                detail, WATCH_CONFIG, WATCH_NAME_ENV
            ),
        )
        return
    if state == "mismatch":
        report(
            "WARN",
            "watch channel: {} and the two differ. The export wins for pollers spawned "
            "here, so this repo's own declaration is not in effect and its board is "
            "some other repo's fleet. The names are not printed; both places to look "
            "are named.".format(detail),
        )
        return
    if state == "derived-export":
        report(
            "OK",
            "watch channel: {} and {} declares no watch_name -- so this is the export "
            "bin/oss-workspace makes for this repo, not a channel it never named. The "
            "repo did name it, in {}, which is tracked and authoritative. This "
            "compares two declarations against a derivation; it does not enumerate "
            "the pollers on that channel, and WHICH server holds the socket is not "
            "established, here or by supertool 'channel:health'.".format(
                detail, WATCH_CONFIG, OSS_CONFIG
            ),
        )
        return
    if state == "undeclared-export":
        report(
            "WARN",
            "watch channel: {} is exported, {} declares no watch_name, and {} -- so "
            "this repo is on a channel it never named, which is what a hand-copied "
            ".claude/settings.local.json produces: every repo carrying that copy "
            "shares one poller slot while each board renders as its own.".format(
                WATCH_NAME_ENV, WATCH_CONFIG, detail
            ),
        )
        return
    if state == "undeclared-export-unknown":
        report(
            "WARN",
            "watch channel: {} is exported, {} declares no watch_name, and {} -- so "
            "whether this is the export bin/oss-workspace derives for this repo or "
            "one copied from another is unknown. Not answered as copied, which would "
            "accuse on no evidence, and not as derived, which would clear on "
            "none.".format(WATCH_NAME_ENV, WATCH_CONFIG, detail),
        )
        return
    if state == "agree":
        report(
            "OK",
            "watch channel: {}, and they match. This compares two declarations; it "
            "does not enumerate the pollers on that channel.".format(detail),
        )
        return
    if state == "declared-only":
        report(
            "OK",
            "watch channel: {} and nothing is exported over it. That reaches supertool's "
            "own ops; the claude-channel consumer is spawned by the harness and does not "
            "read this file, so check delivery with supertool 'channel:health'.".format(
                detail
            ),
        )
        return
    if state == "derived":
        report(
            "OK",
            "watch channel: {}, so bin/oss-workspace exports a name derived from it "
            "and a session it opens gets this repo's own socket. That covers sessions "
            "this launcher opens: a `claude` started by hand here exports nothing and "
            "lands on the shared default. WHICH server holds that socket is not "
            "established, here or by supertool 'channel:health' -- its own report says "
            "so, and it is the half that decides delivery.".format(detail),
        )
        return
    # WARN, not OK. #191 measured this repository in exactly this state, with five
    # events read, five forwarded, zero dropped and none delivered, under a line
    # that said "Nothing is broken". The state was right and the verdict was not:
    # the shared socket is held by one process, first one wins, and the loser is
    # never told.
    report(
        "WARN",
        "watch channel: none declared in {} and {} is unset, and {} -- so this repo "
        "binds the SHARED default socket with every other repo that resolves to no "
        "name. One process holds it, the first one wins, and the loser is never told "
        "(#191). WHICH server holds it is not established, here or by supertool "
        "'channel:health' -- its own report says so, and it is the half that decides "
        "delivery.".format(WATCH_CONFIG, WATCH_NAME_ENV, detail),
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

        # Derived BEFORE the first report, because every count printed below is a count of
        # rules and `rules` is a count of files. `JIT_ENTRY_SKIP` is not an entry: it gets
        # no index row and the dependency's builder skips it, so a layer that documents
        # itself was reported as having one more rule than it has -- in all three arms, one
        # of which is a FAIL that would name a rule the layer does not contain.
        dimension = name.parts[0] if name.parts else ""
        entries = {p.name: p for p in rules if p.name != JIT_ENTRY_SKIP}

        if not index.is_file():
            report(
                "FAIL",
                "{}: {} rule(s) and no {} -- the matcher reads the index, so none of "
                "them run, and that is indistinguishable from rules that matched "
                "nothing. Rebuild the index.".format(name, len(entries), JIT_INDEX),
            )
            continue
        # Read once, and guarded: this used to be an unguarded `read_text` inside the
        # emptiness test, so an index holding a byte sequence that is not UTF-8 raised
        # out of a diagnostic whose whole contract is to exit 0 with a VERDICT line.
        # The tree being diagnosed chooses that file's bytes.
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
                "Rebuild the index.".format(name, JIT_INDEX, len(entries)),
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

        # `entries`, not `rules`: the unfiltered list carries `JIT_ENTRY_SKIP`, which is
        # not an entry, gets no index row, and is skipped by the dependency's builder. A
        # layer that documents itself was reported as having one more rule than it has --
        # and the drift comparison two lines up had already filtered it out, so the count
        # disagreed with the check it was printed beside.
        current = "{}: {} rule(s) indexed, rows match their frontmatter".format(
            name, len(entries)
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


def _gate_verdict(repo_root, config):
    """Would `/oss:scaffold` write the owned changelog trio into this repo at all?

    ``"write"``, ``"declined"`` or ``"unknown"``.

    The verdict only, without scaffold's own detail sentence. That sentence is a whole
    paragraph naming the trio and the override, written for a caller that prints one
    finding; passed through into a report line that already names all three files it
    covers, it said the same thing three times over. What matched is a question
    `/oss:scaffold` answers directly, and the detail lines below say so.

    scaffold declines the trio when the repo already runs a changelog gate under
    another name -- two jobs called `fragment` on every pull request is the failure it
    cannot have. That decline is why this exists: without it `owned_drift` reported
    three files `absent` with the remedy `Run /oss:scaffold.`, forever, in a repo where
    running it declines again. Both halves were correct; the composition was not.

    Read through the PUBLIC `scaffold.check_changelog_gate`, not the private
    `_detect_changelog_gate` and not a decline recorded on disk at scaffold time:

    * A private import couples a diagnostic to a helper nobody owes stability to, and
      that helper is being changed right now (#124).
    * A file written at scaffold time answers "what was true the last time somebody
      ran the command", which is a different question from "what would happen if they
      ran it today" -- and the drift between those two is exactly the class of thing
      this module exists to catch, so introducing another instance of it to fix one
      would be perverse.
    * `check_changelog_gate` is already the function whose whole job is to report this
      to a caller, and it carries a machine-readable `state` per finding.

    The contract relied on is deliberately the narrowest available: an empty result
    means the trio gets written; a non-empty one means it does not. Only `found` is
    read as a decision. Every other state -- `unknown` today, anything a later change
    adds -- lands in `unknown`, so a new state is an addition rather than a break, and
    the failure mode of being out of step is the honest third answer rather than the
    wrong one. A decline that scaffold made because it could not look is not a
    decision anybody took, and reporting it as one would reinstate this repo's own
    defect class one layer up.
    """
    try:
        findings = scaffold.check_changelog_gate(repo_root, config)
    except Exception:  # noqa: BLE001 - a diagnostic never dies on a probe
        return "unknown"

    if not findings:
        return "write"

    states = {str(f.get("state")) for f in findings if isinstance(f, dict)}
    return "declined" if states == {"found"} else "unknown"


def owned_drift(repo_root, config, plugin_root=None):
    """Compare the files this plugin owns in a repo against what it ships today.

    `/oss:scaffold` replaces them on every run -- but an update to the plugin does not
    run the command, so a repo scaffolded months ago still holds the old copies. This
    is the check that makes that visible rather than assumed.

    Five states, and the two added by #126 are the ones that carry the argument:

    `current`   on disk and byte-identical to what the plugin ships
    `drifted`   on disk and different; re-running the scaffold would change it
    `absent`    not on disk, and re-running the scaffold WOULD write it
    `declined`  not on disk because the scaffold refuses to write it here, on purpose
    `unknown`   the comparison, or the question of which of the two above applies,
                could not be answered

    `declined` is not decoration on `absent`. They share the observation -- no file --
    and have opposite remedies: one is fixed by running `/oss:scaffold`, the other is
    *caused* by it, and `--force-owned` is the only thing that changes it. Folded
    together, a declined repo gets a WARN on every run, mid-tick and before every
    release, naming a command that provably changes nothing. `owned_drift_summary`
    argues the same point about a different line: advice printed regardless of state
    carries no information.

    So `declined` reports at OK: it is the designed steady state of a repo that made a
    choice, and it still prints, because a decline that nobody sees is how a repo ends
    up with no changelog gate at all while looking clean.
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

    # Asked once, lazily: it walks the repo tree, and it only changes an answer on
    # the absent branch. A repo whose owned files are all present never pays for it.
    gate = []

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

        # `Path.is_file()` cannot be used here, and neither can `os.path.isfile`: both
        # answer the wrong question in a different way on each interpreter. Before 3.13
        # `is_file()` re-raises anything that is not "this path is not there", so an
        # owned file inside a directory this process cannot traverse raised
        # `PermissionError` and took out doctor's *exit 0 always, one VERDICT line*
        # contract. From 3.13 the same call answers False -- which is worse, because an
        # unreadable file then reports as an *absent* one with `Run /oss:scaffold.`
        # beside it, and nothing raises to say otherwise. CI runs 3.9-3.12 and this was
        # written on 3.14, so the local suite was green while eight legs were red.
        #
        # `os.stat` raises on every version instead, which makes the three states a
        # property of the call rather than of the runner: absent, present, or could not
        # look. The exception already in hand settles which -- the filesystem is not
        # asked a second question to explain why the first one failed.
        try:
            mode = os.stat(str(target)).st_mode
        except (FileNotFoundError, NotADirectoryError):
            present = False
        except OSError as exc:
            findings.append(
                {
                    "path": name,
                    "state": "unknown",
                    "detail": "{}: could not be looked at ({}), so whether this repo has "
                    "it is unknown -- not absent".format(name, type(exc).__name__),
                }
            )
            continue
        else:
            present = stat.S_ISREG(mode)

        if not present:
            if not gate:
                gate.append(_gate_verdict(repo_root, config))
            verdict = gate[0]
            if verdict == "declined":
                findings.append(
                    {
                        "path": name,
                        "state": "declined",
                        "detail": "{}: absent on purpose -- this repo already runs a "
                        "changelog gate under a different name, so /oss:scaffold "
                        "declines the trio and will decline it again. Run "
                        "/oss:scaffold to see which file matched; pass --force-owned "
                        "to write ours anyway.".format(name),
                    }
                )
            elif verdict == "unknown":
                findings.append(
                    {
                        "path": name,
                        "state": "unknown",
                        "detail": "{}: not in this repo, and whether /oss:scaffold "
                        "would write it could not be determined -- so this is neither "
                        "a gap nor a decision. Run /oss:scaffold, which reports what "
                        "it could not read.".format(name),
                    }
                )
            else:
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
    keeps the states apart without the grouping needing to know them: `absent`,
    `drifted`, `declined` and `unknown` say different things, `unknown` is a check that
    could not look rather than a pass, and `declined` is a file the scaffold refuses to
    write here rather than one it has not written yet. `current` stays one OK line per
    file; a clean repo's output is not what was wrong here.

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
        # `declined` joins `current` at OK. It is not a gap: the file is absent
        # because /oss:scaffold refuses to write it into this repo, every run, and
        # nothing the reader can do about it is an improvement. Warned about, it is a
        # line that appears on every run of a correctly configured repo and names a
        # remedy that changes nothing -- which is what the docstring above says makes
        # a line worthless. It still prints, because a decline nobody ever sees is how
        # a repo ends up with no changelog gate while reading as clean.
        level = "OK" if state in ("current", "declined") else "WARN"
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


#: The dependency that consumes ``JIT_RULES_DIR``. It is declared in this plugin's own
#: manifest, and the check below refuses to answer if it stops being declared rather
#: than quietly measuring a plugin nobody depends on any more.
JIT_PLUGIN = "claude-jit-context"

PLUGIN_CACHE_ROOT = "~/.claude/plugins/cache"

#: A *fixed layer list* in a hook, matched by shape rather than by its current spelling.
#:
#: The hooks hold ``split("00-manual 10-auto 20-grouped 30-crosscutting", layers, " ")``
#: today, and matching that string is the version of this check that breaks the moment
#: it is fixed: `claude-jit-context#176` replaces the literal, and a check keyed on the
#: old spelling would then report `unread` forever -- #119 inverted, and harder to
#: notice because the wrong answer is the one everybody already expects.
#:
#: So the pattern is "a quoted run of two or more layer-shaped tokens". It survives a
#: reordering, a fifth layer, a rename of the awk variable, and a move to another
#: language. What it does NOT survive is the list going away entirely -- which is the
#: expected fix, and which lands in `could-not-determine` rather than in a verdict.
JIT_LAYER_ENUMERATION = re.compile(
    r"""(["'])(\d\d-[A-Za-z0-9][A-Za-z0-9-]*(?:[ \t]+\d\d-[A-Za-z0-9][A-Za-z0-9-]*)+)\1"""
)

#: Where a Claude Code plugin declares the scripts the runtime executes. The manifest is
#: what separates a hook from a file that merely sits in the same tree (#241): the
#: installed 0.4.0 answered this check off `tests/test-layer-enumeration.sh`, the
#: dependency's own positive control for its enumerator -- a true sentence reached through
#: a file that enumerates nothing at run time, and one that would have printed `reads`
#: with the broken fixed list still in the hooks. A path prefix would not do: 0.4.0's real
#: enumeration lives in `scripts/common.sh`, beside eight scripts nothing wires to an
#: event.
JIT_HOOK_MANIFEST = ("hooks", "hooks.json")

#: A `*.sh` path inside a hook command. `${CLAUDE_PLUGIN_ROOT}` is the documented spelling
#: for the install root; anything else still holding a `$` after substitution is reported
#: as unresolved rather than guessed at.
JIT_HOOK_COMMAND_SCRIPT = re.compile(r"""[^\s"';|&()<>]*\.sh""")

#: `source foo.sh` / `. foo.sh`. A hook's layer list may live in a file it sources -- up to
#: 0.3.5 it lived in the three entry points, and in 0.4.0 the enumerator lives in
#: `common.sh` -- so the hook set is the closure, not the manifest's own list.
JIT_SOURCE_DIRECTIVE = re.compile(r"""(?:^|[\s;&|(])(?:\.|source)\s+(.*)$""")
JIT_SCRIPT_BASENAME = re.compile(r"""([\w.+-]+\.sh)""")

#: State -> level. `unread` is WARN and not OK, and not FAIL.
#:
#: Not OK: #146 chose OK for a sentence equally true on every machine forever, because a
#: permanent WARN pins every repo at `usable with gaps` and costs the verdict its
#: discrimination. This is not that. A layer that provably never fires is a real gap
#: with a real consequence -- every rule in it is written, indexed, listed by the check
#: above, and read by nothing -- and it clears the day an installed version fixes it, so
#: it does not pin anybody permanently.
#:
#: Not FAIL: nothing is broken. The repo builds, the tests run, the tick works. What is
#: lost is the injection, which is an improvement not a dependency.
JIT_LAYER_LEVELS = {
    "reads": "OK",
    "no-layer": "OK",
    "unread": "WARN",
    "could-not-determine": "WARN",
}


def jit_hook_roots(record=None, cache_root=None):
    """``(roots, version)`` -- where the *running* ``claude-jit-context`` is unpacked.

    The version comes from the install record for the reason ``active_versions``
    documents at length: old versions stay unpacked on disk and a cache listing returns
    whichever sorts last, so a directory glob answers "what was ever installed" to a
    question that was about what runs.

    ``installPath`` from that same record is preferred over rebuilding the cache path,
    because it is the runtime's own answer rather than this file's second copy of a
    layout it does not own. The glob is the fallback for records that predate the field.
    """
    version = active_versions([JIT_PLUGIN], record).get(JIT_PLUGIN)
    if not version:
        return [], None

    roots = []
    path = Path(record or os.path.expanduser(INSTALL_RECORD))
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    plugins = doc.get("plugins") if isinstance(doc, dict) else None
    for key, entries in (plugins or {}).items() if isinstance(plugins, dict) else ():
        if key.split("@", 1)[0] != JIT_PLUGIN or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("version") != version:
                continue
            if entry.get("installPath"):
                roots.append(Path(str(entry["installPath"])))

    if not roots:
        cache = Path(cache_root or os.path.expanduser(PLUGIN_CACHE_ROOT))
        try:
            roots = [
                candidate
                for candidate in sorted(
                    cache.glob("*/{}/{}".format(JIT_PLUGIN, version))
                )
                if candidate.is_dir()
            ]
        except OSError:
            roots = []
    return list(dict.fromkeys(roots)), version


def _jit_manifest_paths(root):
    """``(entries, rejected)`` -- where this plugin declares its hooks.

    ``entries`` is ``[(path, as-written)]``. The second element is carried rather than
    recomputed: the "no hook manifest" message names the path that was looked for, and a
    message naming the convention while a manifest key named something else is a
    diagnostic answering a question nobody asked.

    ``.claude-plugin/plugin.json`` may name the file. When it names one this cannot
    resolve -- ``..``, a drive, empty -- ``rejected`` carries the string **as the plugin
    wrote it** and there are no entries at all. It deliberately does not fall back to the
    convention, and that is the stronger of the two available answers: falling back reads
    a file the plugin did not name, which is #241's own substitution one field over. The
    cheap half of that bug is a message quoting the wrong path; the expensive half is a
    conventional manifest happening to sit there, which would have produced a confident
    ``reads`` with nothing anywhere recording that the declaration was ignored.
    """
    named = None
    try:
        doc = json.loads(
            root.joinpath(".claude-plugin", "plugin.json").read_text(encoding="utf-8")
        )
        if isinstance(doc, dict) and isinstance(doc.get("hooks"), str):
            named = doc["hooks"]
    except (OSError, ValueError):
        named = None
    if named:
        parts = _jit_path_parts(named)
        if not parts:
            return [], _one_line(named)
        return [(root.joinpath(*parts), "/".join(parts))], None
    parts = list(JIT_HOOK_MANIFEST)
    return [(root.joinpath(*parts), "/".join(parts))], None


def _jit_path_parts(token):
    """A manifest path as components, or ``None`` if it is not one this can resolve.

    ``os.sep`` rather than a hardcoded separator: a Windows-style path in a manifest
    splits on the platform that wrote it, and a backslash stays an ordinary filename
    character on POSIX, where it legally is one. A component that would climb out of the
    install root resolves to nothing rather than to a file outside the tree.

    Two components are refused, and the second is Windows-only in effect but guarded
    unconditionally because a guard that only fires on the platform that broke is a guard
    nobody re-reads. ``..`` climbs out. A component carrying a colon is a drive or a
    stream specifier: ``PureWindowsPath("C:/plugin").joinpath("D:", "x.sh")`` is
    ``D:x.sh`` -- the anchor resets and the join lands outside the install root
    entirely, which would then be stat'ed and read. A colon is not a legal filename
    character on Windows and is vanishingly rare on POSIX, so refusing it costs nothing
    and is one refusal rather than a table of platform behaviours.
    """
    parts = [
        part
        for part in token.replace(os.sep, "/").split("/")
        if part not in ("", ".")
    ]
    if not parts or ".." in parts:
        return None
    if any(":" in part for part in parts):
        return None
    return parts


def _jit_commands(node, out):
    """Every ``command`` string anywhere in a hooks manifest, shape-agnostically."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "command" and isinstance(value, str):
                out.append(value)
            else:
                _jit_commands(value, out)
    elif isinstance(node, list):
        for value in node:
            _jit_commands(value, out)


def _jit_hook_files(roots):
    """``(hooks, problem, unresolved)`` -- which scripts the dependency actually runs.

    #241. Reading every ``*.sh`` under the install root answers "does any file in this
    tree contain a layer list", which is not the question: the tree also ships the
    dependency's own test suite, and a fixture asserting that the enumerator works
    contains the same string as the enumerator. It contains it *whether or not the
    enumerator was ever fixed*, so that scan could not distinguish the two worlds it
    exists to distinguish.

    A hook is what the runtime executes: a script named by a ``command`` in the plugin's
    hooks manifest, plus the transitive closure of what those scripts ``source``. Both
    halves are needed and neither is a path convention -- 0.4.0 declares five commands
    under ``scripts/`` and puts the enumeration in ``scripts/common.sh``, which it
    declares nowhere and every hook sources.

    ``problem`` is the third state: no manifest at all means there is no way to tell a
    hook from a fixture, and that is a non-answer rather than a scan of everything.
    ``unresolved`` collects declared or sourced targets that did not resolve to a file,
    so a manifest pointing at nothing cannot read as a manifest pointing at nothing
    wrong.
    """
    hooks, unresolved, manifests, looked = [], [], [], []
    unparsed, rejected = [], []
    for root in roots:
        entries, refused = _jit_manifest_paths(root)
        if refused:
            rejected.append(refused)
        for manifest, written in entries:
            looked.append(_one_line(written))
            try:
                doc = json.loads(manifest.read_text(encoding="utf-8"))
            except FileNotFoundError:
                continue
            except (OSError, ValueError) as exc:
                # Unreadable is not empty. These used to join `unresolved` and share the
                # "named nothing this could resolve to a file" sentence with a manifest
                # that parsed to `{}` -- the right state, asserting the wrong thing about
                # the file, with the truth demoted to a parenthetical.
                unparsed.append(
                    "{}: {}".format(_one_line(manifest.name), _one_line(str(exc)))
                )
                manifests.append(manifest)
                continue
            manifests.append(manifest)
            commands = []
            _jit_commands(doc, commands)
            for command in commands:
                for token in JIT_HOOK_COMMAND_SCRIPT.findall(command):
                    cleaned = token.replace("${CLAUDE_PLUGIN_ROOT}", "").replace(
                        "$CLAUDE_PLUGIN_ROOT", ""
                    )
                    parts = None if "$" in cleaned else _jit_path_parts(cleaned)
                    candidate = root.joinpath(*parts) if parts else None
                    if candidate is not None and _jit_is_file(candidate):
                        hooks.append(candidate)
                    else:
                        unresolved.append(_one_line(token))

    if rejected:
        return (
            [],
            "declares its hooks at {} in .claude-plugin/plugin.json, which is not a path "
            "this can resolve inside the install tree. It deliberately did not fall back "
            "to the conventional location: measuring a file the plugin did not name is "
            "how a fixture came to answer this check (#241). Nothing was measured.".format(
                "; ".join(dict.fromkeys(rejected))
            ),
            unresolved,
            unparsed,
        )

    if not manifests:
        return (
            [],
            "carries no hook manifest ({}), so which of its scripts the runtime executes "
            "-- as opposed to ships -- is not something this can tell, and a scan of "
            "every file in the tree would be answered by the dependency's own test "
            "fixtures (#241). Nothing was measured.".format(
                "; ".join(dict.fromkeys(looked)) or "/".join(JIT_HOOK_MANIFEST)
            ),
            unresolved,
            unparsed,
        )

    # The sourced closure. Comments are skipped for the same reason the enumeration scan
    # skips them: prose quoting a `source` line is not a `source` line.
    seen, queue = set(), list(hooks)
    ordered = []
    while queue:
        path = queue.pop(0)
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Left for the caller's scan to record: it reads the same files and its
            # `unreadable` arm is where an incomplete read is supposed to land.
            continue
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            directive = JIT_SOURCE_DIRECTIVE.search(line)
            if not directive:
                continue
            basename = JIT_SCRIPT_BASENAME.search(directive.group(1))
            if not basename:
                continue
            sourced = path.parent / basename.group(1)
            if _jit_is_file(sourced):
                queue.append(sourced)
            else:
                unresolved.append(_one_line(basename.group(1)))
    return ordered, None, unresolved, unparsed


def _jit_is_file(path):
    try:
        return path.is_file()
    except OSError:
        return False


def _jit_layer_verdict(project_dir, layer, record, cache_root):
    """``(state, detail)`` for one question: does the installed dependency read ``layer``?

    Four states, and the honest third one is the reason this exists. #119: every
    observable signal said the layer was healthy -- files on disk, index rows current,
    ``check_jit_rules`` above listing them clean -- and nothing anywhere asked whether
    anything reads the directory. Nothing did, and had not since the layer was created.

    Reading the dependency's own shipped hook scripts is a read outside the project
    tree, and that is deliberate and in bounds. The ownership contract governs what this
    plugin **writes**; ``active_versions`` and ``dependency_repositories`` already read
    the same install record and the same cache to answer smaller questions. Nothing else
    can answer this one: the contract being checked belongs to another repository and
    lives in that repository's files.

    ``detail`` is composed here and printed by the caller through ``report``, so hook
    filenames -- text from a tree this script does not own -- go through ``_one_line``.
    """
    if not layer:
        return (
            "could-not-determine",
            "the layer name comes from oss_rules.LAYER and that module could not be "
            "imported, so there was nothing to look for",
        )

    if JIT_PLUGIN not in (declared_dependencies() or []):
        return (
            "could-not-determine",
            "{} is no longer a declared dependency of this plugin, so which component "
            "is supposed to read {}/*/{}/ is not something this can assume".format(
                JIT_PLUGIN, JIT_RULES_DIR, layer
            ),
        )

    try:
        dimensions = sorted(
            path.parent.name
            for path in Path(project_dir).joinpath(JIT_RULES_DIR).glob("*/" + layer)
            if path.is_dir()
        )
    except OSError as exc:
        return (
            "could-not-determine",
            "{}/ would not be listed ({}), so whether this repo even has a {} layer is "
            "unknown".format(JIT_RULES_DIR, _one_line(str(exc)), layer),
        )

    if not dimensions:
        return (
            "no-layer",
            "this repo has no {}/*/{}/ , so there is nothing here for {} to read. Run "
            "/oss:scaffold if you want this plugin's own rules injected.".format(
                JIT_RULES_DIR, layer, JIT_PLUGIN
            ),
        )

    roots, version = jit_hook_roots(record, cache_root)
    named = "{} {}".format(JIT_PLUGIN, version) if version else JIT_PLUGIN
    if not roots:
        return (
            "could-not-determine",
            "{} carries {} rule(s) for {}, and the running {} could not be located -- it "
            "is absent from the install record, the record would not read, or the "
            "version it names is not unpacked. Nothing was measured.".format(
                layer, len(dimensions), ", ".join(dimensions), named
            ),
        )

    scripts, hook_problem, unresolved, unparsed = _jit_hook_files(roots)
    if hook_problem:
        # `hook_problem` is a whole clause rather than a keyword, because the two cases it
        # covers -- no manifest, and a manifest path this refused -- have nothing in
        # common but their state, and a shared sentence with the difference in a
        # parenthetical is the defect two arms below used to have.
        return (
            "could-not-determine",
            "{} is recorded as installed and {}".format(named, hook_problem),
        )
    if not scripts:
        if unparsed:
            return (
                "could-not-determine",
                "{} is recorded as installed and no hook script (*.sh) was found under "
                "it -- its hook manifest would not be read ({}) -- so what reads {} was "
                "never measured. That is a fact about the file, not about its "
                "contents.".format(named, "; ".join(unparsed[:3]), layer),
            )
        return (
            "could-not-determine",
            "{} is recorded as installed and no hook script (*.sh) was found under it -- "
            "its hook manifest named nothing this could resolve to a file{} -- so what "
            "reads {} was never measured".format(
                named,
                " ({})".format("; ".join(unresolved[:3])) if unresolved else "",
                layer,
            ),
        )

    unreadable = []
    naming, omitting = [], []
    for path in scripts:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # The exception in hand says what went wrong. Asking the filesystem a second
            # question to explain the first is how release_delta.py took down the
            # release gate.
            unreadable.append(
                "{}: {}".format(_one_line(path.name), _one_line(str(exc)))
            )
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                # Prose about the layer list is not the layer list. Both hook trees
                # carry comments quoting it, and one of them quotes a stale copy.
                continue
            for _, listed in JIT_LAYER_ENUMERATION.findall(line):
                site = _one_line("{}:{}".format(path.name, number))
                (naming if layer in listed.split() else omitting).append(site)

    if naming:
        # A positive answer stands on its own evidence: one enumeration naming the layer
        # is a hook that reads it, and no file this could not open can unsay that.
        return (
            "reads",
            # `dimensions`, so the noun is `dimension(s)`. It read `rule(s)`, which is a
            # different number and the one a reader would quote: this repo ships three
            # dimensions and more rules than that.
            "{} names {} in its layer list ({}), so the {} dimension(s) under {}/*/{}/ are "
            "reachable".format(
                named, layer, ", ".join(naming[:3]), len(dimensions), JIT_RULES_DIR, layer
            ),
        )

    incomplete = unreadable + unresolved + unparsed
    if incomplete:
        # `unresolved` belongs here and not only in the empty-hook-set arm above. A
        # manifest declaring two hooks where one is missing, and where the one that
        # survived omits the layer, is not evidence of a gap: the missing hook is exactly
        # where the enumeration might have been. An incomplete scan cannot say `unread`,
        # for the same reason an unreadable file cannot.
        return (
            "could-not-determine",
            "{} hook file(s) under {} would not be read, or were declared or sourced and "
            "not found ({}), so the scan is incomplete and nothing here says whether {} "
            "is read".format(
                len(incomplete), named, "; ".join(incomplete[:3]), layer
            ),
        )

    if omitting:
        return (
            "unread",
            "{} enumerates layers from a fixed list that does not include {} ({}), so "
            "every rule under {}/*/{}/ -- {} dimension(s), {} -- is written, indexed and "
            "read by nothing. The fix belongs to that plugin "
            "(Digital-Process-Tools/claude-jit-context#176); until an installed version "
            "carries it, treat those rules as inert rather than as active.".format(
                named, layer, ", ".join(omitting[:3]), JIT_RULES_DIR, layer,
                len(dimensions), ", ".join(dimensions),
            ),
        )

    outside, unwalkable = _jit_layer_lists_outside(roots, scripts)
    partial = (
        " {} path(s) under it could not be walked or read ({}), so this did not see the "
        "whole tree.".format(len(unwalkable), "; ".join(unwalkable[:3]))
        if unwalkable
        else ""
    )
    if outside:
        # The judgement call in #241, taken the honest way: a layer list in a file the
        # runtime never executes is *reported as the reason this is unknown*, not
        # silently dropped. Dropping it renders identically to a tree with no layer list
        # anywhere, and the file that supplied the wrong kind of evidence is the single
        # most useful thing a reader can be handed.
        return (
            "could-not-determine",
            "{} hook script(s) of {} were read and none carries a fixed layer list. The "
            "only layer list(s) found are outside the hook set ({}) -- files the runtime "
            "never executes, typically that plugin's own test fixtures, which name {} "
            "whether or not anything enumerates it. So this is unknown, not a pass: a "
            "fixture answered this check for a whole release (#241).{}".format(
                len(scripts), named, ", ".join(outside[:3]), layer, partial
            ),
        )

    return (
        "could-not-determine",
        "{} hook script(s) of {} were read and none carries a fixed layer list, so "
        "whether {} is read could not be determined from the hooks on disk. That is "
        "what an enumerate-the-directory implementation looks like -- the shape the "
        "upstream fix takes -- which is why this is unknown rather than a gap.{}".format(
            len(scripts), named, layer, partial
        ),
    )


def _jit_layer_lists_outside(roots, scripts):
    """``(sites, unreadable)`` -- layer lists in the install tree that no hook reaches.

    Read only to *explain* a non-answer, never to produce one. Anything found here is by
    construction a file the runtime does not execute.

    ``os.walk(onerror=...)`` and not ``Path.rglob``. This function is the one place left
    that walks the whole install tree, and the first version of it wrapped ``rglob`` in
    ``except OSError`` -- which ``CLAUDE.md``'s traps list already records as unable to
    fire, because pathlib's recursive glob swallows ``PermissionError`` mid-walk and
    yields nothing for that subtree. So "the tree holds no layer list outside the hook
    set" and "this could not read the tree" came back identical, in a function whose
    entire job is explaining why something could not be determined. There is no argument
    to ``rglob`` that makes it speak; the walk has to be one that reports.

    ``unreadable`` is returned separately rather than folded into ``sites`` for the same
    reason ``_workflow_scan`` returns two lists: an empty ``sites`` already means "read
    the whole tree, found nothing", and that is a different sentence.
    """
    inside = {str(path) for path in scripts}
    sites, unreadable = [], []

    def _note(exc):
        where = getattr(exc, "filename", None) or ""
        unreadable.append(
            "{}: {}".format(
                _one_line(os.path.basename(str(where))), _one_line(str(exc))
            )
        )

    for root in roots:
        for directory, _subdirectories, names in os.walk(str(root), onerror=_note):
            for name in sorted(names):
                if not name.endswith(".sh"):
                    continue
                path = Path(directory) / name
                if str(path) in inside:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    # Not a gap in the walk: a binary or mis-encoded file cannot be a
                    # shell script carrying a layer list, and saying the tree was not
                    # fully seen because of one would be a false alarm.
                    continue
                except OSError as exc:
                    unreadable.append(
                        "{}: {}".format(_one_line(name), _one_line(str(exc)))
                    )
                    continue
                for number, line in enumerate(text.splitlines(), 1):
                    if line.lstrip().startswith("#"):
                        continue
                    if JIT_LAYER_ENUMERATION.search(line):
                        sites.append(_one_line("{}:{}".format(name, number)))
    return sites, unreadable


def jit_layer_readers(project_dir, layer=None, record=None, cache_root=None):
    """Does anything read this plugin's rule layer? ``[{state, detail}]``, one entry.

    The verdict is computed by ``_jit_layer_verdict`` and emitted here, once. Every
    branch of the vocabulary is pinned by ``tests/test_jit_layer_readers.py``, which
    asserts all four states were **observed** before checking the level table against
    them -- a table checked against an empty set of states is trivially complete, which
    is the failure this whole check is about.
    """
    name = layer or (oss_rules.LAYER if oss_rules is not None else None)
    state, detail = _jit_layer_verdict(project_dir, name, record, cache_root)
    return [{"state": state, "detail": "jit rule layer: {}".format(detail)}]


def check_jit_layer_readers(project_dir, record=None, cache_root=None):
    for finding in jit_layer_readers(project_dir, record=record, cache_root=cache_root):
        report(JIT_LAYER_LEVELS.get(finding["state"], "WARN"), finding["detail"])


def check_ci_enforcement(project_dir, config):
    """Does anything in CI run the tests?

    A merge gate that passes because nothing ran is the worst of the three states: it
    reads exactly like a gate that passed because everything was checked.

    It no longer asks how many legs there are. That number was `ci.required_checks`,
    and #113 deleted it: nothing offline can produce it, so the config could only ever
    carry a guess wearing a measurement's clothes.
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

    # A key this plugin no longer reads, left on disk by an earlier version (#113).
    # It is not an error and the config validates without complaint -- but tolerated
    # is not the same as invisible, and a dead measurement sitting in .oss.json reads
    # exactly like a live one to the next person who opens the file. Fired off the
    # key's presence, so a repo without it hears nothing.
    if "ci" in config:
        report(
            "WARN",
            "ci.required_checks: no longer read by anything, and safe to delete from "
            ".oss.json. It counted workflow job declarations, which a build matrix, a "
            "reusable workflow or an org/app-level check multiplies or adds to "
            "invisibly -- so the number was never the merge gate's. Count the legs on "
            "the pull request instead: gh pr checks",
        )


# Every `oss:NAME` spawn written into this plugin's own documents. The names are read
# off the documents rather than listed here: a list would be a fact about the plugin
# kept in a second place, and the one that drifts is always the copy nobody edits.
AGENT_DISPATCH_RE = re.compile(r'subagent_type:\s*"oss:([A-Za-z0-9_-]+)"')

# Directories of this plugin that dispatch agents. `agents/` is included because an
# agent may spawn another one -- developer.md does.
DISPATCHING_DIRECTORIES = ("commands", "skills", "agents")

# The clause that keeps the line from being read as "the agents work", and the remedy
# for the one failure that has actually been observed.
#
# It rides on the line rather than getting its own, and it is OK rather than WARN, on
# purpose. A permanent warning is not a signal: this sentence is equally true on every
# machine, every run, forever, so counting it into the verdict would put every repo at
# "usable with gaps" and cost the verdict the discrimination it exists for -- and #140
# quotes exactly such a verdict as the thing whose one warning the reader had to go
# hunting for. What #140 needs is that the report is not SILENT about agents, which is
# what produced two wrong diagnoses; it does not need a finding invented to carry it.
#
# The wording deliberately avoids "not checked", which #140 suggested -- and so does
# every other branch of this function. That phrase is already taken: two suites assert
# it appears for every unmeasured label when .oss.json is absent and appears NOWHERE
# when it is present, and `commands/doctor.md` tells its reader all five of its uses
# mean the config was missing, so nothing below is evidence either way. Reusing it for
# a fact that is unobservable in principle would make a maintainer read a configured
# repo as a misconfigured one, and would silently retire an invariant -- a worse outcome
# than picking a phrase.
NOT_OBSERVABLE_HERE = (
    "whether this session can dispatch to them cannot be determined from here -- it is "
    "a fact about the harness's agent registry, which no script can read; if a spawn "
    "fails with 'Agent type not found', run /reload-plugins and try again (#140)"
)


def agent_dispatch(plugin_root=None):
    """Cross-reference the agent names this plugin dispatches against the files it ships.

    Returns ``[(level, message)]`` rather than printing, so the states are testable.

    Three of them, and the third is why this exists at all. ``ok``: every dispatched
    name has an ``agents/<name>.md``. A finding: a name with no file, or a document
    that could not be read, which is a hole in the cross-reference and not an absence
    of findings. And ``unknown``: nothing was scanned, which is trivially clean --
    "no dispatched name lacks a file" is true of the empty set -- and would otherwise
    print an OK line about a tree the check never found.

    What it CANNOT see is stated on the line rather than left out of it. Registration
    lives in the harness's agent registry; no python process can query it. #81 is the
    bill for leaving that unsaid: two of the four shipped agents did not register, the
    release gate's blocking security audit dispatched to a name that resolved to
    nothing for two versions, and a gate that never ran read exactly like a gate that
    passed. A check reporting "four agent files ship and are well-formed" would have
    called that healthy -- this repo's own defect class, inside the checker written to
    catch it -- so this one reports what it measured and names what it did not.
    """
    root = PLUGIN_ROOT if plugin_root is None else Path(plugin_root)
    dispatched = {}  # name -> the documents that spawn it
    unreadable = []
    scanned = 0
    for directory in DISPATCHING_DIRECTORIES:
        base = root / directory
        try:
            paths = sorted(base.rglob("*.md"))
        except OSError as exc:
            unreadable.append("{}/: {}".format(directory, _one_line(str(exc))))
            continue
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                # The exception in hand answers what went wrong. Asking the filesystem
                # a second question to explain the first is how release_delta.py's
                # _read_config took down the release gate.
                unreadable.append("{}: {}".format(path.name, _one_line(str(exc))))
                continue
            scanned += 1
            for name in AGENT_DISPATCH_RE.findall(text):
                dispatched.setdefault(name, set()).add(path.name)

    lines = []
    # "could not be checked", never "not checked". `commands/doctor.md` enumerates the
    # five labels that say `not checked` and tells its reader that all of them mean one
    # thing: .oss.json was absent, so nothing below is evidence either way. These
    # branches are a sixth source with a different cause -- the plugin's own tree is
    # empty or unreadable, which IS a finding about the plugin -- and borrowing the
    # phrase would have a reader wave it off as expected fallout from unset config.
    if not scanned and not unreadable:
        return [
            (
                "WARN",
                "agent dispatch: could not be checked -- no documents found under {} in "
                "{}, so nothing was cross-referenced".format(
                    "/, ".join(DISPATCHING_DIRECTORIES) + "/", root
                ),
            )
        ]
    for detail in unreadable:
        lines.append(
            (
                "WARN",
                "agent dispatch: could not read {} -- the cross-reference below is "
                "incomplete by that much".format(detail),
            )
        )

    try:
        shipped = {path.stem for path in (root / "agents").glob("*.md")}
    except OSError as exc:
        return lines + [
            (
                "WARN",
                "agent dispatch: could not be checked -- agents/ could not be listed "
                "({}), so "
                "there was nothing to check the dispatched names against".format(
                    _one_line(str(exc))
                ),
            )
        ]

    missing = sorted(name for name in dispatched if name not in shipped)
    if missing:
        lines.append(
            (
                "FAIL",
                "agent dispatch: {} spawned by {} but no agents/<name>.md ships it".format(
                    ", ".join("oss:" + name for name in missing),
                    ", ".join(sorted(set().union(*(dispatched[n] for n in missing)))),
                ),
            )
        )
        return lines

    if not dispatched:
        lines.append(
            (
                "WARN",
                "agent dispatch: could not be checked -- {} document(s) read and none "
                "spawns an "
                "oss: agent, so nothing was cross-referenced".format(scanned),
            )
        )
        return lines

    # Every SHIPPED agent is named, not only the dispatched ones. #140 asks for the four
    # individually, and two of them (developer, triager) are spawned by a human out of
    # the manager loop rather than by a document, so a list of dispatched names would
    # silently omit exactly the two whose absence started this.
    lines.append(
        (
            "OK",
            "agent dispatch: {} agent file(s) ship ({}) and every oss: name this "
            "plugin's documents spawn has one -- {}".format(
                len(shipped),
                ", ".join("oss:" + name for name in sorted(shipped)),
                NOT_OBSERVABLE_HERE,
            ),
        )
    )
    return lines


def check_agent_dispatch(plugin_root=None):
    for level, message in agent_dispatch(plugin_root):
        report(level, message)


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


# --- which copy of this plugin answered this invocation (#262, #248) ---------------
#
# The obvious detector -- do the two manifests declare the same version -- provably
# cannot answer this. The version does not move between releases, so an installed
# copy sitting at the tag and a clone a whole cycle past it declare the same number,
# and `yes` comes back for the healthy case and the skewed one alike. Measured
# 2026-08-16: the same agent report validated `ok` against the clone's schema and
# `expected 1, got 2` against a cache declaring the identical version.
#
# So the comparison is over content, and the report is over *provenance*: which root
# this invocation answered from, and whether the checkout being diagnosed carries the
# same bytes. Reporting rather than refusing is deliberate -- disagreement is the
# normal state for the whole window between a merge and a release, and a check that
# refused there would be switched off within a week.

#: What decides behaviour: the text a command or a skill injects, the agents it
#: dispatches, and the scripts it runs. Deliberately not a version number.
COMPARED_DIRECTORIES = ("agents", "commands", "scripts", "skills")

#: Compared as bytes as well, so a manifest edit is visible. Read for its ``name``
#: -- never for its ``version``, which is the field this whole check exists because
#: nobody can rely on.
COMPARED_FILES = (".claude-plugin/plugin.json",)

SKIPPED_DIRECTORIES = frozenset({".git", "__pycache__"})

#: On every scope line, in all three of its states. #248 is a session resolving one
#: command's text once and holding it for the whole turn; a line that reported the
#: copy behind THIS command as though it spoke for the session would be the same
#: defect one layer up, wearing a receipt.
SESSION_CAVEAT = (
    "This is one command's copy -- nothing here says which copy answered any other "
    "command or skill in this session."
)


def plugin_tree_digest(root):
    """``({relative posix path: sha256}, [unreadable detail])``.

    Two returns rather than one, for the reason ``_workflow_scan`` has two: a walk
    that could not enter a subtree and a subtree with nothing in it produce the same
    empty mapping, and the caller has to be able to tell them apart. ``Path.rglob``
    cannot -- it swallows ``PermissionError`` while walking and simply yields less --
    so this is ``os.walk(onerror=...)``, which is the only walk that can report.

    A directory that is absent is not a failure to look: a plugin need not ship every
    one of these. That is classified off the exception already in hand rather than by
    asking the filesystem a second question, because ``Path.exists()`` swallows a
    short list of errnos and re-raises the rest.

    CRLF is folded to LF before hashing. A checkout with ``autocrlf`` on and an
    installer's unpacked copy would otherwise differ in every file, which is a verdict
    about line endings dressed as a verdict about contracts. The cost is stated rather
    than hidden: a difference that is ONLY line endings is invisible here.

    Keys are relative POSIX paths, so the two sides compare equal on Windows, where
    the walk yields backslashes.
    """
    root = Path(root)
    files = {}
    unreadable = []

    def onerror(exc):
        if isinstance(exc, FileNotFoundError):
            return
        unreadable.append(
            "{}: {}".format(
                _one_line(getattr(exc, "filename", "?"), limit=120), exc.__class__.__name__
            )
        )

    targets = []
    for name in COMPARED_DIRECTORIES:
        for dirpath, dirnames, filenames in os.walk(str(root / name), onerror=onerror):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIPPED_DIRECTORIES)
            for filename in sorted(filenames):
                targets.append(Path(dirpath) / filename)
    for relative in COMPARED_FILES:
        targets.append(root.joinpath(*relative.split("/")))

    for path in targets:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            continue
        except OSError as exc:
            unreadable.append(
                "{}: {}".format(_one_line(str(path), limit=120), exc.__class__.__name__)
            )
            continue
        try:
            key = path.relative_to(root).as_posix()
        except ValueError:  # pragma: no cover - every target is built under root
            continue
        files[key] = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
    return files, unreadable


def _git_head(root):
    """A label, not the verdict. The content digest is what decides agreement; this
    is here so a human can say *which commit* in one glance, and it says so plainly
    when it cannot -- an installed copy is usually not a git tree at all.
    """
    if shutil.which("git") is None:
        return "git not on PATH"
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            timeout=10,
        )
    except Exception:  # noqa: BLE001 - a diagnostic never dies on a probe
        return "git HEAD could not be read"
    if done.returncode != 0:
        return "no git HEAD here"
    return "git HEAD {}".format(_one_line(done.stdout, limit=40))


def _tree_identity(root, files, unreadable=()):
    """A content digest over what was read, and how much of it was not.

    ``unreadable`` is part of the identity rather than a separate line, because a
    digest over 20 of 26 files and a digest over all 26 print the same shape, and the
    branches that never reach a comparison -- a repo that is not a checkout of this
    plugin, a manifest that would not parse -- print this string and nothing else. A
    partial scan rendered as a whole one there is exactly the absence this file is
    named after.
    """
    digest = hashlib.sha256()
    for key in sorted(files):
        digest.update(key.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[key].encode("ascii"))
        digest.update(b"\n")
    incomplete = ""
    if unreadable:
        incomplete = ", and {} path(s) could not be read ({}), so this digest is over " \
            "less than the whole tree".format(len(unreadable), _named_few(list(unreadable)))
    return "{}, content {} over {} file(s){}".format(
        _git_head(root), digest.hexdigest()[:12], len(files), incomplete
    )


def plugin_manifest(root):
    """``(doc, reason)``. Exactly one is None.

    ``reason`` distinguishes *absent* from *unreadable* from *unparseable*, because
    they are three different answers: the first says this tree is not a plugin
    checkout, and the other two say nothing was established either way.
    """
    manifest = Path(root) / ".claude-plugin" / "plugin.json"
    try:
        raw = manifest.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "it has no .claude-plugin/plugin.json"
    except (OSError, UnicodeDecodeError) as exc:
        return None, "its .claude-plugin/plugin.json could not be read ({})".format(
            exc.__class__.__name__
        )
    try:
        doc = json.loads(raw)
    except ValueError:
        return None, "its .claude-plugin/plugin.json would not parse"
    if not isinstance(doc, dict) or not doc.get("name"):
        return None, "its .claude-plugin/plugin.json names no plugin"
    return doc, None


def plugin_attestation(flag, env_value):
    """``(root, source)``: what this invocation said about which copy it resolved.

    A command's text carries ``${CLAUDE_PLUGIN_ROOT}``, so the root a command
    resolved from is a fact the invocation itself holds. A script run any other way
    holds no such fact, and ``(None, None)`` is that third state rather than a
    default.
    """
    if flag:
        return Path(os.path.expanduser(str(flag))), "--plugin-root"
    if env_value:
        return Path(os.path.expanduser(str(env_value))), "CLAUDE_PLUGIN_ROOT"
    return None, None


def _named_few(names, limit=3):
    shown = ", ".join(names[:limit])
    if len(names) > limit:
        shown += ", and {} more".format(len(names) - limit)
    return shown


def _version_sentence(ours, theirs):
    if ours == theirs:
        return "Both manifests declare version {}, which is why comparing versions " \
            "cannot see this.".format(_one_line(ours, limit=40))
    return "The manifests declare {} and {}.".format(
        _one_line(ours, limit=40), _one_line(theirs, limit=40)
    )


def plugin_provenance(script_root, project_dir, attested=None, attested_source=None):
    """``[(level, message)]`` -- two lines, and neither may be silent.

    Returns rather than prints, so every state is testable.
    """
    script_root = Path(script_root)
    lines = []

    if attested is None:
        lines.append(
            (
                "WARN",
                "plugin copy scope: not established -- neither --plugin-root nor "
                "CLAUDE_PLUGIN_ROOT named a root, so the copy reported below is "
                "inferred from this script's own location ({}) and nothing "
                "establishes which copy the harness resolves a command from. "
                "{}".format(script_root, SESSION_CAVEAT),
            )
        )
    elif same_directory(attested, script_root):
        lines.append(
            (
                "OK",
                "plugin copy scope: {} named {}, and that is the tree doctor.py ran "
                "from. {}".format(attested_source, script_root, SESSION_CAVEAT),
            )
        )
    else:
        lines.append(
            (
                "WARN",
                "plugin copy scope: {} names {}, but doctor.py ran from {}. The tree "
                "reported below is the one that ran; nothing establishes that the "
                "harness resolves a command from it. {}".format(
                    attested_source, Path(attested), script_root, SESSION_CAVEAT
                ),
            )
        )

    ours, our_reason = plugin_manifest(script_root)
    theirs, their_reason = plugin_manifest(project_dir)

    files, unreadable = plugin_tree_digest(script_root)
    identity = _tree_identity(script_root, files, unreadable)

    if theirs is None and their_reason == "it has no .claude-plugin/plugin.json":
        lines.append(
            (
                "OK",
                "plugin copy: doctor.py answered from {} ({}); the repo being "
                "diagnosed is not a checkout of this plugin -- {} -- so there was "
                "nothing to compare it against.".format(script_root, identity, their_reason),
            )
        )
        return lines
    if theirs is None:
        lines.append(
            (
                "WARN",
                "plugin copy: whether the repo being diagnosed is a checkout of this "
                "plugin could not be determined -- {} -- so nothing was compared. "
                "doctor.py answered from {} ({}).".format(their_reason, script_root, identity),
            )
        )
        return lines
    if ours is None:
        lines.append(
            (
                "WARN",
                "plugin copy: whether the repo being diagnosed is a checkout of this "
                "plugin could not be determined -- the copy that answered ({}) is "
                "itself unreadable as a plugin: {} -- so nothing was compared.".format(
                    script_root, our_reason
                ),
            )
        )
        return lines

    our_name = _one_line(ours.get("name"), limit=60)
    their_name = _one_line(theirs.get("name"), limit=60)
    if our_name != their_name:
        lines.append(
            (
                "OK",
                "plugin copy: doctor.py answered from {} ({}); the repo being "
                "diagnosed is not a checkout of this plugin -- it declares plugin "
                "'{}' and this one is '{}' -- so there was nothing to compare it "
                "against.".format(script_root, identity, their_name, our_name),
            )
        )
        return lines

    if same_directory(script_root, project_dir):
        lines.append(
            (
                "OK",
                "plugin copy: doctor.py answered from the checkout being diagnosed "
                "({}, {}), so there is no installed-copy/clone split to report "
                "here.".format(script_root, identity),
            )
        )
        return lines

    their_files, their_unreadable = plugin_tree_digest(project_dir)
    their_identity = _tree_identity(project_dir, their_files, their_unreadable)
    every = set(files) | set(their_files)
    differing = sorted(key for key in every if files.get(key) != their_files.get(key))
    blocked = unreadable + their_unreadable
    version = _version_sentence(ours.get("version"), theirs.get("version"))
    incomplete = ""
    if blocked:
        incomplete = " {} path(s) could not be read ({}), so this did not compare the " \
            "whole tree.".format(len(blocked), _named_few(blocked))

    if differing:
        lines.append(
            (
                "WARN",
                "plugin copy: SKEW -- the copy that answered ({}, {}) and the "
                "checkout being diagnosed ({}, {}) differ in {} of {} compared "
                "file(s): {}. {}{}".format(
                    script_root,
                    identity,
                    project_dir,
                    their_identity,
                    len(differing),
                    len(every),
                    _named_few(differing),
                    version,
                    incomplete,
                ),
            )
        )
        return lines

    if blocked:
        lines.append(
            (
                "WARN",
                "plugin copy: could not be answered -- {} path(s) could not be read "
                "({}), so the comparison did not cover the whole tree; the {} file(s) "
                "it did compare match. The copy that answered is {} ({}); the "
                "checkout being diagnosed is {} ({}).".format(
                    len(blocked),
                    _named_few(blocked),
                    len(every),
                    script_root,
                    identity,
                    project_dir,
                    their_identity,
                ),
            )
        )
        return lines

    lines.append(
        (
            "OK",
            "plugin copy: the copy that answered ({}, {}) and the checkout being "
            "diagnosed ({}, {}) are identical over {} compared file(s), line endings "
            "normalised.".format(
                script_root, identity, project_dir, their_identity, len(every)
            ),
        )
    )
    return lines


def check_plugin_copy(project_dir, script_root=None, attested=None, attested_source=None):
    for level, message in plugin_provenance(
        script_root or PLUGIN_ROOT,
        project_dir,
        attested=attested,
        attested_source=attested_source,
    ):
        report(level, message)


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a bad flag. This one refuses to, because a mistyped argument
    must still produce a report -- exit 0 and one VERDICT line is the contract, and a
    usage message on stderr with neither is the diagnostic failing to run.
    """

    def error(self, message):  # pragma: no cover - exercised through parse_args
        raise ValueError(message)


def parse_args(argv):
    """``(root, plugin_root, problems)``. Never exits and never raises."""
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
    parser.add_argument(
        "--plugin-root",
        default=None,
        help="the plugin root this invocation resolved from, which only the "
        "invocation knows -- a command's text carries ${CLAUDE_PLUGIN_ROOT}. Absent, "
        "the `plugin copy scope` line reports that nothing established which copy "
        "answered, rather than assuming this script's own location speaks for the "
        "harness.",
    )
    try:
        parsed = parser.parse_args(list(argv))
        return parsed.root, parsed.plugin_root, []
    except ValueError as exc:
        return None, None, [
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
    root, plugin_root, arg_problems = parse_args([] if argv is None else argv)
    project_dir, resolution = resolve_project_dir(
        root, os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()
    )

    report("OK", "oss plugin version {}".format(plugin_version()))
    for problem in arg_problems:
        report("FAIL", problem)
    for state, message in resolution:
        report(state, message)

    # Immediately under the version line, because the version line is the thing it
    # exists to stop anybody trusting on its own: two copies a whole release cycle
    # apart declare the same number (#262), and the one that answered a command is
    # not necessarily the one that is installed (#248).
    attested, attested_source = plugin_attestation(
        plugin_root, os.environ.get("CLAUDE_PLUGIN_ROOT")
    )
    check_plugin_copy(
        project_dir, attested=attested, attested_source=attested_source
    )

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
    # A fact about the plugin, not about the project, so it needs no config and runs
    # even when everything else was unmeasurable.
    check_agent_dispatch()

    # Declared dependencies install automatically; they do not configure themselves,
    # and the unconfigured state is the one that still appears to work.
    check_memory(project_dir)
    check_jit_rules(project_dir)
    # Rules indexed is not rules read. The check above answers "will the matcher find
    # these rows"; this one answers "does anything look in this directory at all", and
    # #119 is the bill for never having asked it.
    check_jit_layer_readers(project_dir)
    # The merge permission is settled here or it is settled at the merge step,
    # with the whole review already spent.
    check_merge_permission(project_dir)
    # Needs no config: the channel is supertool's file and this process's
    # environment, so it answers on a repo that has never run /oss:setup.
    check_watch_channel(project_dir)
    # The channel and the board are two questions, and answering only the first is
    # how a repo with a route to nowhere read as healthy (#191). Also needs no
    # config: both live in supertool's file.
    check_radar_publish(project_dir)
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
