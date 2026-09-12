"""#1416: for every `scripts/<name>.py`, does something ACTUALLY RUN it, or
only describe it? Reproduced against a synthetic plugin tree so each state is
exercised in isolation, rather than against this repository's own live
corpus (which changes underneath a fixture pinned to a literal count).
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import script_call_survey as mod  # noqa: E402


def _plugin(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "commands").mkdir()
    (tmp_path / "agents").mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "bin").mkdir()
    return tmp_path


def _rows_by_name(rows):
    return {name: (state, detail) for name, state, detail in rows}


def test_a_documented_command_line_with_a_runner_verb_is_called(tmp_path):
    root = _plugin(tmp_path)
    (root / "scripts" / "run_me.py").write_text("print(1)", encoding="utf-8")
    (root / "commands" / "foo.md").write_text(
        "Run it:"
        + chr(10)
        + chr(10)
        + "```bash"
        + chr(10)
        + "python3 scripts/run_me.py --flag"
        + chr(10)
        + "```"
        + chr(10),
        encoding="utf-8",
    )
    rows, _roots, _notes = mod.survey(str(root))
    state, detail = _rows_by_name(rows)["run_me.py"]
    assert state == "called", detail
    assert "command line" in detail


def test_a_bare_prose_mention_with_no_runner_verb_is_mentioned_only(tmp_path):
    """Must-fire: the same name, same file, but never inside an executing
    form -- a table cell, a plain sentence -- must not read as `called`."""
    root = _plugin(tmp_path)
    (root / "scripts" / "described.py").write_text("print(1)", encoding="utf-8")
    (root / "commands" / "foo.md").write_text(
        "`scripts/described.py` computes the release version.",
        encoding="utf-8",
    )
    rows, _roots, _notes = mod.survey(str(root))
    state, detail = _rows_by_name(rows)["described.py"]
    assert state == "mentioned-only", detail
    assert "never in an executing form" in detail


def test_a_script_nobody_mentions_anywhere_is_also_mentioned_only(tmp_path):
    """The degenerate case, folded in deliberately rather than a fourth
    state -- see the module docstring."""
    root = _plugin(tmp_path)
    (root / "scripts" / "orphan.py").write_text("print(1)", encoding="utf-8")
    rows, _roots, _notes = mod.survey(str(root))
    state, detail = _rows_by_name(rows)["orphan.py"]
    assert state == "mentioned-only", detail
    assert "not referenced anywhere" in detail


def test_a_neighbouring_dot_sh_filename_does_not_forge_a_runner_verb(tmp_path):
    """Must-fire (reviewer spawn finding): a bare word-boundary match on
    "sh" also matches the trailing "sh" inside any .sh-suffixed filename
    token, because a word boundary fires on the transition from "." (a
    non-word character) to "s" (a word character) exactly as it does on
    real whitespace. A window naming a script alongside an unrelated .sh
    file, with no real runner verb anywhere in it, must not read as
    `called`."""
    root = _plugin(tmp_path)
    (root / "scripts" / "foo.py").write_text("print(1)", encoding="utf-8")
    (root / "commands" / "test.md").write_text(
        "```" + chr(10) + "scripts/foo.py bin/refresh.sh" + chr(10) + "```" + chr(10),
        encoding="utf-8",
    )
    rows, _roots, _notes = mod.survey(str(root))
    state, detail = _rows_by_name(rows)["foo.py"]
    assert state == "mentioned-only", detail


def test_a_real_standalone_sh_invocation_is_still_called(tmp_path):
    """Positive control: excluding the .sh-filename false positive must not
    also blind the detector to a genuine `sh script.py` invocation."""
    root = _plugin(tmp_path)
    (root / "scripts" / "foo.py").write_text("print(1)", encoding="utf-8")
    (root / "commands" / "test.md").write_text(
        "```" + chr(10) + "sh scripts/foo.py" + chr(10) + "```" + chr(10),
        encoding="utf-8",
    )
    rows, _roots, _notes = mod.survey(str(root))
    state, detail = _rows_by_name(rows)["foo.py"]
    assert state == "called", detail


def test_an_import_from_another_script_is_called(tmp_path):
    root = _plugin(tmp_path)
    (root / "scripts" / "lib_mod.py").write_text("VALUE = 1", encoding="utf-8")
    (root / "scripts" / "caller.py").write_text(
        "import lib_mod" + chr(10) + chr(10) + "print(lib_mod.VALUE)",
        encoding="utf-8",
    )
    rows, _roots, _notes = mod.survey(str(root))
    state, detail = _rows_by_name(rows)["lib_mod.py"]
    assert state == "called", detail
    assert "imported" in detail


def test_an_import_inside_bin_oss_workspaces_own_heredoc_is_called(tmp_path):
    """`bin/oss-workspace` has no `.py` extension and is not markdown, so
    neither of this module's other two readers would see it without this
    dedicated pass -- its embedded heredocs are literal Python source."""
    root = _plugin(tmp_path)
    (root / "scripts" / "doctor_bit.py").write_text("VALUE = 1", encoding="utf-8")
    (root / "bin" / "oss-workspace").write_text(
        "#!/bin/sh"
        + chr(10)
        + "python3 - <<'PY'"
        + chr(10)
        + "import doctor_bit"
        + chr(10)
        + "PY"
        + chr(10),
        encoding="utf-8",
    )
    rows, _roots, _notes = mod.survey(str(root))
    state, detail = _rows_by_name(rows)["doctor_bit.py"]
    assert state == "called", detail


def test_an_unreadable_script_is_could_not_tell_never_called(tmp_path, monkeypatch):
    """Must-fire: an unreadable script must render as `could-not-tell`, and
    the positive control alongside it (a readable sibling correctly called)
    proves the guard actually distinguishes rather than always refusing."""
    root = _plugin(tmp_path)
    (root / "scripts" / "unreadable.py").write_text("x = 1", encoding="utf-8")
    (root / "scripts" / "readable.py").write_text("y = 2", encoding="utf-8")
    (root / "commands" / "foo.md").write_text(
        "```bash" + chr(10) + "python3 scripts/readable.py" + chr(10) + "```" + chr(10),
        encoding="utf-8",
    )

    real_read_text = Path.read_text

    def _boom(self, *args, **kwargs):
        if self.name == "unreadable.py":
            raise OSError("simulated permission denial")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _boom)
    rows, _roots, _notes = mod.survey(str(root))
    by_name = _rows_by_name(rows)
    state, detail = by_name["unreadable.py"]
    assert state == "could-not-tell", detail
    assert by_name["readable.py"][0] == "called"


def test_an_ambiguous_runtime_render_is_noted_but_not_attributed(tmp_path):
    """`lane_setup.py`'s own `Agent(...)` render is exactly this shape: a
    command line assembled from a variable rather than a literal filename.
    This must produce a corpus-wide note, never a guessed `called` on any
    one script's row."""
    root = _plugin(tmp_path)
    (root / "scripts" / "maybe_run.py").write_text("print(1)", encoding="utf-8")
    (root / "scripts" / "lane_setup.py").write_text(
        'prompt = "python3 scripts/{}.py".format(name)', encoding="utf-8"
    )
    rows, _roots, notes = mod.survey(str(root))
    state, _detail = _rows_by_name(rows)["maybe_run.py"]
    assert state != "called"
    assert any("runtime-rendered" in note for note in notes), notes


def test_the_real_plugin_tree_runs_end_to_end():
    """Smoke test against this repository's own tree -- proves the survey
    completes over the real corpus with no crash and reasonable totals,
    without pinning a literal count that would go stale on the next commit
    touching any prose file."""
    rows, roots, _notes = mod.survey(str(REPO_ROOT))
    assert rows
    assert all(
        state in ("called", "mentioned-only", "could-not-tell")
        for _n, state, _d in rows
    )
    assert not any(state == "unreadable" for _n, state, _d in roots)
