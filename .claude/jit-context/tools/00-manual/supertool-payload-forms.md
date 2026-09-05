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

**Labels are exact repo spellings, not conventions.** `priority-high`, not `priority:high`; check
with `gh-labels` rather than guessing, or the create refuses after you have written the whole body.
