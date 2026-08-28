"""`plugin copy` could not see a schema-only skew, because `schemas/` was not compared (#415).

The instance: two copies whose only difference is `schemas/agent-report.schema.json`
were reported as carrying the same bytes, while every agent report written against
the newer one came back `UNVALIDATABLE ... exit 2` from the older one's
`scripts/report_schema.py`. Both statements were true and together they misled.

Three fixtures decide the fix rather than one, and the third is the one that says
whether this is a better check or a louder one:

* bytes differ under `schemas/` and the declared contract numbers differ -- the real
  skew, which must be reported AND must name both numbers;
* bytes differ under `schemas/` and the declared numbers agree -- a comment or a
  description moved. Still a byte skew, and the line must say the numbers agree
  rather than implying a refusal that will not happen;
* the two trees are identical -- the control. Every firing here sits beside it,
  because "no skew detected" is exactly what a check that cannot see anything prints,
  and a fix that always claimed skew would pass the first two on its own.

The last test is the class rather than the instance: a tuple cannot report a
directory it does not contain, so the tuple is now half of a partition over the
tracked tree and this fails when a top-level entry belongs to neither half.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402

COPY = "plugin copy:"
SCHEMA = "schemas/agent-report.schema.json"


@pytest.fixture(autouse=True)
def clean_findings():
    doctor.FINDINGS.clear()
    yield
    doctor.FINDINGS.clear()


def _plugin_tree(root, contract=5, note="the report contract", schema=True):
    """A tree of the shape this check compares.

    Bytes with LF endings, never `write_text`: text mode uses `newline=None` and
    translates to CRLF on Windows, which would hand the code under test a difference
    the fixture did not intend and hide one it did.
    """
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "plugin.json").write_bytes(
        # 9.9.9 is the convention here: a version this repository will not reach, so
        # the release commit that bumps the real one cannot redden this file.
        (json.dumps({"name": "oss", "version": "9.9.9"}) + "\n").encode("utf-8")
    )
    for sub in ("agents", "commands", "skills", "scripts"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "commands" / "doctor.md").write_bytes(b"run the diagnostic\n")
    (root / "skills" / "manager.md").write_bytes(b"the loop\n")
    (root / "agents" / "developer.md").write_bytes(b"one issue\n")
    (root / "scripts" / "report_schema.py").write_bytes(b"# the validator\n")
    if schema:
        (root / "schemas").mkdir(parents=True, exist_ok=True)
        (root / "schemas" / "agent-report.schema.json").write_bytes(
            (
                json.dumps(
                    {"x-schema-version": contract, "description": note, "type": "object"},
                    indent=2,
                )
                + "\n"
            ).encode("utf-8")
        )
    return root


def _copy_line(answered, checkout):
    lines = doctor.plugin_provenance(answered, checkout)
    matched = [(level, message) for level, message in lines if message.startswith(COPY)]
    assert len(matched) == 1, "expected exactly one {!r} line, got {!r}".format(COPY, lines)
    return matched[0]


def test_two_identical_trees_still_report_no_skew(tmp_path):
    """The control. Without it every assertion below passes on `always claim skew`."""
    answered = _plugin_tree(tmp_path / "installed")
    checkout = _plugin_tree(tmp_path / "clone")
    level, message = _copy_line(answered, checkout)
    assert level == "OK", message
    assert "SKEW" not in message
    assert "identical over" in message


def test_a_schema_only_difference_is_reported(tmp_path):
    """The filed instance: nothing differs anywhere else in the tree."""
    answered = _plugin_tree(tmp_path / "installed", contract=4)
    checkout = _plugin_tree(tmp_path / "clone", contract=5)
    level, message = _copy_line(answered, checkout)
    assert level == "WARN", message
    assert "SKEW" in message
    assert SCHEMA in message, message


def test_a_schema_skew_names_both_declared_contract_numbers(tmp_path):
    """"These bytes differ" is weaker than the fact the reader acts on."""
    answered = _plugin_tree(tmp_path / "installed", contract=4)
    checkout = _plugin_tree(tmp_path / "clone", contract=5)
    _, message = _copy_line(answered, checkout)
    assert "contract version 4" in message, message
    assert "declares 5" in message, message
    assert "UNVALIDATABLE" in message, message


def test_bytes_differing_without_the_number_moving_says_the_numbers_agree(tmp_path):
    """The case that decides whether this is a better check or a noisier one.

    A description moved and the contract number did not. The byte skew is real and is
    still reported -- suppressing it would be trading a loud finding for a quiet one,
    and this line's subject is which copy answered. What must NOT happen is the line
    implying a refusal that will not occur. And it must not claim the CONTRACTS agree
    either: the number is a declaration, and #221 is the case of a number that stayed
    still while the contract moved.
    """
    answered = _plugin_tree(tmp_path / "installed", contract=5, note="the report contract")
    checkout = _plugin_tree(tmp_path / "clone", contract=5, note="the agent report contract")
    level, message = _copy_line(answered, checkout)
    assert level == "WARN", message
    assert "SKEW" in message
    assert SCHEMA in message, message
    assert "UNVALIDATABLE" not in message, message
    assert "contract version 5" in message, message
    assert "declare" in message, message


def test_a_copy_shipping_no_schema_says_the_contract_was_not_established(tmp_path):
    """Absent is not `version 0` and not agreement. The third state, on the line."""
    answered = _plugin_tree(tmp_path / "installed", schema=False)
    checkout = _plugin_tree(tmp_path / "clone", contract=5)
    level, message = _copy_line(answered, checkout)
    assert level == "WARN", message
    assert "SKEW" in message
    assert "not established" in message, message
    assert "UNVALIDATABLE" not in message, message


def test_a_sibling_module_of_the_wrong_shape_does_not_take_out_the_run(tmp_path, monkeypatch):
    """`doctor.main` has no outer `except`, and this check runs from it.

    `report_schema.py` is a live file (#416 is editing it as this lands), so
    `contract_version` disappearing has to be a fifth way to have no number rather
    than an `AttributeError` three frames from the VERDICT line -- which is #124's
    shape exactly. The must-fire half sits in the same fixture: with the real module
    in place the number IS read, so this cannot pass by never reading one.
    """
    answered = _plugin_tree(tmp_path / "installed", contract=4)
    checkout = _plugin_tree(tmp_path / "clone", contract=5)

    assert doctor.declared_contract(answered) == (4, None), "the control did not fire"

    class _Hollow(object):
        pass

    monkeypatch.setattr(doctor, "report_schema", _Hollow())
    version, why = doctor.declared_contract(answered)
    assert version is None
    assert "contract_version" in why, why
    level, message = _copy_line(answered, checkout)
    assert level == "WARN", message
    assert "not established" in message, message


# --- the class, not the instance ---------------------------------------------------


def _uncovered(top_level):
    """Top-level names that are neither compared nor documented as not compared."""
    covered = set(doctor.COMPARED_DIRECTORIES)
    covered |= {name.split("/")[0] for name in doctor.COMPARED_FILES}
    covered |= set(doctor.NOT_COMPARED_TOP_LEVEL)
    return {name for name in top_level if name not in covered}


def test_the_partition_helper_fires_and_stays_silent():
    """The positive control for the test below, which asserts an empty set.

    An assertion that nothing is uncovered also passes when the helper can never
    return anything, so both halves are pinned in one place.
    """
    assert _uncovered({"schemas", "scripts", ".claude-plugin"}) == set()
    assert _uncovered({"a-directory-nobody-classified"}) == {"a-directory-nobody-classified"}


def _empty_reasons(mapping):
    """Keys of `mapping` whose reason string is empty or whitespace-only.

    `NOT_COMPARED_TOP_LEVEL` is not a suppression list -- every entry carries a
    reason that is a claim about the file, checked by a human reading the diff. A
    key present with nothing behind it would pass the partition check above while
    saying nothing to the next reader deciding whether the classification still
    holds.
    """
    return {name for name, reason in mapping.items() if not reason.strip()}


def _stale_entries(mapping, top_level):
    """Keys of `mapping` that name a path no longer in the tracked tree.

    A `NOT_COMPARED_TOP_LEVEL` entry is a claim about a file that exists; once the
    file leaves the tree the claim is not merely unneeded, it is about nothing, and
    the entry should have left with it.
    """
    return {name for name in mapping if name not in top_level}


def test_the_reason_and_staleness_helpers_fire_and_stay_silent():
    """The positive control for the two tests below.

    Pairs a must-fire case with a must-not-fire case in the same fixture, since an
    assertion that nothing is empty/stale also passes when the helper can never
    return anything.
    """
    assert _empty_reasons({"a": "a real reason", "b": ""}) == {"b"}
    assert _empty_reasons({"a": "a real reason", "b": "   "}) == {"b"}
    assert _empty_reasons({"a": "a real reason"}) == set()

    assert _stale_entries({"a": "reason"}, {"a", "b"}) == set()
    assert _stale_entries({"a": "reason", "gone": "reason"}, {"a", "b"}) == {"gone"}


def test_every_not_compared_reason_is_non_empty():
    empty = _empty_reasons(doctor.NOT_COMPARED_TOP_LEVEL)
    assert empty == set(), (
        "these NOT_COMPARED_TOP_LEVEL entries carry an empty reason, so the "
        "classification is a bare suppression rather than a checkable claim: "
        "{}".format(sorted(empty))
    )


def test_no_not_compared_entry_names_a_path_that_has_left_the_tree():
    try:
        done = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(
            "git could not be run ({}), so staleness was not checked".format(
                exc.__class__.__name__
            )
        )
    if done.returncode != 0:
        pytest.skip(
            "git ls-files exited {} in {}, so staleness was not checked".format(
                done.returncode, REPO_ROOT
            )
        )
    top_level = {line.split("/")[0] for line in done.stdout.splitlines() if line.strip()}
    assert top_level, "git ls-files returned nothing, so this checked nothing"
    stale = _stale_entries(doctor.NOT_COMPARED_TOP_LEVEL, top_level)
    assert stale == set(), (
        "these NOT_COMPARED_TOP_LEVEL entries name a path no longer in the tracked "
        "tree, so the classification is now about nothing: {}".format(sorted(stale))
    )


def test_every_tracked_top_level_entry_is_compared_or_documented():
    """`schemas/` went uncompared for its whole life because nothing asked this.

    Read off the index rather than the commit, so a directory added and staged is
    caught in the commit that adds it rather than one merge later.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(
            "git could not be run ({}), so the tracked top level was not enumerated and "
            "nothing here was checked".format(exc.__class__.__name__)
        )
    if done.returncode != 0:
        pytest.skip(
            "git ls-files exited {} in {}, so the tracked top level was not enumerated "
            "and nothing here was checked".format(done.returncode, REPO_ROOT)
        )
    top_level = {line.split("/")[0] for line in done.stdout.splitlines() if line.strip()}
    assert top_level, "git ls-files returned nothing, so this checked nothing"
    assert _uncovered(top_level) == set(), (
        "these top-level entries of the plugin tree are neither in "
        "COMPARED_DIRECTORIES/COMPARED_FILES nor in NOT_COMPARED_TOP_LEVEL, so the "
        "plugin-copy comparison cannot say whether it looked at them: {}".format(
            sorted(_uncovered(top_level))
        )
    )
