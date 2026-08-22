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
from pathlib import Path

import doctor

MEMORY_DIR = ".remember"
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


def check_memory(project_dir):
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
    """
    config_dir, store = memory_layout(project_dir)
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
