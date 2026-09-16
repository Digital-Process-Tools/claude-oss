---
title: "gh-issue-create / gh-pr-create / gh-issue-comment take a JSON or TOML payload, never a .md"
description: "Passing a markdown file to an @FILE op fails with 'Expected = after a key in a key/value pair'. Convert to JSON, or TOML literal strings -- basic strings eat backslash escapes."
tool: Bash
match: ~gh-issue-create|gh-pr-create|gh-issue-comment|gh-pr-edit
mode: remind
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
