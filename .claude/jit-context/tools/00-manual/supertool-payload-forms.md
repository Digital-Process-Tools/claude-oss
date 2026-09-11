---
title: "gh-issue-create / gh-pr-create / gh-issue-comment take a JSON or TOML payload, never a .md"
description: "Passing a markdown file to an @FILE op fails with 'Expected = after a key in a key/value pair'. Convert to JSON, or TOML literal strings -- basic strings eat backslash escapes."
tool: Bash
match: ~gh-issue-create|gh-pr-create|gh-issue-comment|gh-pr-edit
mode: remind
---

The `@FILE` in these ops is a **payload**, not the body text. A plain markdown file fails:

    ERROR: failed to parse payload: Expected '=' after a key in a key/value pair
    (at line 1, column 7) (expected JSON or TOML with title/body)

`gh-issue-create` and `gh-pr-create` want `title` + `body`; `gh-issue-comment` and `gh-pr-edit` want
`body` (or `body_file`). The error names the fix, so it costs one round trip — **each time**, and it
has been paid at least twice: once when this was first logged, and again on 2026-09-05 filing two
issues and a comment in one session, by someone who had read the fragment.

Cheapest conversion, and it keeps the markdown file as the thing you actually edit:

```bash
python3 - issue.md issue.json <<'PY'
import json, sys
raw = open(sys.argv[1]).read()
title, body = raw.split("\n", 1)
json.dump({"title": title.strip(), "body": body.strip(), "labels": ["bug"]},
          open(sys.argv[2], "w"), indent=2)
PY
```

**If you hand-write TOML instead, use literal strings (`'''`), never basic strings (`"""`).** Basic
strings process escapes, so a body containing `\n` inside backticks — writing about a regex, a
locator, a `sed` expression — silently becomes a real newline in the published issue.

**Inside a TOML literal string, a typed `\n` is two characters, not a newline -- and it can
silently "succeed" instead of refusing.** For a payload body this creates a real newline in the
wrong place (the bug above). For a supertool `edit`/`paste` `old`/`new` payload writing into a
`.py` file, it is worse: the doubled sequence (a typed `\n` standing in for a real line break) is
*itself* syntactically valid Python -- a string literal containing a backslash and an `n` -- so
`py-syntax` validation passes and nothing catches that the string's runtime *value* changed. When
the match instead simply fails, the tool's own refusal (`old string not found ... nearest match at
line N (70%)`) is a partial score, not 0%, because everything except the line-break substring
matched -- which reads like a fuzzy-anchoring problem rather than what it actually is. **For a
multi-line `old`/`new` payload, type a real embedded newline inside a triple-single-quoted TOML
block; never a typed `\n` standing in for one.** A single-line payload with no line break at all
works either way, which is why several single-line edits can succeed and mask the pattern until a
multi-line one fails.

**Labels are exact repo spellings, not conventions.** `priority-high`, not `priority:high`; check
with `gh-labels` rather than guessing, or the create refuses after you have written the whole body.
