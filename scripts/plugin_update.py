#!/usr/bin/env python3
"""Keep this plugin and its declared dependencies current, and say what happened (#480, #605).

Claude Code has no plugin auto-update. `autoUpdates` in `~/.claude.json` governs Claude
Code itself, not what is installed alongside it, so a plugin drifts until somebody
remembers two commands:

    claude plugin marketplace update
    claude plugin update <name> --scope user

Nothing ran them, and #289 is what that costs: eight consecutive rounds where the
installed copy on one machine was behind the clone, observed every time and repaired
none of them, because the repair was a person remembering.

**This modifies somebody else's installation without being asked, which nothing else in
this plugin does.** Three things follow from that and are not optional:

* it is **reversible by the person it happens to** -- `OSS_NO_AUTO_UPDATE=1` in the
  environment, or `"auto_update": false` in `.oss.json` or `.oss.local.json`, and it
  never runs again. An opt-out that needs a plugin file edited is not an opt-out,
  because the next update overwrites it;
* it leaves a **receipt** -- what moved, from which version to which, and when. An
  update nobody can see is indistinguishable from one that never ran;
* it **never blocks a session**. The hook forks this module and returns; nothing waits
  on a network call at session start.

Three states in the receipt, and the third is the one that must not be rounded up:
``updated`` (with `from`/`to`, and both remedies: /reload-plugins moves the registry
now, and a restart is still needed before the new code fully runs), ``current``, and
``could-not-check`` -- offline, `claude` not on PATH, a
marketplace that did not resolve. Rendering the third as ``current`` would be this
repository's own defect class pointed at its own updater.

**The subject is the loop plugin AND every name in its manifest's `dependencies` (#605).**
It was the loop plugin alone for as long as this module existed, while `statusline`'s
`plugin_facts` already rendered currency for the whole set -- so the report's subject was
wider than the actor's and nothing said so. Measured instance: `remember` sat at 0.21.0
against a published 0.22.0 through a restart and a `/reload-plugins`, with a green
three-plugin currency line beside it. Each plugin gets its own record in a
``dependencies`` list; a dependency's verdict never becomes the loop plugin's, and the
top-level `state`/`plugin`/`from`/`to` still answer about the loop plugin alone because
every existing reader of this receipt asks them that question. A dependency adds a fourth
state, ``not-installed`` -- see `_update_one` for why it is not a failure.

One level, not transitive: the manifest is the only declaration available here, and a
dependency's own dependencies would have to be read out of its installed copy. That is a
different question and gets filed as one if it turns out to matter.

Python 3.9 compatible.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

#: Where the receipt lives: machine state, never inside a managed repository.
RECEIPT_NAME = "auto-update.json"

#: The environment opt-out. Read as "set to anything non-empty means off".
OPT_OUT_ENV = "OSS_NO_AUTO_UPDATE"

#: Config key, in either half of the config. Absent means on.
OPT_OUT_KEY = "auto_update"

#: A receipt written this recently means a run just happened -- most likely
#: `bin/oss-workspace`'s own synchronous call, moments before this same session's
#: SessionStart hook fires `hooks/session-start-update.sh` (and this module) again
#: in the background (#753). `update()` stands down entirely rather than repeating
#: the marketplace refresh and every per-plugin update for a result that cannot
#: have changed in this short a window.
#:
#: Deliberately well under `statusline.REFRESH_AFTER` (60s, the board cache) and
#: nowhere near `statusline.LATEST_REFRESH_AFTER` (3600s): this answers a narrower
#: question than either -- "did a run already happen a moment ago", not "is this
#: reading current enough to trust" -- and is sized against the doctor diagnostic's
#: own worst-case per-dependency network timeout (25s) plus the channel
#: registration calls ahead of it in the launcher, so a slow diagnostic between the
#: launcher's call and the hook's does not make the hook repeat the check anyway.
DEBOUNCE_SECONDS = 120


def receipt_dir():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "oss-statusline"
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    return Path(base) / "oss-statusline"


def receipt_path():
    return receipt_dir() / RECEIPT_NAME


class ReceiptUnreadable(object):
    """A receipt file exists but could not be parsed (#484).

    Distinct from ``None`` on purpose: ``None`` means nothing was ever written, which is
    the ordinary state before the first SessionStart hook runs. This means something WAS
    written and is now broken -- corrupt JSON, or a permission that changed underneath
    it -- and a caller that folds the two together reports "nothing recorded" about a
    receipt that is sitting right there and cannot be trusted.
    """

    def __init__(self, detail):
        self.detail = detail

    def __repr__(self):
        return "ReceiptUnreadable({!r})".format(self.detail)


def read_receipt(path=None):
    """The last run's receipt, ``None``, or a `ReceiptUnreadable`.

    ``None`` is "no receipt" -- the file was never written, which is not "it did not
    update"; the caller says which. A `ReceiptUnreadable` is the third state: a receipt
    exists and the exception in hand says why it could not be read, told apart from
    absence by the exception that was actually raised rather than by asking the
    filesystem a second question (the trap this repo's own CLAUDE.md names).
    """
    target = Path(path or receipt_path())
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        return ReceiptUnreadable(str(exc))
    try:
        return json.loads(text)
    except ValueError as exc:
        return ReceiptUnreadable(str(exc))


def _confirm_absent(path):
    """True / False / None for "is `path` genuinely not there", after `iterdir()`
    already raised `FileNotFoundError` on it (#548, the local copy of the idea in
    `scripts/doctor.py`'s `_absence_confirmed` -- see `opt_out`'s own docstring for
    why this is a separate small copy rather than a shared import this round).

    True  -- confirmed absent: the deepest ancestor this platform can still list
             does not contain the next path component down.
    False -- the name IS in its parent's own listing, so whatever stopped
             `iterdir()` from reaching it is not "it does not exist".
    None  -- nothing here could confirm either way (an unreadable ancestor, a
             parent that is not a directory at all, or the walk ran out of
             ancestors) -- the caller must not claim absence on this alone.
    """
    try:
        current = os.path.abspath(os.fspath(path))
    except (OSError, ValueError, TypeError):
        return None
    parent = os.path.dirname(current)
    name = os.path.basename(current)
    if not name or parent == current or not parent:
        return None
    try:
        entries = os.listdir(parent)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError:
        return None
    return name not in entries


def opt_out(root=None, env=None):
    """Is auto-update switched off, and by what? ``(status, where)``.

    ``status`` is one of three strings -- never a bool, and never a value that is merely
    falsy where it should be a genuine "I do not know" (#492). ``"off"`` means an opt-out
    was found (environment or config). ``"on"`` means the search completed and found
    none. ``"unknown"`` means a config file exists but could not be read or parsed -- or
    the directory holding it could not even be listed -- so whether it declares an
    opt-out cannot be told, and the caller must not treat that the same as either "on" or
    "off": see `update`'s own handling of this return for why the unresolved case fails
    toward not touching the install.

    The environment wins over config, because it is the switch somebody reaches for when
    a plugin is misbehaving right now, and it needs no file they may not be able to edit.

    Walks upward from ``root`` all the way to the filesystem root, because a machine-wide
    opt-out in a config above every managed repository is a supported spelling (the class
    of location this module's own top docstring names -- "`.oss.json` or `.oss.local.json`"
    -- without scoping it to the project root). A directory that holds a config file which
    does not itself declare the key does **not** stop the search (#534): the nearest
    ancestor is, in an ordinary managed repository, that repo's own `.oss.json`, which
    declares `repo` and nothing about `auto_update` -- stopping there the moment *a* config
    is found, rather than at *a declaration*, made a machine-wide opt-out unreachable in
    exactly the population this walk exists for. Only a declaration ("off" or an explicit
    "on"), an unreadable config ("unknown"), or the filesystem root stops it.

    This deliberately does not delegate to `statusline.repo_root`: that helper decides a
    directory is the repo root by `.oss.json` alone, so a directory carrying only
    `.oss.local.json` (a real, documented opt-out location) would be walked straight past
    and silently answer "on" -- measured on #492's own review round. `Path.is_file()`
    also swallows most `OSError`s but not `PermissionError`, so a locked ancestor
    directory would otherwise crash this walk outright rather than reporting "unknown";
    `iterdir()` is caught explicitly here for that reason.

    `FileNotFoundError` out of `iterdir()` is not, on its own, "nothing is here" (#548).
    CLAUDE.md's own #380 record: Windows folds an over-`MAX_PATH` name onto that exact
    exception, indistinguishable from a candidate that genuinely does not exist -- so
    reading the type alone as the verdict would silently skip PAST a directory that
    declares an opt-out this walk could simply not read, and answer "on" about a repo
    that turned auto-update off. `_confirm_absent` below asks the platform a question
    it cannot fold: whether the candidate's own parent still lists it. See
    `scripts/doctor.py`'s `_dir_state`/`_absence_confirmed` for the same idea against a
    directory-or-not question rather than this walk's "declares nothing, or unlookable"
    one -- not shared as a module here, deliberately: this file and doctor.py are edited
    by different lanes this round, and the two call sites have different callers, return
    shapes and existing tests.
    """
    env = os.environ if env is None else env
    if env.get(OPT_OUT_ENV):
        return "off", "{} in the environment".format(OPT_OUT_ENV)
    if root is None:
        return "on", None
    try:
        start = Path(root).resolve()
    except OSError as exc:
        # Self-review finding on #492: `statusline._normalized_path` guards this exact
        # call with a fallback because `resolve()` can raise on some platforms for a
        # path with a permission problem partway up it -- this walk had the identical
        # call unguarded, so the one situation the rest of this function exists to
        # report as "unknown" could instead crash the caller outright.
        return "unknown", "could not resolve {}: {}".format(root, exc)
    for candidate in [start] + list(start.parents):
        try:
            present = {
                entry.name
                for entry in candidate.iterdir()
                if entry.name in (".oss.json", ".oss.local.json")
            }
        except FileNotFoundError as exc:
            if _confirm_absent(candidate) is True:
                continue
            return "unknown", "could not list {}: {}".format(candidate, exc)
        except OSError as exc:
            return "unknown", "could not list {}: {}".format(candidate, exc)
        if not present:
            continue
        unreadable = []
        declared = False
        off_reason = None
        for name in (".oss.json", ".oss.local.json"):
            if name not in present:
                continue
            path = candidate / name
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, ValueError) as exc:
                unreadable.append("{} ({})".format(path, exc))
                continue
            try:
                document = json.loads(text)
            except ValueError as exc:
                unreadable.append("{} ({})".format(path, exc))
                continue
            if isinstance(document, dict) and OPT_OUT_KEY in document:
                if document.get(OPT_OUT_KEY) is False:
                    # Self-review finding on #534: this used to `return "off"` right
                    # here, before the sibling file in the SAME directory was even
                    # looked at -- so an unreadable `.oss.json` sitting next to a
                    # readable `.oss.local.json` that declares `false` silently lost
                    # the "unreadable" finding, while the symmetric case (an explicit
                    # `true` alongside a broken sibling) already fell through to the
                    # `unreadable` check below correctly. Recording the reason and
                    # continuing the inner loop makes both files in this directory
                    # get read before any verdict is returned, so `unreadable` is
                    # checked first and consistently either way.
                    if off_reason is None:
                        off_reason = '"{}": false in {}'.format(OPT_OUT_KEY, path)
                else:
                    # An explicit non-``False`` declaration (typically ``true``) is
                    # itself a declaration and stops the walk here, same as an
                    # explicit "off" -- #534's fix is "keep walking past a config
                    # that declares nothing", not "keep walking past a config,
                    # period". Only the *absence* of the key continues the search.
                    declared = True
        if unreadable:
            return "unknown", "; ".join(unreadable)
        if off_reason is not None:
            return "off", off_reason
        if declared:
            return "on", None
        # #534: a config directory that declares nothing about the key does not stop the
        # walk. The nearest ancestor is, in every managed repository, that repo's own
        # `.oss.json` -- it declares `repo` and says nothing about `auto_update` -- so
        # stopping here the moment *a* config is found (rather than *a declaration*) made
        # a machine-wide opt-out unreachable in the one population the upward walk was
        # added for. Only a declaration (handled above), an unreadable config (handled
        # above), or the filesystem root (below) stops the search.
        continue
    return "on", None


def plugin_name(plugin_root=None):
    """This plugin's own name, off its own manifest. Never spelled inline."""
    root = Path(plugin_root or Path(__file__).resolve().parent.parent)
    try:
        return json.loads(
            (root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        ).get("name")
    except (OSError, ValueError):
        return None


def declared_dependencies(plugin_root=None):
    """``(names, status)`` -- the plugins this one declares it needs (#605).

    `status` is ``"ok"`` or ``"unreadable"``, and the two must not both arrive as an
    empty list. "This manifest declares no dependencies" is a fact; "the `dependencies`
    key is there and nobody can tell what it says" is the absence this repository is
    named after, and an updater that acted on `[]` in the second case would silently
    narrow itself back to one plugin with nothing reporting that it had.

    Both entry shapes `doctor.declared_dependencies` accepts are accepted here --
    a bare string, or an object carrying a `name` -- because the row a maintainer reads
    and the actor that runs must agree about the set. `tests/
    test_plugin_update_dependencies_605.py` compares the two derivations against the
    shipped manifest rather than a fixture, which is the only comparison that can catch
    them drifting apart.

    An entry that is neither shape, or one whose name is empty, makes the whole list
    unreadable rather than being dropped: a dependency skipped for being malformed is a
    dependency nothing updates, reported as a list that was fully handled.
    """
    root = Path(plugin_root or Path(__file__).resolve().parent.parent)
    try:
        manifest = json.loads(
            (root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return [], "unreadable"
    if not isinstance(manifest, dict):
        return [], "unreadable"
    if "dependencies" not in manifest or manifest["dependencies"] is None:
        return [], "ok"
    raw = manifest["dependencies"]
    if not isinstance(raw, list):
        return [], "unreadable"
    names = []
    for item in raw:
        name = item.get("name") if isinstance(item, dict) else item
        if not isinstance(name, str) or not name:
            return [], "unreadable"
        names.append(name)
    return names, "ok"


def installed_scopes(name, project_root, plugins_root=None):
    """Which scopes this plugin is installed at, FOR THIS PROJECT (#521).

    `claude plugin update <name> --scope user` fails outright with `Plugin "<name>" not
    found` when the plugin lives at another scope -- measured on the author's machine,
    where every `oss` entry is `project`. So the scope is read off the install record
    rather than assumed, and each recorded scope is updated: an install at two scopes is
    two installs, and updating one of them silently leaves the other behind.

    Filtered to entries that apply to `project_root`, the same way `installed_version`
    is (#521's own review round): an un-filtered scan can find a `project`- or
    `local`-scope entry belonging to a *different* project on the machine, attempt
    `claude plugin update <name> --scope <that scope>` against THIS project (where no
    such install exists), and record the resulting failure as `partial_failure` -- a
    scope this project never had, reported as one it silently lost.

    Order matters only for the receipt, which names the newest.
    """
    root = Path(plugins_root or Path(os.path.expanduser("~")) / ".claude" / "plugins")
    try:
        doc = json.loads((root / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    import statusline

    project = (
        statusline._normalized_path(project_root) if project_root is not None else None
    )
    scopes = []
    for plugin_key, entries in (doc.get("plugins") or {}).items():
        if plugin_key.split("@", 1)[0] != name:
            continue
        for entry in entries or []:
            if not statusline._entry_applies(entry, project):
                continue
            scope = entry.get("scope")
            if scope and scope not in scopes:
                scopes.append(scope)
    return scopes


def qualified_name(name, plugins_root=None):
    """`oss@dpt-plugins` where the record carries a marketplace, else the bare name.

    The CLI accepts either, and the qualified form is the unambiguous one when two
    marketplaces ship a plugin under one name.
    """
    root = Path(plugins_root or Path(os.path.expanduser("~")) / ".claude" / "plugins")
    try:
        doc = json.loads((root / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return name
    for plugin_key in doc.get("plugins") or {}:
        if plugin_key.split("@", 1)[0] == name:
            return plugin_key
    return name


def installed_version(name, project_root, plugins_root=None):
    """The version recorded for ``name`` against THIS project, or ``None`` (#521).

    `installed_plugins.json` is one file shared by every project on the machine, and an
    old project's entry is never rewritten when a newer copy is installed elsewhere
    (#479, which fixed reading whichever entry came first -- a version chosen by dict
    order -- by taking the newest recorded *anywhere*). That answers a question nobody
    asks here: it can only ever report a version at or above the one actually installed
    for THIS project, so a project pinned behind a sibling project's newer pin silently
    reported as current (#521). Resolved per project instead, via the same
    `scope`/`projectPath` match `statusline.installed_plugins` uses -- imported rather
    than duplicated, so the two cannot drift apart on what "applies to this project"
    means.

    Two situations both return ``None`` and neither is a version to compare: no entry
    applies to this project, and the install record could not be read. `update`'s
    before/after comparison already treats a `None` on either end as "unknown" rather
    than as a version, which is the correct behaviour for both.
    """
    root = Path(plugins_root or Path(os.path.expanduser("~")) / ".claude" / "plugins")
    try:
        doc = json.loads((root / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    import statusline

    project = (
        statusline._normalized_path(project_root) if project_root is not None else None
    )

    def key(text):
        parts = []
        for chunk in str(text).lstrip("vV").split("."):
            digits = ""
            for char in chunk:
                if not char.isdigit():
                    break
                digits += char
            if not digits:
                return None
            parts.append(int(digits))
        return tuple(parts) if parts else None

    best = None
    for plugin_key, entries in (doc.get("plugins") or {}).items():
        if plugin_key.split("@", 1)[0] != name:
            continue
        for entry in entries or []:
            if not statusline._entry_applies(entry, project):
                continue
            version = entry.get("version")
            if not version or version == "unknown":
                continue
            if best is None or (key(version) or ()) > (key(best) or ()):
                best = version
    return best


def resolved_plugin_root(name, project_root, plugins_root=None):
    """The on-disk directory of the copy actually recorded as installed for THIS
    project (#677) -- as opposed to whatever `${CLAUDE_PLUGIN_ROOT}` a running
    session happens to hold, which is substituted once at command-injection time
    and is a version-pinned path: it can name the copy a session STARTED with, and
    nothing built from it can ever detect that copy going stale.

    Built from ``installed_version`` (the version `installed_plugins.json` records
    for this project) and ``qualified_name`` (which carries the marketplace, e.g.
    ``oss@dpt-plugins``), mirroring the cache layout observed on this machine:
    ``<plugins_root>/cache/<marketplace>/<name>/<version>``. Returns ``None`` --
    never a guessed path -- when any piece of that is unavailable: no version on
    record for this project, no marketplace on record (an unqualified local/dev
    install, which this cache layout does not describe), or the assembled
    directory does not exist. A caller that gets ``None`` back has NOT been told
    "unchanged"; it has been told this route could not resolve, and #677's own
    comment is explicit that route failing to resolve must render as its own
    state, never silently fall back to comparing nothing.
    """
    root = Path(plugins_root or Path(os.path.expanduser("~")) / ".claude" / "plugins")
    version = installed_version(name, project_root, plugins_root)
    if not version:
        return None
    qualified = qualified_name(name, plugins_root)
    if "@" not in qualified:
        return None
    marketplace = qualified.split("@", 1)[1]
    if not marketplace:
        return None
    candidate = root / "cache" / marketplace / name / version
    if not candidate.is_dir():
        return None
    return candidate


def _run(command, timeout=180):
    """``(ok, output)``. A missing binary and a non-zero exit are both `not ok`.

    The first token is resolved via `shutil.which()` before being handed to
    `subprocess.run()`, and the RESOLVED path -- not the bare name -- is what
    actually gets executed. Windows' own process creation (what
    `subprocess.run` uses with `shell=False`, the default here) does not
    perform the PATHEXT search that turns a bare `claude` into `claude.cmd`;
    only `which()` does. Running the bare name through `subprocess.run()`
    unresolved reproduces the exact "could not find claude" failure on
    Windows that a real `claude.cmd` install would otherwise resolve fine --
    the same mismatch found and fixed in
    `doctor_check_mcp_channel_registration.mcp_channel_registration_state`
    and `channel_consumer_census_state` (#753/#810's own Windows CI failure).
    A name that `which()` cannot resolve at all is left as-is, so the
    eventual `OSError` still names the exact string that was tried.
    """
    resolved = shutil.which(command[0]) if command else None
    argv = [resolved] + list(command[1:]) if resolved else list(command)
    try:
        result = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "{}: {}".format(type(exc).__name__, exc)
    return result.returncode == 0, result.stdout.decode("utf-8", "replace").strip()


def _update_one(name, root, plugins_root, runner, scope_fallback):
    """Update one plugin at every scope it is installed at, and say what happened (#605).

    Four states, and the fourth is the one that only exists because the dependencies
    arrived: ``updated`` / ``current`` / ``could-not-check`` / ``not-installed``.

    **`scope_fallback` is the asymmetry between the loop plugin and a dependency, and it
    is deliberate.** `installed_scopes` returns `[]` both when nothing is installed for
    this project and when the install record carries no `scope` field -- the shape most
    of #480's own fixtures use -- so the loop plugin has always fallen back to `["user"]`
    and attempted the update anyway. That is the right trade for the plugin whose own
    hook is running: it is installed by construction, so `[]` is far more likely to mean
    "the record is thin" than "this is not installed".

    It is the wrong trade for a declared dependency, which genuinely may not be installed
    for this project. Falling back there would run `claude plugin update <name> --scope
    user` against a project that has no such install, collect `Plugin "<name>" not found`,
    and record it as `could-not-check` -- a plugin this project never had, reported as one
    it might silently have lost. `not-installed` is the honest answer and it makes no call
    at all; whether a declared dependency *should* be installed is a different question,
    and `doctor.check_install`'s dependency row is what already owns it.

    No `at` and no `plugin`/`name` key: the caller stamps the receipt once for the whole
    run and labels each record, so neither can disagree between the entries.
    """
    before = installed_version(name, root, plugins_root)
    scopes = installed_scopes(name, root, plugins_root)
    if not scopes:
        if not scope_fallback:
            return {
                "state": "not-installed",
                "from": before,
                "to": None,
                "scopes": [],
                "partial_failure": False,
                "detail": "no install record for this plugin applies to this project, so "
                "nothing was updated -- an absence, not a failed update",
            }
        scopes = ["user"]

    target = qualified_name(name, plugins_root)
    failures = []
    for scope in scopes:
        ok, output = runner(["claude", "plugin", "update", target, "--scope", scope])
        if not ok:
            failures.append("{}: {}".format(scope, output[-200:]))
    if len(failures) == len(scopes):
        return {
            "state": "could-not-check",
            "from": before,
            "to": None,
            "scopes": scopes,
            "partial_failure": True,
            "detail": "every update call failed -- {}".format("; ".join(failures)),
        }

    after = installed_version(name, root, plugins_root)

    # A partial failure must reach the receipt without becoming a failed run: one
    # scope succeeding is enough for `updated`/`current` to stand (that is what
    # `test_one_scope_succeeding_is_not_a_failed_run` fixes), but a scope that was
    # silently left behind is the whole thing `installed_scopes`' own docstring warns
    # about, and the receipt is the only record anybody reads. `partial_failure` is a
    # structured field precisely so a reader downstream (`doctor.check_auto_update`)
    # does not have to parse it back out of the free-text `detail` -- #521's own
    # receipt showed `state: current` with the failed scope named only in prose, and
    # the row that prints `state` never looked at `detail` at all (#521).
    partial = ""
    if failures:
        partial = " -- but {} of {} scope(s) failed: {}".format(
            len(failures), len(scopes), "; ".join(failures)
        )

    if before is None or after is None:
        # Either side being unknown is enough: the review round that read this file
        # found the symmetric-only version of this guard still let the asymmetric case
        # -- one read succeeding while the install record went briefly unreadable for
        # the other -- fall through to `current` with a `None` on one end of the
        # receipt, exactly the "nothing was there" vs "could not tell" collapse #484
        # exists to remove. One `None` is one unknown; it needs no partner to be one.
        return {
            "state": "could-not-check",
            "from": before,
            "to": after,
            "scopes": scopes,
            "partial_failure": bool(failures),
            "detail": "the install record could not be read, so the version before and/or "
            "after is unknown{}".format(partial),
        }

    if before and after and before != after:
        return {
            "state": "updated",
            "from": before,
            "to": after,
            "scopes": scopes,
            "partial_failure": bool(failures),
            "detail": "run /reload-plugins to move the registry now; a restart is still "
            "needed before the new version fully runs -- this session is still on "
            "{}{}".format(before, partial),
        }
    return {
        "state": "current",
        "from": before,
        "to": after,
        "scopes": scopes,
        "partial_failure": bool(failures),
        "detail": "already at the newest published version{}".format(partial),
    }


def update(
    root=None,
    plugin_root=None,
    plugins_root=None,
    env=None,
    runner=None,
    now=None,
    receipt=None,
):
    """Refresh the marketplace, update this plugin and its declared dependencies (#605).

    The marketplace refresh comes first and its failure is fatal to the run: without it
    `latest` means whatever it meant the last time anything refreshed, so an update
    against a stale index reports `current` about a version that is not the current one.
    That is the third state wearing the first one's clothes, and it is the whole reason
    the two commands are one function rather than two hook lines. It stays fatal to the
    whole run now that the run covers the dependencies too, and it stays exactly one
    call: one index serves every name in the manifest, so refreshing per plugin would
    scale the network cost with the dependency list for nothing.

    `receipt` is the previous run's document, or ``None`` -- this function never reads
    it off disk itself (#753). Debouncing here on an implicit `read_receipt()` would
    make every EXISTING test in this file, which calls `update()` directly with no
    knowledge of debouncing at all, flaky against whatever this machine's real
    `~/.cache/oss-statusline/auto-update.json` happens to hold. So debouncing is
    opt-in per call: only `main()` reads the real receipt and threads it through,
    which is also the only place a stale caller could double-pay for a check that
    just ran. A `receipt` recorded within `DEBOUNCE_SECONDS` of `now` is returned
    as-is, `debounced` marked `True` and `at` refreshed to this call's `now`, and
    `runner` is never invoked -- no marketplace refresh, no per-plugin update, and
    the opt-out itself is not even re-read, because the answer this debounce stands
    down on already reflects it. A `receipt` with no numeric `at`, or one from the
    future (clock skew), falls through to a real run rather than being read as
    fresh -- this repository's own defect class, landing on its own debounce.
    """
    runner = _run if runner is None else runner
    stamp = time.time() if now is None else now
    if isinstance(receipt, dict):
        at = receipt.get("at")
        if isinstance(at, (int, float)) and 0 <= stamp - at < DEBOUNCE_SECONDS:
            document = dict(receipt)
            # `at` stays PINNED to the last REAL check, never refreshed to this
            # call's `stamp` -- self-review finding on this same change. Refreshing
            # it here made a debounced document, fed back in as the NEXT call's
            # `receipt` (exactly what a caller invoking this every launch does),
            # slide the window forward on every call: `main()` writes this
            # document's `at` back to the receipt file, so a machine opening
            # sessions more often than DEBOUNCE_SECONDS apart would never reach a
            # real check again, forever. Leaving `at` untouched means the window
            # expires DEBOUNCE_SECONDS after the last REAL check regardless of how
            # many debounced calls happened in between.
            document["debounced"] = True
            document["detail"] = (
                "a receipt from {:.0f}s ago is inside the {}s debounce window, so "
                "nothing was re-checked; last result: {}".format(
                    stamp - at, DEBOUNCE_SECONDS, receipt.get("detail", "")
                )
            )
            return document
    status, where = opt_out(root, env)
    if status == "off":
        return {
            "state": "off",
            "at": stamp,
            "detail": "switched off by {}".format(where),
        }
    if status == "unknown":
        # Whether an opt-out was declared could not be told, and the docstring's
        # reversibility promise is the one that must not be risked by a guess: modifying
        # an install nobody can prove consented to it is worse than not modifying one
        # that would have been fine to touch. Reported as `could-not-check`, not `off`
        # and not `current` -- the receipt says nothing was decided, not that it was on
        # or off (#492).
        return {
            "state": "could-not-check",
            "at": stamp,
            "detail": "auto-update opt-out status could not be determined -- {} -- so "
            "nothing was touched until this is resolved".format(where),
        }

    name = plugin_name(plugin_root)
    if not name:
        return {
            "state": "could-not-check",
            "at": stamp,
            "detail": "this plugin's own manifest could not be read, so there is nothing to name",
        }

    dependencies, dependencies_status = declared_dependencies(plugin_root)

    ok, output = runner(["claude", "plugin", "marketplace", "update"])
    if not ok:
        return {
            "state": "could-not-check",
            "at": stamp,
            "plugin": name,
            "from": installed_version(name, root, plugins_root),
            "detail": "the marketplace did not refresh, so `latest` is whatever it "
            "meant last time and no update was attempted: {}".format(output[-400:]),
        }

    # The loop plugin keeps the `or ["user"]` scope fallback and the dependencies do not
    # -- see `_update_one`'s docstring for why the asymmetry is deliberate.
    document = _update_one(name, root, plugins_root, runner, scope_fallback=True)
    document["at"] = stamp
    document["plugin"] = name

    # A dependency's verdict never becomes the loop plugin's, in either direction: the
    # top-level `state`/`plugin`/`from`/`to` above still answer about the loop plugin
    # alone, because every existing reader of this receipt asks them that question. The
    # dependencies are a sibling list, and `doctor.check_auto_update` reports it as its
    # own row -- a failure recorded in a receipt no row reads is #521 with an extra step.
    document["dependencies"] = [
        dict(
            _update_one(dependency, root, plugins_root, runner, scope_fallback=False),
            name=dependency,
        )
        for dependency in dependencies
    ]
    # Absent from an older receipt this key means "nothing looked"; `False` here means
    # the manifest was read and said what it declares. The two must stay distinguishable,
    # which is why this is written even when the list is empty.
    document["dependencies_unreadable"] = dependencies_status == "unreadable"
    return document


def write_receipt(document, path=None):
    path = Path(path or receipt_path())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(document), encoding="utf-8")
        os.replace(str(tmp), str(path))
    except OSError:
        return None
    return path


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = argv[argv.index("--root") + 1] if "--root" in argv else os.getcwd()
    if "--print-resolved-root" in argv:
        # A read, not an update -- deliberately does not call update()/write_receipt()
        # below, which refresh the marketplace and may modify the install. #677 needs
        # only to ask where the currently-installed copy for THIS project lives.
        name = plugin_name()
        if not name:
            sys.stderr.write("could not read this plugin's own name\n")
            return 1
        resolved = resolved_plugin_root(name, root)
        if resolved is None:
            sys.stderr.write(
                "could not resolve the installed root for {!r} against {!r}\n".format(
                    name, root
                )
            )
            return 1
        # `.as_posix()`, not `str()`: this value is consumed by a bash snippet in
        # commands/tick.md (`"$RESOLVED_ROOT/scripts/doctor.py"`) that runs inside
        # Git Bash on Windows, where `str(WindowsPath(...))` prints native
        # backslashes -- concatenating a POSIX-style suffix onto those produces a
        # mixed-separator path. `scripts/doctor.py`'s own `_launcher_remedy` (the
        # "run … inside Git Bash" case) already established this convention for the
        # identical reason; this follows it rather than inventing a second one.
        sys.stdout.write(resolved.as_posix())
        return 0
    # Read once, threaded into `update()` as `receipt=` -- see that function's own
    # docstring for why this is the ONLY place that reads the real receipt for
    # debounce purposes, and why `update()` itself never does (#753). A broken
    # receipt is not a fresh one: `ReceiptUnreadable` means something is there and
    # cannot be trusted, which is the opposite of "a run just happened cleanly", so
    # it is never handed through as though it were a dict.
    prior = read_receipt()
    if isinstance(prior, ReceiptUnreadable):
        prior = None
    document = update(root=root, receipt=prior)
    write_receipt(document)
    if "--print" in argv:
        sys.stdout.write(json.dumps(document, indent=2))
    if "--print-state" in argv:
        # `bin/oss-workspace` calls this synchronously, before deciding which
        # opening prompt to use (#753), and parses the result with a plain shell
        # `read`. ONE line, four tab-separated fields -- state, from, to, detail --
        # with any tab/newline/CR already in each collapsed to a space so none of
        # them can forge an extra field or a second line. `from`/`to` travel
        # separately from `detail` because the launcher's own message for
        # `updated` is NOT `detail` verbatim: `detail` is written for the
        # SessionStart hook's audience ("this session is still on the old copy,
        # run /reload-plugins") and is actively wrong read as a synchronous,
        # pre-exec update -- there is no old session to reload, a fresh one is
        # about to start. The launcher composes its own sentence from the raw
        # versions instead.
        def _flat(value):
            return (
                str(value if value is not None else "")
                .replace("\t", " ")
                .replace("\n", " ")
                .replace("\r", " ")
            )

        sys.stdout.write(
            "{}\t{}\t{}\t{}\n".format(
                _flat(document.get("state")),
                _flat(document.get("from")),
                _flat(document.get("to")),
                _flat(document.get("detail")),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
