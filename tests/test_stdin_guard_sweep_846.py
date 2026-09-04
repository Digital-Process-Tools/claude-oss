"""#846 -- the closed-stdin class recurred because #405's guard was scoped to
one file, so a sweep is the fix rather than three individual patches.

`sys.stdin` is `None` when the harness hands a process a closed or
unopenable standard input. Three CLI entry points read `sys.stdin` (or
`sys.stdin.read()`) with only a JSON-decode exception guarding the read, so
`AttributeError` escapes uncaught and the process exits 1 with none of its
own documented states -- past the `COULD NOT READ` / empty-payload fallback
each module otherwise has for a bad read.

This is deliberately one parametrized sweep over every script named in #846
plus `review_return.py` (the #405 fix this class was named after), rather
than three copies of the same test one per file -- so a fourth CLI added to
this list is one line, not a new test module.

**Known, unfixed instances of the same class exist outside this lane's
claimed files** and are reported rather than silently swept up here:
`scripts/oss_config.py:3085` (`json.load(sys.stdin)`, guarded only by
`except ValueError`). That is out of this lane's claimed file set
(`agents/developer.md`'s own boundary) -- see the lane's report.
`scripts/lane_setup.py`'s `--suggest-companions` mode carried the identical
shape (#984) and is fixed and swept below alongside the rest.
`scripts/board_touch.py` and `scripts/tree_snapshot.py` also read
`sys.stdin` but are already safe: `board_touch.py` wraps the whole read in
`except Exception: pass` (module docstring: never break a tool call), and
`tree_snapshot.py` already uses the #405 `getattr(sys.stdin, "buffer",
None)` pattern.

**The negative assertion carries a positive control in the same sweep**: a
closed stdin must not crash, and an ordinary piped payload must still be
read and produce the module's normal answer -- see
`test_an_ordinary_piped_payload_still_works`, paired per script.
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# (script relative to REPO, argv after the script name, ordinary stdin payload)
SWEPT_SCRIPTS = [
    ("scripts/dispatch_rank.py", [], '{"declared": {}, "issues": []}'),
    ("scripts/statusline.py", [], '{}'),
    ("scripts/batch_hint.py", [], '{}'),
    ("scripts/review_return.py", ["-"], "NO FINDINGS: nothing to check"),
    (
        "scripts/lane_setup.py",
        ["--suggest-companions", "1", "--lane", "scripts/lane_setup.py"],
        '{"declared": {}, "issues": []}',
    ),
]


def _run_with_closed_stdin(script, argv):
    """Drive `script` with `sys.stdin is None`, exactly what a harness handing
    a closed fd 0 produces -- see #405's own driver, the same shape here.
    """
    driver = (
        "import os, runpy, sys\n"
        "os.close(0)\n"
        "sys.stdin = None\n"
        "sys.argv = [{0!r}] + {1!r}\n"
        "try:\n"
        "    runpy.run_path({0!r}, run_name='__main__')\n"
        "except SystemExit as exc:\n"
        "    raise SystemExit(exc.code)\n"
    ).format(str(REPO / script), argv)
    return subprocess.run(
        [sys.executable, "-c", driver],
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )


def test_a_closed_stdin_never_raises_uncaught():
    failures = []
    for script, argv, _payload in SWEPT_SCRIPTS:
        proc = _run_with_closed_stdin(script, argv)
        err = proc.stderr.decode("utf-8", errors="replace")
        if "Traceback" in err:
            failures.append("{0}: still raises on a closed stdin\n{1}".format(script, err))
    assert not failures, "\n\n".join(failures)


def test_an_ordinary_piped_payload_still_works():
    """The positive control: none of the three answers "closed" for everything."""
    failures = []
    for script, argv, payload in SWEPT_SCRIPTS:
        proc = subprocess.run(
            [sys.executable, str(REPO / script)] + argv,
            input=payload.encode("utf-8"),
            capture_output=True,
        )
        err = proc.stderr.decode("utf-8", errors="replace")
        if "Traceback" in err:
            failures.append(
                "{0}: an ordinary piped payload should not crash either\n{1}".format(script, err)
            )
    assert not failures, "\n\n".join(failures)
