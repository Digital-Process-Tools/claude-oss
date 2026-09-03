---
title: "Workflows this plugin owns: two constraints the forge imposes"
description: "A forge reads workflows only from .github/workflows/ itself -- no subdirectories, and a symlink there fails outright. A workflow calling a plugin path is red on day one."
match: (^|/)\.github/workflows/
---

- **A forge reads workflows only from `.github/workflows/` itself.** Subdirectories are unsupported
  and a symlink there fails outright. That is why the `oss-` filename prefix is the only ownership
  signal available — there is no directory to put owned files in.
- **A workflow calling a plugin path is a red build on day one.** CI checks out the managed
  repository and nothing else; the plugin is not there. Owned scripts ship into `.oss/` for exactly
  this reason, and a workflow step must call `.oss/<script>`, never `${CLAUDE_PLUGIN_ROOT}/...`.
