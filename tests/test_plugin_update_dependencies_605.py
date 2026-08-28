"""Auto-update acts on the loop plugin's declared dependencies too (#605).

The updater kept exactly one plugin current: its own. The status line, meanwhile, already
rendered currency for the loop plugin *and* every name in its manifest's `dependencies`,
deriving that set from the manifest for the stated reason that "absent because it is fine"
and "absent because nothing looked" must not render alike. So the actor's subject was
narrower than the report's subject and nothing said so -- which is this repository's own
defect class one level up.

Two properties carry most of this file:

* a declared dependency with no install record applying to this project is `not-installed`,
  a fourth state, and no `claude plugin update` call is made for it. Reusing the loop
  plugin's `installed_scopes(...) or ["user"]` fallback would turn "this project never had
  this plugin" into a `Plugin "<name>" not found` failure, recorded as a plugin that was
  silently lost;
* a dependency's verdict never becomes the loop plugin's verdict, in either direction. The
  top-level `state`/`plugin`/`from`/`to` still answer about the loop plugin alone, because
  every existing reader of the receipt asks them that question.

Every negative assertion here is paired with a positive control in the same fixture, per
this repository's rule: "no update call was made for it" also passes when no update call
was made for anything.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import plugin_update  # noqa: E402


def _plugin_root(tmp_path, dependencies=("remember", "supertool"), name="oss"):
    """This plugin's own manifest. `dependencies=None` writes no key at all."""
    root = tmp_path / "plugin"
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "version": "9.9.9"}
    if dependencies is not None:
        manifest["dependencies"] = (
            dependencies if isinstance(dependencies, str) else list(dependencies)
        )
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _registry(tmp_path, entries):
    """`entries` maps a registry key (`oss@dpt`) to a list of install records."""
    root = tmp_path / "plugins"
    root.mkdir(parents=True, exist_ok=True)
    (root / "installed_plugins.json").write_text(
        json.dumps({"plugins": entries}), encoding="utf-8"
    )
    return root


def _installed(tmp_path, version, scope="project"):
    return [{"version": version, "scope": scope, "projectPath": str(tmp_path)}]


class _Runner:
    """Records every `claude` call and answers from a queue, defaulting to success."""

    def __init__(self, results=()):
        self.results = list(results)
        self.calls = []

    def __call__(self, command, timeout=180):
        self.calls.append(list(command))
        return self.results.pop(0) if self.results else (True, "")

    def updates_for(self, target):
        return [
            call
            for call in self.calls
            if call[:3] == ["claude", "plugin", "update"] and call[3].split("@", 1)[0] == target
        ]


def _by_name(document):
    return {entry["name"]: entry for entry in document.get("dependencies") or []}


# --------------------------------------------------------- the dependencies are acted on


def test_every_declared_dependency_is_updated_alongside_the_loop_plugin(tmp_path):
    """The whole point of #605. The loop plugin is still updated -- that is the positive
    control for the two dependency assertions beside it."""
    plugins = _registry(
        tmp_path,
        {
            "oss@dpt": _installed(tmp_path, "9.9.9"),
            "remember@dpt": _installed(tmp_path, "0.21.0"),
            "supertool@dpt": _installed(tmp_path, "0.40.0"),
        },
    )
    runner = _Runner()
    document = plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path),
        plugins_root=plugins,
        env={},
        runner=runner,
    )

    assert runner.updates_for("oss"), runner.calls
    assert runner.updates_for("remember"), runner.calls
    assert runner.updates_for("supertool"), runner.calls
    assert sorted(_by_name(document)) == ["remember", "supertool"], document


def test_the_marketplace_is_refreshed_exactly_once_for_the_whole_run(tmp_path):
    """Refreshing per plugin would make the network cost scale with the dependency list
    for no gain: one index serves every name in it."""
    plugins = _registry(
        tmp_path,
        {
            "oss@dpt": _installed(tmp_path, "9.9.9"),
            "remember@dpt": _installed(tmp_path, "0.21.0"),
            "supertool@dpt": _installed(tmp_path, "0.40.0"),
        },
    )
    runner = _Runner()
    plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path),
        plugins_root=plugins,
        env={},
        runner=runner,
    )
    refreshes = [
        call for call in runner.calls if call[:4] == ["claude", "plugin", "marketplace", "update"]
    ]
    assert len(refreshes) == 1, runner.calls


def test_a_dependency_is_updated_at_every_scope_it_is_installed_at(tmp_path):
    """#521's finding, which is a property of the loop plugin's update and has to hold
    for a dependency's too: an install at two scopes is two installs."""
    plugins = _registry(
        tmp_path,
        {
            "oss@dpt": _installed(tmp_path, "9.9.9"),
            "remember@dpt": [
                {"version": "0.21.0", "scope": "project", "projectPath": str(tmp_path)},
                {"version": "0.21.0", "scope": "user"},
            ],
        },
    )
    runner = _Runner()
    plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path, ["remember"]),
        plugins_root=plugins,
        env={},
        runner=runner,
    )
    assert [call[-1] for call in runner.updates_for("remember")] == [
        "project",
        "user",
    ], runner.calls


