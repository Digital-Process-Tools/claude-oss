"""``check_memory`` -- moved out of ``scripts/doctor.py`` (#497).

`doctor.py` keeps `main()`, the check registry and the shared contract (exit 0
always, one VERDICT line, `report()` / `unmeasured()`); this module holds one
check, its own private helpers and constants, and nothing else. Every shared
name -- `report`, `unmeasured` -- is reached through `doctor` imported as a
module (`import doctor`), never `from doctor import name`, the same reason
spelled out in full in `scripts/doctor_check_statusline.py`: a name looked up
this way is always the current value in `doctor`'s own namespace, which is
what keeps a test's `monkeypatch.setattr(doctor, ...)` reaching code that used
to be inline in `doctor.py`.

`doctor.py` imports `check_memory` back out of this module immediately after
this docstring's own code is defined, so `doctor.check_memory` keeps
answering exactly as it did before the move -- a pure relocation, not a
rewrite; see #497.
"""

import json
import os
import re
from pathlib import Path

import doctor

MEMORY_DIR = ".remember"
MEMORY_CONFIG_DIR = ".claude/remember"

#: A Windows drive letter followed by a separator ("C:/..." or "C:\...") is an
#: absolute path there just as much as a leading "/" is on POSIX -- #614.
_WINDOWS_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")

#: #210. Separate from identity.md on purpose -- see `check_core_memories` below.
CORE_MEMORIES_NAME = "core-memories.md"

#: A self-review finding: the first version of this matched only `## YYYY-MM-DD`
#: headers, which is this repository's OWN convention and not a format anybody
#: else was ever asked to follow. Checked against three real core-memories.md
#: files in the wild: one uses `## YYYY-MM-DD -- title` headers (this repo's
#: own), one uses `- YYYY-MM-DD: text` bullets, and one uses undated bold
#: paragraphs with no isolated date marker at all. The header-only pattern
#: would have found zero entries in the second file (11 real entries) and
#: reported "created and never filled" about a repo that is actively learning
#: -- the exact false signal this check exists to prevent. Widened to match
#: both observed date-marker shapes; a file using neither still reports
#: honestly (see `check_core_memories`) rather than claiming a count it
#: cannot support.
_ENTRY_HEADER_RE = re.compile(r"^(?:##|-)\s+(\d{4}-\d{2}-\d{2})\b", re.MULTILINE)

#: Markdown heading lines, to tell "nothing here but a title" from "content
#: below the title" without assuming any particular entry format.
_HEADING_ONLY_RE = re.compile(r"^#{1,6}\s*.*$")


