#!/usr/bin/env python3
"""One status line for a repository this loop manages (#479).

Claude Code pipes a JSON payload in on stdin once per assistant message and prints
whatever this writes on stdout. That cadence is the whole design constraint: a render
that makes a network call makes one every message, so the forge counts come from a cache
that a detached ``--refresh`` run repopulates, and the render itself only reads files.

**Every field has three states and the third is never rounded up.** A count nobody took
prints `?`, never `0`. A version comparison nobody could make prints `?`, never a tick.
A transcript this process did not read to the bottom cannot say "no tick is armed" -- it
says `?`, because a window that did not reach the top of the file is not a file with
nothing in it. That is the defect class this repository is named after, and a status line
is where it is easiest to commit: the render always produces *something*, so a wrong
answer looks exactly like a right one.

Nothing here is hardcoded about any repository. The forge slug comes from the managed
repo's own ``.oss.json``; the plugin repositories come from each installed plugin's own
manifest, the same derivation ``scripts/doctor.py`` uses and for the same reason.

No third-party imports: this file is vendored into ``.oss/statusline.py`` in repositories
that install nothing to run it.

Python 3.9 compatible.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

#: How much of the transcript tail is scanned for the last ScheduleWakeup. A transcript
#: is append-only and can reach tens of megabytes, and this runs once per message.
DEFAULT_TAIL_BYTES = 2 * 1024 * 1024

#: How old a cached board reading may be before a refresh is forked, in seconds.
REFRESH_AFTER = 300

#: How long a refresh may hold its lock before another render is allowed to retry. A
#: lock that outlives a killed refresher would otherwise freeze the counts forever.
LOCK_STALE_AFTER = 180

RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"


# --------------------------------------------------------------------------- values


def parse_timestamp(text):
    """An ISO-8601 stamp from a transcript record, as epoch seconds, or ``None``.

    ``datetime.fromisoformat`` does not accept a trailing ``Z`` before 3.11 and this
    file runs on 3.9, so the suffix is normalised before parsing rather than after.
    """
    if not text:
        return None
    import datetime

    cleaned = str(text).strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        return datetime.datetime.fromisoformat(cleaned).timestamp()
    except ValueError:
        return None


def _version_tuple(text):
    if not text:
        return None
    cleaned = str(text).strip()
    if cleaned[:1] in ("v", "V"):
        cleaned = cleaned[1:]
    parts = []
    for chunk in cleaned.split("."):
        digits = ""
        for char in chunk:
            if not char.isdigit():
                break
            digits += char
        if digits == "":
            return None
        parts.append(int(digits))
    return tuple(parts) if parts else None


def version_status(installed, latest):
    """Compare an installed version against the latest published one.

    Four states, and two of them are not findings: ``current``, ``behind``, ``ahead``
    (a clone running unreleased work, which is the normal state in this repository's own
    checkout) and ``unknown``. ``unknown`` covers either half of the comparison being
    missing, and it must never render as ``current`` -- nobody asked the forge is not the
    same answer as the forge saying yes.
    """
    mine = _version_tuple(installed)
    theirs = _version_tuple(latest)
    if mine is None or theirs is None:
        state = "unknown"
    elif mine == theirs:
        state = "current"
    elif mine < theirs:
        state = "behind"
    else:
        state = "ahead"
    return {"state": state, "installed": installed, "latest": latest}


# ---------------------------------------------------------------------------- board


def board_from_cache(cache, now=None):
    """Read the two forge counts back out of a cache document.

    Each count is read on its own. A cache written by a refresh where one call answered
    and the other did not is a real state, and collapsing it to "unknown board" throws
    away the half that was measured.
    """
    if not isinstance(cache, dict):
        return {"state": "unknown", "prs": None, "issues": None, "age": None}
    prs = cache.get("prs")
    issues = cache.get("issues")
    prs = prs if isinstance(prs, int) else None
    issues = issues if isinstance(issues, int) else None
    fetched = cache.get("fetched_at")
    age = None
    if isinstance(fetched, (int, float)):
        age = max(0.0, (time.time() if now is None else now) - fetched)
    if prs is None and issues is None:
        state = "unknown"
    elif prs is None or issues is None:
        state = "partial"
    else:
        state = "measured"
    return {"state": state, "prs": prs, "issues": issues, "age": age}


def cache_dir():
    """Where the cached board lives -- outside the managed repository, always.

    A status line must not write into somebody's tree. `.oss/` is ours and would be a
    candidate, but a cache file is machine state rather than repository content, and it
    would arrive in `git status` on every clone.
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "oss-statusline"
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "oss-statusline"


