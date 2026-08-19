"""#144 asked for a tools rule on `Agent`. #307 is the day the blocker went away.

#144 proposed a `01-oss` rule in the **tools** dimension keyed on the `Agent` tool, so the
standing clauses every brief re-types from memory arrive at dispatch time instead. It could
not be built: `pre-tool-hook.sh` built the subject its tool rules match against from four
keys -- `command`, `skill`, `file_path`, `pattern` -- and an `Agent` payload carries
`subagent_type`, `description` and `prompt`. The subject came out empty, the hook printed
`{}` and exited before the layer loop, and a `tool: Agent` row would have indexed cleanly,
listed healthy in every diagnostic, and never once fired. So #144 shipped a **recorded gap**
in the layer's `00-README.md` and a test written to fail loudly the day the dependency
closed it.

That day came. `claude-jit-context` **0.5.0** reads `subagent_type` as a fifth subject key
(its own #182), and also grew a third state for the case that motivated it: a dispatch
carrying none of the five now returns a notice naming the rules that were indexed, counted
and never reached, instead of the same `{}` a no-match returns.

**So the record is no longer about a gap, and neither is this file.** What replaced both is
narrower and has to be measured rather than assumed, because the useful successor to "the
rule cannot fire" is not "the rule fires" -- it is *what it fires on*:

  1. no `Agent` rule is shipped yet    a decision, recorded in the layer, not an oversight
  2. the record ships and is not a rule the layer documents itself without inflating counts
  3. the subject is `subagent_type`    driven against the installed hook, with controls

(3) is the one that matters and it is the one CI cannot reach: the pytest legs are green on
every platform because a runner installs no plugin, so this measures only where the
dependency is actually present. Where nothing can be measured it skips and names what went
untested; it never reports a capability as confirmed by a harness that saw nothing.

Python 3.9 compatible.
"""

import os
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import doctor  # noqa: E402
import jit_hook_harness  # noqa: E402
import oss_rules  # noqa: E402

LAYER_RECORD = "00-README.md"

#: Distinct, neither a substring of the other, ASCII only. The hook's reason string is
#: written to a pipe and read back through the console's codepage; an arrow or a box-drawing
#: glyph here would raise `UnicodeEncodeError` on cp1252 rather than fail an assertion.
AGENT_SENTINEL = "AGENT-RULE-FIRED"
OTHER_SENTINEL = "OTHER-AGENT-RULE-FIRED"
BASH_SENTINEL = "BASH-CONTROL-FIRED"

#: The `subagent_type` the fabricated `Agent` rule is written to match, and the one it is
#: written to miss. Arbitrary strings, deliberately not this plugin's real agent names: the
#: question is what the hook does with the key, not what any particular agent is called.
MATCHED_SUBAGENT = "ossfixture:one"
UNMATCHED_SUBAGENT = "elsewhere:two"


def _layer_label():
    """How `doctor` names this layer in its own output, on the platform running the test.

    `check_jit_rules` builds the label from `layer.relative_to(rules_dir)`, a `PurePath`,
    so it joins with a backslash on Windows and a forward slash everywhere else. A literal
    forward-slash spelling matched nothing on all four Windows legs -- and because the
    filter then returned an empty list, the failure surfaced as the positive control
    firing (`the tools layer was not reported at all`), which reads as the diagnostic
    having gone silent rather than as the test having asked in the wrong dialect. The
    control was right; the question was wrong.

    Derived rather than branched on `os.name`: the separator this needs is whichever one
    `PurePath` will use, and `os.path.join` is the same answer from the same source.
    """
    return os.path.join("tools", oss_rules.LAYER)


# --- 1. no Agent rule is shipped yet, with the control that makes an absence mean something


def test_no_tools_rule_is_keyed_on_the_agent_tool():
    """Still a deliberate absence, and for a different reason than it was under #144.

    The blocker is gone: 0.5.0 reads `subagent_type`, so a `tool: Agent` rule fires and can
    key on which agent was dispatched. What has not been decided is what such a rule should
    *say* -- it fires on dispatch, where the standing clauses live in the agent definition
    being dispatched, and a second copy of them in this layer is the drift the layer's own
    record warns about. That is a design decision with its own review, not a rider here.

    Paired with the must-fire half below: on its own this assertion is equally satisfied by
    a tools dimension that ships nothing at all, or by an accessor that returns nothing.
    """
    keyed = []
    for name, body in oss_rules.RULES.get("tools", {}).items():
        tool = oss_rules._field(body, "tool") or ""
        if "Agent" in [alt.strip() for alt in tool.split("|")]:
            keyed.append(name)
    assert not keyed, (
        "{} is keyed on the Agent tool. That is now buildable -- the dependency reads "
        "subagent_type -- but what such a rule should say has not been decided, and {} in "
        "the tools layer records the two questions it turns on.".format(
            keyed, LAYER_RECORD
        )
    )


