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
* **The tree being diagnosed does not get to write the diagnosis.** Every finding is
  emitted by ``report()`` or ``report_with_remedy()``, and both reduce foreign text to
  one printable ASCII line through ``_one_line()``. The files this script reads --
  ``.oss.json``, ``.claude/settings.json`` -- are tracked in a managed repo and a
  contributor writes them; unflattened, an entry in one forged the VERDICT line above.

  **Exactly one fragment is exempt from the ASCII fold, and nothing else is** (#376):
  the ``remedy`` argument of ``report_with_remedy()``, a paste-ready command built from
  ``PLUGIN_ROOT`` -- this script's own resolved install location, not text the audited
  tree chose. Folding it would put a ``?`` (a shell glob) inside a command the reader is
  meant to paste and run, which is #344. It still gets the newline and control-character
  collapse of ``_one_line_keep_unicode()``, so it can neither forge a line of this
  script's output nor rewrite what a terminal already printed, and ``_safe_print()``
  keeps the "exit 0 always" contract when the stream cannot encode it.

  This paragraph and the set of functions that call ``_emit()`` are held to each other by
  ``tests/test_doctor_fold_contract_376.py``: a third emitter, or a contract that goes
  back to stating the fold unconditionally, fails there.

Python 3.9 compatible.
"""

import argparse
import ctypes
import difflib
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent

sys.path.insert(0, str(SCRIPT_DIR))

# #497: five `check_*` functions moved out of this file into their own modules
# (`scripts/doctor_check_*.py`), each reaching this module's shared names through
# `import doctor` rather than `from doctor import name` -- so a monkeypatch on
# `doctor.<name>` from a test still reaches code that used to be inline here.
# That only resolves correctly when THIS module is what "doctor" names in
# `sys.modules`. When this file runs as the script entry point its own module
# name is `__main__`, not `doctor`, so without this alias each moved module's
# `import doctor` would reenter this very file under `sys.modules["doctor"]`
# while it is still mid-import. Observed (by disabling this alias and running
# the script): with `import doctor` placed before each module's own `def
# check_X`, that reentry raises `ImportError: cannot import name 'check_X'`
# immediately and doctor.py exits 1 -- loud, not the silent FINDINGS-undercount
# a two-independent-copies story would suggest, though a future reordering of a
# moved module's own imports could still produce that quieter failure instead.
# `tests/test_doctor_check_relocation_497.py` runs this file as a subprocess to
# hold this down either way; no other test exercises `__main__`.
if __name__ == "__main__":
    sys.modules.setdefault("doctor", sys.modules[__name__])

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
    import plugin_update
except ImportError:  # pragma: no cover - the module sits beside this file
    plugin_update = None

try:
    import oss_state
except ImportError:  # pragma: no cover - the module sits beside this file
    oss_state = None

try:
    import report_schema
except ImportError:  # pragma: no cover - the module sits beside this file
    report_schema = None

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


def _one_line_keep_unicode(text, limit=200):
    """Text THIS SCRIPT composed itself, reduced to one line, with the
    newline/control-character defence `_one_line` exists for but WITHOUT its
    ASCII-fold (#344).

    `_one_line`'s docstring scopes the fold to "text from outside this
    script" -- settings entries, config values, subprocess stderr, things
    the audited tree chooses and could use to forge this script's own
    output. A remedy command built from `PLUGIN_ROOT` (this script's own
    resolved install location) is not that: it is not foreign text, so
    folding it is not a security control, it is a `?` -- a shell glob --
    sitting inside a command the reader is meant to paste and run. On a
    non-ASCII install path that either fails to match or matches a
    directory the caller never named.

    The newline-collapse (`" ".join(text.split())`) is kept unconditionally:
    a newline forging a new line of this script's own output is a real
    hazard regardless of whose text it is. Only the character-by-character
    ASCII restriction is dropped; everything below `chr(32)` and `chr(127)`
    (DEL) is still folded to `?`, so a control character cannot rewrite what
    a terminal has already printed either.
    """
    flat = " ".join(str(text).split())
    safe = "".join(ch if (ord(ch) >= 32 and ch != "\x7f") else "?" for ch in flat)
    return safe[:limit]


def _safe_print(line):
    """Print `line`. Never raises, regardless of what the stream can encode.

    `_one_line` keeps only printable ASCII, so its output is always encodable
    by any stream `print()` reaches. `_one_line_keep_unicode` (#344)
    deliberately does not make that promise -- it exists precisely to let
    genuine non-ASCII text through -- so a caller can hand this a codepoint
    the ACTUAL stdout stream cannot represent: a lone surrogate (what
    `surrogateescape` produces decoding an undecodable filename byte,
    ordinary for a non-UTF-8 path on Linux) or an otherwise valid character
    outside a narrow console codepage (the Windows cp1252 hazard this repo's
    own CLAUDE.md already names for every OTHER print in this codebase).
    Either would raise `UnicodeEncodeError` out of a bare `print()`, which
    breaks the one contract that matters more than any single check:
    `exit 0 always, one VERDICT line`.

    Three levels, each a net under the one above, because a self-review
    round on #344 found the first version's net had a hole of its own:
    `sys.stdout.encoding` naming a codec Python's registry does not
    recognise (a mocked or wrapped stream) raised `LookupError` out of the
    `.encode(encoding, ...)` fallback itself, uncaught. The final level
    encodes as `ascii`, which is always a registered codec, so it cannot
    raise `LookupError` and its own `print()` cannot raise
    `UnicodeEncodeError` either -- there is nothing below `ascii` to fall
    back to further, so this is where the defence stops.
    """
    try:
        print(line)
        return
    except UnicodeEncodeError:
        pass
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        safe = line.encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")
    except LookupError:
        safe = line
    try:
        print(safe)
        return
    except UnicodeEncodeError:
        pass
    print(line.encode("ascii", errors="backslashreplace").decode("ascii"))


def _emit(state, flat):
    FINDINGS.append((state, flat))
    _safe_print("{} {}".format(state, flat))


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
    _emit(state, flat)


def report_with_remedy(state, prose, remedy):
    """Like `report`, for the small set of findings that embed a paste-ready
    command naming THIS install's own resolved path (#344).

    `prose` is folded exactly like `report`'s `message` -- it still fully
    ASCII-folds, because a self-review round found the first version of this
    function folded the WHOLE composed message through
    `_one_line_keep_unicode`, so text embedded in `prose` at the call sites
    (`resolved`/`detail`/`version_clause` -- `os.path.realpath()` of
    whatever PATH resolves `oss-workspace` to, i.e. local filesystem state
    this script did NOT compose) escaped the fold it should still get. Only
    `remedy` -- built from `PLUGIN_ROOT`/`plugin_root`, this script's own
    resolved install location, which is what `_one_line_keep_unicode`'s own
    docstring scopes the exemption to -- skips the ASCII fold.
    """
    folded = _one_line(prose, limit=REPORT_LIMIT + 1)
    safe_remedy = _one_line_keep_unicode(remedy, limit=REPORT_LIMIT + 1) if remedy else ""
    flat = "{} {}".format(folded, safe_remedy).strip() if safe_remedy else folded
    if len(flat) > REPORT_LIMIT:
        flat = flat[: REPORT_LIMIT - 4] + " ..."
    _emit(state, flat)


def _manifest_version(plugin_root):
    """The version a plugin manifest under `plugin_root` declares, in three states.

    Returns ``(state, version)``:

    * ``("read", "0.6.0")`` -- the manifest parsed and carries a version string.
    * ``("no-version-field", None)`` -- it parsed and does not.
    * ``("unreadable", None)`` -- absent, unparseable, or not a JSON object.

    **The two failure states return no version, rather than a word standing where a
    version goes.** `plugin_version()` below folds them into `"unknown"` and
    `"unreadable"`, which is right for the one line at the top of this script's
    output -- "oss plugin version unreadable" is a true sentence about the install
    the reader is running. It is wrong anywhere the value is formatted as
    `version {}` beside a measurement, which is #350: a receipt naming a version
    nobody read is the same defect as a receipt naming a version read from the
    wrong tree.

    `plugin_root` is a parameter because `oss_workspace_launcher_state` is handed
    one and its content comparison already honours it (#329). Its version label did
    not, so the WARN described one install beside a comparison performed against
    another -- and the assertion that should have caught it was itself pinned to
    whatever version this repository happened to be at, so it only fired on the
    release commit that bumped the manifest.

    A non-object JSON body is `unreadable` rather than a crash: `[]` reached
    `.get` and raised `AttributeError` out of `plugin_version()`, whose whole
    contract is that its line prints when everything else has failed.
    """
    manifest = Path(plugin_root) / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unreadable", None
    if not isinstance(data, dict):
        return "unreadable", None
    version = data.get("version")
    if not isinstance(version, str) or not version:
        return "no-version-field", None
    return "read", version


def plugin_version():
    """The RUNNING install's version, as a string that always prints.

    Deliberately still global and still argument-free. Surveyed for #350: at the
    time, its only other caller was `main()`'s `oss plugin version {}` header,
    which is a claim about the install the reader invoked and would be wrong if it
    took a root from anywhere else. The parameterised question got its own
    function above instead of a new keyword here, so no existing caller's meaning
    moved.

    `main()`'s header now calls `plugin_identity(PLUGIN_ROOT)` instead (#418),
    which wraps this same version answer with a content digest -- the version
    string alone stays at the last RELEASED number for a whole cycle, so it
    cannot tell a tag from a same-numbered cache dir unpacked mid-cycle apart.
    This function's own behaviour is unchanged, but that header was its one
    production caller: it has none left in `scripts/`. `plugin_identity` builds
    its label from `_manifest_version` directly rather than calling this
    function, so nothing routes through it any more -- only the test suite does.
    """
    state, version = _manifest_version(PLUGIN_ROOT)
    if state == "read":
        return version
    return "unknown" if state == "no-version-field" else "unreadable"


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


def _os_error_detail(exc):
    """One clause naming what stopped a stat, built from the exception in hand.

    **The exception, and nothing else.** Asking the filesystem a second question to
    explain why the first one failed is the trap `release_delta.py` was bitten by:
    `Path.exists()` swallows a short list of errnos and re-raises the rest, so the
    call added to tell absence from unreadability is the call that kills a diagnostic
    contracted to exit 0. `os.stat` sets `filename` and `strerror` already.
    """
    reason = exc.strerror or exc.__class__.__name__
    if exc.filename:
        return "{} could not be examined ({})".format(exc.filename, reason)
    return "one of the two paths could not be examined ({})".format(reason)


def compare_directories(left, right):
    """Do two spellings name one directory? ``(True | False | None, reason)``.

    `os.getcwd()` is resolved by the kernel and a path handed in on the command line is
    not, so on macOS `/tmp` and `/private/tmp` are the same directory under two names --
    and `Path(".") != Path("/abs")` however identical the two are. So the question is
    asked of the filesystem, by device and inode, exactly as `_same_file` asks it of a
    file and as supertool's own `hooks/session-start.sh` asks it with ``-ef``.

    **``None`` is "could not tell", and it is a third answer rather than a ``False``**
    -- #309. `os.path.samefile` raises when either path is absent, and absence is an
    ordinary state at two of this function's four call sites: ``--root`` and
    ``--plugin-root`` are paths somebody typed, and a typo is the common case. The
    version this replaces caught that `OSError` and fell back to comparing
    `os.path.abspath` strings, so two spellings of one directory answered ``False``
    while it did not exist and ``True`` once it did -- a verdict that moves with the
    filesystem's state rather than with the question asked. ``False`` is then rendered
    by every caller as *these are two different trees*, which is an accusation, and the
    callers that printed it were printing it about a tree nobody had looked at.

    **The string comparison is kept for the positive answer only, and that asymmetry is
    the point.** Two equal normalised paths denote one directory by construction,
    existing or not; that answer needs no filesystem behind it and stays ``True``. Two
    *different* normalised paths establish nothing -- `os.path.abspath` does not resolve
    symlinks, and `os.path.realpath` would not have rescued it either: on Windows that
    function is prefix-preserving rather than canonicalising, recording at
    `ntpath.py:683` whether its input already carried the extended-length prefix and
    stripping it from the result at `:713` only when it did not, while `os.readlink`
    returns a reparse point's substitute name, which carries it. Symmetry of function is
    not symmetry of result when the output depends on the form of the input, so the
    negative half is refused rather than guessed.

    Every string fix for that is a list of spellings -- the extended-length prefix, its
    UNC form, 8.3 short names, a substituted drive, a junction, case folding -- and a
    list is wrong the first time Windows adds one. Asking the filesystem has no list in
    it, and saying "could not tell" when it will not answer has no list in it either.

    The reason is the second element and is ``None`` for a decided verdict, so a caller
    cannot print an explanation for an answer that needs none.
    """
    try:
        return os.path.samefile(str(left), str(right)), None
    except OSError as exc:
        detail = _os_error_detail(exc)
    if os.path.abspath(str(left)) == os.path.abspath(str(right)):
        return True, None
    return None, detail


def same_directory(left, right):
    """The verdict from `compare_directories` alone.

    ``None`` is could-not-tell and is **not** ``False``. Callers that only ever act on
    proof of sameness use this; callers with something to say about the third state
    call `compare_directories` and print its reason.
    """
    return compare_directories(left, right)[0]


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

    **Of the four call sites of `compare_directories`, this is the one whose third
    state wants no message of its own** (#309), and that is a decision rather than an
    omission. ``None`` takes the same arm as ``False`` here because the conservative
    arm is the right one for it: widening on an unproven identity is what produced the
    five-level search above, and the caller is already told the clone was not searched.
    It is also the site where the third state is not reachable through the filesystem
    -- the `is_dir()` guard directly above has already made the kernel answer for
    `project_dir`, and `os.getcwd()` raises before this line if the current directory
    has gone. The arm is written as ``is True`` rather than left truthy so that a later
    verdict cannot silently widen; nothing about that needs printing.
    """
    absolute = os.path.abspath(str(Path(project_dir) / oss_config.CONFIG_NAME))
    if not Path(project_dir).is_dir():
        # The widening starts its git query from `.` when the directory the path points
        # into does not exist, so a --root that is not there searched the CALLER's clone
        # and named it in the finding: "Not in the enclosing clone at <somewhere else>
        # either". A sentence about a repository nobody asked about, inside a report
        # about one that does not exist.
        return absolute, False
    if same_directory(project_dir, os.getcwd()) is True:
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


# ENOENT. Apple's own documented reading of `sysctl.proc_translated` is that the
# sysctl being ABSENT means this system has no translation layer at all -- so it is
# the third valid answer to the probe, not a failed probe.
_SYSCTL_ABSENT = 2


def _sysctl(name):
    """One integer sysctl by name, as ``(value, errno)``. Darwin only.

    ``value`` is None when the call did not produce one, and ``errno`` says why:
    the C ``errno`` when the call itself failed, or None when ctypes could not be
    used at all. The two are returned separately because the whole of the Rosetta
    probe below turns on telling "this sysctl does not exist" from "the call
    failed", and a bare None cannot.

    Read in-process through ctypes rather than by spawning ``sysctl``: an emulated
    process is shown the emulated architecture and **so is anything it spawns**, so
    a subprocess helper inherits the very question being asked.
    """
    if platform.system() != "Darwin":
        return None, None
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        value = ctypes.c_int64(0)
        size = ctypes.c_size_t(ctypes.sizeof(value))
        ctypes.set_errno(0)
        rc = libc.sysctlbyname(
            name.encode("ascii"),
            ctypes.byref(value),
            ctypes.byref(size),
            None,
            ctypes.c_size_t(0),
        )
    except Exception:  # pragma: no cover - a libc without this symbol, or no ctypes
        # Deliberately broad: this is a diagnostic, and "exit 0 always, one VERDICT
        # line" outranks any single check. An unusable ctypes returns the unknown
        # state, which the caller renders as a WARN naming what went unprobed.
        return None, None
    if rc != 0:
        return None, ctypes.get_errno()
    # A 4-byte sysctl fills the low half of a zeroed 8-byte little-endian buffer, so
    # the widened read is exact on both architectures macOS runs on.
    return int(value.value), 0


def _sysctl_int(name):
    """The value half of `_sysctl`, for callers that do not need to tell the two
    failure causes apart.

    "Do not need to" is a claim about the CALLER, and #400 is what happens when it is
    wrong: `cpu_topology` read this for `hw.nperflevels`, where an absent sysctl is a
    real answer, and turned it into a WARN saying the probe had not answered. Before
    reaching for this, ask what the caller would print for an absent sysctl. If that
    differs from what it would print for a failed call, it wants `_sysctl` and the
    `_SYSCTL_ABSENT` comparison.
    """
    value, _ = _sysctl(name)
    return value


def translation_state(system=None):
    """Is THIS process running under binary translation? Three states (#367).

    Returns ``(state, host_machine, reason)``:

    * ``("native", "arm64", "")`` -- the process architecture is the host's.
    * ``("translated", "arm64", "")`` -- Rosetta 2, or its equivalent.
    * ``("unknown", None, "<why>")`` -- a probe exists here, ran, and did not answer.
    * ``("not-probed", None, "<why>")`` -- no probe exists for this platform at all,
      so nothing was attempted and nothing will be until somebody writes one.

    **The last two were one state until CI answered, and separating them is #367's
    real lesson.** Folded together they were rendered WARN, which made ``VERDICT:
    ok`` unreachable on every Linux and Windows leg forever. That does not add a
    finding, it removes a signal: a verdict line that always reads ``usable with
    gaps`` can no longer carry a real WARN, so every genuine gap on those platforms
    is masked by a permanent one. This repository's own defect class, pointed at the
    verdict line instead of at a check.

    So `not-probed` is reported at OK with the gap named ON the line, which is the
    shape `agent_dispatch` already uses in this file for a sub-question that is
    unobservable in principle (`NOT_OBSERVABLE_HERE`). `unknown` keeps the WARN,
    because a probe that exists and did not answer has a cause worth chasing. What
    neither of them does is say `native`: an emulated interpreter on either platform
    reports the emulated architecture, so the line names what went unprobed and is
    pinned by a test never to contain the word.

    **`platform.machine()` cannot answer this and neither can `uname -m`**: an
    emulated process is shown the *emulated* architecture, so a comparison between
    the two is a comparison of one number with itself. The probe has to be one the
    translation layer answers truthfully about the caller, which on Darwin is
    `sysctl.proc_translated`.

    No probe is implemented for Linux (qemu-user binfmt) or Windows-on-ARM, so both
    return `unknown` **rather than `native`**. Folding them into `native` would be
    this repository's own defect class: an emulated interpreter on either platform
    reports the emulated architecture, and a line reading "native" would be a
    confident wrong answer where a gap belongs.
    """
    system = platform.system() if system is None else system
    if system != "Darwin":
        return (
            "not-probed",
            None,
            "no translation probe is implemented for {} -- the Darwin probe is the "
            "sysctl.proc_translated flag, and qemu-user (Linux) and Windows-on-ARM "
            "expose no equivalent this script reads".format(_one_line(system, limit=40)),
        )
    translated, errno = _sysctl("sysctl.proc_translated")
    if translated is None and errno != _SYSCTL_ABSENT:
        return (
            "unknown",
            None,
            "sysctl.proc_translated could not be read (errno {}), so this Darwin "
            "install's translation state was not established".format(errno),
        )
    if translated is None:
        translated = 0
    # The host architecture gets the same three-state care as the flag above, and
    # for the same reason: `hw.optional.arm64` returns nothing both when the machine
    # genuinely is not arm64 and when the call failed, so folding the second into the
    # first prints "host architecture x86_64" about a host nobody read. `host` is
    # None when it was not established, and the renderer says so rather than naming
    # an architecture in a remedy the reader is meant to act on.
    arm64_flag, arm64_errno = _sysctl("hw.optional.arm64")
    if arm64_flag is None and arm64_errno != _SYSCTL_ABSENT:
        host = None
    else:
        host = "arm64" if arm64_flag else "x86_64"
    return ("translated" if translated else "native", host, "")


def interpreter_architecture(machine=None, system=None, translation=None):
    """The architecture line, as ``[(level, message)]`` so the states are testable.

    WARN on translated, because it is the finding: measured on the machine #367 was
    filed from, roughly 3x on interpreter startup and 3.4x on the CPU cost of a
    subprocess spawn. WARN again on `unknown` -- a probe that exists here and did
    not answer -- because a check that could not look must not render as a check
    that looked and found nothing.

    `not-probed` is OK, and the argument for the difference is in
    `translation_state`'s docstring: a permanent unclearable WARN on two of the
    three platforms costs the verdict line its ability to discriminate, which is a
    bigger absence than the one it reports. In both states the line deliberately
    never contains the word "native", and a test pins that.
    """
    machine = platform.machine() if machine is None else machine
    system = platform.system() if system is None else system
    if translation is None:
        translation = translation_state(system)
    state, host, reason = translation
    machine = _one_line(machine, limit=40) or "unrecognised"
    version = "python {}.{}.{}".format(*sys.version_info[:3])
    host_clause = (
        "host architecture {}".format(host)
        if host
        else "the host architecture could not be read from hw.optional.arm64"
    )
    if state == "translated":
        return [
            (
                "WARN",
                "interpreter architecture: {}, {} build running under binary "
                "translation ({}) -- measured ~3x on interpreter startup and ~3.4x on "
                "the CPU cost of a subprocess spawn (#367), and this loop is "
                "subprocess-shaped. A native {}python3 removes the tax.".format(
                    version, machine, host_clause, host + " " if host else ""
                ),
            )
        ]
    if state == "native":
        return [
            (
                "OK",
                "interpreter architecture: {}, {} build running natively ({})".format(
                    version, machine, host_clause
                ),
            )
        ]
    return [
        (
            "WARN" if state == "unknown" else "OK",
            "interpreter architecture: {}, reporting itself as a {} build; whether it "
            "is running under binary translation was NOT probed -- {}. An emulated "
            "interpreter reports "
            "the emulated architecture, so the name above is not evidence either "
            "way.".format(version, machine, _one_line(reason, limit=400)),
        )
    ]


def cpu_topology(system=None):
    """``(logical, performance, efficiency, split_state)``, None where nothing said.

    macOS exposes the split through `hw.nperflevels` and `hw.perflevelN.logicalcpu`,
    level 0 being the fastest. Nothing else this script runs on exposes it in a shape
    worth guessing at, so the two halves come back None and the caller says the split
    is absent rather than omitting the clause -- an omitted clause reads exactly like
    a machine whose split nobody looked for.

    Only a two-level machine reports a split. A hypothetical third performance level
    would make `performance + efficiency` a partial count presented as a whole one.

    `split_state` is `"split"`, `"none"` or `"unknown"`, and the third exists because
    `hw.nperflevels` returning nothing means *either* "this machine has one
    performance level" *or* "the probe failed" -- and the first version of this
    printed "this platform reports no performance/efficiency core split" for both,
    which tells the reader the count below is sizing against uniform cores when
    nobody established that.

    Those two are told apart by the **errno**, not by the value (#400): `_SYSCTL_ABSENT`
    means the sysctl does not exist on this machine, which is the first case and
    reports `"none"`. Anything else is the second and reports `"unknown"`. The value
    alone cannot distinguish them, which is why this reads `_sysctl` rather than
    `_sysctl_int` -- for a whole release it read the latter and every machine without
    the sysctl got an unclearable WARN whose sentence said the probe had not answered.
    """
    system = platform.system() if system is None else system
    logical = os.cpu_count()
    if system != "Darwin":
        # Not `unknown`: no probe was attempted, because none exists here, and the
        # renderer's non-Darwin sentence says exactly that. `unknown` is reserved for
        # a probe that ran on a platform that has one and did not answer.
        return (logical, None, None, "none")
    darwin_logical = _sysctl_int("hw.logicalcpu")
    if darwin_logical:
        logical = darwin_logical
    # `_sysctl`, not `_sysctl_int`, and #400 is the whole reason: this caller is
    # exactly the one that has to tell "the sysctl does not exist" from "the probe
    # failed", which is the distinction `_sysctl_int` documents itself as discarding.
    # An ABSENT `hw.nperflevels` is a machine with one performance level -- the
    # `"none"` arm below, at OK -- and calling it `unknown` prints a WARN saying the
    # probe did not answer, which is false and which no remedy clears. A verdict line
    # permanently reading `usable with gaps` cannot carry a real warning any more, the
    # same argument `translation_state()` makes two screens up.
    levels, levels_errno = _sysctl("hw.nperflevels")
    if levels is None and levels_errno == _SYSCTL_ABSENT:
        return (logical, None, None, "none")
    if levels is None:
        # Every other errno, and the None that means ctypes was unusable, keep the
        # WARN: a probe that exists and did not answer has a cause worth chasing.
        # Folding those into `"none"` is the opposite defect and would claim uniform
        # cores on a machine nobody measured.
        return (logical, None, None, "unknown")
    if levels != 2:
        return (logical, None, None, "none")
    perf = _sysctl_int("hw.perflevel0.logicalcpu")
    eff = _sysctl_int("hw.perflevel1.logicalcpu")
    if perf is None or eff is None:
        return (logical, None, None, "unknown")
    return (logical, perf, eff, "split")


def xdist_auto_workers(env=None, physical=None, affinity=None, logical=None):
    """What ``pytest -n auto`` would ask this machine for. ``(count, source, note)``.

    A transcription of `xdist.plugin.pytest_xdist_auto_num_workers`, in its order:
    `PYTEST_XDIST_AUTO_NUM_WORKERS` first -- it is read **before** anything is
    counted, which is the cap #367 wants stated because you have to know it is
    there -- then psutil's **physical** core count (`-n auto` passes
    `logical=False`, so on an SMT machine this is half `os.cpu_count()` and a doctor
    reporting the logical count would double the number on exactly the machines
    where the mistake is expensive), then `os.sched_getaffinity(0)`, then
    `os.cpu_count()`.

    `count` is None with source `"unknown"` when nothing answered -- never 0 or 1. A
    number invented here would be a confident wrong answer about the one thing the
    reader came for.

    Being a transcription it is a claim about a dependency and can go stale if xdist
    changes; `note` carries the case where the two visibly disagree, a variable that
    is set and is not a number, which xdist warns about and ignores.
    """
    env = os.environ if env is None else env
    note = ""
    raw = env.get("PYTEST_XDIST_AUTO_NUM_WORKERS")
    if raw:
        try:
            return (
                int(raw),
                "PYTEST_XDIST_AUTO_NUM_WORKERS, which xdist reads before it counts "
                "anything",
                "",
            )
        except (TypeError, ValueError):
            note = (
                "PYTEST_XDIST_AUTO_NUM_WORKERS is set to '{}', which is not a number: "
                "xdist warns and ignores it, so the cap is NOT in effect".format(
                    _one_line(raw, limit=60)
                )
            )
    for value, source in (
        (physical, "psutil.cpu_count(logical=False)"),
        (affinity, "os.sched_getaffinity(0)"),
        (logical, "os.cpu_count()"),
    ):
        if value:
            return (value, source, note)
    return (None, "unknown", note)


def _worker_inputs():
    """``(physical, affinity, logical)`` as xdist would find them, None where absent.

    psutil is imported under a bare `except` because it is not declared anywhere in
    this repository -- it is present or absent in whatever environment an agent runs
    a suite in, and a diagnostic that raised on its absence would break the one
    contract above every check here.
    """
    try:
        import psutil

        physical = psutil.cpu_count(logical=False) or psutil.cpu_count()
    except Exception:  # pragma: no cover - depends on the environment, not the code
        physical = None
    affinity = None
    getaffinity = getattr(os, "sched_getaffinity", None)
    if getaffinity is not None:
        try:
            affinity = len(getaffinity(0))
        except OSError:  # pragma: no cover - the exception in hand is the answer
            affinity = None
    return (physical, affinity, os.cpu_count())


def _xdist_installed():
    """Is pytest-xdist importable in THIS interpreter? Never raises."""
    try:
        return importlib.util.find_spec("xdist") is not None
    except Exception:  # pragma: no cover - a broken meta path finder
        return False


def worker_sizing(topology, workers, xdist_installed):
    """The two topology/sizing lines, as ``[(level, message)]``.

    Pure: everything it needs is passed in, so all three states of both inputs are
    assertable on any platform. The probing lives in `check_interpreter_environment`.
    """
    logical, perf, eff, split = topology
    count, source, note = workers
    lines = []
    if logical is None:
        lines.append(
            (
                "WARN",
                "cpu topology: the logical core count could not be determined here, so "
                "what a worker pool sized against this machine would ask for is "
                "unknown",
            )
        )
    elif split == "split":
        lines.append(
            (
                "OK",
                "cpu topology: {} logical core(s) -- {} performance + {} "
                "efficiency".format(logical, perf, eff),
            )
        )
    elif split == "unknown":
        lines.append(
            (
                "WARN",
                "cpu topology: {} logical core(s); whether they are split into "
                "performance and efficiency cores could NOT be determined -- the "
                "hw.nperflevels probe did not answer, so the count below may be "
                "sizing against cores of two different speeds without saying "
                "so".format(logical),
            )
        )
    else:
        lines.append(
            (
                "OK",
                "cpu topology: {} logical core(s); this platform reports no "
                "performance/efficiency core split, so the number below sizes against "
                "all of them".format(logical),
            )
        )

    if count is None:
        lines.append(
            (
                "WARN",
                "worker sizing: what `pytest -n auto` would request here could not be "
                "determined -- no core count answered, so the cap that matters when "
                "several agents each size against the whole machine cannot be "
                "reported either{}".format(". " + note if note else ""),
            )
        )
        return lines

    clause = ""
    if perf is not None and count > perf:
        clause = (
            " -- more than the {} performance core(s), and concurrent agents each "
            "size against the whole machine without seeing each other".format(perf)
        )
    cap = ""
    if not note and "PYTEST_XDIST_AUTO_NUM_WORKERS" not in source:
        cap = (
            "; PYTEST_XDIST_AUTO_NUM_WORKERS caps it and is read before any core is "
            "counted"
        )
    absent = ""
    if not xdist_installed:
        absent = (
            "; pytest-xdist is not installed in THIS interpreter, so nothing here "
            "consumes that number"
        )
    lines.append(
        (
            "OK",
            "worker sizing: `pytest -n auto` would request {} worker(s), from {}{}{}{}"
            "{}".format(
                count, source, clause, cap, absent, ". " + note if note else ""
            ),
        )
    )
    return lines


def check_interpreter_environment():
    """#367. Two facts about the environment this process runs in, both of which
    took a morning to find once and take one line to state.
    """
    for level, message in interpreter_architecture():
        report(level, message)
    physical, affinity, logical = _worker_inputs()
    for level, message in worker_sizing(
        cpu_topology(),
        xdist_auto_workers(None, physical, affinity, logical),
        _xdist_installed(),
    ):
        report(level, message)


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


# --- the entry point every brief names, which is not the binary on PATH (#285) ------
#
# `check_tool("supertool", ...)` above answers *is it on PATH*. Every developer brief
# this plugin issues says to call `./supertool`, and this repo's rule layer BLOCKS
# Read/Edit/Write/Glob/Grep with a message naming the op that replaces each -- so the
# entry point is mandatory. `scripts/scaffold.py` also writes `/supertool` into a
# managed repo's `.gitignore`, correctly, because committing it would bake one
# developer's absolute path into every other clone. Mandatory, and absent from every
# fresh clone by design: two different questions rendering as one OK line.
#
# **What creates it is supertool's own `hooks/session-start.sh`**, read rather than
# assumed, and it already handles every case right -- it links when nothing is there,
# leaves a stranger untouched, and refuses to link at all inside a supertool checkout.
# Nothing here is a defect in that hook. The gap is that the hook fires on a SESSION's
# cwd, so a clone nobody has opened a session in, and every worktree an agent cuts
# mid-session, has none -- and no diagnostic said so.
SUPERTOOL_ENTRY = "supertool"

#: The file the hook links to, and the file a supertool checkout carries at its own
#: root. Both spellings are the same name on purpose; which one is meant is decided by
#: what else is beside it.
SUPERTOOL_CORE = "supertool.py"


def _same_file(left, right):
    """Do these two names denote the same file? ``True`` / ``False`` / ``None``.

    ``None`` is "could not tell", and it is a separate answer rather than a ``False``,
    because ``False`` here is an accusation: the caller turns it into "your ./supertool
    points somewhere it should not".

    **Identity, not string equality, and this is a transcription rather than a
    preference.** supertool's own `hooks/session-start.sh` decides the same question
    with `[ "$d/supertool.py" -ef "$BIN" ]`, and its comment says why -- ``-ef``
    compares device+inode through symlinks. `os.path.samefile` is that test.

    The string comparison this replaces failed two Windows legs of #285's first
    version, and the mechanism is worth writing down because "normalise both sides"
    does not fix it. Both sides already went through the *same* function,
    `os.path.realpath`. On Windows that function is **prefix-preserving rather than
    canonicalising**: `ntpath.py:683` records `had_prefix` as whether the path already
    began with the extended-length prefix, and `:713` strips that prefix from the
    result only when `had_prefix` was false. `os.readlink` returns a reparse point's
    substitute name, which carries the prefix, so the side that came through the link
    kept it and the side that did not had it stripped -- one function, both sides, two
    spellings. Symmetry of function is not symmetry of result when the function's
    output depends on the form of its input.

    Every string fix for that is a list of spellings: the extended-length prefix, the
    UNC form of it, 8.3 short names, a substituted drive, a junction, case folding.
    A list is wrong the first time a spelling is added to Windows, which is the same
    shape as a table of error codes and is refused here for the same reason. Asking the
    filesystem which file each name opens has no list in it.

    The residual risk, stated rather than hidden: `st_ino` is not meaningful on every
    remote filesystem, and two files could in principle compare equal there. That
    direction clears a wrong link rather than accusing a right one, and the plugin
    cache is local disk; the string comparison had a failure in the accusing direction
    and it was observed, not hypothesised.
    """
    try:
        return os.path.samefile(left, right)
    except OSError:
        return None


def _safe_is_file(path):
    """``path.is_file()``, classified by the exception in hand rather than
    trusted to pathlib's own swallow (PR #359 -- CI red on 8 of 14 legs:
    Python 3.9/3.10/3.11 on BOTH ubuntu-latest and macos-latest, on the
    exact input #341's fix is about).

    `Path.is_file()` catches `OSError` internally, but `EACCES`/`EPERM` is
    not in its ignored-errno set on at least 3.9, 3.11 and 3.13 (measured
    directly, one command each, on this machine's own installs of those
    three) -- only THIS repository's local 3.14 interpreter swallows it. The
    unguarded `.is_file()` calls this replaces predate this PR entirely; what
    is new is a test that actually exercises them against a real unreadable
    directory (#341's own fixture), which is why they went red on every
    3.9-3.11 CI leg, on both `ubuntu-latest` and `macos-latest`, and stayed
    invisible on this machine's local run. The exact version where the
    swallow widens is deliberately not asserted -- 3.10 and 3.12 were not
    directly measured, and a version this repo does not itself confirm is
    not a fact to assert as one. Relying on a stdlib swallow whose
    ignored-errno set differs by version at all is exactly the trap this
    repo's own CLAUDE.md already names for `Path.exists()` (#76) and for
    `is_dir()`/`rglob()` (#124); `is_file()` is the same shape one call over.
    So the classification is done here, explicitly, on every interpreter
    this repo supports rather than left to whichever one happens to be
    running.
    """
    try:
        return path.is_file()
    except OSError:
        return False


def _safe_is_dir(path):
    """``path.is_dir()``, swallowed to ``False`` the same way `_safe_is_file`
    swallows -- for callers that only ever *filter* a list and have nowhere
    to put a third answer. One bad candidate must not wipe every candidate
    already found: `is_dir()` raising mid-comprehension used to propagate to
    an outer `except OSError` that discarded the whole list, readable
    entries included (#363).
    """
    try:
        return path.is_dir()
    except OSError:
        return False


def _rglob_md(root):
    """Every ``*.md`` file under ``root``, recursively -- ``(files, unreadable)``.

    ``Path.rglob`` swallows ``PermissionError`` while it walks and silently
    yields nothing for the subtree it could not enter -- CLAUDE.md's own
    `Path.rglob`/`Path.is_dir` bullet (#124), measured directly for this file
    in `tests/test_swallow_census_383.py`: `sorted((denied).rglob("*.md"))`
    over a mode-000 directory returns ``[]``, never a raise, on every
    interpreter this repo runs. So an `except OSError` wrapped around the
    call -- the shape both call sites this replaces used -- can never fire
    for the case it was written for (#383). There is no argument to `rglob`
    that makes it speak; `os.walk(onerror=...)` is the only shape that does,
    because its callback runs with the exception in hand for whichever
    directory `scandir` could not enter.

    ``unreadable`` holds one message per directory the walk could not enter.
    ``root`` itself not existing, or not being a directory, is reported as
    *nothing found* rather than as unreadable -- `os.walk` would otherwise
    call `onerror` for that case too, and a directory that plainly is not
    there is not the same fact as one this process could not read. A caller
    that needs to tell those two apart at the top level already has a
    dedicated three-state check for it (`_dir_state`); this function answers
    a narrower question, same as `_workflow_scan` does for one directory
    level -- an empty ``unreadable`` here means "as much of the tree as this
    process could enter had no unreadable subtree", not "root is present".
    """
    root_str = os.path.normpath(str(root))
    files = []
    unreadable = []

    def _onerror(exc):
        failed = os.path.normpath(getattr(exc, "filename", None) or root_str)
        if failed == root_str and isinstance(exc, (FileNotFoundError, NotADirectoryError)):
            return
        unreadable.append(_one_line(str(exc)))

    for dirpath, _dirnames, filenames in os.walk(root_str, onerror=_onerror):
        for name in filenames:
            # #469: case-folded deliberately, to match what `Path.rglob("*.md")` --
            # the walk this function replaced -- already did on Windows. This does
            # NOT lean on the filesystem's own case-folding the way an NTFS-vs-APFS
            # question would: `os.walk` returns each entry exactly as stored on every
            # platform, and the fold happens here, once, in Python, before the
            # comparison -- so it is exactly as deterministic on a case-sensitive
            # POSIX filesystem as on a case-insensitive one. A directory holding only
            # `.MD` files must not read as holding none.
            if name.lower().endswith(".md"):
                files.append(Path(dirpath) / name)
    return sorted(files), unreadable


# How far up the tree `_absence_confirmed` will walk. See the sibling constant in
# `scripts/lane_setup.py`: a belt on a walk that already stops at the anchor.
_ANCESTOR_LIMIT = 512


def _absence_confirmed(path):
    """Confirm positively that nothing is at `path`, after `stat` already raised one
    of the two absence exceptions. True / False / None -- and the third is the point.

    True  -- confirmed absent: an ancestor this platform *can* look at was listed
             and the next component down was not in it (or that ancestor is not a
             directory at all, so nothing can be under it).
    False -- the name is right there in its parent's listing and `stat` could not
             reach it. That is the unlookable case wearing absence's clothes.
    None  -- nothing here could confirm either way, so the caller must not claim.

    **#380, and this is the sibling of `lane_setup._absence_confirmed`, not a second
    copy of one classifier.** Reading absence off the exception type is right on
    POSIX, where an over-long name arrives as a plain `OSError` and reaches the
    unreadable arm already. On Windows without `LongPathsEnabled` a path past
    `MAX_PATH` arrives as `FileNotFoundError`, errno 2, `winerror` None -- CLAUDE.md's
    own CI measurement -- which is byte-identical to a name that is merely not there.
    So this repo's own defect class arrives delivered by the OS: a check that could
    not look, printed as a check that looked and found nothing.

    The control is not the plainly-missing same-shape path #380 proposed: on the
    folding platform such a control is *also* past `MAX_PATH` and answers exactly
    what the subject answered, so it would be a guard that can never fire. The
    control here is the subject's own deepest lookable ancestor and that ancestor's
    directory listing -- same shape by construction, since it is the subject's own
    path prefix -- because enumeration answers regardless of how long the resulting
    full path would be, which is the property `stat` loses.

    No errno table and no `MAX_PATH` constant: the limit is conditional on a machine
    setting, and Windows folds several Win32 codes onto `ENOENT`, so neither could
    report the value it would need. The cost is one `stat` per ancestor walked plus
    one `listdir`, paid only on the absence arm -- the seam about to print a verdict.

    `lane_setup.worktree_occupancy` carries the identical body under the identical
    name. They were not lifted into a shared module for the reason #379 argued and
    this change does not revisit: `_dir_state` has four call sites here and its own
    tests. What holds them together is
    `tests/test_unlookable_absence_380.py::test_the_two_classifiers_agree_on_a_folded_name`
    and `tests/test_lane_setup_373.py`, not this paragraph.
    """
    try:
        current = os.path.abspath(os.fspath(path))
    except (OSError, ValueError, TypeError):
        return None
    for _ in range(_ANCESTOR_LIMIT):
        parent = os.path.dirname(current)
        name = os.path.basename(current)
        if not name or parent == current or not parent:
            return None
        try:
            found = os.stat(parent)
        except (FileNotFoundError, NotADirectoryError):
            current = parent
            continue
        except (OSError, ValueError):
            return None
        if not stat.S_ISDIR(found.st_mode):
            return True
        try:
            entries = os.listdir(parent)
        except (OSError, ValueError):
            return None
        return name not in entries
    return None


def _dir_state(path):
    """Three answers for "is this a directory", not `_safe_is_dir`'s two --
    for callers that print a verdict rather than just filter a list.

    ``is_dir()`` on a mode-000 *target* still succeeds: `stat` needs execute
    permission on the *parent*, not on the target (#363, confirmed against
    #341's own reproduction, which never reaches this case for exactly that
    reason). So the case this exists for is an unreadable *parent* of
    ``path``, where the underlying stat call raises `OSError` on at least
    this repo's own 3.9, 3.11 and 3.13 -- see `_safe_is_file` for the
    measurement, which is the same shape one call over. Swallowing that raise
    to `False`, `_safe_is_dir`'s job elsewhere, would report a directory that
    may well be there as a confident "does not exist" with a remedy attached
    -- the exact sentence #341 was filed about, one call site over. So
    callers that print a verdict get a third answer instead: ``"dir"``,
    ``"absent"``, or ``"unreadable"`` with the exception's own text as
    detail, never asserted from an errno table.

    Deliberately `path.stat()`, not `path.is_dir()` (self-review, #363):
    `is_dir()` wraps its own `stat()` call in a version-dependent swallow --
    measured directly, on this machine's local 3.14 install, `is_dir()`
    against the exact fixture above returns `False` with no exception at
    all, so an `except OSError` around `is_dir()` itself is unreachable there
    and this function would silently degrade back into the confident-absence
    bug it exists to fix, on precisely the interpreter this repo's own
    CLAUDE.md already flags as the one that swallows. `path.stat()` does
    raise there (also measured directly, same fixture); 3.9/3.11/3.13 are
    reasoned rather than independently measured for `stat()` specifically --
    `is_dir()` already re-raises on those three (this file's own
    `_safe_is_file` measurement, the same shape one call over), and `is_dir()`
    can only re-raise what its own internal `stat()` call raised first, so
    `stat()` itself raising there is implied rather than a fresh claim.

    `stat()` raises `FileNotFoundError`/`NotADirectoryError` for a genuinely
    absent path too (self-review, #363: the first version of this function
    folded that into "unreadable" and broke every genuinely-absent case,
    caught by this file's own must-not-fire controls). Both are `OSError`
    subclasses whose type -- not an errno table, which CLAUDE.md already
    warns folds several Win32 codes onto `ENOENT` on Windows -- is what
    Python's own interpreter normalises platform errors into, so they are
    caught ahead of the general `OSError` arm and read as ordinary absence --
    but no longer on the strength of the type alone. #380: Windows folds an
    unlookable name onto that same type with no distinguishing signal, so the
    absence arm asks `_absence_confirmed` for a positive confirmation and falls
    to `unreadable` when none is available.
    """
    try:
        st = path.stat()
    except (FileNotFoundError, NotADirectoryError) as exc:
        confirmed = _absence_confirmed(path)
        if confirmed is True:
            return "absent", ""
        if confirmed is False:
            return "unreadable", _one_line(
                "the name is present in its parent's listing but stat could not "
                "reach it: {}".format(exc)
            )
        return "unreadable", _one_line(
            "stat reported absence and nothing could confirm it: {}".format(exc)
        )
    except OSError as exc:
        return "unreadable", _one_line(str(exc))
    except ValueError as exc:
        # #380, adjacent: `stat` raises `ValueError`, not `OSError`, for a path
        # carrying an embedded null byte, so neither arm above caught it and it
        # escaped this function -- a raise path in a script whose contract is
        # exit 0 always, one VERDICT line. The values that reach here come from
        # `.oss.json` / `.oss.local.json`, and JSON can spell a null.
        return "unreadable", _one_line(str(exc))
    return ("dir" if stat.S_ISDIR(st.st_mode) else "absent"), ""


def _own_supertool_tree(project_dir):
    """The checkout this directory is inside, as ``(root, core)``, or ``(None, None)``.

    Transcribed from supertool's `hooks/session-start.sh`, which walks up for the
    `.supertool.json` that would be loaded and looks for a `supertool.py` beside it.
    Inside such a tree the hook deliberately creates **no** wrapper: one pointing at
    the plugin install would run the plugin's core against this tree's presets, the
    mix every custom op declines. So `./supertool` being absent there is correct, and
    a check without this arm would fire a confident wrong warning in claude-supertool
    -- which is itself managed by this loop.

    **The root is returned with the core**, and that is the second instance of the same
    defect CI caught in the comparison above. The walk starts at `realpath(project_dir)`
    -- it has to, or a symlinked project directory walks up the wrong tree -- so the core
    it finds is spelled in resolved form while the caller holds the raw `project_dir`.
    Handing that core to `_display(project_dir, ...)` made `relative_to` raise
    `ValueError` and fall back to an absolute path: `/tmp` against `/private/tmp` on
    macOS, an extended-length prefix on Windows. Only the printed string was affected
    and never a verdict, which is exactly why nothing caught it -- so the resolved root
    is returned alongside and the caller displays against the root the core came from.

    An unreadable directory on the way up must read as "no config here" and let the
    walk continue -- that is the safe direction, since the failure is to *not* claim
    an own-tree, which costs a warning rather than a wrong silence. This docstring
    used to say `is_file()` already does that by swallowing `OSError`, and that claim
    was false (PR #359, CI red on 8 of 14 legs -- Python 3.9/3.10/3.11 on BOTH
    `ubuntu-latest` and `macos-latest`, on the exact input #341's own fix is about).
    See `_safe_is_file`'s own docstring for the measurement: `EACCES` is re-raised
    on 3.9/3.11/3.13, and only this repository's local 3.14 interpreter swallows
    it, which is this repo's own CLAUDE.md warning about the interpreter axis being
    the easier one to miss. So the swallow is done explicitly here, on every
    interpreter, rather than trusted to a stdlib behaviour whose ignored-errno set
    is not pinned down across the versions CI actually runs.
    """
    directory = Path(os.path.realpath(str(project_dir)))
    while True:
        if _safe_is_file(directory / WATCH_CONFIG):
            core = directory / SUPERTOOL_CORE
            return (directory, core) if _safe_is_file(core) else (None, None)
        if directory.parent == directory:
            return None, None
        directory = directory.parent


def plugin_supertool_entries(cache_root=None, record=None):
    """Every unpacked supertool `supertool.py` in the plugin cache, newest-named last.

    Returns a list of ``(version, path)``. Empty means the question "is this link the
    plugin's" has no answer available -- not that the link is wrong.

    `os.listdir` rather than `Path.glob`, for the reason in `_listdir`: glob swallows
    `PermissionError` while walking and yields nothing, so an unreadable cache would
    arrive here indistinguishable from an empty one. Here both do route to the same
    verdict, deliberately -- but by a return value that says so rather than by an
    absence nobody produced on purpose.
    """
    root = Path(os.path.expanduser(cache_root or PLUGIN_CACHE_ROOT))
    try:
        markets = sorted(os.listdir(str(root)))
    except OSError:
        return []
    found = []
    for market in markets:
        base = root / market / SUPERTOOL_ENTRY
        try:
            versions = sorted(os.listdir(str(base)))
        except OSError:
            continue
        for version in versions:
            entry = base / version / SUPERTOOL_CORE
            # #383: a bare `Path.is_file()` here raises unguarded for an
            # unreadable entry on at least 3.9/3.11/3.13 (`_safe_is_file`'s
            # own measurement, this repo's local 3.14 excepted), which would
            # crash this function's caller with a traceback instead of the
            # "could not tell" state `entries` being empty already produces.
            # `_safe_is_file` -- same precedent as #363's `_jit_layer_verdict`
            # comprehension -- drops the one bad candidate and keeps the rest,
            # which is safe here specifically because an entry dropped this
            # way still lands in the existing `unknown-plugin-path` /
            # `unknown-comparison` states below rather than a false `ok`.
            if _safe_is_file(entry):
                found.append((version, entry))
    return found


def supertool_entry_point(project_dir, cache_root=None, record=None):
    """Which state this repo's `./supertool` is in. Returns ``(state, detail)``.

    Ten states. Three of them are ways of saying "could not tell", and those are the
    reason this is a function rather than an ``==``:

    * ``own-tree`` -- a supertool checkout, where no wrapper is correct.
    * ``own-tree-stranger`` -- a supertool checkout that has one anyway.
    * ``absent`` -- nothing there. A fresh clone, or a worktree cut mid-session.
    * ``ok`` -- a link reaching a `supertool.py` in the plugin cache.
    * ``other-target`` -- a link reaching something else. Observed on this repo, where
      supertool's hook reported `./supertool already exists here and is not the plugin
      symlink -- leaving it untouched`. A deliberate local checkout looks exactly like
      this, so it is reported and not condemned.
    * ``unknown-plugin-path`` -- **a could-not-look state.** There is a link, and no
      readable cache to compare it against. Calling that ``other-target`` accuses a
      link that may be perfectly correct; calling it ``ok`` clears one that may not be.
      Neither was measured, so neither is said.
    * ``unknown-comparison`` -- the same shape one layer down: candidates were found and
      the filesystem would not say whether any of them is this file. Kept apart from
      ``unknown-plugin-path`` so the message can name which of the two happened, and
      apart from ``other-target`` because falling through to that is precisely the
      accusation this pair exists to avoid.
    * ``not-a-symlink`` / ``dangling`` / ``unreadable`` -- present and not usable, each
      with its own remedy, none of them "create one".
    """
    link = Path(project_dir) / SUPERTOOL_ENTRY
    root, core = _own_supertool_tree(project_dir)
    # #341: `os.path.lexists` swallows every `OSError`, not only `ENOENT` --
    # the third instance of the class #333/#340 already fixed once in this
    # file's PATH walk. An unreadable PARENT of `link` (an over-long
    # component, a mode-000 ancestor) must not read as "absent", which would
    # print a remedy telling the reader to link a file that may already be
    # there. It reuses the `unreadable` state already returned below for a
    # readlink/stat failure -- `check_supertool_entry_point`'s catch-all
    # message for that state already reads correctly here too: "so which of
    # present/absent/wrong-target this repo is in is unknown."
    try:
        os.lstat(str(link))
        present = True
    except (FileNotFoundError, NotADirectoryError):
        # Absence, stated by the exception itself -- nothing is asked twice.
        present = False
    except OSError as exc:
        return "unreadable", str(exc.strerror or exc.__class__.__name__)

    if core is not None:
        # Displayed against the root the core was found under, not against the raw
        # project_dir -- see _own_supertool_tree.
        if present:
            return "own-tree-stranger", _display(root, core)
        return "own-tree", _display(root, core)
    if not present:
        return "absent", ""
    if not os.path.islink(str(link)):
        return "not-a-symlink", _display(project_dir, link)

    try:
        target = os.readlink(str(link))
    except OSError as exc:
        return "unreadable", str(exc.strerror or exc.__class__.__name__)
    resolved = os.path.realpath(os.path.join(str(link.parent), target))
    try:
        os.stat(resolved)
    except FileNotFoundError:
        # The exception in hand settles it; no second question is asked of the
        # filesystem to explain why the first failed.
        return "dangling", resolved
    except OSError as exc:
        return "unreadable", "{} ({})".format(resolved, exc.strerror or exc.__class__.__name__)

    entries = plugin_supertool_entries(cache_root=cache_root, record=record)
    if not entries:
        return "unknown-plugin-path", resolved
    # Identity, never string equality -- see `_same_file`. A candidate the filesystem
    # would not answer for is remembered rather than counted as a mismatch: "these are
    # different files" and "I could not tell" must not both come out as other-target.
    undecidable = False
    for version, entry in entries:
        same = _same_file(resolved, str(entry))
        if same is None:
            undecidable = True
            continue
        if same:
            active = active_versions([SUPERTOOL_ENTRY], record=record).get(SUPERTOOL_ENTRY)
            if active and active != version:
                return "ok", "{} (cached {}, active {})".format(resolved, version, active)
            return "ok", resolved
    if undecidable:
        return "unknown-comparison", resolved
    return "other-target", resolved


def check_supertool_entry_point(project_dir, cache_root=None, record=None):
    """One line, in every state. Never raises: `supertool_entry_point` returns."""
    state, detail = supertool_entry_point(project_dir, cache_root=cache_root, record=record)
    if state == "own-tree":
        report(
            "OK",
            "./supertool: not expected here -- this is a supertool checkout, so its "
            "session-start hook deliberately creates no wrapper (one would run the "
            "plugin core against this tree's presets). Call {} directly.".format(detail),
        )
    elif state == "own-tree-stranger":
        report(
            "WARN",
            "./supertool exists inside a supertool checkout, where the session-start "
            "hook creates none on purpose. If it points at the plugin install it runs "
            "the plugin core against this tree's presets and every custom op through it "
            "declines. Call {} directly and remove the wrapper.".format(detail),
        )
    elif state == "ok":
        report("OK", "./supertool: the plugin's entry point ({})".format(detail))
    elif state == "absent":
        report(
            "WARN",
            "./supertool: absent. Every developer brief this plugin issues calls it, and "
            "it is gitignored on purpose -- committing it would bake one machine's "
            "absolute path into every clone -- so a fresh clone never has one. "
            "supertool's session-start hook creates it for the directory a session opens "
            "in, which is why a worktree cut mid-session has none either. Open a session "
            "here, or link it by hand to the supertool plugin's supertool.py.",
        )
    elif state == "other-target":
        report(
            "WARN",
            "./supertool points at {}, which is not a supertool.py in the plugin cache. "
            "A deliberate local checkout looks exactly like this and may be what you "
            "want; a stale link from another machine looks the same and is not. Nothing "
            "here can tell them apart, so this names the target rather than judging "
            "it.".format(detail),
        )
    elif state == "unknown-plugin-path":
        report(
            "WARN",
            "./supertool points at {}, and no supertool.py could be found in the plugin "
            "cache to compare it against -- so whether this is the plugin's entry point "
            "is unknown, not wrong. Check that supertool is installed.".format(detail),
        )
    elif state == "unknown-comparison":
        report(
            "WARN",
            "./supertool points at {}, and the plugin cache does hold supertool.py "
            "copies, but the filesystem would not say whether any of them is that same "
            "file -- so this is unknown, not wrong. Not reported as a bad target: the "
            "comparison failed, the link did not.".format(detail),
        )
    elif state == "not-a-symlink":
        report(
            "WARN",
            "{} exists and is not a symlink. supertool's session-start hook leaves "
            "anything already at that name untouched, so every op call in this repo "
            "reaches whatever this is rather than the tool the briefs mean.".format(detail),
        )
    elif state == "dangling":
        report(
            "WARN",
            "./supertool is a symlink to {}, which does not exist. The remedy is "
            "re-linking, not creating: the checkout it named has moved or gone.".format(
                detail
            ),
        )
    else:
        report(
            "WARN",
            "./supertool: could not be read ({}) -- so which of "
            "present/absent/wrong-target this repo is in is unknown.".format(detail),
        )


# --- reaches the running install (#288/#289) -----------------------------------
#
# `oss-workspace` is meant to be linked once, by hand, into `~/.local/bin` -- see
# README.md. That link is resolved once, at install time, against a directory that
# is version-scoped (`.../dpt-plugins/oss/<version>/bin/`), so nothing re-points it
# on a later release and nothing checks it. A stale target that still exists behaves
# exactly like a current one. Measured twice on the maintainer's own machine, and the
# second time carried a security consequence: the release that shipped a fix to
# `bin/oss-workspace` itself (#324) was the one release whose fix a stale link would
# silently have kept out.
_OSS_WORKSPACE_CACHE_SHAPE = re.compile(r"^oss-workspace$")


def _oss_workspace_version_segment(path):
    """The `<version>` component of a `.../oss/<version>/bin/oss-workspace` path, or
    `None` when the path does not have that shape.

    That shape is an observation about one plugin manager's cache layout, not a
    contract -- a parse that assumed it and used it to DECIDE match/mismatch would
    silently clear a target laid out any other way. It is not used that way here:
    `oss_workspace_launcher_state` decides by content, and this only supplies a
    human-readable label when the label is available. `None` is that "not
    available" answer, distinct from a version string that happens to be wrong.
    """
    parts = Path(path).parts
    if len(parts) < 4:
        return None
    if not _OSS_WORKSPACE_CACHE_SHAPE.match(parts[-1]):
        return None
    if parts[-2] != "bin" or parts[-4] != "oss":
        return None
    return parts[-3]


def _locate_on_path(name, path=None):
    """``(first PATH entry naming exactly `name`, or `None`; unreadable entries)``.

    Deliberately not `shutil.which`, which answers a different question --
    "can this be launched" -- and filters candidates on properties that are
    irrelevant here and actively wrong for the one shape this check is always
    looking for:

    * **On Windows**, `shutil.which`'s own source (`files = [cmd + ext for ext
      in pathext]`, with the bare `cmd` inserted only when `cmd` already ends
      in one of those extensions) never makes an extensionless name a
      candidate at all. `oss-workspace` is extensionless by design -- it is a
      POSIX shell script, run through Git Bash on Windows the same way
      `scripts/doctor.sh` and every other launcher this plugin ships is (see
      the trap in this repo's own CLAUDE.md) -- so `shutil.which("oss-
      workspace")` on native Windows Python returns `None` unconditionally,
      regardless of whether the symlink this launcher's own install line
      creates is present and correct. #329: every one of five tests collapsed
      to `not-resolvable` on all four Windows CI legs, and this is why --
      not a labeling gap in `_oss_workspace_version_segment`, which was the
      wrong mechanism named in the self-review that first looked at this.
    * **On POSIX**, `shutil.which`'s default `mode` additionally requires
      `os.X_OK`, so a copy that exists with the right bytes but lacks the
      execute bit -- irrelevant to a content comparison -- is invisible to it
      too (observed on this machine;
      `test_a_non_executable_target_is_still_resolved`).

    This check only ever needs one answer -- does a file or symlink named
    exactly `name` exist here, so its bytes can be read -- and asks that
    directly, which is also platform-independent by construction: no
    extension list, no execute bit, just one `os.lstat` per PATH entry.

    **`os.lstat`, not `os.path.lexists`, and that is #333.** `lexists` swallows
    *every* `OSError`, not only `ENOENT`, so a PATH entry the process cannot
    traverse -- permission-denied, or with an over-long component -- was
    indistinguishable from one that simply does not hold the file, and the walk
    continued silently. If every entry answered that way the caller received
    exactly the `not on PATH` a genuinely absent launcher produces: this
    repository's named defect class, an absence produced by the tool read as an
    absence in the world. `shutil.which` had the same property through its own
    `_access_check`, so the rewrite in #329 neither introduced nor removed it.

    So the entries that could not be looked at are returned alongside the hit,
    as `[(entry, exc), ...]`, rather than collapsed into it -- the same
    resolution `_workflow_scan` already took for `(files, unreadable)` after
    #124, and for the same reason: `None` already means "looked everywhere,
    found nothing", and one value cannot also mean "could not look".

    **The exception in hand does the classifying; nothing asks the filesystem a
    second question.** `FileNotFoundError` is absence. `NotADirectoryError` is
    absence too -- an `ENOTDIR` says no path under this entry can exist, and a
    PATH entry that is a plain file is an ordinary configuration that must not
    produce a warning. Everything else is "could not look". A follow-up
    `os.path.exists()` to tell those apart is exactly what took out the release
    gate in #76: it swallows a different set of errnos on different interpreter
    versions, so the explanation would be less reliable than the failure it
    explains.

    **A dangling symlink does not stop the search.** `os.lstat` succeeds on one
    -- it stats the link itself, not the target -- and a first version
    of this function returned on the first `lexists` match unconditionally, so
    a stale, dead `oss-workspace` symlink anywhere earlier on `PATH` (left over
    from a prior install layout, say) shadowed a correct, matching one further
    down `PATH` and reported `unresolved-target` for a launcher that was, one
    directory later, genuinely present. `shutil.which` never had this failure
    mode: its own `_access_check` runs `os.path.exists`, which follows the
    symlink and is `False` for a dangling one, so it silently kept searching.
    This restores that one piece of `shutil.which`'s behaviour -- continue past
    a candidate that resolves to nothing -- without reintroducing the
    extension or executable-bit filtering that made `shutil.which` wrong for
    this check in the first place. Anything else that `os.lstat`
    answers for -- a regular file, a directory, a valid symlink -- stops the
    search immediately and is returned as-is: those are all "found something,"
    and it is the caller's job (via `os.path.realpath` and `read_bytes`) to
    decide whether what was found can be compared.

    **An unreadable entry does not withhold a hit found later on PATH.** The
    unreadable list is returned in every case, but a candidate that was actually
    resolved is a positive answer and stands on its own; only the *negative*
    answer is the one the sixth state replaces. The residue is stated rather
    than hidden: an unreadable entry EARLIER on PATH could in principle hold a
    launcher that shadows the one found later, and this does not report that.
    Warning about a launcher that was found, and matches, on the strength of a
    directory nobody could read is the worse trade -- it would fire on every run
    of a process that cannot traverse some entry of its own PATH.
    """
    search = path if path is not None else os.environ.get("PATH", "")
    unreadable = []
    for entry in search.split(os.pathsep):
        if not entry:
            continue
        candidate = os.path.join(entry, name)
        try:
            st = os.lstat(candidate)
        except (FileNotFoundError, NotADirectoryError):
            # Absence, stated by the exception itself -- nothing is asked twice.
            continue
        except OSError as exc:
            unreadable.append((entry, exc))
            continue
        if stat.S_ISLNK(st.st_mode):
            try:
                os.stat(candidate)
            except (FileNotFoundError, NotADirectoryError):
                # Dangling: nothing is actually reachable through this PATH
                # entry, so it contributes nothing -- keep looking, same as
                # shutil.which.
                continue
            except OSError as exc:
                # The link exists and where it points could not be looked at.
                # That is neither a dangling link nor a resolvable one.
                unreadable.append((entry, exc))
                continue
        return candidate, unreadable
    return None, unreadable


def _describe_unreadable(unreadable):
    """Which PATH entries could not be read, and the errno each answered with.

    The errno is carried rather than the message: a message is locale-dependent
    and, on Windows, several distinct Win32 codes fold onto one errno, so the
    number is the part a reader can look up. Nothing here classifies BY errno --
    that decision was already taken by exception type in `_locate_on_path`,
    which is the rule `CLAUDE.md` records after #76 and again after the errno-206
    round: never read a platform's error codes out of a table.
    """
    return "; ".join(
        "{} ({}, errno {})".format(entry, exc.__class__.__name__, exc.errno)
        for entry, exc in unreadable
    )


def oss_workspace_launcher_state(plugin_root=None, path=None):
    """Which state PATH's `oss-workspace` is in, relative to THIS running install.

    Returns ``(state, detail)``. Six states, and the choice of which five are
    not "matched" is deliberate:

    * ``not-resolvable`` -- PATH carries no `oss-workspace` at all. Nothing was
      found to compare, so this must never render as a mismatch, which would name a
      target that does not exist.
    * ``path-unreadable`` -- nothing was found AND at least one PATH entry could
      not be looked at, so "PATH carries no `oss-workspace`" is a claim this walk
      is in no position to make (#333). `detail` names every such entry and the
      errno it answered with. This is the state that must never render as
      `not-resolvable`: those two are "looked everywhere, found nothing" and
      "could not look", and rendering them the same is this repository's own
      defect class.
    * ``matched`` -- the resolved target is either the same file as this running
      install's own `bin/oss-workspace` (`os.path.samefile`, so a symlink straight
      at it counts) or its bytes are identical (CRLF folded, matching every other
      content comparison in this file) AND the path carries no claim of belonging
      to a different install -- see ``matched-elsewhere`` below for the one it does.
    * ``matched-elsewhere`` (#519) -- bytes are identical today, but the resolved
      target recognisably belongs to a DIFFERENT version-scoped plugin cache
      directory than `plugin_root`'s own: `_oss_workspace_version_segment` parses a
      version out of it, AND this running install's own manifest version parses too,
      AND the two disagree. A stale pin with correct bytes behaves exactly like a
      current one -- until the next release that touches this file, which is
      exactly the occurrence that cost #324 its security fix -- so this is reported
      even though nothing differs today. `detail` is `(resolved, their_version)`.
      **This running install's own version being unreadable (`our_version is None`)
      is not the same fact as the two versions disagreeing, and must not read as
      one** -- that would be this repository's own defect class landing on the
      check written to fix its first occurrence, so that case stays `matched`.
    * ``mismatched`` -- the resolved target's bytes differ. `detail` is
      ``(resolved, their_version, our_version)``; `their_version` is
      `_oss_workspace_version_segment(resolved)` and may be `None`.
      `our_version` is read from **`plugin_root`'s own manifest**, not from the
      running install (#350), and is `None` on exactly the same terms as
      `their_version`: it names a version or it says there is none, and it never
      renders a word where a version goes. Before #350 it came from
      `plugin_version()`, a global, so a caller that passed a `plugin_root` got a
      version describing one tree beside a byte comparison performed against
      another -- and the only assertion over it was pinned to whatever version
      this repository happened to be at, which made it fire on the release that
      bumped the manifest and nowhere else.
    * ``own-copy-unreadable`` / ``unresolved-target`` -- one side could not be read,
      so nothing was compared. Neither is "matched" and neither is "mismatched":
      both of those would be an answer to a question that was not actually asked.

    **Content decides match/mismatch; the version segment is a label, not a
    filter.** #289's own second occurrence is why: the stale target was a git clone
    pulled mid-release, so its *directory* read "0.5.0" while its *content* matched
    no release at all. A check that compared only the version segment would have
    called that "matched" and missed the exact failure it was written to catch. The
    version segment is still read and reported when it parses, because it is the
    cheap, human-readable half of the answer -- just not the half anything is
    decided from.

    `entry` comes from `_locate_on_path("oss-workspace", path=path)`, never
    `shutil.which` -- see that function's docstring for why (#329). Every
    branch below is reachable through `path` alone with an ordinary PATH-entry
    fixture: `_locate_on_path` uses `os.lstat`, which succeeds on a directory
    too, so `unresolved-target` needs no separate testing seam either.
    `path-unreadable` is the one exception -- an unreadable directory is a
    property of the filesystem rather than of the fixture, so it is reached
    both by a real `chmod` (measured, and skipped with what went untested when
    the mode bit does not deny) and by injecting `os.lstat`, which needs no
    privileges and therefore never skips on any leg.
    """
    plugin_root = Path(plugin_root or PLUGIN_ROOT)
    own = plugin_root / "bin" / "oss-workspace"

    entry, unreadable = _locate_on_path("oss-workspace", path=path)
    if entry is None:
        if unreadable:
            return "path-unreadable", _describe_unreadable(unreadable)
        return "not-resolvable", ""
    resolved = os.path.realpath(entry)

    if _same_file(resolved, str(own)):
        return "matched", resolved

    try:
        own_bytes = own.read_bytes()
    except OSError as exc:
        return "own-copy-unreadable", "{} ({})".format(own, exc.__class__.__name__)

    try:
        resolved_bytes = Path(resolved).read_bytes()
    except OSError as exc:
        return "unresolved-target", "{} ({})".format(resolved, exc.__class__.__name__)

    their_version = _oss_workspace_version_segment(resolved)
    _our_state, our_version = _manifest_version(plugin_root)

    if own_bytes.replace(b"\r\n", b"\n") == resolved_bytes.replace(b"\r\n", b"\n"):
        # #519: content equality answers "are these bytes the same today", not "is
        # this THIS running install" -- and those are different questions when the
        # resolved target recognisably belongs to a DIFFERENT version-scoped plugin
        # cache directory (`their_version` parses and disagrees with `our_version`).
        # That is a stale pin whose bytes have not diverged YET, which is a fact
        # about today, not about the next release that touches this file (#324).
        # A version that fails to parse, or one that matches this running install's
        # own, carries no such claim and stays plain `matched` -- an ordinary
        # hand-copied path, or two paths onto the same install, is not stale.
        # `our_version is None` -- this running install's own manifest could not be
        # read, or carries no version field -- must ALSO stay `matched`: `their_version
        # != None` is vacuously true for any cache-shaped path, and reporting a
        # CONFIRMED different install on the strength of an absence in our own
        # reading is this repository's own defect class, one input over from the one
        # `matched-elsewhere` exists to fix.
        if their_version is not None and our_version is not None and their_version != our_version:
            return "matched-elsewhere", (resolved, their_version)
        return "matched", resolved

    return "mismatched", (resolved, their_version, our_version)


def _launcher_remedy(plugin_root, windows=None):
    """How to make `oss-workspace` reachable, on the platform this is running on.

    **#330 asked the prior question first: is `bin/oss-workspace` installable on
    Windows at all, by the route the POSIX line describes?** It is not, and the
    two reasons are read off files in this repository rather than off a Windows
    machine, so both are graded REASONED -- macOS is the only platform this was
    run on.

    * `bin/oss-workspace` is a `#!/bin/sh` script. It is meant to run under Git
      Bash on Windows -- that is not an inference, it is written into the script,
      which strips a backslash separator from `$0` for exactly that case, and into
      this repo's CLAUDE.md. Native `cmd` and PowerShell have no route to an
      extensionless `/bin/sh` script: `PATHEXT` never matches one.
    * `~/.local/bin` on `PATH` is a POSIX convention. Nothing puts it on a Windows
      `PATH`, so even a link successfully created there is not found.

    So the honest Windows output is a sentence, not a translated command. A
    translated command would be the same `misdirects` defect the issue filed, one
    platform over: a receipt naming a next step that does not do what the caller
    needs. The route that does work is the one README already gives as the
    fallback -- run it from this install's own checkout.

    Deliberately NOT claimed here, because it was not measured and a wrong claim in
    a remedy line is worse than a short one: what Git Bash's own `ln -sf` does. MSYS
    may copy rather than link depending on `MSYS=winsymlinks`, which if true would
    make the POSIX line actively harmful there -- a copy is a stale target from the
    moment of the next release, which is the very failure this check exists to
    catch. Unverified, so unsaid.

    `windows` is a parameter rather than a read of `os.name` at the call site so
    both arms are assertable on every CI leg. Its default is the running platform,
    and `test_the_default_remedy_matches_the_platform_actually_running` asserts
    that default against `os.name` with no skip -- which is the assertion that has
    to land on a Windows leg for this to be closed rather than restated (#265).
    """
    target = Path(plugin_root) / "bin" / "oss-workspace"
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return 'ln -sf "{}" ~/.local/bin/oss-workspace'.format(target)
    return (
        "There is no one-line install of the launcher on Windows: "
        "bin/oss-workspace is a /bin/sh script, so it runs under Git Bash rather "
        "than cmd or PowerShell, and the POSIX home-directory bin convention the "
        "documented link targets is on no Windows PATH. Run it from this install's "
        'own checkout, inside Git Bash: sh "{}"'.format(target.as_posix())
    )


def check_oss_workspace_launcher(plugin_root=None, path=None, windows=None):
    """One line, in every state. The remedy line names THIS install's own path
    (`plugin_root`, which defaults to `PLUGIN_ROOT` -- this script's own resolved
    location) rather than `$PWD`, so it is correct regardless of where the reader is
    standing (#288), and is platform-appropriate rather than POSIX everywhere
    (#330 -- see `_launcher_remedy`)."""
    plugin_root = Path(plugin_root or PLUGIN_ROOT)
    remedy = _launcher_remedy(plugin_root, windows=windows)
    state, detail = oss_workspace_launcher_state(plugin_root=plugin_root, path=path)
    if state == "matched":
        report(
            "OK",
            "oss-workspace launcher: PATH resolves to {}, which matches this "
            "running install's own bin/oss-workspace.".format(detail),
        )
    elif state == "not-resolvable":
        # #344: this message embeds `remedy`, a paste-ready command naming
        # THIS install's own resolved path -- report_with_remedy, not
        # report, so a non-ASCII install path is not folded to `?`.
        report_with_remedy(
            "WARN",
            "oss-workspace launcher: not on PATH, so every developer brief this "
            "plugin issues that calls `oss-workspace` has no route to run it.",
            remedy,
        )
    elif state == "path-unreadable":
        report(
            "WARN",
            "oss-workspace launcher: part of PATH could not be read ({}), and no "
            "oss-workspace was found in the entries that could -- so whether the "
            "launcher is reachable is unknown, not absent. Make those entries "
            "readable and run this again; installing a second copy on the strength "
            "of this line would be acting on a question nobody answered.".format(
                detail
            ),
        )
    elif state == "matched-elsewhere":
        resolved, their_version = detail
        _our_state, our_version = _manifest_version(plugin_root)
        report(
            "WARN",
            "oss-workspace launcher: PINNED ELSEWHERE -- PATH resolves oss-workspace "
            "to {} (cache version {}), a different install from this running one "
            "(version {}). Its content happens to be identical today, so this is not "
            "a mismatch -- but identical today is a fact about today, not a claim "
            "about this running install: a stale pin with correct bytes behaves "
            "exactly like a current one until the next release that touches this "
            "file, which is what cost #324 its security fix. Re-point the symlink to "
            "this running install's own bin/oss-workspace.".format(
                resolved, their_version, our_version
            ),
        )
    elif state == "own-copy-unreadable":
        report(
            "WARN",
            "oss-workspace launcher: could not read this running install's own "
            "bin/oss-workspace ({}) -- so whether PATH's copy matches is unknown, "
            "not wrong.".format(detail),
        )
    elif state == "unresolved-target":
        # #344: same reason as the not-resolvable arm above.
        report_with_remedy(
            "WARN",
            "oss-workspace launcher: PATH resolves oss-workspace to {} -- so "
            "whether it matches this running install is unknown, not wrong.".format(
                detail
            ),
            remedy,
        )
    elif state == "mismatched":
        resolved, their_version, our_version = detail
        if their_version:
            version_clause = "cache version {}".format(their_version)
        else:
            version_clause = (
                "a path with no recognised .../oss/<version>/bin/ shape, so no "
                "version could be read from it"
            )
        if our_version:
            ours_clause = "version {}".format(our_version)
        else:
            # #350's third state. Symmetric with `version_clause` above: say the
            # label is missing rather than print "version unreadable", which reads
            # as a version and is the defect this whole check exists to not commit.
            #
            # `_manifest_version` distinguishes an unreadable manifest from one that
            # parsed and carries no version, and this line does not, because the
            # state is not in `detail` and re-deriving it here would mean asking the
            # filesystem a second question to explain why the first one failed --
            # the trap that took the release gate out in #76. So the sentence
            # enumerates the possibilities instead of asserting one: a reader told
            # only "could not be read" goes looking for a permissions problem that
            # may not exist.
            ours_clause = (
                "no version could be read from its own manifest -- it is absent, "
                "unparseable, or carries no version field"
            )
        # #344: same reason as the not-resolvable arm above.
        report_with_remedy(
            "WARN",
            "oss-workspace launcher: SKEW -- PATH resolves oss-workspace to {} "
            "({}), whose content differs from this running install's own "
            "bin/oss-workspace ({}). A stale target that still exists "
            "behaves exactly like a current one -- one release shipped a security "
            "fix to this exact file (#324), and a symlink pinned at an older "
            "release would silently keep running without it.".format(
                resolved, version_clause, ours_clause
            ),
            remedy,
        )
    else:
        # #348: a state `oss_workspace_launcher_state` does not emit today.
        # Every real state above has a named arm; this exists so a seventh
        # state added later is REPORTED rather than reaching the `mismatched`
        # arm's `detail` unpack blind -- which would turn `exit 0 always` into
        # a traceback three frames from wherever the state was added. `detail`
        # is not assumed to be any particular shape, so it is not touched.
        report(
            "WARN",
            "oss-workspace launcher: unrecognised state {!r} from "
            "oss_workspace_launcher_state -- not one of matched, "
            "matched-elsewhere, not-resolvable, path-unreadable, "
            "own-copy-unreadable, unresolved-target, mismatched. Treat this as "
            "unknown, not absent; this check's own code has fallen behind its "
            "producer.".format(state),
        )


def check_directory(label, value, config_found=True):
    if not config_found:
        unmeasured(label)
        return
    if not value:
        report("WARN", "{}: not set in config; cannot check it".format(label))
        return
    path = Path(os.path.expanduser(str(value)))
    state, detail = _dir_state(path)
    if state == "dir":
        report("OK", "{}: {}".format(label, path))
    elif state == "absent":
        report("WARN", "{}: {} does not exist".format(label, path))
    else:
        # #363: an unreadable *parent* of `path` must not read as a confident
        # "does not exist" with a remedy telling the reader to create
        # something that may already be there.
        report(
            "WARN",
            "{}: {} could not be checked -- {} -- so whether it exists is "
            "unknown, not confirmed absent.".format(label, path, detail),
        )


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


# COMPATIBILITY_BULLET and _fragments_directory moved to
# scripts/doctor_check_fragments_readme.py along with check_fragments_readme
# (#497); see that module.


# Moved to scripts/doctor_check_auto_update.py (#497) -- see that module for
# the check and its docstring, unchanged; this is a pure relocation.
from doctor_check_auto_update import check_auto_update


# Moved to scripts/doctor_check_statusline.py (#497) -- see that module for
# the check, its private helper and their docstrings, unchanged; this is a
# pure relocation.
from doctor_check_statusline import _POSIX_VAR_RE, _statusline_windows_gap, check_statusline


# Moved to scripts/doctor_check_fragments_readme.py (#497) -- see that module
# for the check, its private helper and constant, and their docstrings,
# unchanged; this is a pure relocation.
from doctor_check_fragments_readme import (
    COMPATIBILITY_BULLET,
    _fragments_directory,
    check_fragments_readme,
)


JIT_RULES_DIR = ".claude/jit-context"
JIT_INDEX = "00-index.tsv"


# MEMORY_DIR, MEMORY_CONFIG_DIR, memory_layout, _display, _listdir,
# _identity_names and check_memory moved to scripts/doctor_check_memory.py
# (#497); see that module for the check and its private helpers, unchanged.
from doctor_check_memory import (
    MEMORY_DIR,
    MEMORY_CONFIG_DIR,
    memory_layout,
    _display,
    _listdir,
    _identity_names,
    check_memory,
)


# MERGE_OP, MERGE_RULE_FILE, settings_candidates, _permission_entries,
# _entry_count, merge_permission_state and check_merge_permission moved to
# scripts/doctor_check_merge_permission.py (#497); see that module for the
# check and its private helpers, unchanged. `MERGE_OP` is imported back here
# too: `PUBLISH_OP_PRESETS` below (`check_publish_confirm`, unmoved) still
# reads it as a bare name.
from doctor_check_merge_permission import (
    MERGE_OP,
    MERGE_RULE_FILE,
    settings_candidates,
    _permission_entries,
    _entry_count,
    merge_permission_state,
    check_merge_permission,
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


# Can the merge call skip supertool's own confirm gate? (#421)
#
# `presets/_publish_safety.py:require_confirm` is one function, shared by three
# ops, and it returns early on any of three opt-outs -- a `|force` suffix per
# call, `$SUPERTOOL_NO_PUBLISH_CONFIRM`, or `"no_publish_confirm": true` in this
# repo's `.supertool.json`. Reading the file and the environment is the whole
# check: no call, no spawn, nothing published.
#
# The opt-out is wider than the merge: setting the flag turns confirmation off
# for whichever of the three ops this repo's `presets` currently route, and a
# later preset arrives with confirmation already off, silently. So this is a
# read of the loaded presets, not a constant naming `gh-pr-merge` alone.
#
# Deliberately scoped to supertool's own gate. The harness's own permission
# layer sits above it, can refuse the call before supertool sees it, and an
# allowlist entry does not clear it reliably -- #421's own comment measured
# exactly that: an allowlist entry naming this call, denied five times across
# four pull requests, on a machine where the identical shape merged normally
# in a different repo. Nothing here can read that layer, so every message
# built from this state says so rather than implying a guarantee.
PUBLISH_OP_PRESETS = {
    "github": MERGE_OP,
    "devto": "devto_publish",
    "bluesky": "bluesky_publish",
}


def publish_confirm_state(project_dir, env=None):
    """Can supertool's confirm gate be skipped here? Three answers, not two.

    `confirmable` / `needs-force` / `could-not-tell`. `needs-force` is the
    shipped default -- no `.supertool.json` at all resolves here, same as one
    that declares the key `false` -- and it is not a fault.

    The flag is read with plain `bool()`, matching the gate it reports on
    (`_publish_safety.require_confirm` does `bool(_supertool_config().get(
    "no_publish_confirm"))`, not a type check) -- so a truthy non-boolean
    value such as `"yes"` really does turn confirmation off, and reporting
    that as `could-not-tell` would be a wrong answer dressed as caution.

    `could-not-tell` is reserved for a file that is there and broken --
    unreadable, or not an object -- because a broken file cannot be read at
    all, and a guess about a document that would not read is not the same
    thing as reading the flag it declares. It must never render as either of
    the other two.
    """
    env = os.environ if env is None else env
    doc, problem, detail = _supertool_document(project_dir)
    if problem:
        return "could-not-tell", detail
    if doc is None:
        doc = {}

    raw_flag = doc.get("no_publish_confirm")
    confirm_off = bool(raw_flag) or env.get("SUPERTOOL_NO_PUBLISH_CONFIRM") == "1"
    verb = "reaches" if confirm_off else "gates"

    presets = doc.get("presets")
    if isinstance(presets, list) and all(isinstance(p, str) for p in presets):
        routed = sorted(op for name, op in PUBLISH_OP_PRESETS.items() if name in presets)
        if routed:
            reach = "it {} {} here today".format(verb, ", ".join(routed))
        else:
            reach = "it {} none of {} today (no publish preset is enabled)".format(
                verb, ", ".join(sorted(PUBLISH_OP_PRESETS.values()))
            )
    else:
        reach = (
            "which op(s) it {} could not be read (`presets` in {} is absent "
            "or not a list of strings)".format(verb, WATCH_CONFIG)
        )

    if confirm_off:
        source = (
            "`no_publish_confirm` in {} is truthy".format(WATCH_CONFIG)
            if raw_flag
            else "SUPERTOOL_NO_PUBLISH_CONFIRM=1 in the environment"
        )
        return "confirmable", "{}, so {}".format(source, reach)
    return "needs-force", "no opt-out is set, so {}".format(reach)


def check_publish_confirm(project_dir, env=None):
    """Report supertool's publish-confirm gate before the merge step is where a
    maintainer meets it -- `skills/manager/SKILL.md`'s "before the first tick"
    section names this arrangement and nothing performs or checks it (#421).

    `needs-force` renders as OK, deliberately: it is the shipped default and
    most repos are in it, so flagging it as a warning trains a maintainer to
    skim doctor output, which costs more than the thing it would warn about.
    """
    state, detail = publish_confirm_state(project_dir, env=env)
    if state == "could-not-tell":
        report(
            "WARN",
            "publish confirm: {}, so whether the merge call can skip supertool's "
            "confirm gate is unknown -- not answered as either state, because "
            "both would be a guess about a file that would not read.".format(detail),
        )
        return
    if state == "confirmable":
        report(
            "OK",
            "publish confirm: {}. This is supertool's own gate only -- the "
            "harness's own permission layer sits above it and can still refuse "
            "the call regardless.".format(detail),
        )
        return
    report(
        "OK",
        "publish confirm: {}. Append |force to the call, set "
        "SUPERTOOL_NO_PUBLISH_CONFIRM=1, or add `no_publish_confirm: true` to "
        "{} before the first tick if batch merging is wanted -- this is the "
        "shipped default, not a fault.".format(detail, WATCH_CONFIG),
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
    state, detail = _dir_state(rules_dir)
    if state == "unreadable":
        # #363: same class as `check_directory` -- an unreadable parent must
        # not read as the confident "no rules for this repo" a genuine
        # absence gets.
        report(
            "WARN",
            "{}: could not be checked -- {} -- so whether this repo has "
            "rules is unknown, not confirmed absent.".format(JIT_RULES_DIR, detail),
        )
        return
    if state == "absent":
        report(
            "WARN",
            "{}: no rules for this repo. Project conventions are not being injected; "
            "nothing is broken, but nothing is being carried either.".format(JIT_RULES_DIR),
        )
        return

    rule_files, unreadable = _rglob_md(rules_dir)
    if unreadable:
        # #383: `Path.rglob` swallows `PermissionError` while it walks and
        # silently yields nothing for the subtree it could not enter, so the
        # layer count below could otherwise miss a whole layer with no sign
        # anything was skipped -- the #124 shape one call site over. Named
        # rather than silent, and if nothing at all could be read there is
        # nothing to compare "holds no rules" against, so that sentence is
        # not printed on top of it.
        report(
            "WARN",
            "{}: could not fully walk -- {} -- so the layer count below is "
            "a floor, not a total.".format(JIT_RULES_DIR, "; ".join(unreadable)),
        )
        if not rule_files:
            return

    layers = {}
    for rule in rule_files:
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
        # `str.isdigit()` and `int()` do not agree on a domain (#388):
        # U+00B2 SUPERSCRIPT TWO is True for `isdigit()` and `int()` refuses it, so
        # that guard alone lets the conversion below raise where the docstring
        # promises `unknown`. U+0662 ARABIC-INDIC DIGIT TWO is True for `isdigit()`
        # *and* accepted by `int()`, converting to 2 -- so a version string nobody
        # typed would silently compare equal to a real one. An ASCII-only digit
        # test closes both: `str.isdecimal()` alone does not, since U+0662 is also
        # decimal.
        if not parts or not all(
            part and all(ch in "0123456789" for ch in part) for part in parts
        ):
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
            # The gate answers one question -- does a changelog gate already run here
            # under another name -- so it governs the files that question is about and
            # no others (#479). An owned file outside that set is plainly `absent`:
            # reading the gate for it would report a decline scaffold never made, with
            # a remedy (`--force-owned`) that is not the one that writes it.
            gated_here = getattr(scaffold, "CHANGELOG_OWNED", frozenset(scaffold.OWNED))
            if name not in gated_here:
                findings.append(
                    {
                        "path": name,
                        "state": "absent",
                        "detail": "{}: not in this repo. Run /oss:scaffold.".format(name),
                    }
                )
                continue
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


def loop_repository(plugin_root=None):
    """Where a defect in *this plugin* gets filed. Returns ``(url, problem)``.

    A sibling of ``dependency_repositories``, not a row in it, and the reason is
    measured rather than aesthetic. That mapping's one caller is ``check_freshness``,
    which feeds it through ``published_versions`` into ``dependency_findings`` -- and
    that function unions ``declared | installed | latest``. This plugin is in neither of
    the first two, because nothing declares itself as its own dependency, so folding it
    into the mapping makes doctor print `oss: declared but not installed. Run
    `claude plugin install oss@dpt-plugins``. False, actionable, wrong, and printed by
    the plugin it is wrong about. "Every existing caller works unchanged" was the
    argument for folding; the one existing caller does not.

    So the loop's own board is derived the same way every other board is -- off the
    ``repository`` key in the manifest at ``PLUGIN_ROOT``, read from disk. No hardcoded
    slug, no name-to-repo table, nothing about one repository living in shared code.

    **Three states, because two is the collapse #292 is about.** A manifest with no
    ``repository`` key is a real state and it is not "there is no tracker":

    * ``(url, None)`` -- read.
    * ``(None, "no-repository-key")`` -- the manifest was read and does not say. Also
      where a non-string value lands: ``plugin.json`` is tracked and a contributor
      writes it, so an object here would otherwise be formatted into a diagnostic line
      and into whatever a brief does with it.
    * ``(None, "unreadable")`` -- absent, or not JSON.
    """
    root = Path(plugin_root) if plugin_root is not None else PLUGIN_ROOT
    try:
        doc = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "unreadable"
    value = doc.get("repository") if isinstance(doc, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None, "no-repository-key"
    return value.strip(), None


def check_loop_repository(plugin_root=None):
    """The caller that makes the accessor above reach something.

    An honest accessor nobody calls is a capability that exists and cannot be used,
    which is the same shape as the gap it was written to close. A guest install that
    cannot resolve where to send a tooling defect should learn that from the diagnostic
    rather than from an agent improvising a slug at filing time.
    """
    url, problem = loop_repository(plugin_root=plugin_root)
    if problem is None:
        report(
            "OK",
            "loop repository: {} -- where a defect in this plugin itself is filed. "
            "Read from this plugin's own manifest, not inferred.".format(url),
        )
    elif problem == "no-repository-key":
        report(
            "WARN",
            "loop repository: this plugin's manifest carries no usable string "
            "`repository` key, so where a defect in the loop's own tooling should be "
            "filed is unknown -- not absent. Nothing may guess a slug from it. Add "
            "`repository` to .claude-plugin/plugin.json.",
        )
    else:
        report(
            "WARN",
            "loop repository: this plugin's manifest at {} could not be read, so where a "
            "defect in the loop's own tooling should be filed is unknown -- not "
            "absent.".format(Path(plugin_root) if plugin_root is not None else PLUGIN_ROOT),
        )


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
                # #363: `_safe_is_dir`, not a bare `.is_dir()` -- one
                # unreadable candidate raising here used to propagate out of
                # the whole comprehension and be caught by the `except
                # OSError` below, discarding every candidate already found,
                # readable ones included.
                if _safe_is_dir(candidate)
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
    resolve -- ``..``, a drive, a backslash, empty -- ``rejected`` carries the string **as
    the plugin wrote it**, followed by the refusal's own reason in parentheses, and there
    are no entries at all. Both halves are needed: the string alone left #258's
    backslash case looking like a typo in a filename, and the reason alone would name a
    rule without the value it was applied to. It deliberately does not fall back to the
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
        parts, reason = _jit_path_parts(named)
        if not parts:
            return [], "{} ({})".format(_one_line(named), reason)
        return [(root.joinpath(*parts), "/".join(parts))], None
    parts = list(JIT_HOOK_MANIFEST)
    return [(root.joinpath(*parts), "/".join(parts))], None


def _jit_path_parts(token):
    """``(parts, reason)`` -- a manifest path as components, or why it was not resolved.

    ``/`` is the separator on every platform and a backslash is refused rather than
    guessed at. Splitting on ``os.sep`` made the answer a property of the runner (#258):
    ``custom\\hooks.json`` was two components on Windows and one literal filename on the
    eight POSIX legs, so one declaration produced ``reads`` on a fifth of the matrix and
    ``could-not-determine`` -- blaming a file that was in fact present -- on the rest.

    Refusing is the conservative half of a real choice and the permissive half was
    available: treating ``\\`` as a separator everywhere would resolve a Windows-authored
    declaration on all thirteen legs, uniformly. It is declined because a backslash is a
    legal filename character on POSIX, so accepting it reads a file the manifest did not
    name whenever the guess is wrong -- #241's substitution one field over, and here it
    would convert an honest non-answer into a confident one. Nothing here can tell the two
    intentions apart, and there is no authority this could transcribe and measure saying
    which the runtime accepts, so the value goes to the third state carrying its reason
    rather than to a guess. A plugin that wants to be read writes ``/``, which resolves
    everywhere.

    Two further components are refused, and the second is Windows-only in effect but
    guarded unconditionally because a guard that only fires on the platform that broke is
    a guard nobody re-reads. ``..`` climbs out. A component carrying a colon is a drive or
    a stream specifier: ``PureWindowsPath("C:/plugin").joinpath("D:", "x.sh")`` is
    ``D:x.sh`` -- the anchor resets and the join lands outside the install root
    entirely, which would then be stat'ed and read. A colon is not a legal filename
    character on Windows and is vanishingly rare on POSIX, so refusing it costs nothing
    and is one refusal rather than a table of platform behaviours.

    The reason is returned rather than logged because the caller writes it into the
    message: an unresolvable declaration and an absent file are two situations, and #258
    was the second one's sentence being printed about the first.
    """
    if "\\" in token:
        return None, (
            "a backslash, which is a separator on Windows and an ordinary filename "
            "character on POSIX -- nothing here can tell which was meant, and guessing "
            "would read a file the plugin did not name"
        )
    parts = [part for part in token.split("/") if part not in ("", ".")]
    if not parts:
        return None, "no component left to resolve"
    if ".." in parts:
        return None, "a component that climbs out of the install root"
    if any(":" in part for part in parts):
        return None, "a component carrying a colon, which resets the anchor of a join"
    return parts, None


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
                    parts = None if "$" in cleaned else _jit_path_parts(cleaned)[0]
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
            # #363: `_safe_is_dir`, not a bare `.is_dir()` -- same reason as
            # `jit_hook_roots`'s glob filter: one unreadable candidate must
            # not wipe every dimension already found.
            if _safe_is_dir(path)
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


def check_release_authority(project_dir, config):
    """#478: report which release-authority mode this repo is in, before the tag step
    rather than at it -- the same reason #421 put the merge-call check here.

    All three states are legitimate, so none of them is a WARN: the point is visibility,
    not a preference between them. What must never happen is `not-declared` rendering as
    anything but a stop -- so its detail names the same consequence `maintainer` gets,
    in the same words.
    """
    if oss_config is None:
        report("WARN", "release authority: not checked (scripts/oss_config.py could not be imported)")
        return
    if config is None:
        report("WARN", "release authority: not checked (.oss.json could not be read)")
        return
    state = oss_config.release_authority(config)
    if state == oss_config.AUTHORITY_LOOP:
        report(
            "OK",
            "release authority: loop -- .oss.json's release.authority grants the loop "
            "tagging and publishing without a stop. The release report must name this "
            "grant every time it acts under it.",
        )
    elif state == oss_config.AUTHORITY_MAINTAINER:
        report(
            "OK",
            "release authority: maintainer -- tagging and publishing stop, exactly as "
            "skills/manager/SKILL.md's Stops table reads.",
        )
    else:
        report(
            "OK",
            "release authority: not-declared (release.authority is absent, unreadable, "
            "or an unrecognised value) -- tagging and publishing stop, the same as "
            "maintainer. Set release.authority to \"loop\" in .oss.json to change that.",
        )


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
        # #383: this used to be `sorted(base.rglob("*.md"))` inside a
        # try/except OSError. `Path.rglob` swallows `PermissionError` while
        # it walks and returns `[]` for a directory it cannot enter -- it
        # does not raise -- so that `except` was dead code for exactly the
        # input it was written to catch, measured directly in
        # `tests/test_swallow_census_383.py`. `_rglob_md` uses
        # `os.walk(onerror=...)`, the only shape that speaks.
        paths, walk_unreadable = _rglob_md(base)
        for detail in walk_unreadable:
            unreadable.append("{}/: {}".format(directory, detail))
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

    # #383: same class as the two rglob call sites above -- `Path.glob("*.md")`
    # swallows `PermissionError` scanning `root / "agents"` itself and returns
    # `[]`, so the `except OSError` this used to be wrapped in could never
    # fire for the case it was written for (confirmed directly, same fixture
    # shape as `tests/test_swallow_census_383.py`'s rglob reproduction, one
    # level shallower). `_rglob_md` is written for a recursive walk, but
    # `agents/` has never had subdirectories and a flat `os.walk` first level
    # is the same one-directory scan `glob` performed -- the recursion never
    # runs because there is nothing to recurse into, so this is not a second
    # helper, only a documented reuse of the first one.
    agent_files, agents_unreadable = _rglob_md(root / "agents")
    if agents_unreadable:
        return lines + [
            (
                "WARN",
                "agent dispatch: could not be checked -- agents/ could not be listed "
                "({}), so "
                "there was nothing to check the dispatched names against".format(
                    "; ".join(agents_unreadable)
                ),
            )
        ]
    shipped = {path.stem for path in agent_files}

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
#: dispatches, the scripts it runs, and the contracts those scripts enforce.
#: Deliberately not a version number.
#:
#: `schemas/` joined this on #415, and how it was missing is the point. The set was
#: chosen when the contract between two copies lived entirely in code and prose. It
#: no longer does: `schemas/agent-report.schema.json` declares a contract number,
#: `scripts/report_schema.py` reads it, and a mismatch refuses an agent report with
#: `UNVALIDATABLE` at exit 2. So two copies differing ONLY there were reported as
#: carrying the same bytes -- a comparison that looked, found nothing, and could not
#: say it had not looked everywhere.
#: `hooks/` joined on #480 and belongs in the first half rather than the second: the
#: harness executes what is in there at every session start, so two copies differing
#: only there behave differently from the first second of a session -- which is the
#: exact property this tuple selects for.
COMPARED_DIRECTORIES = ("agents", "commands", "hooks", "schemas", "scripts", "skills")

#: The other half of a partition over the plugin tree's top level, with why each entry
#: is not compared. A tuple cannot report a directory it does not contain, which is
#: exactly how `schemas/` went uncompared for its whole life -- so the fix for the
#: CLASS is not a longer tuple, it is writing the complement down and checking it:
#: `tests/test_doctor_compared_set_415.py` fails when a tracked top-level entry lands
#: in neither half, so the next `schemas/` reddens the commit that adds it.
#:
#: Deriving the set at runtime instead -- compare everything shipped in the tree -- was
#: weighed and refused. An installed copy legitimately does not ship `tests/` or
#: `changelog.d/`, and every file under a directory present on one side only scores as
#: a difference, so derivation buys a permanent WARN that no release can clear. That
#: is the failure `translation_state`'s docstring describes: a verdict line that always
#: reads `usable with gaps` cannot carry a real finding any more. A listed set with a
#: checked complement gets the coverage without the noise.
NOT_COMPARED_TOP_LEVEL = {
    ".claude": "this repository's own session rule layers; a managed repo's copy is "
               "written by scaffold and is not part of any plugin copy",
    ".claude-plugin": "its plugin.json is compared as a file above; nothing else in "
                      "there is read at runtime",
    ".github": "runs in this repository's CI, never in an install",
    ".gitignore": "a checkout's own bookkeeping, not read at runtime",
    ".oss.json": "the config of whatever repo is being diagnosed, not of a plugin copy",
    ".supertool.json": "op configuration for a checkout, not read from a plugin copy",
    "CHANGELOG.md": "release history; a copy behind the clone is expected to differ and "
                    "the difference decides nothing",
    "CLAUDE.md": "prose for a session in this repository",
    "CODE_OF_CONDUCT.md": "project prose, read by people",
    "LICENSE": "project prose, read by people",
    "README.md": "project prose, read by people",
    "SECURITY.md": "project prose, read by people",
    "bin": "the launcher is copied onto PATH rather than read from the tree, so WHICH "
           "copy of it runs is the `launcher` check's question and not this one",
    "changelog.d": "unreleased fragments, emptied at every fold; a copy at the tag "
                   "holding none of them is the healthy state",
    "docs": "prose for people; nothing dispatches or executes it",
    "pyproject.toml": "test and lint configuration for this checkout",
    "tests": "not shipped by every install and never read at runtime",
}

#: The one compared file whose skew has a named, user-visible consequence. Byte
#: difference is how it is DETECTED; the two declared contract numbers are the fact a
#: reader acts on, which is why the skew line carries them (#415).
SCHEMA_CONTRACT_FILE = "schemas/agent-report.schema.json"

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


def _relative_key(root, path):
    """A relative POSIX key, or the flattened absolute path when it is not under root."""
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return _one_line(str(path), limit=120)


def plugin_tree_digest(root):
    """``({relative posix path: sha256}, {relative posix path: why it could not be read})``.

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
    the walk yields backslashes. The unreadable half is keyed the same way on purpose:
    the caller has to be able to subtract those keys from the comparison, because a
    path present on one side and unreadable on the other is *unknown*, not different,
    and reporting it as a difference is the loud-but-wrong answer this whole check
    exists to avoid.

    A compared directory that is a symlink is declined rather than followed.
    ``os.walk`` refuses symlinked *sub*directories and always traverses the top it was
    given, so ``scripts -> /`` in a tracked repo would be an unbounded read inside a
    diagnostic contracted to always finish. Declining is recorded as unreadable, which
    is what it is: nothing under it was seen.

    **A symlinked file is declined on the same rule (#279), and the top-level decline
    used to be the whole of it.** ``os.walk`` yields a symlinked file as an ordinary
    entry in ``filenames`` and ``read_bytes()`` follows it, so ``agents/leaked.md ->``
    anywhere had that file's bytes folded into the digest while ``unreadable`` stayed
    empty -- a receipt that could not be told from a tree with no symlink in it.

    Declining is chosen over resolving-and-containment-checking, and the two produce
    different digests for the same repository, so it is a decision rather than a detail.
    Resolving keeps a legitimately symlinked file inside the tree measurable; it also
    requires deciding what "inside" means against ``realpath``, which is where the
    platforms stop agreeing -- ``/var`` against ``/private/var``, case folding, short
    names -- and a containment test that is wrong on one leg reads a file outside the
    tree with a receipt saying it did not. Declining needs no such test, matches the
    decline already applied to a symlinked directory so one sentence covers both, and
    fails toward *unknown*. The cost is real and is not hidden: a symlinked file inside
    the tree is not compared, and says so in ``unreadable``.

    Non-regular files are a **separate** refusal, and the one that stopped a release:
    a FIFO inside the tree with no symlink involved blocks in ``open()`` until somebody
    writes to it, so this never returned at all and ``doctor``'s *exit 0 always, one
    VERDICT line* contract was unreachable from a launcher that runs it before every
    session. Both refusals ride on one ``os.lstat``, which neither follows a link nor
    opens anything. That is a guard against a hang and a misread, not a security
    boundary: nothing here defends against a path swapped between the ``lstat`` and the
    read, and a diagnostic is the wrong place to claim it does.
    """
    root = Path(root)
    files = {}
    unreadable = {}

    def onerror(exc):
        if isinstance(exc, FileNotFoundError):
            return
        unreadable[_relative_key(root, getattr(exc, "filename", "?"))] = exc.__class__.__name__

    targets = []
    for name in COMPARED_DIRECTORIES:
        top = root / name
        if os.path.islink(str(top)):
            unreadable[name] = "declined: it is a symlink, so nothing under it was read"
            continue
        for dirpath, dirnames, filenames in os.walk(str(top), onerror=onerror):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIPPED_DIRECTORIES)
            for filename in sorted(filenames):
                targets.append(Path(dirpath) / filename)
    for relative in COMPARED_FILES:
        parts = relative.split("/")
        # The `lstat` below refuses a symlinked leaf, and refuses nothing above it: an
        # ancestor is followed before the leaf is ever stat'ed, so `.claude-plugin ->`
        # elsewhere reads a manifest outside the tree exactly the way the leaf used to
        # (#279). The compared *directories* need no equivalent -- their tops are checked
        # above and `os.walk` declines symlinked subdirectories on its own.
        walked, linked = root, None
        for part in parts[:-1]:
            walked = walked / part
            if os.path.islink(str(walked)):
                linked = _relative_key(root, walked)
                break
        if linked:
            unreadable[relative] = (
                "declined: {} is a symlink, so nothing under it was read".format(linked)
            )
            continue
        targets.append(root.joinpath(*parts))

    for path in targets:
        key = _relative_key(root, path)
        try:
            status = os.lstat(str(path))
        except FileNotFoundError:
            continue
        except OSError as exc:
            unreadable[key] = exc.__class__.__name__
            continue
        if stat.S_ISLNK(status.st_mode):
            unreadable[key] = "declined: it is a symlink, so what it points at was not read"
            continue
        if not stat.S_ISREG(status.st_mode):
            unreadable[key] = (
                "declined: it is not a regular file, so opening it could never return"
            )
            continue
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            continue
        except OSError as exc:
            unreadable[key] = exc.__class__.__name__
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
            "less than the whole tree".format(len(unreadable), _named_few(_detail_list(unreadable)))
    return "{}, content {} over {} file(s){}".format(
        _git_head(root), digest.hexdigest()[:12], len(files), incomplete
    )


def plugin_identity(plugin_root, tree=None):
    """Version plus content digest for the plugin copy at ``plugin_root`` (#418).

    The version alone cannot tell two installs apart: ``.claude-plugin/plugin.json``
    keeps the last RELEASED number for the whole cycle that follows it, so a cache
    directory unpacked mid-cycle from ``main`` and the tag it is named for both read
    the same manifest string while carrying different code. Measured directly by
    #418: a cache directory named ``0.9.0`` declared agent-report contract 5 while
    the ``v0.9.0`` tag it was named for declared contract 4 -- both manifests
    reading "0.9.0", six hours apart.

    The content digest is what actually distinguishes them, built from the same
    ``plugin_tree_digest`` / ``_tree_identity`` pair ``plugin_provenance`` already
    uses to compare two trees -- so a single install now carries the same
    discriminator on its own, without needing a second tree on disk to diff
    against. Returns a string and never raises: the two failure states
    ``_manifest_version`` can return fold into ``"unknown"`` / ``"unreadable"``,
    exactly like ``plugin_version()`` -- so a version-shaped placeholder never
    reads as a version here either.

    ``tree`` is the optional ``(files, unreadable)`` pair ``plugin_tree_digest``
    already returns, for a caller that has just computed one for this same root
    and would otherwise walk and hash the whole plugin tree a second time in the
    same invocation -- ``main()`` is exactly that caller, immediately below,
    computing one digest of ``PLUGIN_ROOT`` and handing it to both this function
    and ``check_plugin_copy``. Omitted, this recomputes it.
    """
    state, version = _manifest_version(plugin_root)
    if state == "read":
        label = version
    elif state == "no-version-field":
        label = "unknown"
    else:
        label = "unreadable"
    files, unreadable = plugin_tree_digest(plugin_root) if tree is None else tree
    return "{}, {}".format(label, _tree_identity(plugin_root, files, unreadable))


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


def _under_blocked(key, blocked):
    """Is `key` inside something nobody could read?

    Prefix matching, not equality: ``os.walk``'s error handler names the DIRECTORY it
    could not enter, and the files under it exist on the other side under their own
    keys. Comparing by equality alone would subtract the directory and then score every
    file beneath it as present-on-one-side-only, which is the same wrong answer one
    level up.
    """
    if key in blocked:
        return True
    return any(key.startswith(entry + "/") for entry in blocked)


def _detail_list(unreadable):
    """``{key: why}`` flattened to sorted ``key (why)`` strings, for printing."""
    return ["{} ({})".format(key, unreadable[key]) for key in sorted(unreadable)]


def _merge_unreadable(left, right):
    """Both sides' unknowns, keyed the same way, with the side named when they differ.

    A key unreadable on both sides is one unknown, not two -- counting it twice would
    make the printed count disagree with the set that was actually subtracted from the
    comparison, and the count is the only thing telling a reader how much of the answer
    is missing.
    """
    merged = dict(left)
    for key, why in right.items():
        if key in merged and merged[key] != why:
            merged[key] = "{} on one side, {} on the other".format(merged[key], why)
        else:
            merged[key] = why
    return merged


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


def declared_contract(root):
    """``(version, why)`` -- exactly one is None. The agent-report contract a copy declares.

    Four ways to have no number, and they are not one: no schema shipped at all, a
    schema that could not be read, one that would not parse, and one that declares no
    ``x-schema-version``. Every one of them is *not established* rather than
    *version 0*, and the sentence below says which.

    The number is extracted by ``report_schema.contract_version`` -- OUR copy's
    function, applied to the other copy's parsed document -- rather than by reaching
    for the key name here. Two spellings of the same field name in two files is how a
    rename becomes a check that confidently reads nothing; and nothing here imports or
    executes the other tree's code, which would be a diagnostic running a stranger.
    """
    relative = SCHEMA_CONTRACT_FILE
    if report_schema is None:  # pragma: no cover - the module sits beside this file
        return None, "report_schema.py could not be imported beside doctor.py"
    # `getattr` rather than a call, because `main` has no outer `except` and this
    # check runs from it: a sibling module that has changed shape would take out
    # `doctor`'s *exit 0 always, one VERDICT line* contract from three frames away,
    # which is #124 exactly. A fifth way to have no number is cheaper than that, and
    # it is a state a reader can act on rather than a traceback.
    extract = getattr(report_schema, "contract_version", None)
    if not callable(extract):
        return None, (
            "the report_schema.py beside doctor.py exposes no contract_version(), so "
            "nothing here can read a declared contract number"
        )
    path = Path(root).joinpath(*relative.split("/"))
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "it ships no {}".format(relative)
    except (OSError, UnicodeDecodeError) as exc:
        return None, "its {} could not be read ({})".format(relative, exc.__class__.__name__)
    try:
        doc = json.loads(raw)
    except ValueError:
        return None, "its {} would not parse".format(relative)
    version = extract(doc)
    if version is None:
        return None, "its {} declares no contract version".format(relative)
    return version, None


def schema_contract_sentence(script_root, project_dir):
    """The sentence carried by a skew line when the agent-report schemas differ.

    "These bytes differ" is the detection. This is the consequence, and it has three
    states rather than two:

    * the numbers differ -- an agent report written against one copy is refused by the
      other, by name, at exit 2. That is the fact the reader acts on.
    * the numbers agree -- something moved that the number does not track: a
      description, an annotation, a comment. The byte skew is still reported (this
      line's subject is which copy answered, and suppressing a real difference to make
      a check quieter trades a loud finding for a silent one), but the line must not
      imply a refusal that will not happen. Nor may it claim the CONTRACTS agree: #221
      is precisely a number that stayed still while the contract moved, so this says
      what the copies DECLARE and says that a declaration is not a measurement.
    * one side named no number -- absent, unreadable, unparseable, or declaring none.
      Not agreement, and not a mismatch. Saying which side and why is the whole of it.
    """
    ours, our_why = declared_contract(script_root)
    theirs, their_why = declared_contract(project_dir)
    if ours is None or theirs is None:
        return (
            " Which agent-report contract each copy implements was not established: "
            "for the copy that answered, {}; for the checkout being diagnosed, {}."
            .format(
                "it declares version {}".format(ours) if our_why is None else our_why,
                "it declares version {}".format(theirs) if their_why is None else their_why,
            )
        )
    if ours == theirs:
        return (
            " Both copies' {} declares contract version {}, so an agent report is not "
            "refused by either on its number -- though that is what they DECLARE, and a "
            "schema can change without its number moving.".format(SCHEMA_CONTRACT_FILE, ours)
        )
    return (
        " The copy that answered declares agent-report contract version {} and the "
        "checkout being diagnosed declares {}, so a report written against one is "
        "UNVALIDATABLE by the other's scripts/report_schema.py, at exit 2.".format(
            ours, theirs
        )
    )


def plugin_provenance(script_root, project_dir, attested=None, attested_source=None,
                       script_tree=None):
    """``[(level, message)]`` -- two lines, and neither may be silent.

    Returns rather than prints, so every state is testable.

    ``script_tree`` is the optional ``(files, unreadable)`` pair from
    ``plugin_tree_digest(script_root)``, for a caller that already computed one
    for this root -- ``main()`` does, for ``plugin_identity`` (#418), and passing
    it here avoids walking and hashing the whole plugin tree a second time in the
    same invocation. Omitted, this recomputes it.
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
    else:
        # Three states, not two (#309). `attested` is a path somebody typed at
        # `--plugin-root` or exported into `CLAUDE_PLUGIN_ROOT`, so a name that is not
        # there is the ordinary failure rather than an exotic one -- and the old
        # comparison rendered it as the mismatch arm below, a sentence about a
        # disagreement between two trees, one of which was never looked at. This is the
        # call site whose third state most needs its own message: "I could not examine
        # what you named" and "you named somewhere else" send a reader to two different
        # places.
        scope, why = compare_directories(attested, script_root)
        if scope is True:
            lines.append(
                (
                    "OK",
                    "plugin copy scope: {} named {}, and that is the tree doctor.py ran "
                    "from. {}".format(attested_source, script_root, SESSION_CAVEAT),
                )
            )
        elif scope is False:
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
        else:
            lines.append(
                (
                    "WARN",
                    "plugin copy scope: {} names {}, and whether that is the tree "
                    "doctor.py ran from ({}) could not be determined -- {}. The tree "
                    "reported below is the one that ran. {}".format(
                        attested_source, Path(attested), script_root, why, SESSION_CAVEAT
                    ),
                )
            )

    ours, our_reason = plugin_manifest(script_root)
    theirs, their_reason = plugin_manifest(project_dir)

    files, unreadable = plugin_tree_digest(script_root) if script_tree is None else script_tree
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

    here, why = compare_directories(script_root, project_dir)
    if here is True:
        lines.append(
            (
                "OK",
                "plugin copy: doctor.py answered from the checkout being diagnosed "
                "({}, {}), so there is no installed-copy/clone split to report "
                "here.".format(script_root, identity),
            )
        )
        return lines
    if here is None:
        # #309's third state, at the site where it is a race rather than an ordinary
        # input: both trees have already had a manifest read out of them by the time
        # this line runs, so the filesystem has answered for both. It still gets a
        # branch, because the fall-through below compares the two trees byte for byte
        # and would report ONE tree read twice as two identical trees -- a confident
        # "no skew" about a comparison that never had two sides. The comparison still
        # runs; what changes is that its result is no longer read as an answer to a
        # question this line could not decide.
        lines.append(
            (
                "WARN",
                "plugin copy: whether doctor.py answered from the checkout being "
                "diagnosed could not be determined -- {} -- so the two trees are "
                "compared below as though they were separate. An identical result "
                "there may be one tree read twice.".format(why),
            )
        )

    their_files, their_unreadable = plugin_tree_digest(project_dir)
    their_identity = _tree_identity(project_dir, their_files, their_unreadable)

    # A path unreadable on either side is UNKNOWN, not different. It is absent from
    # that side's map, so a plain symmetric difference scores it as a file present on
    # one side only and reports two byte-identical trees as a SKEW -- the loud-but-wrong
    # answer, in the check written to avoid exactly that. Subtracted here, and reported
    # separately below, because "we could not look at this one" is its own state.
    blocked = _merge_unreadable(unreadable, their_unreadable)
    every = {
        key for key in (set(files) | set(their_files)) if not _under_blocked(key, blocked)
    }
    differing = sorted(key for key in every if files.get(key) != their_files.get(key))
    version = _version_sentence(ours.get("version"), theirs.get("version"))
    incomplete = ""
    if blocked:
        incomplete = " {} path(s) could not be read ({}), so this did not compare the " \
            "whole tree.".format(len(blocked), _named_few(_detail_list(blocked)))

    # The consequence rides on the detection rather than on a line of its own (#415).
    # A second line would be a second mechanism reporting the same difference, and the
    # one it is about only exists when this one already fired; more to the point, a
    # reader who sees SKEW and no contract sentence would have to know that silence
    # meant "the schemas match" rather than "nobody asked".
    contract = ""
    if SCHEMA_CONTRACT_FILE in differing:
        contract = schema_contract_sentence(script_root, project_dir)

    if differing:
        lines.append(
            (
                "WARN",
                "plugin copy: SKEW -- the copy that answered ({}, {}) and the "
                "checkout being diagnosed ({}, {}) differ in {} of {} compared "
                "file(s): {}. {}{}{}".format(
                    script_root,
                    identity,
                    project_dir,
                    their_identity,
                    len(differing),
                    len(every),
                    _named_few(differing),
                    version,
                    contract,
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
                    _named_few(_detail_list(blocked)),
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


def check_plugin_copy(project_dir, script_root=None, attested=None, attested_source=None,
                       script_tree=None):
    for level, message in plugin_provenance(
        script_root or PLUGIN_ROOT,
        project_dir,
        attested=attested,
        attested_source=attested_source,
        script_tree=script_tree,
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
        if env_value:
            # Three states, not two (#309). `--root` naming a directory that is not
            # there is an ordinary user error -- the FAIL immediately below reports
            # exactly that -- and until #309 this line fired on the same run as well,
            # claiming the flag and the environment named two different trees. They may
            # name one; with neither path stat-able nothing here can tell, and a
            # warning that fires on agreement is the noise a real disagreement gets
            # scrolled past with.
            agree, why = compare_directories(os.path.expanduser(str(env_value)), chosen)
            named = Path(os.path.expanduser(str(env_value)))
            if agree is False:
                findings.append(
                    (
                        "WARN",
                        "--root and CLAUDE_PROJECT_DIR disagree. CLAUDE_PROJECT_DIR "
                        "names {}, --root won, and nothing below is about that other "
                        "tree.".format(named),
                    )
                )
            elif agree is None:
                findings.append(
                    (
                        "WARN",
                        "--root and CLAUDE_PROJECT_DIR could not be compared -- {} -- "
                        "so whether they name one tree is unknown. CLAUDE_PROJECT_DIR "
                        "names {}, --root won, and if those are two trees then nothing "
                        "below is about the other one.".format(why, named),
                    )
                )
        # #363: this is the entry point where the third state is
        # ESTABLISHED, not merely consumed -- `_dir_state` here rather than a
        # bare `.is_dir()`. #341's own reproduction never reaches this line:
        # `is_dir()` on a mode-000 *target* succeeds, since `stat` needs
        # execute permission on the parent, not the target. The scenario
        # here is an unreadable *parent* of `--root`, which is a different,
        # adjacent case -- and reporting it as `FAIL: not a directory` would
        # tell a maintainer to create a tree that may already be there.
        state, detail = _dir_state(chosen)
        if state == "unreadable":
            findings.append(
                (
                    "WARN",
                    "--root {}: could not be checked -- {} -- so whether it is a "
                    "directory is unknown, not confirmed absent. Checks below that "
                    "depend on it report themselves unmeasured.".format(chosen, detail),
                )
            )
        elif state == "absent":
            findings.append(
                (
                    "FAIL",
                    "--root {}: not a directory, so there is nothing here to "
                    "diagnose. Every check below reports itself unmeasured.".format(chosen),
                )
            )
        else:
            # `.git` is a file in a worktree and a directory in a clone, so this asks
            # whether it exists rather than what kind of thing it is.
            try:
                git_here = (chosen / ".git").exists()
            except OSError as exc:
                findings.append(
                    (
                        "WARN",
                        "--root {}: whether .git is here could not be checked -- {} -- "
                        "so whether this is a git repository is unknown.".format(
                            chosen, _one_line(str(exc))
                        ),
                    )
                )
            else:
                if not git_here:
                    findings.append(
                        (
                            "WARN",
                            "--root {}: no .git here, so this is not a git repository or "
                            "its checkout is elsewhere. Findings below may not be about "
                            "the tree you meant.".format(chosen),
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

    # #418: the version alone cannot tell two installs apart -- it stays at the
    # last RELEASED number for the whole cycle that follows a release, so a copy
    # unpacked mid-cycle and the tag it is named for both print it. The content
    # digest from `plugin_identity` rides on the same line, right where a reader
    # (or a report) is most likely to actually see it. Computed once and handed to
    # `check_plugin_copy` below too -- both walk and hash the identical
    # `PLUGIN_ROOT` tree, and a diagnostic meant to run before every session
    # should not do that twice a run.
    own_tree = plugin_tree_digest(PLUGIN_ROOT)
    report("OK", "oss plugin version {}".format(plugin_identity(PLUGIN_ROOT, tree=own_tree)))
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
        project_dir, attested=attested, attested_source=attested_source,
        script_tree=own_tree
    )

    config = check_config(project_dir)

    # #367. Above the three `check_tool` probes deliberately: each of those spawns a
    # subprocess, and the interpreter line is the one that explains what a subprocess
    # costs here. Needs no config -- it is a fact about this process, so it answers on
    # a repo that has never run /oss:setup.
    check_interpreter_environment()

    check_tool("gh", ["gh", "auth", "status"])
    check_tool("supertool", ["supertool", "version"])
    check_tool("git", ["git", "--version"])
    # PATH is not the question the briefs ask. Immediately under the PATH line, because
    # that line is the one a reader takes for this one (#285).
    check_supertool_entry_point(project_dir)
    # A fact about this launcher's own reach, not about the project being
    # diagnosed -- needs no config and runs even when everything else could not be
    # measured. Immediately under the two PATH checks above for the same reason
    # #285 put its own check there: a reader who has just read one PATH-resolution
    # line takes the next one for the same question.
    check_oss_workspace_launcher()

    # Passed through even when the config is None: each of these prints its own
    # "not checked" line, and skipping the call would restore the silence #62 is about.
    found = config is not None
    check_directory("clone", config.get("clone") if found else None, config_found=found)
    check_directory(
        "worktree_root", config.get("worktree_root") if found else None, config_found=found
    )
    check_state_file(project_dir, config)
    check_fragments_readme(project_dir, config)
    # Visible before the tag step rather than at it -- same reason #421 put the
    # merge-call check here.
    check_release_authority(project_dir, config)
    check_statusline(project_dir)
    check_auto_update(project_dir)
    check_ci_enforcement(project_dir, config)
    # A fact about the plugin, not about the project, so it needs no config and runs
    # even when everything else was unmeasurable.
    check_agent_dispatch()
    # Same shape and the same reason: a fact about the plugin, needing no config. Where
    # a defect in the loop's own tooling gets filed is the one board no derivation over
    # the dependencies can produce (#292).
    check_loop_repository()

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
    # Same reason, one layer down: an allowlist rule can exist and the merge
    # can still refuse for want of |force (#421). Needs no config either --
    # both live in supertool's file and this process's environment.
    check_publish_confirm(project_dir)
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
