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
python3 scripts/assemble_changelog.py --check-links
python3 scripts/assemble_changelog.py --version X.Y.Z   # release only: rewrites CHANGELOG.md, deletes fragments
```

## Until this repo has a tracker

Fragments are keyed on issue numbers, and this repo has no issues yet. Writing one now would mean
inventing a number, which is worse than the conflicts fragments exist to prevent — an invented
reference points somewhere, and later points at someone else's issue.

So `CHANGELOG.md` stays hand-edited under `## [Unreleased]` until the first issue exists, and the
first fragment is written against a real number. The policy is not aspirational; it is waiting on
the one input it cannot fabricate.
