---
title: "subprocess text=True decodes with the locale, which is cp1252 on a Windows runner"
description: "Any subprocess reading repository or forge content without encoding= is a Windows leg waiting to fail. UnicodeDecodeError is a ValueError, so an except (OSError, SubprocessError) arm never catches it."
match: (^|/)(scripts|tests)/[^/]+\.py$
---

**`subprocess.run(..., text=True)` (or `universal_newlines=True`) with
no `encoding=` decodes the child's output with the *locale* encoding.**
That is UTF-8 almost everywhere and cp1252 on a Windows runner. Most of
this loop's own markdown carries em dashes; U+2014 is three bytes, and
cp1252 turns each into three separate characters that match nothing.

**Pass `encoding="utf-8"`. Add `errors="replace"` where a decode failure
must not be fatal.**

Two live instances:

- **#1144**, one leg of eighteen: `tests/test_developer_brief_duties.py`
  shelled out to `git show <commit>:agents/developer.md` with `text=True`
  and nothing else. Green on macOS, green on every Linux leg, green on
  `main`, red on `pytest (windows-latest, 3.12)` -- and the change under
  review had touched neither that test nor the file it reads.
- **#1181**, found by a release audit and still open:
  `scripts/doctor_check_lane_other_label.py` decodes `gh label list` the
  same way. **`UnicodeDecodeError` is a `ValueError`**, so the
  surrounding `except (OSError, subprocess.SubprocessError)` does not
  catch it -- it escapes a diagnostic whose whole contract is "exit 0
  always, one VERDICT line", and the launcher's VERDICT parse gets
  nothing instead of a warning.

**A test that usually skips is a test whose bugs surface at random.**
Issue #1144's `_blob` returns `None` and skips when `git show` cannot produce
the old commit, which is what a depth-1 checkout normally looks like --
so the decode path is only reached on a runner whose checkout is deep
enough. Months later, on one platform.

**The same risk runs in the write direction too: `print()` to stdout encodes with the console
codepage, not the locale a script reasons about.** `scripts/delegation_cost.py`'s `--json` mode
prints an `OSError` message via a bare `print(...)`, no explicit stdout encoding; on Windows,
stdout defaults to the console codepage (typically cp1252), so an error message embedding a
non-ASCII path component would raise `UnicodeEncodeError` at the print call -- after the whole
measurement already ran, so the crash lands on delivery, not on computation (#1595).
`scripts/loop_cost_report.py` (`print(json.dumps(...))` / `print(render(result))`) has the identical
shape, unremediated. Not a one-off: a shared stdout-encoding-safety helper
(`sys.stdout.reconfigure(errors="replace")`, guarded for older Pythons, or re-encoding before
printing) belongs in front of every script in this class, not a fix inside one caller alone. No live
repro attempted -- reasoned from the code and the sibling pattern, not an observed crash.

**To reproduce a decode failure deliberately:** set
`git config core.quotepath false` in the fixture repo first, or git
quotes any non-ASCII path as backslash-octal-escaped ASCII that can
never fail. And on Python >= 3.10 monkeypatch `locale.getencoding`, not
`locale.getpreferredencoding` -- `subprocess._text_encoding()` calls the
former (PEP 597).