def memory_layout(project_dir, home=None):
    """Where the memory plugin keeps its config and its saved sessions.

    Two different places: `config.json` sits in `.claude/remember/` for a LOCAL
    install (the plugin's own code copied into the repo), or is layered across the
    plugin's bundled defaults, a user-global override at `~/.remember/config.json`,
    and a per-project override that lives INSIDE the data dir itself -- and sessions
    go wherever that layered config's `data_dir` names, `.remember` by default.

    identity.md can sit in either the config dir or the data dir, and which one is
    READ depends on the install layout. Measured against the plugin's session-start
    hook: it reads the resolved data dir first, then the data dir's parent, then the
    plugin's own install directory. In a local install the plugin's own directory IS
    `<repo>/.claude/remember/`, so identity there is read -- as the last-resort
    fallback. In a marketplace or dependency install, which is how this plugin
    declares it, the plugin lives outside the repo entirely and
    `<repo>/.claude/remember/identity.md` is never read at all.

    So this function resolves `data_dir` the way the hook does, as far as it safely
    can (#614):

    - `$REMEMBER_DIR`, if the current process already has it -- set by the plugin's
      own scripts while one of them is running, and authoritative when present.
    - `.claude/remember/config.json`'s own `data_dir`, project-local and read first
      regardless of install layout -- unchanged from before #614, and load-bearing:
      `tests/test_dependency_setup.py` measures this against the plugin's own
      session-start hook for a genuine dependency (non-local) install and the file
      IS read there, so this function must not stop reading it.
    - only when that file is absent or carries no `data_dir`, `~/.remember/config.json`
      -- a user-global override this function never read before #614, for the layout
      the issue was filed from: no project-local override at all, storage configured
      purely at the user level.

    What this does NOT do: replicate the plugin's `{slug}` substitution
    (`session_dir_slug` in `lib-slug.sh` -- UTF-8-aware, over-200-character hashing,
    Windows drive-letter folding) or its linked-worktree redirect
    (`_resolve_memory_project_dir`). Reimplementing either is a second copy of
    another plugin's logic that goes stale the moment it changes there and nothing
    here would notice (see CLAUDE.md's `coverage_gate.py` trap). When a `data_dir`
    from either layer names a `{slug}`-keyed external store this function cannot
    resolve the real directory, and says so through its return value rather than
    silently keeping a repo-local default it already knows is wrong.

    Returns `(config_dir, data_dir, unresolved)`. `unresolved` is `None` when
    `data_dir` is believed accurate; otherwise a sentence naming what could not be
    confirmed and why. Callers MUST report that as an unknown, never as an absence:
    checking `data_dir` in that state would ask about a directory this function
    already knows is not the one the plugin reads.
    """
    root = Path(project_dir)
    config_dir = root / MEMORY_CONFIG_DIR
    data_dir = root / MEMORY_DIR

    env_dir = os.environ.get("REMEMBER_DIR")
    if env_dir:
        return config_dir, Path(env_dir), None

    project_cfg = config_dir / "config.json"
    doc, unresolved = _read_config_layer(project_dir, project_cfg)
    if unresolved:
        return config_dir, data_dir, unresolved

    raw = None
    cfg_path = project_cfg
    if isinstance(doc, dict) and doc.get("data_dir"):
        raw = str(doc["data_dir"])
    else:
        # No project-local override. Fall back to the user-global layer -- the one
        # a purely external install (no `.claude/remember/config.json` at all)
        # relies on, and the one this function never read before #614.
        if home is None:
            try:
                home = Path.home()
            except RuntimeError:
                # No HOME/USERPROFILE to resolve, so the user-global layer cannot be
                # checked at all -- unlike settings_candidates in
                # doctor_check_merge_permission.py, which degrades silently because
                # its own caller already lists BOTH scopes and a missing one just
                # narrows the search. Here there is only one remaining candidate
                # (the repo-local default), and it is not known to be right: report
                # unresolved rather than let it read as confirmed.
                return (
                    config_dir,
                    data_dir,
                    "this account's home directory could not be determined, so "
                    "~/.remember/config.json -- the layer a purely external "
                    "install's data_dir would be set in -- could not be checked",
                )
        home_cfg = Path(home) / MEMORY_DIR / "config.json"
        hdoc, unresolved = _read_config_layer(project_dir, home_cfg)
        if unresolved:
            return config_dir, data_dir, unresolved
        if isinstance(hdoc, dict) and hdoc.get("data_dir"):
            raw = str(hdoc["data_dir"])
            cfg_path = home_cfg

    if raw is None:
        return config_dir, data_dir, None

    if "{slug}" in raw:
        return (
            config_dir,
            data_dir,
            "{} sets data_dir to \"{}\", which the plugin expands with a "
            "per-project slug it computes at save time (session_dir_slug in "
            "lib-slug.sh). This check does not reimplement that algorithm, so the "
            "external store's exact location cannot be confirmed here".format(
                _display(project_dir, cfg_path), raw
            ),
        )
    if raw.startswith("~") or raw.startswith("/") or _WINDOWS_ABS_RE.match(raw):
        return config_dir, Path(os.path.expanduser(raw)), None
    return config_dir, root / raw, None


def _read_config_layer(project_dir, cfg_path):
    """One config.json, in the same three states as `_listdir` (#614).

    Returns ``(doc, unresolved)``. ``doc`` is the parsed dict when the file exists
    and parses, or ``None`` when it is simply absent -- the ordinary, expected case
    for a layer nothing wrote. ``unresolved`` is ``None`` on either of those, and a
    sentence when the file is present but could not be read or parsed: that must
    not collapse into "absent", which is what a bare
    ``except (OSError, ValueError): pass`` did before this fix and could not tell
    apart from a config layer nobody configured.
    """
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, "{} could not be read ({})".format(
            _display(project_dir, cfg_path), exc.strerror or exc.__class__.__name__
        )
    except ValueError as exc:
        return None, "{} is not valid JSON ({})".format(_display(project_dir, cfg_path), exc)