def test_the_tools_dimension_still_ships_a_rule_that_is_keyed():
    """The must-fire half of the fixture above.

    A tools rule keyed on a tool the hook does read, so "no Agent rule" is a statement about
    `Agent` rather than about an empty dimension or a broken field accessor.
    """
    keyed = {
        name: oss_rules._field(body, "tool")
        for name, body in oss_rules.RULES.get("tools", {}).items()
        if oss_rules._field(body, "tool")
    }
    assert keyed, "the tools dimension ships no keyed rule at all"


# --- 2. the decision is recorded, and the record is not itself a rule -------------------


def test_the_decision_is_recorded_in_the_layer_rather_than_only_in_the_issue():
    """A decision nobody wrote down reads as an oversight, and gets re-proposed.

    The layer is replaced wholesale on every install, so the record has to be something
    `oss_rules.install()` writes: a file added by hand in this repository survives locally
    and reaches no managed repo at all.
    """
    body = oss_rules.RULES.get("tools", {}).get(LAYER_RECORD)
    assert body, "the tools layer ships no {}".format(LAYER_RECORD)
    assert "Agent" in body, "the record does not name the tool it is about"


def test_the_record_no_longer_says_an_agent_rule_cannot_fire():
    """#307: the record outlived its cause and became a false statement this plugin writes
    into other people's repositories.

    Anchored on the retracted claim rather than on the replacement prose, so the check is
    about the sentence that went wrong. Paired below with the must-still-say half, or
    "the false sentence is gone" is equally satisfied by a record deleted down to nothing.
    """
    body = oss_rules.RULES["tools"][LAYER_RECORD]
    # Present-tense claims only. A past-tense recital of what the hook used to do is not
    # just permitted here, it is the point: the record ships into repositories whose
    # installed dependency this module cannot see, and a reader on an older one needs to
    # know the capability is version-gated. An anchor broad enough to catch the history
    # would push the record back towards asserting one version's truth unconditionally,
    # which is the shape #307 was filed about.
    for retracted in ("cannot fire", "cannot be built", "never once fires"):
        assert retracted not in body, (
            "the record still claims an Agent rule {!r}. The dependency reads "
            "subagent_type as of 0.5.0 and such a rule fires -- measured in this file "
            "(#307).".format(retracted)
        )
    assert "0.5.0" in body, (
        "the record names no version for the change, so a reader on an older dependency "
        "cannot tell whether it describes their machine"
    )


def test_the_record_still_names_what_the_subject_is_built_from():
    """The must-still-say half.

    The record's whole value to a reader is that it saves them the measurement. Naming the
    key the subject is built from is that value; without it the file is a note saying a
    decision was taken and nothing a reader can act on.
    """
    body = oss_rules.RULES["tools"][LAYER_RECORD]
    assert "subagent_type" in body, "the record does not name the subject key"
    assert "prompt" in body, (
        "the record does not say that the prompt is deliberately not the subject, which "
        "is the constraint any proposed rule has to be written against"
    )


def test_the_record_ships_into_an_installed_layer(tmp_path):
    written = oss_rules.install(tmp_path)
    record = tmp_path / ".claude" / "jit-context" / "tools" / oss_rules.LAYER / LAYER_RECORD
    assert record in written, "install() did not report writing the record"
    assert record.is_file()


def test_the_record_gets_no_index_row_but_a_real_rule_does(tmp_path):
    """Both halves in one fixture.

    The record must not be indexed: the dependency's builder skips `00-README.md` by name in
    every one of its builders, so a row written for it here would vanish on the next rebuild
    and read as index drift. The rule beside it must be indexed, or "no row for the record"
    is equally consistent with an indexer that wrote no rows at all.
    """
    oss_rules.install(tmp_path)
    layer = tmp_path / ".claude" / "jit-context" / "tools" / oss_rules.LAYER
    rows = (layer / "00-index.tsv").read_text(encoding="utf-8").splitlines()
    named = {row.split("\t")[2] for row in rows if row.strip()}
    assert LAYER_RECORD not in named, "the record was indexed as a rule"
    assert "supertool-required.md" in named, "no rule was indexed at all"

    # Why it gets no row, held directly rather than inferred from the row list above. The
    # exemption in `test_every_rule_file_is_indexed` means an added `match:` here would
    # produce a row for a filename the dependency's builder skips -- a row deleted by the
    # next rebuild and read as drift -- with nothing else in the suite going red.
    record = oss_rules.RULES["tools"][LAYER_RECORD]
    assert oss_rules._field(record, "match") is None, "the record declares a match:"
    assert oss_rules._field(record, "tool") is None, "the record declares a tool:"
    assert oss_rules._field(record, "description"), "the record declares no description:"


