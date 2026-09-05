"""Debounce: a receipt this fresh means a run just happened (#753).

`bin/oss-workspace` is about to call `plugin_update.py` synchronously, before
`exec claude`, so an opening prompt can be chosen from its outcome. Once that
lands, `hooks/session-start-update.sh`'s own SessionStart hook still fires
seconds later on the same session -- it is kept as the fallback for a
hand-started `claude`, per the issue's own coverage argument -- and would
otherwise repeat the identical marketplace refresh and per-plugin update the
launcher's call just paid for. `update()` now stands down when the receipt
handed to it is fresh enough to mean "this already ran a moment ago", and
performs no network call at all in that case: no `runner` invocation, no
`opt_out` consequence beyond what the fresh receipt already recorded.

The debounce is opt-in per call, not read off the real machine receipt file:
`update()` only debounces when a caller hands it `receipt=`, which is exactly
what `main()` now does (having read it once via `read_receipt()`) and exactly
what every OTHER test in this suite does not do -- so the pre-existing tests in
`tests/test_plugin_update_480.py` etc., which call `update()` directly with no
`receipt=`, stay green unmodified. Reading the real `~/.cache/oss-statusline/`
receipt implicitly inside `update()` would have made every test in this file
flaky against whatever this developer's machine had lying around from a real
run -- observed directly: a real receipt written minutes before this file was
authored sat on disk the whole time.
"""

import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import plugin_update  # noqa: E402


class _Runner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, command, timeout=180):
        self.calls.append(list(command))
        return self.results.pop(0) if self.results else (True, "")


def _plugin_root(tmp_path, name="oss"):
    import json

    root = tmp_path / "plugin"
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": name, "version": "9.9.9"}), encoding="utf-8"
    )
    return root


def test_a_fresh_receipt_stands_down_and_makes_no_network_call(tmp_path):
    """The must-fire half: within the debounce window, `update()` never reaches
    `runner` at all -- not the marketplace refresh, not the per-plugin update."""
    now = time.time()
    receipt = {
        "state": "current",
        "at": now - 5,
        "plugin": "oss",
        "from": "9.9.9",
        "to": "9.9.9",
    }
    runner = _Runner([(True, "")])
    document = plugin_update.update(
        root=str(tmp_path),
        plugin_root=str(_plugin_root(tmp_path)),
        plugins_root=str(tmp_path / "plugins"),
        runner=runner,
        now=now,
        receipt=receipt,
    )
    assert runner.calls == [], "a debounced run must not shell out at all"
    assert document["state"] == "current"
    assert document["debounced"] is True


def test_a_stale_receipt_does_not_debounce(tmp_path):
    """The must-not-fire control: a receipt older than the window is not "just ran",
    so a real check still happens."""
    now = time.time()
    receipt = {
        "state": "current",
        "at": now - plugin_update.DEBOUNCE_SECONDS - 1,
        "plugin": "oss",
        "from": "9.9.9",
        "to": "9.9.9",
    }
    runner = _Runner([(True, "")])
    document = plugin_update.update(
        root=str(tmp_path),
        plugin_root=str(_plugin_root(tmp_path)),
        plugins_root=str(tmp_path / "plugins"),
        runner=runner,
        now=now,
        receipt=receipt,
    )
    assert runner.calls, "a stale receipt must not stand down the real check"
    assert "debounced" not in document


def test_no_receipt_at_all_does_not_debounce(tmp_path):
    now = time.time()
    runner = _Runner([(True, "")])
    document = plugin_update.update(
        root=str(tmp_path),
        plugin_root=str(_plugin_root(tmp_path)),
        plugins_root=str(tmp_path / "plugins"),
        runner=runner,
        now=now,
        receipt=None,
    )
    assert runner.calls
    assert "debounced" not in document


def test_a_receipt_with_no_numeric_at_does_not_debounce(tmp_path):
    """A malformed receipt must fall through to a real run rather than being
    silently treated as fresh -- this repo's own defect class, landing on its
    own debounce."""
    now = time.time()
    receipt = {"state": "current", "at": "not-a-number"}
    runner = _Runner([(True, "")])
    document = plugin_update.update(
        root=str(tmp_path),
        plugin_root=str(_plugin_root(tmp_path)),
        plugins_root=str(tmp_path / "plugins"),
        runner=runner,
        now=now,
        receipt=receipt,
    )
    assert runner.calls
    assert "debounced" not in document


