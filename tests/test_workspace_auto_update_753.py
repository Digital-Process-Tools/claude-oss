"""#753 -- an auto-update that lands mid-session is invisible until somebody
happens to run /oss:doctor. `bin/oss-workspace` now shells out to the REAL
`scripts/plugin_update.py` synchronously, before deciding which opening prompt
to use, so a session's own registry is current before it starts working and
there is no reload/restart window to be silent about.

Every test drives the REAL launcher against the REAL plugin_update.py module,
via `tests/test_workspace_launcher.py`'s `run()`, with a `claude` stub whose
`plugin update ...` call (#753's own `_update_one`) rewrites
`installed_plugins.json`'s recorded version for this project -- simulating what
a real update does, so `update()`'s own before/after comparison sees a genuine
version change rather than a no-op.

`tests/test_plugin_update_debounce_753.py` already covers the debounce and
`--print-state` format directly; this file is about the LAUNCHER's own wiring:
does an `updated` receipt actually override the opening prompt, does
`could-not-check` leave the ordinary prompt in place while saying so, and does
`OSS_NO_AUTO_UPDATE=1` (the pre-existing opt-out) make this whole path a no-op.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))

from test_workspace_launcher import (  # noqa: E402
    BASH,
    LAUNCHER,
    _executable,
    _repo,
    _require_git,
    _require_shell,
)


def _plugin_update_stub_claude(
    bindir,
    argv_log,
    registry_path,
    project_path,
    before,
    after,
    marketplace_exit=0,
    update_exit=0,
):
    """A `claude` whose `plugin marketplace update` and `plugin update oss ...`
    calls actually rewrite `installed_plugins.json`'s recorded version for THIS
    project -- the same file `installed_scopes`/`installed_version` read -- so
    the REAL `update()` sees a genuine before/after change rather than comparing
    a file nothing touched. `mcp` calls fall through to the ordinary "not
    registered" answer: none of these tests care about the channel.
    """
    updater = bindir / "bump_version.py"
    updater.write_text(
        "import json, sys\n"
        "path, project, version = sys.argv[1], sys.argv[2], sys.argv[3]\n"
        "doc = json.load(open(path, encoding='utf-8'))\n"
        "for entries in doc.get('plugins', {}).values():\n"
        "    for entry in entries:\n"
        "        if entry.get('projectPath') == project:\n"
        "            entry['version'] = version\n"
        "json.dump(doc, open(path, 'w', encoding='utf-8'))\n",
        encoding="utf-8",
    )
    script = (
        "#!/bin/sh\n"
        'if [ "${1:-}" = "mcp" ]; then\n'
        '    if [ "${2:-}" = "get" ]; then exit 1; fi\n'
        '    if [ "${2:-}" = "list" ]; then exit 0; fi\n'
        "    exit 0\n"
        "fi\n"
        'if [ "${1:-}" = "plugin" ] && [ "${2:-}" = "marketplace" ]; then\n'
        "    exit " + str(marketplace_exit) + "\n"
        "fi\n"
        'if [ "${1:-}" = "plugin" ] && [ "${2:-}" = "update" ]; then\n'
        "    "
        + '"$(command -v python3 || command -v python)"'
        + ' "'
        + str(updater)
        + '" "'
        + str(registry_path)
        + '" "'
        + str(project_path)
        + '" "'
        + after
        + '"\n'
        "    exit " + str(update_exit) + "\n"
        "fi\n"
        'for a in "$@"; do printf "%s\\n" "$a" >> "' + str(argv_log) + '"; done\n'
        "exit 0\n"
    )
    return _executable(bindir / "claude", script)


def _registry(home, project, before):
    registry = home / ".claude" / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        json.dumps(
            {
                "plugins": {
                    "oss@dpt-plugins": [
                        {
                            "scope": "project",
                            "projectPath": project,
                            "installPath": "x",
                            "version": before,
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return registry


def _run_with_stub(
    repo,
    before="0.1.0",
    after="0.1.0",
    marketplace_exit=0,
    update_exit=0,
    no_auto_update=False,
):
    _require_shell()
    bindir = repo / "_stubbin"
    bindir.mkdir(exist_ok=True)
    argv_log = repo / "argv.txt"
    home = repo / "_home"
    (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
    registry = _registry(home, str(repo), before)
    _plugin_update_stub_claude(
        bindir,
        argv_log,
        registry,
        str(repo),
        before,
        after,
        marketplace_exit=marketplace_exit,
        update_exit=update_exit,
    )
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    # See tests/test_workspace_launcher.py's `run()` for the full explanation (#853):
    # `plugin_update.receipt_dir()` reads LOCALAPPDATA first on Windows and does not
    # fall back to HOME while it is set, so an ambient LOCALAPPDATA -- inherited by
    # `env = dict(os.environ)` above -- makes the receipt file this whole module is
    # ABOUT shared across every test in this file rather than scoped to `home`. That
    # is precisely how a genuine update in one test survived, via debounce, into a
    # later test's must-not-fire assertion on Windows CI.
    env["LOCALAPPDATA"] = str(home / "_localappdata")
    env["XDG_CACHE_HOME"] = str(home / "_cache")
    env.pop("SUPERTOOL_WATCH_NAME", None)
    if no_auto_update:
        env["OSS_NO_AUTO_UPDATE"] = "1"
    else:
        env.pop("OSS_NO_AUTO_UPDATE", None)
    # #764: the setup diagnostic now routes the prompt to /oss:doctor on any
    # real WARN it finds, and a minimal fixture like `_repo()` below genuinely
    # carries some (no settings rule names gh-pr-merge, and the like) -- a
    # fact about this fixture's tree, not about the auto-update prompt switch
    # this whole file is testing. Skipped so the two mechanisms stay isolated
    # from each other, the same reason `test_workspace_launcher.py`'s own
    # `run()` defaults OSS_NO_AUTO_UPDATE on for tests that are not about it.
    env["OSS_WORKSPACE_SKIP_DOCTOR"] = "1"
    env["PATH"] = os.pathsep.join(
        [str(bindir), str(Path(sys.executable).parent), "/usr/bin", "/bin"]
    )
    done = subprocess.run(
        [BASH, str(LAUNCHER)],
        cwd=str(repo),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    argv = (
        argv_log.read_text(encoding="utf-8").splitlines() if argv_log.exists() else []
    )
    return done, argv


def test_an_updated_version_switches_the_opening_prompt_to_doctor(tmp_path):
    """The must-fire half: a genuine version change before `exec claude` opens
    with /oss:doctor instead of the ordinary /oss:tick, and says why."""
    repo = _repo(tmp_path)
    done, argv = _run_with_stub(repo, before="0.1.0", after="0.2.0")
    assert "/oss:doctor" in argv, (argv, done.stderr)
    assert "/oss:tick" not in argv, argv
    assert "0.1.0" in done.stderr and "0.2.0" in done.stderr


def test_no_version_change_keeps_the_ordinary_prompt(tmp_path):
    """The must-not-fire control: current-and-unchanged must never override the
    prompt `.oss.json`'s presence already chose."""
    repo = _repo(tmp_path)
    done, argv = _run_with_stub(repo, before="0.1.0", after="0.1.0")
    assert "/oss:tick" in argv, (argv, done.stderr)
    assert "/oss:doctor" not in argv, argv


def test_a_failed_marketplace_refresh_keeps_the_ordinary_prompt_and_says_so(tmp_path):
    """could-not-check must never silently masquerade as current or as updated --
    the ordinary prompt stays, and the reason reaches stderr."""
    repo = _repo(tmp_path)
    done, argv = _run_with_stub(repo, marketplace_exit=1)
    assert "/oss:tick" in argv, (argv, done.stderr)
    assert "/oss:doctor" not in argv, argv
    assert "could not check" in done.stderr.lower()


def test_the_existing_opt_out_makes_this_whole_path_a_no_op(tmp_path):
    """OSS_NO_AUTO_UPDATE=1 -- the pre-existing opt-out -- must reach this
    synchronous call exactly as it reaches the SessionStart hook: no version
    comparison, ordinary prompt, no claim about currency printed."""
    repo = _repo(tmp_path)
    done, argv = _run_with_stub(
        repo,
        before="0.1.0",
        after="0.2.0",
        no_auto_update=True,
    )
    assert "/oss:tick" in argv, (argv, done.stderr)
    assert "/oss:doctor" not in argv, argv