def _display(project_dir, path):
    """A path the reader can act on, relative to the repo when it is inside it."""
    try:
        return path.relative_to(Path(project_dir)).as_posix()
    except ValueError:
        return str(path)


def _listdir(directory):
    """One directory's entries, in three states rather than two.

    Returns ``(entries, problem)``. ``problem`` is ``None`` when the listing
    succeeded, ``"absent"`` when the directory is not there, and a sentence when it
    is there and could not be read.

    ``Path.is_dir`` and ``Path.glob`` are both unusable here, and for the same
    reason: each destroys the answer. ``is_dir()`` swallows ``OSError`` and returns
    True for a directory that exists and cannot be entered, and pathlib's glob
    swallows ``PermissionError`` while walking and yields nothing -- so "read it,
    found no identity file" and "could not read it" arrived at the caller
    identically, and the caller then said the first out loud (#284, and the same
    mechanism as #124 one directory over).

    No second question is asked of the filesystem to explain why the first failed:
    the exception already in hand settles it. ``FileNotFoundError`` is absence,
    ``NotADirectoryError`` is a file standing where a directory was expected, and
    anything else is unreadable. ``Path.exists()`` would answer with its own
    swallowed errno list and gets no vote.
    """
    try:
        return sorted(os.listdir(str(directory))), None
    except FileNotFoundError:
        return [], "absent"
    except NotADirectoryError:
        return [], "is a file, not a directory"
    except OSError as exc:
        return [], "could not be read ({})".format(exc.strerror or exc.__class__.__name__)


def _identity_names(entries):
    """identity.md, specifically.

    An earlier version of this accepted core-memories.md too, because two of our own
    repos have no identity.md and the warning was inconvenient -- which is widening a
    check until a real gap disappears. Core memories are what the agent LEARNED;
    identity is who it is, and it is the file injected at session start. They are not
    substitutes.
    """
    return [n for n in entries if n.startswith("identity") and n.endswith(".md")]


