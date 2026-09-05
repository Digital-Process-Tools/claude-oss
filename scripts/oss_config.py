"""Read, validate and derive `.oss.json` -- the per-repo config for the maintainer loop.

Everything the loop used to hardcode lives here instead. Two rules shape this module:

1. **Nothing is invented.** A repo with no labels gets an empty list, never a plausible
   default. An invented value reaches a brief indistinguishable from a measured one.
2. **Absence is a stated outcome, not a silent pass.** Every function returns problems
   by name rather than falling back, because a config that "loaded fine" while missing
   half its keys is the same defect this whole loop exists to catch.

Python 3.9 compatible: no match statements, no `X | Y` annotations.
"""

import json
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
from pathlib import Path

REQUIRED_KEYS = {
    "repo",
    "default_branch",
    "clone",
    "worktree_root",
    "branch_pattern",
    "test_command",
    "version_sites",
    "changelog_dir",
    "docs_targets",
    "labels",
    "state_file",
}

OPTIONAL_KEYS = {
    "milestones", "notes", "release", "changelog_untagged", "watch_channel",
    # #932: a maintainer attestation that this repo's own pytest run measures
    # test duration and coverage -- see doctor_check_test_measurement.py's
    # module docstring for why this is never derived from the config's
    # own content.
    "test_measurement_configured",
    # #779: which changed paths this repository considers user-visible, so the
    # generated changelog gate can exempt a pull request that touches none of
    # them. Absent/null is the default and leaves the gate unconditional, same
    # as before this key existed -- see `user_visible_paths_problem` below.
    "user_visible_paths",
}

# #355: `.oss.json` is JSON, with no comment syntax, so the only place a maintainer
# can record *why* a value is what it is has always been a key -- and every key not
# on the schema was refused as a typo, indistinguishably from one. A leading
# underscore is the declared escape hatch: any such key is maintainer prose,
# skipped by `validate()`, never emitted by this module, and never load-bearing.
# It is deliberately a prefix rather than the one `notes` key already reserved
# above: a note kept *next to* the value it explains (`_milestones_note` beside
# `milestones`) is the property that made the note useful the first time it was
# written, and a single top-level `notes` blob loses that adjacency. The cost is
# real and is not hidden: an underscore typo in a key meant to be load-bearing
# (`_est_command`) is silently accepted as prose rather than refused as a typo --
# accepted because this loop is not the one place a schema-shaped key could be
# born, and drawing the line any narrower reopens the failure this fixes.
_RESERVED_PREFIX = "_"

# Keys this plugin used to write and no longer reads. Tolerated, never emitted, never
# validated -- a type check over a value with no consumer is asserting against nothing.
#
# `ci.required_checks` was deleted in #113. It was a measurement that cannot be taken:
# the only quantity derivable without a run is the workflow *job declaration* count, and
# this repo's own config was the proof that this is not the merge gate's number -- three
# declarations against fourteen check runs, because a 3x4 matrix expands one declaration
# into twelve. A guard asserting the config matched the declarations would have gone
# green over a value wrong by eleven. Beyond a static matrix it is worse still: a
# reusable workflow declares nothing locally, an organisation- or app-level check never
# appears in `.github/workflows/` at all, and a run that has not happened declares
# nothing either. The number is read live off the pull request, where it exists.
#
# They stay in KNOWN_KEYS on purpose. Every `.oss.json` an earlier version wrote still
# carries the block, and a validator that starts refusing it turns a cleanup into a
# breaking change for repos that did nothing.
LEGACY_KEYS = {"ci"}

# The config is two files because its keys have two different owners (#34).
#
# `.oss.json` is the *project's* answer: the repo slug, the tag spelling, what runs the
# tests, which files carry the version. Those are reviewed like any other repo fact and
# must be the same for everyone, so the file is tracked.
#
# `.oss.local.json` is *this machine's* answer: three keys, all of them a directory on
# one person's disk. It is git-excluded and never shared.
#
# The split was not cosmetic. Setup used to write one file and exclude it, so the whole
# `release` block lived on a single laptop. A second maintainer running /oss:release had
# no `tag_pattern`, the documented remedy for that is stop-and-ask, and a repo tagging
# `v1.2.3` can come back with `1.2.4` -- the second tag namespace this module warns
# about, opened by the tool that warns about it.
CONFIG_NAME = ".oss.json"
LOCAL_CONFIG_NAME = ".oss.local.json"

LOCAL_KEYS = {"clone", "worktree_root", "state_file"}

# #608: the three states every consumer of a LOCAL_KEYS value must report, never just
# a value. `configured` -- read from .oss.local.json. `derived, not configured` -- no
# such file, or no such key in it; computed from the repository root instead, same
# convention `_derive_local_config` below has always used. `could-not-derive` --
# neither, with a reason. A value someone chose and a value this script guessed must
# never render the same way to whoever reads the receipt (#608's own acceptance
# condition) -- so every one of these three spellings is a distinct, greppable string,
# not a boolean a caller has to pair with prose of its own.
LOCAL_STATE_CONFIGURED = "configured"
LOCAL_STATE_DERIVED = "derived, not configured"
LOCAL_STATE_COULD_NOT_DERIVE = "could-not-derive"

# What a repo does when it releases differs, so it is configured. What must NEVER be
# configured is the gate list -- default branch green at leg level, nothing mid-review,
# security audit passed, every version site bumped, the tag verified on the remote. A
# gate that can be switched off is switched off on the day it is inconvenient, which is
# the day it existed for. Keys that look like gates are refused, not ignored: an ignored
# key reads as an accepted setting.
RELEASE_KEYS = {
    "tag_pattern",
    "commit_subject",
    "merge_method",
    "triggers",
    "create_release",
    "draft",
    "latest",
    "authority",
}
MERGE_METHODS = {"squash", "merge", "rebase"}
TRIGGER_KEYS = {"merged_prs", "soak_hours"}

# #478: whether this repository has granted the loop authority to tag and publish a
# release without stopping. Per-repository -- CLAUDE.md's governing rule -- because the
# grant used to live only in a per-machine memory file the skill cannot read and a second
# maintainer does not have.
AUTHORITY_LOOP = "loop"
AUTHORITY_MAINTAINER = "maintainer"
AUTHORITY_NOT_DECLARED = "not-declared"
RELEASE_AUTHORITIES = {AUTHORITY_LOOP, AUTHORITY_MAINTAINER}

# Whether the tag becomes a GitHub Release, and what kind (#58).
#
# These are policy, not a gate, and they are policy about a *project* rather than
# about a machine -- every maintainer of a repo should publish the same way -- so they
# live in the tracked `.oss.json` and never in `.oss.local.json`.
#
# The shipped defaults are the conservative ones, and each is conservative about a
# different thing:
#
#   create_release: false  Some projects tag deliberately without releasing. More to
#                          the point, publishing is not this tool's decision to make
#                          on a repo that never asked for it.
#   draft: true            A draft is undoable; a published release has already
#                          notified everyone watching by the time you regret it.
#   latest: false          `Latest` changes what the repo's landing page shows, which
#                          is outward-facing and belongs to whoever owns the page.
#
# Unset is a third state and not a quiet `false`: `release_publish_policy` reports
# `stated`, and `release_publish.py` names the key in its skip reason, so a repo that
# never chose is told what it would set rather than silently not releasing forever.
PUBLISH_KEYS = ("create_release", "draft", "latest")
PUBLISH_DEFAULTS = {"create": False, "draft": True, "latest": False}

VERSION_PLACEHOLDER = "{version}"

# Tag schemes we can recognise from tags that already exist. Anything else stays null:
# guessing `v{version}` against a repo tagging `rel-1.2` opens a second tag namespace
# nobody notices until a release goes missing from it.
TAG_SCHEMES = [
    (re.compile(r"^v\d+\.\d+\.\d+$"), "v{version}"),
    (re.compile(r"^\d+\.\d+\.\d+$"), "{version}"),
]

# Keys whose value may honestly be null. `test_command` is null when the probe could
# not tell what runs the tests, and `changelog_dir` is null when the repo has not
# adopted fragments -- both are findings, and a guess would be worse.
#
# Everything else being null is a hole, not an answer: a config carrying `repo: null`
# passed validation until a test caught it, because the key was present and only its
# type was checked. A present-but-empty key is the same absence, one layer down.
NULLABLE_KEYS = {"test_command", "changelog_dir"}

KNOWN_KEYS = REQUIRED_KEYS | OPTIONAL_KEYS | LEGACY_KEYS
PROJECT_KEYS = KNOWN_KEYS - LOCAL_KEYS

# The one nullable release key that gets a default rather than a stop (#34).
#
# The two nullable keys in the release block are deliberately not symmetric, and the
# asymmetry is the point rather than an oversight: a wrong commit subject is cosmetic and
# revisable in the next commit, while a wrong tag opens a namespace that exists forever.
# So `commit_subject` resolves to a stated default and `tag_pattern` stops and asks. What
# was wrong before was not the asymmetry -- it was that only one of the two said anything,
# so a null `commit_subject` reached an agent that invented a subject line.
#
# `{version}`, not `{tag}`: `_validate_release` refuses any subject without the {version}
# placeholder, so a default spelled the obvious way would be rejected by this same module.
DEFAULT_COMMIT_SUBJECT = "chore(release): {version}"
RELEASE_DEFAULTS = {"commit_subject": DEFAULT_COMMIT_SUBJECT}

# A config file is committed. Nothing in it may look like a credential, and an
# unfamiliar key that does is refused rather than ignored -- ignoring it is how a
# token ends up in git history with everyone assuming the schema rejected it.
SECRET_RE = re.compile(r"(token|password|passwd|secret|api[_-]?key|credential)", re.IGNORECASE)

# `\A...\Z`, not `^...$`, here and for every pattern below that validates a value
# destined for a file this plugin writes. Python's `$` matches **before** a trailing
# newline, so `^...$` accepted `owner/name` and `changelog.d` with a newline glued to
# the end -- and such a newline does not escape a shell quote, it ends the YAML block
# scalar the command sits in, so the generated workflow stops parsing and the
# changelog gate it carries silently stops running (#173).
#
# The anchors live in the pattern rather than at the call site (`fullmatch` would also
# close it) because a later caller reaching for `.match` or `.search` cannot then lose
# them. `scripts/assemble_changelog.py` already spells it this way for the same reason.
#
# The excluded-character class also excludes a backslash (#897). The class used to
# read `[^/\s]`, which keeps a backslash out of neither run -- `owner/..\..\..\x`
# matched, because a backslash is not `/` and is not whitespace. `_derive_local_config`
# folds an unrefused `repo` straight into `state_file` (`.max/{name}-watch.json`), and
# on Windows `ntpath.normpath` resolves a backslash as a separator, so that value could
# walk the write target outside the clone. GitHub's own repo-name rules already exclude
# a backslash, so this tightens the pattern to match what a real value can be rather
# than adding a second check the derivation site would need to remember to call.
REPO_RE = re.compile(r"\A[^/\\\s]+/[^/\\\s]+\Z")


def repo_problem(value):
    """Why this `repo` cannot be used, or None when it is fine.

    A function rather than a bare `REPO_RE.match()` at the one call site so that
    `scaffold.py` can re-check at the moment it renders, the way `fragments_dir()`
    and `untagged_declaration()` already do for the two values that reach the
    generated workflow. `repo` reaches a generated file too -- it is the H1 of the
    CLAUDE.md this plugin writes -- and it had exactly one guard, inside `validate()`,
    which only `plan()` calls. A caller reaching `render()` directly got no check at
    all, which is the same asymmetry #31 closed for `changelog_dir` (#173).

    Null is accepted here and refused one layer up: `repo` is in REQUIRED_KEYS and not
    in NULLABLE_KEYS, so `validate()` already reports a null with the sentence that
    explains why a null is a hole rather than an answer. Repeating it here would put
    two different sentences on one fact.
    """
    if value is None:
        return None
    if not (isinstance(value, str) and REPO_RE.match(value)):
        return "repo: expected 'owner/name', got {!r}".format(value)
    return None


# The consumer of `repo` that did not route through the guard above (#207).
#
# `bin/oss-workspace` derives SUPERTOOL_WATCH_NAME from `repo` at SESSION START --
# before /oss:tick, before doctor, before anything else reads the config -- and did
# it with a bare `re.sub` whose character class permits `.`, `..` and a leading `-`.
# `scaffold.repo_slug` refuses those and `doctor` refuses those; the launcher folded
# them into a name and exported it, and supertool turns that name into a socket path
# and a poller state directory.
#
# The sentence this comment used to open with -- "the ONE consumer of `repo` that did
# not route through the guard" -- was read as a claim that the launcher had no other
# unguarded route to SUPERTOOL_WATCH_NAME, and that was false when it was written.
# The launcher has a second route which does not consume `repo` at all: a `watch_name`
# DECLARED in a managed repository's tracked `.supertool.json`, which it exported
# verbatim (#230). The rule for what a derived name may be therefore is not the whole
# rule for what an EXPORTED name may be, and `watch_name_problem` below is the second
# half. Uniqueness claims in a comment are what stop the next reader looking.
#
# Whether such a name TRAVERSES is a fact about the dependency's path construction
# rather than about this module, and the issue recorded it unestablished. Routing
# through `repo_problem` is what makes the question moot: a validated slug carries
# exactly one slash, the fold below always turns it into a dash, so the result holds
# no separator and can never be `.` or `..` exactly. That claim is a measurement in
# `tests/test_watch_name.py`, which folds every accepted slug in its fixture and puts
# the result through `watch_name_problem`, rather than prose nobody re-checks.
WATCH_NAME_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


#: Whether the loop's own status line spends a detached refresh cycle asking
#: `channel:health` about this repository's watch channel (#613). On by
#: default -- the field exists to surface a dead consumer between ticks, and a
#: repository that opts out is the exception, not the rule. `False` is the only
#: value that turns it off; anything else (absent, `True`) leaves it on, the
#: same "declared-or-not" shape `release_publish_policy`'s `stated` uses for a
#: key whose absence must not read as a decision nobody made.
WATCH_CHANNEL_KEY = "watch_channel"


def watch_channel_enabled(config):
    """Does this repository's status line probe the watch channel at all (#613)?

    `False` only -- anything else, including absence, is "on" by the issue's own
    stated default. A `str`/`int`/`None` spelled like a decision must not read as
    one either way; `validate()` is what tells the maintainer their value will be
    ignored, this accessor just picks the one value that turns the check off.

    Not called from `scripts/statusline.py` itself -- that module has NO
    imports of its own siblings, this repository's own included, because it is
    vendored standalone into `.oss/statusline.py` (its own module docstring
    says so, and `_expected_watch_name`'s docstring in that file says the same
    of the name derivation it copies from `watch_channel_name` below).
    `statusline.py` therefore carries the identical `config.get("watch_channel")
    is not False` check inline, twice, rather than calling this. This accessor
    exists for every OTHER reader of `.oss.json` that is not under that
    constraint -- `doctor.py`, `scaffold.py`, a future one -- so the decision
    has one written home instead of a fresh `is not False` at each call site.
    Self-review finding on this issue: the first draft of this function had no
    caller anywhere in this repository, and its own unit test exercised it in
    complete isolation from `statusline.py`'s inline copies, which could have
    drifted from it silently.
    `tests/test_statusline_channel_613.py::test_statusline_gate_matches_this_accessor`
    now pins the two together across every value this repo's own tests
    exercise for the config key.
    """
    return config.get(WATCH_CHANNEL_KEY) is not False


def watch_channel_name(value):
    """`(name, problem)` -- the watch channel name derived from `repo`, or why not.

    A pair rather than a raise, because the caller is a shell launcher whose job is
    to OPEN A SESSION. A refusal here costs the private channel and nothing else, and
    `bin/oss-workspace` already has three arms that derive nothing, say so on stderr
    and launch anyway: no `.oss.json`, an unreadable one, and one declaring no repo.
    Exiting non-zero would trade the product for an enhancement, and substituting
    some other name would invent a private socket nobody publishes to -- a quiet
    wrong state where the shared default socket is at least a loud one.

    Null is refused here and deferred by `repo_problem`, the one value the two
    disagree on. That deferral exists so `validate()` keeps sole ownership of the
    sentence about a required key being null; nothing in the launcher's path calls
    `validate()`, so an unrefused null would derive the string `None` and export it.

    The fold survives the validation rather than being replaced by it: `REPO_RE`
    accepts any pair of non-slash, non-backslash, non-whitespace runs (#897 added
    the backslash exclusion), so a character a socket path should not carry -- `+`,
    say -- can still reach it.
    """
    if not isinstance(value, str):
        return None, "repo: expected 'owner/name', got {!r}".format(value)
    problem = repo_problem(value)
    if problem:
        return None, problem
    return WATCH_NAME_UNSAFE_RE.sub("-", value), None


# The other two values that reach a file this plugin writes into somebody else's
# repository, and the two #173 did not reach (#180).
#
# `scaffold._render_claude_md` substitutes three things into that repo's CLAUDE.md --
# the file every agent there reads first. #173 gave `repo` a render-time chokepoint
# and left these two with nothing but a `str` type check, in the same function and the
# same commit. That sweep was over the *compiled patterns* in `scripts/`, honestly and
# in both directions; a value with no pattern cannot appear in a sweep of patterns.
# So these are written down beside the values, not beside the mechanism.
#
# Neither of them is a pattern. `test_command` is a shell command and a `\A...\Z`
# allow-list over it is the thing that did not generalise: any pattern loose enough to
# admit `pytest -k 'not slow' | tee out.txt` admits everything that matters anyway.
# What is actually refused is a *character class*, chosen from the harm rather than
# from the shape.

