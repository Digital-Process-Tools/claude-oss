"""The code-level half of withholding release authority from a sub-manager (#695).

#695 splits the manager into a scheduler that never holds a tick's payload
and a sub-manager that runs exactly one tick and dies with its context. The
issue is explicit that tag-and-publish authority must stay with the
scheduler -- filed separately as the releaser agent, #696 -- and that the
withholding has to be "in the code, not only in prose".

Prose alone was already tried and named as insufficient for a related
boundary in this repository: `CLAUDE.md`'s section on agent tool grants
argues "prose is a request, frontmatter is the boundary" and then shows the
frontmatter half is not enough either once a grant reaches `Bash` (#251, an
audit spawn whose own definition said "annotates, never blocks" and then ran
a write op anyway). The lesson generalises past tool grants: a sentence in
`agents/sub-manager.md` telling it never to run the release phase is exactly
that kind of request, and this module is what makes it a fact a release
script checks for itself instead.

The mechanism is one environment variable, set by whichever agent is running
and read by the release scripts before they do anything else: config read,
notes extraction, the `gh` call. `role_forbids_release` answers the question
in the same three-state shape this repository uses everywhere -- a role that
is not `sub-manager` (including no role at all, the ordinary case for a
human-invoked `/oss:release`) never forbids; a role of exactly
`sub-manager`, folded for case and surrounding whitespace so a brief that
types `Sub-Manager` still trips it, always forbids; there is no third
"unsure" state here because the check is a string comparison against one
known value, not a measurement that can come back inconclusive.
"""

from __future__ import annotations

import os

#: The environment variable a spawned agent sets to declare its own role.
ROLE_ENV = "OSS_AGENT_ROLE"

#: The one role this module knows to forbid. Everything else -- absent,
#: `maintainer`, an unrecognised string -- passes through unforbidden: this
#: is a denylist of exactly one entry, not an allowlist, because the set of
#: roles legitimately entitled to release authority is `.oss.json`'s own
#: `release.authority` question (`oss_config.release_authority`) and this
#: module does not duplicate that answer.
SUB_MANAGER = "sub-manager"


def current_role() -> str | None:
    """The role declared in the environment, or ``None`` if none was set."""
    value = os.environ.get(ROLE_ENV)
    return value if value else None


def role_forbids_release(role: str | None = None) -> bool:
    """Does this role forbid release (tag, publish) authority?

    ``role`` defaults to `current_role()`; pass it explicitly to check a
    role other than the calling process's own environment.
    """
    if role is None:
        role = current_role()
    if role is None:
        return False
    return role.strip().lower() == SUB_MANAGER


def release_refusal(action: str, role: str | None = None) -> dict:
    """A structured refusal for `action`, or a structured non-refusal.

    Always returns a dict with a `forbidden` key so a caller can act on the
    shape without a second branch: `if release_refusal(...)["forbidden"]:`.
    """
    resolved_role = role if role is not None else current_role()
    forbidden = role_forbids_release(resolved_role)
    if not forbidden:
        return {"forbidden": False, "role": resolved_role, "reason": None}
    return {
        "forbidden": True,
        "role": resolved_role,
        "reason": (
            "role {0!r} may not {1}: release (tag, publish) authority is "
            "withheld from the per-tick sub-manager by #695 and stays with "
            "the scheduler until #696 (the releaser agent) gives it a "
            "spawn of its own".format(resolved_role, action)
        ),
    }
