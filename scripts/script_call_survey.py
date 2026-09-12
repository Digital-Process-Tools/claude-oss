"""``script_call_survey`` -- for every ``scripts/<name>.py``, who calls it, and
does that reference actually EXECUTE it (#1416)?

Four things were built in one night, each individually correct, each
correctly described in its own prose, and each never wired to a caller:
triage-after-release (#1386), the curation threshold-route (#1303), the
cohort-freeze marker (#1410), and the manager-in-the-picker
``user_invocable``/``user-invocable`` key mismatch (#1391). No per-file review
catches this class, because every file involved is individually right -- the
gap is between files, and nothing before this compared them.

``tests/test_unwired_scripts_253.py`` already asks whether a script is
referenced **at all**. This module asks a narrower, harder question: does a
reference **run** the script, or does it only **describe** one -- a state
word, a docstring cross-reference, a changelog fragment's own prose? A script
mentioned in ten places and executed in none of them still reads as "covered"
to a reviewer skimming for the name; it is not covered by anything a session
executes.

## Three states, and the third one is load-bearing

* ``called`` -- something under ``commands/``, ``agents/``, ``skills/``,
  ``bin/`` or another ``scripts/*.py`` module invokes it in a form that RUNS:
  a documented command line (a fenced code block or backtick span,
  reusing ``prose_script_refs``'s own windowing) naming ``scripts/<name>.py``
  alongside a runner verb (``python3``/``python``/``bash``/``sh``); or a
  Python ``import <stem>`` / ``from <stem> import ...`` statement, textually,
  in another script or in ``bin/oss-workspace``'s own embedded heredocs
  (which are literal Python source, read as plain text here -- that file has
  no ``.py`` extension and is not markdown, so neither of this module's other
  two readers would otherwise see it at all).
* ``mentioned-only`` -- the script's name appears somewhere in the scanned
  corpus and never in one of the executing forms above; or it appears
  **nowhere at all**. The all-zero case is deliberately folded in here rather
  than given a fourth state: it is the identical finding (a script this
  survey never sees running) at its most extreme, and ``tests/
  test_unwired_scripts_253.py`` is already the dedicated check for "not
  referenced at all" -- this module does not re-derive that as something new,
  only reports which of its own referenced scripts share the same fate.
* ``could-not-tell`` -- the script's own file could not be read (``OSError``
  / ``UnicodeDecodeError``), or one of the roots this survey scans could not
  be listed at all. **Must never render as ``called``**: an unreadable file
  proves nothing about whether anything runs it.

## What is deliberately NOT attempted (the hidden judgment call, named)

A script can be invoked through a command line **assembled at runtime** --
``scripts/lane_setup.py``'s own ``Agent(...)`` call is built from an f-string
that interpolates a variable, never a literal ``scripts/<name>.py``
substring. This module's ``called`` detection requires a literal, concrete
``<name>.py`` -- so a purely runtime-rendered reference produces no match at
all and the script it actually invokes falls to ``mentioned-only`` rather
than a guessed ``called``. This is a deliberate false-negative in exchange
for never guessing what a template resolves to at runtime: attributing an
unresolvable interpolation to one specific script among many would be
exactly the kind of claim this module exists to avoid making about anything
else. When the corpus contains at least one such ambiguous, unattributable
construction (a literal ``scripts/{`` substring, an f-string or ``.format()``
placeholder immediately following the directory name rather than a
concrete filename), ``survey()`` records it as a standalone note rather than
assigning it to any one script's state, precisely because it cannot be
attributed without guessing.

Python 3.9 compatible.
"""

from __future__ import annotations

import re
from pathlib import Path

import doctor
from prose_script_refs import OP_TEXT_ROOTS, _tier2_windows, real_scripts

#: A runner verb, inside the SAME documented-command-line window as a script
#: mention, is what turns a bare name into an executing reference.
_RUNNER_RE = re.compile(r"\b(python3?|bash|sh)\b")

#: `scripts/` immediately followed by an interpolation placeholder rather
#: than a literal filename -- proof an ambiguous, runtime-rendered reference
#: exists somewhere in the corpus, without saying which script it resolves
#: to. See the module docstring's "What is deliberately NOT attempted".
_AMBIGUOUS_RENDER_RE = re.compile(r"scripts/\{")


def _import_pattern(stem):
    """`import STEM` or `from STEM import ...`, at the start of a logical
    line (allowing leading whitespace for an indented import inside a
    function or a try block)."""
    return re.compile(
        r"(?m)^[ \t]*(?:from[ \t]+{0}[ \t]+import\b|import[ \t]+{0}\b)".format(
            re.escape(stem)
        )
    )