def test_a_dependency_that_moved_carries_its_two_versions(tmp_path):
    """`updated` with no `from`/`to` is a claim nobody can check."""
    plugins = _registry(
        tmp_path,
        {
            "oss@dpt": _installed(tmp_path, "9.9.9"),
            "remember@dpt": _installed(tmp_path, "0.21.0"),
        },
    )

    class Moving(_Runner):
        def __call__(self, command, timeout=180):
            result = _Runner.__call__(self, command, timeout)
            if command[:3] == ["claude", "plugin", "update"] and command[3].startswith("remember"):
                (plugins / "installed_plugins.json").write_text(
                    json.dumps(
                        {
                            "plugins": {
                                "oss@dpt": _installed(tmp_path, "9.9.9"),
                                "remember@dpt": _installed(tmp_path, "0.22.0"),
                            }
                        }
                    ),
                    encoding="utf-8",
                )
            return result

    document = plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path, ["remember"]),
        plugins_root=plugins,
        env={},
        runner=Moving(),
    )
    entry = _by_name(document)["remember"]
    assert entry["state"] == "updated", entry
    assert entry["from"] == "0.21.0" and entry["to"] == "0.22.0", entry
    # The loop plugin did not move, and its own verdict must be unaffected by one that did.
    assert document["state"] == "current", document


# ------------------------------------------------------- the fourth state, and its control


def test_a_dependency_this_project_never_installed_is_not_installed_not_a_failure(tmp_path):
    """The loop plugin's `installed_scopes(...) or ["user"]` fallback must not be reused
    here: it would run `claude plugin update jit --scope user` against a project that has
    no such install, and record `Plugin "jit" not found` as a plugin silently lost.

    `remember` in the same fixture is the positive control -- it IS installed, so it does
    get a call, which is what makes "no call was made for jit" mean something."""
    plugins = _registry(
        tmp_path,
        {
            "oss@dpt": _installed(tmp_path, "9.9.9"),
            "remember@dpt": _installed(tmp_path, "0.21.0"),
            # jit is installed -- for a DIFFERENT project on this machine.
            "jit@dpt": [
                {
                    "version": "0.6.0",
                    "scope": "project",
                    "projectPath": str(tmp_path / "elsewhere"),
                }
            ],
        },
    )
    runner = _Runner()
    document = plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path, ["remember", "jit"]),
        plugins_root=plugins,
        env={},
        runner=runner,
    )
    entries = _by_name(document)
    assert entries["jit"]["state"] == "not-installed", entries["jit"]
    assert runner.updates_for("jit") == [], runner.calls
    assert runner.updates_for("remember"), runner.calls  # positive control
    assert entries["remember"]["state"] in ("current", "updated"), entries["remember"]


def test_a_dependency_whose_every_scope_failed_is_could_not_check(tmp_path):
    """Not `current`. An update that could not run has established nothing."""
    plugins = _registry(
        tmp_path,
        {
            "oss@dpt": _installed(tmp_path, "9.9.9"),
            "remember@dpt": _installed(tmp_path, "0.21.0"),
        },
    )
    runner = _Runner([(True, ""), (True, ""), (False, "network unreachable")])
    document = plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path, ["remember"]),
        plugins_root=plugins,
        env={},
        runner=runner,
    )
    entry = _by_name(document)["remember"]
    assert entry["state"] == "could-not-check", entry
    assert "network unreachable" in entry["detail"], entry


def test_a_failed_dependency_does_not_become_the_loop_plugins_verdict(tmp_path):
    """Both directions in one fixture: the loop plugin reports `current` on its own terms
    while the dependency reports `could-not-check`, and neither is rewritten by the other."""
    plugins = _registry(
        tmp_path,
        {
            "oss@dpt": _installed(tmp_path, "9.9.9"),
            "remember@dpt": _installed(tmp_path, "0.21.0"),
        },
    )
    document = plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path, ["remember"]),
        plugins_root=plugins,
        env={},
        runner=_Runner([(True, ""), (True, ""), (False, "boom")]),
    )
    assert document["state"] == "current", document
    assert document["plugin"] == "oss", document
    assert _by_name(document)["remember"]["state"] == "could-not-check", document


