---
title: "review_return.py's _BACKREF regex fires on back-reference-shaped phrases quoted inside a code fence"
description: "A message that fully states two findings, one of which quotes example/repro text containing a back-reference phrase inside a fenced code block, is classified referred-not-stated -- _BACKREF has no fenced-code awareness."
match: (^|/)scripts/review_return\.py$
---

**`_BACKREF`/`_BLOCK` operate on raw bytes with no fenced-code-block awareness.** A message can
genuinely, fully state every finding (`FINDINGS: N` plus N complete blocks with mechanism,
severity and reproduction) and still get classified `referred-not-stated` if one finding's own
repro text -- inside a fenced code block, quoted as an EXAMPLE of the very defect being
reported -- happens to contain a back-reference-shaped phrase like "as shown above".

**Confirmed by direct reproduction:** a reviewer message fully stating two findings, one of
whose reproduction quoted `"As shown above, nothing else touched."` as fixture/example text
inside a fenced block, still returned `VERDICT: referred-not-stated` from `review_return.py
--framed`, citing that quoted line as the decisive back-reference -- even though nothing was
actually left unstated.

**Distinct from the case #1727 already fixed:** that fix shields an incidental phrase describing
an already-enumerated finding, confined to a block's own span. This is one level removed: the
back-reference regex's own trigger words appearing inside quoted repro/example content, which is
data being reported, not a gesture pointing outside the message.

**Fix direction (not yet built, a judgement call rather than a mechanical follow-on):** exclude
fenced code-block spans (paired ``` markers) from both the block count and the back-reference
search, the same way `_BLOCK` already excludes indented sub-bullet lines from counting. Whether
this is worth a further hardening round of the same heuristic (#1270, #1327, and this) or whether
fenced-code exclusion is the right shape was left as a judgement for whoever picks this up, not
decided here. **If you rely on this classifier's verdict, read the message yourself when a
finding's own repro text could plausibly contain "above"/"earlier"/"already"-shaped phrasing --
the mechanical verdict can be wrong in the safe-to-verify direction (over-flagging), not the
silent-loss direction, but a caller trusting it blindly still loses real findings for nothing.**

Routed via /oss:curate from `trap.d/1727.review-return-backref-matches-quoted-repro-text.md`.
