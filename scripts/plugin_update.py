#!/usr/bin/env python3
"""Keep this plugin's installation current, and say what happened (#480).

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
``updated`` (with `from`/`to`, and the fact that a restart is needed before the new code
runs), ``current``, and ``could-not-check`` -- offline, `claude` not on PATH, a
marketplace that did not resolve. Rendering the third as ``current`` would be this
repository's own defect class pointed at its own updater.

Python 3.9 compatible.
"""

import json
import os
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


def receipt_dir():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "oss-statusline"
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
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


def opt_out(root=None, env=None):
    """Is auto-update switched off, and by what? ``(status, where)``.

    ``status`` is one of three strings -- never a bool, and never a value that is merely
    falsy where it should be a genuine "I do not know" (#492). ``"off"`` means an opt-out
    was found (environment or config). ``"on"`` means the search completed and found
    none. ``"unknown"`` means a config file exists but could not be read or parsed, so
    whether it declares an opt-out cannot be told -- and the caller must not treat that
    the same as either "on" or "off": see `update`'s own handling of this return for why
    the unresolved case fails toward not touching the install.

    The environment wins over config, because it is the switch somebody reaches for when
    a plugin is misbehaving right now, and it needs no file they may not be able to edit.

    Walks upward from ``root`` the same way `statusline.repo_root` does, rather than
    reading only ``root`` itself -- called from a subdirectory, the un-walked read found
    nothing below the repo's own `.oss.json` and answered "on" about a repo that opted
    out at its root.
    """
    env = os.environ if env is None else env
    if env.get(OPT_OUT_ENV):
        return "off", "{} in the environment".format(OPT_OUT_ENV)
    if root is None:
        return "on", None
    import statusline

    found_root = statusline.repo_root(root)
    if found_root is None:
        return "on", None
    unreadable = []
    for name in (".oss.json", ".oss.local.json"):
        path = Path(found_root) / name
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except OSError as exc:
            unreadable.append("{} ({})".format(name, exc))
            continue
        try:
            document = json.loads(text)
        except ValueError as exc:
            unreadable.append("{} ({})".format(name, exc))
            continue
        if isinstance(document, dict) and document.get(OPT_OUT_KEY) is False:
            return "off", '"{}": false in {}'.format(OPT_OUT_KEY, name)
    if unreadable:
        return "unknown", "; ".join(unreadable)
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


def installed_scopes(name, plugins_root=None):
    """Which scopes this plugin is installed at, newest-version first.

    `claude plugin update <name> --scope user` fails outright with `Plugin "<name>" not
    found` when the plugin lives at another scope -- measured on the author's machine,
    where every `oss` entry is `project`. So the scope is read off the install record
    rather than assumed, and each recorded scope is updated: an install at two scopes is
    two installs, and updating one of them silently leaves the other behind.

    Order matters only for the receipt, which names the newest.
    """
    root = Path(plugins_root or Path(os.path.expanduser("~")) / ".claude" / "plugins")
    try:
        doc = json.loads((root / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    scopes = []
    for plugin_key, entries in (doc.get("plugins") or {}).items():
        if plugin_key.split("@", 1)[0] != name:
            continue
        for entry in entries or []:
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
    for plugin_key in (doc.get("plugins") or {}):
        if plugin_key.split("@", 1)[0] == name:
            return plugin_key
    return name


def installed_version(name, plugins_root=None):
    """The newest version recorded for ``name``, or ``None``.

    Newest rather than first: one plugin has an entry per scope and per project, and
    those entries hold different versions -- reading whichever came first reports a
    version chosen by dict order (#479).
    """
    root = Path(plugins_root or Path(os.path.expanduser("~")) / ".claude" / "plugins")
    try:
        doc = json.loads((root / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

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
            version = entry.get("version")
            if not version or version == "unknown":
                continue
            if best is None or (key(version) or ()) > (key(best) or ()):
                best = version
    return best


def _run(command, timeout=180):
    """``(ok, output)``. A missing binary and a non-zero exit are both `not ok`."""
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "{}: {}".format(type(exc).__name__, exc)
    return result.returncode == 0, result.stdout.decode("utf-8", "replace").strip()


def update(root=None, plugin_root=None, plugins_root=None, env=None, runner=None):
    """Refresh the marketplace, update this plugin, and return the receipt.

    The marketplace refresh comes first and its failure is fatal to the run: without it
    `latest` means whatever it meant the last time anything refreshed, so an update
    against a stale index reports `current` about a version that is not the current one.
    That is the third state wearing the first one's clothes, and it is the whole reason
    the two commands are one function rather than two hook lines.
    """
    runner = _run if runner is None else runner
    stamp = time.time()
    status, where = opt_out(root, env)
    if status == "off":
        return {"state": "off", "at": stamp, "detail": "switched off by {}".format(where)}
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

    before = installed_version(name, plugins_root)
    ok, output = runner(["claude", "plugin", "marketplace", "update"])
    if not ok:
        return {
            "state": "could-not-check",
            "at": stamp,
            "plugin": name,
            "from": before,
            "detail": "the marketplace did not refresh, so `latest` is whatever it "
            "meant last time and no update was attempted: {}".format(output[-400:]),
        }

    scopes = installed_scopes(name, plugins_root) or ["user"]
    target = qualified_name(name, plugins_root)
    failures = []
    for scope in scopes:
        ok, output = runner(["claude", "plugin", "update", target, "--scope", scope])
        if not ok:
            failures.append("{}: {}".format(scope, output[-200:]))
    if len(failures) == len(scopes):
        return {
            "state": "could-not-check",
            "at": stamp,
            "plugin": name,
            "from": before,
            "scopes": scopes,
            "detail": "every update call failed -- {}".format("; ".join(failures)),
        }

    after = installed_version(name, plugins_root)

    # A partial failure must reach the receipt without becoming a failed run: one
    # scope succeeding is enough for `updated`/`current` to stand (that is what
    # `test_one_scope_succeeding_is_not_a_failed_run` fixes), but a scope that was
    # silently left behind is the whole thing `installed_scopes`' own docstring warns
    # about, and the receipt is the only record anybody reads.
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
            "at": stamp,
            "plugin": name,
            "from": before,
            "to": after,
            "scopes": scopes,
            "detail": "the install record could not be read, so the version before and/or "
            "after is unknown{}".format(partial),
        }

    if before and after and before != after:
        return {
            "state": "updated",
            "at": stamp,
            "plugin": name,
            "from": before,
            "to": after,
            "detail": "restart Claude Code before the new version runs -- this session "
            "is still on {}{}".format(before, partial),
        }
    return {
        "state": "current",
        "at": stamp,
        "plugin": name,
        "from": before,
        "to": after,
        "detail": "already at the newest published version{}".format(partial),
    }


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
    document = update(root=root)
    write_receipt(document)
    if "--print" in argv:
        sys.stdout.write(json.dumps(document, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