def test_a_marketplace_that_did_not_refresh_attempts_no_dependency_either(tmp_path):
    """The refresh's failure is fatal to the whole run, which now includes the
    dependencies: updating them against a stale index reports `current` about a version
    that is not the current one."""
    plugins = _registry(
        tmp_path,
        {
            "oss@dpt": _installed(tmp_path, "9.9.9"),
            "remember@dpt": _installed(tmp_path, "0.21.0"),
        },
    )
    runner = _Runner([(False, "network unreachable")])
    document = plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path, ["remember"]),
        plugins_root=plugins,
        env={},
        runner=runner,
    )
    assert document["state"] == "could-not-check", document
    assert len(runner.calls) == 1, runner.calls


# --------------------------------------------- declaring none vs not being able to tell


def test_no_dependencies_declared_is_an_empty_list_not_an_unreadable_one(tmp_path):
    """The positive control for the test below. A manifest with no `dependencies` key is
    a manifest that declares none, and that is a fact, not a gap."""
    names, status = plugin_update.declared_dependencies(_plugin_root(tmp_path, None))
    assert (names, status) == ([], "ok")

    plugins = _registry(tmp_path, {"oss@dpt": _installed(tmp_path, "9.9.9")})
    document = plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path, None),
        plugins_root=plugins,
        env={},
        runner=_Runner(),
    )
    assert document["dependencies"] == [], document
    assert document.get("dependencies_unreadable") is False, document


def test_a_dependencies_key_that_is_not_a_list_is_unreadable_not_empty(tmp_path):
    """An empty list means "declares none". A `dependencies` key holding a string means
    nobody can tell what it declares, and rendering that as "declares none" is the whole
    defect class this repository is named after."""
    names, status = plugin_update.declared_dependencies(
        _plugin_root(tmp_path, "remember, supertool")
    )
    assert status == "unreadable", (names, status)

    plugins = _registry(tmp_path, {"oss@dpt": _installed(tmp_path, "9.9.9")})
    document = plugin_update.update(
        root=tmp_path,
        plugin_root=_plugin_root(tmp_path, "remember, supertool"),
        plugins_root=plugins,
        env={},
        runner=_Runner(),
    )
    assert document["dependencies_unreadable"] is True, document


def test_a_dependency_entry_may_be_an_object_carrying_a_name(tmp_path):
    """`doctor.declared_dependencies` already accepts both shapes; this one must not
    diverge from it, or the row a maintainer reads and the actor that runs disagree
    about the set."""
    names, status = plugin_update.declared_dependencies(
        _plugin_root(tmp_path, [{"name": "remember"}, "supertool"])
    )
    assert (names, status) == (["remember", "supertool"], "ok")


def test_doctors_dependency_set_and_the_updaters_are_the_same_set():
    """Two derivations of one manifest key is two things to disagree. Measured against
    the real manifest rather than a fixture, because the shipped file is the one that
    matters."""
    import doctor  # noqa: E402

    names, status = plugin_update.declared_dependencies(REPO_ROOT)
    assert status == "ok", (names, status)
    assert names == list(doctor.declared_dependencies()), (names, doctor.declared_dependencies())


# ------------------------------------------------------------------- the shipped manifest


def test_the_shipped_manifest_still_declares_the_dependencies_this_updates():
    """Not a tautology: it fails if `dependencies` is dropped or renamed, which would
    silently narrow the updater back to one plugin with every test above still green
    against its own fixtures."""
    names, status = plugin_update.declared_dependencies(REPO_ROOT)
    assert status == "ok"
    assert names, "the manifest declares no dependencies; #605's subject would be empty"

# ------------------------------------------------------- what a maintainer actually reads
#
# A dependency the updater failed to update, recorded only in a receipt no row reads, is
# #521 with an extra step: that issue's own measured instance was `state: current` printed
# while one of two scopes had failed, with the failure named only in `detail`, which the
# row never looked at. So the receipt's new list has to reach `doctor` in the same change
# that starts writing it.

import doctor  # noqa: E402


def _doctor_rows(receipt, monkeypatch, tmp_path):
    doctor.FINDINGS.clear()
    monkeypatch.setattr(plugin_update, "opt_out", lambda root=None, env=None: ("on", None))
    monkeypatch.setattr(plugin_update, "read_receipt", lambda: receipt)
    doctor.check_auto_update(str(tmp_path))
    return list(doctor.FINDINGS)


def _clean_loop_plugin(**extra):
    document = {"state": "current", "plugin": "oss", "from": "9.9.9", "to": "9.9.9"}
    document.update(extra)
    return document


def test_a_dependency_that_could_not_be_updated_reaches_the_doctor_row(tmp_path, monkeypatch):
    """The must-fire half. The loop plugin is clean in this fixture, so the only thing
    that can produce a WARN is the dependency -- which is the point."""
    rows = _doctor_rows(
        _clean_loop_plugin(
            dependencies_unreadable=False,
            dependencies=[
                {"name": "remember", "state": "could-not-check", "detail": "boom"},
                {"name": "supertool", "state": "current", "from": "0.40.0", "to": "0.40.0"},
            ],
        ),
        monkeypatch,
        tmp_path,
    )
    assert rows[0][0] == "OK", rows  # the loop plugin's own row, unaffected
    dependency_rows = [row for row in rows[1:] if "dependencies" in row[1]]
    assert dependency_rows, rows
    state, message = dependency_rows[0]
    assert state == "WARN", rows
    assert "remember" in message and "boom" in message


