"""The per-check module split of `scripts/doctor.py`, derived and declared (#630).

#497 moved a handful of `check_*` functions out of `doctor.py` into their own
`scripts/doctor_check_*.py` modules. #628 then added a whole new check straight
into `doctor.py` twenty minutes before #630 was filed -- and nothing objected,
because completed moves are a batch, not a rule. A comment alone would not have
objected either: this repository has already measured the advice-shaped version
of a rule at zero effect (#490's batching instruction, which had to become a
hook).

So the convention has two halves and this module is the second one:

* the **rule**, stated in the convention block at the top of `scripts/doctor.py`;
* the **ratchet**, here -- `PENDING` and `SHARED` declare every `check_*`
  function still defined inside `doctor.py`, and
  `tests/test_doctor_check_convention_630.py` compares that declaration against
  the file in both directions. A check that is defined and not declared fails,
  which is what #628 would have hit. A check that is declared and no longer
  defined fails too, so the list can only ever shrink.

The ratchet cannot force the extraction and does not pretend to. What it removes
is the silence: adding a check to `doctor.py` now costs a visible line in
`PENDING`, which is a decision somebody can review, instead of nothing at all.

**Nothing here writes down a count.** The module set is read off disk by
`check_modules`, the inline set is parsed out of `doctor.py` by `inline_checks`,
and the header comment states the convention with no tally in it -- which is
#630's own second, smaller instance: that comment opened "#497: five `check_*`
functions moved out" while six modules existed, and nothing noticed.

Every function here answers in three states, never two. A `scripts/` directory
that could not be listed and one holding no modules must not both come back as
an empty list, or every guard built on this passes vacuously -- the defect class
this repository is named after, one layer under the checker that reports it.

Python 3.9 compatible.
"""

import ast
import os
import re
from pathlib import Path

MODULE_PREFIX = "doctor_check_"

#: The bounds of the convention block in `scripts/doctor.py`. Explicit markers
#: rather than "the first comment run after the imports": a block located by
#: shape moves out from under its own guard the first time somebody adds a
#: paragraph above it.
CONVENTION_BEGIN = "# --- the per-check module convention"
CONVENTION_END = "# --- end of the per-check module convention"

#: `check_*` functions that are the report machinery rather than a check of any
#: particular subject: both take what they are checking as an argument and are
#: called several times with different ones. These are not "not moved yet" --
#: they belong beside `report()` and `main()`, and a move would put the shared
#: half of the file in a module named after nothing.
SHARED = (
    "check_tool",
    "check_directory",
)

#: Every remaining `check_*` still defined in `doctor.py`. **This list may only
#: shrink.** Each move deletes its entry in the same change; the test refuses an
#: entry whose function is gone, because a declaration left behind after a move
#: is a licence rather than a record.
#:
#: Adding a name here is the escape hatch, and it is deliberately a visible one:
#: it is the line that says "this check stays in the monolith", which is the
#: sentence #628 never had to write. Write the reason beside it.
#:
#: Which are next: `check_mcp_channel_registration` was the first #630 names, and
#: is gone from this list because it moved to
#: `scripts/doctor_check_mcp_channel_registration.py`.
#: `check_channel_consumer_pin` is the obvious next one -- it sits beside the
#: check that just left -- and was deliberately not taken in the same change,
#: because it reaches a chain of `doctor.py`'s own version-comparison helpers
#: (`active_versions`, `dependency_install_roots`, `_manifest_version`,
#: `compare_versions`) and is worth reviewing on its own terms. After that, the
#: self-contained ones below are the cheapest, because each reaches only
#: `report`/`unmeasured` and its own private helpers.
PENDING = (
    # Config and repo shape.
    "check_config",
    "check_gitignore_hides_config",
    "check_oss_json_committed",
    "check_oss_json_presence",
    "check_state_file",
    "check_freshness",
    # This process, and the binaries it spawns.
    "check_interpreter_environment",
    "check_gh_binary",
    "check_supertool_entry_point",
    "check_oss_workspace_launcher",
    "check_dependency_resolution",
    "check_dependency_diagnostics",
    "check_loop_repository",
    "check_plugin_copy",
    # The watch channel and the radar board.
    "check_watch_channel",
    "check_radar_publish",
    "check_channel_consumer_pin",
    "check_publish_confirm",
    "check_git_push_budget",
    # The rule layers, the release process and the tracker.
    "check_jit_rules",
    "check_jit_layer_readers",
    "check_release_authority",
    "check_ci_enforcement",
    "check_agent_dispatch",
    "check_label_vocabulary",
    # #990, added straight into doctor.py rather than its own module: it is small,
    # self-contained (report/unmeasured and one private read of config), and sits
    # right beside check_release_authority above, which the same reasoning already
    # applies to and which extraction has not reached yet either.
    "check_filed_by_loop",
)

#: A tally of something the filesystem already answers. `modules` and `checks`
#: are the two subjects the header comment has actually got wrong; a bare digit
#: is in the alternation so a numeral is caught as readily as a word.
_COUNTED_RE = re.compile(
    r"\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)"
    r"[ \t]+(`?check_\*`?[ \t]+(?:functions|modules|checks)|modules|checks)\b",
    re.IGNORECASE,
)


