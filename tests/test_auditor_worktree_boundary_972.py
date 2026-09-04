"""#972: a spawned `oss:auditor` ran `rm -f` against a file in the live main clone,

not the worktree its brief scoped it to -- an untracked file it decided, from its
shape alone, was its own scratch artifact. The deletion left no git-visible trace
at all, because the file was untracked. `agents/auditor.md` already told a spawn
its `Bash` grant is total and that writes should be avoided (#251, #769), but
nothing in the file named the one thing that would have stopped this specific
failure: a hard boundary the spawn is required to check a mutating target's path
against, rather than a belief about what the file looked like.

Companion to test_auditor_evidence.py and test_content_invariants.py's auditor
section, same shape: contracts are substrings that must all appear, checked
against a positive control (a plausible-but-empty auditor stub, which must fail
every contract) so the anchors cannot be satisfied by vocabulary already ambient
in the file.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDITOR = REPO_ROOT / "agents" / "auditor.md"

# id -> substrings that must all be present for the contract to be legible.
WORKTREE_BOUNDARY_CONTRACTS = [
    (
        "names-the-worktree-as-the-boundary",
        ("worktree you were briefed on", "before you run it"),
    ),
    (
        "refuse-and-report-not-skip-silently",
        ("refuse the call and report the refusal", "never skip it silently"),
    ),
    (
        "belief-about-shape-is-not-a-check-on-location",
        ("belief about the file's shape", "not a check on its location"),
    ),
    ("names-the-incident-by-number", ("#972",)),
]

ALL_CONTRACTS = {name for name, _ in WORKTREE_BOUNDARY_CONTRACTS}


def _flatten(text):
    """Fold case and collapse every run of whitespace to one space, so a
    multi-word anchor still matches after a paragraph reflow across a newline --
    these documents wrap around 100 columns.
    """
    return " ".join(text.lower().split())


def _unmet(text):
    folded = _flatten(text)
    return {
        name
        for name, anchors in WORKTREE_BOUNDARY_CONTRACTS
        if not all(anchor in folded for anchor in anchors)
    }


def test_auditor_agent_exists():
    """Without the file every check below fails for the wrong reason, and a suite
    that cannot find its subject must say which of the two it is.
    """
    assert AUDITOR.is_file(), "agents/auditor.md is missing"


def test_auditor_states_the_worktree_boundary_contract():
    unmet = _unmet(AUDITOR.read_text(encoding="utf-8"))
    assert not unmet, (
        "agents/auditor.md no longer states the worktree-boundary rule #972 "
        "exists to hold a future spawn to: " + repr(sorted(unmet))
    )


STUB_AUDITOR = (
    "---\n"
    "name: auditor\n"
    "description: Audit a diff.\n"
    "tools: Bash\n"
    "---\n\n"
    "Read the diff and report any problems you find. Your Bash grant is "
    "total, so be careful with it.\n"
)


def test_the_contract_fires_on_an_agent_that_says_nothing():
    """The must-fire half. A plausible-looking auditor stub that never states the
    rule must report every contract unmet, or the anchors are satisfied by
    something already ambient rather than by what this change wrote.
    """
    unmet = _unmet(STUB_AUDITOR)
    assert unmet == ALL_CONTRACTS, (
        "the worktree-boundary contract checks do not fire on an agent file that "
        "never states the rule, so they would also pass on one that never landed "
        "it. Not firing: " + repr(sorted(ALL_CONTRACTS - unmet))
    )


# The pre-#972 "Your Bash grant is total" section, verbatim -- what shipped before
# this issue's fix. It already warned that Bash is total and that writes should be
# avoided (#251, #769), but never named the worktree as a boundary to check a
# mutating target against, and never named this incident. Every contract above
# must report unmet against it, or these anchors are satisfied by prose that was
# already there and constrain nothing new.
THE_PRE_FIX_SECTION = """
So the request: **run only ops that read, and no bare shell that writes.** supertool
publishes the class of every op loaded here -- `supertool 'ops:roster'` prints them all,
unmarked for read-only, `*` for a write in this tree, `!` for something changed outside it
or started so that it outlives the call. Ask it rather than working from a list of names;
a list here would be a second copy of a classification the tool already publishes, and the
copy is the one that goes stale. Plain `git`, `gh`, a redirect or an inline interpreter
are `Bash` too, with nothing between them and the disk.

If a class below is genuinely unreachable without acting, **report that class as one you
could not check**, and say what stopped you. That is the third state and it is the whole
point of this repository. It is never a licence to run the op.
"""


def test_the_contract_fires_on_the_section_as_it_stood_before_972():
    unmet = _unmet(THE_PRE_FIX_SECTION)
    assert unmet == ALL_CONTRACTS, (
        "the worktree-boundary contract is satisfied by the section as it stood "
        "before #972's fix landed, so it constrains nothing new. Not firing: "
        + repr(sorted(ALL_CONTRACTS - unmet))
    )
