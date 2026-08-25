"""#210 -- doctor checks identity.md and nothing checks core memories, so a loop
that has stopped learning looks exactly like one that never had to.

`check_memory` (scripts/doctor_check_memory.py) answers one question: who the agent
is, injected at session start. `.remember/core-memories.md` answers a different one:
what the loop has LEARNED -- the corrections that changed how it works in this
repo. #210 is explicit that the two must never become interchangeable again; an
earlier version of `check_memory` accepted `core-memories.md` as evidence
`identity.md` existed, which is widening a check until a real gap disappears, and
that decision stands. `check_core_memories` is its own check, answering its own
question, never a second branch folded back into `check_memory`.

Four states, and the third is this repository's own defect class pointed at a
check about memory: a store that cannot be listed must read as "unknown", never
as "no core memories" -- the same rule `check_memory`'s `_listdir` already
follows, reused here rather than re-derived.

Not read into any receipt: `_core_memory_summary` counts the `## YYYY-MM-DD`
headers a real core-memories.md is written in and finds the newest date -- pure
structure, never the entries' own words.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import doctor_check_memory  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _only():
    lines = list(doctor.FINDINGS)
    assert len(lines) == 1, "check_core_memories must print exactly one line, got {!r}".format(lines)
    return lines[0]


# --- _core_memory_summary: structure only, never content ---


def test_summary_counts_dated_headers_and_finds_the_newest():
    text = (
        "# Core Memories\n\n"
        "## 2026-08-15 -- first thing\n"
        "body one\n\n"
        "## 2026-08-16 -- second thing\n"
        "body two\n"
    )
    count, newest = doctor_check_memory._core_memory_summary(text)
    assert count == 2, (count, newest)
    assert newest == "2026-08-16", (count, newest)


def test_summary_of_no_dated_headers_is_zero_and_no_newest():
    count, newest = doctor_check_memory._core_memory_summary("# Core Memories\n\nheader only, nothing else\n")
    assert count == 0, (count, newest)
    assert newest is None, (count, newest)


def test_summary_of_an_empty_file_is_zero():
    count, newest = doctor_check_memory._core_memory_summary("")
    assert (count, newest) == (0, None)


# --- check_core_memories: the four states ---


def test_no_memory_store_at_all_is_ok_not_a_second_warning(tmp_path):
    """check_memory already warns about a wholly-absent store. This check must not
    double it -- a second warning about the same absence is a real cost in signal
    (doctor.py's own note: this repo prints "not usable" on a green tree once
    warnings pile up) and #210 says this state is "already covered by the
    existing WARN, unchanged".
    """
    doctor_check_memory.check_core_memories(tmp_path)
    state, message = _only()
    assert state == "OK", message
    assert "no memory store" in message.lower() or "does not exist" in message.lower(), message


def test_an_unreadable_store_is_unknown_not_absent(tmp_path, monkeypatch):
    """The hard state named in the issue: doctor cannot distinguish "capture never
    ran" from "capture is broken and nothing reaches the file" from the
    filesystem alone -- so an unreadable listing must read as unknown, not as
    "nothing recorded".
    """
    store = tmp_path / ".remember"
    store.mkdir()

    def _boom(directory):
        return [], "could not be read (Permission denied)"

    monkeypatch.setattr(doctor_check_memory, "_listdir", _boom)
    doctor_check_memory.check_core_memories(tmp_path)
    state, message = _only()
    assert state == "WARN", message
    assert "unknown" in message.lower(), message


def test_store_present_no_core_memories_file_is_ok_first_day_is_not_a_fault(tmp_path):
    """The state #210 calls out as the hard one to get right: absent must not
    read as a fault by default, because a repo on its first day is in exactly
    this state and it is correct.
    """
    (tmp_path / ".remember").mkdir()
    doctor_check_memory.check_core_memories(tmp_path)
    state, message = _only()
    assert state == "OK", message
    assert "core-memories.md" in message, message


def test_present_and_empty_is_distinct_from_absent(tmp_path):
    """Created and never filled is its own state, worth a WARN: something set the
    file up and nothing has been recorded in it since.
    """
    store = tmp_path / ".remember"
    store.mkdir()
    (store / "core-memories.md").write_text("# Core Memories\n", encoding="utf-8")
    doctor_check_memory.check_core_memories(tmp_path)
    state, message = _only()
    assert state == "WARN", message
    assert "no dated entries" in message.lower() or "holds nothing" in message.lower(), message


def test_bullet_style_dated_entries_are_counted_too(tmp_path):
    """The self-review finding: a real core-memories.md in the wild uses
    `- YYYY-MM-DD: text` bullets, not `## YYYY-MM-DD` headers -- the ONLY shape
    the first version of this check recognised. That file (11 real entries)
    would have reported zero and printed "created and never filled" about a
    repo that is actively and substantially learning.
    """
    store = tmp_path / ".remember"
    store.mkdir()
    (store / "core-memories.md").write_text(
        "# Core Memories\n\n"
        "Not a changelog. The moments that changed how I work here.\n\n"
        "- 2026-03-06: first thing that happened.\n"
        "- 2026-03-07: second thing that happened.\n"
        "- 2026-03-08: third thing that happened.\n",
        encoding="utf-8",
    )
    doctor_check_memory.check_core_memories(tmp_path)
    state, message = _only()
    assert state == "OK", message
    assert "3" in message, message
    assert "2026-03-08" in message, message


def test_undated_content_is_ok_and_says_it_could_not_count_rather_than_warning(tmp_path):
    """A third real shape: undated bold-paragraph entries, no isolated date
    marker at all. Content is genuinely present -- this must be OK, honestly
    saying entries could not be counted, never the WARN reserved for a file
    that holds nothing but its own heading.
    """
    store = tmp_path / ".remember"
    store.mkdir()
    (store / "core-memories.md").write_text(
        "# Core Memories\n\n"
        '**"You are supposed to be autonomous."** -- Florian, after I asked '
        "twice.\n\n"
        "**Another correction, no date attached.**\n",
        encoding="utf-8",
    )
    doctor_check_memory.check_core_memories(tmp_path)
    state, message = _only()
    assert state == "OK", message
    assert "content present" in message.lower(), message
    assert "no `## yyyy-mm-dd` or `- yyyy-mm-dd:` markers were found" in message.lower(), message


def test_check_memory_and_check_core_memories_agree_on_a_wholly_absent_store(tmp_path):
    """The coupling `check_core_memories` relies on: it reports OK for a wholly
    absent store on the strength of `check_memory` already warning about it in
    the same doctor run. Guarded here by calling both, so a future change to
    `check_memory`'s absent-store handling that breaks the assumption fails
    this test rather than silently losing the "nothing configured" signal.
    """
    doctor_check_memory.check_memory(tmp_path)
    memory_state, memory_message = _only()
    doctor.FINDINGS.clear()
    doctor_check_memory.check_core_memories(tmp_path)
    core_state, core_message = _only()
    assert memory_state == "WARN", memory_message
    assert core_state == "OK", core_message


def test_present_with_content_is_ok_and_reports_count_and_newest_date(tmp_path):
    store = tmp_path / ".remember"
    store.mkdir()
    (store / "core-memories.md").write_text(
        "# Core Memories\n\n"
        "## 2026-08-15 -- first thing\n"
        "body one\n\n"
        "## 2026-08-16 -- second thing\n"
        "body two\n",
        encoding="utf-8",
    )
    doctor_check_memory.check_core_memories(tmp_path)
    state, message = _only()
    assert state == "OK", message
    assert "2" in message, message
    assert "2026-08-16" in message, message
    # Not read into the receipt: neither entry's own words appear.
    assert "first thing" not in message, message
    assert "second thing" not in message, message


def test_an_unreadable_core_memories_file_is_unknown_not_empty(tmp_path, monkeypatch):
    """Present in the listing but unreadable at read time is a fifth path through
    the same rule: unknown, never folded into "holds nothing".
    """
    store = tmp_path / ".remember"
    store.mkdir()
    path = store / "core-memories.md"
    path.write_text("# Core Memories\n", encoding="utf-8")

    from pathlib import Path as _Path

    real_read_text = _Path.read_text

    def _boom(self, *args, **kwargs):
        if self.name == "core-memories.md":
            raise OSError(13, "Permission denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(_Path, "read_text", _boom)
    doctor_check_memory.check_core_memories(tmp_path)
    state, message = _only()
    assert state == "WARN", message
    assert "could not be read" in message.lower(), message
    assert "no dated entries" not in message.lower(), message


# --- doctor's whole contract: exit 0 always, one VERDICT line ---


def test_check_core_memories_never_raises(tmp_path):
    doctor_check_memory.check_core_memories(tmp_path)
    doctor.FINDINGS.clear()
    doctor_check_memory.check_core_memories(tmp_path / "does" / "not" / "exist")
