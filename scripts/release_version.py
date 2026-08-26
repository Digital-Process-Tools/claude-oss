#!/usr/bin/env python3
"""Which number the release gets -- proposed from the changelog fragments (#171).

Every other release input is pinned somewhere a reader can find it: `tag_pattern`,
`commit_subject`, the range, the publish policy, and the version *sites*. The number
itself was not, so it came from whoever happened to be cutting the release, out of an
impression of what the delta felt like. #171 is the receipt: a `removed` fragment sat
unread in the same directory as the recommendation, and the one sentence that settled
whether it broke compatibility was prose inside its body, where no tool could see it.

The input was already on disk and already maintained. Fragments are named
`<issue>.<section>[.<slug>].md` over the Keep a Changelog sections, the changelog gate
requires one per user-visible change, and the assembler already parses them. That is
the input a version rule consumes -- and it is parsed with the *assembler's* grammar,
transcribed rather than invented, because a name the assembler accepts and this rule
refuses stops a release over a correctly-named file (#297).

## It proposes. It does not decide.

The output is a recommendation carrying its evidence. Gate 4 in
`skills/manager/phases/release.md` accepts the proposal by default and records which -- a major
bump is the one arm of that gate that still stops, because that promise to users is a
different promise. Who accepts the result is that gate's decision and belongs in one
place; this module's job is the derivation and its three states. Nothing here writes to
a file, bumps a site, or tags.

## Three states, and the third one is why this exists

  proposed          the fragments decide a change class, and a current version was
                    read. `version` is the number to argue with.
  no-baseline       the class is known and the current version is not -- no tag, no
                    `tag_pattern` to read one out of a tag with, or a tag that does not
                    spell a triple. The class is still reported, because "I could not
                    read the delta" and "I could not read the number it applies to" are
                    different problems with different fixes.
  could-not-decide  the fragments do not decide -- none at all, a file name that is
                    not a fragment name, a section outside the six, a fragment whose
                    bytes will not read, a compatibility line that will not read, or a
                    `removed` fragment that declares nothing.

**The reason names the cause that fired, and only that one.** It used to be one fixed
sentence offering two of the causes above whatever had happened, so a maintainer chased
a malformed body in a file whose body was fine, renamed a correctly-named file and
reported the contributor who wrote it (#297). The receipt now carries the cause beside
each file name, because with two unreadable fragments a single sentence cannot say
which file had which.

**No state but `proposed` names a number.** A default patch bump over a breaking change
is indistinguishable in the tag from a considered one, which is this plugin's own defect
class landing on the most permanent artefact a project produces.

Exit codes, because a shell reads those and never reads prose:

  0   proposed
  3   could not decide
  4   no baseline
  2   argparse usage error

## What `removed` means, written down rather than left to the moment

Under strict semver a removal is a major bump; under the 0.x convention -- semver's own
clause 4, where anything may change at any time -- it is a minor. Both are defensible
and "it depends" is what produced #171, so the rule picks one and says which:

  * in a `0.x` line, a breaking change is a **minor**, and the receipt says the fold
    happened so a maintainer who wanted `1.0.0` has something to argue with.
  * at `1.0.0` or later, a breaking change is a **major**.

The section alone never decides that. `113.removed.md` in this repository is the proof:
a removal that broke nothing. So the rule keys on a declared compatibility verdict, and
`removed` is the one section required to carry one.

## The field, and why it is only required on one section

Every fragment carrying a field is every fragment having a field to get wrong, and a
wrong-but-present flag is worse than an absent one. That cost scales with how many
fragments must carry it, so the field is required exactly where the question is genuinely
open -- one fragment in this release, whose author already knew the answer and already
wrote it in prose. Everywhere else it is optional, an absent one is read as compatible,
and the receipt reports that assumption by count rather than folding it in silently.

Three properties keep the field from becoming the thing it replaced:

  * absent on `removed` is `could-not-decide`, naming the file. Not a quiet minor.
  * present and unrecognised is `could-not-decide`. A value this rule does not know
    never grades as compatible, which is what stops a wrong flag being worse than none.
  * the verdict without its reason is `could-not-decide`. A bare flag is the same
    unsourced verdict one field further along; the sentence is the part worth having.

It is a `-` bullet in the ordinary body, so the assembler needs no change and the claim
ships into `CHANGELOG.md` where users read it, rather than being metadata deleted at the
fold.

Nothing from inside a fragment is echoed. Bodies are written by contributors, and a
receipt that prints one lets a pull request forge the receipt's own verdict line. File
names are echoed -- reduced to one printable ASCII line -- because naming the evidence is
the entire point of the receipt.
"""

