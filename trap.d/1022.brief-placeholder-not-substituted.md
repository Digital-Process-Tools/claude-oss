Dispatching three lanes this tick (fix/970, fix/971, fix/955), I wrote each brief's "supertool
required" section as a literal template placeholder string ("{{PASTE THE FULL CONTENTS OF
<scratchpad path> HERE}}") instead of actually substituting the blockquote content -- there is no
templating step between composing an Agent() prompt and it being sent; whatever string is typed is
what the agent receives verbatim. Caught it immediately after the three Agent() calls returned,
tried to correct via SendMessage to each agent, and found SendMessage is disabled in this session
(sub-manager included) -- so a placeholder mistake in a brief cannot be fixed after dispatch once
the tool is unavailable, only avoided before it.

Mitigating factor worth knowing: dispatch.md says explicitly this same blockquote is duplicated
into agents/developer.md "on purpose -- a brief has to be self-contained for an agent that never
loads the other," so a developer lane's own system prompt already carries the real content
regardless of what the brief says. The exposure is smaller than it looked, but do not rely on that
as an excuse -- write the actual text, not a placeholder, checked by re-reading the composed prompt
string before the Agent() call, not after.
