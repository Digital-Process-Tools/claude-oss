---
title: "Read, Edit, Write, Glob and Grep go through supertool"
description: "supertool has an op for every one of these; the call is refused and the reader is told which op replaces it -- and, if none of them run, how to tell a missing binary from a missing entry point."
tool: Read|Edit|Write|Glob|Grep
match: ~.*
mode: block
---

There is no read, edit, write, glob or grep that cannot go through `supertool`. Use the op that
replaces the call just refused:

- **Read** -- `supertool 'read:PATH'`
- **Edit** -- `supertool 'edit:@-'` (a TOML payload on stdin) or `supertool 'edit:::OLD:::NEW:::PATH'`
- **Write** -- `supertool 'paste:@-'` (a TOML payload on stdin, fields `path` and `content`) or
  `supertool 'paste:::PATH:::CONTENT'` -- `paste` creates missing parent directories and rewrites an
  existing file, so it covers both halves of a Write
- **Glob** -- `supertool 'glob:PATTERN'`
- **Grep** -- `supertool 'grep:PATTERN:PATH'`

No exception for an image, a PDF or a notebook cell: none exists in this repository today. If one
appears, that is when it gets one -- not before.

## If none of those run

**This rule cannot tell whether `supertool` is reachable from where you are, and it fires the
same way either way.** A rule is a text file the hook matches a subject against; it runs no
command. Nor did whatever wrote this file check on your behalf -- it ran once, elsewhere, on
somebody else's machine, possibly months ago. So the check is yours to make, and it is two
commands rather than one, because there are two routes and they fail differently:

```bash
./supertool 'ops'
supertool 'ops'
```

- **The first prints a list of ops.** Everything is wired; the refusal above was about your call.
- **The first is missing and the second works.** The binary is installed and *this clone* has no
  entry point. `./supertool` is gitignored on purpose -- committing it would bake one machine's
  absolute path into every other clone -- and it is created by supertool's own session-start
  hook, so a fresh clone has none until a session has been started in it. Start one, or call
  whichever spelling answers. **Nothing is missing from your installation.**
- **Neither runs.** `supertool` is **not installed** on this machine, and no op above will work
  until it is. That is a missing dependency, not a mistake in what you were doing. It is a Claude
  Code plugin and a declared dependency of the plugin that wrote this layer, so installing that
  plugin resolves it from the same marketplace.

**The presence of this file says nothing about your machine.** It is committed to this repository
and travels to every clone, including yours. It is enforced only where `claude-jit-context` is
also installed -- that plugin is what reads this layer and issues the refusal -- so a clone with
neither plugin is unaffected by it.
