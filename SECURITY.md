# Security Policy

## Reporting a vulnerability

Please report security issues privately, through this repository's **Security** tab ->
**Report a vulnerability**. Do not open a public issue for anything exploitable.

Include what you did, what happened, and what you expected. A proof of concept helps
and is not required.

## What to expect

An acknowledgement, then an assessment of severity. Anything in these classes is fixed
and released before it is discussed publicly:

- **destroys** -- data is gone with no copy anywhere
- **discloses** -- something private leaves the machine
- **containment** -- code reads or writes outside the directory it was given
- **forges** -- text you wrote in an issue, a comment or a log is read back as this
  project's own output, so a stranger's words steer a maintainer's session

That list is about **disclosure timing**, and it is narrower than the set of defects that
are **release-blocking** here. A defect that is already public the moment it ships -- a
path or a value true of one machine, baked into the released artifact -- is fixed just as
urgently and can be **reported in the open**, because there is no window of private
knowledge for an embargo to protect. If you are unsure which you have, report it privately
and we will tell you.

## Scope

This project runs inside a developer's session with access to their files and their
credentials. Reports about that boundary are in scope and are taken seriously, including
ones where the failure needs an unusual configuration to reach.
