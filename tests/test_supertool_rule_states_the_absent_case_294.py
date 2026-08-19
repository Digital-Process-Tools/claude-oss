"""#294: the rule that refuses the file tools told a reader without supertool nothing.

`supertool-required.md` ships in the `01-oss` tools layer and is **committed into every
repository this plugin scaffolds**. It refuses `Read`, `Edit`, `Write`, `Glob` and `Grep`
and names the op that replaces each. For a reader who has supertool that is the whole
answer. For a reader who does not, every one of those five calls is refused and pointed at
a binary they have never heard of -- total failure, arriving with no statement that a
dependency is missing.

The rule used to close that hole by asserting it away: *"a tree that carries this layer
already carries supertool"*. That sentence is false in exactly the situation the reporter
was in, and it is unfalsifiable from inside the rule -- **a rule is a text file the hook
matches a subject against, and it runs no command**, so it cannot probe for the binary and
fires identically either way. The missing third state is not something the rule can
compute; it is something the rule has to hand to the reader as one command to run.

So the tests here hold two things, and the second is the one CI cannot reach:

  1. the rule states the absent case      asserted against the constant, on every runner
  2. it refuses what it means to refuse   driven against the installed hook, with controls

(2) skips where `claude-jit-context` is not installed, which is every CI leg -- a runner
installs no plugin. It names what went untested rather than reporting the rule as verified.

Python 3.9 compatible.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import jit_hook_harness  # noqa: E402
import oss_rules  # noqa: E402

RULE = "supertool-required.md"

#: The one command the rule hands the reader so they can tell the two situations apart.
#: The rule cannot run it; that is the point. Written once here rather than spelled into
#: each assertion, so a change to the command is one edit and not a hunt.
DISCRIMINATOR = "supertool 'ops'"

#: The claim #294 retracts. Kept as an anchor so re-adding it goes red rather than quiet:
#: it renders as reassurance and is false for the only reader who needs this rule to speak.
RETRACTED = "already carries"

#: Every op the rule has to keep naming. The positive control for the assertions above:
#: "the rule now mentions a missing dependency" is equally satisfied by a body that was
#: gutted down to that one paragraph, and a reader who *does* have supertool would then be
#: refused with no replacement named.
OPS = ("read:", "edit:", "paste:", "glob:", "grep:")


def _body():
    body = oss_rules.RULES["tools"].get(RULE)
    assert body, "the tools layer ships no {}".format(RULE)
    return body


# --- 1. the rule states the absent case -------------------------------------------------


def test_the_rule_no_longer_asserts_that_the_binary_must_be_present():
    body = _body()
    assert RETRACTED not in body, (
        "the rule still claims a tree carrying this layer already carries supertool. "
        "The layer is committed and travels to every clone, so its presence is evidence "
        "about a repository and none at all about the machine reading it (#294)."
    )


def test_the_rule_hands_the_reader_a_command_that_tells_the_two_situations_apart():
    body = _body()
    assert DISCRIMINATOR in body, (
        "the rule names no command a reader can run to find out whether supertool is "
        "installed. It fires identically whether it is or not and cannot probe, so the "
        "discriminator has to be handed to the reader (#294)."
    )
    assert "not installed" in body, (
        "the rule never says in as many words that supertool may simply not be here"
    )
    assert "install" in body, (
        "the rule names no route to getting supertool, for a reader who has never heard "
        "of it"
    )


def test_the_rule_still_names_the_op_that_replaces_every_refused_call():
    """The must-still-work half of the fixture above.

    Without this, every assertion in this section is satisfied by a rule reduced to a
    paragraph about a missing dependency -- which is a worse rule for the reader who has
    the dependency, and that reader is the majority.
    """
    body = _body()
    missing = [op for op in OPS if op not in body]
    assert not missing, "the rule stopped naming {}".format(missing)


def test_the_rule_still_blocks_rather_than_reminding():
    """A `remind` here is the quiet failure traded for the loud one.

    The refusal is what makes the reader read the replacement. Downgrading it to make
    #294's reader unblocked would let a call through that the whole layer exists to route.
    """
    assert oss_rules._field(_body(), "mode") == "block"


# --- 2. it refuses what it means to refuse, and nothing else ----------------------------
#
# #294 carries a finding from upstream: supertool's own equivalent rule uses `match: ~.`,
# which matches every string, so a mutation shipping it denies a plain `make test` in a
# foreign repository. This plugin's pattern is `~.*` -- the same shape -- and the question
# is whether the `tool:` column scopes it. Measured here rather than reasoned, in both
# directions in one fixture.


def _installed_layer(tmp_path):
    project = tmp_path / "repo"
    project.mkdir()
    oss_rules.install(project)
    return project


def test_the_rule_fires_on_a_file_tool_and_not_on_an_unrelated_call(tmp_path):
    """Both directions, one fixture, against the real layer this plugin installs.

    The `Read` half is the must-fire: without it, "a Bash command is not denied" is
    equally satisfied by a hook that answered nothing to anything. The `Bash` and
    `TodoWrite` halves are the must-not-fire that #294's upstream finding asks for.
    """
    hook, version, why_not = jit_hook_harness.hook_path()
    if hook is None:
        pytest.skip(
            "{} -- untested: whether {} is scoped by its tool: column or denies every "
            "call".format(why_not, RULE)
        )
    import shutil

    bash = shutil.which("bash")
    project = _installed_layer(tmp_path)

    refused, problem = jit_hook_harness.drive(
        bash, hook, project, {"tool_name": "Read", "tool_input": {"file_path": "a.py"}}
    )
    if problem is not None:
        pytest.skip(
            "the hook did not answer the must-fire half, so this harness saw nothing "
            "and an unrefused Bash call would mean nothing. Untested: whether {} is "
            "scoped by its tool: column. Problem: {}".format(RULE, problem)
        )
    assert RULE in refused, (
        "the rule this plugin installs did not refuse a native Read against {}. The "
        "hook answered ({!r}), so it was reached and did not match.".format(
            version, refused[:200]
        )
    )

    for tool, tool_input in (
        ("Bash", {"command": "make test"}),
        ("TodoWrite", {"todos": []}),
    ):
        answer, problem = jit_hook_harness.drive(
            bash, hook, project, {"tool_name": tool, "tool_input": tool_input}
        )
        assert problem is None, problem
        assert RULE not in answer, (
            "{} refused a {} call. `match: ~.*` matches every subject, so the tool: "
            "column is the only thing scoping it -- if that stops holding, this rule "
            "denies a plain `make test` in every repository it was ever installed "
            "into (#294).".format(RULE, tool)
        )


def test_the_refusal_a_reader_receives_carries_the_discriminator(tmp_path):
    """The rule's text is only worth anything if it survives into the refusal.

    Asserted against what the hook emits rather than against the constant: the two are
    different artifacts, and the reader in #294 only ever sees the second one.
    """
    hook, version, why_not = jit_hook_harness.hook_path()
    if hook is None:
        pytest.skip(
            "{} -- untested: whether the refusal a reader receives names the missing "
            "dependency".format(why_not)
        )
    import shutil

    bash = shutil.which("bash")
    project = _installed_layer(tmp_path)
    refused, problem = jit_hook_harness.drive(
        bash, hook, project, {"tool_name": "Read", "tool_input": {"file_path": "a.py"}}
    )
    if problem is not None:
        pytest.skip("the hook did not answer, so nothing was measured: {}".format(problem))
    assert RULE in refused, "the rule did not fire at all against {}".format(version)
    assert DISCRIMINATOR in refused, (
        "the refusal delivered to the reader does not carry the command that tells them "
        "whether supertool is installed. Whatever the rule file says, this is the only "
        "text they see (#294). Got: {!r}".format(refused[:400])
    )
