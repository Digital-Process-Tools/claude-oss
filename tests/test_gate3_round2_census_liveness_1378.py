"""#1378 findings 2, 3 and 4 (gate 3 round two, v0.31.0): three defects in
`_drop_dead_plugin_consumers`'s liveness gate, all three inside the same
`_CHANNEL_CENSUS`/round-one fix (#1372).

* finding 2: `channel_consumer_census_state`'s own docstring promises a
  caller who already injects `run`/`which` for the `claude mcp list` half is
  not left with a second, real subprocess call it has no way to stub for the
  plugin-liveness half -- but `run`/`which`/`env` were never threaded into
  `_drop_dead_plugin_consumers`'s default `arm_target_liveness`, so that
  promise was false. On this repo's own CI (no `claude` installed), the
  real `shutil.which`/`subprocess.run` always answers could-not-ask, so the
  drop this module exists to perform was nominally on and untestable there.
* finding 3: the drop filtered by NAME PREFIX over the concatenated
  populations, not by which population a name actually came from -- so a
  `claude mcp list` row whose bare, harness-assigned name happens to start
  with `plugin:` (spoofable by anyone who can run `claude mcp add`) was
  liveness-probed and droppable exactly like a real plugin-declared
  consumer, and every drop moves the count toward `single` -- the unsafe
  direction for a census whose job is catching two servers racing one
  socket.
* finding 4: the lazy `from doctor_check_mcp_channel_connection import
  arm_target_liveness` had no failure arm, so an ImportError would escape as
  a raw traceback out of a function `doctor.py`'s own `main()` calls with no
  enclosing `except` -- violating doctor's own exit-0-one-VERDICT-line
  contract.

Each test below is a reproduction against the real module -- run before the
fix, they fail for the stated reason.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_mcp_channel_registration as reg  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


class _Completed:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout


def _which_stub(name):
    return "/usr/bin/claude" if name == "claude" else None


# ------------------------------------- finding 2: run/which never threaded


def test_census_drops_a_failed_plugin_consumer_using_only_run_which(
    tmp_path, monkeypatch
):
    """Must-fire: a REAL plugin-declared consumer (from the registry
    population) whose transport the injected `run`/`which` stubs report
    FAILED must still be dropped with NO explicit `liveness=` override --
    proving `run`/`which` reached the liveness ask rather than falling
    through to the real subprocess."""

    def _run_stub(argv, **_kwargs):
        assert argv[0] == "/usr/bin/claude", argv
        if argv[1:3] == ["mcp", "list"]:
            text = (
                "oss-channel:    bun /x/notifiers/claude-channel/channel.ts - Connected"
            )
            return _Completed(0, text.encode("utf-8"))
        if argv[1:3] == ["mcp", "get"]:
            assert argv[3] == "plugin:supertool:claude-channel", argv
            return _Completed(0, b"Status: Failed to connect - CONNECTION_CLOSED")
        raise AssertionError(("unexpected subcommand", argv))

    monkeypatch.setattr(
        reg,
        "_plugin_channel_consumer_names",
        lambda *_a, **_k: (["plugin:supertool@dpt-plugins:claude-channel"], None),
    )

    state, detail = reg.channel_consumer_census_state(
        run=_run_stub, which=_which_stub, project_dir=str(tmp_path)
    )
    assert state == "single", (state, detail)
    assert detail == "oss-channel"


def test_census_still_counts_a_plugin_consumer_that_is_alive(tmp_path, monkeypatch):
    """Positive control: the same wiring must not drop a plugin consumer
    whose liveness ask reports CONNECTED -- proving the guard actually
    distinguishes rather than always dropping once wired up."""

    def _run_stub(argv, **_kwargs):
        if argv[1:3] == ["mcp", "list"]:
            return _Completed(0, b"")
        if argv[1:3] == ["mcp", "get"]:
            return _Completed(0, b"Status: Connected")
        raise AssertionError(("unexpected subcommand", argv))

    monkeypatch.setattr(
        reg,
        "_plugin_channel_consumer_names",
        lambda *_a, **_k: (["plugin:supertool@dpt-plugins:claude-channel"], None),
    )

    state, detail = reg.channel_consumer_census_state(
        run=_run_stub, which=_which_stub, project_dir=str(tmp_path)
    )
    assert state == "single", (state, detail)


# ---------------------------- finding 3: name prefix over population


def test_a_mcp_list_only_name_spelled_like_a_plugin_is_never_liveness_probed(
    tmp_path, monkeypatch
):
    """Must-fire: a `claude mcp list` row whose bare name happens to start
    with `plugin:` (never seen in the plugin registry) must not be
    liveness-probed at all -- it is a real, currently CONNECTED collision,
    and dropping it on a spoofed FAILED reply would silently disarm a real
    race the census exists to catch."""

    def _run_stub(argv, **_kwargs):
        if argv[1:3] == ["mcp", "list"]:
            text = (
                "oss-channel:      bun /x/notifiers/claude-channel/channel.ts - Connected\n"
                "plugin:evil:name: bun /x/notifiers/claude-channel/channel.ts - Connected"
            )
            return _Completed(0, text.encode("utf-8"))
        if argv[1:3] == ["mcp", "get"]:
            # If this is ever reached for the mcp-list-only row, answer FAILED
            # -- proving whether the (buggy) code drops it.
            return _Completed(0, b"Status: Failed to connect - CONNECTION_CLOSED")
        raise AssertionError(("unexpected subcommand", argv))

    monkeypatch.setattr(
        reg, "_plugin_channel_consumer_names", lambda *_a, **_k: ([], None)
    )

    state, detail = reg.channel_consumer_census_state(
        run=_run_stub, which=_which_stub, project_dir=str(tmp_path)
    )
    assert state == "collision", (state, detail)
    assert set(detail) == {"oss-channel", "plugin:evil:name"}, detail


# ------------------------------------ finding 4: the lazy import has no arm


def test_a_broken_lazy_import_does_not_crash_the_census(monkeypatch):
    """Must-fire: an ImportError resolving `arm_target_liveness` must not
    escape as a raw traceback -- `channel_consumer_census_state` promises
    could-not-ask for any failure to establish a population, and an
    unhandled exception here would reach `doctor.py`'s own `main()` with no
    enclosing `except`, violating its exit-0-one-VERDICT-line contract. An
    import that could not be resolved is not evidence a consumer is dead,
    so the name must be KEPT, not dropped."""
    monkeypatch.setitem(sys.modules, "doctor_check_mcp_channel_connection", None)
    names = reg._drop_dead_plugin_consumers(["plugin:x:y"])
    assert names == ["plugin:x:y"], names
