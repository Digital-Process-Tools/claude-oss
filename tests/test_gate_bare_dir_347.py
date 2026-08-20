"""#347: `GATE_DIR_RE`'s whitespace class crosses a newline, so a bare `--dir` with no
argument lets the bare-token alternative capture the *next* token -- the following
flag, such as `--changelog` -- which then passes directory-name validation and is
accepted as the directory the gate polices.

The issue names the decision explicitly: refusing a captured token that starts with
`-` would be a second rule on top of `changelog_dir_problem`, and PR #345's whole
argument is one value, one rule. So the fix here is structural, not a content rule --
`--dir`'s argument is read from the SAME LINE only, and a `--dir` that carries no
argument at all is its own state, distinct from `absent` (no `--dir` line found) and
from `present-refused-dir` (a value was captured and it does not validate). Nothing
was captured here: there is no value to refuse.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import oss_config  # noqa: E402
import release_version  # noqa: E402


BARE = "present-bare-dir"


def _workflow(tmp_path, body):
    workflow = tmp_path / ".github" / "workflows" / "oss-changelog.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(body, encoding="utf-8")
    return tmp_path


# --- the reproduction from the issue itself -----------------------------------


def test_a_bare_dir_across_a_newline_does_not_capture_the_next_flag(tmp_path):
    """The exact shape #347 reports: `--dir` alone on a line, the next flag on the
    line after it. Before the fix this answered `('present-other-dir', '--changelog')`
    -- the next flag, accepted as a directory name."""
    root = _workflow(
        tmp_path,
        "name: oss changelog\n"
        "jobs:\n"
        "  fragment:\n"
        "    steps:\n"
        "      - run: python3 .oss/assemble_changelog.py --check --dir\n"
        "          --changelog CHANGELOG.md\n",
    )

    state, detail = oss_config.scaffolded_changelog_gate(root)

    assert state == BARE, (
        "a --dir with no argument crossed a newline and was read as {!r} -- the "
        "bare-token alternative captured the following flag as a directory "
        "name".format((state, detail))
    )
    assert detail
    assert "--changelog" not in detail or "no argument" in detail.lower() or (
        "argument" in detail.lower()
    )


def test_a_bare_dir_at_the_very_end_of_the_file_is_also_caught(tmp_path):
    """No trailing newline, no following flag at all -- `Z-anchor` rather than `newline`."""
    root = _workflow(
        tmp_path,
        "name: oss changelog\n"
        "      - run: python3 .oss/assemble_changelog.py --check --dir",
    )

    state, detail = oss_config.scaffolded_changelog_gate(root)

    assert state == BARE
    assert detail


# --- the must-not-fire half, in the same fixture --------------------------------


def test_a_well_formed_single_line_dir_still_parses(tmp_path):
    """Positive control named in the issue: a well-formed workflow must still parse.
    Scaffold always writes `--dir` and its value on the same line, quoted."""
    root = _workflow(
        tmp_path,
        "name: oss changelog\n"
        "jobs:\n"
        "  fragment:\n"
        "    steps:\n"
        "      - run: python3 .oss/assemble_changelog.py --check --dir 'docs/frags' "
        "--changelog CHANGELOG.md\n",
    )

    assert oss_config.scaffolded_changelog_gate(root) == ("present-other-dir", "docs/frags")


def test_a_well_formed_default_dir_still_parses(tmp_path):
    root = _workflow(
        tmp_path,
        "name: oss changelog\n"
        "jobs:\n"
        "  fragment:\n"
        "    steps:\n"
        "      - run: python3 .oss/assemble_changelog.py --check --dir 'changelog.d' "
        "--changelog CHANGELOG.md\n",
    )

    assert oss_config.scaffolded_changelog_gate(root) == ("present", "")


def test_a_gate_with_no_dir_line_at_all_is_unaffected(tmp_path):
    root = _workflow(tmp_path, "name: oss changelog\n")

    assert oss_config.scaffolded_changelog_gate(root) == ("present", "")


def test_multiline_run_block_with_a_well_formed_dir_on_its_own_line_still_parses(tmp_path):
    """Same-line whitespace inside a `run: |` block scalar, no crossing -- must not
    be mistaken for the bare case just because the flag and its value sit on an
    indented line of a multi-line block."""
    root = _workflow(
        tmp_path,
        "name: oss changelog\n"
        "jobs:\n"
        "  fragment:\n"
        "    steps:\n"
        "      - run: |\n"
        "          python3 .oss/assemble_changelog.py --check-links --dir 'docs/frags' "
        "--changelog CHANGELOG.md || status=$?\n",
    )

    assert oss_config.scaffolded_changelog_gate(root) == ("present-other-dir", "docs/frags")


# --- the state is distinct from every other one ---------------------------------


def test_the_bare_state_is_not_any_existing_state():
    assert BARE not in ("present", "present-other-dir", "present-refused-dir", "absent", "unknown")


# --- the resolver: never resolve a path out of a bare --dir ---------------------


def test_the_resolver_returns_no_directory_for_a_bare_dir(tmp_path):
    root = _workflow(
        tmp_path,
        "name: oss changelog\n"
        "jobs:\n"
        "  fragment:\n"
        "    steps:\n"
        "      - run: python3 .oss/assemble_changelog.py --check --dir\n"
        "          --changelog CHANGELOG.md\n",
    )

    directory, problem = release_version._fragment_dir(root, None, {"changelog_dir": None})

    assert directory is None, "resolved {0!r} out of a --dir with no argument".format(
        str(directory)
    )
    assert problem, "a refusal with no reason is a silence"