def test_debouncing_does_not_slide_the_window_forever(tmp_path):
    """#753 review finding: a debounced return used to stamp `at` with the
    CURRENT call's `now`, not the original receipt's -- so feeding a debounced
    document back in as the next call's `receipt` (exactly what `main()` does,
    call after call) made the window slide forward on every call and never
    expire. A caller invoked more often than the debounce window is wide would
    never reach a real check again. `at` must stay pinned to the LAST REAL
    check throughout a chain of debounced calls, so the window expires
    `DEBOUNCE_SECONDS` after the real check, not after the last debounce."""
    runner = _Runner([(True, "")])
    now = time.time()
    real_at = now
    receipt = {
        "state": "current",
        "at": real_at,
        "plugin": "oss",
        "from": "9.9.9",
        "to": "9.9.9",
    }
    for _ in range(5):
        now += plugin_update.DEBOUNCE_SECONDS / 10  # 5 hops stay well inside the window
        receipt = plugin_update.update(
            root=str(tmp_path),
            plugin_root=str(_plugin_root(tmp_path)),
            plugins_root=str(tmp_path / "plugins"),
            runner=runner,
            now=now,
            receipt=receipt,
        )
        assert receipt["debounced"] is True
        assert receipt["at"] == real_at, (
            "the window slid forward on a debounced call instead of staying "
            "anchored to the last REAL check"
        )
    # Once far enough past the ORIGINAL real check, a real check must fire again.
    now = real_at + plugin_update.DEBOUNCE_SECONDS + 1
    receipt = plugin_update.update(
        root=str(tmp_path),
        plugin_root=str(_plugin_root(tmp_path)),
        plugins_root=str(tmp_path / "plugins"),
        runner=runner,
        now=now,
        receipt=receipt,
    )
    assert runner.calls, (
        "the window never expired even once past the real check's own age"
    )


def test_a_receipt_from_the_future_does_not_debounce(tmp_path):
    """Clock skew must not make a debounce window last forever."""
    now = time.time()
    receipt = {"state": "current", "at": now + 1000}
    runner = _Runner([(True, "")])
    document = plugin_update.update(
        root=str(tmp_path),
        plugin_root=str(_plugin_root(tmp_path)),
        plugins_root=str(tmp_path / "plugins"),
        runner=runner,
        now=now,
        receipt=receipt,
    )
    assert runner.calls
    assert "debounced" not in document


def test_main_reads_the_real_receipt_and_threads_it_through(tmp_path, monkeypatch):
    """`main()` is the one production caller that opts a run into debouncing --
    it reads the existing receipt once and hands it to `update()`."""
    now = time.time()
    fresh = {
        "state": "updated",
        "at": now - 1,
        "plugin": "oss",
        "from": "0.1.0",
        "to": "0.2.0",
    }
    monkeypatch.setattr(plugin_update, "read_receipt", lambda path=None: fresh)
    captured = {}

    def fake_update(
        root=None,
        plugin_root=None,
        plugins_root=None,
        env=None,
        runner=None,
        now=None,
        receipt=None,
    ):
        captured["receipt"] = receipt
        return {"state": "updated", "at": now or time.time(), "debounced": True}

    monkeypatch.setattr(plugin_update, "update", fake_update)
    monkeypatch.setattr(
        plugin_update, "write_receipt", lambda document, path=None: None
    )
    plugin_update.main(["--root", str(tmp_path)])
    assert captured["receipt"] == fresh


def test_a_receipt_unreadable_is_not_threaded_as_a_dict(tmp_path, monkeypatch):
    """`ReceiptUnreadable` must not be mistaken for a fresh dict receipt -- it is
    the OPPOSITE fact (something is there and broken, not "just ran cleanly")."""
    monkeypatch.setattr(
        plugin_update,
        "read_receipt",
        lambda path=None: plugin_update.ReceiptUnreadable("boom"),
    )
    captured = {}

    def fake_update(
        root=None,
        plugin_root=None,
        plugins_root=None,
        env=None,
        runner=None,
        now=None,
        receipt=None,
    ):
        captured["receipt"] = receipt
        return {"state": "could-not-check", "at": time.time()}

    monkeypatch.setattr(plugin_update, "update", fake_update)
    monkeypatch.setattr(
        plugin_update, "write_receipt", lambda document, path=None: None
    )
    plugin_update.main(["--root", str(tmp_path)])
    assert captured["receipt"] is None


def test_print_state_emits_one_tab_separated_line(tmp_path, monkeypatch, capsys):
    """The launcher parses this with a plain shell `read`, so it has to be one
    line, four tab-separated fields, with embedded tabs and newlines in `detail`
    collapsed rather than left free to forge a fifth field."""
    monkeypatch.setattr(plugin_update, "read_receipt", lambda path=None: None)
    document = {
        "state": "updated",
        "from": "0.1.0",
        "to": "0.2.0",
        "detail": "line one\twith a tab\nand a newline",
    }
    monkeypatch.setattr(plugin_update, "update", lambda **kw: document)
    monkeypatch.setattr(
        plugin_update, "write_receipt", lambda document, path=None: None
    )
    plugin_update.main(["--root", str(tmp_path), "--print-state"])
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert len(lines) == 1, lines
    fields = lines[0].split("\t")
    assert len(fields) == 4, fields
    assert fields[0] == "updated"
    assert fields[1] == "0.1.0"
    assert fields[2] == "0.2.0"
    assert "\t" not in fields[3]
    assert "\n" not in fields[3]


def test_print_state_renders_none_versions_as_empty_fields(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(plugin_update, "read_receipt", lambda path=None: None)
    document = {
        "state": "could-not-check",
        "from": None,
        "to": None,
        "detail": "offline",
    }
    monkeypatch.setattr(plugin_update, "update", lambda **kw: document)
    monkeypatch.setattr(
        plugin_update, "write_receipt", lambda document, path=None: None
    )
    plugin_update.main(["--root", str(tmp_path), "--print-state"])
    fields = capsys.readouterr().out.splitlines()[0].split("\t")
    assert fields == ["could-not-check", "", "", "offline"]