def check_memory(project_dir, home=None):
    """Is the memory plugin configured, or merely installed?

    Installed-and-unconfigured is the invisible state: it still runs and still saves.
    What is missing is the identity file, which records who the AGENT is in this repo
    and is injected at session start. Without it the loop still works and starts every
    session as nobody in particular.

    Not scaffolded silently. An identity asserts values and a voice, and writing one
    into somebody else's repository picks a persona they did not choose.

    **Both locations are listed before anything is reported, and that ordering is the
    whole of #284.** This used to return early on ``not store.is_dir()`` with "no memory
    store in this project ... it will create one on first save" -- true, reassuring, and
    unreachable-past. A marketplace install on day one has exactly that shape: nothing
    has saved a session, so there is no data dir, and the installer has put identity.md
    at ``.claude/remember/identity.md`` because that is where it looks like it goes. The
    stray branch below is the one that would have said so, and the early return meant it
    never ran. A check that cannot look must not print what a check that looked and found
    nothing prints.

    Where the file is READ is settled in ``memory_layout``'s docstring, measured against
    the memory plugin's session-start hook. That reasoning stays there, in one copy; what
    the messages below owe is the same conclusion, and the tests are what bind them
    together rather than a second prose copy that drifts.

    A fourth state, on top of the three ``memory_layout`` already returns for a single
    listing (#614): the layered config that decides ``data_dir`` can itself be
    unresolved -- an external store keyed by a ``{slug}`` this check does not compute,
    or a config layer it could not read. Checking ``store`` in that state would report
    on a directory ``memory_layout`` already knows is not the one the plugin reads, so
    it is refused before anything below gets a chance to call it absent.
    """
    config_dir, store, layout_problem = memory_layout(project_dir, home=home)
    if layout_problem:
        doctor.report(
            "WARN",
            "{} -- so whether identity.md is configured is unknown, not absent. "
            "Nothing else in this check can answer while that is unresolved.".format(
                layout_problem
            ),
        )
        return
    # Data dir first, because that is the hook's first choice and the only location
    # read in every layout (see memory_layout).
    store_entries, store_problem = _listdir(store)
    config_entries, config_problem = _listdir(config_dir)
    identity = _identity_names(store_entries)
    if identity:
        doctor.report(
            "OK",
            "memory store configured ({} in {})".format(
                identity[0], _display(project_dir, store)
            ),
        )
        return

    if store_problem not in (None, "absent"):
        # The third state. Everything below this line asserts an absence, and an
        # absence asserted about a directory nobody could read is a finding invented
        # by the tool.
        doctor.report(
            "WARN",
            "{} {} -- so whether an identity.md is configured here is unknown, not "
            "absent. Nothing else in this check can answer while that listing "
            "fails.".format(_display(project_dir, store), store_problem),
        )
        return

    # How the data dir stands, carried into whichever message follows. The old early
    # return was the only thing saying this, and the fix must not buy the branch below
    # by dropping the fact.
    store_state = (
        "{} does not exist yet -- the remember plugin creates it on first save".format(
            _display(project_dir, store)
        )
        if store_problem == "absent"
        else "{} exists and holds no identity.md".format(_display(project_dir, store))
    )

    stray = _identity_names(config_entries)
    if stray:
        # Read only when the plugin is installed INTO the repo, which is what a
        # scripts/ directory beside config.json means. Otherwise the file exists, looks
        # deliberate, and is never injected -- the worst of the three, because every
        # signal says configured. Two of our own repos are in exactly this state.
        #
        # Tested against the listing already in hand rather than with a fresh
        # `is_dir()`, which would ask the filesystem a second question and swallow the
        # error from it.
        if "scripts" in config_entries:
            doctor.report(
                "OK",
                "memory store configured ({} in {}, local install)".format(
                    stray[0], _display(project_dir, config_dir)
                ),
            )
            return
        doctor.report(
            "WARN",
            "{}/{} exists but is never read. The plugin is not installed into this repo, "
            "so the session-start hook resolves identity against {} and the plugin's own "
            "directory -- never this one. It looks configured from every angle except the "
            "one that matters. Move it to {}/identity.md ({}).".format(
                _display(project_dir, config_dir),
                stray[0],
                _display(project_dir, store),
                _display(project_dir, store),
                store_state,
            ),
        )
        return

    if config_problem not in (None, "absent"):
        doctor.report(
            "WARN",
            "no identity.md in {}, and {} {} -- so whether one is sitting there unread "
            "is unknown rather than answered. {}.".format(
                _display(project_dir, store),
                _display(project_dir, config_dir),
                config_problem,
                store_state[0].upper() + store_state[1:],
            ),
        )
        return

    # Name the paths consulted. The previous message named MEMORY_DIR while the lookup
    # read the config dir, so following it to the letter left the warning byte-for-byte
    # unchanged and gave the reader nothing to tell "wrong place" from "wrong content".
    doctor.report(
        "WARN",
        "no identity.md in {} or {} ({}). It records who the AGENT is here -- name, "
        "voice, working style -- and is injected at session start, so without it every "
        "session begins as nobody in particular. Saving still works, which is exactly "
        "what makes the gap invisible. Seed {}/identity.md from the memory plugin's "
        "identity.example.md and edit it -- that directory self-ignores, so the file "
        "cannot be committed by accident, and it is the only location read in every "
        "install layout.".format(
            _display(project_dir, store),
            _display(project_dir, config_dir),
            store_state,
            _display(project_dir, store),
        ),
    )


def _core_memory_summary(text):
    """(entry_count, newest_date) from `core-memories.md`'s own structure -- the
    dated markers it is written in (`## YYYY-MM-DD` headers or `- YYYY-MM-DD:`
    bullets, see `_ENTRY_HEADER_RE`) -- and never the entries' own words.
    `(0, None)` when no dated markers were found, which callers must NOT read
    as "no entries": see `_has_content` for that question instead.
    """
    dates = _ENTRY_HEADER_RE.findall(text)
    return len(dates), (max(dates) if dates else None)


