"""#144 asked for a tools rule on `Agent`. The dimension cannot see an `Agent` call.

#144 proposes a `01-oss` rule in the **tools** dimension, keyed on the `Agent` tool, so the
standing clauses every brief re-types from memory arrive at dispatch time instead. The issue
records itself as blocked on the layer enumeration (#119, and the dependency's own #176).
That blocker is gone: the dependency enumerates layers from disk now, and the `01-oss` tools
rule shipped beside this one refuses a native `Read` today.

A second blocker is not gone, and neither the issue nor #119 knows about it.

`pre-tool-hook.sh` builds the subject its tool rules match against from exactly four keys --
`command`, `skill`, `file_path`, `pattern` -- falling back through them in that order. An
`Agent` payload carries `subagent_type`, `description` and `prompt`, and none of those is
read. The subject is therefore empty, and the hook returns `{}` and exits **before** the
layer loop that the enumeration fix added ever runs. No `tool: Agent` row can match, at any
layer, with any `match:`, in any mode -- including `mode: block`.

So the honest artifact is not the rule. A rule shipped into that dimension would sit on
disk, index cleanly, pass every structural check in `tests/test_oss_rules.py`, be listed by
`/oss:doctor`, and never once fire -- the defect class this plugin is named after, authored
deliberately. The gap is recorded in the layer's `00-README.md` instead, a filename the
dependency's index builder skips, and the tests below hold three things:

  1. the gap is real           no tools rule is keyed on `Agent`
  2. the gap is recorded       the reason ships with the layer, not only in an issue
  3. the gap is still true     driven against the installed hook, with a control

(3) is the one that matters. It fails loudly the day the dependency starts reading an
`Agent` payload, because on that day the recorded reason becomes stale prose shipped into
every managed repo and the feature becomes buildable -- and nothing else here would notice.
Where nothing can be measured it skips and names what went untested; it never reports the
gap as confirmed by a harness that saw nothing.

Python 3.9 compatible.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
import oss_rules  # noqa: E402

GAP_RECORD = "00-README.md"

#: Distinct, neither a substring of the other, ASCII only. The hook's reason string is
#: written to a pipe and read back through the console's codepage; an arrow or a box-drawing
#: glyph here would raise `UnicodeEncodeError` on cp1252 rather than fail an assertion.
AGENT_SENTINEL = "AGENT-RULE-FIRED"
BASH_SENTINEL = "BASH-CONTROL-FIRED"


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


# --- 1. the gap is real, with the control that makes an absence mean something ----------


def test_no_tools_rule_is_keyed_on_the_agent_tool():
    """The deliberate absence #144 asks for and this repository declines to ship.

    Paired with the must-fire half below: on its own this assertion is equally satisfied by
    a tools dimension that ships nothing at all, or by an accessor that returns nothing.
    """
    keyed = []
    for name, body in oss_rules.RULES.get("tools", {}).items():
        tool = oss_rules._field(body, "tool") or ""
        if "Agent" in [alt.strip() for alt in tool.split("|")]:
            keyed.append(name)
    assert not keyed, (
        "{} is keyed on the Agent tool. The dependency's pre-tool-hook.sh reads its match "
        "subject from command/skill/file_path/pattern only, so an Agent payload leaves it "
        "empty and the hook exits before the layer loop -- the rule cannot fire. See {} in "
        "the tools layer.".format(keyed, GAP_RECORD)
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


# --- 2. the gap is recorded, and the record is not itself a rule ------------------------


def test_the_gap_is_recorded_in_the_layer_rather_than_only_in_the_issue():
    """An absence nobody wrote down reads as an oversight, and gets re-proposed.

    The layer is replaced wholesale on every install, so the record has to be something
    `oss_rules.install()` writes: a file added by hand in this repository survives locally
    and reaches no managed repo at all.
    """
    body = oss_rules.RULES.get("tools", {}).get(GAP_RECORD)
    assert body, "the tools layer ships no {}".format(GAP_RECORD)
    assert "Agent" in body, "the record does not name the tool it is about"


def test_the_gap_record_ships_into_an_installed_layer(tmp_path):
    written = oss_rules.install(tmp_path)
    record = tmp_path / ".claude" / "jit-context" / "tools" / oss_rules.LAYER / GAP_RECORD
    assert record in written, "install() did not report writing the gap record"
    assert record.is_file()


def test_the_gap_record_gets_no_index_row_but_a_real_rule_does(tmp_path):
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
    assert GAP_RECORD not in named, "the gap record was indexed as a rule"
    assert "supertool-required.md" in named, "no rule was indexed at all"

    # Why it gets no row, held directly rather than inferred from the row list above. The
    # exemption in `test_every_rule_file_is_indexed` means an added `match:` here would
    # produce a row for a filename the dependency's builder skips -- a row deleted by the
    # next rebuild and read as drift -- with nothing else in the suite going red.
    record = oss_rules.RULES["tools"][GAP_RECORD]
    assert oss_rules._field(record, "match") is None, "the record declares a match:"
    assert oss_rules._field(record, "tool") is None, "the record declares a tool:"
    assert oss_rules._field(record, "description"), "the record declares no description:"


def test_the_diagnostic_does_not_count_the_gap_record_as_a_rule(tmp_path, capsys):
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


def test_the_failure_arms_do_not_count_the_gap_record_either(tmp_path, capsys):
    """The same count, in the branch that fires when the index is gone.

    Fixing only the healthy branch leaves a layer holding one rule and one record saying
    "2 rule(s) and no 00-index.tsv" -- and a layer holding *only* a record saying
    "1 rule(s)" about zero rules, which is a FAIL naming a rule that does not exist.
    """
    oss_rules.install(tmp_path)
    layer = tmp_path / ".claude" / "jit-context" / "tools" / oss_rules.LAYER
    (layer / "00-index.tsv").unlink()
    rules = len([p for p in layer.glob("*.md") if p.name != GAP_RECORD])
    doctor.check_jit_rules(tmp_path)
    reported = [
        line
        for line in capsys.readouterr().out.splitlines()
        if _layer_label() in line
    ]
    assert reported, "the tools layer was not reported at all"
    assert "{} rule(s)".format(rules) in reported[0], reported[0]


# --- 3. the gap is still true, driven against the installed dependency ------------------


def _fabricated_layer(project):
    """A tools layer carrying one `Agent` rule and one `Bash` control, both `match: ~.*`.

    Fabricated rather than read out of this repository: the question is what the dependency
    does with an `Agent` row, and shipping one here to ask it would be shipping the very
    rule this file exists to decline.
    """
    directory = project / ".claude" / "jit-context" / "tools" / oss_rules.LAYER
    directory.mkdir(parents=True)
    rows = []
    for filename, tool, sentinel in (
        ("agent-brief.md", "Agent", AGENT_SENTINEL),
        ("bash-control.md", "Bash", BASH_SENTINEL),
    ):
        (directory / filename).write_text(
            '---\ntitle: "{}"\ntool: {}\nmatch: ~.*\n---\n\n{}\n'.format(
                filename, tool, sentinel
            ),
            encoding="utf-8",
        )
        rows.append("\t".join([tool, "~.*", filename, "", "", ""]))
    (directory / "00-index.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _child_env(project):
    """A minimal environment: enough for bash to run, nothing of this session's state."""
    keep = ("PATH", "HOME", "SYSTEMROOT", "WINDIR", "TMP", "TEMP", "LANG", "LC_ALL")
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    env["CLAUDE_PROJECT_DIR"] = str(project)
    return env


