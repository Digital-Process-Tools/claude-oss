#!/usr/bin/env python3
"""Whether the auditor's checklist matches the tree it is about to audit.

`commands/release.md` gate 3 already requires the checklist version to be
*recorded before the release-auditor spawn*, in three states -- matches /
differs / could not tell -- and its own text says exactly what happens without
a measurement: the honest answer is always "could not tell", and the rendered
answer is usually nothing at all, because reading two manifests was a step a
human performed by hand and typed into a payload. This is that read, done
mechanically, so the honest answer is the one that actually gets printed.

The two numbers:

  installed   ${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json -- the plugin
              copy the harness will actually load the auditor definition from.
  repo        <repo>/.claude-plugin/plugin.json -- this repository's own
              copy, when this repository is the one that ships the
              definitions being audited (this repo, claude-oss, is that
              repository; most repos this plugin manages are not, and do not
              carry this file at all).

Three states, matching the gate's own vocabulary exactly:

  matches         both manifests read and their versions are equal.
  differs         both manifests read and their versions disagree. Both
                  numbers are named. Never a verdict about whether the skew
                  mattered -- see `definitions` below.
  could-not-tell  either manifest is absent, unreadable, not JSON, or carries
                  no string 'version' -- including the ordinary case of a repo
                  that only installed the plugin and never shipped its own
                  .claude-plugin/plugin.json at all. It never renders as a
                  match: a manifest this script could not read is not
                  evidence that the two are the same.

This gate **annotates, it does not block** (`commands/release.md` says so in
as many words, and blocking on a skew nobody chose would trade a reporting gap
for a release nobody can cut) -- so every state exits 0. The state itself,
never the exit code, is what a caller reads.

## `definitions`: evidence, not a verdict

A version skew answers "an old checklist ran". It does not answer whether
that checklist would have said anything different -- and #538 was filed
because, once, a human answered that second question by hand: diffing the
auditor's own definition, `agents/auditor.md`, and the ranking table
`skills/manager/SKILL.md` owns, and finding the ranking rows byte-identical.

So when the state is `differs`, this module compares those three files, PLUS
every `agents/*.md` path one of the three names in its own text -- e.g.
`agents/auditor.md` delegating its platform band to `agents/developer.md`
rather than reading it (#547) -- byte-for-byte between the two trees, and
reports each as `identical`, `differs`, or `could-not-tell` (a file present on
one side only, or an unreadable one, is not silently skipped).

**This is not a semantic verdict, and callers must not read it as one.** A
byte-identical ranking table is evidence that nothing in it moved; it is not
proof that nothing *relevant* moved elsewhere in the two trees -- prose above
or below the table, a file this gate does not name, a change to how the
auditor is dispatched. The base three are stable because they are what gate 3
itself reads directly; the derived files on top of them are only as complete
as what those three name in their own prose, which #547 is the record of once
falling short of what they actually delegate to.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

STATE_MATCHES = "matches"
STATE_DIFFERS = "differs"
STATE_COULD_NOT_TELL = "could-not-tell"

EXIT_OK = 0

MANIFEST_REL = (".claude-plugin", "plugin.json")

#: The files gate 3's own release-auditor spawn reads directly: its own
#: definition, the per-PR auditor definition it may reference, and the ranking
#: table the manager skill owns. Not the full coverage set on its own -- see
#: `_derive_definition_files` below, which is what `compute()` actually
#: compares. #547: `agents/auditor.md` delegates its whole platform band to
#: `agents/developer.md` by naming it in prose rather than reading it, so a
#: fixed list beside this one went stale the moment that delegation was
#: written, silently, with nothing to say the coverage had narrowed.
DEFINITION_FILES = (
    "agents/release-auditor.md",
    "agents/auditor.md",
    "skills/manager/SKILL.md",
)

#: Matches a bare `agents/<name>.md` path the way these files actually write
#: one -- inside a backtick span, often prefixed `${CLAUDE_PLUGIN_ROOT}/`. Not
#: anchored to the prefix: the goal is "this text names a file", not "this
#: text names it in one specific way", because the second is exactly the kind
#: of narrow match a later rewording slips past.
_AGENT_FILE_RE = re.compile(r"agents/[A-Za-z0-9_.-]+\.md")

DEF_IDENTICAL = "identical"
DEF_DIFFERS = "differs"
DEF_COULD_NOT_TELL = "could-not-tell"


def _one_line(text, limit=200):
    """Text from outside this script (an OS error, a path), one printable line."""
    flat = " ".join(str(text).split())
    safe = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in flat)
    return safe[:limit]


def _read_version(manifest_path):
    """``(version, reason)``. On success ``reason`` is ``None``; on failure
    ``version`` is ``None`` and ``reason`` says why, in one printable line.
    """
    try:
        # UnicodeDecodeError is a ValueError, not an OSError -- a manifest that is
        # not valid UTF-8 would otherwise raise out of this function and crash a
        # gate whose whole contract is "never blocks, always could-not-tell".
        raw = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, "{0} could not be read: {1}".format(
            manifest_path, _one_line(exc)
        )
    try:
        data = json.loads(raw)
    except ValueError as exc:
        return None, "{0} is not valid JSON: {1}".format(
            manifest_path, _one_line(exc)
        )
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str) or not version:
        return None, "{0} has no string 'version' field".format(manifest_path)
    # A manifest is written by whoever controls that plugin copy, and its
    # 'version' field reaches receipt() and a release report unchanged. Flatten
    # it the same way _one_line already flattens every other foreign string in
    # this file, so a newline in a version cannot forge a receipt line the way a
    # commit subject forging release_delta.py's output was already flagged for.
    return _one_line(version, limit=80), None


def _referenced_agent_files(text):
    return sorted(set(_AGENT_FILE_RE.findall(text)))


def _derive_definition_files(plugin_root, repo):
    """`DEFINITION_FILES` plus every `agents/*.md` path one of those files
    names in its own text (#547) -- the mechanism `agents/auditor.md` uses to
    delegate its platform band to `agents/developer.md` instead of reading it
    directly. The coverage set is derived from what the gate's own definitions
    actually reference, so a new delegation reaches this comparison the moment
    it is written rather than waiting for someone to notice the list beside it
    went stale.

    Reads whichever tree has each base file (repo first, since a repo missing
    a file entirely is the ordinary case for most managed repositories, then
    the installed copy) -- a base file unreadable on BOTH sides adds nothing
    from it, same as before this derivation existed; that file's own row is
    still `could-not-tell` via `_compare_definitions`, so nothing is silently
    dropped, only not derived from.
    """
    found = set()
    for rel in DEFINITION_FILES:
        text = None
        for root in (repo, plugin_root):
            path = root.joinpath(*rel.split("/"))
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            break
        if text is not None:
            found.update(_referenced_agent_files(text))
    ordered = list(DEFINITION_FILES)
    for rel in sorted(found):
        if rel not in ordered:
            ordered.append(rel)
    return tuple(ordered)


def _compare_definitions(plugin_root, repo):
    """Per-file receipt over `_derive_definition_files(plugin_root, repo)`.
    Never a relevance verdict -- see the module docstring's `## definitions`
    section for what this is and is not evidence of.
    """
    rows = []
    for rel in _derive_definition_files(plugin_root, repo):
        installed_path = plugin_root.joinpath(*rel.split("/"))
        repo_path_ = repo.joinpath(*rel.split("/"))
        try:
            installed_bytes = installed_path.read_bytes()
        except OSError as exc:
            rows.append(
                {
                    "path": rel,
                    "state": DEF_COULD_NOT_TELL,
                    "detail": "installed copy: {0}".format(_one_line(exc)),
                }
            )
            continue
        try:
            repo_bytes = repo_path_.read_bytes()
        except OSError as exc:
            rows.append(
                {
                    "path": rel,
                    "state": DEF_COULD_NOT_TELL,
                    "detail": "repo copy: {0}".format(_one_line(exc)),
                }
            )
            continue
        rows.append(
            {
                "path": rel,
                "state": DEF_IDENTICAL if installed_bytes == repo_bytes else DEF_DIFFERS,
                "detail": "",
            }
        )
    return rows


def compute(repo=".", plugin_root=None):
    """The three-state skew payload. Never raises; a failure to read either
    manifest is `could-not-tell`, not an exception a caller has to guard.
    """
    repo_path = Path(repo)

    root_value = plugin_root
    source = "--plugin-root" if plugin_root else None
    if not root_value:
        env_value = os.environ.get("CLAUDE_PLUGIN_ROOT")
        if env_value:
            root_value = env_value
            source = "CLAUDE_PLUGIN_ROOT"

    base = {
        "plugin_root": root_value,
        "plugin_root_source": source,
        "installed_version": None,
        "installed_manifest": None,
        "repo_version": None,
        "repo_manifest": None,
        "definitions": None,
    }

    if not root_value:
        return dict(
            base,
            state=STATE_COULD_NOT_TELL,
            reason=(
                "CLAUDE_PLUGIN_ROOT is unset and no --plugin-root was given, so "
                "which checklist is running is unknown"
            ),
            detail="",
        )

    plugin_root_path = Path(os.path.expanduser(str(root_value)))
    installed_manifest = plugin_root_path.joinpath(*MANIFEST_REL)
    base["installed_manifest"] = str(installed_manifest)
    installed_version, installed_err = _read_version(installed_manifest)
    if installed_version is None:
        return dict(
            base,
            state=STATE_COULD_NOT_TELL,
            reason=(
                "the installed plugin's manifest could not be read, so its "
                "checklist version is unknown"
            ),
            detail=installed_err or "",
        )
    base["installed_version"] = installed_version

    repo_manifest = repo_path.joinpath(*MANIFEST_REL)
    base["repo_manifest"] = str(repo_manifest)
    repo_version, repo_err = _read_version(repo_manifest)
    if repo_version is None:
        return dict(
            base,
            state=STATE_COULD_NOT_TELL,
            reason=(
                "this repository's own .claude-plugin/plugin.json could not be "
                "read, so either it does not ship these definitions or its "
                "version is unknown"
            ),
            detail=repo_err or "",
        )
    base["repo_version"] = repo_version

    if installed_version == repo_version:
        return dict(
            base,
            state=STATE_MATCHES,
            reason=(
                "the installed checklist ({0}) matches this repository's own "
                "version".format(installed_version)
            ),
            detail="",
        )

    definitions = _compare_definitions(plugin_root_path, repo_path)
    return dict(
        base,
        state=STATE_DIFFERS,
        reason=(
            "the installed checklist ({0}) differs from this repository's own "
            "version ({1})".format(installed_version, repo_version)
        ),
        detail="",
        definitions=definitions,
    )


HEADINGS = {
    STATE_MATCHES: "matches",
    STATE_DIFFERS: "differs",
    STATE_COULD_NOT_TELL: "could not tell",
}


def receipt(payload):
    """One block a human reads. Annotates only -- see the module docstring."""
    lines = ["checklist-skew: {0}".format(HEADINGS[payload["state"]])]

    def row(label, value):
        if value not in (None, ""):
            lines.append("{0:<19}: {1}".format(label, value))

    row("reason", payload["reason"])
    row("detail", payload["detail"])
    row("plugin root", payload.get("plugin_root") or "UNSET")
    row("plugin root from", payload.get("plugin_root_source"))
    row("installed manifest", payload.get("installed_manifest"))
    row("installed version", payload.get("installed_version"))
    row("repo manifest", payload.get("repo_manifest"))
    row("repo version", payload.get("repo_version"))

    definitions = payload.get("definitions")
    if definitions:
        lines.append(
            "definitions        : evidence only -- identical is not proof "
            "nothing relevant moved"
        )
        for d in definitions:
            lines.append("  {0:<28}: {1}".format(d["path"], d["state"]))

    lines.append(
        "gate                : ANNOTATES -- this never stops the release. "
        "could-not-tell never renders as a match."
    )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Compare the installed auditing plugin's version to this "
            "repository's own, in three states: matches, differs, "
            "could-not-tell. Annotates; never blocks."
        ),
    )
    parser.add_argument("--repo", default=".", help="repository to read (default: .)")
    parser.add_argument(
        "--plugin-root",
        default=None,
        help=(
            "the installed plugin root to read (default: $CLAUDE_PLUGIN_ROOT). "
            "Neither present is could-not-tell, never a match."
        ),
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the payload instead of the receipt"
    )
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass

    payload = compute(args.repo, args.plugin_root)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(receipt(payload))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
