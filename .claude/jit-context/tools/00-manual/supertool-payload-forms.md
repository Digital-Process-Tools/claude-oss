---
title: "gh-issue-create / gh-pr-create / gh-issue-comment take a JSON or TOML payload, never a .md"
description: "Passing a markdown file to an @FILE op fails with 'Expected = after a key in a key/value pair'. Convert to JSON, or TOML literal strings -- basic strings eat backslash escapes. A literal block also does ZERO escape processing of its own, so doubling a backslash out of Python-string reflex writes the double, not the one you meant."
tool: Bash
match: ~gh-issue-create|gh-pr-create|gh-issue-comment|gh-pr-edit|paste:@|edit:@
mode: once
---

The `@FILE` in these ops is a **payload**, not the body text. A plain markdown file fails:
`ERROR: failed to parse payload: Expected '=' after a key in a key/value pair` (JSON or TOML with
`title`/`body` expected). `gh-issue-create`/`gh-pr-create` want `title`+`body`;
`gh-issue-comment`/`gh-pr-edit` want `body` (or `body_file`). Paid at least twice already.

Cheapest conversion, keeping the markdown file as the thing you actually edit:

```bash
python3 - issue.md issue.json <<'PY'
import json, sys
raw = open(sys.argv[1]).read()
title, body = raw.split("\n", 1)
json.dump({"title": title.strip(), "body": body.strip(), "labels": ["bug"]},
          open(sys.argv[2], "w"), indent=2)
PY
```

**Hand-written TOML: use a triple-single-quoted literal block, never a triple-double-quoted basic
one.** A basic string processes escapes, so a body containing `\n` inside backticks (a regex, a
`sed` expression) silently becomes a real newline.

**Inside a literal block, type a real embedded newline -- never a typed `\n` standing in for one.**
The typed form is two characters, not a line break, and it can succeed silently rather than refuse:
for `edit`/`paste` writing into a `.py` file, a typed `\n` is itself valid Python (a backslash-n
string literal), so `py-syntax` passes while the string's runtime value silently changed. A
single-line payload works either way, which is why several single-line edits can mask the pattern
until a multi-line one fails or partially matches (`old string not found ... nearest match at
line N (70%)`).

**Labels are exact repo spellings, not conventions.** `priority-high`, not `priority:high`; check
with `gh-labels` rather than guessing, or the create refuses after you have written the whole
body.

**A `''' ... '''` TOML literal block also fires for `paste:@-`/`edit:@-`, not only the `gh-*`
ops above, and the reflex that trips there is the opposite kind of mistake.** Coming from Python
source, where `\n` inside a string literal is a one-character escape, the habit is to double a
backslash as though the TOML layer will also interpret one -- it will not: a literal block writes
the exact bytes typed, so doubling turns one real backslash into two literal ones plus whatever
followed. Refused with the line/column of the offending run and two opposite fixes (meant AS
WRITTEN vs. meant HALF); read which one applies before resending, and if a payload genuinely mixes
a real doubled backslash (a Windows-path example inside a docstring) with content that needs
correcting, add `literal_backslashes = true` at the payload's top level, or scope it to one field
with `literal_backslashes = ["content"]`, rather than fighting the refusal occurrence by occurrence
(#1628).