def cache_path(repo):
    slug = "".join(char if char.isalnum() else "-" for char in (repo or "unknown"))
    return cache_dir() / (slug + ".json")


def read_cache(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------------ next tick


def _wakeup_input(record):
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("name") == "ScheduleWakeup" and isinstance(block.get("input"), dict):
            return block["input"]
    return None


def _tail_lines(path, max_bytes):
    """The last ``max_bytes`` of a file as whole lines, plus whether anything was cut.

    The truncation flag is the load-bearing return value. Without it a wakeup armed
    above the window is indistinguishable from no wakeup at all, and the status line
    would confidently report an unarmed loop.
    """
    size = os.path.getsize(path)
    truncated = size > max_bytes
    with open(path, "rb") as handle:
        if truncated:
            handle.seek(size - max_bytes)
            handle.readline()  # discard the partial line the seek landed inside
        return handle.read().splitlines(), truncated


def next_tick(transcript_path, now=None, max_bytes=DEFAULT_TAIL_BYTES):
    """When the next tick fires, from the last ScheduleWakeup in the transcript.

    Five states: ``armed`` (seconds left), ``due`` (its time has passed and nothing has
    fired yet, which is worth seeing), ``stopped`` (the loop was stopped deliberately),
    ``none`` (the whole file was read and holds no wakeup), and ``unknown`` -- no
    transcript, an unreadable one, or a tail scan that did not reach the top of the file.
    """
    now = time.time() if now is None else now
    if not transcript_path:
        return {"state": "unknown", "detail": "no transcript path in the payload"}
    try:
        lines, truncated = _tail_lines(transcript_path, max_bytes)
    except OSError as exc:
        return {"state": "unknown", "detail": "transcript unreadable: {}".format(exc)}

    found = None
    for raw in lines:
        if b"ScheduleWakeup" not in raw:
            continue
        try:
            record = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        payload = _wakeup_input(record)
        if payload is not None:
            found = (record, payload)

    if found is None:
        if truncated:
            return {
                "state": "unknown",
                "detail": "only the last {} bytes were scanned".format(max_bytes),
            }
        return {"state": "none", "detail": "no wakeup in this transcript"}

    record, payload = found
    if payload.get("stop"):
        return {"state": "stopped", "detail": "the loop was stopped"}
    delay = payload.get("delaySeconds")
    stamp = parse_timestamp(record.get("timestamp"))
    if not isinstance(delay, (int, float)) or stamp is None:
        return {"state": "unknown", "detail": "the wakeup carried no readable delay"}
    seconds = stamp + delay - now
    state = "armed" if seconds > 0 else "due"
    return {"state": state, "seconds": seconds, "reason": payload.get("reason")}


# --------------------------------------------------------------------------- render


def _symbols(ascii_only):
    if ascii_only:
        return {"sep": " | ", "dot": " . ", "current": "", "behind": ">", "ahead": "+"}
    return {
        "sep": " | ",
        "dot": " · ",
        "current": " ✓",
        "behind": " ⇡",
        "ahead": " ↑",
    }


def _duration(seconds):
    seconds = int(abs(seconds))
    if seconds < 90:
        return "{}s".format(seconds)
    minutes = seconds // 60
    if minutes < 90:
        return "{}m".format(minutes)
    return "{}h{:02d}".format(minutes // 60, minutes % 60)


def _tick_field(tick):
    state = (tick or {}).get("state")
    if state == "armed":
        return "tick " + _duration(tick.get("seconds") or 0)
    if state == "due":
        return "tick due"
    if state == "stopped":
        return "tick off"
    if state == "none":
        return "tick -"
    return "tick ?"


def _board_field(board, symbols):
    prs = board.get("prs")
    issues = board.get("issues")
    return "{}PR{}{}IS".format(
        "?" if prs is None else prs,
        symbols["dot"],
        "?" if issues is None else issues,
    )


def _short_version(text):
    """`v0.11.0` and `0.11.0` are the same version, and a status line has one column.

    A release tag carries the prefix and a manifest does not, so the raw pair renders as
    `0.9.0 -> v0.11.0` -- two spellings of one thing, in the field whose whole job is to
    make a difference obvious.
    """
    if not text:
        return None
    text = str(text).strip()
    return text[1:] if text[:1] in ("v", "V") else text


def _short_name(name):
    """A plugin name at status-line width, by rule rather than by table.

    A leading `claude-` says which ecosystem the plugin is in, which is not news on a
    line about this ecosystem, so it goes. What is left is capped at four characters --
    enough to tell the installed set apart, and derived, so a plugin nobody has written
    yet gets a label without anybody adding a row here. A per-name map would be the
    per-repo fact this codebase keeps out of shared code, and it would be wrong the
    first time a plugin is renamed.
    """
    text = str(name or "")
    if text.startswith("claude-"):
        text = text[len("claude-"):]
    # Trimmed after the cut, not before it: a four-character cap lands mid-word as
    # often as not, and `jit-` reads as a truncation artefact rather than as a name.
    return text[:4].rstrip("-_.") or "?"


def _plugin_field(name, status, symbols, color):
    name = _short_name(name)
    installed = _short_version(status.get("installed")) or "?"
    state = status.get("state")
    if state == "behind":
        marker = symbols["behind"] + (_short_version(status.get("latest")) or "?")
        if color:
            marker = YELLOW + marker + RESET
    elif state == "current":
        marker = symbols["current"]
    elif state == "ahead":
        marker = symbols["ahead"]
    else:
        marker = "?"
    return "{} {}{}".format(name, installed, marker)


def render(facts, ascii_only=False, color=False):
    """The whole line, from facts already gathered. No I/O, so it is testable.

    Colour is off by default because every assertion about this line is a string
    comparison; ``main`` turns it on.
    """
    symbols = _symbols(ascii_only)
    percent = facts.get("percent")
    if percent is None:
        context = "ctx ?"
    else:
        context = "{}%".format(int(percent))
        if color:
            shade = RED if percent >= 80 else YELLOW if percent >= 50 else GREEN
            context = shade + context + RESET
    blocks = ["{}{}{}".format(facts.get("model") or "?", symbols["dot"], context)]

    where = [facts.get("repo_name") or "?", facts.get("branch") or "?"]
    if facts.get("version"):
        where.append("v" + str(facts["version"]))
    blocks.append(" ".join(where))

    blocks.append(_board_field(facts.get("board") or {}, symbols))
    blocks.append(_tick_field(facts.get("tick")))

    plugins = [
        _plugin_field(name, status, symbols, color)
        for name, status in (facts.get("plugins") or [])
    ]
    if plugins:
        blocks.append(symbols["dot"].join(plugins))
    return symbols["sep"].join(blocks)


# ------------------------------------------------------------------------ gathering


def repo_root(start):
    path = Path(start).resolve()
    for candidate in [path] + list(path.parents):
        if (candidate / ".oss.json").is_file():
            return candidate
    return None


def repo_config(root):
    try:
        return json.loads((Path(root) / ".oss.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def repo_version(root):
    """The version this clone declares, or ``None``.

    The plugin manifest first, then the newest tag. Both are read rather than assumed,
    and a repo that states neither reports nothing rather than a guess.
    """
    manifest = Path(root) / ".claude-plugin" / "plugin.json"
    try:
        version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
        if version:
            return version
    except (OSError, ValueError):
        pass
    return _run(["git", "-C", str(root), "describe", "--tags", "--abbrev=0"]) or None


def branch_name(root):
    return _run(["git", "-C", str(root), "branch", "--show-current"]) or None


def _run(command, timeout=5):
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace").strip()


def plugins_root():
    return Path(os.path.expanduser("~")) / ".claude" / "plugins"


def installed_plugins(root=None):
    """``{plugin name: {"version": ..., "repository": ...}}`` from the installed set.

    Derived from each plugin's own installed manifest rather than from a name-to-repo
    table here: a hardcoded map is a per-repo fact in shared code and is wrong the first
    time a plugin moves. Same derivation ``doctor.dependency_repositories`` uses.
    """
    root = plugins_root() if root is None else Path(root)
    try:
        doc = json.loads((root / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    found = {}
    for key, entries in (doc.get("plugins") or {}).items():
        name = key.split("@", 1)[0]
        for entry in entries or []:
            record = found.setdefault(name, {"version": None, "repository": None})
            # One plugin has many entries -- one per scope and one per project that
            # ever installed it -- and they carry different versions, because an old
            # project entry is never rewritten when a newer copy is installed
            # elsewhere. Measured on this machine: `oss` had 0.1.0, 0.5.0, 0.9.0 and
            # 0.10.0 all recorded at once. Taking whichever came last reports a version
            # chosen by dict order, which read as "a release behind" against a machine
            # that had the current one. The newest recorded version is the one this
            # session can actually resolve, so that is the answer.
            version = entry.get("version")
            if version and version != "unknown":
                current = _version_tuple(record["version"])
                incoming = _version_tuple(version)
                if current is None or (incoming is not None and incoming > current):
                    record["version"] = version
            install_path = entry.get("installPath")
            if install_path and not record["repository"]:
                try:
                    manifest = json.loads(
                        (Path(install_path) / ".claude-plugin" / "plugin.json").read_text(
                            encoding="utf-8"
                        )
                    )
                except (OSError, ValueError):
                    continue
                record["repository"] = manifest.get("repository")
                record["dependencies"] = manifest.get("dependencies") or []
    return found


def repo_from_url(url):
    if not url:
        return None
    text = str(url).rstrip("/")
    if text.endswith(".git"):
        text = text[:-4]
    parts = text.split("/")
    if len(parts) < 2:
        return None
    return "/".join(parts[-2:])


def plugin_facts(loop_name, installed, latest_by_repo):
    """The loop's own plugin and every dependency it declares, rendered alike.

    All of them, always, in one shape -- the set comes from the loop plugin's own
    manifest, so nothing here names a plugin and a new dependency arrives on the line
    without an edit. An earlier version showed only the ones that were not current,
    which reads well and is the wrong trade for this field: a plugin that is absent
    because it is fine and a plugin that is absent because nothing looked at it render
    identically, and only the second is a problem. Shown uniformly, the marker carries
    the difference -- current, behind (in the colour that means *update this*), ahead,
    or `?` for a comparison nobody could make.
    """
    mine = installed.get(loop_name) or {}

    def status_for(name):
        record = installed.get(name) or {}
        return version_status(
            record.get("version"), latest_by_repo.get(repo_from_url(record.get("repository")))
        )

    facts = [(loop_name, status_for(loop_name))]
    for name in mine.get("dependencies") or []:
        facts.append((name, status_for(name)))
    return facts


# ------------------------------------------------------------------------- refresh


def _gh_count(repo, kind):
    """One exact count, read off the search API's own `total_count`.

    The alternative -- walking every page of results and counting rows client-side --
    runs its filter once per page and prints one number per page with no total, so
    whoever reads the first line gets a number smaller than the truth, correctly
    formatted, at exit 0. One call and one field cannot fail that way.
    """
    query = "repo:{} is:{} is:open".format(repo, kind)
    out = _run(
        [
            "gh",
            "api",
            "-X",
            "GET",
            "search/issues",
            "-f",
            "q=" + query,
            "-f",
            "per_page=1",
            "--jq",
            ".total_count",
        ],
        timeout=25,
    )
    try:
        return int(out)
    except (TypeError, ValueError):
        return None


def _latest_release(repo):
    if not repo:
        return None
    return (
        _run(
            ["gh", "api", "repos/{}/releases/latest".format(repo), "--jq", ".tag_name"],
            timeout=25,
        )
        or None
    )


def refresh(root):
    """Fill the cache for one managed repository. Runs detached, never on the render path."""
    root = Path(root)
    config = repo_config(root)
    repo = config.get("repo")
    document = {"fetched_at": time.time(), "repo": repo}
    if repo:
        document["prs"] = _gh_count(repo, "pr")
        document["issues"] = _gh_count(repo, "issue")
    latest = {}
    for record in installed_plugins().values():
        slug = repo_from_url(record.get("repository"))
        if slug and slug not in latest:
            tag = _latest_release(slug)
            if tag:
                latest[slug] = tag
    document["latest"] = latest
    path = cache_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(document), encoding="utf-8")
    os.replace(str(tmp), str(path))
    return document


def _lock_path(repo):
    return cache_path(repo).with_suffix(".lock")


def _fork_refresh(root, repo):
    """Start a detached refresh, at most one at a time.

    The lock carries a timestamp rather than being a directory: a refresher killed
    mid-run must not freeze the counts forever, so a stale lock is simply overwritten.
    """
    lock = _lock_path(repo)
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        if lock.exists() and time.time() - lock.stat().st_mtime < LOCK_STALE_AFTER:
            return
        lock.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        return
    try:
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--refresh", "--root", str(root)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------------------- main


def gather(payload, root, now=None):
    now = time.time() if now is None else now
    config = repo_config(root)
    cache = read_cache(cache_path(config.get("repo")))
    board = board_from_cache(cache, now=now)
    if board["age"] is None or board["age"] > REFRESH_AFTER:
        _fork_refresh(root, config.get("repo"))
    latest = (cache or {}).get("latest") or {}
    loop_name = os.environ.get("OSS_STATUSLINE_PLUGIN", "oss")
    return {
        "model": ((payload.get("model") or {}).get("display_name") or "").split(" ")[0] or None,
        "percent": (payload.get("context_window") or {}).get("used_percentage"),
        "repo_name": Path(root).name,
        "branch": branch_name(root),
        "version": repo_version(root),
        "board": board,
        "tick": next_tick(payload.get("transcript_path"), now=now),
        "plugins": plugin_facts(loop_name, installed_plugins(), latest),
    }


def _ascii_only(stream):
    """Does this console's encoding survive the symbols? Measured, not assumed.

    On Windows stdout carries the console codepage rather than the source encoding, so
    an arrow raises ``UnicodeEncodeError`` at the ``print`` -- after the work it was
    reporting already happened. Rather than table the platforms, encode a sample and look.
    """
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        "·✓⇡↑".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return True
    return False


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--refresh" in argv:
        root = "."
        if "--root" in argv:
            root = argv[argv.index("--root") + 1]
        refresh(root)
        try:
            _lock_path(repo_config(root).get("repo")).unlink()
        except OSError:
            pass
        return 0

    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}
    start = (payload.get("workspace") or {}).get("current_dir") or os.getcwd()
    root = repo_root(start)
    if root is None:
        # Not a repository this loop manages. Say the little that is true rather than
        # rendering an OSS board about a repo that has none.
        model = ((payload.get("model") or {}).get("display_name") or "?").split(" ")[0]
        percent = (payload.get("context_window") or {}).get("used_percentage")
        sys.stdout.write(
            "{} {}".format(model, "?" if percent is None else "{}%".format(int(percent)))
        )
        return 0
    line = render(gather(payload, root), ascii_only=_ascii_only(sys.stdout), color=True)
    sys.stdout.write(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