#: Every character `str.splitlines()` treats as ending a line. Written down because
#: `\n` and `\r` are not the whole set -- `\x85` and `\u2028` end a line for Python and
#: for several Markdown renderers, and a validator that knows two of ten leaves the
#: other eight able to put text at column 0. `tests/test_claude_md_injection.py`
#: measures this constant against `splitlines()` rather than trusting it.
LINE_BREAKS = "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"

#: C0 control characters other than tab, plus DEL. None of these belongs in a shell
#: command written into a JSON config, and refusing the class rather than the two
#: characters of the exploit is what keeps the next line terminator from being news.
_CONTROLS = frozenset(chr(point) for point in range(0x20) if point != 0x09) | {"\x7f"}

_TEST_COMMAND_FORBIDDEN = frozenset(LINE_BREAKS) | _CONTROLS


def names_pytest(value):
    """Does this `test_command` name pytest, or at least not name something else?

    `test_command` is an arbitrary shell command -- `npm test`, `go test ./...`,
    `cargo test` are all valid values -- so any advice that is pytest-specific
    (`--durations`, `--cov`, `pyproject.toml`'s `[tool.pytest.ini_options]
    addopts`) has to ask this before it fires. CLAUDE.md's own governing rule,
    one level down from a repository to a language: a fact about one project
    baked into shared code arrives with the authority of a measured one.

    **Absent, empty, or not a string answers True.**

    `doctor_check_test_measurement` is this function's only caller now: it
    keeps asking when the answer is True (nobody probed the command, which is
    not evidence the repo is not Python, and a maintainer reading a
    diagnostic can answer the question in a second) and short-circuits to
    `OK: not applicable` when it is False.

    `scaffold` used to be a second caller, gating its own CLAUDE.md paragraph
    on this same substring match -- and #955 is why it no longer is: the
    match is a substring, not a parse, so it is wrong in both directions over
    an arbitrary shell command (`'npm test --grep pytest'` matches,
    `'make test'` wrapping pytest does not), and scaffold's paragraph is a
    write into somebody else's repository, permanently, in the file every
    session there reads first -- too permanent a place to be wrong. Its
    advice is now runner-neutral instead (see `scaffold.TEST_MEASUREMENT_
    RECOMMENDATION`) and gates only on `test_command` being set, never on
    this predicate.

    A non-string is a schema PROBLEM `check_config` reports; it is not stripped
    out of the config dict a caller holds, so it is answered here rather than
    raising `AttributeError` on `.lower()` and taking a whole diagnostic run
    down with it (#946).
    """
    if not value or not isinstance(value, str):
        return True
    return "pytest" in value.lower()