def _drive(bash, hook, project, payload):
    """`(stdout, problem)`. `problem` is `None` only when the hook actually answered.

    The two failure shapes here render identically to a substring test and must not, which
    is the whole subject of this file pointed at its own harness:

    - the spawn raised, hung past the timeout, or was killed -- `subprocess.run` raises,
      and `TimeoutExpired` is a `SubprocessError`, so a hang arrives here as an exception
      rather than as output
    - the process ran and printed nothing

    Neither is the hook saying "no rule matched". The hook's contract is to print a JSON
    object on every call -- `{}` is its way of having nothing to say -- so empty stdout is
    *no answer*, not a quiet one. Collapsing either into `""` would let `SENTINEL not in
    output` pass on a run that measured nothing, and report it as the gap holding.
    """
    try:
        done = subprocess.run(
            [bash, str(hook)],
            input=json.dumps(payload),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_child_env(project),
            universal_newlines=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", "the hook could not be run: {!r}".format(exc)
    if not done.stdout.strip():
        return done.stdout, (
            "the hook printed nothing at all (exit {}), so it did not answer. "
            "stderr: {!r}".format(done.returncode, done.stderr[-400:])
        )
    return done.stdout, None


def test_a_hook_that_never_answered_is_not_read_as_a_silent_one(tmp_path):
    """The harness's own three states, all in one fixture.

    An unspawnable binary, and a hook that runs and says nothing, must both come back as a
    *problem* rather than as empty output -- otherwise every assertion built on `_drive`
    passes on a run where nothing was measured. Paired with a stand-in that does answer, so
    "reports a problem" is not satisfied by a helper that reports one unconditionally.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH, so the answering half of this fixture cannot run")

    out, problem = _drive("this-binary-does-not-exist-144", "hook.sh", tmp_path, {})
    assert problem is not None, "an unspawnable binary was reported as a silent hook"
    assert out == ""

    mute = tmp_path / "mute.sh"
    mute.write_text("cat > /dev/null\n", encoding="utf-8")
    out, problem = _drive(bash, mute, tmp_path, {})
    assert problem is not None, "a hook that printed nothing was reported as an answer"

    # The must-answer half. `{}` is the hook's own way of having nothing to say, so it is
    # deliberately the reply used here: the helper has to call that an answer, or the real
    # test below would skip on every silent-but-successful run and measure nothing.
    speaking = tmp_path / "speaks.sh"
    speaking.write_text("cat > /dev/null; printf '{}'\n", encoding="utf-8")
    out, problem = _drive(bash, speaking, tmp_path, {})
    assert problem is None, problem
    assert out.strip() == "{}"


def test_the_tools_dimension_still_cannot_see_an_agent_call(tmp_path):
    """Driven against the installed hook. Fails the day the feature becomes buildable.

    Three outcomes, and the third is the load-bearing one:

      control fired, Agent silent   the gap is real -- what this repository ships for
      control fired, Agent fired    the dependency now reads an Agent payload: the feature
                                    is unblocked and the recorded reason is stale. FAIL.
      control did not fire          nothing was measured. SKIP, naming what went untested;
                                    never "the gap is confirmed"

    The control is a `Bash` rule in the same fabricated layer, matched by the same `~.*`,
    read out of the same index by the same process. Without it, an empty answer for `Agent`
    is equally consistent with a hook that could not read the layer, could not be spawned,
    or wrote its answer somewhere this test is not looking.
    """
    roots, version = doctor.jit_hook_roots()
    if not roots:
        pytest.skip(
            "the jit-context dependency is not installed here, so whether its tools "
            "dimension can see an Agent call went unmeasured -- the recorded gap stands "
            "on its own word on this runner"
        )
    hooks = [
        root / "scripts" / "pre-tool-hook.sh"
        for root in roots
        if (root / "scripts" / "pre-tool-hook.sh").is_file()
    ]
    if not hooks:
        pytest.skip(
            "the dependency ({}) is installed but ships no pre-tool-hook.sh where the "
            "install record points, so nothing was driven".format(version)
        )
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH, so the PreToolUse hook could not be driven")

    project = tmp_path / "repo"
    project.mkdir()
    _fabricated_layer(project)
    hook = hooks[0]

    control, problem = _drive(
        bash, hook, project, {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}
    )
    if problem is not None or BASH_SENTINEL not in control:
        pytest.skip(
            "the control rule did not fire, so this harness saw nothing and an empty Agent "
            "answer would mean nothing. Untested: whether {} reads an Agent payload. "
            "Problem: {}. Control output: {!r}".format(version, problem, control)
        )

    subject, problem = _drive(
        bash,
        hook,
        project,
        {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "oss:developer",
                "description": "implement one issue",
                "prompt": "Implement one issue.",
            },
        },
    )
    if problem is not None:
        # The control answered and this did not. That is not the gap holding -- it is the
        # one payload this dependency has never been asked to handle failing to produce an
        # answer, which is a different fact and must never be reported as the first one.
        pytest.skip(
            "the control answered but the Agent payload did not, so nothing was measured "
            "about it. Untested: whether {} reads an Agent payload. Problem: {}".format(
                version, problem
            )
        )
    assert AGENT_SENTINEL not in subject, (
        "{} now injects on an Agent dispatch. The feature is unblocked: build the rule, and "
        "delete the gap record from oss_rules.py -- it has become stale prose shipped into "
        "every managed repo.".format(version)
    )

