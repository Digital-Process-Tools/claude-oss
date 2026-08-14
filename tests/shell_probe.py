"""Pick the shell a launcher suite spawns by measuring it, not by naming it.

`shutil.which("bash")` returns the first entry on PATH called `bash`. That is a
statement about a filename. On a Windows runner it is regularly System32's
`bash.exe` -- WSL's launcher, which is a genuine POSIX shell and still the wrong
binary, because either no distribution is installed or the one that is has never
heard of the `C:` path the test is about to hand it.

So the question asked here is not "what are you called" but "can you see the file
I am going to ask you to run". A candidate is spawned and handed the exact absolute
paths the suite will use; it is chosen only if it answers that it can see all of
them.

Deliberately NOT probed: which tools the candidate finds on PATH. Both launcher
suites pin PATH themselves at run time, so a probe run under the ambient PATH would
be answering a different question than the one the run asks -- the "green probe,
red step" mismatch. File visibility is PATH-independent, which is why it is the
whole measurement.

Three outcomes, and the third is the point: a shell that ran and behaved, a shell
that ran and misbehaved, and no shell that could be resolved or spawned at all.
`report()` renders the third so it can never be read as either of the others.
"""

import os
import shutil
import subprocess
from pathlib import Path

# $0 is the literal "probe"; the witnesses arrive as "$@". One line per witness it
# can see, so a candidate that sees some but not all is distinguishable from one
# that sees none -- a partial answer is a finding, not a pass.
# `echo` rather than `printf`, because the escape this needs would have to survive
# a Python string, a TOML payload and the shell in turn, and each layer that
# processes one is a layer that can silently eat it.
PROBE = (
    "echo shell\n"
    "for p in \"$@\"; do\n"
    "    if [ -f \"$p\" ]; then echo sees; fi\n"
    "done\n"
)

_CACHE = {}


def candidates():
    """Every plausible shell, best-first.

    Nothing here is an install path guessed for a platform: PATH is read, and Git's
    own shell is derived from where `git` actually is, so a runner that puts Git
    somewhere unusual is still covered.
    """
    seen = []

    def add(path):
        # A PATH entry does not have to be a well-formed path, and a Windows one
        # regularly is not. A candidate that cannot even be spelled is not a reason
        # to stop before looking at the next one.
        try:
            if path and str(path) not in seen and Path(path).is_file():
                seen.append(str(path))
        except (OSError, ValueError):
            pass

    add(os.environ.get("OSS_TEST_BASH"))
    add(shutil.which("bash"))
    # Every bash on PATH, not only the first: on Windows the first is WSL's.
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry:
            for name in ("bash", "bash.exe"):
                add(Path(entry) / name)
    # Git ships a shell beside itself, and a Windows runner always has Git.
    git = shutil.which("git")
    if git:
        try:
            home = Path(git).resolve().parent
        except OSError:
            home = None
        if home is not None:
            for base in (home, home.parent):
                for rel in ("bash", "bash.exe", "bin/bash", "bin/bash.exe",
                            "usr/bin/bash", "usr/bin/bash.exe"):
                    add(base.joinpath(*rel.split("/")))
    return seen


def classify(returncode, stdout, expected):
    """The verdict on one answer.

    Split out from the spawn so it can be tested against the exact reply a Windows
    runner produced, on a machine that is not one.
    """
    # WSL answers in UTF-16; dropping the interleaved NULs is what makes its refusal
    # readable in the skip reason instead of a wall of nul bytes.
    said = (stdout or "").replace("\x00", "").split()
    if returncode != 0 or "shell" not in said:
        joined = " ".join(said)
        return False, "exit {}: {}".format(returncode, joined[:160] or "(said nothing)")
    reached = said.count("sees")
    if reached != expected:
        return False, "ran, but saw only {} of the {} paths handed to it".format(
            reached, expected
        )
    return True, "ok, ran and saw all {} paths handed to it".format(expected)


def probe(candidate, witnesses):
    """Spawn it and see. Returns (usable, a line saying what happened)."""
    witnesses = [str(w) for w in witnesses]
    try:
        done = subprocess.run(
            [str(candidate), "-c", PROBE, "probe"] + witnesses,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            errors="replace",
            timeout=120,
        )
    except OSError as exc:
        return False, "not spawnable: {}".format(exc)
    except subprocess.TimeoutExpired:
        return False, "spawned and never answered"
    return classify(done.returncode, done.stdout, len(witnesses))


def attempts(witnesses):
    """Every candidate and what it said, cached per witness set.

    Each suite imports this at module scope, and an uncached probe would respawn
    every candidate once per suite for an answer that cannot have changed.
    """
    key = tuple(str(w) for w in witnesses)
    if key not in _CACHE:
        _CACHE[key] = [(c, probe(c, key)) for c in candidates()]
    return _CACHE[key]


def pick(tried):
    """The first candidate that answered usably, or None.

    First rather than best: `candidates()` is already ordered by preference, and on
    POSIX that keeps the `bash` on PATH as the one that runs.
    """
    for candidate, (ok, _note) in tried:
        if ok:
            return candidate
    return None


def report(tried):
    """Why there is no shell, in the words of the shells themselves.

    A bare "no bash" fires identically where a shell is genuinely absent and where
    one was looked for in the wrong place, and nobody reading a CI log can tell
    those apart. `-rs` is in this repo's addopts, so this reaches the log.
    """
    if not tried:
        return (
            "no usable shell: no candidate was found to try. PATH carries no bash, "
            "and git -- which ships one beside itself -- is at {}.".format(
                shutil.which("git") or "(nowhere on PATH)"
            )
        )
    return (
        "no usable shell. Spawned each candidate and asked whether it could see the "
        "files this suite hands it: "
        + "; ".join("{} -> {}".format(c, note) for c, (_ok, note) in tried)
    )