def test_the_diagnostic_does_not_count_the_record_as_a_rule(tmp_path, capsys):
    """`doctor` already knows `00-README.md` is not an entry -- its count did not.

    `check_jit_rules` filters the skipped name out of `entries`, which is what the drift
    comparison walks, and then reports `len(rules)` -- the unfiltered list. Nothing showed
    it while no layer carried a record, and shipping one makes a diagnostic say "2 rule(s)
    indexed" about a layer with one rule and one index row. A count that inflates when a
    layer documents itself teaches the reader to discount the count.

    Both halves in one fixture: the number must be the rule, and the layer must still be
    reported at all, or "does not say 2" is satisfied by a check that said nothing.
    """
    oss_rules.install(tmp_path)
    doctor.check_jit_rules(tmp_path)
    lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if _layer_label() in line
    ]
    assert lines, "the tools layer was not reported at all"
    reported = lines[0]
    layer = tmp_path / ".claude" / "jit-context" / "tools" / oss_rules.LAYER
    indexed = len(
        [
            row
            for row in (layer / "00-index.tsv").read_text(encoding="utf-8").splitlines()
            if row.strip()
        ]
    )
    assert "{} rule(s)".format(indexed) in reported, reported


def test_the_failure_arms_do_not_count_the_record_either(tmp_path, capsys):
    """The same count, in the branch that fires when the index is gone.

    Fixing only the healthy branch leaves a layer holding one rule and one record saying
    "2 rule(s) and no 00-index.tsv" -- and a layer holding *only* a record saying
    "1 rule(s)" about zero rules, which is a FAIL naming a rule that does not exist.
    """
    oss_rules.install(tmp_path)
    layer = tmp_path / ".claude" / "jit-context" / "tools" / oss_rules.LAYER
    (layer / "00-index.tsv").unlink()
    rules = len([p for p in layer.glob("*.md") if p.name != LAYER_RECORD])
    doctor.check_jit_rules(tmp_path)
    reported = [
        line
        for line in capsys.readouterr().out.splitlines()
        if _layer_label() in line
    ]
    assert reported, "the tools layer was not reported at all"
    assert "{} rule(s)".format(rules) in reported[0], reported[0]


# --- 3. the subject is subagent_type, driven against the installed dependency -----------