def test_every_dependency_current_is_the_ok_control(tmp_path, monkeypatch):
    """The must-not-fire control for the test above, in the same shape: change only the
    one dependency's state and the row flips back to OK."""
    rows = _doctor_rows(
        _clean_loop_plugin(
            dependencies_unreadable=False,
            dependencies=[
                {"name": "remember", "state": "current", "from": "0.22.0", "to": "0.22.0"},
                {"name": "supertool", "state": "current", "from": "0.40.0", "to": "0.40.0"},
            ],
        ),
        monkeypatch,
        tmp_path,
    )
    dependency_rows = [row for row in rows if "dependencies" in row[1]]
    assert dependency_rows, rows
    assert dependency_rows[0][0] == "OK", rows


def test_a_dependency_that_moved_warns_because_this_session_runs_the_old_copy(
    tmp_path, monkeypatch
):
    """Same reason the loop plugin's `updated` arm WARNs: the registry has moved and this
    session has not, so the remedy has to be said rather than implied."""
    rows = _doctor_rows(
        _clean_loop_plugin(
            dependencies_unreadable=False,
            dependencies=[
                {"name": "remember", "state": "updated", "from": "0.21.0", "to": "0.22.0"}
            ],
        ),
        monkeypatch,
        tmp_path,
    )
    dependency_rows = [row for row in rows if "dependencies" in row[1]]
    state, message = dependency_rows[0]
    assert state == "WARN", rows
    assert "remember" in message and "0.21.0" in message and "0.22.0" in message
    assert "/reload-plugins" in message, message


def test_a_receipt_with_no_dependencies_key_does_not_read_as_all_current(tmp_path, monkeypatch):
    """A receipt written by the updater before #605 says nothing about dependencies. The
    row must say that it says nothing -- the absence is in the instrument, not the world,
    and rendering it as a clean pass is this repository's whole subject."""
    rows = _doctor_rows(_clean_loop_plugin(), monkeypatch, tmp_path)
    dependency_rows = [row for row in rows if "dependencies" in row[1]]
    assert dependency_rows, rows
    message = dependency_rows[0][1]
    assert "records nothing" in message, message
    assert "not a statement" in message, message


def test_an_unreadable_dependencies_key_warns_rather_than_reading_as_none(tmp_path, monkeypatch):
    """`dependencies_unreadable` is the manifest half of the same distinction: which
    dependencies should have been updated could not be told, so none were."""
    rows = _doctor_rows(
        _clean_loop_plugin(dependencies_unreadable=True, dependencies=[]),
        monkeypatch,
        tmp_path,
    )
    dependency_rows = [row for row in rows if "dependencies" in row[1]]
    state, message = dependency_rows[0]
    assert state == "WARN", rows
    assert "could not be read" in message, message


def test_a_dependency_this_project_never_installed_is_named_without_warning(
    tmp_path, monkeypatch
):
    """`not-installed` is not a failure of the updater, and a different doctor row already
    owns whether a declared dependency should be installed. It is still named here rather
    than counted as current, because "nothing was updated" and "nothing needed updating"
    are the two answers this file exists to keep apart."""
    rows = _doctor_rows(
        _clean_loop_plugin(
            dependencies_unreadable=False,
            dependencies=[
                {"name": "jit", "state": "not-installed", "detail": "no install record"},
                {"name": "remember", "state": "current", "from": "0.22.0", "to": "0.22.0"},
            ],
        ),
        monkeypatch,
        tmp_path,
    )
    dependency_rows = [row for row in rows if "dependencies" in row[1]]
    state, message = dependency_rows[0]
    assert state == "OK", rows
    assert "jit" in message and "not installed" in message, message


def test_the_dependency_row_is_not_emitted_when_the_updater_never_ran(tmp_path, monkeypatch):
    """Switched off, or no receipt at all: nothing ran, so there is nothing to say about
    dependencies and a row claiming otherwise would be inventing one. The `off` arm's own
    single row is the control that the check still reports something."""
    doctor.FINDINGS.clear()
    monkeypatch.setattr(
        plugin_update, "opt_out", lambda root=None, env=None: ("off", "OSS_NO_AUTO_UPDATE")
    )
    monkeypatch.setattr(plugin_update, "read_receipt", lambda: None)
    doctor.check_auto_update(str(tmp_path))
    assert len(doctor.FINDINGS) == 1, doctor.FINDINGS
    assert "dependencies" not in doctor.FINDINGS[0][1], doctor.FINDINGS