def _has_content(text):
    """Is there anything here besides a markdown title? True/False, structural
    only -- no assumption about entry format, because #210's own review round
    found real core-memories.md files that use no isolated date marker at all
    (undated bold-paragraph entries). A heading-only file (just `# Core
    Memories`, or nothing) is the one state that gets a WARN; anything else
    present is content, whether or not `_core_memory_summary` can parse dates
    out of it.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _HEADING_ONLY_RE.match(stripped):
            continue
        return True
    return False


def check_core_memories(project_dir, home=None):
    """Has anything ever been recorded to `core-memories.md`? A different
    question from `check_memory`'s identity.md, on purpose -- #210 is explicit
    that folding the two together (accepting one as evidence for the other) is
    the mistake `_identity_names` was already fixed not to make, and reverting
    that here would be repeating it one check over.

    `identity.md` says who the agent is; `core-memories.md` says what it has
    been WRONG about -- the corrections that changed how it works in this
    repo. Nothing else checks that the second file exists, is non-empty, or has
    ever been touched.

    Four states:

    - no memory store at all -- `check_memory` already warns about this, so
      this reports OK rather than a second warning about the same absence.
      Doubling it has a real cost in signal: this repo prints "not usable" on
      a green tree once warnings pile up (see `check_memory`'s own docstring).
    - store present, no `core-memories.md` -- OK. Nothing has ever been
      recorded, which is correct and unremarkable for a repo on day one.
      Telling that apart from a repo that has been running for months and has
      simply stopped learning needs a second signal (tick history) this check
      does not have -- named in #210 as "a judgement, not an obvious yes", and
      declined here rather than coupling this check to the state file's own
      shape.
    - present and empty, or header only -- WARN. Something created the file
      and nothing has filled it since.
    - present with content -- OK, reporting the entry count and the newest
      entry's date, never the entries' own words: this is a diagnostic run on
      a maintainer's own machine, not a receipt anyone else reads.

    And the state that is this repository's own defect class pointed at
    itself: a store that cannot be listed, or a `core-memories.md` that exists
    and cannot be read, must render as unknown -- never as "nothing recorded",
    which is the finding this same argument produced for `check_memory`'s
    `_listdir` (see its docstring) and is reused here rather than re-derived.

    Scaffolding is out, for the same reason `check_memory` refuses to seed
    identity.md: core memories are somebody else's agent's corrections. This
    check reports, and never writes.

    A fifth state feeds this from `memory_layout` (#614): the layered config that
    decides `data_dir` can itself be unresolved, and listing whatever fallback
    `store` this function was handed in that state would ask about a directory
    `memory_layout` already knows is wrong, not the store the plugin actually
    reads.
    """
    _, store, layout_problem = memory_layout(project_dir, home=home)
    if layout_problem:
        doctor.report(
            "WARN",
            "{} -- so whether any core memories exist is unknown, not "
            "absent.".format(layout_problem),
        )
        return
    entries, problem = _listdir(store)
    if problem == "absent":
        doctor.report(
            "OK",
            "{} does not exist yet, so there are no core memories to check (see "
            "memory: above)".format(_display(project_dir, store)),
        )
        return
    if problem is not None:
        doctor.report(
            "WARN",
            "{} {} -- so whether any core memories exist is unknown, not absent. "
            "Nothing else in this check can answer while that listing "
            "fails.".format(_display(project_dir, store), problem),
        )
        return
    if CORE_MEMORIES_NAME not in entries:
        doctor.report(
            "OK",
            "no {} in {} yet -- nothing recorded so far. Correct and unremarkable "
            "for a repo on day one; worth a second look if this repo has a long "
            "tick history, which this check has no way to tell.".format(
                CORE_MEMORIES_NAME, _display(project_dir, store)
            ),
        )
        return
    path = store / CORE_MEMORIES_NAME
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        doctor.report(
            "WARN",
            "{} exists but could not be read ({}) -- so whether it holds anything "
            "is unknown, not empty.".format(
                _display(project_dir, path), exc.strerror or exc.__class__.__name__
            ),
        )
        return
    if not _has_content(text):
        doctor.report(
            "WARN",
            "{} exists and holds nothing but a heading -- created and never "
            "filled.".format(_display(project_dir, path)),
        )
        return
    count, newest = _core_memory_summary(text)
    if count == 0:
        # Content is there, but not in either dated-marker shape this check
        # recognises (`## YYYY-MM-DD` headers or `- YYYY-MM-DD:` bullets) --
        # #210's own review round found a real core-memories.md using neither.
        # Report the presence honestly rather than inventing a count.
        doctor.report(
            "OK",
            "core memories: content present in {}, but no `## YYYY-MM-DD` or "
            "`- YYYY-MM-DD:` markers were found to count entries or find the "
            "newest one".format(_display(project_dir, path)),
        )
        return
    doctor.report(
        "OK",
        "core memories: {} entr{} in {}, newest {}".format(
            count, "y" if count == 1 else "ies", _display(project_dir, path), newest
        ),
    )
