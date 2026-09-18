---
title: "A review-brief drafted for FINDINGS: N must ban 'above' and closing tallies, not just require restatement"
description: "scripts/review_return.py classified a fully-stated, three-finding message as referred-not-stated because two findings carried an internal cross-reference back to an earlier paragraph in the same message, and a closing tally line pointed at material outside itself. The content was complete; only the phrasing tripped the classifier."
match: (^|/)agents/(developer/review-return|tick-review|tick-accounting)\.md$
---

**When drafting a brief that expects a `FINDINGS: <n>` reply, state explicitly: never use the word
"above" or any other cross-reference -- even when the referenced material is fully restated in the
same message -- and merge duplicate observations into one finding instead of pointing at an earlier
paragraph.** `scripts/review_return.py --framed -` cannot tell "fully restated but cross-referenced"
from "gestured and lost"; a back-reference decides the classification regardless of whether the
content itself is complete.

**Also ban a closing summary/tally line** ("Findings: 3 (...)") -- it reads as a pointer to material
outside the message even when every item it tallies was already stated in full above it.

Cost when missed: a full extra spawn (the one retry `agents/developer/review-return.md` allows),
reformatting identical content to avoid the trip rather than adding anything new. Found during
self-review of #1656.
