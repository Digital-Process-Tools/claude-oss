#!/usr/bin/env python3
"""Whether the auditor's checklist matches the tree it is about to audit.

`commands/release.md` gate 3 already requires the checklist version to be
*recorded before the release-auditor spawn*, in four states -- matches /
differs / not applicable / could not tell -- and its own text says exactly
what happens without a measurement: the honest answer is always "could not
tell", and the rendered answer is usually nothing at all, because reading two
manifests was a step a human performed by hand and typed into a payload. This
is that read, done mechanically, so the honest answer is the one that
actually gets printed.

The two numbers:

  installed   ${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json -- the plugin
              copy the harness will actually load the auditor definition from.
  repo        <repo>/.claude-plugin/plugin.json -- this repository's own
              copy, when this repository is the one that ships the
              definitions being audited (this repo, claude-oss, is that
              repository; most repos this plugin manages are not, and do not
              carry this file at all).

Four states. #659: this module used to fold two different questions into one
`could-not-tell` -- "which checklist is running" (answerable whenever the
installed manifest reads) and "does this repo's own copy diverge" (genuinely
inapplicable for the ordinary managed repo, which ships neither its own
manifest nor the checklist's definition files at all). A release gated over a
repo like that reported "could not tell" for a comparison it was in fact able
to name half of. The two questions now render as two different states:

  matches         both manifests read, both sides ship the checklist's
                  definitions, and the versions are equal.
  differs         both manifests read, both sides ship the checklist's
                  definitions, and the versions disagree. Both numbers are
                  named. Never a verdict about whether the skew mattered --
                  see `definitions` below.
  not-applicable  the installed checklist's own version IS known, but this
                  repository ships none of the checklist's own definition
                  files -- so there is nothing of its own on disk to compare
                  that version against. `installed_version` is always
                  populated here; `repo_version` may or may not be (a repo
                  that ships no definitions commonly ships no manifest of its
                  own either, but #580's case -- a readable, unrelated
                  plugin's own manifest -- lands here too, with
                  `repo_version` naming that unrelated plugin's number
                  purely for the receipt, never compared against anything).
                  This is the ordinary shape for most repos this plugin only
                  installs into. Never rendered as `could-not-tell`: the
                  checklist that ran is not in doubt here, only whether a
                  divergence check has a subject.
  could-not-tell  the installed checklist's own version could NOT be
                  established -- no plugin root, an absent/unreadable/
                  non-JSON installed manifest, or one with no string
                  'version' field. Also could-not-tell when this repo DOES
                  ship at least one of the checklist's own definition files
                  (so a divergence check has a real subject) but this repo's
                  own manifest could not be read -- there the comparison
                  applies and simply cannot be carried out. Never renders as
                  a match: a manifest this script could not read is not
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

So whenever the installed checklist's own version could be read -- `matches`,
`differs` and `not-applicable` alike, #659 widened this from "both manifests
readable" to "the installed one is readable", since the repo side not
shipping a manifest is exactly the ordinary `not-applicable` case and the
question this section answers does not depend on it -- this module compares
those three files, PLUS every `agents/*.md` path one of the three names in
its own text -- e.g. `agents/auditor.md` delegating its platform band to
`agents/developer.md` rather than reading it (#547) -- byte-for-byte between
the two trees, and reports each as `identical`, `differs`, or
`could-not-tell` (a file present on one side only, or an unreadable one, is
not silently skipped).

#572: the comparison used to run only under `differs`, on the reasoning that
an equal version number meant nothing to check. That left the byte comparison
skipped in the one state this repository is always in at release time -- an
equal version number is not a promise the two trees are otherwise identical,
and `matches` now carries `definitions` too, so a config drift under an
unmoved version number is not silently unreported. The state name still
answers the version question alone; a `matches` payload carrying a `differs`
row is a config finding the release report must quote, exactly as it already
does under `differs`.

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
STATE_NOT_APPLICABLE = "not-applicable"

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

#: The same mechanism one directory over. `skills/manager/SKILL.md` is a base
#: file above, and it defers each phase of the loop -- the ranking table's own
#: consumers among them -- to `skills/manager/phases/*.md`, naming each path in
#: its own index. A fixed list here would have gone stale at the moment of that
#: split for exactly the reason #547 records: the coverage set narrowed and
#: nothing said so. Derived, so a phase file added later is compared the moment
#: the spine names it.
_SKILL_FILE_RE = re.compile(r"skills/[A-Za-z0-9_.-]+/(?:phases/)?[A-Za-z0-9_.-]+\.md")

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
    """Every definition-shaped path this text names -- agent definitions and
    the manager skill's own phase files alike. One function rather than two,
    because the question is the same one in both directories: which files does
    the thing gate 3 reads depend on?
    """
    found = set(_AGENT_FILE_RE.findall(text))
    found.update(_SKILL_FILE_RE.findall(text))
    return sorted(found)


def _derive_definition_files(plugin_root, repo):
    """`DEFINITION_FILES` plus every `agents/*.md` path one of those files
    names in its own text (#547) -- the mechanism `agents/auditor.md` uses to
    delegate its platform band to `agents/developer.md` instead of reading it
    directly. The coverage set is derived from what the gate's own definitions
    actually reference, so a new delegation reaches this comparison the moment
    it is written rather than waiting for someone to notice the list beside it
    went stale.

    Reads BOTH trees for each base file and unions what each one references --
    not just whichever resolves first (self-review finding: when the two
    copies differ, a reference the OTHER copy names would otherwise be
    silently unseen -- the same "coverage set narrower than what it depends
    on" shape this function exists to close, one level up). This function now
    runs whether the manifest versions agree or not (#572) -- a base file
    unreadable on BOTH sides contributes nothing, same as before this
    derivation existed; that file's own row is still `could-not-tell` via
    `_compare_definitions`, so nothing is silently dropped, only not derived
    from.
    """
    found = set()
    for rel in DEFINITION_FILES:
        for root in (repo, plugin_root):
            path = root.joinpath(*rel.split("/"))
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            found.update(_referenced_agent_files(text))
    ordered = list(DEFINITION_FILES)
    for rel in sorted(found):
        if rel not in ordered:
            ordered.append(rel)
    return tuple(ordered)


def _repo_definition_presence(plugin_root, repo):
    """``(present, total)`` over `_derive_definition_files(plugin_root, repo)`:
    how many of the derived definition files exist in the repo tree.

    #580: a manifest read succeeding is not proof this repository ships the
    checklist being audited -- a managed repository can carry its own,
    unrelated `.claude-plugin/plugin.json` (a different plugin entirely,
    with its own version number that has nothing to do with `oss`'s). Zero
    present is that repository saying, in the only vocabulary it has, that it
    does not ship these definitions at all -- the version comparison then has
    no subject. `total` is always >= `len(DEFINITION_FILES)` (3), so a caller
    never has to guard against a division-by-nothing case that cannot occur.
    """
    rels = _derive_definition_files(plugin_root, repo)
    present = sum(1 for rel in rels if repo.joinpath(*rel.split("/")).is_file())
    return present, len(rels)


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
    """The four-state skew payload. Never raises; a failure to read the
    installed manifest is `could-not-tell`, not an exception a caller has to
    guard -- and a repo that ships none of the checklist's own files is
    `not-applicable`, not `could-not-tell`, whenever the installed version is
    still known.
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

    # #659: "which checklist ran" is already answered above -- installed_version
    # is set. From here the only open question is whether THIS repo's own copy
    # diverges, and that is a separate axis from whether its manifest happens
    # to be readable: reading the repo manifest and deriving/comparing the
    # definition files are both attempted regardless, and it is `present`
    # (does this repo ship the checklist's own files at all), not
    # `repo_version`, that decides whether the divergence question has a
    # subject.
    repo_manifest = repo_path.joinpath(*MANIFEST_REL)
    base["repo_manifest"] = str(repo_manifest)
    repo_version, repo_err = _read_version(repo_manifest)
    base["repo_version"] = repo_version

    definitions = _compare_definitions(plugin_root_path, repo_path)
    present, total = _repo_definition_presence(plugin_root_path, repo_path)

    if present == 0:
        # #580 found this case; #659 corrected its rendering. A readable repo
        # manifest is not proof this repo ships the checklist -- it may be a
        # different plugin's own manifest entirely -- and an unreadable one is
        # the ordinary shape for a repo that only installed the plugin. Either
        # way, zero of the derived definition files existing in the repo tree
        # means the divergence comparison has no subject. That is not the same
        # fact as "the checklist version is unknown" -- installed_version is
        # right there -- so this is `not-applicable`, never `could-not-tell`.
        if repo_version is not None:
            subject = (
                "this repository's own .claude-plugin/plugin.json could be "
                "read ({0}), but none of the checklist's {1} definition "
                "file(s) are present in this repository -- it does not ship "
                "these definitions, so there is nothing of its own to "
                "compare the installed checklist's version ({2}) "
                "against".format(repo_version, total, installed_version)
            )
        else:
            # _read_version always names a reason when version is None, so
            # repo_err is populated on this branch -- this is the ordinary
            # "never shipped a manifest at all" shape, not an unreachable
            # default.
            subject = (
                "the installed checklist is {0}; this repository ships none "
                "of its {1} definition file(s), and its own .claude-plugin/"
                "plugin.json is unavailable too ({2}) -- the checklist "
                "version is known, there is simply nothing on this "
                "repository's own disk to compare it against".format(
                    installed_version, total, repo_err or "no reason given"
                )
            )
        return dict(
            base,
            state=STATE_NOT_APPLICABLE,
            reason=subject,
            detail="",
            definitions=definitions,
        )

    if repo_version is None:
        # This repo DOES ship at least one of the checklist's own definition
        # files -- a real subject for the divergence check -- but its own
        # manifest could not be read, so the comparison applies and simply
        # cannot be carried out. Unlike the present == 0 branch, this IS the
        # "which of the two matches" question left unanswered.
        return dict(
            base,
            state=STATE_COULD_NOT_TELL,
            reason=(
                "this repository ships {0} of the checklist's {1} definition "
                "file(s), but its own .claude-plugin/plugin.json could not be "
                "read, so its version is unknown and cannot be compared to "
                "the installed checklist ({2})".format(
                    present, total, installed_version
                )
            ),
            detail=repo_err or "",
            definitions=definitions,
        )

    if installed_version == repo_version:
        return dict(
            base,
            state=STATE_MATCHES,
            reason=(
                "the installed checklist ({0}) matches this repository's own "
                "version".format(installed_version)
            ),
            detail="",
            definitions=definitions,
        )

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
    STATE_NOT_APPLICABLE: "not applicable",
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
        "could-not-tell/not-applicable never render as a match."
    )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Compare the installed auditing plugin's version to this "
            "repository's own, in four states: matches, differs, "
            "not-applicable, could-not-tell. Annotates; never blocks."
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