def _fabricated_layer(project):
    """A tools layer carrying two `Agent` rules and one `Bash` control.

    Fabricated rather than read out of this repository: the question is what the dependency
    does with an `Agent` row, and shipping one here to ask it would be shipping the very
    rule this file records a decision not to ship yet.

    The two `Agent` rules differ only in their `match:`, and that is what makes this a
    measurement of the *subject* rather than of the tool name. One is written to match the
    dispatched `subagent_type` and one to miss it. A single always-matching rule would fire
    just as happily against a hook that matched on the tool name alone, on an empty subject,
    or on the literal string "Agent".
    """
    directory = project / ".claude" / "jit-context" / "tools" / oss_rules.LAYER
    directory.mkdir(parents=True)
    rows = []
    for filename, tool, pattern, sentinel in (
        ("agent-matching.md", "Agent", "~^" + MATCHED_SUBAGENT.split(":")[0], AGENT_SENTINEL),
        ("agent-missing.md", "Agent", "~^" + UNMATCHED_SUBAGENT.split(":")[0], OTHER_SENTINEL),
        ("bash-control.md", "Bash", "~.*", BASH_SENTINEL),
    ):
        (directory / filename).write_text(
            '---\ntitle: "{}"\ntool: {}\nmatch: {}\n---\n\n{}\n'.format(
                filename, tool, pattern, sentinel
            ),
            encoding="utf-8",
        )
        rows.append("\t".join([tool, pattern, filename, "", "", ""]))
    (directory / "00-index.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _agent_payload(**tool_input):
    return {"tool_name": "Agent", "tool_input": tool_input}


def test_a_hook_that_never_answered_is_not_read_as_a_silent_one(tmp_path):
    """The harness's own three states, all in one fixture.

    An unspawnable binary, and a hook that runs and says nothing, must both come back as a
    *problem* rather than as empty output -- otherwise every assertion built on `drive()`
    passes on a run where nothing was measured. Paired with a stand-in that does answer, so
    "reports a problem" is not satisfied by a helper that reports one unconditionally.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH, so the answering half of this fixture cannot run")

    out, problem = jit_hook_harness.drive(
        "this-binary-does-not-exist-144", "hook.sh", tmp_path, {}
    )
    assert problem is not None, "an unspawnable binary was reported as a silent hook"
    assert out == ""

    mute = tmp_path / "mute.sh"
    mute.write_text("cat > /dev/null\n", encoding="utf-8")
    out, problem = jit_hook_harness.drive(bash, mute, tmp_path, {})
    assert problem is not None, "a hook that printed nothing was reported as an answer"

    # The must-answer half. `{}` is the hook's own way of having nothing to say, so it is
    # deliberately the reply used here: the helper has to call that an answer, or the real
    # tests below would skip on every silent-but-successful run and measure nothing.
    speaking = tmp_path / "speaks.sh"
    speaking.write_text("cat > /dev/null; printf '{}'\n", encoding="utf-8")
    out, problem = jit_hook_harness.drive(bash, speaking, tmp_path, {})
    assert problem is None, problem
    assert out.strip() == "{}"


def _driven(tmp_path):
    """`(bash, hook, project, version)` -- or a skip naming what went untested.

    The `Bash` control is fired here, once, for every test in this section. Without it an
    `Agent` answer means nothing: an empty one is equally consistent with a hook that could
    not read the layer, could not be spawned, or wrote its answer somewhere nobody looked.
    """
    hook, version, why_not = jit_hook_harness.hook_path()
    if hook is None:
        pytest.skip(
            "{} -- untested: what subject the tools dimension builds for an Agent "
            "dispatch".format(why_not)
        )
    bash = shutil.which("bash")
    project = tmp_path / "repo"
    project.mkdir()
    _fabricated_layer(project)

    control, problem = jit_hook_harness.drive(
        bash, hook, project, {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}
    )
    if problem is not None or BASH_SENTINEL not in control:
        pytest.skip(
            "the control rule did not fire, so this harness saw nothing and any Agent "
            "answer would mean nothing. Untested: what subject {} builds for an Agent "
            "dispatch. Problem: {}. Control output: {!r}".format(
                version, problem, control[:200]
            )
        )
    return bash, hook, project, version


def test_the_tools_dimension_matches_an_agent_call_on_its_subagent_type(tmp_path):
    """The successor to #144's gap assertion, inverted by #307 and narrowed.

    Both directions in one fixture, because "a rule fired" on its own does not say what it
    fired *on*. The matching rule must fire and the missing rule must not, against a single
    dispatch -- which is only possible if the subject really is the `subagent_type` string.
    """
    bash, hook, project, version = _driven(tmp_path)

    answer, problem = jit_hook_harness.drive(
        bash,
        hook,
        project,
        _agent_payload(
            subagent_type=MATCHED_SUBAGENT,
            description="implement one issue",
            prompt="Implement one issue.",
        ),
    )
    assert problem is None, problem
    assert AGENT_SENTINEL in answer, (
        "{} did not fire a tool: Agent rule whose match: covers the dispatched "
        "subagent_type {!r}. If this dependency has stopped reading subagent_type, the "
        "layer's {} is wrong again in the other direction: it now tells a reader such a "
        "rule can be built. Got: {!r}".format(
            version, MATCHED_SUBAGENT, LAYER_RECORD, answer[:300]
        )
    )
    assert OTHER_SENTINEL not in answer, (
        "a tool: Agent rule whose match: does not cover {!r} fired anyway, so the subject "
        "is not the subagent_type and a rule cannot key on which agent was "
        "dispatched".format(MATCHED_SUBAGENT)
    )


def test_an_agent_dispatch_carrying_no_subagent_type_is_reported_as_unreached(tmp_path):
    """The dependency's own third state, and the reason the record can promise anything.

    `prompt` and `description` are deliberately not read as the subject upstream, so a
    dispatch carrying only those builds no subject at all. What must not happen is the
    thing #144 filed: that case answering with the same `{}` a genuine no-match answers,
    which is what made an inert rule indistinguishable from a rule that simply did not
    apply. 0.5.0 names the unreached rules instead.

    Paired with the assertion above: that one is the must-fire, this one the must-not, and
    the same two rules are in the layer for both.
    """
    bash, hook, project, version = _driven(tmp_path)

    answer, problem = jit_hook_harness.drive(
        bash,
        hook,
        project,
        _agent_payload(description="implement one issue", prompt=UNMATCHED_SUBAGENT),
    )
    assert problem is None, problem
    for sentinel in (AGENT_SENTINEL, OTHER_SENTINEL):
        assert sentinel not in answer, (
            "an Agent rule matched a dispatch carrying no subagent_type, so the prompt or "
            "the description reached the subject. The layer record states the opposite, "
            "and a rule keyed on an agent name would fire on prose that merely mentions "
            "it. Got: {!r}".format(answer[:300])
        )
    assert "did NOT run" in answer or "no subject" in answer, (
        "{} answered a subjectless Agent dispatch without saying the rules went "
        "unreached, so an indexed-and-inert rule is again indistinguishable from one "
        "that did not match -- the defect #144 was filed about. Got: {!r}".format(
            version, answer[:300]
        )
    )
