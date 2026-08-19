---
title: "Read, Edit, Write, Glob and Grep go through supertool"
description: "supertool has an op for every one of these; the call is refused and the reader is told which op replaces it -- and what to do if supertool is not installed on this machine."
tool: Read|Edit|Write|Glob|Grep
match: ~.*
mode: block
---

**This refusal has two causes and cannot tell them apart. One command can.** Run:

```bash
supertool 'ops'
```

- **It prints a list of ops.** `supertool` is here, and this refusal is about the call: use the
  op that replaces it, below.
- **It says `command not found`, or nothing runs.** `supertool` is **not installed** on this
  machine, and no op below will work until it is. That is a missing dependency, not a mistake in
  what you were doing.

This rule cannot make that check itself. A rule is a text file the hook matches a subject
against; it runs no command, so it fires identically in both situations. Nor can whatever wrote
this file check on your behalf: it ran once, elsewhere, on somebody else's machine.

**The presence of this file says nothing about your machine.** It is committed to this
repository and travels to every clone, including yours. It is enforced only where
`claude-jit-context` is also installed -- that plugin is what reads this layer and issues the
refusal -- so a clone with neither plugin is unaffected by it.

**Getting `supertool`:** it is a Claude Code plugin, and a declared dependency of the plugin that
wrote this layer. Installing that plugin resolves it from the same marketplace; there is nothing
in this repository to install and nothing here to configure.

There is no read, edit, write, glob or grep that cannot go through it. Use the op that replaces
the call just refused:

- **Read** -- `supertool 'read:PATH'`
- **Edit** -- `supertool 'edit:@-'` (a TOML payload on stdin) or `supertool 'edit:::OLD:::NEW:::PATH'`
- **Write** -- `supertool 'paste:@-'` (a TOML payload on stdin, fields `path` and `content`) or
  `supertool 'paste:::PATH:::CONTENT'` -- `paste` creates missing parent directories and rewrites an
  existing file, so it covers both halves of a Write
- **Glob** -- `supertool 'glob:PATTERN'`
- **Grep** -- `supertool 'grep:PATTERN:PATH'`

No exception for an image, a PDF or a notebook cell: none exists in this repository today. If one
appears, that is when it gets one -- not before.