def _read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace"), None
    except OSError as exc:
        return None, "{0}: {1}".format(type(exc).__name__, exc)


def _bin_files(root):
    """Every regular file directly under `bin/` -- not recursive, and not
    filtered by extension: `bin/oss-workspace` itself has none, and its
    embedded heredocs are literal Python source read as plain text here."""
    directory = root / "bin"
    state, detail = doctor._dir_state(directory)
    if state == "unreadable":
        return None, ("bin", "unreadable", detail)
    if state != "dir":
        return [], ("bin", "absent", "")
    try:
        files = sorted(p for p in directory.iterdir() if p.is_file())
    except OSError as exc:
        return None, ("bin", "unreadable", "{0}: {1}".format(type(exc).__name__, exc))
    return files, ("bin", "read", "{0} file(s)".format(len(files)))


def survey(plugin_root=None):
    """`(rows, roots, notes)`.

    `rows` is one `(name, state, detail)` per `scripts/<name>.py` on disk,
    sorted by name. `roots` is one `(name, state, detail)` per scanned root
    (`OP_TEXT_ROOTS` plus `bin/` and `scripts/` itself) -- `read` / `absent`
    / `unreadable`, the same three-state shape `prose_script_refs.survey`
    already uses. `notes` is a list of standalone strings for corpus-wide
    facts that cannot be attributed to one script (see the module docstring).
    """
    root = doctor.PLUGIN_ROOT if plugin_root is None else Path(plugin_root)
    scripts_dir = root / "scripts"
    names = real_scripts(scripts_dir)
    roots = []
    if names is None:
        roots.append(("scripts", "unreadable", "scripts/ could not be listed"))
        return [], roots, []
    roots.append(("scripts", "read", "{0} file(s)".format(len(names))))

    # Every scripts/*.py source, read once -- used both for the executing-
    # import scan and for the ambiguous-render note.
    py_texts = []
    unreadable_names = set()
    for name in sorted(names):
        text, error = _read_text(scripts_dir / name)
        if text is None:
            unreadable_names.add(name)
            roots.append(("scripts/" + name, "unreadable", error))
            continue
        py_texts.append(text)

    bin_files, bin_root = _bin_files(root)
    roots.append(bin_root)
    bin_texts = []
    if bin_files:
        for path in bin_files:
            text, error = _read_text(path)
            if text is None:
                roots.append(("bin/" + path.name, "unreadable", error))
                continue
            bin_texts.append(text)

    # Documented command-line windows across the markdown roots.
    windows = []
    for root_name in OP_TEXT_ROOTS:
        directory = root / root_name
        state, detail = doctor._dir_state(directory)
        if state == "unreadable":
            roots.append((root_name, "unreadable", detail))
            continue
        if state != "dir":
            roots.append((root_name, "absent", ""))
            continue
        files, unreadable = doctor._rglob_md(directory)
        for path in files:
            text, error = _read_text(path)
            if text is None:
                unreadable.append(error)
                continue
            windows.extend(_tier2_windows(text))
        if unreadable:
            roots.append(
                (root_name, "unreadable", doctor._one_line("; ".join(unreadable)))
            )
        else:
            roots.append((root_name, "read", "{0} file(s)".format(len(files))))

    import_corpus = py_texts + bin_texts
    ambiguous_render = any(
        _AMBIGUOUS_RENDER_RE.search(text) for text in (windows + import_corpus)
    )

    all_prose_text = "\n".join(windows) + "\n" + "\n".join(import_corpus)

    rows = []
    for name in sorted(names):
        if name in unreadable_names:
            rows.append(
                (name, "could-not-tell", "could not read scripts/{0}".format(name))
            )
            continue
        stem = name[: -len(".py")]
        called_where = None
        for window in windows:
            if name in window and _RUNNER_RE.search(window):
                called_where = "a documented command line"
                break
        if called_where is None:
            pattern = _import_pattern(stem)
            for text in import_corpus:
                if pattern.search(text):
                    called_where = "imported by another module"
                    break
        if called_where is not None:
            rows.append((name, "called", called_where))
            continue
        mentioned = ("scripts/" + name) in all_prose_text
        if mentioned:
            rows.append(
                (name, "mentioned-only", "named in prose, never in an executing form")
            )
        else:
            rows.append(
                (name, "mentioned-only", "not referenced anywhere this survey scanned")
            )

    notes = []
    if ambiguous_render:
        notes.append(
            "at least one runtime-rendered script-path construction (a "
            "'scripts/{' interpolation, never a literal filename) was found "
            "in the scanned corpus. It cannot be attributed to one script "
            "without guessing, so no row above is marked 'called' on its "
            "account -- see 'What is deliberately NOT attempted' in this "
            "module's own docstring."
        )
    return rows, roots, notes