def scripts_dir():
    return Path(__file__).resolve().parent


def doctor_path():
    return scripts_dir() / "doctor.py"


def check_modules(directory=None):
    """``(modules, problems)`` -- every `doctor_check_*` module beside `doctor.py`.

    ``problems`` holds one message per reason the answer is incomplete, and it is
    the whole point of returning a pair: a directory that could not be listed
    yields ``([], [why])``, never a bare ``[]`` that a caller would read as "this
    tree has no per-check modules".

    `os.listdir` rather than `Path.glob`, for the reason `manager_docs.documents`
    and `doctor._rglob_md` both record: pathlib's globs swallow `PermissionError`
    while they walk and yield nothing, so an `except OSError` around one can
    never fire for the case it was written for (#124/#383). `listdir` is the call
    that raises.
    """
    directory = scripts_dir() if directory is None else Path(directory)
    try:
        entries = os.listdir(str(directory))
    except (FileNotFoundError, NotADirectoryError) as exc:
        # Absence, stated by the exception in hand. Still a problem rather than
        # an empty answer: no scripts directory means no derivation, not no
        # modules.
        return [], [
            "{} is not a directory that could be listed ({})".format(directory, exc)
        ]
    except (OSError, ValueError) as exc:
        return [], ["{} could not be listed ({})".format(directory, exc)]
    modules = sorted(
        name[: -len(".py")]
        for name in entries
        if name.startswith(MODULE_PREFIX) and name.endswith(".py")
    )
    return modules, []


def inline_checks(source):
    """``(state, value)`` -- the `check_*` functions defined at the top level of
    `doctor.py`'s own source.

    ``("read", [names])`` or ``("could-not-read", detail)``. A re-export --
    `from doctor_check_memory import check_memory` -- is an import, not a
    definition, so a completed move stops counting against the ratchet by
    construction rather than by anybody remembering to delete a line.

    Parsed rather than matched with a regex: `def check_x` inside a docstring or
    a string literal is not a definition, and a false finding here tells an
    author to go and write a module that should not exist.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return "could-not-read", str(exc)
    names = sorted(
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("check_")
    )
    return "read", names


def module_for(check_name):
    """The module a check of this name is expected to live in."""
    return "scripts/{}{}.py".format(MODULE_PREFIX, check_name[len("check_") :])


def convention_state(
    source=None, source_path=None, declared_pending=None, declared_shared=None
):
    """``(state, findings)`` -- ``ok`` / ``findings`` / ``could-not-read``.

    ``could-not-read`` is never folded into ``ok``: a source that would not open
    or would not parse has told us nothing about whether the convention holds,
    and an unread file reporting clean is the failure this module exists to make
    impossible one level down.
    """
    pending = tuple(PENDING if declared_pending is None else declared_pending)
    shared = tuple(SHARED if declared_shared is None else declared_shared)
    if source is None:
        path = doctor_path() if source_path is None else Path(source_path)
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:
            return "could-not-read", ["{} could not be read ({})".format(path, exc)]
    state, value = inline_checks(source)
    if state != "read":
        return "could-not-read", [
            "scripts/doctor.py could not be parsed ({})".format(value)
        ]

    declared = set(pending) | set(shared)
    actual = set(value)
    findings = []
    for name in sorted(actual - declared):
        findings.append(
            "{} is defined in scripts/doctor.py and declared nowhere. A new check "
            "goes in {} -- see the convention block at the top of doctor.py. If it "
            "genuinely belongs inline, add it to SHARED or PENDING in "
            "scripts/doctor_modules.py with the reason, so the choice is a line "
            "somebody can read.".format(name, module_for(name))
        )
    for name in sorted(declared - actual):
        findings.append(
            "{} is declared in scripts/doctor_modules.py and is no longer defined "
            "in scripts/doctor.py. Delete the entry in the change that moved it: "
            "the declared list may only shrink.".format(name)
        )
    return ("findings" if findings else "ok"), findings


def convention_header(source):
    """The convention block out of `doctor.py`'s source, or ``""`` when the
    markers are not both there. An empty string is a finding for the caller, not
    a default: a block that has been deleted and one that was never found have
    to look different to a reader, and the test says which by asserting the
    block is non-empty before it asserts anything about its contents.
    """
    begin = source.find(CONVENTION_BEGIN)
    if begin == -1:
        return ""
    end = source.find(CONVENTION_END, begin)
    if end == -1:
        return ""
    return source[begin:end]


def counted_claims(text):
    """Every written-down tally of something derived from disk, normalised.

    Deliberately narrow. A detector that fired on any digit would fire on `#497`,
    on `Python 3.9` and on every issue reference in the block -- and a check
    wrong that often gets edited away rather than obeyed, which is this
    repository's own argument against the gates it declines to add.
    """
    return [
        " ".join(match.group(0).replace("`", "").split())
        for match in _COUNTED_RE.finditer(text)
    ]
