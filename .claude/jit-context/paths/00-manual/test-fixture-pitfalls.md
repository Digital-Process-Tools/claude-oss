---
title: "Writing a test here: seven fixture traps that each cost a CI round"
description: "A fixture is a measurement, not a given. Long paths, permission denies, injected failures and platform differences must be established and skipped with what went untested, never asserted."
match: (^|/)tests/
---

**A condition you did not establish must not be asserted on.** Attempt the exact operation the code
under test performs; when it does not take, `pytest.skip` carrying the platform, the errno and the
sentence naming what went untested.

- **Long-path fixtures: build the length from many short components.** Windows caps the whole path
  at 260, POSIX caps each component at 255. Four nested directories failed all four Windows legs at
  `git init -q: Filename too long`; one 256-byte component then failed all eight POSIX legs. A
  construction that cannot violate either limit is the fix, not shorter names — shortening deletes
  the case on the one platform where paths are long.
- **A permission fixture is a measurement.** Root ignores the mode bit, some filesystems ignore it,
  and Windows' `os.chmod` on a directory toggles a read-only attribute that does not stop a listing.
  Confirm the deny by attempting the operation; never assert on an error code from a table.
- **Patch the method the code under test calls, not a module attribute.** `pathlib` on **3.10 alone**
  binds `_NormalAccessor.open = io.open` at import, so monkeypatching `io.open` injects nothing.
  Patch `Path.write_text` / `Path.read_bytes` — looked up on the class at call time on every version.
  Green on 3.9, 3.11, 3.12 and red on all three OSes at 3.10 is this bug.
- **A stdlib answer is not a constant across interpreter versions.** `ntpath.isabs("/etc/passwd")` is
  `False` on 3.13 and `True` on 3.9-3.12. Do not pin the answer your local interpreter gives; remove
  the dependence on a live `os.path` answer (a fabricated stand-in module, a normalized string test).
- **`pytest.raises(Exception)` does not catch a skip.** pytest's outcome exceptions derive from
  `BaseException`, so a `pytest.skip` inside the block skips the enclosing test — a green tick over
  an assertion that never ran, reported as `1 skipped` where nobody reads it. Pin the outcome type
  when a test's subject is a skip.
- **A guard over "did this platform distinguish these two cases?" asks a control, never a table.**
  Windows folds several Win32 codes onto `ENOENT`; a `winerror in (2, 3)` skip arm cannot report a
  value it does not contain. Open a plainly-missing path of the same shape and compare: identical
  answers mean there is nothing to classify, and it skips carrying both.
- **Pin `PATH`.** With the stub absent, the launcher finds the real `claude` and executes it — a
  suite starting live agent sessions in temp directories.

**A negative assertion needs a positive control**: pair every must-not-fire with a must-fire in the
same fixture, or an assertion that nothing happened also passes when nothing ran.
