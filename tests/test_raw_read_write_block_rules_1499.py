"""#1499: two `mode: block` jit-context rules refuse the raw reads and unvalidated
writes that made one developer lane 761k tokens of context.

Measured on lane #1069 (1,132 turns): `sed -n` 105 calls / 277 KB, `cat` 26 / 130 KB,
`grep` 126 / 55 KB of uncapped raw reads, and 120 `python3 - <<EOF` write heredocs
carrying 253 KB of payload past every validator. Both rules first lived in this
repository's own `tools/00-manual/` layer; measured on two claude-remember lanes
(66% and 58% of tool output in raw reads, no rule reaching them), they now ship in
`oss_rules.py`'s `01-oss` layer, and this file reads that rendered layer.

Driven against the real installed hook, both directions, with the must-pass list
carrying the forms a refusal must not reach: a filter after a pipe, a supertool op
that carries a raw form inside its *payload*, a read-only python heredoc.

One blocked form is spelled by concatenation below: the reads rule matches the
chained form at any position, and the paste payload that wrote this file is itself
a Bash call.
"""

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import jit_hook_harness  # noqa: E402

LAYER = REPO_ROOT / ".claude" / "jit-context" / "tools" / "01-oss"
READS_RULE = "raw-file-reads-are-uncapped.md"
WRITES_RULE = "python-heredoc-writes-are-unvalidated.md"
READS_TITLE = "A raw sed/cat/head/tail/grep read has no window cap"
WRITES_TITLE = "A python heredoc or cat > that writes a file skips every validator"
#: What the installed hook prints for a `mode: block` refusal (measured on 0.9.0).
BLOCKED = '"decision":"block"'

MUST_BLOCK_READS = [
    "sed -n 10,40p scripts/x.py",
    "cat scripts/x.py",
    "cd /w &" + "& c" + "at a.py b.py",
    "head -30 f.md",
    "grep -rn foo scripts/",
    "grep -n x f.py | wc -l",
]
MUST_BLOCK_WRITES = [
    "cat > scripts/new.py <<'EOF'\nx = 1\nEOF",
    "python3 - <<'EOF'\nopen('a.json', 'w').write('x')\nEOF",
    "python3 - a b <<'EOF'\np.write_text('x')\nEOF",
]
MUST_PASS = [
    "./supertool 'read:scripts/x.py:10:40'",
    "git log | grep fix",
    "cmd | sed -n 1p",
    "cat f.py | python3 -",
    "cat <<'EOF' | ./supertool 'edit:@-'\nold = 'a'\nEOF",
    "python3 - <<'EOF'\nimport json; print(json.load(open('a.json')))\nEOF",
    "if grep -q x f; then echo y; fi",
    "ls -la",
    "echo hi > /dev/null",
    # A paste payload whose CONTENT documents both raw forms, at line start.
    "./supertool 'paste:@-' <<'EOF'\npath = 'x.md'\ncontent = '''\n"
    "cat > foo <<EOF2\npython3 - <<EOF2\n'''\nEOF",
]


def _rule(name):
    return (LAYER / name).read_text(encoding="utf-8")


def test_both_rules_are_block_mode_and_need_supertool():
    for name in (READS_RULE, WRITES_RULE):
        body = _rule(name)
        head = body.split("---", 2)[1]
        assert "mode: block" in head, name
        assert "requires: supertool" in head, name
        assert "tool: Bash" in head, name


def test_the_tracked_layer_is_what_oss_rules_renders():
    """The checked-in 01-oss copy is `install()`'s output, never hand-edited: a
    drift here is a rule this repo reads that no other repo receives (#577)."""
    import oss_rules  # noqa: E402

    shipped = oss_rules.rules(repo_root=REPO_ROOT)["tools"]
    for name in (READS_RULE, WRITES_RULE):
        assert _rule(name) == shipped[name], name


def test_the_tracked_index_carries_both_rows():
    rows = (LAYER / "00-index.tsv").read_text(encoding="utf-8").splitlines()
    named = {row.split("\t")[2] for row in rows if row.strip()}
    assert READS_RULE in named and WRITES_RULE in named, (
        "rebuild-tsv.sh was not run after writing the rule -- an unindexed rule is inert"
    )


def _driven(tmp_path):
    hook, version, why_not = jit_hook_harness.hook_path()
    if hook is None:
        pytest.skip("{} -- untested: whether the two block rules fire".format(why_not))
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH, so the installed hook could not be driven")
    if shutil.which("supertool") is None:
        pytest.skip(
            "no supertool on PATH: `requires: supertool` degrades both rules to "
            "advisory, so a deny cannot be observed here"
        )
    project = tmp_path / "repo"
    target = project / ".claude" / "jit-context" / "tools" / "01-oss"
    shutil.copytree(LAYER, target)
    return bash, hook, project, version


def _answer(tmp_path, command):
    bash, hook, project, version = _driven(tmp_path)
    answer, problem = jit_hook_harness.drive(
        bash, hook, project, {"tool_name": "Bash", "tool_input": {"command": command}}
    )
    assert problem is None, problem
    return answer, version


@pytest.mark.parametrize("command", MUST_BLOCK_READS)
def test_a_raw_read_at_command_position_is_refused(tmp_path, command):
    answer, version = _answer(tmp_path, command)
    assert BLOCKED in answer and READS_TITLE in answer, (
        "{} did not refuse {!r}. Got: {!r}".format(version, command, answer[:300])
    )


@pytest.mark.parametrize("command", MUST_BLOCK_WRITES)
def test_an_unvalidated_write_is_refused(tmp_path, command):
    answer, version = _answer(tmp_path, command)
    assert BLOCKED in answer and WRITES_TITLE in answer, (
        "{} did not refuse {!r}. Got: {!r}".format(version, command, answer[:300])
    )


@pytest.mark.parametrize("command", MUST_PASS)
def test_a_filter_a_payload_or_a_read_only_heredoc_is_not_refused(tmp_path, command):
    """Must-not-fire controls; without them the deny assertions above are equally
    satisfied by a rule that refuses every Bash call."""
    answer, version = _answer(tmp_path, command)
    assert READS_TITLE not in answer and WRITES_TITLE not in answer, (
        "{} refused {!r} -- a match is too wide. Got: {!r}".format(
            version, command, answer[:300]
        )
    )
