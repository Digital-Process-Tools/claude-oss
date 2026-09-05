"""Drive the installed `claude-jit-context` PreToolUse hook, in three states.

Two test modules need this and a second copy would drift: `test_jit_agent_dispatch.py`
asks what the hook does with an `Agent` payload, and
`test_supertool_rule_states_the_absent_case_294.py` asks what a reader actually receives
when a file tool is refused. Both need the same distinction and it is the subject of this
whole area: **a hook that could not be run and a hook that had nothing to say are not the
same answer**, and to a substring test they render identically.

`drive()` therefore returns `(stdout, problem)` and `problem` is `None` only when the hook
really answered. The hook's contract is to print a JSON object on every call -- `{}` is its
way of having nothing to say -- so empty stdout is *no answer*, not a quiet one.

Python 3.9 compatible.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402

HOOK_RELATIVE = ("scripts", "pre-tool-hook.sh")


def hook_path():
    """`(hook, version, why_not)` -- and `why_not` is the load-bearing third state.

    `hook` is `None` whenever nothing can be driven, and `why_not` then says which of the
    three reasons it is, in the words a skip should carry: the dependency is not installed,
    it is installed but ships no hook where its install record points, or there is no bash
    to run it with. A caller that collapsed those into "no hook" would report a runner
    without bash and a dependency that changed its layout as the same finding.
    """
    roots, version = doctor.jit_hook_roots()
    if not roots:
        return (
            None,
            version,
            (
                "the claude-jit-context dependency is not installed here, so nothing about "
                "what its PreToolUse hook does was measured on this runner"
            ),
        )
    hooks = [root.joinpath(*HOOK_RELATIVE) for root in roots]
    hooks = [hook for hook in hooks if hook.is_file()]
    if not hooks:
        return (
            None,
            version,
            (
                "the dependency ({}) is installed but ships no {} where its install record "
                "points, so nothing was driven".format(version, "/".join(HOOK_RELATIVE))
            ),
        )
    if shutil.which("bash") is None:
        return (
            None,
            version,
            (
                "no bash on PATH, so the PreToolUse hook of {} could not be driven".format(
                    version
                )
            ),
        )
    return hooks[0], version, None


def child_env(project):
    """A minimal environment: enough for bash to run, nothing of this session's state."""
    keep = ("PATH", "HOME", "SYSTEMROOT", "WINDIR", "TMP", "TEMP", "LANG", "LC_ALL")
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    env["CLAUDE_PROJECT_DIR"] = str(project)
    return env


def drive(bash, hook, project, payload):
    """`(stdout, problem)`. `problem` is `None` only when the hook actually answered.

    The two failure shapes here render identically to a substring test and must not:

    - the spawn raised, hung past the timeout, or was killed -- `subprocess.run` raises,
      and `TimeoutExpired` is a `SubprocessError`, so a hang arrives here as an exception
      rather than as output
    - the process ran and printed nothing

    Neither is the hook saying "no rule matched". Collapsing either into `""` would let a
    `SENTINEL not in output` assertion pass on a run that measured nothing.

    **`encoding` is pinned and it is not decoration.** Text mode with no `encoding` decodes
    the child's output with `locale.getpreferredencoding(False)` -- cp1252 on a typical
    Windows runner -- under `errors="strict"`. A byte the console codepage has no character
    for then raises `UnicodeDecodeError` *inside* `subprocess.run`, and that is neither an
    `OSError` nor a `SubprocessError`, so it would sail past the `except` below and crash
    the test rather than arriving as a `problem`. That is this module's own contract broken
    by the one line the contract does not cover, on the platform nobody re-reads. The hook
    writes UTF-8; `errors="replace"` means a byte that is somehow not UTF-8 still comes back
    as an answer that fails an assertion, rather than as an exception that reads like a bug
    in the harness.
    """
    try:
        done = subprocess.run(
            [bash, str(hook)],
            input=json.dumps(payload),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=child_env(project),
            universal_newlines=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", "the hook could not be run: {!r}".format(exc)
    if not done.stdout.strip():
        return done.stdout, (
            "the hook printed nothing at all (exit {}), so it did not answer. "
            "stderr: {!r}".format(done.returncode, done.stderr[-400:])
        )
    return done.stdout, None
