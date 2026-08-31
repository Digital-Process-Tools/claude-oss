# Changelog fragments

One file per pull request, so two open PRs never touch the same file and stop conflicting on every
merge. `CHANGELOG.md` is assembled from these at release time and the fragments are deleted.

## Naming

```
<issue>.<section>[.<slug>].md
```

`<section>` is a Keep a Changelog heading, lowercased: `added`, `changed`, `deprecated`, `removed`,
`fixed`, `security`. `<slug>` is optional and exists so one issue can file two entries in one
section without the two pull requests colliding on a path, e.g. `878.fixed.second-entry.md`.

## Body

A single top-level `-` list. No headings, no raw HTML, no unclosed fences. Name the issue in the
text — the file name is metadata, and metadata does not survive being read out of context.

```markdown
- The tag pattern is inferred from tags that already exist and stays null when none are recognised.
  Guessing `v{version}` against a repo tagging `rel-1.2` opens a second tag namespace nobody
  notices until a release goes missing from it (#12).
```

## Compatibility, on a `removed` fragment

A `removed` fragment must say whether the removal breaks anything, as an ordinary
bullet in the body:

```markdown
- Compatibility: breaking|compatible - <reason>
```

The release number is proposed from these fragments, and a `removed` fragment that
declares nothing stops the proposal rather than defaulting quietly — a patch bump
over a breaking change is indistinguishable in the tag from a considered one. A word
that is neither `breaking` nor `compatible` stops it too, so a value nothing
recognises never grades as compatible.

The reason after the verdict is required: a bare flag is the same unsourced verdict
one field further along, and the sentence is the part worth having.

Only `removed` is required to carry one. Every other section may, and a fragment that
says nothing is read as compatible with the count of such fragments reported out
loud. A field on every fragment is a field on every fragment to get wrong, so it is
required exactly where the question is genuinely open.

It is a plain bullet rather than front matter, so the assembler needs no special case
and the claim ships into `CHANGELOG.md` where a user reads it, instead of being
metadata deleted at the fold.

## Checking and folding

```bash
python3 scripts/assemble_changelog.py --check
# `--untagged`: that section was never tagged and has no release page, so no
# `releases/tag/v0.1.0` link is expected for it. Drop it and this refuses (#93).
# `0.1.0` is not typed here twice by accident -- it is `changelog_untagged` in
# `.oss.json`, which is where the CI leg and the jit-context rule read it from too, so
# one question has one answer (#101). Change it there, not here.
# Absent/null, `[]` and a list are three different declarations: pass no flag, pass
# `--untagged ''`, or pass the versions. Do not fold the first two together with a
# falsy test -- both are falsy and they do not mean the same thing.
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