import argparse
import json
import re
import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import oss_config  # noqa: E402  -- the scaffolded-fallback signal is read from here, once (#299)
import release_delta  # noqa: E402  -- the tag glob is derived in exactly one place

STATE_PROPOSED = "proposed"
STATE_NO_BASELINE = "no-baseline"
STATE_COULD_NOT_DECIDE = "could-not-decide"

EXIT_PROPOSED = 0
EXIT_COULD_NOT_DECIDE = 3
EXIT_NO_BASELINE = 4

CONFIG_NAME = ".oss.json"
VERSION_PLACEHOLDER = "{version}"
README = "readme.md"

# The Keep a Changelog headings, lowercased -- the same six changelog.d/README.md
# names. A seventh section is not a new bucket to fold into `changed`; it is a
# fragment this rule cannot classify, and it says so.
SECTIONS = ("added", "changed", "deprecated", "removed", "fixed", "security")

# Sections whose fragments can plausibly break a consumer, and which therefore have to
# say. `deprecated` is deliberately not here: a deprecation that still works is the
# definition of a compatible change, and requiring a field whose answer is fixed buys a
# chance to get it wrong and nothing else.
MUST_DECLARE = ("removed",)

FEATURE_SECTIONS = ("added", "changed", "deprecated", "removed")

BREAKING = "breaking"
COMPATIBLE = "compatible"
VERDICTS = (BREAKING, COMPATIBLE)

CLASS_BREAKING = "breaking"
CLASS_FEATURE = "feature"
CLASS_FIX = "fix"

LINE_ZERO = "0.x"
LINE_STABLE = ">=1.0"

TRIPLE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

# `<issue>.<section>[.<slug>].md`. Transcribed from `_NAME_RE` in
# scripts/assemble_changelog.py rather than invented here: the assembler is the gate
# a fragment must already pass to reach `CHANGELOG.md`, so a name it accepts and this
# rule refuses stops a release over a correctly-named file -- which is #297, observed
# twice on a repository where the slug is documented convention. A transcription is a
# claim about something outside this module, so the two are measured against each
# other in tests/test_release_version_fragment_names_297.py rather than asserted here.
# `\Z` and not `$`: a POSIX filename may end in a newline and `$` matches before one.
FRAGMENT_NAME = re.compile(r"\A(\d+)\.([a-z]+)(?:\.([A-Za-z0-9][A-Za-z0-9._-]*))?\.md\Z")

COMPAT_LINE = re.compile(r"^\s*-\s+compatibility\s*:\s*(.*)$", re.IGNORECASE)


def _has_reason(text):
    """Is there a sentence after the verdict, once the separator is dropped?

    The separator is a hyphen in the documented spelling, a colon in somebody
    else's, and an en or em dash in prose pasted out of a document. So it is
    recognised by category -- leading non-alphanumerics go, and whatever is left is
    the reason -- rather than by a table of dashes, which has to guess at the one the
    next author reaches for and puts a non-ASCII literal in a file whose every other
    byte is ASCII.
    """
    return any(char.isalnum() for char in text)


def _one_line(text, limit=200):
    """Text from outside this script, reduced to one printable ASCII line.

    A file name is chosen by whoever opened the pull request. A newline in one forges a
    receipt row, and a control character can rewrite what a terminal already printed.
    """
    flat = " ".join(str(text).split())
    safe = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in flat)
    return safe[:limit]


def _names(paths):
    return [_one_line(name, 120) for name in paths]