def test_command_problem(value):
    """Why this `test_command` cannot be used, or None when it is fine.

    A line break and nothing else, and that balance is the whole decision. This value
    is a shell command: it legitimately carries quotes, pipes, `$`, `&&`, `#` and
    backticks, and a rule refusing any of those refuses a legitimate repository to
    close a hole that is not open. It lands inside a fenced code block, where a
    backtick cannot close the fence unless it starts its own line -- so the line break
    is not merely the floor, it is the entire mechanism. The fence is *also* widened at
    render time to outrun any backtick run in the value: two mechanisms, neither of
    them the only one standing there, the same design `changelog_untagged` already has.

    Null is fine and means the probe could not tell what runs the tests; the renderer
    writes the "not detected" paragraph, which is a third state and not a guess.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return (
            "test_command: expected the shell command that runs this repository's "
            "tests as a string, or null when the probe could not tell; got "
            "{!r}.".format(value)
        )
    found = sorted(set(value) & _TEST_COMMAND_FORBIDDEN)
    if found:
        return (
            "test_command: contains {}. This value is written into a fenced block of "
            "the CLAUDE.md generated for another repository -- the file every agent "
            "there reads first -- so a character that ends a line ends the fence and "
            "puts everything after it at column 0, where it is indistinguishable from "
            "prose the maintainer wrote; got {!r}.".format(
                ", ".join(repr(char) for char in found), value
            )
        )
    return None


#: What `git check-ref-format` refuses outright, as characters. Not a transcription of
#: a style guide: these are the bytes git itself will not accept in a ref name, so
#: refusing them cannot refuse a branch that exists. `\x85`, `\u2028` and `\u2029` are
#: added because git tolerates them and this value is written into a Markdown document
#: where they end a line.
#: The control set is built here rather than borrowed from `_CONTROLS`, which carves
#: tab out because a shell command legitimately contains one. A ref name does not: git
#: refuses EVERY ASCII control including tab, so reusing that constant made this set
#: quietly one byte looser than the authority its own docstring cites. Found by review
#: on #180, and it is why `tests/test_claude_md_injection.py` now measures this
#: function against `git check-ref-format` itself instead of asserting the claim.
_REF_CONTROLS = frozenset(chr(point) for point in range(0x20)) | {"\x7f"}

_REF_FORBIDDEN = (
    frozenset(" ~^:?*[") | {"\\"} | _REF_CONTROLS | frozenset(LINE_BREAKS)
)


#: What a watch channel name may not carry, chosen from the harm rather than from a
#: shape -- the same decision `test_command_problem` makes above, and for the same
#: reason: there is no pattern here that is both tight enough to be worth having and
#: loose enough not to refuse a channel that works.
#:
#: The harm is a PATH one. supertool renders the name into a socket path and a poller
#: state directory, so a separator escapes the directory it was meant to name, and a
#: line break or a control character puts arbitrary text into every receipt that
#: quotes it -- including this plugin's own stderr.
#:
#: `_REF_CONTROLS` is reused rather than `_CONTROLS`, which carves tab out because a
#: shell command legitimately holds one. A path component does not, and #180 already
#: paid for a set that was quietly one byte looser than its own docstring.
#:
#: It lives here, below `_REF_CONTROLS` and `LINE_BREAKS`, rather than beside
#: `watch_channel_name` where it reads better: both names are defined further down
#: this file, and the first draft of this constant sat above them and raised
#: `NameError` at import. Module order is not a style question.
_WATCH_NAME_FORBIDDEN = (
    frozenset("/") | {chr(92)} | _REF_CONTROLS | frozenset(LINE_BREAKS)
)


def watch_name_problem(value):
    """Why this watch channel name cannot be used AS A PATH COMPONENT, or None.

    The single statement of that narrower question, for BOTH routes that produce
    a name. `bin/oss-workspace` reads a name declared in a managed repository's
    tracked `.supertool.json` and derives one from `repo` when nothing declares it;
    #207 guarded the second and left the first exporting whatever it read, so the
    guard and its bypass sat a few lines apart in one file (#230). The launcher now
    calls this once, after the two routes converge, which is what makes "no bypass" a
    property of the code rather than a promise: there is nowhere else a name is made.

    It is NOT the single statement of what a watch channel name may be, full stop --
    that was #533's own reading of an earlier draft of this docstring, and it is
    exactly the false authority that let doctor's watch-channel check clear a name
    this function accepts and supertool discards. This function does not decide
    whether the CONSUMER will accept the name. supertool has its own `NAME_RE`,
    which caps the length at 32 and constrains the first character, and it is the
    one that decides delivery. Transcribing that pattern here would put a second
    spelling of somebody else's rule in this repository to drift -- the thing #207
    declined to do and this repo's own rules forbid -- and it would take a working
    private channel away from any repository whose consumer accepts a name this
    copy does not, which is exactly what a raised cap in a later supertool would
    produce. That question is asked of the installed consumer AT RUN TIME and
    REPORTED, never refused, in the two places a name is put in front of a human:
    `bin/oss-workspace`'s ASK_CONSUMER block (#231) and `doctor.check_watch_channel`
    via `_consumer_watch_name_verdict` (#533). Neither asks here, because this
    function runs whether or not supertool is installed at all.

    So the floor is narrow on purpose: what is refused here is refused because this
    plugin can argue the harm on its own, knowing nothing about the dependency. A
    name this function clears is a name that is SAFE TO EXPORT, not a name that
    is USABLE -- the two questions have different authorities and only the second
    one decides whether the channel is private or shared.

    A bare `str` return rather than the `(name, problem)` pair `watch_channel_name`
    hands back: this validates and never derives, so there is no second value.
    """
    if not isinstance(value, str):
        return (
            "watch name: expected the channel name as a string, got {!r}".format(value)
        )
    if not value:
        return (
            "watch name: it is empty, and an empty path component names the directory "
            "above rather than a channel"
        )
    found = set(value) & _WATCH_NAME_FORBIDDEN
    # `isspace()` rather than a space literal: the set above already holds every line
    # break, and what is left is the rest of Unicode's whitespace, which a socket path
    # can technically carry and no receipt quoting it can be read against.
    found |= {char for char in value if char.isspace()}
    if found:
        return (
            "watch name: contains {}. The consumer renders this value into a socket "
            "path and a poller state directory, so a separator escapes the directory "
            "it was meant to name and a line break puts arbitrary text into every "
            "receipt that quotes it; got {!r}".format(
                ", ".join(repr(char) for char in sorted(found)), value
            )
        )
    if value in (".", ".."):
        return (
            "watch name: {!r} names a directory that already exists rather than a "
            "channel".format(value)
        )
    return None


def _git_ref_problem(name):
    """Why `git check-ref-format` would refuse `name`, as a phrase, or None."""
    if not name:
        return "it is empty"
    found = sorted(set(name) & _REF_FORBIDDEN)
    if found:
        return "it contains {}".format(", ".join(repr(char) for char in found))
    if name == "@" or "@{" in name:
        return "'@' alone and the sequence '@{' are reserved by git"
    if ".." in name:
        return "it contains '..'"
    if name.startswith("-"):
        return (
            "it starts with '-', which every command line built from it reads as an "
            "option rather than as a branch"
        )
    if name.startswith("/") or name.endswith("/") or "//" in name:
        return "it has an empty path component"
    if name.endswith("."):
        return "it ends with a dot"
    for component in name.split("/"):
        if component.startswith(".") or component.endswith(".lock"):
            return (
                "the component {!r} starts with a dot or ends with '.lock'".format(
                    component
                )
            )
    return None


def default_branch_problem(value):
    """Why this `default_branch` cannot be used, or None when it is fine.

    Not a pattern either, and for the opposite reason to `test_command`: there is an
    authority for this value's shape and it is not this file. `git check-ref-format`
    decides what a branch may be called, so the rule is transcribed from it rather
    than invented -- which is what makes "keep every value that validates today
    validating" checkable instead of hopeful. A name git would refuse cannot be any
    repository's default branch.

    That rule already excludes every line terminator, since git forbids all ASCII
    control characters and the space. The three Unicode terminators git tolerates are
    added, because the harm here is Markdown rather than git: this value is written
    into a code span of a generated CLAUDE.md, and a backtick in it is handled at
    render time by widening the span rather than by refusing a name git allows.

    Null is accepted here and refused in two other places, each with its own sentence:
    `validate()` reports it as a required key that is null, and `scaffold` refuses to
    render, because "Default branch `None`" is an invented fact in a generated file.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return (
            "default_branch: expected the branch name as a string; got "
            "{!r}.".format(value)
        )
    problem = _git_ref_problem(value)
    if problem:
        return (
            "default_branch: {}, so git itself would refuse it as a ref name. It is "
            "also written into a code span of the CLAUDE.md generated for another "
            "repository, where a character that ends a line puts the remainder at "
            "column 0; got {!r}.".format(problem, value)
        )
    return None


def branch_pattern_problem(value):
    """Why this `branch_pattern` cannot be used, or None when it is fine.

    Not a git ref by itself -- it carries a literal placeholder (`fix/{issue}`) no
    single branch ever has -- so this is not "would git accept this as a ref". It
    is the same question `default_branch_problem` asks for the same reason: the
    value is written into a code span of a generated CONTRIBUTING.md (#460), and
    CommonMark decides block structure -- where a paragraph or a heading starts --
    before an inline span is parsed, so a blank line or a heading marker inside the
    "span" is read as real document structure regardless of the backticks around
    it, the same seam #180 closed for `default_branch` and `test_command`.

    `_git_ref_problem`'s character class already excludes every line break and
    control character for exactly that reason, and it is reused rather than a
    second class invented beside it: every pattern this plugin ships or a
    maintainer would plausibly write (`fix/{issue}`, `issue-{issue}`, a nested
    `area/{issue}`) contains only `/`, letters, digits and the placeholder's own
    braces, none of which `_git_ref_problem` forbids, so nothing that already
    passes today would start failing.

    Null is accepted here and refused one layer up, matching every other
    render-time funnel in this file: `branch_pattern` is required and
    non-nullable in `REQUIRED_KEYS`, so `validate()` already reports a null with
    its own sentence.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return "branch_pattern: expected the pattern as a string; got {!r}.".format(value)
    problem = _git_ref_problem(value)
    if problem:
        return (
            "branch_pattern: {}. It is written into a code span of the "
            "CONTRIBUTING.md generated for another repository, where a character "
            "that ends a line puts the remainder at column 0, outside the span, as "
            "real Markdown structure; got {!r}.".format(problem, value)
        )
    return None


# `changelog_dir` is the one value in this file that becomes shell source. `scaffold.py`
# substitutes it into a `run:` line of the workflow it writes into somebody else's
# repository, so a value carrying `$(...)` is a command that runs in their CI -- and this
# module checked every other key and not that one (#31).
#
# The shape is one or more path segments of letters, digits, dot, dash and underscore.
# That admits `changelog.d`, `news.d` and a nested `docs/changelog.d` -- nesting works,
# the scaffold creates parent directories -- and admits nothing a shell, a regex or a
# path resolver reads as an instruction. Tighter than this refuses a legitimate repo to
# close a hole that quoting already closes; looser is theatre.
#
# Anchored `\A...\Z` per the note on REPO_RE: `^...$` admitted a trailing newline, and
# this value lands on four separate lines of the generated workflow, so it was the
# widest instance of that defect rather than the newest (#173).
CHANGELOG_DIR_RE = re.compile(r"\A[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*\Z")


def changelog_dir_problem(value):
    """Why this `changelog_dir` cannot be used, or None when it is fine.

    Null is fine and means the repo has not adopted fragments. A non-string is not: it
    used to travel all the way to `str.replace()` and raise a TypeError from inside the
    renderer, which is a crash wearing the same hat as the gap above.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return (
            "changelog_dir: expected a relative directory path as a string, or null "
            "when the repo has no fragment practice; got {!r}.".format(value)
        )
    if not CHANGELOG_DIR_RE.match(value) or any(
        segment in (".", "..") for segment in value.split("/")
    ):
        return (
            "changelog_dir: expected a relative path of plain segments, such as "
            "'changelog.d' or 'docs/changelog.d'; got {!r}. This value is written into "
            "a `run:` line of the workflow generated for another repository, so a value "
            "a shell would read as an instruction is refused rather than quoted and "
            "hoped about.".format(value)
        )
    return None


# The directory `scripts/scaffold.py` falls back to when `changelog_dir` is null and it
# creates the fragment machinery anyway -- see `scaffold.fragments_dir`. Kept here, not
# there, because a reader on this side of the boundary (`release_version.py`) needs the
# same number without importing scaffold's much heavier module (#299).
DEFAULT_FRAGMENTS_DIR = "changelog.d"

# The one path a generated changelog gate can live at: a forge reads workflows only
# from `.github/workflows/` itself, subdirectories are unsupported and a symlink there
# fails outright, so the fixed `oss-` filename prefix IS the ownership signal --
# `scaffold.py`'s own `_detect_changelog_gate` excludes this exact name for the same
# reason. Declared once here so a second reader does not retype it and drift (#299).
OWNED_CHANGELOG_WORKFLOW = ".github/workflows/oss-changelog.yml"


# The `--dir` argument `scaffold.CHANGELOG_WORKFLOW` writes on every line that invokes
# the assembler, always single-quoted -- see `render_owned` in scaffold.py. A hand-edited
# workflow might not quote it the same way, so double quotes and a bare token are also
# read: what matters is the value the CI leg actually gates on, not policing how it is
# spelled.
#
# The whitespace between `--dir` and its value is deliberately `[ \t]+`, not `\s+`
# (#347). `\s` admits a newline, so a bare `--dir` at the end of a line let the
# bare-token alternative reach across it and capture the FOLLOWING flag -- `--changelog`
# -- as though it were the directory. `--changelog` is built from characters
# `CHANGELOG_DIR_RE` admits, so it then passed directory-name validation too: a flag,
# accepted as a value. `--dir` and its argument are always written on the same line by
# `render_owned`, so restricting the gap to same-line whitespace changes nothing for a
# well-formed workflow and stops the reach for a malformed one.
#
# The trailing alternative matches a `--dir` that carries no argument at all: same-line
# whitespace (possibly none) followed by the end of the line, the end of the text, or an
# unquoted token that itself starts with `-`. That last part of the lookahead closes the
# same defect one clause over: `--dir --changelog CHANGELOG.md` on ONE line, no newline
# anywhere, is exactly as ambiguous with the following flag as the newline-crossing case
# -- an unquoted token that starts with `-` cannot be told apart from another CLI flag,
# whether or not a line break separates it from `--dir`. The unquoted-value alternative's
# `(?!-)` excludes that same shape from ever being captured as a value in the first
# place, so it always falls through to "no value" instead. A QUOTED value starting with
# `-` is unaffected either way -- `--dir '-x'` is unambiguously a value, because quoting
# is what removes the ambiguity with a flag, not the character itself.
#
# None of this touches `changelog_dir_problem`: no captured value is ever refused on
# content by this pattern, only recognised or not recognised as a value at all. #345's
# argument was one value, one rule; a value that was never captured has no content for
# that rule to apply to, which is why the bare/ambiguous case is a new EXTRACTION state
# (`present-bare-dir`, below) rather than a second rule bolted onto the existing one.
GATE_DIR_RE = re.compile(
    r"--dir(?:[ \t]+(?:'([^']*)'|\"([^\"]*)\"|(?!-)(\S+))|[ \t]*(?=-|\r?\n|\Z))"
)


def _gate_directories(text):
    """(values, bare) -- every distinct `--dir` value named in a generated changelog
    workflow's text, and whether any `--dir` occurrence carried no argument at all.

    An EMPTY value counts. `--dir ''` and a workflow carrying no `--dir` line at all
    are two different facts about a repository, and this used to return them both as
    the empty set -- so the empty spelling inherited the other one's answer, `present`,
    and a workflow that named something inadmissible fell silently back to
    `DEFAULT_FRAGMENTS_DIR`. No escape, but a directory nobody named, which is what
    #299 and #325 are both about. The refusal that belongs to it is applied by the
    caller, on the same rule as every other inadmissible value.

    Which group participated is what selects the value, not which one is truthy: with
    `or` chaining, a matched-but-empty quoted group fell through to the two groups that
    did not participate and produced `None`, which is the same collapse one level down.

    A match where NONE of the three groups participated is the trailing alternative in
    `GATE_DIR_RE` above -- a `--dir` with no argument on its line (#347) -- and it is
    reported back as `bare` rather than folded into `values`, for the same reason: it
    is not a value nobody confirmed, it is no value at all.
    """
    values = set()
    bare = False
    for match in GATE_DIR_RE.finditer(text):
        captured = False
        for value in match.groups():
            if value is not None:
                values.add(value)
                captured = True
                break
        if not captured:
            bare = True
    return values, bare


def scaffolded_changelog_gate(repo_root):
    """(state, detail) for whether THIS repo's own scaffolded gate is on disk, and which
    directory it polices (#299, #325, #343, #347).

    `changelog_dir: null` is ambiguous on its own: it means "never adopted fragments"
    for a hand-maintained repo, and it also means "adopted through scaffold.py's
    fallback, and nobody has recorded the directory it picked" for a repo scaffold
    just ran on -- `/oss:scaffold --apply` writes the fragment directory and the
    gating workflow without writing `changelog_dir` itself (`commands/scaffold.md`).
    A reader that cannot tell the two apart either refuses fragments that are sitting
    on disk with a CI leg already gating on them, or -- worse -- has to guess a
    directory nobody named, which is exactly the silent-wrong-answer failure the
    `could-not-decide` state exists to avoid.

    "present" answers only the ownership question: our workflow, at the one path a
    forge will read it from, and it polices `DEFAULT_FRAGMENTS_DIR` -- either because no
    `--dir` line was found (an older or hand-trimmed workflow) or because every `--dir`
    line names the default explicitly. It says nothing about whether that directory
    exists or holds anything -- callers that need fragments still have to look.

    "present-other-dir" is #325: scaffold does not always pick `DEFAULT_FRAGMENTS_DIR`
    -- it writes a gate policing `fragments_dir(config)`, which is the *named*
    `changelog_dir` when one was set at the time `/oss:scaffold --apply` ran. A repo
    scaffolded with `changelog_dir: "docs/frags"` whose key is later nulled -- legal,
    `changelog_dir` is in `NULLABLE_KEYS`, and `.oss.json` is tracked so it arrives by
    ordinary contribution -- still carries a gate policing `docs/frags`, and `present`
    alone cannot say that. `detail` for this state IS the directory read out of the
    workflow, a relative path string, not a message.

    "present-refused-dir" is #343, and it is the state that says the gate was read
    perfectly well and named something inadmissible. `changelog_dir` has a validating
    rule -- `changelog_dir_problem`, written for #173 because the value becomes a path
    and a shell argument -- and #327 opened a second entrance for the same value, this
    one, which applied none of it. An absolute `--dir` discards the repo root at
    `Path(repo) / detail` and a `..` chain walks out of it, and the directory this
    function names is the one `/oss:changelog` folds, which unlinks every fragment it
    consumes.

    Reviewing that fix turned up the sharper half: the `.oss.json` entrance, which #343
    was filed calling the control, was not guarded either on the paths that matter.
    `changelog_dir_problem` is reached from `validate()`, and neither
    `release_version._read_config` nor `/oss:changelog`'s own resolver calls it -- both
    read the key straight out of the file. Two readers now apply this rule directly, so
    "there is a guard on this value" is a claim about a call site rather than about the
    existence of a function.

    The same rule is applied here rather than a new one, for a reason narrower than
    "it already existed": this is the same key, carrying the same meaning, reaching the
    same two consumers -- a `run:` line of a generated workflow and a fold that deletes
    files under whatever it names. Two rules for one value is how the entrances came to
    disagree in the first place, so `tests/test_gate_dir_validated_343.py` asserts the
    two as an *equivalence* over one value set rather than restating the rule.

    `detail` for this state is a message, deliberately not the directory: `unknown` and
    this share the shape "there is no directory to give you", and a caller that reached
    for `detail` as a path would get a sentence rather than a plausible-looking escape.

    "present-bare-dir" is #347: a `--dir` occurrence on disk carries no argument at all
    -- the flag, and nothing after it on its own line. This used to be misread as
    "present-other-dir" naming the FOLLOWING flag as the directory, because the old
    pattern's whitespace class crossed the newline between them. It is deliberately not
    folded into "present-refused-dir": that state means a value was captured and does
    not validate, and #345's argument was one value, one rule -- refusing a captured
    token that merely starts with `-` would be a second rule on the same value. Here
    nothing was captured, so there is no value for `changelog_dir_problem` to have an
    opinion about; the defect is in extraction, not in content, so it gets its own state
    rather than a second rule riding on an existing one. `detail` for this state is a
    message, the same shape as "present-refused-dir" and "unknown".

    Six states, and "unknown" must never render as either "present" reading: a wrong
    "absent" here costs a caller its existing loud refusal, unchanged from before this
    function existed; a wrong "present" or "present-other-dir" would pick a directory
    nobody confirmed, which is the one failure this exists to prevent. So an unreadable
    path is reported as "unknown" rather than folded into "absent" -- `os.stat` and its
    exact exception, never `Path.is_file()`, which swallows every `OSError` and answers
    `False` for a directory that exists and cannot be entered (the `doctor.py` trap this
    repo's own `CLAUDE.md` names). The same "unknown" covers a workflow this process can
    stat but not read, and one whose `--dir` lines disagree with each other -- a
    hand-edit leaves no single directory to trust, so this refuses exactly like an
    unreadable path rather than guessing between the two nobody confirmed.
    """
    path = Path(repo_root) / OWNED_CHANGELOG_WORKFLOW
    try:
        mode = os.stat(str(path)).st_mode
    except FileNotFoundError:
        return "absent", ""
    except OSError as exc:
        return "unknown", "{} could not be read: {}".format(path, type(exc).__name__)
    if not stat.S_ISREG(mode):
        return "absent", "{} exists but is not a regular file".format(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return "unknown", "{} could not be read: {}".format(path, type(exc).__name__)
    directories, bare = _gate_directories(text)
    if bare:
        return "present-bare-dir", (
            "{} has a --dir flag with no argument on its line, so which fragments "
            "this gate polices could not be determined. No caller may resolve "
            "it.".format(path)
        )
    if not directories:
        return "present", ""
    if len(directories) > 1:
        return "unknown", (
            "{} names more than one --dir value ({}); which fragments this gate "
            "polices could not be determined".format(path, ", ".join(sorted(directories)))
        )
    named = next(iter(directories))
    problem = changelog_dir_problem(named)
    if problem:
        return "present-refused-dir", (
            "{} names a --dir of {!r}, which is not a usable fragment directory: "
            "{} No caller may resolve it.".format(path, named, problem)
        )
    if named == DEFAULT_FRAGMENTS_DIR:
        return "present", ""
    return "present-other-dir", named


# The second value in this file that becomes shell source, and it arrives by the same
# route: `scaffold.py` interpolates it into the `--check-links` line of the workflow it
# writes into somebody else's repository (#101, #121).
#
# A version is `x.y.z` and nothing else, so anything else is REFUSED at validation
# rather than escaped at the template. Escaping is a claim about a quoting context that
# the next person to edit the template can invalidate without noticing; a refusal is a
# claim about the value, and it holds wherever the value goes next. The template quotes
# anyway -- two mechanisms, and neither of them the only one standing there.
#
# Not `v1.2.3`: the tag spelling is `release.tag_pattern`'s business, and the audit this
# feeds compares against `## [x.y.z]` headings, which carry the version.
#
# Anchored `\A...\Z` per the note on REPO_RE. The template quoting held, exactly as
# this comment claimed -- and a newline is the one byte that needs no quote to escape:
# it ended the `run:` block scalar instead (#173). Two mechanisms is still the design;
# this is the second one being made to actually hold up its half.
CHANGELOG_UNTAGGED_RE = re.compile(r"\A\d+\.\d+\.\d+\Z")

# A backslash immediately followed by an ASCII letter -- `\d`, `\w`, `\s`, `\A`,
# `\Z`, `\b`, and every other Perl/Python-only escape class share this shape.
# POSIX ERE (what `grep -E` speaks, spliced from `user_visible_paths_problem`
# below) defines no backslash-letter escapes at all; whichever ones a given
# `grep` happens to accept as a GNU extension is a version question this
# validator, running on the maintainer's own machine rather than the release
# runner, has no way to answer -- so the whole class is refused rather than
# allow-listed one construct at a time (#779, found by review).
PERL_ONLY_BACKSLASH_ESCAPE_RE = re.compile(r"\\[A-Za-z]")

# #1018: the previous validator denylisted `'` and `\n` one character at a time
# and missed `\r`, U+2028 (the YAML line separator) and VT (`\x0b`) -- every one
# of them a YAML line break, and each one either silently absorbed into the
# generated `grep -E` alternation (permanent skip, the same failure shape
# `(?...)` above is refused for) or a break in the middle of the workflow's own
# YAML block scalar. `CHANGELOG_UNTAGGED_RE` above is already an anchored
# allow-list rather than a denylist; this is the same shape applied here --
# only printable ASCII, and not the single quote a single-quoted shell literal
# still needs refused, is admitted at all. A denylist grows one incident at a
# time; an allow-list of printable ASCII closes the whole class, known bytes
# and unknown ones alike, by construction.
USER_VISIBLE_PATH_CHAR_RE = re.compile(r"\A[\x20-\x26\x28-\x7e]*\Z")


def changelog_untagged_problem(value):
    """Why this `changelog_untagged` cannot be used, or None when it is fine.

    Three states, all legal, and only the first two mean the same thing:

    * absent or `None` -- nobody declared anything, so every `## [x.y.z]` section is
      expected to carry a link ref. That is the default reading, not a statement.
    * `[]` -- declared empty. This repository states that every release section was
      tagged. Same behaviour, different epistemics, and the receipts keep them apart.
    * `["0.1.0"]` -- declared. Those sections are exempt and the audit names them.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        return (
            "changelog_untagged: expected a list of x.y.z version strings, or null "
            "when nothing has been declared; got {!r}. An empty list is a legal and "
            "different answer -- it says every release section was tagged.".format(value)
        )
    bad = [item for item in value
           if not (isinstance(item, str) and CHANGELOG_UNTAGGED_RE.match(item))]
    if bad:
        return (
            "changelog_untagged: every entry must be an x.y.z version, one per list "
            "item; got {!r}. This value is written into a `run:` line of the workflow "
            "generated for another repository, so anything a shell would read as an "
            "instruction is refused rather than quoted and hoped about. Versions, not "
            "tags: write '0.1.0', not 'v0.1.0'.".format(bad)
        )
    return None


# The lower of the two known grep-family interval limits (#1058). BSD grep
# (what `/usr/bin/grep` is on macOS) enforces `RE_DUP_MAX`, measured directly
# on BSD grep 2.6.0-FreeBSD: `grep -Eq 'a{255}'` exits 1 (an ordinary
# no-match) and `grep -Eq 'a{256}'` exits 2 (SYNTAX ERROR, "invalid
# repetition count(s)"). GNU grep documents a higher limit (32767), so 255 is
# the binding constraint across both grep families this validator can name --
# a bound above it is refused regardless of which grep the release runner
# happens to carry.
_GREP_INTERVAL_MAGNITUDE_LIMIT = 255


def _brace_interval_problem(pattern):
    """None, or why a `{...}` in `pattern` is a POSIX ERE interval bound
    `grep -E` reads as malformed, rather than a genuine no-match.

    `re.compile` gives no signal here: `a{1,2,3}` is not a valid Python
    interval either, so Python reads it as eight literal characters and
    never raises. Measured directly against both BSD grep (what
    `/usr/bin/grep` is on macOS) and ugrep: `a{1,2,3}` (three counts, ERE
    allows at most two) and an unbalanced `a{` (no closing `}`) both exit 2,
    SYNTAX ERROR -- indistinguishable, in the generated
    `if ! grep -Eq PATTERN; then skip; fi` guard, from a genuine no-match
    (#1015, found by review). `{`, `}`, digits and `,` are all otherwise
    safe, allow-listed characters, so this is checked separately from
    `USER_VISIBLE_PATH_CHAR_RE` above: only the *arrangement* was checked
    there -- this function also checks the *magnitude*: `a{99999}` is a
    well-formed interval bound Python's own grammar has no opinion on, but
    it exceeds `RE_DUP_MAX` on BSD grep and the documented limit on GNU
    grep alike, so `grep -Eq` exits 2, SYNTAX ERROR, on it too (#1058, found
    by review) -- the identical silent-disable failure #1015 closed at the
    arrangement boundary, reopened at the magnitude boundary instead.

    Bracket expressions (`[...]`) are skipped while scanning: a `{` inside
    one can never be a POSIX ERE interval opener, so it is not interval
    syntax at all and must not be misread as an unbalanced or malformed one
    (#1059, found by review).
    """
    index = 0
    length = len(pattern)
    while index < length:
        char = pattern[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            content_start = index + 1
            if content_start < length and pattern[content_start] == "^":
                content_start += 1
            if content_start < length and pattern[content_start] == "]":
                content_start += 1
            close = pattern.find("]", content_start)
            if close == -1:
                index += 1
                continue
            index = close + 1
            continue
        if char == "{":
            close = pattern.find("}", index + 1)
            if close == -1:
                return "has an unbalanced `{` with no matching `}`"
            content = pattern[index + 1:close]
            match = re.match(r"\A(\d+)(,(\d*))?\Z", content)
            if not match:
                return (
                    "has `{{{}}}`, which is not a well-formed interval bound "
                    "-- expected `{{m}}`, `{{m,}}` or `{{m,n}}`".format(content)
                )
            low = int(match.group(1))
            high = match.group(3)
            if high:
                if int(high) < low:
                    return (
                        "has `{{{}}}`, whose lower bound is greater than its "
                        "upper bound".format(content)
                    )
            bounds = [low] + ([int(high)] if high else [])
            over_limit = [b for b in bounds if b > _GREP_INTERVAL_MAGNITUDE_LIMIT]
            if over_limit:
                return (
                    "has `{{{}}}`, whose bound {} exceeds {}, the lower of "
                    "the known grep-family interval limits (BSD grep's "
                    "measured RE_DUP_MAX; GNU grep documents a higher one) "
                    "-- `grep -Eq` exits 2, SYNTAX ERROR, on a magnitude "
                    "this large, the same silent-disable failure as an "
                    "unbalanced or malformed interval".format(
                        content, max(over_limit), _GREP_INTERVAL_MAGNITUDE_LIMIT
                    )
                )
            index = close + 1
            continue
        index += 1
    return None


def user_visible_paths_problem(value):
    """Why this `user_visible_paths` cannot be used, or None when it is fine.

    Null is the default and means nobody has told the generated changelog gate
    which paths are user-visible for this repository, so every non-empty diff
    with no fragment still fails -- exactly the behaviour before this key
    existed (#779).

    A declared value becomes a `grep -E` pattern spliced, single-quoted, into a
    `run:` line of the workflow generated for another repository -- the same
    surface `changelog_dir_problem` above already refuses a shell-breaking
    value on, so a quote character here is refused for the identical reason
    rather than shipped as an injection surface waiting for the first
    contributor to (accidentally or not) close that literal early.

    `[]` is refused rather than accepted as "declared, and nothing is
    user-visible": unlike `changelog_untagged`, where an empty list is a real
    and different answer from null, an empty `user_visible_paths` would turn
    the whole gate off silently for every pull request -- exactly the failure
    the acceptance bar for #779 names by name. Say nothing (null) to keep
    today's behaviour, or name at least one pattern.

    Validated against POSIX ERE, not Python `re`, and that is not a stricter
    reading of the same grammar -- it is the actual one the value runs
    against. The generated workflow splices this pattern into `grep -Eq`,
    which runs POSIX ERE (with GNU extensions the version this validator
    cannot see may or may not carry), on the maintaining repository's own
    `ubuntu-latest` runner, not on whatever machine ran `/oss:scaffold`.
    `re.compile` alone used to accept Perl-only syntax -- `(?=...)`,
    `(?:...)`, `\\d`, `\\w`, `\\s`, `\\A`, `\\Z`, `\\b` -- that `grep -E`
    rejects as a SYNTAX ERROR (exit 2) at runtime, and the generated guard
    (`if ! grep -Eq PATTERN; then skip; fi`) cannot tell that apart from a
    genuine no-match: an accepted-but-unparseable pattern silently and
    permanently disables the changelog gate for the whole repository,
    reopening the exact failure the empty-list refusal above exists to
    close (found by review, #779). So `(?` anywhere, and a backslash
    followed by a letter, are refused outright rather than allow-listed one
    construct at a time -- which GNU-extension escapes a given `grep`
    happens to support is a version question this validator has no way to
    answer from here.
    """
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        return (
            "user_visible_paths: expected a non-empty list of regex strings, or null "
            "to leave the generated changelog gate unconditional (today's default "
            "behaviour); got {!r}. An empty list is refused rather than read as "
            "'nothing is user-visible', which would silently turn the gate off for "
            "the whole repository.".format(value)
        )
    for index, pattern in enumerate(value):
        if not isinstance(pattern, str) or not pattern:
            return (
                "user_visible_paths[{}]: expected a non-empty regex string; got "
                "{!r}.".format(index, pattern)
            )
        if not USER_VISIBLE_PATH_CHAR_RE.match(pattern):
            return (
                "user_visible_paths[{}]: {!r} carries a character outside printable "
                "ASCII, or a single quote. This value is written into a `run:` line "
                "of the workflow generated for another repository, single-quoted "
                "inside a YAML block scalar -- so a single quote would close that "
                "shell literal early, and any byte outside printable ASCII (a "
                "carriage return, U+2028 the YAML line separator, VT, or anything "
                "else) is either a YAML line break this validator has no way to "
                "enumerate by name, or absorbed silently into the grep alternation. "
                "Refused by an anchored allow-list rather than a denylist of the "
                "characters found so far (#1018).".format(index, pattern)
            )
        try:
            re.compile(pattern)
        except re.error as exc:
            return (
                "user_visible_paths[{}]: {!r} is not a valid regular expression "
                "({}).".format(index, pattern, exc)
            )
        if "(?" in pattern:
            return (
                "user_visible_paths[{}]: {!r} uses `(?...)` -- a non-capturing "
                "group, a lookaround or a named group. These are Python `re` syntax, "
                "not POSIX ERE, and this value runs as `grep -E` at release time, on "
                "the generated workflow's own runner. `grep -E` treats this as a "
                "SYNTAX ERROR indistinguishable, in the generated receipt, from a "
                "genuine no-match -- so an accepted pattern like this one silently "
                "and permanently disables the changelog gate rather than exempting "
                "the paths you meant. Write plain groups: `(docs|tests)`, not "
                "`(?:docs|tests)`.".format(index, pattern)
            )
        if PERL_ONLY_BACKSLASH_ESCAPE_RE.search(pattern):
            return (
                "user_visible_paths[{}]: {!r} carries a backslash followed by a "
                "letter. POSIX ERE, which `grep -E` speaks at release time, defines "
                "no backslash-letter escapes at all -- `\\d`, `\\w`, `\\s`, `\\A`, "
                "`\\Z`, `\\b` and similar are Python `re` (or a GNU extension this "
                "validator cannot confirm the release runner's `grep` carries), and "
                "an unrecognised one is the same silent-disable failure `(?...)` is "
                "refused for above. Escape only ERE metacharacters -- `\\.`, `\\(`, "
                "`\\)`, `\\[`, `\\]`, `\\*`, `\\+`, `\\?`, `\\{{`, `\\}}`, `\\|`, "
                "`\\\\` -- or use a POSIX character class such as "
                "`[[:digit:]]`.".format(index, pattern)
            )
        interval_problem = _brace_interval_problem(pattern)
        if interval_problem:
            return (
                "user_visible_paths[{}]: {!r} {}. This value runs as `grep -E` "
                "on the release runner's own machine, and a malformed interval "
                "like this is a SYNTAX ERROR (exit 2) the generated "
                "`if ! grep -Eq PATTERN; then skip; fi` guard cannot tell "
                "apart from a genuine no-match, so the changelog gate would go "
                "silently and permanently off for the whole repository "
                "(#1015).".format(index, pattern, interval_problem)
            )
    return None


# Label vocabularies differ per repo and no pattern list covers every convention, so
# these are widened rather than made exhaustive -- and every label that matches none
# of them is reported by name. `priority/high` is GitHub's own documented spelling and
# used to match nothing, producing an empty priority list on a fully labelled board
# that read exactly like the measured empty list of a board with none.
PRIORITY_RES = (
    re.compile(r"^(?:priority|prio|p)[-:/ ]", re.IGNORECASE),
    re.compile(r"^p\d+$", re.IGNORECASE),
)
LANE_RES = (re.compile(r"^(?:lane|area|type)[-:/ ]", re.IGNORECASE),)

# #990: the spelling this repo hand-added at `.oss.json`'s `labels.filed_by_loop` --
# "filed-by-loop" -- widened the same way PRIORITY_RES and LANE_RES are, on the same
# reasoning: a pattern list covers a convention, not an exact string, and every probed
# label that matches none of them is simply absent from this match rather than reported
# by name, because unlike priority/lane classification this is a single opt-in value,
# not a bucket.
FILED_BY_LOOP_RE = re.compile(r"^filed[-_:/ ]?by[-_:/ ]?loop$", re.IGNORECASE)


def _infer_filed_by_loop_label(labels):
    """The probed label name matching a loop-filed spelling, or None.

    Never invents: this only ever returns a name that was actually in ``labels``.
    The first match wins when more than one label matches, which is not expected in
    practice and is not a case this function tries to adjudicate.
    """
    for label in labels or []:
        name = str(label)
        if FILED_BY_LOOP_RE.match(name):
            return name
    return None


# A version-shaped string. Two-part versions are deliberately not matched: `3.9` in a
# README is far more often a Python floor than a release.
VERSION_RE = re.compile(r"\b\d+\.\d+\.\d+\b")

# Files that may carry the version, and how to look. The structured ones get a key
# lookup because a stray semver anywhere in a manifest is not the version; the prose
# ones get a regex because there is no key to read.
VERSION_CANDIDATES = (
    (".claude-plugin/plugin.json", "json"),
    ("package.json", "json"),
    ("Cargo.toml", "toml:package"),
    ("pyproject.toml", "toml:project"),
    ("CHANGELOG.md", "text"),
    ("README.md", "text"),
)

# Five states, and each of the last three is a different fact about a candidate that
# yielded no version. `none` is a measured negative -- the file was read and holds none
# -- and dropping it silently is correct. The other three are not measurements, and they
# were one word until #396:
#
#   absent      in the index, not in the working tree. `git ls-files` reports the index
#               and every read here happens in the tree, so between an uncommitted `rm`
#               and its commit -- the changelog fold produces twenty-one at once -- the
#               two disagree about exactly these paths. Not a defect and not a refusal;
#               reported by name because a file deleted in a diff nobody meant to make
#               is worth saying out loud.
#   unreadable  the file is there and its bytes did not come back. The TOOL failed to
#               answer: a mode bit, an encoding, a filesystem.
#   malformed   every byte arrived and the structure is not what the candidate's kind
#               promises -- a `.json` that is not JSON, or one that is not an object.
#               A fact about the FILE, found by reading all of it.
#
# Splitting `malformed` out is the same repair as splitting `absent` out, one line over:
# printing "could not read" about a file this process read in full renders the tool's
# answer about its own read as an answer about the file. Adding members can only widen
# what `probe_problems` accepts, so a probe written by an older copy stays valid.
VERSION_EVIDENCE_STATES = {"version", "none", "absent", "unreadable", "malformed"}

# Shared because two receipts independently asserting the same claim is what this
# repository's first rule forbids (#413): both narrated an uncommitted delete as
# the *cause* of a bare `FileNotFoundError`, when CI has measured that Windows
# returns the identical exception -- errno 2, no distinguishing winerror -- for a
# path it could not even look up (folding several Win32 codes, including
# `ERROR_FILENAME_EXCED_RANGE`, onto `ENOENT`). The exception says the path is not
# there; it does not say why. The bucket is still decided correctly from the
# exception already in hand -- that part is not in question, here or at either
# call site -- only the sentence claiming a cause the signal cannot support.
_ABSENT_CAUSE_HEDGE = (
    "The usual cause is an uncommitted delete, but the same `FileNotFoundError` is "
    "also what Windows returns for a path it could not look up at all, so this "
    "signal alone does not confirm which one it is"
)

# The probe schema, in one place, because it had none: the key names were discoverable
# only by reading this file and the semantics of `files` were written down nowhere. A
# caller who guessed produced a schema-valid config that was confidently wrong, with no
# error at any layer. `merge_method` is the one key that may honestly be null.
PROBE_SCHEMA = (
    ("repo", (str,), False),
    ("default_branch", (str,), False),
    ("clone", (str,), False),
    ("files", (list,), False),
    ("tags", (list,), False),
    ("labels", (list,), False),
    ("milestones", (list,), False),
    ("workflow_jobs", (list,), False),
    ("merge_method", (str,), True),
    ("version_evidence", (dict,), False),
)

PROBE_KEYS = tuple(key for key, _, _ in PROBE_SCHEMA)

PROBE_SCHEMA_HELP = """the probe schema
----------------
`--probe REPO` measures a repo directory and writes this shape; `--build` reads it.
There is one implementation of the schema on purpose -- a hand-assembled probe was
the defect, not the workaround.

  repo              "owner/name"
  default_branch    "main"
  clone             absolute path to the local clone
  files             repo-relative paths exactly as `git ls-files` prints them,
                    nested ones included. NOT top-level directory entries: the
                    detectors match on strings like "tests/test_x.py" and
                    ".claude-plugin/plugin.json", so a list of directory names
                    silently detects nothing.
  tags              tag names as `git tag --list` prints them
  labels            label names as they are spelled on the repo
  milestones        milestone titles
  workflow_jobs     job names read out of .github/workflows/* in the WORKING TREE.
                    A candidate `files` lists that is not on disk declares no jobs
                    and is named in a NOTE on stderr rather than refusing the
                    probe -- usually an uncommitted delete, though a bare
                    FileNotFoundError does not confirm that (#413). One that is on
                    disk and will not read still refuses: an unknown counted as
                    zero understates the checks.
  merge_method      "squash" | "merge" | "rebase" | null when more than one is
                    allowed and the repo has not decided
  version_evidence  {candidate path: "version" | "none" | "absent" |
                    "unreadable" | "malformed"} for every version candidate
                    present in `files`. "none" means read and carries none.
                    The last three are not measurements and are reported
                    rather than dropped: "absent" is in the index and not on
                    disk -- usually an uncommitted delete, though a bare
                    FileNotFoundError does not confirm that (#413) -- while
                    "unreadable" is on disk and would not read, and
                    "malformed" read completely and holds the wrong shape.

Every key is required. Absent is not empty: `probe.get("files") or []` made a
typo'd key and an empty repo identical, and the config that came out said so with
the same authority as a measurement."""

# Ordered: the first entry whose marker file is present wins.
TEST_COMMANDS = [
    ("pyproject.toml", "pytest"),
    ("tests/run-all.sh", "bash tests/run-all.sh"),
    ("package.json", "npm test"),
    ("Cargo.toml", "cargo test"),
]


class ContainmentError(Exception):
    """A path derived from config or a branch name tried to leave its root."""


class ProbeError(Exception):
    """The probe handed to `build` is not the shape `build` reads.

    Raised rather than worked around, because the alternative is what this replaced:
    a missing key read as an empty measurement, and a config nobody could tell apart
    from a correct one.
    """


def classify_labels(labels):
    """Sort label names into priority, lane, and *what matched neither*.

    The third list is the point. An empty priority list is a legitimate measurement
    on a repo with no priority labels, and it is also what a pattern miss produces --
    the two are byte-identical in the config, so the miss has to be said out loud
    somewhere else.
    """
    classified = {"priority": [], "lanes": [], "unclassified": []}
    for label in labels or []:
        name = str(label)
        if any(pattern.match(name) for pattern in PRIORITY_RES):
            classified["priority"].append(name)
        elif any(pattern.match(name) for pattern in LANE_RES):
            classified["lanes"].append(name)
        else:
            classified["unclassified"].append(name)
    return classified


def _toml_section_version(text, section):
    """True when ``[section]`` in a TOML document carries a version-shaped value.

    A hand-rolled scan rather than a parser: tomllib is 3.11+ and this module is
    3.9-compatible. It reads one key in one section, which is the whole requirement.
    """
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].strip().strip('"')
            continue
        if current != section:
            continue
        match = re.match(r"""^version\s*=\s*["'](.+?)["']""", stripped)
        if match and VERSION_RE.search(match.group(1)):
            return True
    return False


# A version constant at module scope in a root-level Python file -- the shape a
# single-file CLI package uses instead of a manifest field. Filed against #85: a repo
# shipping `_supertool.py` carried its version in `VERSION = "0.43.0"` at column zero,
# and the fixed manifest whitelist below had nowhere to put it, so a release from the
# derived config bumped every candidate but that one.
_PY_VERSION_CONST_RE = re.compile(r"""(?m)^(?:__version__|VERSION)\s*=\s*["'](.+?)["']""")


def _version_state(path, kind):
    """One candidate, in five states -- see `VERSION_EVIDENCE_STATES` for the split.

    The exception already in hand decides absence: `FileNotFoundError` is a file that
    is not there, any other `OSError` is a file that is there and would not read. No
    second question is put to the filesystem -- `exists()` swallows a short list of
    errnos and re-raises the rest, a trap this repository has already paid for (#396,
    and `_read_config` in `release_delta.py` before it).

    One consequence worth writing down: Windows folds several Win32 codes onto ENOENT,
    so a path that is unlookable rather than missing arrives here as
    `FileNotFoundError` and reads as `absent`. That is a degraded answer, not a silent
    one -- the receipt names the path either way.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return "absent"
    except (OSError, UnicodeDecodeError):
        return "unreadable"
    if kind == "json":
        # Read in full, so nothing below is a statement about the read.
        try:
            payload = json.loads(text)
        except ValueError:
            return "malformed"
        if not isinstance(payload, dict):
            return "malformed"
        value = payload.get("version")
        if isinstance(value, str) and VERSION_RE.search(value):
            return "version"
        return "none"
    if kind.startswith("toml:"):
        return "version" if _toml_section_version(text, kind.split(":", 1)[1]) else "none"
    if kind == "py-const":
        match = _PY_VERSION_CONST_RE.search(text)
        return "version" if match and VERSION_RE.search(match.group(1)) else "none"
    return "version" if VERSION_RE.search(text) else "none"


def _root_python_modules(files):
    """Root-level `.py` files only -- a version-shaped constant three directories
    deep is someone's test fixture or a vendored copy, not the package version, and
    scanning the whole tree trades one false negative for a false-positive machine.
    """
    return [
        name for name in files
        if isinstance(name, str) and "/" not in name and name.endswith(".py")
    ]


def inspect_version_sites(root, files):
    """Say, for every version candidate the repo has, whether it carries a version.

    Existence was being treated as proof, so `README.md` was listed as a version site
    on repos where it holds no version at all and `/oss:release` was told to bump a
    file with nothing to bump. Reading the file is the difference between a candidate
    and a site.

    The fixed manifest list is not the whole candidate set: a root-level Python
    module carrying a module-scope `VERSION` or `__version__` constant is measured
    the same way (#85).
    """
    root = Path(root)
    evidence = {}
    for candidate, kind in VERSION_CANDIDATES:
        if candidate in files:
            evidence[candidate] = _version_state(root / candidate, kind)
    for name in _root_python_modules(files):
        evidence[name] = _version_state(root / name, "py-const")
    return evidence


def probe_problems(probe):
    """Return a list of sentences naming everything wrong with a probe."""
    if not isinstance(probe, dict):
        return ["probe: expected a JSON object, got {}".format(type(probe).__name__)]

    problems = []
    for key, types, nullable in PROBE_SCHEMA:
        if key not in probe:
            problems.append(
                "probe: missing key {!r}. Absent is not empty -- a missing key used to "
                "derive as though the repo had none of it. Produce a probe with "
                "--probe REPO rather than assembling one.".format(key)
            )
            continue
        value = probe[key]
        if value is None and nullable:
            continue
        if not isinstance(value, types):
            problems.append(
                "probe.{}: expected {}, got {!r}. See --help for the schema, or use "
                "--probe REPO.".format(key, " or ".join(t.__name__ for t in types), value)
            )

    for key in sorted(set(probe) - set(PROBE_KEYS)):
        problems.append(
            "probe.{}: unknown key (typo, or a schema change nobody wrote down). "
            "--probe REPO writes the shape --build reads.".format(key)
        )

    evidence = probe.get("version_evidence")
    files = probe.get("files")
    if isinstance(evidence, dict) and isinstance(files, list):
        candidates = list(VERSION_CANDIDATES) + [
            (name, "py-const") for name in _root_python_modules(files)
        ]
        for candidate, _ in candidates:
            if candidate not in files:
                continue
            state = evidence.get(candidate)
            if state is None:
                problems.append(
                    "probe.version_evidence: nothing recorded for {}, which the probe "
                    "lists. 'could not answer' is not 'carries no version', so it is "
                    "refused rather than quietly dropped.".format(candidate)
                )
            elif state not in VERSION_EVIDENCE_STATES:
                problems.append(
                    "probe.version_evidence[{}]: {!r} is not one of {}".format(
                        candidate, state, ", ".join(sorted(VERSION_EVIDENCE_STATES))
                    )
                )

    return problems


def local_config_path(path):
    """The machine half that sits beside a given project config."""
    return Path(path).parent / LOCAL_CONFIG_NAME


def _enclosing_clone(start):
    """The working tree whose git dir ``start`` shares, as ``(path, why_not)``.

    ``path`` is None whenever the question could not be answered -- git absent, not a
    repository, a bare repo -- and ``why_not`` then says which, so no caller can print
    "there is no clone" for "I could not look".

    Git is asked rather than the layout being reconstructed: a worktree's ``.git`` is a
    *file* pointing into ``<clone>/.git/worktrees/<name>``, and hand-walking that back up
    is the kind of separator arithmetic that fails on exactly one platform.
    """
    ok, out, detail = _run(["git", "rev-parse", "--git-common-dir"], cwd=start)
    if not ok:
        return None, detail
    first = out.strip().splitlines()
    if not first or not first[0].strip():
        return None, "git rev-parse --git-common-dir printed nothing"
    common = Path(first[0].strip())
    if not common.is_absolute():
        common = Path(start) / common
    try:
        common = common.resolve()
    except OSError as exc:
        return None, "{} could not be resolved ({})".format(common, exc)
    if common.name != ".git":
        return None, "{} is not a .git directory, so this checkout has no working tree beside it".format(
            common
        )
    return common.parent, ""


def _anchored_elsewhere(given):
    """Would joining ``given`` onto a base directory throw that base away?

    Only Windows answers yes for a path that is not absolute. `C:x` is drive-relative,
    and a leading separator with no drive is relative to the current drive's root;
    pathlib joins both by discarding the left-hand side -- so an explicit `start` would
    silently revert to the process's own directory, which is the exact leak `start`
    exists to close. The branch is unreachable on a POSIX leg, so it is measured against
    `PureWindowsPath` directly rather than through a fixture no POSIX runner can build.
    """
    return bool(given.drive or given.root) and not given.is_absolute()


def resolve_config_path(path, start=None):
    """Where the project config really is, as ``(resolved, origin, detail)``.

    ``start`` is the directory the question is asked *from*, defaulting to the process's
    own. A relative ``path`` is read against it and the widening anchors on it, so a
    caller pointed at a tree it is not standing in -- `/oss:doctor --root` -- can ask
    the question it means. Without it the only expressible question was about the
    current directory, and the alternative every caller reached for was to compute a
    relative path from cwd to the tree: ``os.path.relpath`` returns
    ``../../../../../clone/sub/.oss.json`` whenever the two differ, or merely arrive
    under different spellings of one directory, which on macOS is the default. That
    path is then appended to the clone and answers `not found` for a config sitting in
    it -- #53's bug reintroduced by the code adopting #53's fix. ``start`` exists so
    that no caller has to build such a path: nothing here is resolved against cwd.

    ``origin`` is one of:

    ``here``           ``path`` exists relative to ``start``, and nothing else is
                       consulted.
    ``clone``          absent there, present in the working tree of the enclosing clone.
                       This is the git-worktree case: `.oss.json` may be git-excluded,
                       so it lives in the clone and in none of its worktrees, and the
                       developer standing in a worktree is in the same repository.
    ``missing``        absent, and the widening ran: ``detail`` says how far it got.
    ``unsearchable``   absent, and the widening could NOT run -- there is no enclosing
                       clone to search, or git could not be asked whether there is one.
                       Split out from ``missing`` because "the clone has no config" and
                       "no clone was searched at all" are the two answers this whole
                       project exists to keep apart, and prose alone kept them apart
                       only for readers: a caller branching on ``origin`` saw one value.

    ``unsearchable`` deliberately does not subdivide further into "git is absent" and
    "this is no repository". ``_enclosing_clone`` draws the line it can measure -- git
    answered, or it did not -- and its ``why_not`` carries the rest as prose. Recovering
    that finer split would mean matching git's stderr text, which is version- and
    locale-dependent; a state derived from a string match is a state that goes wrong
    silently, which is the defect, not the fix.

    An absolute ``path`` is never widened, with or without ``start``: a path somebody
    typed in full is an answer, not a starting point, and it stays ``missing`` because
    nothing the caller asked about went unsearched.
    """
    given = Path(path)
    base = None if start is None else Path(start)
    if base is not None and _anchored_elsewhere(given):
        return (
            None,
            "unsearchable",
            "{} carries an anchor of its own, so it cannot be read relative to {} -- "
            "joining them would drop {} and search this process's directory instead. "
            "Pass the path in full, or pass one with no drive and no leading "
            "separator.".format(given, base, base),
        )
    here = given if (base is None or given.is_absolute()) else base / given
    if here.is_file():
        return here, "here", ""
    if given.is_absolute():
        return None, "missing", "Run /oss:setup to write it."
    if base is not None and not base.is_dir():
        # An explicit `start` that is not there must never fall back to the process's
        # directory the way the cwd form does below. That fallback is how a --root at a
        # path that does not exist came back describing the caller's own repository
        # (#62), and with `start` the fallback would be silent as well as wrong.
        return (
            None,
            "unsearchable",
            "{} is not a directory, so it is in no clone that could be searched.".format(base),
        )

    # git is asked from the directory the path points into, but that directory need not
    # exist here -- an excluded `configs/.oss.json` has no `configs/` in the worktree.
    # A non-existent cwd makes the subprocess fail to start, which would be reported as
    # "git could not answer" about a repository git can answer about perfectly well.
    probe = here.parent
    if not probe.is_dir():
        probe = base if base is not None else Path(".")
    clone, why_not = _enclosing_clone(probe)
    if clone is None:
        return (
            None,
            "unsearchable",
            "No enclosing clone could be checked ({}), so nowhere else was searched. "
            "Run /oss:setup to write it.".format(why_not),
        )
    try:
        same = clone.samefile(probe)
    except OSError:
        same = False
    if same:
        return None, "missing", "This directory is the clone. Run /oss:setup to write it."
    candidate = clone / given
    if candidate.is_file():
        return candidate, "clone", str(clone)
    return (
        None,
        "missing",
        "Not in the enclosing clone at {} either. Run /oss:setup to write it.".format(clone),
    )


def load_from(path, start=None):
    """`load`, plus where the file was found: ``(config, problems, origin, resolved)``.

    Callers that print to a human want the origin -- reading the clone's config from a
    worktree is correct and still worth saying out loud, because the config names paths
    that are now one directory away.

    ``start`` is passed straight through to `resolve_config_path`; a caller pointed at a
    tree it is not standing in names that tree here rather than building a path to it.
    """
    resolved, origin, detail = resolve_config_path(path, start=start)
    if resolved is None:
        return None, ["{}: not found. {}".format(path, detail)], origin, None
    config, problems = load(resolved)
    return config, problems, origin, resolved


def split(config):
    """Partition a config into ``(project, local)``.

    An unknown key goes to the project half on purpose. It is a typo or an undeclared
    schema change, and `validate` names it there; hidden in an untracked file it would
    be one maintainer's private mystery.
    """
    project = dict((key, value) for key, value in config.items() if key not in LOCAL_KEYS)
    local = dict((key, value) for key, value in config.items() if key in LOCAL_KEYS)
    return project, local


def _read_json_object(path):
    """``(document, problem)``. A file that is simply absent is neither."""
    path = Path(path)
    if not path.is_file():
        return None, None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, "{}: could not read ({})".format(path, exc)
    except ValueError as exc:
        # `read_text` also raises `UnicodeDecodeError`, a `ValueError`, for a file saved
        # in another encoding -- cp1252, latin-1, UTF-16. That is a different answer
        # from the OSError above: the file was found and opened, so this is not a path
        # or permission problem, and the caller may act on the distinction (#78).
        return None, "{}: could not decode ({})".format(path, exc)
    try:
        document = json.loads(raw)
    except ValueError as exc:
        return None, "{}: could not parse as JSON ({})".format(path, exc)
    if not isinstance(document, dict):
        return None, "{}: could not parse as a JSON object".format(path)
    return document, None


def _is_project_scoped(key):
    """Whether `key` belongs in the tracked half regardless of where it lands.

    `PROJECT_KEYS` alone used to answer this, until #355's reserved-prefix escape
    (`_RESERVED_PREFIX`, see `OPTIONAL_KEYS` above) added a second class of key
    that must never be sourced from the git-excluded local file: a note is exactly
    the kind of thing worth sharing with every other maintainer, and `split()`'s
    docstring already explains why an unknown key goes to the project half on
    purpose -- hidden in an untracked file it would be one maintainer's private
    mystery. A `_`-prefixed key is no different, and treating it as project-scoped
    everywhere `PROJECT_KEYS` was previously the answer keeps that guarantee.
    """
    return key in PROJECT_KEYS or key.startswith(_RESERVED_PREFIX)


def _scope_problems(project, local, local_exists):
    """Where a key sits, as opposed to whether its value is any good.

    `validate` sees only the merged config and so cannot tell the two halves apart. This
    is the only place that can, and every finding here names the remedy: a scope problem
    that merely says "wrong" is a file the maintainer leaves exactly as it is.
    """
    problems = []

    for key in sorted(LOCAL_KEYS & set(project)):
        problems.append(
            "{}: machine-scoped key in the committed config. It names a directory on one "
            "person's disk, so it belongs in {}. Run `oss_config.py --split` to move it; "
            "the config still loads meanwhile.".format(key, LOCAL_CONFIG_NAME)
        )

    if local:
        for key in sorted(k for k in local if _is_project_scoped(k)):
            problems.append(
                "{}: project-scoped key overridden in {}. The committed value wins -- a "
                "project fact that differs per machine is how two maintainers cut two "
                "different releases from one repo.".format(key, LOCAL_CONFIG_NAME)
            )
    # The "local half missing" case used to be reported here as a FAIL-shaped problem
    # ("... is missing, so this machine has no clone, worktree_root, state_file. Run
    # /oss:setup here"). #608: that read a fresh clone -- the ordinary state of every
    # checkout that has never run setup -- as broken, and blocked every lane cut on a
    # file /oss:setup's own migration path (`split_config_file`, below) already knows
    # how to live without. `load()` now derives the three values from the repository
    # root instead of failing, and reports which of `configured` / `derived, not
    # configured` / `could-not-derive` produced each one through `local_key_states`
    # rather than through this problems list -- a successful derivation is not a
    # problem, and rendering it as one would be exactly the defect class this
    # repository is named after, aimed at the fix for it.

    return problems


def _local_key_states(project, local, local_problem, path):
    """The per-key provenance `load()` uses to fill `config`, and every consumer of a
    LOCAL_KEYS value reports from directly (`local_key_states` below is the same
    computation, for a caller that has not already read `project`/`local` itself).

    Returns ``{key: (state, value, reason)}`` for every key in `LOCAL_KEYS`. `value`
    is the value to use when `state` is not `LOCAL_STATE_COULD_NOT_DERIVE`; `reason`
    is None except then.

    `local_problem` (the local half was present and unreadable/unparseable) takes
    every key straight to `could-not-derive`: a real file with a real problem must
    never be silently swapped for a guess, which is a stronger and more surprising
    thing to do than merely failing to read it.

    **A machine-scoped key left in the committed `.oss.json` (self-review round,
    found by this diff's own spawned reviewer) is `configured`, not derived, even
    with no `.oss.local.json` on disk.** `_scope_problems` already flags that shape
    as a scope violation on its own; what this function must not do on top of it is
    relabel the maintainer's own real value as a guess. `load()`'s own precedence is
    local wins over a mis-scoped project value when both are present -- `local` is
    checked before `project` below for the identical reason.
    """
    states = {}
    derived = None
    derive_error = None
    if local_problem is None:
        try:
            derived = _derive_local_config(project, Path(path).parent)
        except OSError as exc:
            derive_error = "{}".format(exc)
    for key in sorted(LOCAL_KEYS):
        if local_problem is not None:
            states[key] = (LOCAL_STATE_COULD_NOT_DERIVE, None, local_problem)
        elif local is not None and key in local:
            states[key] = (LOCAL_STATE_CONFIGURED, local[key], None)
        elif key in project:
            states[key] = (LOCAL_STATE_CONFIGURED, project[key], None)
        elif derived is not None:
            states[key] = (LOCAL_STATE_DERIVED, derived[key], None)
        else:
            states[key] = (LOCAL_STATE_COULD_NOT_DERIVE, None, derive_error)
    return states


def local_key_states(path):
    """`_local_key_states` for a caller that only has the committed config's path --
    `doctor.py` and `lane_setup.py`, neither of which has already parsed `project`
    and `local` the way `load()` has. Re-reads both halves; a caller that already
    holds them (`load()` itself) uses `_local_key_states` directly instead.

    ``path`` not a file, or unreadable/unparseable, folds every key to
    `could-not-derive` naming that problem -- there is no repository root to derive
    from without a readable committed config.
    """
    path = Path(path)
    project, problem = _read_json_object(path)
    if project is None:
        reason = problem or "{}: not found".format(path)
        return {key: (LOCAL_STATE_COULD_NOT_DERIVE, None, reason) for key in sorted(LOCAL_KEYS)}
    local_path = local_config_path(path)
    local, local_problem = _read_json_object(local_path)
    return _local_key_states(project, local, local_problem, path)


def load(path):
    """Return ``(config, problems)`` for the two config halves taken together.

    ``config`` is the merge of the tracked project file and the git-excluded machine
    file, so every caller downstream keeps seeing one dictionary and the split stays a
    fact about storage. It is None only when the project half could not be read.

    Problems are sentences, not codes -- they are printed to a human by `doctor`.

    #608: when `.oss.local.json` is absent, or missing one of the three machine
    keys, the missing ones are DERIVED from the repository root rather than left out
    of `config` -- the ordinary state of a fresh clone must not read as a broken one.
    `local_key_states` (or `_local_key_states`, used here directly since `project` and
    `local` are already in hand) is the one place that decides `configured` /
    `derived, not configured` / `could-not-derive` per key; a caller that needs to
    report WHICH happened, rather than just use the value, calls it directly.
    """
    path = Path(path)
    if not path.is_file():
        return None, ["{}: not found. Run /oss:setup to write it.".format(path)]
    project, problem = _read_json_object(path)
    if problem is not None:
        return None, [problem]

    local_path = local_config_path(path)
    local_exists = local_path.is_file()
    local, local_problem = _read_json_object(local_path)

    problems = []
    if local_problem is not None:
        problems.append(local_problem)

    config = dict(project)
    for key, value in sorted((local or {}).items()):
        if not _is_project_scoped(key):
            config[key] = value

    states = _local_key_states(project, local, local_problem, path)
    for key in sorted(LOCAL_KEYS - set(config)):
        state, value, reason = states[key]
        if state == LOCAL_STATE_COULD_NOT_DERIVE:
            problems.append(
                "{}: could not derive {} from the repository root ({}). Run "
                "/oss:setup here.".format(LOCAL_CONFIG_NAME, key, reason)
            )
        else:
            config[key] = value

    # `local` is already None whenever `local_problem is not None` -- every failure
    # branch of `_read_json_object` returns `(None, "...")` -- so `_scope_problems`
    # below sees the right thing without a reset here. (Self-review round: an
    # earlier version of this function re-set `local = None` at this exact point,
    # a no-op left over from moving the original reset past the derivation block
    # above; removed rather than kept as misleading dead code.)
    problems.extend(_scope_problems(project, local, local_exists))
    problems.extend(validate(config))
    return config, problems


def _unknown_key_problems(key, unknown_message):
    """One rule, one place: whether `key` is refused for looking like a credential,
    waved through as maintainer prose (`_RESERVED_PREFIX`), or reported unknown.

    #471: `10a6002` implemented this ordering three times -- once at top level, once
    in `_validate_release`, once in its `triggers` loop -- and got the credential
    check running *before* the prefix escape in only the first. The other two ran the
    prefix skip first, so `release._api_key` and `release.triggers._api_key`
    validated clean: a real secret laundered by an underscore into a tracked,
    committed file. All three call sites route through here now, so there is exactly
    one place this ordering can be gotten wrong.

    The credential check runs before the reserved-prefix escape, and on purpose:
    `_api_key` is not made safe by being spelled as maintainer prose, and a
    maintainer writing a real secret under a leading underscore must be refused
    exactly as a bare `api_key` would be.
    """
    if SECRET_RE.search(key):
        return [
            "{}: looks like a credential. This file is committed -- secrets never "
            "go here; gh holds its own auth.".format(key)
        ]
    if key.startswith(_RESERVED_PREFIX):
        # #355: maintainer prose, not a typo -- see _RESERVED_PREFIX above.
        return []
    return [unknown_message]


def validate(config):
    """Return a list of problems. An empty list means the config is usable as-is."""
    problems = []

    for key in sorted(REQUIRED_KEYS - set(config)):
        problems.append("missing required key: {}".format(key))

    for key in sorted((REQUIRED_KEYS - NULLABLE_KEYS) & set(config)):
        if config[key] is None:
            problems.append(
                "{}: is null. Only test_command and changelog_dir may be null; "
                "everything else null means the probe found nothing and said "
                "nothing.".format(key)
            )

    for key in sorted(set(config) - KNOWN_KEYS):
        problems.extend(
            _unknown_key_problems(
                key, "{}: unknown key (typo, or a schema change nobody wrote down)".format(key)
            )
        )

    repo = repo_problem(config.get("repo"))
    if repo:
        problems.append(repo)

    # The other two values `scaffold._render_claude_md` substitutes into a generated
    # CLAUDE.md. Reported here AND re-checked at the render chokepoint, for the reason
    # `fragments_dir()` and `untagged_declaration()` are: `render()` reaches that
    # template without going near `plan()`, so a guard living only here does not run
    # for that caller (#180).
    default_branch = default_branch_problem(config.get("default_branch"))
    if default_branch:
        problems.append(default_branch)

    test_command = test_command_problem(config.get("test_command"))
    if test_command:
        problems.append(test_command)

    # `scaffold._render_contributing_md` substitutes this one, same reason and same
    # re-check-at-the-chokepoint shape as the two above (#460).
    branch_pattern = branch_pattern_problem(config.get("branch_pattern"))
    if branch_pattern:
        problems.append(branch_pattern)

    labels = config.get("labels")
    if labels is not None:
        if not isinstance(labels, dict):
            problems.append("labels: expected an object with 'priority' and 'lanes'")
        else:
            for field in ("priority", "lanes"):
                if not isinstance(labels.get(field), list):
                    problems.append("labels.{}: expected a list (an empty one is fine)".format(field))
            # #762: the label the loop attaches to every issue it files, so the intake
            # metric's numerator is read off the tracker instead of recalled from a
            # tick's own memory. Optional and null-is-fine, same shape as
            # test_command/changelog_dir -- a repo that has not declared one yet is
            # not a typo, it is `could-not-count` at counting time.
            if "filed_by_loop" in labels:
                filed_by_loop = labels["filed_by_loop"]
                if filed_by_loop is not None and (
                    isinstance(filed_by_loop, bool)
                    or not isinstance(filed_by_loop, str)
                    or not filed_by_loop.strip()
                ):
                    problems.append(
                        "labels.filed_by_loop: expected a label name (string) or null "
                        "for 'not declared', got {!r}".format(filed_by_loop)
                    )
            # #844: a maintainer-side reservation is a fourth fact dispatch
            # selection cannot read off assignees alone -- an issue nobody has
            # claimed that the maintainer is deliberately holding open. Same
            # opt-in shape as filed_by_loop directly above: optional, null
            # means "not declared yet", not a typo.
            if "reserved" in labels:
                reserved = labels["reserved"]
                if reserved is not None and (
                    isinstance(reserved, bool)
                    or not isinstance(reserved, str)
                    or not reserved.strip()
                ):
                    problems.append(
                        "labels.reserved: expected a label name (string) or null "
                        "for 'not declared', got {!r}".format(reserved)
                    )

    for field in ("version_sites", "docs_targets"):
        if field in config and not isinstance(config[field], list):
            problems.append("{}: expected a list".format(field))

    changelog_dir = changelog_dir_problem(config.get("changelog_dir"))
    if changelog_dir:
        problems.append(changelog_dir)

    changelog_untagged = changelog_untagged_problem(config.get("changelog_untagged"))
    if changelog_untagged:
        problems.append(changelog_untagged)

    user_visible_paths = user_visible_paths_problem(config.get("user_visible_paths"))
    if user_visible_paths:
        problems.append(user_visible_paths)

    if "release" in config:
        problems.extend(_validate_release(config["release"]))

    if "watch_channel" in config and not isinstance(config["watch_channel"], bool):
        problems.append(
            "watch_channel: expected true or false, got {!r}. Every non-empty "
            "value here is not necessarily off, and only `false` is (#613) -- a "
            "value spelled like a decision must not silently no-op.".format(
                config["watch_channel"]
            )
        )

    # #932: a maintainer attestation, same shape as `watch_channel` above --
    # a value spelled like a decision (a truthy non-bool string, say) must not
    # silently pass as one.
    if "test_measurement_configured" in config and not isinstance(
        config["test_measurement_configured"], bool
    ):
        problems.append(
            "test_measurement_configured: expected true or false, got {!r}.".format(
                config["test_measurement_configured"]
            )
        )

    return problems


def _validate_release(release):
    """Validate the release block. Null fields are allowed and mean 'not observed'."""
    if not isinstance(release, dict):
        return ["release: expected an object, got {}".format(type(release).__name__)]

    problems = []

    for key in sorted(set(release) - RELEASE_KEYS):
        problems.extend(
            _unknown_key_problems(
                key,
                "release.{}: unknown key. The release gates are not configurable -- green "
                "at leg level, nothing mid-review, audit passed, every version site "
                "bumped, tag verified on the remote -- so a key that reads like one is "
                "refused rather than ignored.".format(key),
            )
        )

    for key in ("tag_pattern", "commit_subject"):
        value = release.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or VERSION_PLACEHOLDER not in value:
            problems.append(
                "release.{}: must contain {}, got {!r}. Without it every release "
                "produces the same string, and the second one collides with the "
                "first.".format(key, VERSION_PLACEHOLDER, value)
            )

    merge_method = release.get("merge_method")
    if merge_method is not None and merge_method not in MERGE_METHODS:
        problems.append(
            "release.merge_method: expected one of {}, got {!r}".format(
                ", ".join(sorted(MERGE_METHODS)), merge_method
            )
        )

    # #478: null and absent both mean "not stated" and are read as not-declared by
    # `release_authority` below -- neither is a problem here. An unrecognised string is,
    # because a typo that silently read as not-declared would look identical to one that
    # parsed, and the difference is exactly what a maintainer needs to fix it.
    authority = release.get("authority")
    # `not in RELEASE_AUTHORITIES` alone raises TypeError on an unhashable value
    # (`{}`, `[]`) -- checked here rather than left to Python, because this is a
    # tracked, maintainer-editable file and a crash here takes down `doctor.py`'s
    # own "exit 0 always, one VERDICT line" contract along with every other caller
    # of `oss_config.load()`. Not a string is exactly as much "unrecognised" as a
    # string this rule does not know.
    if authority is not None and (
        not isinstance(authority, str) or authority not in RELEASE_AUTHORITIES
    ):
        problems.append(
            "release.authority: expected one of {}, got {!r}. An unrecognised value is "
            "read as not-declared and stops tagging and publishing -- it must not default "
            "to autonomy.".format(", ".join(sorted(RELEASE_AUTHORITIES)), authority)
        )

    for key in PUBLISH_KEYS:
        value = release.get(key)
        if value is not None and not isinstance(value, bool):
            problems.append(
                "release.{}: expected true or false, got {!r}. Every non-empty string is "
                "truthy, so a value spelled like a decision publishes when it reads like "
                "a refusal.".format(key, value)
            )

    if release.get("draft") is True and release.get("latest") is True:
        problems.append(
            "release.latest: a draft cannot be marked Latest, so this pair states an "
            "outcome the release path can never produce. Set release.draft to false to "
            "publish and mark Latest, or release.latest to false to keep the draft."
        )

    triggers = release.get("triggers")
    if triggers is not None:
        if not isinstance(triggers, dict):
            problems.append("release.triggers: expected an object")
        else:
            for key in sorted(set(triggers) - TRIGGER_KEYS):
                problems.extend(
                    _unknown_key_problems(
                        key, "release.triggers.{}: unknown key".format(key)
                    )
                )
            for key in sorted(TRIGGER_KEYS & set(triggers)):
                value = triggers[key]
                if value is not None and not isinstance(value, int):
                    problems.append(
                        "release.triggers.{}: expected a number, got {!r}".format(key, value)
                    )

    return problems


def release_commit_subject(config):
    """The subject line the release commit is made with.

    Null in the config is honest -- the probe cannot observe a house style it has never
    seen -- but a null still has to become a string before anything commits, and the
    only thing downstream of an undefined null is an agent writing whatever it likes.
    """
    release = config.get("release")
    if not isinstance(release, dict):
        release = {}
    value = release.get("commit_subject")
    if value is None:
        return DEFAULT_COMMIT_SUBJECT
    return value


def release_publish_policy(config):
    """Whether the tag becomes a GitHub Release, and what kind (#58).

    Returns `create`, `draft`, `latest` -- and `stated`, which is the one that keeps
    this honest. A repo that has never chosen and a repo that chose not to publish
    produce the same three booleans and must not produce the same sentence: the first
    is told which key would change it, the second is reported as the decision it is.
    """
    release = config.get("release") if isinstance(config, dict) else None
    if not isinstance(release, dict):
        release = {}

    policy = {
        "create": PUBLISH_DEFAULTS["create"],
        "draft": PUBLISH_DEFAULTS["draft"],
        "latest": PUBLISH_DEFAULTS["latest"],
        "stated": False,
    }

    for key, field in zip(PUBLISH_KEYS, ("create", "draft", "latest")):
        value = release.get(key)
        if isinstance(value, bool):
            policy[field] = value

    # `stated` is about `create_release` alone, and deliberately not a union over the
    # three keys. A repo that set only `draft` has said how it would publish, not
    # whether to -- and a union here reported that repo as having chosen not to
    # publish, in those words, which is a decision it never made rendered exactly like
    # one it did. That is this module's own defect class inside the accessor written
    # to prevent it.
    policy["stated"] = isinstance(release.get("create_release"), bool)

    return policy


def release_authority(config):
    """Whether this repository has granted the loop authority to tag and publish a
    release without stopping (#478), in the three states this repo's own defect class
    demands -- an absence produced by the tool must never read as permission from the
    world:

      loop          -- the two Stops rows (tagging, publishing) do not stop. The loop
                        acts and names this grant in the release report.
      maintainer    -- explicit, unconditional stop, exactly as the Stops table reads.
      not-declared  -- absent, unreadable, or an unrecognised value. Stops, the same as
                        `maintainer`. A repository that never opted in must not be tagged
                        because a config file failed to parse.

    Governs tagging and publishing only. Deriving a version number (#467) is listed under
    `## Who decides` as the loop's, unconditionally, and does not read this key -- a
    single key that silently also granted version acceptance would be a wider grant than
    the config text says.
    """
    release = config.get("release") if isinstance(config, dict) else None
    if not isinstance(release, dict):
        return AUTHORITY_NOT_DECLARED
    value = release.get("authority")
    # `isinstance` first: `value in RELEASE_AUTHORITIES` alone raises TypeError on an
    # unhashable value (`{}`, `[]`), and this accessor's whole contract is to never
    # raise on a config it did not write -- an unhashable value is exactly as
    # not-declared as a string this rule does not recognise.
    if isinstance(value, str) and value in RELEASE_AUTHORITIES:
        return value
    return AUTHORITY_NOT_DECLARED


def _infer_tag_pattern(tags):
    """Derive the tag spelling from tags that exist, or None when none are recognised."""
    for tag in tags or []:
        for pattern, template in TAG_SCHEMES:
            if pattern.match(str(tag)):
                return template
    return None


def build(probe):
    """Derive a config from what was actually observed on the repo.

    ``probe`` carries only measurements, in the shape `--probe` writes and `--help`
    documents. A probe that is not that shape raises `ProbeError` instead of deriving
    around the gap: absent used to read as empty, and the config that came out was
    indistinguishable from one that had been measured.

    Nothing here invents. Anything the probe measured as empty comes out empty.
    """
    problems = probe_problems(probe)
    if problems:
        raise ProbeError("\n".join(problems))

    labels = list(probe.get("labels") or [])
    files = list(probe.get("files") or [])

    test_command = None
    for marker, command in TEST_COMMANDS:
        if marker in files:
            test_command = command
            break
    if test_command is None and any(
        f.startswith("tests/") and f.endswith(".py") and "test" in f.rsplit("/", 1)[-1]
        for f in files
    ):
        # A plain unittest layout: no manifest to key on, tests plainly present. Found
        # by probing a real repo that reported null while its tests sat in tests/.
        test_command = "python3 -m unittest discover -s tests"

    # A candidate the probe read and found a version in. Existence is not evidence:
    # every repo has a README.md and most of them carry no version anywhere.
    evidence = probe.get("version_evidence") or {}
    version_sites = [
        candidate
        for candidate, _ in VERSION_CANDIDATES
        if candidate in files and evidence.get(candidate) == "version"
    ] + [
        name for name in _root_python_modules(files) if evidence.get(name) == "version"
    ]

    classified = classify_labels(labels)

    docs_targets = [doc for doc in ("README.md",) if doc in files]

    repo_name = (probe.get("repo") or "/").split("/")[-1]

    return {
        "repo": probe.get("repo"),
        "default_branch": probe.get("default_branch"),
        "clone": probe.get("clone"),
        "worktree_root": "{}-wt".format(probe.get("clone")) if probe.get("clone") else None,
        "branch_pattern": "fix/{issue}",
        "test_command": test_command,
        "version_sites": version_sites,
        # A prefix, not a membership test: `git ls-files` prints files and never the
        # directories holding them, so asking whether "changelog.d" is in the list is
        # asking a question the answer can never be yes to.
        "changelog_dir": (
            "changelog.d"
            if any(name.startswith("changelog.d/") for name in files)
            else None
        ),
        # Emitted as null rather than omitted. Which release sections were never
        # tagged is not measurable from a probe -- a tag can be absent because the
        # release predates the repository, which is the case #121 was filed from, or
        # because nobody has cut it yet. So the key ships visible and undeclared, and
        # a maintainer who needs it finds it in the file rather than in a changelog.
        "changelog_untagged": None,
        "docs_targets": docs_targets,
        "labels": {
            "priority": classified["priority"],
            "lanes": classified["lanes"],
            # #990: never invented -- a match against the labels the probe already
            # collected, or an emitted `null` with the same visible-but-undeclared
            # shape `changelog_untagged` above already uses. Without this, no
            # repository onboarded through /oss:setup ever received the key, and
            # dispatch_rank.rank (#798) refused to rank anything on every one of them
            # but this repo, where the key was hand-added.
            "filed_by_loop": _infer_filed_by_loop_label(labels),
        },
        "milestones": list(probe.get("milestones") or []),
        # No `ci` block. See LEGACY_KEYS: the job-declaration count this used to emit
        # was not the merge gate's number and could not be made into one (#113, #85).
        "state_file": ".max/{}-watch.json".format(repo_name) if repo_name else ".max/oss-watch.json",
        "release": {
            # Both derived from what the repo already does. Null means the probe could
            # not tell, and /oss:release refuses on a null rather than inventing one.
            "tag_pattern": _infer_tag_pattern(probe.get("tags")),
            "merge_method": probe.get("merge_method"),
            # Not observable, and cosmetic: the subject line is written by whoever cuts
            # the release. Left null so it is a decision rather than a house style
            # arriving from a tool that has never read this repo's history.
            "commit_subject": None,
            # These two ARE defaults rather than measurements, and deliberately so: the
            # loop states them as decisions to be overridden, and they sit in the file
            # where they can be seen and argued with.
            "triggers": {"merged_prs": 10, "soak_hours": 48},
        },
    }


def _write_json(path, document):
    Path(path).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _repoint_git_exclude(root):
    """Exclude the machine half, stop excluding the project half.

    The exclusion is half the defect: `.git/info/exclude` is not copied by `git clone`,
    so the second maintainer inherits neither the file nor the reason it was hidden.
    Doing this by hand is the per-maintainer decision this whole change removes.
    """
    exclude = Path(root) / ".git" / "info" / "exclude"
    if not exclude.is_file():
        return [
            "no .git/info/exclude here, so the exclusion was not touched -- make sure "
            "{} is ignored before committing anything".format(LOCAL_CONFIG_NAME)
        ]
    before = exclude.read_text(encoding="utf-8")
    kept = [line for line in before.splitlines() if line.strip() != CONFIG_NAME]
    if LOCAL_CONFIG_NAME not in [line.strip() for line in kept]:
        kept.append(LOCAL_CONFIG_NAME)
    after = "\n".join(kept) + "\n"
    if after == before:
        return []
    exclude.write_text(after, encoding="utf-8")
    return [
        ".git/info/exclude: {} excluded, {} no longer".format(LOCAL_CONFIG_NAME, CONFIG_NAME)
    ]


def _decode_output(raw):
    """Decode a subprocess's bytes for display. Never raises. (#112)

    `universal_newlines=True` -- and its modern spelling `text=True` -- makes
    `subprocess` decode with the *locale* encoding, strictly. `UnicodeDecodeError` is a
    `ValueError`, so it walks straight past every `except OSError` guarding these calls,
    and what they carry is pathnames and command output: the one place a byte the locale
    cannot decode is ordinary rather than exotic.

    Decoding here instead makes the failure impossible rather than merely reportable, and
    that is the stronger fix. The exit code already carries the answer -- `check-ignore`
    exits 0 for ignored and 1 for clear -- so a byte in the *text* must never be able to
    destroy it. Turning a repository whose paths are fine and whose bytes are not into an
    `unknown` would report a limit of this tool as a fact about that repository, which is
    the defect class the three states exist to prevent.

    UTF-8 is named rather than inherited: git speaks UTF-8 for pathnames on every
    platform, while a locale is a property of the machine *reading* the output rather
    than of the process that wrote it. `replace` rather than `surrogateescape` because
    this text is printed -- a lone surrogate only moves the crash from the decode to the
    print. The newline folding is what `universal_newlines=True` was also doing, kept so
    that dropping it changes nothing but the encoding policy.
    """
    if raw is None:
        return ""
    if not isinstance(raw, bytes):
        return raw
    text = raw.decode("utf-8", "replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _ignore_rule(root, name):
    """Is ``name`` still ignored? ``(state, detail)`` -- clear, ignored, or unknown.

    `.git/info/exclude` is the only ignore source this script may rewrite; a `.gitignore`
    belongs to whoever maintains the repo. So repointing the exclude file does not
    establish that the project half can be committed, and saying so anyway reports the
    action taken rather than the state produced -- which is how this plugin's own repo
    ended up with a correct `.oss.json` that `git add` silently refused.

    `git check-ignore` exits 1 for "not ignored", so the shared `_run` helper cannot be
    used here: it folds every non-zero exit into failure, and that would render a clean
    answer as an unknown one.
    """
    command = ["git", "-C", str(root), "check-ignore", "-v", "--", name]
    try:
        # Bytes, not text: see _decode_output. The pathname git echoes back is the one
        # thing here guaranteed to be a filename, and a filename is where an undecodable
        # byte lives. It is also the part after the tab, which this function throws away.
        done = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return "unknown", "git would not start ({})".format(exc)
    except ValueError as exc:
        # A different answer from the one above, and worth keeping apart: git is
        # installed and would have run -- it is this *name* subprocess refuses to put in
        # an argument vector, a NUL byte being the reachable case. Folding it into "would
        # not start" would send someone to install a binary that is already there.
        return "unknown", "{!r} could not be handed to git ({})".format(name, exc)
    if done.returncode == 0:
        first = _decode_output(done.stdout).strip().splitlines()
        return "ignored", first[0].split("\t")[0] if first else name
    if done.returncode == 1:
        return "clear", ""
    stderr = _decode_output(done.stderr).strip().splitlines()
    return "unknown", stderr[-1] if stderr else "git check-ignore exited {}".format(done.returncode)


def _derive_local_config(document, root):
    """The three machine-scoped values, computed from ``root`` rather than read.

    Same derivation `build()` reaches for when a fresh probe has nothing on disk to
    measure against -- `<clone>-wt` for `worktree_root`, `.max/<repo-name>-watch.json`
    for `state_file` -- reused here for a different situation. `build()` runs once, on
    a repo that has never had a config at all. This runs on a repo whose committed
    `.oss.json` is already correct and already split, and that simply has no
    `.oss.local.json` on THIS machine -- the ordinary state of a fresh clone (#608,
    #701). No network call and no `gh`: the repo name comes from ``document["repo"]``,
    already on disk, rather than from a fresh probe.
    """
    clone = str(Path(root).resolve())
    # `build()` uses this identical fallback (line ~1849), but only after
    # `probe_problems` has already refused a probe whose `repo` is not a string.
    # `split_config_file` reads a committed file with no such gate -- a hand-edited
    # or otherwise corrupted `.oss.json` can carry a `repo` that is present and
    # truthy and not a string (an int, a dict, a list, a bool), and every OTHER
    # malformed-input path in `split_config_file` returns a problem sentence
    # rather than crashing. `isinstance` first folds that case into the same
    # "nothing usable" fallback an absent or empty `repo` already takes, instead
    # of a bare `AttributeError` out of `_main` (found in review, #701).
    repo_value = document.get("repo")
    repo_name = (repo_value if isinstance(repo_value, str) else "/").split("/")[-1]
    return {
        "clone": clone,
        "worktree_root": "{}-wt".format(clone),
        "state_file": (
            ".max/{}-watch.json".format(repo_name) if repo_name else ".max/oss-watch.json"
        ),
    }


def split_config_file(path):
    """Migrate a combined config in place. Returns ``(problems, notes)``.

    Same command for both audiences, deliberately: the repo that already has a combined
    `.oss.json` and the fresh `/oss:setup` that has just written one run the identical
    step, so there is one migration to get right rather than a migration and a happy
    path that drift.

    Idempotent. A project half with no machine keys and a machine half already on disk is
    an already-split repo, and re-running must not rewrite either file -- a migration you
    are afraid to repeat is one nobody runs twice, including after a bad merge.

    A THIRD shape, not a variant of either of the above (#608, #701): no machine key in
    the committed file AND no `.oss.local.json` on this machine -- the ordinary state of
    every fresh clone of an already-onboarded repo. There is nothing here to *move*, so
    nothing is moved: the three values are derived from the repository root instead,
    written to the machine half alone, and the project half is left byte-for-byte
    untouched. The receipt says `derived, not configured` rather than a plain `OK`,
    because a value this script guessed and a value a maintainer chose must never render
    the same way to whoever reads the note -- #608's own acceptance condition, reached
    here from the setup side.
    """
    path = Path(path)
    if not path.is_file():
        return ["{}: not found. Run /oss:setup to write it.".format(path)], []
    document, problem = _read_json_object(path)
    if problem is not None:
        return [problem], []

    project, local = split(document)
    target = local_config_path(path)
    notes = []

    if not local and target.is_file():
        notes.append("{}: already split; no key moved.".format(path.name))
    elif not local:
        derived = _derive_local_config(document, path.parent)
        _write_json(target, derived)
        notes.append(
            "{}: derived, not configured -- no machine-scoped key in {} and no {} on "
            "this machine, so clone={!r}, worktree_root={!r}, state_file={!r} were "
            "guessed from the repository root rather than read. {} was left "
            "untouched.".format(
                target.name,
                path.name,
                target.name,
                derived["clone"],
                derived["worktree_root"],
                derived["state_file"],
                path.name,
            )
        )
    else:
        _write_json(target, local)
        _write_json(path, project)
        notes.append(
            "{}: {} machine-scoped key(s) -- {}".format(
                target.name, len(local), ", ".join(sorted(local)) or "none"
            )
        )
        notes.append("{}: {} project-scoped key(s)".format(path.name, len(project)))

    notes.extend(_repoint_git_exclude(path.parent))

    state, detail = _ignore_rule(path.parent, path.name)
    if state == "clear":
        notes.append("{}: nothing ignores it, now safe to track".format(path.name))
    elif state == "ignored":
        notes.append(
            "{}: still ignored by {} -- that rule is yours to change, and until it does "
            "`git add` refuses the project half without saying so".format(path.name, detail)
        )
    else:
        notes.append(
            "{}: could not ask git whether anything ignores it ({}). Unchecked is not "
            "unignored -- run `git check-ignore -v {}` where the repo is".format(
                path.name, detail, path.name
            )
        )
    notes.append(
        "git add {} -- committing the project half is the point, and it is the one step "
        "this script leaves to you".format(path.name)
    )
    return [], notes


def ensure_worktree_root(config):
    """Create the worktree root if it is missing. Returns what happened.

    The rule this sits under: **create containers, never content.** An empty directory
    asserts nothing, so making one is free and removes a permanent warning. A file
    asserts something -- an identity file claims who somebody is, a state file claims a
    tick happened -- and inventing either is how a default becomes a lie.

    A path occupied by a file is refused rather than replaced: deleting somebody else's
    file to make room is not a default, it is a loss.
    """
    value = config.get("worktree_root")
    if not value:
        return "unset"
    path = Path(os.path.expanduser(str(value)))
    if path.is_dir():
        return "present"
    if path.exists():
        return "blocked"
    try:
        path.mkdir(parents=True)
    except OSError:
        return "blocked"
    return "created"


#: `JOBOBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Named rather than inlined because the whole
#: Windows arm below turns on it: when the last handle to the job closes, every
#: process still in it dies. That is what makes this survive THIS process crashing
#: between the spawn and the timeout, which `taskkill` cannot.
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

#: `JobObjectExtendedLimitInformation`, the class index `SetInformationJobObject`
#: takes for the struct below.
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


def _windows_job_object():
    """A job object every descendant of the spawned command will belong to, or None.

    **`taskkill /F /T /PID` cannot do this job and that is what #937's Windows legs
    measured.** `/T` walks the live parent-child links Windows keeps, and those links
    only exist while the parent does. The shape this function exists for is the
    ordinary one: `cmd.exe` starts a command, that command spawns something and
    exits, and by the time the timeout fires the survivor's parent is gone -- so the
    survivor is no longer under the pid `/T` was given and is never signalled. It
    also keeps the stdout handle it inherited, and a Windows anonymous pipe does not
    report EOF while any handle to it is open, which is the second half of #937.

    A job object is not walked, so nothing about it goes stale when a parent exits: a
    process joins the job and stays in it, and `TerminateJobObject` reaches every
    member at once no matter who spawned whom or who has since died.

    Returns None rather than raising when any step fails -- no `ctypes`, a Windows
    without these entry points, a job the process may not create. The caller falls
    back to `taskkill`, which is weaker and not nothing.
    """
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:  # pragma: no cover - Windows-only path
        return None

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BasicLimits(ctypes.Structure):
        # `Affinity` is a ULONG_PTR, so it is `c_size_t` and not `DWORD`: on 64-bit
        # the wrong width here silently misaligns every field after it, and the
        # struct would still be accepted.
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Declared, not left to default: a HANDLE returned as a C int is truncated
        # on 64-bit Windows, and the truncated value fails later as a wrong handle
        # rather than as a failed create -- an error attributed to the wrong call.
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            kernel32.CloseHandle(job)
            return None
        return job
    except (OSError, AttributeError, ValueError):  # pragma: no cover - Windows-only
        return None


def _windows_assign_job(job, proc):
    """Put `proc` in `job`. True when it took.

    **There is a race here and it is named rather than hidden.** The process is
    already running when this is called -- `subprocess` gives no way to start one
    suspended and hand back the thread handle needed to resume it -- so a command
    that spawns a child within the first milliseconds could leave that child outside
    the job. It is a small window against an interpreter start, and the fallback for
    everything it misses is the `taskkill` path, which is exactly what this replaces
    and no worse than the previous behaviour.

    Nested jobs (Windows 8+) are why this works on a CI runner at all: the runner
    already puts its own processes in a job, and on anything older an assignment
    into a second job fails -- answered False here, not raised.
    """
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        return bool(kernel32.AssignProcessToJobObject(job, int(proc._handle)))
    except (ImportError, OSError, AttributeError, ValueError):  # pragma: no cover
        return False


def _windows_close_job(job):
    """Close the job handle. With KILL_ON_JOB_CLOSE set this is itself a kill of
    anything still in it, so it is never skipped on the success path."""
    try:
        import ctypes

        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(job)
    except (ImportError, OSError, AttributeError, ValueError):  # pragma: no cover
        pass


def _kill_process_tree(proc, job=None):
    """Reach past the one pid Popen.kill() touches.

    A kill aimed at a single pid never reaches anything the command spawned
    underneath it -- the shell it was run in, or anything that shell spawned in turn
    -- which is the mechanism behind #937. The whole unit is reached at once instead,
    and how differs by platform because the primitives do:

    * **Windows**: `TerminateJobObject` over the job every descendant was assigned
      to. `taskkill /F /T` is the fallback when no job could be created, and it is a
      fallback rather than the primary because it walks live parent-child links: a
      grandchild whose parent has already exited is no longer under the pid it is
      given, which is precisely the case the test for this covers.
    * **POSIX**: `killpg` over the process group `start_new_session` created.

    Both are best-effort -- a process that already exited is not an error here.

    Returns True when the primitive that reaches the whole tree reported success --
    `TerminateJobObject` returning nonzero, `taskkill` exiting 0, `killpg` raising
    nothing, or `killpg` raising `ProcessLookupError` (no process with that pgid
    exists at all, which proves the tree is already gone rather than leaving that
    unknown) -- and False when it could not confirm that: some other exception
    `killpg` had to swallow (a permission failure, say), or `taskkill` exiting
    nonzero. (`taskkill`'s own "already gone" exit code is not given the same
    distinction as `killpg`'s -- see #945's own report for why.) False does not
    mean the tree is still running; it means this function cannot say it isn't --
    which #945 exists to surface rather than silently fold into the same "killed"
    outcome as a confirmed clean kill.
    """
    confirmed = False
    if os.name == "nt":
        killed = False
        if job is not None:
            try:
                import ctypes
                from ctypes import wintypes

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.TerminateJobObject.restype = wintypes.BOOL
                kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
                killed = bool(kernel32.TerminateJobObject(job, 1))
            except (ImportError, OSError, AttributeError, ValueError):  # pragma: no cover
                killed = False
        if killed:
            confirmed = True
        else:
            result = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            confirmed = result.returncode == 0
    else:
        # proc.pid IS the group id here, not something to look up: start_new_session
        # made this process its own session leader at the moment it started, and a
        # session leaders pgid equals its own pid by definition, permanently -- it does
        # not change when the leader exits. Looking it up instead with os.getpgid(proc.pid)
        # is the wrong, racy way to get the same number: once the leader has already
        # exited (the common case here -- a shell that execs into a short-lived command
        # returns almost immediately, well before the timeout fires), the pid is gone from
        # the process table and getpgid raises ProcessLookupError, so the kill silently
        # never happens and every descendant is left running -- confirmed by hand: the
        # lookup form left a grandchild alive to finish its full sleep, and using the
        # captured pid directly killed it as soon as the timeout fired.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            confirmed = True
        except ProcessLookupError:
            # No process with this pgid exists at all -- not "we could not tell",
            # the whole tree is provably gone already, which is the positive
            # answer this field exists to carry (#945).
            confirmed = True
        except OSError:
            confirmed = False
    try:
        proc.kill()
    except OSError:
        pass
    return confirmed


def verify_test_command(command, cwd, timeout=120):
    """Run the detected test command and say what happened.

    Detection reads a marker file and infers; this executes and measures. The states
    differ in remedy, so they are kept apart: `failed` is a suite to fix, `not-found`
    is a runner to install, and `timeout` is **unverified** rather than broken --
    reporting broken would send someone to debug a suite that is merely slow.
    """
    if not command:
        return {"state": "none", "detail": "no test command detected; nothing to verify"}

    # The runner is resolved before anything runs, because the shell's own
    # "command not found" code is not portable: POSIX shells answer 127, cmd.exe
    # answers 9009, and on a GitHub Windows runner it answered neither -- so a
    # runner that was never installed reported as a suite that ran and failed,
    # which is the one confusion these states exist to prevent. Only for a plain
    # command: with an operator in it the first word is not the whole story, and a
    # shell builtin resolves to no file at all.
    if not any(token in command for token in ("&&", "||", "|", ";", ">", "<", "$(", "`")):
        try:
            words = shlex.split(command, posix=os.name != "nt")
        except ValueError:
            words = []
        if words and shutil.which(words[0]) is None:
            return {
                "state": "not-found",
                "detail": "{!r}: {!r} is not on PATH".format(command, words[0]),
            }

    # subprocess.run own timeout handling kills only the immediate child. On POSIX
    # that is the exec-ed command itself (a shell with shell=True typically execs rather
    # than forks), but anything that spawns in turn -- a background job, an xdist
    # worker, a fixtures own subprocess -- is untouched and free to keep running, and
    # free to keep holding the stdout pipe open. On Windows the immediate child is the
    # real shell (cmd.exe does not exec-replace), so the gap is wider: the actual test
    # command is already a grandchild, inherits the pipe handle, and a Windows anonymous
    # pipe does not signal EOF until every handle to it -- including the orphaned
    # grandchilds -- is closed. communicate() then blocks for the command own
    # duration regardless of timeout (#937). Putting the whole tree in one killable
    # unit up front, and killing that unit rather than one pid, closes both gaps.
    popen_kwargs = {}
    job = None
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        job = _windows_job_object()
    else:
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **popen_kwargs,
        )
    except OSError as exc:
        return {"state": "not-found", "detail": "{!r} would not start ({})".format(command, exc)}

    # Assigned after the spawn because there is no way to start a process suspended
    # through `subprocess` and resume it afterwards; `_windows_assign_job` documents
    # the window that leaves. A job that could not be created or assigned is None,
    # and `_kill_process_tree` falls back to `taskkill` for it.
    if job is not None and not _windows_assign_job(job, proc):
        _windows_close_job(job)
        job = None

    # The job handle is closed on EVERY exit, which with KILL_ON_JOB_CLOSE is
    # itself a kill of anything still inside it. That is deliberate on the success
    # path too: a suite that returned 0 while leaving a process of its own behind
    # has leaked it into this session, and this function's contract is that the
    # command is over when it returns. Leaking the handle instead would keep those
    # processes alive until this interpreter exits and hold the job open for as long.
    try:
        try:
            stdout, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_confirmed = _kill_process_tree(proc, job=job)
            # Reap with two bounded waits, never an unconditional one: a tree-kill that failed
            # to reach every descendant (a permission failure, a grandchild that called its own
            # setsid and left the group) must not turn "unverified" into "hung forever" on the
            # same pipe -- which would reintroduce the exact unbounded-wait class #937 exists to
            # fix, only now inside this functions own recovery path. If both bounded waits still
            # do not return, give up on the output rather than block; the state below is already
            # honest that this run could not be verified either way.
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            # `state` stays "timeout" either way -- both readings are equally
            # "unverified", and #945's collapse is not in that value. It is here,
            # in a field of its own: `kill_confirmed=True` says the tree-kill
            # primitive itself reported success; `False` says it raised or exited
            # nonzero and this function cannot say the tree is actually down, which
            # is a materially different thing for a caller deciding whether a
            # leaked process on this machine needs a human. Additive rather than a
            # new `state` value on purpose -- commands/setup.md and
            # tests/test_state_vocabularies.py both branch on `state` by exact
            # string, and a value neither one has ever seen would either be
            # silently ignored there or misread as an unrelated state.
            return {
                "state": "timeout",
                "detail": "{!r} did not finish within {}s, so it is unverified -- which is "
                "not the same as broken.".format(command, timeout),
                "kill_confirmed": kill_confirmed,
            }

        returncode = proc.returncode
        if returncode == 0:
            return {"state": "ok", "detail": "{!r} ran and passed".format(command)}

        # Bytes, not text: an arbitrary test suites output is not the callers locale to
        # promise, and a single stray byte in it used to raise past the guards above --
        # reporting a suite that ran as a probe that crashed. See _decode_output.
        tail = _decode_output(stdout).strip().splitlines()[-1:] or [""]
        # 127 is the POSIX shells own "command not found", and 9009 is cmd.exes, which
        # is a different problem from a suite that ran and failed. Reading only 127 makes
        # every missing runner on Windows report as a failing suite -- the exact confusion
        # between "install this" and "fix this" the states exist to prevent.
        if returncode in (127, 9009):
            return {
                "state": "not-found",
                "detail": "{!r}: command not found ({})".format(command, tail[0]),
            }
        return {
            "state": "failed",
            "detail": "{!r} exited {} -- {}".format(command, returncode, tail[0]),
        }
    finally:
        if job is not None:
            _windows_close_job(job)


def resolve_worktree(root, target):
    """Resolve a single worktree directory name under ``root``.

    A worktree target is a bare name. Absolute paths, drive prefixes, UNC paths,
    traversals and anything carrying a separator are refused **before** resolution,
    and the resolved path is checked to still sit under the root afterwards -- a
    symlink swapped between those two checks is exactly the gap this closes.

    Returns the resolved Path so the caller reuses this one value rather than
    re-deriving it from the raw name.
    """
    if not isinstance(target, str) or not target.strip():
        raise ContainmentError("worktree target is empty")
    if target in (".", ".."):
        raise ContainmentError("worktree target {!r} is a traversal".format(target))
    if "/" in target or "\\" in target:
        raise ContainmentError(
            "worktree target {!r} contains a path separator; expected a bare name".format(target)
        )
    if os.path.isabs(target) or re.match(r"^[A-Za-z]:", target):
        raise ContainmentError("worktree target {!r} is not relative".format(target))

    root = Path(root).resolve()
    resolved = (root / target).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ContainmentError(
            "worktree target {!r} resolves to {} which is outside {}".format(target, resolved, root)
        )
    return resolved


def _run(command, cwd=None):
    """Return ``(ok, stdout, detail)``. ``detail`` is why not, when not."""
    try:
        done = subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return False, "", "{} would not start ({})".format(command[0], exc)
    if done.returncode != 0:
        lines = _decode_output(done.stderr).strip().splitlines()
        return (
            False,
            "",
            "{} exited {}: {}".format(
                " ".join(command[:3]), done.returncode, lines[-1] if lines else "no output"
            ),
        )
    # `git ls-files` prints filenames, so this helper carries the same undecodable byte
    # the check-ignore probe does (#112). Decoded here rather than by subprocess.
    return True, _decode_output(done.stdout), ""


def _git_lines(root, args):
    return _run(["git", "-C", str(root)] + list(args))


def _gh_json(root, args):
    """Run gh and parse its JSON. Seam: the tests replace this, not subprocess."""
    ok, out, detail = _run(["gh"] + list(args), cwd=root)
    if not ok:
        return False, None, detail
    try:
        return True, json.loads(out), ""
    except ValueError as exc:
        return False, None, "gh {} did not return JSON ({})".format(args[0], exc)


def _workflow_jobs(root, files):
    """Job names read out of the workflow files, as ``(jobs, problems, absent)``.

    A light scan rather than a YAML parse: this module has no third-party imports and
    the shape being read is two levels deep.

    ``files`` comes from ``git ls-files``, which answers about the **index**; the read
    happens in the **working tree**. Between an uncommitted ``rm`` and its commit the
    two disagree about exactly those paths, so absence gets a bucket of its own and
    the two are not one word (#396):

    * ``problems`` -- the file is on disk and its bytes did not come back. How many
      jobs it declares is genuinely unknown, and counting it as zero would understate
      the required checks, which is the direction that lets a red leg through. Only
      this bucket decides a verdict.
    * ``absent`` -- the file is in the index and not in the working tree. It declares
      no jobs, which is a measurement rather than a gap. Named rather than dropped,
      because ``files`` still lists it and a silently shorter job list is this
      repository's own defect class.

    Absence is decided from the exception already in hand -- ``FileNotFoundError`` is
    a file that is not there, any other ``OSError`` is a file that is there and would
    not read. No second question is put to the filesystem: ``exists()`` swallows a
    short list of errnos and re-raises the rest, a trap this repository has already
    paid for (#396, and ``_read_config`` in ``release_delta.py`` before it).

    Three states rather than the five ``_version_state`` grew in #408, and the
    difference is argued rather than inherited. This is a line scan, so it has no
    ``malformed`` to report: it cannot tell a workflow that declares no jobs from one
    whose ``jobs:`` block the scan did not match, and a state the code cannot support
    is a claim rather than a fact.

    One consequence worth writing down, the same one #408 recorded: Windows folds
    several Win32 codes onto ENOENT, so a path that is unlookable rather than missing
    arrives here as ``FileNotFoundError`` and reads as absent. Degraded, not silent --
    the path is named in the receipt either way.
    """
    jobs = []
    problems = []
    absent = []
    for rel in sorted(files):
        if not rel.startswith(".github/workflows/") or not rel.endswith((".yml", ".yaml")):
            continue
        try:
            text = (Path(root) / rel).read_text(encoding="utf-8")
        except FileNotFoundError:
            absent.append(rel)
            continue
        except (OSError, UnicodeDecodeError) as exc:
            problems.append("could not read {} ({})".format(rel, exc))
            continue
        stem = rel.rsplit("/", 1)[-1]
        in_jobs = False
        for line in text.splitlines():
            if re.match(r"^jobs:\s*$", line):
                in_jobs = True
                continue
            if not in_jobs:
                continue
            if line.strip() and not line.startswith((" ", "\t")):
                in_jobs = False
                continue
            match = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
            if match:
                jobs.append("{}:{}".format(stem, match.group(1)))
    return jobs, problems, absent


def _merge_method(view):
    """The repo's merge method, or None when more than one is allowed.

    Two allowed methods is not a preference the repo has stated, so there is nothing
    to measure and null is the answer. /oss:release refuses on a null rather than
    picking one.
    """
    allowed = [
        name
        for flag, name in (
            ("squashMergeAllowed", "squash"),
            ("mergeCommitAllowed", "merge"),
            ("rebaseMergeAllowed", "rebase"),
        )
        if view.get(flag)
    ]
    return allowed[0] if len(allowed) == 1 else None


def gather(root):
    """Measure a repo directory into a probe. Returns ``(probe, problems, notes)``.

    This exists so the schema has exactly one implementation. The slash command used
    to assemble the probe by hand, got `files` wrong in a way nothing could detect,
    and the derived config was confidently wrong at every layer.

    A probe is returned only when every field in it was measured. A half-measured
    probe is the underspecified probe this whole contract exists to refuse, and
    emitting one with the unmeasured half left empty is exactly the failure --
    "gh could not be reached" would reach disk spelled `"labels": []`.

    `notes` is the third thing this function has to say, and the reason the return is
    a triple (#396). `problems` refuses; `notes` are true statements that are not
    failures, and folding them into either of the other two would make an ordinary
    uncommitted delete either abort the whole probe or vanish. A tracked workflow
    that is not in the working tree declares no jobs -- that is a measurement, so the
    contract above is satisfied rather than relaxed, and `workflow_jobs` is complete
    for the tree it was read from. It still needs saying out loud, because `files` is
    the index and goes on listing the deleted path: without the note, a probe taken
    mid-delete is a shorter job list with nothing to explain it.

    A workflow that is on disk and would not read is the opposite case and still
    refuses: its job count is unknown, and an unknown counted as zero understates the
    required checks.

    The notes do not travel into the probe JSON. Adding a probe key was weighed and
    declined: `probe_problems` refuses both a missing key and an unknown one, so a new
    key breaks probe interchange in *both* version directions -- the cost #408
    deliberately avoided by only widening an existing state set. The documented
    invocation is a single `--probe . | --build` pipeline, where the NOTE lands on the
    same terminal as the probe. A probe saved to a file and read back later loses it,
    and `workflow_jobs` is consumed by no derivation today
    (`test_the_probe_emits_no_ci_block_even_with_workflow_jobs`), so what is lost in
    that case is a sentence for a human rather than an input to a decision.
    """
    root = Path(os.path.expanduser(str(root)))

    ok, out, detail = _git_lines(root, ["ls-files", "-z"])
    if not ok:
        return None, ["could not list the files: {}".format(detail)], []
    files = [name for name in out.split("\0") if name]

    ok, out, detail = _git_lines(root, ["tag", "--list"])
    if not ok:
        return None, ["could not list the tags: {}".format(detail)], []
    tags = [line.strip() for line in out.splitlines() if line.strip()]

    problems = []
    notes = []
    ok, view, detail = _gh_json(
        root,
        [
            "repo",
            "view",
            "--json",
            "nameWithOwner,defaultBranchRef,squashMergeAllowed,mergeCommitAllowed,"
            "rebaseMergeAllowed",
        ],
    )
    if not ok or not isinstance(view, dict):
        return None, ["could not read the repo from gh: {}".format(detail or view)], notes

    repo = view.get("nameWithOwner")
    ok, label_rows, detail = _gh_json(root, ["label", "list", "--json", "name", "--limit", "200"])
    if not ok:
        problems.append("could not read the labels from gh: {}".format(detail))
        label_rows = []

    ok, milestone_rows, detail = _gh_json(
        root, ["api", "repos/{}/milestones".format(repo), "--paginate"]
    )
    if not ok:
        problems.append("could not read the milestones from gh: {}".format(detail))
        milestone_rows = []

    jobs, job_problems, absent_workflows = _workflow_jobs(root, files)
    problems.extend(job_problems)
    if absent_workflows:
        notes.append(
            "{} workflow file(s) are in the index and not on disk, so there was "
            "nothing to read and they contributed no jobs: {}. {}; `files` still "
            "lists them because `files` is the index. The probe is complete for "
            "the working tree it was measured from.".format(
                len(absent_workflows), ", ".join(absent_workflows), _ABSENT_CAUSE_HEDGE
            )
        )

    probe = {
        "repo": repo,
        "default_branch": (view.get("defaultBranchRef") or {}).get("name"),
        "clone": str(root.resolve()),
        "files": files,
        "tags": tags,
        "labels": [row.get("name") for row in label_rows or [] if row.get("name")],
        "milestones": [row.get("title") for row in milestone_rows or [] if row.get("title")],
        "workflow_jobs": jobs,
        "merge_method": _merge_method(view),
        "version_evidence": inspect_version_sites(root, files),
    }
    problems.extend(probe_problems(probe))
    if problems:
        return None, problems, notes
    return probe, [], notes


def _report_probe_notes(probe, config):
    """Say what the probe saw and could not classify, and what the config only
    guessed. None of these is a failure.

    The first two are absences the tool produced rather than absences in the world:
    unclassified labels leave `priority: []`, and a candidate that was never *measured*
    leaves it off `version_sites`. Only `none` is a measurement -- read, and it holds
    no version -- so it is dropped silently and correctly. The other three each get
    their own sentence, because they are three different facts (#396), and one of them
    is not about the read at all: a `malformed` candidate was read in full and its
    contents are the wrong shape. The second two are the opposite shape and the one #85 was
    filed over -- a value that *was* produced, at exit 0, that reads exactly like a
    measurement and is not one. Silence in either direction reads as a measurement,
    so both are stated here instead.
    """
    unclassified = classify_labels(probe.get("labels") or [])["unclassified"]
    if unclassified:
        print(
            "NOTE {} of {} labels matched no priority or lane pattern, so they are "
            "unclassified: {}".format(
                len(unclassified),
                len(probe.get("labels") or []),
                ", ".join(unclassified),
            ),
            file=sys.stderr,
        )
    # One sentence per state, because they are three different facts and the maintainer
    # does three different things about them (#396). Until this split, an ordinary
    # uncommitted delete printed "could not read" about a file that was simply not
    # there, and a `package.json` this process read in full printed it too.
    evidence = probe.get("version_evidence") or {}
    for state, sentence in (
        (
            "absent",
            "in the index and not on disk, so there was nothing to read and they are "
            "not claimed as version sites. {}".format(_ABSENT_CAUSE_HEDGE),
        ),
        (
            "unreadable",
            "are on disk and could not read, so not claimed as version sites",
        ),
        (
            "malformed",
            "read completely and their contents are not the shape the file type "
            "promises, so not claimed as version sites",
        ),
    ):
        named = sorted(name for name, value in evidence.items() if value == state)
        if named:
            print(
                "NOTE {}: {}".format(sentence, ", ".join(named)),
                file=sys.stderr,
            )

    # No NOTE about a leg count, because no leg count is written (#113). The caveat this
    # used to print -- a matrix, a reusable workflow or an org/app-level check multiplies
    # or adds to the number invisibly -- was not a caveat on the value, it was the reason
    # the value could not exist. A number carrying "do not trust this" is still the number
    # a reader who skipped the NOTE will use. Count the legs on the pull request.

    # worktree_root and state_file have no filesystem signal to measure against on a
    # repo being set up for the first time: nothing has been cloned into a worktree
    # root yet, and no state file has been written. Both are a naming-convention
    # guess -- <clone>-wt, .max/<repo>-watch.json -- and #85 was filed on a repo where
    # neither guess matched the real, already-onboarded layout.
    worktree_root = config.get("worktree_root")
    if worktree_root:
        print(
            "NOTE worktree_root: {!r} is a guess from a naming convention, not "
            "something measured on disk. If this repo has been onboarded before, "
            "check the real path before trusting it.".format(worktree_root),
            file=sys.stderr,
        )
    state_file = config.get("state_file")
    if state_file:
        print(
            "NOTE state_file: {!r} is a guess from a naming convention, not "
            "something measured on disk. If this repo has been onboarded before, "
            "check the real path before trusting it.".format(state_file),
            file=sys.stderr,
        )

    # #990: the probe carried no label matching a loop-filed spelling (e.g.
    # "filed-by-loop"), so labels.filed_by_loop ships null -- visible, not omitted,
    # the same shape as changelog_untagged above. Said out loud because a null the
    # maintainer never notices is a dispatch order that never ranks anything: see
    # dispatch_rank.rank (#798), which answers could-not-rank for EVERY issue on a
    # board where this key is undeclared.
    if (config.get("labels") or {}).get("filed_by_loop") is None:
        print(
            "NOTE labels.filed_by_loop: no label on this repo matched a loop-filed "
            "spelling, so this key ships null. Until it names a label, "
            "dispatch_rank.rank cannot rank ANY issue on this board (#798) -- create "
            "a label (e.g. `gh label create filed-by-loop`) and set it by hand, or "
            "re-run /oss:setup once the label exists.",
            file=sys.stderr,
        )


def _main(argv=None):
    """CLI used by /oss:setup and /oss:doctor.

    `--validate` names every problem and exits non-zero; `--probe` measures a repo
    into a probe; `--build` reads a probe as JSON on stdin and writes a config to
    stdout, so the measuring and the deriving stay separable and the derive half is
    testable without a network.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Read, validate and derive .oss.json.",
        epilog=PROBE_SCHEMA_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--validate", metavar="PATH", help="validate an existing .oss.json")
    group.add_argument(
        "--split",
        metavar="PATH",
        help="split a combined .oss.json into the tracked project half and the "
        "git-excluded {} beside it, and repoint .git/info/exclude. Idempotent".format(
            LOCAL_CONFIG_NAME
        ),
    )
    group.add_argument(
        "--probe",
        metavar="REPO",
        help="measure a repo directory and write a probe as JSON on stdout "
        "(the only sanctioned way to build one -- see the schema below)",
    )
    group.add_argument(
        "--build",
        action="store_true",
        help="read a probe as JSON on stdin, write the derived config to stdout. "
        "A probe of the wrong shape is refused, not derived around",
    )
    args = parser.parse_args(argv)

    if args.validate:
        config, problems = load(args.validate)
        for problem in problems:
            print("FAIL {}".format(problem))
        if config is not None and not problems:
            print("OK {} validates".format(args.validate))
        return 1 if problems else 0

    if args.split:
        problems, notes = split_config_file(args.split)
        for problem in problems:
            print("FAIL {}".format(problem))
        for note in notes:
            print("OK {}".format(note))
        return 1 if problems else 0

    if args.probe:
        probe, problems, notes = gather(args.probe)
        for problem in problems:
            print("FAIL {}".format(problem), file=sys.stderr)
        # Printed whether or not a probe came back: a note is true either way, and a
        # refusal caused by one workflow should not swallow the sentence about another.
        for note in notes:
            print("NOTE {}".format(note), file=sys.stderr)
        if probe is None:
            return 1
        print(json.dumps(probe, indent=2))
        return 0

    try:
        probe = json.load(sys.stdin)
    except ValueError as exc:
        print("FAIL probe on stdin is not valid JSON ({})".format(exc))
        return 1
    try:
        config = build(probe)
    except ProbeError as exc:
        for line in str(exc).splitlines():
            print("FAIL {}".format(line), file=sys.stderr)
        return 1
    _report_probe_notes(probe, config)
    problems = validate(config)
    for problem in problems:
        print("FAIL derived config: {}".format(problem), file=sys.stderr)
    print(json.dumps(config, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(_main())
