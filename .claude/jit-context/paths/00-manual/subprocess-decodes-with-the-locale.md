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

**To reproduce a decode failure deliberately:** set
`git config core.quotepath false` in the fixture repo first, or git
quotes any non-ASCII path as backslash-octal-escaped ASCII that can
never fail. And on Python >= 3.10 monkeypatch `locale.getencoding`, not
`locale.getpreferredencoding` -- `subprocess._text_encoding()` calls the
former (PEP 597).