def compatibility(text):
    """The compatibility verdict a fragment declares, as (verdict, problem).

    Exactly one of the two is ever set. `(None, None)` is the third answer and the
    important one: the fragment declared nothing, which is not the same as declaring
    that nothing breaks.
    """
    verdicts = set()
    for line in text.splitlines():
        found = COMPAT_LINE.match(line)
        if not found:
            continue
        rest = found.group(1).strip()
        head = rest.split()[0] if rest else ""
        word = head.strip(".,:;-").lower()
        if word not in VERDICTS:
            return None, (
                "the compatibility line does not read as breaking or compatible"
            )
        if not _has_reason(rest[len(head):]):
            return None, (
                "the compatibility verdict carries no reason, which is the same "
                "unsourced verdict one field further along"
            )
        verdicts.add(word)
    if len(verdicts) > 1:
        return None, "the fragment declares both compatible and breaking"
    if not verdicts:
        return None, None
    return verdicts.pop(), None


# Why an entry could not be read, one name per distinguishable cause. `unreadable`
# was one bucket for four of them and the reason line offered two -- so a receipt
# named a cause the tool had not established, which is what #297 cost: a maintainer
# renamed a correctly-named file and reported the agent that wrote it. A single
# third state for the filename would have fixed the instance and left the class;
# `file-could-not-be-read` was already unnamed before this issue was filed.
CAUSE_NAME = "filename-does-not-parse"
CAUSE_SECTION = "section-outside-the-six"
CAUSE_FILE = "file-could-not-be-read"
CAUSE_COMPAT = "compatibility-line-unrecognised"

#: The sentence each cause contributes to the reason line. Ordered, so a receipt
#: listing two causes lists them the same way twice.
CAUSE_TEXT = (
    (CAUSE_NAME, "a filename that does not parse as `<issue>.<section>[.<slug>].md`"),
    (CAUSE_SECTION, "a section outside the six"),
    (CAUSE_FILE, "a fragment whose bytes could not be read"),
    (CAUSE_COMPAT, "a compatibility line this rule does not recognise"),
)

#: Appended only when the cause it explains actually fired.
CAUSE_NOTE = {CAUSE_COMPAT: " A value it does not know never grades as compatible."}


def fragment_name(name):
    """The section a fragment file name declares, or None when it is not a fragment.

    Public because the grammar is transcribed from the assembler and the two are
    measured against each other in a test. `_scan` wants the *cause* as well and
    calls `_fragment_section`.
    """
    return _fragment_section(name)[0]


def _fragment_section(name):
    """(section, cause). Exactly one of the two is ever set.

    The two failures are kept apart because they are two different repairs: a name
    that does not parse is renamed, and a section outside the six is either a typo
    or a change this rule genuinely cannot classify.
    """
    match = FRAGMENT_NAME.match(name)
    if match is None:
        return None, CAUSE_NAME
    section = match.group(2)
    if section not in SECTIONS:
        return None, CAUSE_SECTION
    return section, None


def _undecided(reason="", detail=""):
    """The payload every answer starts from: all keys present, nothing decided.

    It is spelled with the refusal as a *literal* rather than as a parameter so the
    state sweep in tests/test_state_vocabularies.py can resolve it. A factory that
    took the state would have hidden `could-not-decide` from the one pass that
    enumerates this file's vocabulary -- a state nothing can see, in a repository
    named after exactly that.
    """
    return {
        "state": STATE_COULD_NOT_DECIDE,
        "reason": reason,
        "detail": _one_line(detail),
        "change_class": None,
        "line": None,
        "bump": None,
        "current": None,
        "version": None,
        "baseline": None,
        "fragments": None,
        "sections": {},
        "declared_breaking": [],
        "declared_compatible": [],
        "undeclared": [],
        "unreadable": [],
        "unreadable_causes": [],
        "assumed_compatible": None,
    }


