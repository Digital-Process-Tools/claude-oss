# Changelog fragments

One file per pull request, so two open PRs never touch the same file and stop conflicting on every
merge. `CHANGELOG.md` is assembled from these at release time and the fragments are deleted.

## Naming

```
<issue>.<section>.md
```

`<section>` is a Keep a Changelog heading, lowercased: `added`, `changed`, `deprecated`, `removed`,
`fixed`, `security`.

## Body

A single top-level `-` list. No headings, no raw HTML, no unclosed fences. Name the issue in the
text — the file name is metadata, and metadata does not survive being read out of context.

```markdown
- The tag pattern is inferred from tags that already exist and stays null when none are recognised.
  Guessing `v{version}` against a repo tagging `rel-1.2` opens a second tag namespace nobody
  notices until a release goes missing from it (#12).
```

## Checking and folding

```bash
python3 scripts/assemble_changelog.py --check
# `--untagged 0.1.0`: that section was never tagged and has no release page, so no
# `releases/tag/v0.1.0` link is expected for it. Same declaration the changelog workflow
# passes; drop it and this refuses (#93).
python3 scripts/assemble_changelog.py --check-links --untagged 0.1.0
# Release only: rewrites CHANGELOG.md, deletes fragments. Both flags are required (#67) —
# the fold will not derive its own target.
python3 scripts/assemble_changelog.py --version X.Y.Z --dir changelog.d --changelog CHANGELOG.md
```

## Which number

GitHub issues and pull requests share one numbering, so `<issue>` above is whichever of the two the
change is actually filed under — most fragments in this directory are keyed to the pull request
that shipped the fix, because that is the number that already existed, not a tracking issue opened
first to have something to key against. Use the real number, whichever kind it is; do not invent one.
