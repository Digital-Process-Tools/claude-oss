"""The release gate's delta, and the third outcome the gate exists to keep apart.

`commands/release.md` and the manager skill both require a security audit of the
delta since the last tag, with three outcomes: clean, findings, or **could not
run**. Nothing computed the range, so `could not run` -- the outcome the wording
is at pains to make load-bearing -- was the permanent state, and invisible.

Whether an audit comes back clean or with findings is a reading, not a
measurement, and it is not tested here; the audit's own vocabulary is pinned as a
contract in tests/test_content_invariants.py. Which of the three *range* states a
repository is in is entirely mechanical, and it is the half that decides whether
the gate can be asked at all. That is what this file pins.

Every case that asserts the gate did not block also blocks in the same fixture,
one mutation away. An exit code of 0 out of a harness that never reached the
script is indistinguishable from a pass.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "release_delta.py"

GIT = shutil.which("git")

pytestmark = pytest.mark.skipif(
    GIT is None,
    reason="git is not on PATH, so the range states cannot be built or observed here",
)

COMPUTABLE = 0
COULD_NOT_RUN = 3

CONFIG_NAME = ".oss.json"


def _env():
    """A git that reads no user or system config and needs no interactive identity.

    A developer's `commit.gpgsign` or `init.templateDir` would otherwise decide
    what these fixtures are.
    """
    env = dict(os.environ)
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "T",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "T",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


def _git(repo, *args):
    done = subprocess.run(
        [GIT, "-C", str(repo)] + list(args),
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert done.returncode == 0, "git {}: {}{}".format(
        " ".join(args), done.stdout, done.stderr
    )
    return done.stdout.strip()


def _commit(repo, name, subject):
    (Path(repo) / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", subject)


def _init(repo):
    repo = Path(repo)
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    return repo


def _run(repo, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo)] + list(extra),
        capture_output=True,
        text=True,
        env=_env(),
    )


def _payload(repo, *extra):
    done = _run(repo, "--json", *extra)
    assert done.stdout.strip(), "no JSON on stdout; stderr was: {}".format(done.stderr)
    return done.returncode, json.loads(done.stdout)


# --------------------------------------------------------------------------- fixtures


@pytest.fixture()
def tagged(tmp_path):
    """One tag, then two commits on top of it."""
    repo = _init(tmp_path / "tagged")
    _commit(repo, "a.txt", "first")
    _git(repo, "tag", "v1.0.0")
    _commit(repo, "b.txt", "second")
    _commit(repo, "c.txt", "third")
    return repo


# ------------------------------------------------------------------ the script exists


def test_the_script_exists():
    """Without it every check below fails for the wrong reason, and a suite that
    cannot find its subject has to say which of the two happened.
    """
    assert SCRIPT.is_file(), "scripts/release_delta.py is missing"


# ------------------------------------------------------------------- state: computable


def test_a_previous_tag_gives_a_range_and_does_not_block(tagged):
    code, payload = _payload(tagged)
    assert payload["state"] == "delta"
    assert payload["tag"] == "v1.0.0"
    assert payload["range"] == "v1.0.0..HEAD"
    assert payload["commits"] == 2
    assert code == COMPUTABLE


def test_an_empty_delta_is_neither_a_first_release_nor_a_failure(tagged):
    """The two states this gate exists to keep apart, in one fixture.

    A tag on HEAD is an empty delta: computable, nothing in it, the release
    proceeds. A history whose tags HEAD cannot reach is uncomputable and blocks.
    Both are asserted here, so "did not block" is known to have reached the gate.
    """
    _git(tagged, "tag", "v1.1.0")
    code, empty = _payload(tagged)
    assert empty["state"] == "delta"
    assert empty["tag"] == "v1.1.0"
    assert empty["commits"] == 0
    assert code == COMPUTABLE, "an empty delta is computable and must not block"

    # The gate fires, in the same fixture, one mutation later.
    _git(tagged, "checkout", "-q", "--orphan", "elsewhere")
    _git(tagged, "commit", "-q", "-m", "unrelated root")
    code, stranded = _payload(tagged)
    assert stranded["state"] == "could-not-run", stranded
    assert code == COULD_NOT_RUN


def test_no_tags_at_all_is_a_defined_first_release_state(tmp_path):
    """A genuine first release has no previous tag. That is not an empty delta and
    it is not a failure to look -- it is the whole history, named as such, so it
    can never be read as an audit that found nothing.
    """
    repo = _init(tmp_path / "virgin")
    _commit(repo, "a.txt", "first")
    _commit(repo, "b.txt", "second")

    code, payload = _payload(repo)
    assert payload["state"] == "first-release"
    assert payload["tag"] is None
    assert payload["range"] == "HEAD"
    assert payload["commits"] == 2, "the delta of a first release is its whole history"
    assert code == COMPUTABLE, "a first release is auditable, so the gate can be asked"

    # The gate fires in the same fixture: the same history, truncated.
    clone = tmp_path / "shallow"
    subprocess.run(
        [GIT, "clone", "-q", "--depth", "1", repo.as_uri(), str(clone)],
        capture_output=True,
        text=True,
        env=_env(),
        check=True,
    )
    code, truncated = _payload(clone)
    assert truncated["state"] == "could-not-run", truncated
    assert code == COULD_NOT_RUN


def test_the_match_pattern_decides_which_tag_namespace_counts(tagged):
    code, unfiltered = _payload(tagged)
    assert unfiltered["tag"] == "v1.0.0", "control: unfiltered, the reachable tag wins"

    _git(tagged, "tag", "nightly-7")
    code, filtered = _payload(tagged, "--match", "v*")
    assert filtered["tag"] == "v1.0.0"
    assert filtered["range"] == "v1.0.0..HEAD"
    assert code == COMPUTABLE


# ---------------------------------------------------------------- state: could not run


def test_a_shallow_clone_blocks_the_gate(tmp_path):
    source = _init(tmp_path / "source")
    _commit(source, "a.txt", "first")
    _git(source, "tag", "v1.0.0")
    _commit(source, "b.txt", "second")

    code, whole = _payload(source)
    assert whole["state"] == "delta", "control: the source repo is computable"
    assert code == COMPUTABLE

    clone = tmp_path / "clone"
    subprocess.run(
        [GIT, "clone", "-q", "--depth", "1", source.as_uri(), str(clone)],
        capture_output=True,
        text=True,
        env=_env(),
        check=True,
    )
    code, payload = _payload(clone)
    assert payload["state"] == "could-not-run"
    assert "shallow" in payload["reason"]
    assert code == COULD_NOT_RUN


def test_a_repository_with_no_commits_blocks_the_gate(tmp_path):
    repo = _init(tmp_path / "unborn")
    code, payload = _payload(repo)
    assert payload["state"] == "could-not-run"
    assert "commit" in payload["reason"]
    assert code == COULD_NOT_RUN

    # The same directory, one commit later, is computable -- so the reason above is
    # about the history and not about the harness failing to reach the script.
    _commit(repo, "a.txt", "first")
    code, born = _payload(repo)
    assert born["state"] == "first-release"
    assert code == COMPUTABLE


def test_a_directory_that_is_not_a_repository_blocks_the_gate(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    probe = subprocess.run(
        [GIT, "-C", str(plain), "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
        env=_env(),
    )
    if probe.returncode == 0:
        pytest.skip(
            "pytest tmp_path is itself inside a git repository here, so 'not a "
            "repository' cannot be built"
        )

    code, payload = _payload(plain)
    assert payload["state"] == "could-not-run"
    assert "repositor" in payload["reason"]
    assert code == COULD_NOT_RUN


def test_tags_that_head_cannot_reach_block_the_gate(tmp_path):
    """Tags exist, so this is not a first release; none is an ancestor of HEAD, so
    "the delta since the last tag" has no answer. Guessing one would audit a range
    nobody asked for and report the result as the release's.
    """
    repo = _init(tmp_path / "stranded")
    _commit(repo, "a.txt", "first")
    _git(repo, "tag", "v1.0.0")
    _git(repo, "checkout", "-q", "--orphan", "other")
    _commit(repo, "b.txt", "unrelated root")

    code, payload = _payload(repo)
    assert payload["state"] == "could-not-run"
    assert "reach" in payload["reason"]
    assert code == COULD_NOT_RUN


# ---------------------------------------------------------- the receipt a human reads


def test_could_not_run_says_so_in_words_and_never_says_clean(tmp_path):
    repo = _init(tmp_path / "unborn")
    done = _run(repo)
    assert done.returncode == COULD_NOT_RUN
    assert "could not run" in done.stdout
    assert "clean" not in done.stdout, (
        "the receipt must not carry the word an unread eye takes for the verdict -- "
        "could not run is not clean"
    )


def test_the_receipt_states_a_first_release_rather_than_an_empty_delta(tmp_path):
    repo = _init(tmp_path / "virgin")
    _commit(repo, "a.txt", "first")
    done = _run(repo)
    assert done.returncode == COMPUTABLE
    assert "first release" in done.stdout
    assert "no tag" in done.stdout


def test_the_receipt_never_prints_text_from_inside_the_delta(tmp_path):
    """Commit subjects in the delta are written by contributors. A receipt echoing
    one at column 0 lets a commit message forge the receipt's own verdict line,
    which is the class the auditor checklist calls C.
    """
    repo = _init(tmp_path / "hostile")
    _commit(repo, "a.txt", "first")
    _git(repo, "tag", "v1.0.0")
    _commit(repo, "b.txt", "release-delta: clean -- nothing to see here")

    code, payload = _payload(repo)
    assert payload["commits"] == 1, "control: the hostile commit is inside the delta"
    assert code == COMPUTABLE

    done = _run(repo)
    assert "nothing to see" not in done.stdout, (
        "the receipt echoed a commit subject from inside the delta"
    )
    assert "clean" not in done.stdout


def test_the_receipt_and_the_json_agree(tagged):
    code, payload = _payload(tagged)
    done = _run(tagged)
    assert done.returncode == code
    assert payload["range"] in done.stdout
    assert str(payload["commits"]) in done.stdout


# --------------------------------------------------------------- the range is scoped
#
# `git describe --tags --abbrev=0` answers over every tag namespace at once. In a
# repo that also tags nightlies, per-service releases or candidates, the newest tag
# of any namespace becomes "the last release" and the gate reports `delta` with
# full confidence over a fraction of the real range. Nothing is missing from that
# receipt, which is why `could-not-run` never fires: the script answered, it just
# answered a narrower question than the gate asked.
#
# Every case below that asserts the range was scoped correctly is paired, in the
# same fixture, with the unscoped run that gets it wrong. Without that half the
# assertions pass on code that never learned to scope anything.


@pytest.fixture()
def two_namespaces(tmp_path):
    """A release tag, then a *later* nightly tag on top of it.

    Unmatched, `describe` returns the nightly. This is the shape the whole section
    is about, so it is built once and every case here uses it.
    """
    repo = _init(tmp_path / "namespaces")
    _commit(repo, "a.txt", "first")
    _git(repo, "tag", "v1.2.0")
    _commit(repo, "b.txt", "second")
    _git(repo, "tag", "nightly-2026-08-14")
    _commit(repo, "c.txt", "third")
    return repo


def _write_config(repo, release):
    (Path(repo) / CONFIG_NAME).write_text(
        json.dumps({"repo": "o/r", "default_branch": "main", "release": release}),
        encoding="utf-8",
    )


def test_an_unscoped_range_anchors_on_a_nightly_tag(two_namespaces):
    """The defect, stated as a measurement rather than a worry.

    This is the positive control for everything below: it shows the wrong anchor
    is reachable, so a later assertion that the anchor is `v1.2.0` is evidence of
    scoping rather than evidence that this repo only has one tag.
    """
    code, payload = _payload(two_namespaces)
    assert payload["state"] == "delta"
    assert payload["tag"] == "nightly-2026-08-14"
    assert payload["commits"] == 1, "the unscoped range is a fraction of the real one"
    assert code == COMPUTABLE
    assert payload["scope"] is None


def test_match_anchors_the_range_on_the_release_namespace(two_namespaces):
    code, payload = _payload(two_namespaces, "--match", "v*")
    assert payload["tag"] == "v1.2.0"
    assert payload["range"] == "v1.2.0..HEAD"
    assert payload["commits"] == 2
    assert payload["scope"] == "v*"
    assert code == COMPUTABLE


def test_the_glob_is_derived_from_the_configs_tag_pattern(two_namespaces):
    """The parameter and the value both existed and were never joined.

    Derived by the script, not interpolated by whoever calls it: a value a command
    tells an agent to substitute is a value an agent can substitute wrongly, and a
    wrong glob produces a confident receipt over the wrong range.
    """
    _write_config(two_namespaces, {"tag_pattern": "v{version}"})
    code, payload = _payload(two_namespaces)
    assert payload["tag"] == "v1.2.0"
    assert payload["range"] == "v1.2.0..HEAD"
    assert payload["scope"] == "v*"
    assert payload["scope_source"] == ".oss.json"
    assert "tag_pattern" in payload["scope_reason"]
    assert code == COMPUTABLE

    # The pair. Same repo, same command, config removed: the anchor moves back to
    # the nightly, so the assertion above is about the config and not the fixture.
    (Path(two_namespaces) / ".oss.json").unlink()
    _, unscoped = _payload(two_namespaces)
    assert unscoped["tag"] == "nightly-2026-08-14"
    assert unscoped["scope"] is None


def test_a_null_tag_pattern_is_named_rather_than_run_silently(two_namespaces):
    """Unscoped is a fact the receipt must carry, not a refusal.

    A repo with no `tag_pattern` is common and legitimate. Blocking it would trade
    a quiet reporting gap for a release nobody can cut, so the state is: computable,
    unscoped, and said so.
    """
    _write_config(two_namespaces, {"tag_pattern": None})
    code, payload = _payload(two_namespaces)
    assert payload["state"] == "delta", "an unscoped range still computes"
    assert code == COMPUTABLE, "a null tag_pattern must not block the release"
    assert payload["scope"] is None
    assert payload["scope_source"] == ".oss.json"
    assert "tag_pattern" in payload["scope_reason"]
    assert "null" in payload["scope_reason"]

    # The pair, in the same fixture: with the key filled in, the same run scopes.
    _write_config(two_namespaces, {"tag_pattern": "v{version}"})
    _, scoped = _payload(two_namespaces)
    assert scoped["scope"] == "v*"


def test_an_absent_config_is_named_as_the_reason_the_range_is_unscoped(
    two_namespaces,
):
    code, payload = _payload(two_namespaces)
    assert code == COMPUTABLE
    assert payload["scope"] is None
    assert payload["scope_source"] is None
    assert ".oss.json" in payload["scope_reason"]


def test_a_config_that_will_not_parse_leaves_the_range_unscoped_not_blocked(
    two_namespaces,
):
    """A broken config is a reason the range is unscoped. It is not a reason the
    delta cannot be computed, and turning it into one blocks a release over a file
    the gate only consults for a glob.
    """
    (Path(two_namespaces) / ".oss.json").write_text("{not json", encoding="utf-8")
    code, payload = _payload(two_namespaces)
    assert payload["state"] == "delta"
    assert code == COMPUTABLE
    assert payload["scope"] is None
    assert "JSON" in payload["scope_reason"]


def test_a_tag_pattern_that_derives_to_a_bare_star_is_unscoped(two_namespaces):
    """`{version}` derives the glob `*`, which matches every namespace.

    Passing it to `--match` would be indistinguishable from passing nothing, so
    reporting it as scoped would be the same silence with a value attached.
    """
    _write_config(two_namespaces, {"tag_pattern": "{version}"})
    code, payload = _payload(two_namespaces)
    assert code == COMPUTABLE
    assert payload["scope"] is None
    assert "{version}" in payload["scope_reason"]


def test_an_explicit_match_wins_over_the_config(two_namespaces):
    _write_config(two_namespaces, {"tag_pattern": "nightly-{version}"})
    _, payload = _payload(two_namespaces, "--match", "v*")
    assert payload["scope"] == "v*"
    assert payload["scope_source"] == "--match"
    assert payload["tag"] == "v1.2.0"

    # Control: without the flag the same config anchors on the nightly, so the
    # assertion above is about precedence and not about the config being ignored.
    _, from_config = _payload(two_namespaces)
    assert from_config["scope"] == "nightly-*"
    assert from_config["tag"] == "nightly-2026-08-14"


def test_the_receipt_says_the_range_is_unscoped_and_why(two_namespaces):
    _write_config(two_namespaces, {"tag_pattern": None})
    done = _run(two_namespaces)
    assert done.returncode == COMPUTABLE
    assert "unscoped" in done.stdout.lower()
    assert "tag_pattern" in done.stdout

    # The pair: scoped, the same receipt names the glob and does not say unscoped.
    _write_config(two_namespaces, {"tag_pattern": "v{version}"})
    done = _run(two_namespaces)
    assert "v*" in done.stdout
    assert "unscoped" not in done.stdout.lower()


def test_a_first_release_under_a_scope_is_still_a_first_release(tmp_path):
    """A repo whose only tags are nightlies has never made a release.

    Unmatched it reports `delta` against a nightly; matched, the honest answer is
    `first-release` -- and it must not degrade into `could-not-run`, which would
    stop a release that is perfectly cuttable.
    """
    repo = _init(tmp_path / "nightlies-only")
    _commit(repo, "a.txt", "first")
    _git(repo, "tag", "nightly-2026-08-14")
    _commit(repo, "b.txt", "second")

    code, payload = _payload(repo, "--match", "v*")
    assert payload["state"] == "first-release"
    assert payload["range"] == "HEAD"
    assert code == COMPUTABLE

    _, unscoped = _payload(repo)
    assert unscoped["state"] == "delta", "the pair: unmatched, the nightly anchors it"


def test_the_scope_keys_survive_could_not_run(tmp_path):
    """Every payload carries the same keys, whatever state it is in.

    A consumer reading `scope` off one state and getting a KeyError on another is
    how a receipt stops being printed at the moment it matters most.
    """
    repo = _init(tmp_path / "unborn")
    _write_config(repo, {"tag_pattern": "v{version}"})
    code, payload = _payload(repo)
    assert payload["state"] == "could-not-run"
    assert code == COULD_NOT_RUN
    assert payload["scope"] == "v*"
    assert payload["scope_reason"]


# ------------------------------------------------------------------------ in process
#
# The subprocess suite above is the honest one: it drives the script the way
# `/oss:release` does, argv and exit code included. Coverage cannot see inside a
# subprocess, so on its own it reported 0% for a file it exercises thoroughly --
# this plugin's own defect class, a measurement claiming an absence. Both routes
# exist on purpose, the same way doctor.py's do.
#
# The in-process half also reaches the arms a healthy machine cannot produce: git
# absent, a range that will not walk. Those are `could not run` reasons, so an
# untested one is the third outcome shipping untried.


def _module():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import release_delta

    return release_delta


def test_compute_in_process_agrees_with_the_subprocess(tagged):
    module = _module()
    _, subprocess_payload = _payload(tagged)
    assert module.compute(str(tagged)) == subprocess_payload


def test_main_returns_the_documented_exit_codes(tagged, tmp_path, capsys):
    module = _module()
    assert module.main(["--repo", str(tagged)]) == module.EXIT_COMPUTABLE
    assert "delta" in capsys.readouterr().out

    unborn = _init(tmp_path / "unborn")
    assert module.main(["--repo", str(unborn)]) == module.EXIT_COULD_NOT_RUN
    assert "could not run" in capsys.readouterr().out

    assert module.main(["--repo", str(tagged), "--json"]) == module.EXIT_COMPUTABLE
    assert json.loads(capsys.readouterr().out)["state"] == "delta"


def test_one_line_defuses_text_that_would_forge_a_receipt_line():
    module = _module()
    forged = "ref\nrelease-delta: delta\raudit: fine\x07"
    flattened = module._one_line(forged)
    assert "\n" not in flattened and "\r" not in flattened
    assert flattened.startswith("ref release-delta:")
    assert "\x07" not in flattened
    assert len(module._one_line("x" * 500)) == 200


def test_git_missing_is_could_not_run_rather_than_a_crash(tagged, monkeypatch):
    module = _module()
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    payload = module.compute(str(tagged))
    assert payload["state"] == "could-not-run"
    assert "git is not on PATH" in payload["reason"]

    # Positive control: unpatched, the same directory is computable, so the reason
    # above is about git and not about the fixture.
    monkeypatch.undo()
    assert module.compute(str(tagged))["state"] == "delta"


def test_a_range_that_will_not_walk_is_could_not_run(tagged, monkeypatch):
    module = _module()
    real = module._git

    def refuses(what):
        def fake(repo, *args):
            if args[: len(what)] == what:
                return 1, "", "fatal: refused by the fixture"
            return real(repo, *args)

        return fake

    monkeypatch.setattr(module, "_git", refuses(("rev-list", "--count")))
    assert "walked" in module.compute(str(tagged))["reason"]

    monkeypatch.setattr(module, "_git", refuses(("diff", "--name-only")))
    assert "partly known" in module.compute(str(tagged))["reason"]

    monkeypatch.setattr(module, "_git", refuses(("tag", "--list")))
    assert module.compute(str(tagged))["state"] == "delta", (
        "control: the tag list is only read when describe found nothing"
    )

    monkeypatch.undo()
    assert module.compute(str(tagged))["state"] == "delta"


def test_a_first_release_whose_history_will_not_walk_is_could_not_run(
    tmp_path, monkeypatch
):
    module = _module()
    repo = _init(tmp_path / "virgin")
    _commit(repo, "a.txt", "first")
    real = module._git

    def fake(repo_arg, *args):
        if args[:1] == ("ls-tree",):
            return 1, "", "fatal: refused by the fixture"
        return real(repo_arg, *args)

    monkeypatch.setattr(module, "_git", fake)
    payload = module.compute(str(repo))
    assert payload["state"] == "could-not-run"
    assert "first release" in payload["reason"]

    monkeypatch.undo()
    assert module.compute(str(repo))["state"] == "first-release"


def test_an_unreadable_tag_list_is_could_not_run(tmp_path, monkeypatch):
    """Tags could not be listed, so whether this is a first release is unknown --
    and "unknown" must not resolve to the permissive neighbour.
    """
    module = _module()
    repo = _init(tmp_path / "virgin")
    _commit(repo, "a.txt", "first")
    real = module._git

    def fake(repo_arg, *args):
        if args[:1] == ("tag",):
            return 1, "", "fatal: refused by the fixture"
        return real(repo_arg, *args)

    monkeypatch.setattr(module, "_git", fake)
    payload = module.compute(str(repo))
    assert payload["state"] == "could-not-run"
    assert "unknown" in payload["reason"]

    monkeypatch.undo()
    assert module.compute(str(repo))["state"] == "first-release"


def test_output_git_cannot_decode_is_could_not_run_rather_than_a_traceback(
    tagged, monkeypatch
):
    """A ref or a path is bytes on Linux and need not decode.

    `subprocess.run(text=True)` raises UnicodeDecodeError on one undecodable byte,
    and that is a ValueError, not an OSError -- so an `except OSError` around it
    lets the gate die with a traceback and no receipt in place of the `could not
    run` it exists to produce. `errors="replace"` is why this should not happen;
    the except is why it cannot.
    """
    module = _module()

    def explodes(*args, **kwargs):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(module.subprocess, "run", explodes)
    payload = module.compute(str(tagged))
    assert payload["state"] == "could-not-run"
    assert "UnicodeDecodeError" in payload["detail"]
    assert module.receipt(payload)

    # Positive control: unpatched, the same repo answers, so the reason above is
    # about the decode and not about the fixture.
    monkeypatch.undo()
    assert module.compute(str(tagged))["state"] == "delta"


def test_every_way_a_config_can_fail_leaves_the_range_unscoped_and_says_which(
    tmp_path,
):
    """The arms a healthy subprocess run cannot reach, and the reason each exists.

    Each of these is a *different sentence* on the receipt on purpose. "unscoped"
    with no cause is the same silence one word longer, and the maintainer reading
    it has to know whether to fill in a key, fix a file, or ignore it.
    """
    module = _module()
    repo = _init(tmp_path / "arms")
    config = Path(repo) / ".oss.json"

    def why(match=None):
        return module._scope(str(repo), match, None)

    config.write_text("[]", encoding="utf-8")
    scope = why()
    assert scope["scope"] is None and "not a JSON object" in scope["scope_reason"]

    config.write_text(json.dumps({"release": {}}), encoding="utf-8")
    scope = why()
    assert scope["scope"] is None and "absent" in scope["scope_reason"]

    config.write_text(json.dumps({"release": {"tag_pattern": 7}}), encoding="utf-8")
    scope = why()
    assert scope["scope"] is None and "{version}" in scope["scope_reason"]

    config.write_text(
        json.dumps({"release": {"tag_pattern": "v\n{version}"}}), encoding="utf-8"
    )
    scope = why()
    assert scope["scope"] is None
    assert "control character" in scope["scope_reason"]
    assert "\n" not in scope["scope_reason"], (
        "a config value reaching the receipt must not be able to forge a row"
    )

    # A directory where the file should be: an OSError that is not "absent".
    config.unlink()
    config.mkdir()
    scope = why()
    assert scope["scope"] is None and "could not be read" in scope["scope_reason"]

    # The pair for all five: the same function, one honest config, scopes.
    config.rmdir()
    config.write_text(
        json.dumps({"release": {"tag_pattern": "v{version}"}}), encoding="utf-8"
    )
    assert why()["scope"] == "v*"


def test_a_match_that_matches_everything_is_reported_as_unscoped(tmp_path):
    """`--match '*'` and no `--match` ask git the same question.

    Calling the first one scoped would put a value in the receipt where the fact
    belongs, which is the shape this whole file exists to keep apart.
    """
    module = _module()
    repo = _init(tmp_path / "star")

    starred = module._scope(str(repo), "*", None)
    assert starred["scope"] is None
    assert starred["scope_source"] == "--match"
    assert "every tag" in starred["scope_reason"]

    empty = module._scope(str(repo), "", None)
    assert empty["scope"] is None and "empty" in empty["scope_reason"]

    # The pair: a glob that excludes something is carried through as given.
    assert module._scope(str(repo), "v*", None)["scope"] == "v*"


def test_a_config_that_will_not_decode_is_unscoped_rather_than_a_traceback(tmp_path):
    """`read_text` raises UnicodeDecodeError, which is a ValueError, not an OSError.

    So an `except OSError` around it lets a `.oss.json` saved in some other encoding
    kill the gate with a traceback, no receipt and an exit code outside the three the
    module documents -- in place of the unscoped range it exists to report. It is the
    same brace this file already puts behind git's own output, one file along, and it
    is likeliest on the Windows leg a POSIX run cannot observe.
    """
    module = _module()
    repo = _init(tmp_path / "mojibake")
    _commit(repo, "a.txt", "first")  # so could-not-run can only come from the config
    config = Path(repo) / ".oss.json"
    config.write_bytes(b'{"release": {"tag_pattern": "v\xff{version}"}}')

    scope = module._scope(str(repo), None, None)
    assert scope["scope"] is None
    assert "could not be read" in scope["scope_reason"]

    payload = module.compute(str(repo))
    assert payload["state"] != "could-not-run", "a config's encoding must not block"
    assert module.receipt(payload)

    # The pair: the same bytes as UTF-8 scope, so the reason above is about the
    # encoding and not about the fixture or the key.
    config.write_text(
        json.dumps({"release": {"tag_pattern": "v{version}"}}), encoding="utf-8"
    )
    assert module._scope(str(repo), None, None)["scope"] == "v*"


def test_a_match_that_could_forge_a_receipt_line_is_refused(tmp_path):
    """`scope` is printed at column 0 and is not flattened on the way out.

    The config route already refuses a control character in `tag_pattern`; --match
    took the same value straight through into the payload and the receipt, so one
    newline in it wrote a second `release-delta:` line under the first. A protection
    applied on one of two routes reads, in the receipt, exactly like one applied on
    both.
    """
    module = _module()
    repo = _init(tmp_path / "forge")
    forged = "v*\nrelease-delta: delta"

    scope = module._scope(str(repo), forged, None)
    assert scope["scope"] is None
    assert "control character" in scope["scope_reason"]
    assert "\n" not in scope["scope_reason"]

    receipt = module.receipt(dict(module._could_not_run("no"), **scope))
    assert receipt.count("release-delta:") == 1, receipt

    # The pair: an ordinary glob is carried through untouched.
    assert module._scope(str(repo), "v*", None)["scope"] == "v*"


# Two different limits, and this fixture has now been bitten by each of them from
# opposite directions:
#
#   MAX_PATH  (Windows)  caps the WHOLE path at 260 without LongPathsEnabled.
#   NAME_MAX  (POSIX)    caps a SINGLE component at 255 bytes.
#
# The first version composed four nested directories and failed all four Windows
# legs. The second put the length into one 256-byte component -- long enough overall,
# one byte over NAME_MAX -- and failed every POSIX leg. So the length is built here
# from many *short* components, which cannot violate either: it is a construction, not
# an assertion that a construction is safe. The assertions below are tripwires on the
# construction, not the guarantee.
LONG_PATH_COMPONENT = "ordinary-directory-name"  # 23 bytes, far under NAME_MAX
LONG_PATH_DEPTH = 14  # ~336 characters of path, far over MAX_PATH and any reason cap


def test_a_long_path_does_not_truncate_what_the_range_lost(tmp_path):
    """Found by running the script on a real checkout, not by reading it.

    The reason ends with the consequence -- what the unscoped range anchored on --
    and the path sits in front of it. At a fixed character limit a normal absolute
    path cut the sentence off mid-directory, leaving a reason that named a file and
    never said what it cost.

    Nothing is created. `_scope` reads a config path and never touches git or the
    repo, so what the truncation arithmetic needs is a long *string*; a config that
    does not exist is one of the states under test here anyway.
    """
    module = _module()
    long_path = str(
        tmp_path.joinpath(*[LONG_PATH_COMPONENT] * LONG_PATH_DEPTH) / CONFIG_NAME
    )
    assert len(long_path) > 260, "the fixture must exceed any fixed reason limit"
    components = long_path.replace(os.sep, "/").split("/")
    assert max(len(part) for part in components) < 255, (
        "a component over NAME_MAX makes this a test of the filesystem"
    )

    unscoped = module._scope(str(tmp_path), None, long_path)
    assert unscoped["scope"] is None
    assert long_path in unscoped["scope_reason"], "the reason lost the path it names"
    assert unscoped["scope_reason"].endswith("read as the last release"), (
        "the path pushed the consequence off the end, so the reason names a file and "
        "never says what it cost"
    )

    # The pair: the same call with a short path is not truncated either, so the
    # assertion above is about the arithmetic and not about a limit nothing reaches.
    short = module._scope(str(tmp_path), None, str(tmp_path / CONFIG_NAME))
    assert short["scope_reason"].endswith("read as the last release")


def test_a_config_the_filesystem_will_not_look_at_is_unscoped_not_a_traceback(
    tmp_path,
):
    """The second lookup, which was inside the guard against the first.

    `_read_config` caught the read and then called `path.exists()` to tell absence
    from unreadability -- a second filesystem call, made from inside the except, where
    nothing catches it. `Path.exists()` swallows only a short list of errnos:
    ENAMETOOLONG is not on it, and neither is EACCES, so a config path with an
    over-long component, or one under a directory the process cannot traverse, killed
    the gate with a traceback in place of the unscoped range it exists to report.

    Observed on this machine, one fixture, three interpreters: 3.11 and 3.13 raise,
    3.14 returns False. CPython changed `Path.exists()` to swallow every OSError in
    3.14, which is why a local suite on 3.14 was green while all eight POSIX legs
    (3.9-3.12) were red -- the local run measured a different interpreter, not a
    different fixture. The classification now comes from the exception already in
    hand, so no version's `exists()` semantics can decide whether the gate survives.

    What is asserted here unconditionally is only what holds on every platform: the
    gate does not raise, the range is unscoped, the path survives into the reason and
    the consequence is not truncated. *Which* sentence it gets is not one of those --
    POSIX refuses this path with ENAMETOOLONG, and Windows may report the same path as
    an ordinary absence, in which case "there is no" is a true statement about it. So
    that claim is conditioned on what this platform actually did with the path,
    measured below, and skipped with the measurement when the OS gave nothing to tell
    the two apart. Branching on `sys.platform` instead would be a guess about the
    platform's behaviour dressed as a test of it -- which is the failure this whole
    test exists downstream of.
    """
    module = _module()
    unlookable = str(tmp_path / ("x" * 300) / CONFIG_NAME)

    scope = module._scope(str(tmp_path), None, unlookable)
    assert scope["scope"] is None
    assert unlookable in scope["scope_reason"]
    assert scope["scope_reason"].endswith("read as the last release")

    payload = module.compute(str(tmp_path), None, unlookable)
    assert payload["scope"] is None
    assert module.receipt(payload), "a receipt is produced whatever the path was"

    # The pair the classification claim exists for, and it needs no long path at all:
    # a file that is there and cannot be read, against a file that is simply not
    # there. Two different sentences on every platform, so the distinction the fix
    # introduced is tested wherever this suite runs.
    unreadable = tmp_path / "undecodable.json"
    unreadable.write_bytes(b'{"release": {"tag_pattern": "v\xff{version}"}}')
    assert "could not be read" in (
        module._scope(str(tmp_path), None, str(unreadable))["scope_reason"]
    )
    absent = module._scope(str(tmp_path), None, str(tmp_path / CONFIG_NAME))
    assert "there is no" in absent["scope_reason"]

    # Now the long path, classified against what the OS said rather than against what
    # a platform is assumed to say. The measurement is of the raw open, not of the
    # module, so agreeing with the module is not built in: if the OS reported anything
    # more specific than not-found and the module still called it absence, this fails.
    try:
        open(unlookable).close()
    except OSError as exc:
        raw = exc
    else:  # pragma: no cover - the fixture path cannot be opened anywhere
        pytest.fail("the fixture path was openable, so it tests nothing")

    winerror = getattr(raw, "winerror", None)
    plain_absence = winerror in (2, 3) if winerror is not None else False
    if isinstance(raw, FileNotFoundError) and plain_absence:
        pytest.skip(
            "this platform reported a 300-character component as an ordinary absence "
            "({0}, errno {1}, winerror {2}), so the OS itself offers nothing to tell "
            "'could not look' from 'nothing is there' for this path, and the "
            "classification went untested here. Everything above ran: no traceback, "
            "unscoped, path kept, consequence intact -- and the absent/unreadable "
            "pair is asserted just above without needing a long path.".format(
                type(raw).__name__, raw.errno, winerror
            )
        )
    assert "could not be read" in scope["scope_reason"], (
        "the OS distinguished this path from a missing file ({0}, errno {1}, winerror "
        "{2}) and the classification threw that away -- a check that could not look, "
        "reported as a check that looked and found nothing".format(
            type(raw).__name__, raw.errno, winerror
        )
    )


class _RaisingPath(object):
    """A config path whose read fails with an exception chosen by the test.

    The point of this file is a gate that survives whatever the filesystem does, and
    most of what a filesystem can do cannot be provoked on the platform running the
    suite. Constructing the exception is the only way to exercise the Windows arm
    from a POSIX run at all -- and it is honest about its grade: it establishes what
    `_read_config` does with a given error, never that Windows produces that error.
    """

    def __init__(self, exc):
        self._exc = exc

    def read_text(self, encoding=None):
        raise self._exc

    def __str__(self):
        return "C:\\somewhere\\.oss.json"


def test_a_windows_not_found_that_means_the_name_was_unlookable_is_not_absence():
    """`FileNotFoundError` is several different Win32 answers wearing one class.

    Python maps 206 (ERROR_FILENAME_EXCED_RANGE) onto ENOENT, so a name too long for
    the filesystem arrives in the same arm as a file that is merely not there. Called
    absence, that is this repo's defect class delivered by the OS: a check that could
    not look, reported as a check that looked and found nothing.

    GRADE. That `_read_config` classifies these codes this way is *observed*, here,
    on whatever platform ran this. That Windows *emits* 206 for an over-long name is
    *reasoned* -- from the documented error map, not from a run -- and if it is wrong
    the branch simply never fires, which is why nothing else depends on it.
    """
    module = _module()

    def read(winerror):
        exc = FileNotFoundError(2, "The system cannot find the file specified")
        if winerror is not None:
            exc.winerror = winerror
        return module._read_config(_RaisingPath(exc))

    for code in (206, 123):
        data, reason = read(code)
        assert data is None
        assert "could not be read" in reason, code
        assert str(code) in reason, "the reason drops the code it classified on"

    # The pair, twice over, because a rule that calls everything unreadable is the
    # same bug pointing the other way: a real not-found on Windows, and the POSIX
    # shape where no `winerror` attribute exists at all, are both still absence.
    for code in (2, 3, None):
        data, reason = read(code)
        assert data is None
        assert "there is no" in reason, code


def test_the_scoped_reason_keeps_the_path_of_a_real_deep_checkout(tmp_path):
    """The same arithmetic on the other branch, against a real file on disk.

    Three states, because two of them are not the same: the tree was built and the
    assertion ran, the tree was built and the assertion failed, or **the tree could
    not be built here**. Windows refuses a path past `MAX_PATH` unless
    `LongPathsEnabled` is set, and a runner may have it -- so this attempts the path
    and reports which answer it got, rather than assuming either. Shortening the
    names until they fit everywhere would delete the case on the one platform where
    paths are longest and leave a green tick where nothing ran.

    What a skip here does *not* lose: the arithmetic itself is exercised on every
    platform by the string-level case above, which needs no filesystem. What it does
    lose is the confirmation that a real checkout produces such a path at all.
    """
    module = _module()
    deep = tmp_path.joinpath(*["a-fairly-ordinary-directory-name"] * 4)
    config = deep / CONFIG_NAME
    try:
        deep.mkdir(parents=True)
        config.write_text(
            json.dumps({"release": {"tag_pattern": "v{version}"}}), encoding="utf-8"
        )
    except OSError as exc:
        # The reason names what was measured -- the length, the errno, the path --
        # and stops there. "MAX_PATH" is where this fires in practice and is worth
        # pointing at, but it is a Windows cause and this arm catches any OSError,
        # so stating it as the diagnosis would be an unmeasured claim in a message
        # whose whole job is to say exactly what was and was not established.
        pytest.skip(
            "a {0}-character path could not be created here ({1}: {2}), so the "
            "scoped reason went untested against a real deep checkout -- on Windows "
            "this is MAX_PATH without LongPathsEnabled. The arithmetic itself is "
            "still covered on this platform by the string-level case, which needs "
            "no filesystem.".format(len(str(config)), type(exc).__name__, exc)
        )

    scoped = module._scope(str(deep), None, None)
    assert scoped["scope"] == "v*"
    assert scoped["scope_reason"].endswith(CONFIG_NAME), (
        "the scoped reason lost the path it names"
    )


def test_an_explicit_config_path_is_read_instead_of_the_repos_own(tmp_path):
    module = _module()
    repo = _init(tmp_path / "elsewhere")
    (Path(repo) / ".oss.json").write_text(
        json.dumps({"release": {"tag_pattern": "nightly-{version}"}}), encoding="utf-8"
    )
    other = tmp_path / "other.json"
    other.write_text(
        json.dumps({"release": {"tag_pattern": "v{version}"}}), encoding="utf-8"
    )

    assert module._scope(str(repo), None, str(other))["scope"] == "v*"
    # The pair: without --config the repo's own file answers, so the line above is
    # about the flag and not about either file being the only one present.
    assert module._scope(str(repo), None, None)["scope"] == "nightly-*"


def test_a_path_that_is_not_a_directory_is_could_not_run(tmp_path):
    module = _module()
    payload = module.compute(str(tmp_path / "nowhere"))
    assert payload["state"] == "could-not-run"
    assert "not a directory" in payload["reason"]