def _read_config(path):
    """(data, problem). The exception in hand answers which one -- nothing asks the
    filesystem a second question to explain why the first one failed."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "no {0} was found beside the repository".format(CONFIG_NAME)
    except (OSError, UnicodeDecodeError) as exc:
        return None, "{0} could not be read: {1}".format(CONFIG_NAME, type(exc).__name__)
    try:
        data = json.loads(raw)
    except ValueError:
        return None, "{0} is not valid JSON".format(CONFIG_NAME)
    if not isinstance(data, dict):
        return None, "{0} is not a JSON object, so it states no policy".format(
            CONFIG_NAME
        )
    return data, None


NO_DIRECTORY = (
    "changelog_dir is not set, so the fragments cannot be found. A directory picked "
    "here is a directory the project did not name, and an empty one would read as "
    "`no fragments`."
)

# The third state, distinct from NO_DIRECTORY: `changelog_dir` is still unset, but this
# repo's tree could not be read well enough to say whether scaffold's own fallback gate
# is running -- so a directory is not picked here either, for the same reason NO_DIRECTORY
# is not picked when nothing was found at all (#299).
NO_DIRECTORY_UNKNOWN = (
    "changelog_dir is not set, and whether this repo has scaffold's own fallback gate "
    "could not be determined ({}). A directory picked here would still be a directory "
    "the project did not confirm naming, so this refuses the same way NO_DIRECTORY does "
    "rather than guess."
)

# The fourth state, and the one that is a refusal rather than a gap (#343): the fallback
# gate IS on disk and readable, and the directory it names is one the `.oss.json`
# entrance would refuse outright -- absolute, or a `..` chain, or something a shell reads
# as an instruction. Resolving it would discard `repo` or walk out of it, and the fold
# this feeds deletes every fragment in whatever it names, so the value is refused rather
# than sanitised: what the contributor meant by it is not on disk, and a repaired
# directory is a directory nobody named.
NO_DIRECTORY_REFUSED = (
    "changelog_dir is not set, and the fallback gate on disk names a directory that "
    "cannot be used ({}). Nothing is resolved from it."
)

# And the entrance #343 was filed calling the CONTROL, which turned out not to be one
# on this path. `changelog_dir_problem` is reached from `oss_config.validate()`;
# `_read_config` above is a bespoke `json.loads` that never calls it, deliberately --
# this reader answers about repositories whose config it does not otherwise police. So
# `changelog_dir: "/etc"` reached `Path(repo) / named`, where an absolute string
# discards `repo` entirely, with `problem=None`. Measured, not reasoned:
#
#     _fragment_dir('/some/repo', None, {'changelog_dir': '/etc'})
#     -> (PosixPath('/etc'), None)
#
# Same value, same fold, same deletion. The rule is applied here rather than by routing
# this reader through `validate()`, which would refuse a whole config for reasons that
# have nothing to do with finding fragments -- a loud wrong answer in place of a quiet
# one. Only the key that becomes this directory is checked.
BAD_DIRECTORY = (
    "changelog_dir names a directory that cannot be used ({}). Nothing is resolved "
    "from it: this value becomes the fragment directory, and the fold deletes every "
    "fragment in whatever it names."
)

# The fifth, and it exists so that a state added to `scaffolded_changelog_gate` later
# cannot arrive here as "this repo never adopted fragments" -- a loud unknown, named.
NO_DIRECTORY_UNRECOGNISED = (
    "changelog_dir is not set, and the fallback gate on disk answered with a state this "
    "reader does not recognise ({!r}), so which directory it polices is unknown. "
    "Nothing is resolved from it."
)

# The sixth state (#347): the fallback gate is on disk and readable, and its --dir flag
# carries no argument at all -- not a value that fails validation, which is
# NO_DIRECTORY_REFUSED's case, but no value captured in the first place. Refused the
# same way NO_DIRECTORY_REFUSED is: there is no directory to give back either way.
NO_DIRECTORY_BARE = (
    "changelog_dir is not set, and the fallback gate on disk has a --dir flag with no "
    "argument ({}). Nothing is resolved from it."
)


def _fragment_dir(repo, given, config):
    """(path_or_None, problem_or_None). Three ways `changelog_dir` reaches a directory,
    and only the first two are named in the config itself (#299):

    1. `--dir` on the command line, taken as given.
    2. `changelog_dir` in `.oss.json`, a directory the project explicitly named.
    3. Null or absent, but `/oss:scaffold --apply` has already written its own gating
       workflow at the one path a forge will run it from -- the fallback directory it
       picked when it created the fragment machinery, recognised rather than re-guessed.
       `oss_config.scaffolded_changelog_gate` is what tells (3) apart from a repo that
       genuinely never adopted fragments, which still refuses exactly as it did before.

    (3) is not always `DEFAULT_FRAGMENTS_DIR` (#325): the workflow on disk polices
    whatever directory scaffold gave it, which is the directory that was named at
    apply time, not necessarily the default. `scaffolded_changelog_gate` reads that
    value back out of the workflow's own `--dir` argument and reports it as
    "present-other-dir", so this returns THAT directory rather than the default one --
    the whole point of reading it back is to stop guessing, not to guess correctly by
    coincidence. `changelog_dir` being null said nothing recoverable here; the gate on
    disk did.

    (3) is also where a directory nobody validated used to arrive (#343). The
    workflow is tracked and owned, so its `--dir` value comes in by ordinary
    contribution, and `Path(repo) / detail` discards `repo` entirely for an absolute
    string and walks out of it for a `..` chain. `scaffolded_changelog_gate` now
    applies the same rule the `.oss.json` entrance applies and answers
    "present-refused-dir" instead, which refuses here exactly as "unknown" does --
    the gate is on disk and readable, and there is still no directory to give back.

    (3) also has a sixth arm now, "present-bare-dir" (#347): a `--dir` flag on disk
    with no argument at all. That used to be misread as "present-other-dir" naming
    the FOLLOWING flag on the next line as the directory, because the extractor's
    whitespace class crossed the newline between them. Refused the same way
    "present-refused-dir" is -- there was never a value to resolve, captured or not.

    Every state has a named arm. The trailing `return` serves nothing but the states
    listed above, and it says so: a catch-all is how a state added later renders as
    "never adopted", which is the same class one file over that #328 was about.
    """
    if given:
        return Path(given), None
    if config is None:
        return None, NO_DIRECTORY
    named = config.get("changelog_dir")
    if isinstance(named, str) and named.strip():
        problem = oss_config.changelog_dir_problem(named)
        if problem:
            return None, BAD_DIRECTORY.format(problem)
        return Path(repo) / named, None
    state, detail = oss_config.scaffolded_changelog_gate(repo)
    if state == "present":
        return Path(repo) / oss_config.DEFAULT_FRAGMENTS_DIR, None
    if state == "present-other-dir":
        return Path(repo) / detail, None
    if state == "present-refused-dir":
        return None, NO_DIRECTORY_REFUSED.format(detail)
    if state == "present-bare-dir":
        return None, NO_DIRECTORY_BARE.format(detail)
    if state == "unknown":
        return None, NO_DIRECTORY_UNKNOWN.format(detail)
    if state == "absent":
        return None, NO_DIRECTORY
    return None, NO_DIRECTORY_UNRECOGNISED.format(state)


def _scan(directory):
    """Every fragment in `directory`, classified. Never raises."""
    # No `is_file()` filter. `Path.is_file` swallows every OSError and answers False,
    # so an entry that cannot be stat'd would vanish from the count rather than being
    # reported -- an absence produced by the guard, in the shape this repository is
    # named after. Selection is by name; whether the thing behind the name can be read
    # is answered by reading it, and a failure there lands in `unreadable`.
    try:
        entries = sorted(Path(directory).iterdir())
    except FileNotFoundError:
        return None, "the fragment directory does not exist"
    except OSError as exc:
        return None, "the fragment directory could not be read: {0}".format(
            type(exc).__name__
        )

    scan = {
        "sections": {},
        "count": 0,
        "breaking": [],
        "compatible": [],
        "undeclared": [],
        "unreadable": [],
    }
    for path in entries:
        if path.name.lower() == README or not path.name.lower().endswith(".md"):
            continue
        scan["count"] += 1
        section, cause = _fragment_section(path.name)
        if section is None:
            scan["unreadable"].append((path.name, cause))
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            scan["unreadable"].append((path.name, CAUSE_FILE))
            continue
        scan["sections"][section] = scan["sections"].get(section, 0) + 1
        verdict, problem = compatibility(text)
        if problem is not None:
            scan["unreadable"].append((path.name, CAUSE_COMPAT))
        elif verdict == BREAKING:
            scan["breaking"].append(path.name)
        elif verdict == COMPATIBLE:
            scan["compatible"].append(path.name)
        elif section in MUST_DECLARE:
            scan["undeclared"].append(path.name)
    return scan, None


def _unreadable_reason(unreadable):
    """The reason line, built from the causes that actually fired.

    Not a fixed sentence listing every cause this rule knows about. That was the
    defect: it offered two, the one that fired was neither, and a maintainer went
    looking for a malformed body in a file whose body was fine (#297). A cause with
    no entry behind it does not appear here.

    An unrecognised cause is named as such rather than dropped. A bucket that
    quietly loses an entry it cannot describe is the same failure one layer down.

    An empty list is answered rather than raised on. `compute` guards the call, so
    this arm is unreachable from there today -- but the one receipt this rule must
    never produce is a traceback, which names no number *and* no cause, and a helper
    that reaches an `IndexError` on an empty list is one refactor away from being it.
    """
    if not unreadable:
        return (
            "no entries were recorded as unreadable, so there is no cause to name -- "
            "this reason line was built from an empty list and says so rather than "
            "claiming a fragment failed"
        )

    known = dict(CAUSE_TEXT)
    seen = []
    for _name, cause in unreadable:
        if cause not in seen:
            seen.append(cause)
    order = [cause for cause, _text in CAUSE_TEXT if cause in seen]
    order += [cause for cause in seen if cause not in known]
    phrases = [
        known.get(cause, "a cause this rule cannot describe ({0})".format(cause))
        for cause in order
    ]
    if len(phrases) == 1:
        causes = phrases[0]
    else:
        causes = "{0} and {1}".format(", ".join(phrases[:-1]), phrases[-1])
    notes = "".join(CAUSE_NOTE[cause] for cause in order if cause in CAUSE_NOTE)
    return "{0} fragment(s) would not read -- {1}.{2}".format(
        len(unreadable), causes, notes
    )


def _classify(scan):
    if scan["breaking"]:
        return CLASS_BREAKING
    if any(section in scan["sections"] for section in FEATURE_SECTIONS):
        return CLASS_FEATURE
    return CLASS_FIX


def _bump_for(change_class, major):
    if change_class == CLASS_FIX:
        return "patch"
    if change_class == CLASS_FEATURE:
        return "minor"
    return "minor" if major == 0 else "major"


def _next(current, bump):
    major, minor, patch = (int(part) for part in current.split("."))
    if bump == "major":
        return "{0}.0.0".format(major + 1)
    if bump == "minor":
        return "{0}.{1}.0".format(major, minor + 1)
    return "{0}.{1}.{2}".format(major, minor, patch + 1)


NO_PATTERN = (
    "release.tag_pattern is not set, so the version cannot be read out of the last "
    "tag. `v1.2.0` and `1.2.0` are one release under two spellings and only the "
    "repository knows which; stripping a leading `v` on a hunch reads a number out "
    "of a tag that never carried one."
)

NOT_A_TRIPLE = (
    "does not spell a major.minor.patch triple, and this rule does not reason about "
    "a spelling it cannot take apart"
)


def _baseline(repo, given, config, config_path):
    """(current, source, problem). `current` is a triple or None."""
    if given is not None:
        if TRIPLE.match(given.strip()):
            return given.strip(), "given", None
        return None, None, "the version given " + NOT_A_TRIPLE

    release = (config or {}).get("release")
    pattern = release.get("tag_pattern") if isinstance(release, dict) else None
    if not isinstance(pattern, str) or VERSION_PLACEHOLDER not in pattern:
        return None, None, NO_PATTERN

    delta = release_delta.compute(repo, None, config_path)
    if delta["state"] != release_delta.STATE_DELTA or not delta["tag"]:
        return None, None, (
            "no previous tag was found, so there is no version to bump from ({0})"
        ).format(_one_line(delta["reason"], 120))

    prefix, suffix = pattern.split(VERSION_PLACEHOLDER, 1)
    tag = delta["tag"]
    if not tag.startswith(prefix) or not tag.endswith(suffix):
        return None, None, (
            "the last tag does not fit release.tag_pattern, so no version can be "
            "read out of it"
        )
    end = len(tag) - len(suffix) if suffix else len(tag)
    inner = tag[len(prefix):end]
    if not TRIPLE.match(inner):
        return None, None, "the last tag " + NOT_A_TRIPLE
    return inner, "tag", None


def compute(repo=".", frag_dir=None, current=None, config_path=None):
    """The version proposal for `repo`. Always returns a payload; never raises."""
    repo = Path(repo)
    config_path = Path(config_path) if config_path else repo / CONFIG_NAME
    config, config_problem = _read_config(config_path)

    directory, problem = _fragment_dir(repo, frag_dir, config)
    if problem is not None:
        return _undecided(problem, config_problem or "")

    scan, problem = _scan(directory)
    if problem is not None:
        return _undecided(problem, str(directory))

    payload = _undecided()
    payload.update(
        {
            "fragments": scan["count"],
            "sections": dict(sorted(scan["sections"].items())),
            "declared_breaking": _names(scan["breaking"]),
            "declared_compatible": _names(scan["compatible"]),
            "undeclared": _names(scan["undeclared"]),
            "unreadable": _names(name for name, _cause in scan["unreadable"]),
            # Pairs rather than a mapping: two file names can reduce to the same
            # printable ASCII line, and a dict would silently keep one of them.
            "unreadable_causes": [
                [_one_line(name, 120), cause] for name, cause in scan["unreadable"]
            ],
            "assumed_compatible": (
                scan["count"]
                - len(scan["breaking"])
                - len(scan["compatible"])
                - len(scan["unreadable"])
                - len(scan["undeclared"])
            ),
        }
    )

    if scan["count"] == 0:
        payload["reason"] = (
            "there are no fragments, so there is no evidence to propose a number "
            "from. A release with nothing recorded is a release nobody can read."
        )
        return payload
    if scan["unreadable"]:
        payload["reason"] = _unreadable_reason(scan["unreadable"])
        return payload
    if scan["undeclared"]:
        payload["reason"] = (
            "{0} removal fragment(s) declare no compatibility verdict, and whether a "
            "removal breaks anything is the question the number turns on. Add a "
            "`- Compatibility: breaking|compatible - <reason>` bullet."
        ).format(len(scan["undeclared"]))
        return payload

    change_class = _classify(scan)
    payload["change_class"] = change_class

    current, source, problem = _baseline(repo, current, config, config_path)
    if problem is not None:
        payload["state"] = STATE_NO_BASELINE
        payload["reason"] = problem
        return payload

    major = int(current.split(".")[0])
    line = LINE_ZERO if major == 0 else LINE_STABLE
    bump = _bump_for(change_class, major)
    payload.update(
        {
            "state": STATE_PROPOSED,
            "current": current,
            "baseline": source,
            "line": line,
            "bump": bump,
            "version": _next(current, bump),
            "reason": _reason(change_class, line, bump),
        }
    )
    return payload


def _reason(change_class, line, bump):
    if change_class == CLASS_BREAKING and line == LINE_ZERO:
        return (
            "a breaking change in a 0.x line, which the 0.x convention folds into a "
            "minor rather than a major -- said out loud, because a maintainer who "
            "wants 1.0.0 here has to override rather than notice nothing"
        )
    return "a {0} change in a {1} line, so the proposal is a {2}".format(
        change_class, line, bump
    )


HEADINGS = {
    STATE_PROPOSED: "proposed",
    STATE_NO_BASELINE: "no baseline",
    STATE_COULD_NOT_DECIDE: "could not decide",
}

PROPOSAL_NOTE = (
    "a proposal. skills/manager/phases/release.md gate 4 accepts it by default and records the "
    "acceptance -- override remains available, and a major bump keeps its own stop."
)

NO_NUMBER_NOTE = (
    "NONE -- this rule names no number when it could not decide one. A default bump "
    "over a breaking change is indistinguishable in the tag from a considered one."
)

NO_BASELINE_NOTE = (
    "NONE -- the change class is known and the version it applies to is not. Pass "
    "--current, or write release.tag_pattern into the config."
)


def receipt(payload):
    """One block a human reads. No text from inside a fragment appears in it."""
    lines = ["release-version: {0}".format(HEADINGS[payload["state"]])]

    def row(label, value):
        if value not in (None, "", [], {}):
            lines.append("{0:<13}: {1}".format(label, value))

    row("reason", payload["reason"])
    row("detail", payload["detail"])
    if payload["fragments"] is not None:
        counts = ", ".join(
            "{0} {1}".format(name, count)
            for name, count in sorted(payload["sections"].items())
        )
        row(
            "fragments",
            "{0}{1}".format(
                payload["fragments"], " ({0})".format(counts) if counts else ""
            ),
        )
    row("breaking", ", ".join(payload["declared_breaking"]))
    row("compatible", ", ".join(payload["declared_compatible"]))
    row("undeclared", ", ".join(payload["undeclared"]))
    # Each name carries its own cause. With two unreadable fragments for two
    # different reasons, a reason line alone cannot say which file had which, and
    # `unreadable` is the row a maintainer acts on.
    known = dict(CAUSE_TEXT)
    row(
        "unreadable",
        ", ".join(
            "{0} ({1})".format(
                name,
                known.get(cause, "a cause this rule cannot describe ({0})".format(cause)),
            )
            for name, cause in payload["unreadable_causes"]
        ),
    )
    if payload["assumed_compatible"] is not None:
        lines.append(
            "{0:<13}: {1} fragment(s) declared nothing and are assumed "
            "compatible".format("assumed", payload["assumed_compatible"])
        )
    row("change", payload["change_class"])
    row("line", payload["line"])
    row(
        "current",
        None
        if payload["current"] is None
        else "{0} (from the {1})".format(payload["current"], payload["baseline"]),
    )
    row("bump", payload["bump"])

    if payload["state"] == STATE_PROPOSED:
        lines.append(
            "{0:<13}: {1} -- {2}".format("proposal", payload["version"], PROPOSAL_NOTE)
        )
    elif payload["state"] == STATE_NO_BASELINE:
        lines.append("{0:<13}: {1}".format("proposal", NO_BASELINE_NOTE))
    else:
        lines.append("{0:<13}: {1}".format("proposal", NO_NUMBER_NOTE))
    return "\n".join(lines)


EXITS = {
    STATE_PROPOSED: EXIT_PROPOSED,
    STATE_NO_BASELINE: EXIT_NO_BASELINE,
    STATE_COULD_NOT_DECIDE: EXIT_COULD_NOT_DECIDE,
}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Propose the version number for a release from the changelog fragments, "
            "in three states: proposed, no-baseline, could-not-decide."
        ),
        epilog=(
            "exit 0 = proposed; exit 3 = could not decide; exit 4 = no baseline. "
            "Nothing but `proposed` names a number."
        ),
    )
    parser.add_argument("--repo", default=".", help="repository to read (default: .)")
    parser.add_argument(
        "--dir",
        dest="frag_dir",
        default=None,
        help=(
            "fragment directory (default: changelog_dir from the config, resolved "
            "against --repo). It is never guessed."
        ),
    )
    parser.add_argument(
        "--current",
        default=None,
        help=(
            "the version being released from, e.g. 0.4.0. Without it the number is "
            "read out of the last tag through release.tag_pattern."
        ),
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="config to read (default: {0} beside --repo)".format(CONFIG_NAME),
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the payload instead of the receipt"
    )
    args = parser.parse_args(argv)

    # A path is not ours to choose, and a Windows console encodes stdout with its own
    # codepage rather than this file's.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - very old Python
            pass

    payload = compute(args.repo, args.frag_dir, args.current, args.config_path)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(receipt(payload))
    return EXITS[payload["state"]]


if __name__ == "__main__":
    sys.exit(main())
