"""#779: `user_visible_paths` -- an optional `.oss.json` key naming regexes for
paths this repository considers user-visible, so a pull request touching only
docs/tests-shaped paths can be exempted from the "add a changelog fragment"
gate without a human applying the `no-changelog` label by hand.

Absent/null is the default and must leave today's behaviour byte-identical:
every non-empty diff with no fragment fails, same as before this key existed.

Three things the acceptance bar names, each with its own test below:

1. The exemption sits BELOW the deleted-fragment branch: `git rm` on a pending
   fragment is refused even when `user_visible_paths` is configured and none
   of the changed paths match it.
2. The value is contributor-writable and validated: an unparseable/empty shape
   is a stated refusal (`oss_config.user_visible_paths_problem`), never a
   silent "nothing is user-visible" that would turn the gate off for the
   whole repo.
3. The receipt names which branch fired: `skipped (no user-visible paths
   changed)` is distinguishable from the pre-existing `skipped (...label...)`
   and `skipped (...dependabot...)` branches and from an ordinary pass.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402
import scaffold  # noqa: E402


def _config(**overrides):
    config = {
        "repo": "owner/name",
        "default_branch": "main",
        "clone": "/src/name",
        "worktree_root": "/src/name-wt",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": [".claude-plugin/plugin.json", "README.md"],
        "changelog_dir": "changelog.d",
        "docs_targets": ["README.md"],
        "labels": {"priority": ["priority-high"], "lanes": []},
        "state_file": ".max/oss-watch.json",
    }
    config.update(overrides)
    return config


# --------------------------------------------------------- oss_config validation


def test_null_is_fine_the_default_reading():
    assert oss_config.user_visible_paths_problem(None) is None


def test_a_legitimate_list_of_regexes_is_fine():
    assert oss_config.user_visible_paths_problem([r"^docs/", r"^README\.md$"]) is None


def test_not_a_list_is_refused():
    problem = oss_config.user_visible_paths_problem("^docs/")
    assert problem is not None
    assert "user_visible_paths" in problem


def test_an_empty_list_is_refused_not_read_as_nothing_is_user_visible():
    """The acceptance bar's own words: an empty pattern set must not silently
    turn the gate off for the whole repo."""
    problem = oss_config.user_visible_paths_problem([])
    assert problem is not None


def test_an_unparseable_regex_is_refused():
    problem = oss_config.user_visible_paths_problem(["("])
    assert problem is not None


def test_a_single_quote_is_refused_shell_injection_surface():
    """This value is embedded, single-quoted, into a `run:` line of the
    generated workflow (like `changelog_dir` already is) -- a quote character
    would close that literal early."""
    problem = oss_config.user_visible_paths_problem(["docs/'; rm -rf /; echo '"])
    assert problem is not None


def test_a_perl_only_lookahead_is_refused_grep_e_cannot_parse_it():
    """Found by review (#779): `oss_config.user_visible_paths_problem` used to
    validate with Python's `re.compile`, but the value is spliced into a
    `grep -E` (POSIX ERE) invocation at runtime -- a different grammar.
    `(?=...)` is ordinary Python `re` and a `grep -E` SYNTAX ERROR (exit 2),
    which the generated workflow's `if ! grep -Eq ...; then skip; fi` cannot
    tell apart from a genuine no-match -- so an accepted-but-unparseable
    pattern silently and permanently turns the gate off for the whole repo,
    the exact failure the acceptance bar names by name for an empty list."""
    problem = oss_config.user_visible_paths_problem(["(?=README)"])
    assert problem is not None


def test_a_non_capturing_group_is_refused_same_reason():
    problem = oss_config.user_visible_paths_problem(["(?:docs|README)"])
    assert problem is not None


def test_a_perl_only_backslash_class_is_refused():
    """`\\d`, `\\w`, `\\s`, `\\A`, `\\Z`, `\\b`... are not POSIX ERE. Every
    backslash-letter escape is refused rather than allow-listed one at a
    time, because whether a given one happens to work is a GNU-grep-version
    question this validator cannot answer on the maintainer's own machine."""
    problem = oss_config.user_visible_paths_problem([r"^docs/\d+"])
    assert problem is not None


def test_an_ordinary_ere_pattern_still_validates():
    """Positive control for the three refusals above: a pattern using only
    POSIX ERE syntax -- anchors, character classes, alternation, quantifiers,
    a backslash-escaped metacharacter -- is still accepted."""
    assert (
        oss_config.user_visible_paths_problem(
            [r"^docs/", r"^README\.md$", r"^(docs|tests)/"]
        )
        is None
    )


@pytest.mark.parametrize(
    "pattern",
    [
        "a{1,2,3}",  # three counts -- grep -E: "invalid repetition count(s)"
        "a{",  # unbalanced brace -- grep -E: "braces not balanced"
    ],
)
def test_a_malformed_brace_interval_is_refused(pattern):
    """#1015: `re.compile` reads `a{1,2,3}` as eight literal characters (it does
    not match Python's own interval grammar either, so it never raises), and
    `a{` as a literal open brace with nothing to say about balance. Measured
    directly: both BSD grep (`/usr/bin/grep` on macOS) and ugrep exit 2,
    SYNTAX ERROR, on each of these patterns. The generated
    `if ! grep -Eq PATTERN; then skip; fi` guard cannot tell that apart from
    a genuine no-match, so an accepted-but-malformed pattern like this
    silently and permanently disables the changelog gate for the whole
    repository."""
    problem = oss_config.user_visible_paths_problem([pattern])
    assert problem is not None, pattern


def test_a_well_formed_brace_interval_still_validates():
    """Positive control for the pair above: `{m}`, `{m,}` and `{m,n}` with
    m <= n are real POSIX ERE interval bounds and must still be accepted."""
    assert (
        oss_config.user_visible_paths_problem(
            [r"^v[0-9]{4}/", r"^docs/.{2,}", r"^a{1,3}$"]
        )
        is None
    )


@pytest.mark.parametrize(
    "pattern",
    [
        "a{99999}",  # #1058: well beyond either known grep-family limit
        "a{40000}",
        "a{32768}",  # #1058 (revised, self-review): one past GNU's documented
        # RE_DUP_MAX (32767) -- the limit that actually binds,
        # since the generated changelog-gate workflow always runs
        # on `ubuntu-latest` (GNU grep), confirmed in
        # `scripts/scaffold.py`'s own template and this repo's own
        # generated `.github/workflows/changelog.yml`, never on
        # BSD grep. Found by the auditor spawn in self-review: the
        # original 255 (BSD's measured RE_DUP_MAX) refused values
        # the actual deployed runner accepts fine.
        "a{1,32768}",  # the upper bound of a range can carry the same defect
    ],
)
def test_a_brace_interval_magnitude_above_the_grep_limit_is_refused(pattern):
    """#1058: `_brace_interval_problem` validated the *arrangement* of a
    `{m,n}` interval but never its *magnitude*. `a{99999}` (and any bound
    above 32767) was ACCEPTED, but `grep -Eq` on GNU grep -- the grep the
    generated changelog-gate workflow always runs, on `ubuntu-latest` --
    exits 2 (invalid repetition count) once a bound exceeds its documented
    `RE_DUP_MAX` of 32767, so an accepted pattern silently and permanently
    disables the gate, the same failure #1015 closed at the arrangement
    boundary, reopened here at the magnitude boundary. The refusal must
    name the limit that was exceeded."""
    problem = oss_config.user_visible_paths_problem([pattern])
    assert problem is not None, pattern
    assert "32767" in problem, problem


@pytest.mark.parametrize(
    "pattern",
    [
        "a{32767}",  # #1058: at GNU grep's documented RE_DUP_MAX -- must still pass
        "a{1,32767}",
        "a{5000}",  # #1058 (revised, self-review): within GNU's limit even
        # though it is well past BSD's much lower one -- the
        # deployed runner is always GNU grep, so this must not be
        # refused just because a different grep family would
        # reject it.
        "a{99999999999999}",  # #1058 (revised, self-review): a value so large
        # `int()` still parses it but it dwarfs either
        # limit -- not a magnitude-overflow crash, just
        # an ordinary refusal.
    ],
)
def test_a_brace_interval_magnitude_at_or_below_the_grep_limit_still_validates(pattern):
    """Positive control for the pair above: a magnitude within GNU grep's
    documented `RE_DUP_MAX` (32767) -- the grep that actually runs the
    generated guard -- must still be accepted, even when it exceeds BSD
    grep's much lower, but practically irrelevant, limit."""
    if pattern == "a{99999999999999}":
        # Found in self-review: Python's own `re.compile` raises
        # `OverflowError`, not `re.error`, once a repetition count exceeds
        # CPython's internal `MAXREPEAT` -- a crash this validator must
        # turn into an ordinary refusal rather than propagate, well before
        # `_brace_interval_problem`'s own magnitude check is ever reached.
        problem = oss_config.user_visible_paths_problem([pattern])
        assert problem is not None, pattern
        assert "valid regular expression" in problem, problem
        return
    assert oss_config.user_visible_paths_problem([pattern]) is None, pattern


@pytest.mark.parametrize(
    "pattern",
    [
        "[{]",  # a bracket expression whose sole content is `{`
        "[a{]",  # `{` alongside an ordinary character inside the brackets
        "[^{]",  # negated bracket expression containing `{`
        "[]{]",  # leading `]` per POSIX bracket-expression rules -- literal `]`
        "[^]{]",  # negated leading `]` -- literal `]`, then `{`
    ],
)
def test_a_brace_inside_a_bracket_expression_is_not_an_interval_opener(pattern):
    """#1059: `_brace_interval_problem` did not track bracket-expression
    (`[...]`) state while scanning for `{`/`}`, so a `{` inside one was
    misread as an interval opener and the whole value refused with a reason
    that is not true of it -- `{` can never be an interval bound inside a
    POSIX ERE bracket expression, and `grep -Eq '[{]'` is an ordinary
    (non-erroring, exit 1 on no match) pattern, not a syntax error. `[]abc]`
    and `[^]abc]` both start their bracket content after that leading `]`,
    per POSIX bracket-expression rules, so it must not be read as the
    closing bracket."""
    assert oss_config.user_visible_paths_problem([pattern]) is None, pattern


def test_a_genuine_interval_outside_any_bracket_is_still_correctly_validated():
    """Positive control for the bracket-expression skip above: a real
    interval bound sitting outside any `[...]` must still be scanned and
    validated exactly as before -- both the malformed and well-formed
    cases."""
    assert oss_config.user_visible_paths_problem(["[abc]{1,3}"]) is None
    problem = oss_config.user_visible_paths_problem(["[abc]{"])
    assert problem is not None
    assert "unbalanced" in problem


@pytest.mark.parametrize(
    "pattern",
    [
        "[[:alpha:]{]",  # a `{` still logically inside the bracket,
        # after a named POSIX character class
        "[[:digit:]{99999}]",  # a would-be over-limit magnitude, but it too
        # sits inside the bracket and is just literal
        # characters to `grep -E`, not an interval
        "[a[:digit:]{]",
        "[[.hyphen.]{]",  # a collating-symbol sub-expression
        "[[=a=]{]",  # an equivalence-class sub-expression
    ],
)
def test_a_brace_after_a_posix_bracket_subexpression_is_not_an_interval_opener(pattern):
    """Found by both self-review spawns (Explore and oss:auditor):
    #1059's bracket-expression skip closed the bracket at the *first* `]`
    it found, which is wrong once the bracket contains a POSIX named
    character class (`[:alpha:]`), collating symbol (`[.sym.]`) or
    equivalence class (`[=eq=]`) sub-expression -- each of those carries
    its own `]` before the outer bracket's real close. Closing early left
    the remaining bracket content (which may contain a literal `{`, digits
    or `}` with no interval meaning at all) scanned by the top-level loop
    as though it were outside any bracket, misreading it as a genuine
    interval opener -- the exact defect class #1059 was filed to close,
    recurring for a bracket sub-grammar the original fix's scan never
    considered. Measured directly: `grep -Eq '[[:alpha:]{]'` and
    `grep -Eq '[[:digit:]{99999}]'` both exit 0 (an ordinary ERE bracket
    expression, ordinary no-match on this input), not a syntax error."""
    assert oss_config.user_visible_paths_problem([pattern]) is None, pattern


def test_a_genuine_interval_after_a_posix_bracket_subexpression_still_validates():
    """Positive control for the pair above: once the bracket sub-expression
    genuinely closes, a real interval bound sitting after it must still be
    scanned and validated exactly as before."""
    assert oss_config.user_visible_paths_problem(["[[:alpha:]]{1,3}"]) is None
    problem = oss_config.user_visible_paths_problem(["[[:alpha:]]{99999}"])
    assert problem is not None
    assert "32767" in problem


def test_a_repetition_count_beyond_pythons_own_limit_is_refused_not_crashed():
    """Found in self-review (pre-existing, not introduced by #1058/#1059):
    `re.compile` raises `OverflowError`, not `re.error`, once a `{...}`
    repetition count exceeds CPython's own internal `MAXREPEAT`
    (2**32 - 1) -- and the validator used to catch only `re.error`, so a
    value this large propagated an unhandled exception out of
    `user_visible_paths_problem` instead of the stated refusal every other
    malformed value gets. Confirmed against the pre-fix function: it
    raises `OverflowError: the repetition number is too large`."""
    problem = oss_config.user_visible_paths_problem(["a{99999999999999}"])
    assert problem is not None
    assert "valid regular expression" in problem


@pytest.mark.parametrize("byte", ["\r", "\u2028", "\x0b"])
def test_a_yaml_line_break_character_is_refused(byte):
    """#1018: the previous validator denylisted `'` and `\\n` individually and
    missed `\\r`, U+2028 (the YAML line separator) and VT (`\\x0b`) -- all of
    which are YAML line breaks that either silently vanish into the grep
    alternation (permanent skip) or terminate the generated workflow's block
    scalar mid-parse. Refused by an anchored allow-list of printable ASCII
    now, the same shape `CHANGELOG_UNTAGGED_RE` already uses, rather than a
    denylist patched a third time."""
    problem = oss_config.user_visible_paths_problem(["docs/" + byte + "x"])
    assert problem is not None, repr(byte)


def test_printable_ascii_still_validates_positive_control_for_the_allow_list():
    """Positive control for the allow-list above: an ordinary pattern using
    only printable ASCII (letters, digits, ERE metacharacters, `~`, `%`)
    still validates -- the allow-list must not be narrower than POSIX ERE
    itself."""
    assert oss_config.user_visible_paths_problem([r"^docs/[A-Za-z0-9_~%.-]+$"]) is None


# --------------------------------------------------------- rendered workflow


def test_absent_key_renders_no_exemption_block_pattern():
    """Default: nothing declared, so the generated workflow's exemption guard
    never fires -- the substituted pattern is empty, which makes the `[ -n ]`
    test around it false on every run.

    Caught by review (#779): the earlier version of this assertion,
    `"if [ -n '' ]" in body or "if [ -n \"\" ]" not in body`, was a tautology
    -- the second disjunct is true regardless of what the first substitution
    produced, because the template never uses the double-quoted spelling at
    all. Asserting the exact rendered guard line directly is what actually
    exercises `user_visible_pattern()` returning `""` for an absent key.
    """
    body = scaffold.render_owned(".github/workflows/oss-changelog.yml", _config())
    assert "no user-visible paths changed" in body
    assert "if [ -n '' ]; then" in body


def test_a_declared_list_is_rendered_into_the_workflow():
    body = scaffold.render_owned(
        ".github/workflows/oss-changelog.yml",
        _config(user_visible_paths=[r"^docs/", r"^README\.md$"]),
    )
    assert r"^docs/" in body
    assert "no user-visible paths changed" in body


def test_the_exemption_check_sits_below_the_deleted_fragment_branch():
    """Acceptance bar #1: the fragment-deletion refusal must appear earlier in
    the generated script than the new exemption branch."""
    body = scaffold.render_owned(
        ".github/workflows/oss-changelog.yml",
        _config(user_visible_paths=[r"^docs/"]),
    )
    deleted_branch = body.index("deleted without being assembled")
    exemption_branch = body.index("no user-visible paths changed")
    assert deleted_branch < exemption_branch


def test_the_three_skip_receipts_are_distinguishable():
    body = scaffold.render_owned(
        ".github/workflows/oss-changelog.yml",
        _config(user_visible_paths=[r"^docs/"]),
    )
    assert "skipped (no user-visible paths changed)" in body
    # the pre-existing label escape hatch and dependabot exemption still read
    # differently
    assert "'no-changelog' label present" in body
    assert "dependabot" in body


def test_an_unparseable_config_refuses_at_render_time_rather_than_shipping_silently():
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.render_owned(
            ".github/workflows/oss-changelog.yml",
            _config(user_visible_paths=[]),
        )


# ----------------------------------------------------- real shell execution (#996)
#
# Everything above reads the RENDERED TEXT of the workflow. Its sibling files
# (`tests/test_changelog_gate.py`, `tests/test_bot_pull_request_293.py`,
# `tests/test_changelog_label_live_read_777.py`) all put the extracted `run:` body in
# front of a real git repository and read the exit status instead -- because a defect
# in what the shell actually DOES is invisible to a text assertion (#87 is the reason
# `test_changelog_gate.py` exists at all). This file had none of that until #996: two
# diagnostic passes had to reason about the generated script from outside because
# nothing here ever actually ran it.
#
# Reuses the shared harness (`_gate_script`, `_child_env`, `_pull_request`, `_require`,
# `BASH`) from `tests/test_changelog_gate.py` rather than reinventing shell-extraction
# machinery, exactly as the sibling files already do.

from test_changelog_gate import (  # noqa: E402
    BASH,
    _child_env,
    _config as _shared_config,
    _gate_script,
    _pull_request,
    _require,
    _run_script,
)


def _user_visible_config(**overrides):
    """The shared harness's own `_config()`, with `user_visible_paths` overrides
    layered on top -- this file's local `_config()` above is for the render-only
    tests and is not what `_gate_script()` needs, since the extracted `run:` body
    has to come from the same rendering `_step_script` uses.
    """
    return _shared_config(**overrides)


def _run_gate(repo, config):
    for tool in ("git", "grep", "sed"):
        _require(tool)
    return _run_script(_gate_script(config), repo, _child_env(BASH, BASE_REF="main"))


# A pull request that changes only a path the config below declares user-visible
# (`^docs/`), adds no fragment: the exemption must NOT reach this -- declaring
# `user_visible_paths` narrows what counts, it does not blanket-exempt a repo.
VISIBLE_ONLY = {"docs/guide.md": "a new sentence\n"}

# A pull request that changes only a path OUTSIDE the declared pattern, adds no
# fragment: the shape the exemption exists for.
NOT_VISIBLE_ONLY = {"tests/harness.py": "value = 2\n"}


def test_a_path_not_matching_user_visible_paths_is_skipped_and_says_so(tmp_path):
    """The 'must fire' half of the pair below: a diff that touches only a path the
    config did NOT declare user-visible is exempted, and the receipt says which
    branch fired rather than reading like an ordinary pass or the label escape hatch.
    """
    config = _user_visible_config(user_visible_paths=[r"^docs/"])
    repo = _pull_request(tmp_path, NOT_VISIBLE_ONLY)
    done = _run_gate(repo, config)
    assert done.returncode == 0, done.stdout
    assert "skipped (no user-visible paths changed)" in done.stdout, done.stdout


def test_a_path_matching_user_visible_paths_is_still_refused(tmp_path):
    """The 'must not fire' half: a diff that DOES touch a path the config declared
    user-visible is refused exactly as it would be with no config at all --
    declaring `user_visible_paths` narrows the exemption, it does not turn the gate
    off for the paths it names.
    """
    config = _user_visible_config(user_visible_paths=[r"^docs/"])
    repo = _pull_request(tmp_path, VISIBLE_ONLY)
    done = _run_gate(repo, config)
    assert done.returncode == 1, done.stdout
    assert "No changelog fragment" in done.stdout, done.stdout


def test_with_no_user_visible_paths_configured_the_same_diff_is_still_refused(tmp_path):
    """Positive control for the first test above: without the key declared at all,
    the identical NOT_VISIBLE_ONLY diff is NOT exempted -- proving the skip in the
    first test came from the configured pattern genuinely not matching, not from
    some other branch (`nothing changed`, the label, dependabot) firing instead.
    """
    config = _user_visible_config()
    repo = _pull_request(tmp_path, NOT_VISIBLE_ONLY)
    done = _run_gate(repo, config)
    assert done.returncode == 1, done.stdout
    assert "No changelog fragment" in done.stdout, done.stdout


def test_a_fragment_present_still_passes_even_with_user_visible_paths_configured(
    tmp_path,
):
    """A fragment satisfies the gate regardless of `user_visible_paths` -- the
    exemption is an additional way to pass, never a narrower way to fail."""
    config = _user_visible_config(user_visible_paths=[r"^docs/"])
    repo = _pull_request(
        tmp_path,
        {"src.py": "value = 2\n", "changelog.d/925.fixed.md": "- a fix (#925).\n"},
    )
    done = _run_gate(repo, config)
    assert done.returncode == 0, done.stdout
    assert "925.fixed.md" in done.stdout, done.stdout


def test_deleting_a_fragment_is_refused_even_when_the_rest_of_the_diff_is_user_visible_only(
    tmp_path,
):
    """Acceptance bar #1, executed rather than read: the deleted-fragment branch
    sits ABOVE the user-visible-paths exemption, so losing a pending fragment is
    refused even when every OTHER changed path matches the configured pattern.
    """
    config = _user_visible_config(user_visible_paths=[r"^docs/"])
    repo = _pull_request(
        tmp_path,
        {"docs/guide.md": "a new sentence\n", "changelog.d/906.added.md": None},
    )
    done = _run_gate(repo, config)
    assert done.returncode == 1, done.stdout
    assert "deleted without being assembled" in done.stdout, done.stdout
