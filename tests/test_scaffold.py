"""Repo furniture: CLAUDE.md, SECURITY.md, issue templates, dependabot, settings.

The maintainer loop was not the only thing that drifted between repos. So did the
furniture around it -- one repo has no `.github/` at all, another's SECURITY.md is
a different document with the same name. Scaffolding is how that stops.

The rule that shapes every test here: **this writes into someone else's repo.** It
never overwrites, it shows before it writes, and a file that already exists is
reported as present rather than quietly replaced.
"""

import contextlib
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import doctor  # noqa: E402
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


# ----------------------------------------------------------------------------- plan


def test_every_template_is_planned_on_an_empty_repo(tmp_path):
    plan = scaffold.plan(tmp_path, _config())
    assert plan, "no entries -- the checks below would vacuously pass"
    defaults = {e["path"] for e in plan if e["action"] == "create"}
    assert defaults == set(scaffold.templates_for(_config()))
    owned = {e["path"] for e in plan if e["action"] == "replace"}
    assert owned == set(scaffold.OWNED)


def test_an_existing_file_is_reported_present_never_overwritten(tmp_path):
    target = tmp_path / "SECURITY.md"
    target.write_text("the repo's own policy\n", encoding="utf-8")
    plan = scaffold.plan(tmp_path, _config())
    entry = next(e for e in plan if e["path"] == "SECURITY.md")
    assert entry["action"] == "present"
    assert target.read_text(encoding="utf-8") == "the repo's own policy\n"


def test_apply_writes_only_the_missing_files(tmp_path):
    (tmp_path / "SECURITY.md").write_text("keep me\n", encoding="utf-8")
    written = scaffold.apply(tmp_path, _config())["created"]
    assert "SECURITY.md" not in written
    assert (tmp_path / "SECURITY.md").read_text(encoding="utf-8") == "keep me\n"
    assert "CLAUDE.md" in written
    assert (tmp_path / "CLAUDE.md").is_file()


def test_apply_creates_parent_directories(tmp_path):
    scaffold.apply(tmp_path, _config())
    assert (tmp_path / ".github" / "ISSUE_TEMPLATE" / "bug_report.md").is_file()


def test_a_second_apply_creates_no_defaults_but_still_replaces_ours(tmp_path):
    """Idempotent for defaults, deliberately not for the files we own -- that is the
    contract that lets an update reach a repo at all.
    """
    first = scaffold.apply(tmp_path, _config())
    second = scaffold.apply(tmp_path, _config())
    assert first["created"]
    assert second["created"] == []
    assert second["replaced"] == sorted(scaffold.OWNED)


def test_apply_refuses_a_config_that_does_not_validate(tmp_path):
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.apply(tmp_path, {"repo": "owner/name"})


def test_apply_is_not_disabled_by_an_underscore_prefixed_note(tmp_path):
    """#355. `plan()` and `apply()` both refuse on any `oss_config.validate()`
    problem via `ScaffoldError` -- a separate behaviour from the message the
    validator prints, and the one that actually disables the command. A config
    carrying a maintainer's explanatory note beside the value it explains must
    reach the write path exactly as a config without one does.
    """
    config = _config()
    config["_milestones_note"] = "kept for the release train, not because they're open"
    scaffold.plan(tmp_path, config)  # must not raise
    result = scaffold.apply(tmp_path, config)
    assert result["created"]


def test_plan_refuses_to_escape_the_repo_root(tmp_path):
    """Template paths are literals in this file, but a literal is one edit away from
    a variable. The containment check is on the write path, not on the author.
    """
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.render_to(tmp_path, "../escape.md", "x")


# ---------------------------------------------------------------------------- radar


def test_a_repo_with_no_supertool_config_has_nothing_to_report(tmp_path):
    """Nothing there means the template creates one with radar already on, so there
    is no finding to make.
    """
    assert scaffold.check_radar(tmp_path) == []


def test_an_existing_config_without_radar_tiers_is_reported(tmp_path):
    (tmp_path / ".supertool.json").write_text('{"presets": ["git"]}', encoding="utf-8")
    findings = scaffold.check_radar(tmp_path)
    assert findings and findings[0]["state"] == "no-tiers"
    assert "radar_tiers" in findings[0]["detail"]


def test_an_existing_config_with_a_registered_and_routed_tier_is_clean(tmp_path):
    """The positive control for every route assertion below: this arm can come back
    clean, so a `check_radar` reporting something for every config would fail here.
    """
    (tmp_path / ".supertool.json").write_text(
        json.dumps(
            {"presets": ["watch"], "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}}
        ),
        encoding="utf-8",
    )
    assert scaffold.check_radar(tmp_path) == []


def test_a_registered_tier_with_no_presets_list_is_route_unknown(tmp_path):
    """#205. Registration is half the question. A tier registered under a config that
    declares no `presets` has no observed route to the op that reads it, and answering
    `[]` there is the absence this plugin is named after -- `doctor` already says
    `route-unknown` for the identical file.
    """
    (tmp_path / ".supertool.json").write_text(
        '{"ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}}', encoding="utf-8"
    )
    findings = scaffold.check_radar(tmp_path)
    assert findings and findings[0]["state"] == "route-unknown"
    assert scaffold.WATCH_PRESET in findings[0]["detail"]


def test_a_registered_tier_under_presets_that_omit_watch_is_no_route(tmp_path):
    """Distinct from the one above on purpose: a `presets` list that is there and does
    not carry `watch` is a measured absence, not an unread one, and the two send a
    maintainer to different edits.
    """
    (tmp_path / ".supertool.json").write_text(
        json.dumps(
            {"presets": ["git"], "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}}
        ),
        encoding="utf-8",
    )
    findings = scaffold.check_radar(tmp_path)
    assert findings and findings[0]["state"] == "no-route"


def test_no_route_finding_prints_the_whole_corrected_document_not_a_fragment(tmp_path):
    """#622. The remedy fragment forces a maintainer to merge two independently
    silent halves of `.supertool.json` by hand -- getting one of the two right
    produces the byte-identical-to-healthy state the whole check exists to catch.
    The finding must instead carry the WHOLE corrected file, with the existing
    preset preserved (not replaced) and the already-registered tier untouched.
    """
    (tmp_path / ".supertool.json").write_text(
        json.dumps(
            {"presets": ["git"], "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}}
        ),
        encoding="utf-8",
    )
    findings = scaffold.check_radar(tmp_path)
    detail = findings[0]["detail"]
    marker = "The whole file, corrected: "
    assert marker in detail, detail
    document = json.loads(detail[detail.index(marker) + len(marker):])
    assert sorted(document["presets"]) == sorted(["git", scaffold.WATCH_PRESET])
    assert document["ops"]["radar"]["radar_tiers"] == {"gh-prs": {}}
    # Applying the printed document verbatim must satisfy both checkers -- the same
    # standard #205's own remedy is held to.
    (tmp_path / ".supertool.json").write_text(json.dumps(document), encoding="utf-8")
    assert scaffold.check_radar(tmp_path) == []
    assert doctor.radar_publish_state(tmp_path)[0] == "publishes"


def test_no_tiers_finding_prints_the_whole_corrected_document_when_presets_is_readable(
    tmp_path,
):
    """The other reachable state: tiers missing, `presets` present and already valid
    (with or without `watch`). The merge must still preserve whatever was there.
    """
    (tmp_path / ".supertool.json").write_text(
        json.dumps({"presets": ["watch", "git"]}), encoding="utf-8"
    )
    findings = scaffold.check_radar(tmp_path)
    detail = findings[0]["detail"]
    marker = "The whole file, corrected: "
    assert marker in detail, detail
    document = json.loads(detail[detail.index(marker) + len(marker):])
    assert sorted(document["presets"]) == sorted(["watch", "git"])
    assert document["ops"]["radar"]["radar_tiers"]


def test_route_unknown_prints_no_merged_document_because_presets_could_not_be_read(
    tmp_path,
):
    """Positive control for the two tests above: when `presets` itself is not a
    readable shape, a merge cannot safely decide what to append it to, so nothing
    claiming to be "the whole file, corrected" may appear -- printing a document
    here would risk silently discarding whatever the malformed value actually was.
    """
    (tmp_path / ".supertool.json").write_text(
        '{"presets": "not-a-list", "ops": {"radar": {"radar_tiers": {"gh-prs": {}}}}}',
        encoding="utf-8",
    )
    findings = scaffold.check_radar(tmp_path)
    assert findings and findings[0]["state"] == "route-unknown"
    assert "The whole file, corrected:" not in findings[0]["detail"]


def test_scaffolds_own_radar_remedy_satisfies_both_checkers(tmp_path):
    """The remedy half of #205, and only that half -- said plainly, because the first
    version of this docstring called itself "#205's core" and a reviewer was right that
    it is not. A config carrying both halves comes back clean from the check that reads
    one half and from the check that reads two, so this test would pass unchanged
    against the pre-fix `check_radar`. What it does pin is the defect the old REMEDY
    was: the remedy scaffold printed omitted `presets`, so applying it verbatim left
    `doctor` at `route-unknown`, and the `doctor` assertion below fails against that
    remedy. The route-reading defect is pinned by the two tests above it, which were
    red.

    A remedy is a claim about what would fix the thing, and the only way to find out is
    to run both checks over it -- asserting that the two remedy strings match would pass
    just as happily on two remedies that fix nothing. That is the second measurement
    replacing the deleted "the same remedy" comment in `doctor.py`: the two values are
    composed independently and held together here by what they do.
    """
    (tmp_path / ".supertool.json").write_text(
        json.dumps(scaffold.RADAR_REMEDY_CONFIG), encoding="utf-8"
    )
    assert scaffold.check_radar(tmp_path) == []
    assert doctor.radar_publish_state(tmp_path)[0] == "publishes"


def test_a_supertool_config_that_is_json_but_not_a_config_is_reported_not_raised(
    tmp_path,
):
    """`.supertool.json` is contributor-writable in a managed repo. Every one of these
    parses as JSON and none is a config, and `check_radar` reached an `AttributeError`
    on each -- a traceback out of `/oss:scaffold`, from a tracked file.
    """
    bodies = (
        "[]",
        '"x"',
        '{"ops": "nope"}',
        '{"ops": {"radar": 3}}',
        '{"ops": {"radar": {"radar_tiers": 3}}}',
    )
    for body in bodies:
        (tmp_path / ".supertool.json").write_text(body, encoding="utf-8")
        findings = scaffold.check_radar(tmp_path)
        assert findings, body
        assert findings[0]["state"] in ("unreadable", "malformed"), body


def test_the_radar_row_reaches_the_printed_receipt(tmp_path):
    """scaffold's `radar    ` row was uncovered by the suite (#205). A finding nothing
    prints is a finding nobody reads, and the suite could not tell those two apart.
    """
    (tmp_path / ".supertool.json").write_text('{"presets": ["git"]}', encoding="utf-8")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        scaffold._print_findings(tmp_path, _config(repo=""))
    rows = [line for line in buffer.getvalue().splitlines() if line.startswith("radar ")]
    assert len(rows) == 1, buffer.getvalue()
    assert scaffold.RADAR_TIERS_KEY in rows[0]


def test_an_unreadable_config_is_unknown_not_off(tmp_path):
    """The third state. Reporting "no radar" for a file we could not parse would send
    someone to add a block that is already there.
    """
    (tmp_path / ".supertool.json").write_text("{ broken", encoding="utf-8")
    findings = scaffold.check_radar(tmp_path)
    assert findings and findings[0]["state"] == "unreadable"


def test_the_shipped_config_turns_radar_on(tmp_path):
    """The point of shipping it: a managed repo has a board the first time someone
    opens it, rather than after they discover the op exists.
    """
    scaffold.apply(tmp_path, _config())
    assert scaffold.check_radar(tmp_path) == []
    written = json.loads((tmp_path / ".supertool.json").read_text(encoding="utf-8"))
    assert written["ops"]["radar"]["radar_tiers"]


def test_the_shipped_config_declares_watch_name_on_all_five_watch_ops_682(tmp_path):
    """#682: supertool cannot see .oss.json or the launcher's derivation, so a
    .supertool.json declaring no watch_name reads -- on every single call, not
    just the ones a launcher-started session ever reaches -- as a possible
    cross-project collision. All five ops the watch preset spawns from, not a
    subset: a name on radar alone still leaves channel/unwatch/watch/watches
    reading the shared default socket over a fleet alive on the derived one.
    """
    scaffold.apply(tmp_path, _config(repo="acme/widget"))
    written = json.loads((tmp_path / ".supertool.json").read_text(encoding="utf-8"))
    expected, problem = oss_config.watch_channel_name("acme/widget")
    assert problem is None
    for op in ("channel", "radar", "unwatch", "watch", "watches"):
        assert written["ops"][op]["watch_name"] == expected


def test_the_watch_name_comes_from_oss_json_not_invented_682(tmp_path):
    """.oss.json's repo stays the one source (CLAUDE.md's own rule): a different
    repo slug must produce a different derived name, never a hardcoded default
    scaffold made up on its own.
    """
    scaffold.apply(tmp_path, _config(repo="other/repo"))
    written = json.loads((tmp_path / ".supertool.json").read_text(encoding="utf-8"))
    assert written["ops"]["watch"]["watch_name"] == "other-repo"
    assert written["ops"]["watch"]["watch_name"] != "acme-widget"


def test_rendering_supertool_json_refuses_an_invalid_repo_682():
    """Same refusal shape as CLAUDE.md's repo_slug() -- an invented name from an
    unusable repo value would be a fact this generated file states with no
    measurement behind it.
    """
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.render(".supertool.json", _config(repo=None))


def test_the_shipped_config_declares_defensible_default_validators_633(tmp_path):
    """#633 half one: no scaffolded repo gets a single configured validator today,
    so every write in a managed repo runs with no post-write check and no
    rollback. The three shipped here are chosen for being safe on any machine:
    jsonlint is stdlib-only, tomllint degrades to 'skipped' rather than a false
    'ok' when tomllib/tomli is unavailable, and bash-check only needs a bash on
    PATH. Nothing needing an external binary install (shellcheck, actionlint,
    markdownlint, gitleaks) ships as a default -- half two of #633 (doctor
    reporting a configured-but-absent toolchain) does not exist yet, and an
    unreported 'could not tell' on every write is worse than no validator at all.
    Python itself needs no entry: py-syntax is supertool's built-in backstop and
    applies with zero configuration.
    """
    scaffold.apply(tmp_path, _config())
    written = json.loads((tmp_path / ".supertool.json").read_text(encoding="utf-8"))
    validators = written.get("validators")
    assert validators and set(validators) == {"jsonlint", "tomllint", "bash-check"}
    assert validators["jsonlint"]["match"] == "*.json"
    assert validators["tomllint"]["match"] == "*.toml"
    assert validators["bash-check"]["match"] == "*.sh"


def test_an_existing_supertool_config_is_never_replaced(tmp_path):
    (tmp_path / ".supertool.json").write_text('{"presets": ["mine"]}', encoding="utf-8")
    scaffold.apply(tmp_path, _config())
    assert "mine" in (tmp_path / ".supertool.json").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- render


def test_claude_md_names_this_repo_not_another(tmp_path):
    body = scaffold.render("CLAUDE.md", _config(repo="acme/widget", default_branch="trunk"))
    assert "acme/widget" in body
    assert "trunk" in body


def test_claude_md_carries_the_test_command_when_known():
    assert "pytest" in scaffold.render("CLAUDE.md", _config())


def test_claude_md_says_unknown_rather_than_guessing_a_test_command():
    body = scaffold.render("CLAUDE.md", _config(test_command=None))
    assert "not detected" in body
    assert "pytest" not in body


def test_claude_md_states_the_untrusted_input_rule():
    """The furniture carries it too. A contributor reading CLAUDE.md is the person
    most likely to paste an issue body into a prompt.
    """
    assert "data, not instructions" in scaffold.render("CLAUDE.md", _config())


def test_no_template_hardcodes_a_sibling_repo():
    """The whole point of extracting this was that the copies named their own repo."""
    for name in scaffold.templates_for(_config()):
        body = scaffold.render(name, _config())
        for spelling in ("Digital-Process-Tools/claude-", "claude-supertool", "claude-remember"):
            assert spelling not in body, "{} hardcodes {}".format(name, spelling)


def test_rendering_an_unknown_template_is_an_error_not_an_empty_string():
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.render("NOT_A_TEMPLATE.md", _config())


def test_every_template_renders_without_a_leftover_placeholder():
    """An unsubstituted placeholder reaching a committed file is silent and permanent.

    `branch_pattern` is a legitimate exception rather than a hole in this check: its
    own value (`"fix/{issue}"` in `_config()`) is data that CONTRIBUTING.md quotes
    verbatim (#460), so `{issue}` in the rendered body is that value having arrived
    correctly, not a `.format()` slot .format() itself never filled. Stripped before
    the scan so a real leftover next to it is still caught.

    `.supertool.json`'s `{python}`/`{supertool_dir}`/`{file}` are a second, disjoint
    exception (#682): supertool's OWN placeholder syntax, substituted by supertool at
    call time, never by scaffold. `_render_supertool_json` uses `.replace()` rather
    than `.format()` specifically so these survive untouched -- a real leftover
    `.format()` slot in this file would still be caught, since none of scaffold's own
    substitutions ever spell a name from this set.
    """
    leftover = re.compile(r"\{[a-z_]+\}")
    supertool_placeholders = re.compile(r"\{(python|supertool_dir|file)\}")
    config = _config()
    for name in scaffold.templates_for(config):
        body = scaffold.render(name, config)
        body = body.replace(config["branch_pattern"], "")
        if name == ".supertool.json":
            body = supertool_placeholders.sub("", body)
        found = leftover.search(body)
        assert found is None, "{} still contains {}".format(name, found and found.group(0))


def test_a_null_config_value_never_reaches_a_rendered_file_as_None():
    """`None` cannot be checked for as a bare word -- "None of this is acceptable" is
    ordinary English and appears in the code of conduct. What matters is that a null
    config value renders as prose, so this asserts on the template that interpolates.
    """
    body = scaffold.render("CLAUDE.md", _config(test_command=None))
    assert "None" not in body
    assert "not detected" in body


# ----------------------------------------------------------------------------- show
#
# `/oss:scaffold` tells the caller to relay what each generated file would contain
# before writing it. The dry run named the plan but had no way to obtain the content,
# so an agent's only options were to invent a preview by hand or run --apply first and
# read the result -- which writes before showing, on exactly the files the instruction
# says need a look first (#5).


def test_show_covers_every_file_that_would_be_created(tmp_path):
    """`.claude/settings.json` is excluded on purpose (#494): it is a "create" entry
    too, once settings_plan() is folded into show(), but it is not a template -- it is
    a key-level write into a file that is not ours, and templates_for() only ever
    named whole files this plugin writes. See test_scaffold_settings_preview_494.py
    for that half.
    """
    shown = scaffold.show(tmp_path, _config())
    created = {
        path for path, action, _ in shown
        if action == "create" and path != scaffold.SETTINGS_PATH
    }
    assert created == set(scaffold.templates_for(_config()))


def test_show_covers_every_owned_file_too(tmp_path):
    """`plan()` never marks an OWNED file "create" -- they are always "replace", so a
    filter that only kept "create" entries silently dropped every one of them. These
    are the files `apply` overwrites unconditionally, which makes the preview matter
    most here, not least (coordinator review after the first pass of #5).

    The 01-oss rule layer joined them in #182 -- same contract, same argument -- so this
    is a superset assertion now, with the surplus pinned to the layer rather than left
    unexamined. An equality here would have been the thing that made adding the layer
    look like a regression.
    """
    shown = scaffold.show(tmp_path, _config())
    replaced = {path for path, action, _ in shown if action == "replace"}
    assert set(scaffold.OWNED) <= replaced
    assert replaced - set(scaffold.OWNED) == set(scaffold.rule_layer_paths())


def test_show_when_every_template_already_exists_still_reports_owned_files(tmp_path):
    """The sharp case: a repo that already has every default. `apply` writes nothing
    under TEMPLATES here but still overwrites all three OWNED files -- the destructive
    half of `apply`. A preview that goes quiet in this case is the same shape as #8's
    confident "missing": an absence the tool produced, read as an absence in the repo.
    """
    scaffold.apply(tmp_path, _config())
    shown = scaffold.show(tmp_path, _config())
    paths = {path for path, _, _ in shown}
    assert paths, "nothing to show -- the assertion below would vacuously pass"
    # The owned trio and the rule layer: everything replaced wholesale on every run,
    # and nothing else, since every template is already present. The layer was the
    # missing half of exactly this assertion until #182.
    assert paths == set(scaffold.OWNED) | set(scaffold.rule_layer_paths())
    assert all(action == "replace" for _, action, _ in shown)


def test_show_content_matches_what_apply_would_write(tmp_path):
    config = _config(repo="acme/widget", default_branch="trunk")
    shown = {path: body for path, _, body in scaffold.show(tmp_path, config)}
    assert shown["CLAUDE.md"] == scaffold.render("CLAUDE.md", config)
    assert shown[".oss/README.md"] == scaffold.render_owned(".oss/README.md", config)


def test_show_skips_a_template_that_already_exists(tmp_path):
    (tmp_path / "SECURITY.md").write_text("ours\n", encoding="utf-8")
    shown = scaffold.show(tmp_path, _config())
    assert "SECURITY.md" not in {path for path, _, _ in shown}


def test_show_one_path_returns_only_that_files_body_and_action(tmp_path):
    shown = scaffold.show(tmp_path, _config(), path="SECURITY.md")
    assert shown == [("SECURITY.md", "create", scaffold.SECURITY_MD)]


def test_show_one_path_works_even_when_the_file_is_already_present(tmp_path):
    """A single-path request is "what would this default contain", which is worth
    knowing even for a file the plan would call present rather than create."""
    (tmp_path / "SECURITY.md").write_text("ours\n", encoding="utf-8")
    shown = scaffold.show(tmp_path, _config(), path="SECURITY.md")
    assert shown == [("SECURITY.md", "create", scaffold.SECURITY_MD)]


def test_show_of_an_unknown_path_is_an_error_not_an_empty_list():
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.show(Path("."), _config(), path="NOT_A_TEMPLATE.md")


def test_show_can_render_an_owned_file_by_path(tmp_path):
    shown = scaffold.show(tmp_path, _config(), path=".oss/README.md")
    assert shown == [(".oss/README.md", "replace", scaffold.render_owned(".oss/README.md", _config()))]


def test_show_renders_the_fragments_readme_by_path(tmp_path):
    """The two forms of show must agree. The bare form walks plan(), which is
    config-aware, so a single-path lookup against the module-level TEMPLATES would
    refuse a file the very same call had just listed as pending.
    """
    config = _config()
    shown = scaffold.show(tmp_path, config, path="changelog.d/README.md")
    assert shown == [
        ("changelog.d/README.md", "create", scaffold.render("changelog.d/README.md", config))
    ]


def test_show_follows_the_configured_fragment_directory(tmp_path):
    config = _config(changelog_dir="news.d")
    shown = scaffold.show(tmp_path, config, path="news.d/README.md")
    assert shown[0][0] == "news.d/README.md"
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.show(tmp_path, config, path="changelog.d/README.md")


def test_the_unknown_path_error_lists_the_fragments_readme(tmp_path):
    """The error names what IS known, and a name missing from that list reads as a
    file the scaffold does not write.
    """
    with pytest.raises(scaffold.ScaffoldError) as excinfo:
        scaffold.show(tmp_path, _config(), path="NOT_A_TEMPLATE.md")
    assert "changelog.d/README.md" in str(excinfo.value)


def test_show_lists_the_fragments_readme_among_what_it_would_create(tmp_path):
    shown = scaffold.show(tmp_path, _config())
    created = {path: action for path, action, _ in shown}
    assert created.get("changelog.d/README.md") == "create"


def test_the_fragments_readme_documents_the_compatibility_bullet():
    """`release_version.py` refuses a `removed` fragment that declares nothing (#225).

    The README scaffold writes is the one document a fragment author opens, and
    it is a *default* under the ownership contract -- created once when absent,
    then theirs forever -- so a repo scaffolded without this section never gets
    it retroactively. Shipping the template without it mints a fresh instance of
    #225 into every repository scaffolded from here.
    """
    body = scaffold.render("changelog.d/README.md", _config())
    assert "## Compatibility" in body
    assert "- Compatibility: breaking|compatible - <reason>" in body
    assert "removed" in body


def test_the_compatibility_section_follows_a_renamed_fragment_directory():
    """The section must not be keyed to the default directory name.

    Every other heading in this template is directory-agnostic; a section added
    with `changelog.d` written into it would be correct in this repository and
    wrong in the repositories the template exists for -- which is the shape of
    the defect being fixed, one file over.
    """
    body = scaffold.render("news.d/README.md", _config(changelog_dir="news.d"))
    assert "- Compatibility: breaking|compatible - <reason>" in body
    assert "changelog.d" not in body


# ------------------------------------------------------------------ fragment dir
#
# The scaffold installs a workflow that polices a fragment directory. Until the
# directory exists in the repo, that workflow is red on the pull request that
# introduces it -- for a reason that has nothing to do with the change.


def _with_workflow(root, body="name: ci\n", name="ci.yml"):
    directory = root / ".github" / "workflows"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(body, encoding="utf-8")


def test_the_fragment_directory_the_workflow_polices_is_planned(tmp_path):
    paths = {e["path"]: e["action"] for e in scaffold.plan(tmp_path, _config())}
    assert paths.get("changelog.d/README.md") == "create"


def test_the_scaffolded_repo_passes_its_own_fragment_check(tmp_path):
    """The strongest form of it: run the vendored checker the workflow runs."""
    scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT)
    result = subprocess.run(
        [
            sys.executable,
            str(tmp_path / ".oss" / "assemble_changelog.py"),
            "--check",
            "--dir",
            "changelog.d",
            "--changelog",
            "CHANGELOG.md",
        ],
        cwd=str(tmp_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    assert result.returncode == 0, result.stdout


def test_a_repo_with_no_fragment_practice_gets_the_directory_the_workflow_names(tmp_path):
    """`changelog_dir` null still yields a workflow naming changelog.d, so that is
    the directory that has to exist.
    """
    scaffold.apply(tmp_path, _config(changelog_dir=None), plugin_root=REPO_ROOT)
    assert (tmp_path / "changelog.d" / "README.md").is_file()
    workflow = (tmp_path / ".github" / "workflows" / "oss-changelog.yml").read_text(
        encoding="utf-8"
    )
    assert "changelog.d" in workflow


def test_a_custom_fragment_directory_is_the_one_created(tmp_path):
    scaffold.apply(tmp_path, _config(changelog_dir="news.d"), plugin_root=REPO_ROOT)
    assert (tmp_path / "news.d" / "README.md").is_file()
    assert not (tmp_path / "changelog.d").exists()


def test_an_existing_fragment_readme_is_never_overwritten(tmp_path):
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "changelog.d" / "README.md").write_text("ours\n", encoding="utf-8")
    scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT)
    assert (tmp_path / "changelog.d" / "README.md").read_text(encoding="utf-8") == "ours\n"


# ---------------------------------------------------------------- escape hatch


def test_the_escape_hatch_label_is_reported_missing_never_created():
    """Creating it would mutate the forge from a filesystem tool. Naming it does not."""
    findings = scaffold.check_changelog_label(["bug", "enhancement"])
    assert findings and findings[0]["state"] == "missing"
    assert "no-changelog" in findings[0]["detail"]
    assert "gh label create" in findings[0]["detail"]


def test_an_existing_escape_hatch_label_is_clean():
    assert scaffold.check_changelog_label(["bug", "no-changelog"]) == []


def test_labels_that_could_not_be_listed_are_unknown_not_missing():
    """The third state. "We could not ask" is not "it is not there"."""
    findings = scaffold.check_changelog_label(None)
    assert findings and findings[0]["state"] == "unknown"


def test_the_unknown_state_carries_the_reason_it_could_not_look():
    """An unknown with no reason reads exactly like one nobody attempted."""
    findings = scaffold.check_changelog_label(None, reason="gh is not on PATH")
    assert findings[0]["state"] == "unknown"
    assert "gh is not on PATH" in findings[0]["detail"]


# ------------------------------------------------- the escape hatch, through the CLI
#
# The three arms above are the function's. These are the call site's, which is where
# the state was being thrown away: a hardcoded None meant every run printed the same
# reminder whether the label existed or not. Each case pins the forge seam, so the
# suite never reaches the network.


def _cli_findings(tmp_path, monkeypatch, seam, **overrides):
    """Run the scaffold CLI with the forge read pinned, return everything it printed."""
    config = _config(**overrides)
    project, local = oss_config.split(config)
    (tmp_path / oss_config.CONFIG_NAME).write_text(json.dumps(project), encoding="utf-8")
    (tmp_path / oss_config.LOCAL_CONFIG_NAME).write_text(json.dumps(local), encoding="utf-8")
    monkeypatch.setattr(scaffold, "_forge_label_names", seam)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        scaffold._main(
            [
                "--root",
                str(tmp_path),
                "--config",
                str(tmp_path / oss_config.CONFIG_NAME),
                "--apply",
            ]
        )
    return out.getvalue()


def test_the_cli_reports_the_label_missing_when_the_forge_says_it_is_absent(
    tmp_path, monkeypatch
):
    out = _cli_findings(
        tmp_path, monkeypatch, lambda root, config: (["bug", "enhancement"], "")
    )
    assert "no such label exists" in out
    assert "gh label create" in out


def test_the_cli_says_nothing_about_a_label_the_forge_reports_present(
    tmp_path, monkeypatch
):
    """The positive control for the case above.

    Asserting the reminder appears proves nothing on its own -- the old call site
    printed it unconditionally, so that half passes before the fix as well as after.
    This is the half that fails there. The `tests` finding is asserted alongside, so
    a run that printed nothing at all -- a dead harness, a crash before the findings
    -- fails here rather than passing on the silence.
    """
    out = _cli_findings(
        tmp_path, monkeypatch, lambda root, config: (["bug", "no-changelog"], "")
    )
    assert "runs it" in out, "findings did not print at all -- the silence is the harness"
    assert "label    " not in out
    assert "gh label create" not in out


def test_the_cli_names_why_it_could_not_look_rather_than_passing(tmp_path, monkeypatch):
    """`unknown` must not render as `ok`. It renders as a line saying what stopped it."""
    out = _cli_findings(
        tmp_path, monkeypatch, lambda root, config: (None, "gh is not on PATH")
    )
    assert "label    " in out
    assert "gh is not on PATH" in out
    assert "no such label exists" not in out


# ------------------------------------------------------------------- the forge seam


def test_the_forge_is_not_asked_about_a_repo_this_checkout_is_not(tmp_path, monkeypatch):
    """The read is gated on the checkout in front of us actually being that repo.

    Without the gate, scaffolding any directory fires a network call about whatever
    slug .oss.json happens to name -- including every temp directory in this suite.

    `gh` is pinned present so this measures the git gate rather than whether the
    machine running the suite happens to have gh installed: without the pin, a
    contributor without gh sees this fail on the PATH arm, whose reason has nothing
    to do with the property being asserted.
    """
    monkeypatch.setattr(scaffold.shutil, "which", lambda name: "/usr/bin/" + name)
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names is None
    assert "owner/name" in reason


def test_the_forge_read_is_skipped_with_a_reason_when_gh_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(scaffold.shutil, "which", lambda name: None)
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names is None
    assert "gh" in reason and "PATH" in reason


def test_the_forge_read_is_skipped_when_no_repo_is_configured(tmp_path):
    names, reason = scaffold._forge_label_names(tmp_path, _config(repo=None))
    assert names is None
    assert "repo" in reason


def _pin_forge(monkeypatch, origin, gh):
    """Pin both subprocesses. `gh` is (ok, stdout, detail); `origin` is the remote URL."""
    monkeypatch.setattr(scaffold.shutil, "which", lambda name: "/usr/bin/" + name)

    def fake_run(command):
        if command[0] == "git":
            return (origin is not None), (origin or ""), "no origin remote"
        return gh

    monkeypatch.setattr(scaffold, "_run", fake_run)


def test_the_forge_answers_with_the_label_names_it_read(tmp_path, monkeypatch):
    _pin_forge(
        monkeypatch,
        "git@github.com:owner/name.git\n",
        (True, '[{"name": "bug"}, {"name": "no-changelog"}]', ""),
    )
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names == ["bug", "no-changelog"]
    assert reason == ""
    assert scaffold.check_changelog_label(names, reason=reason) == []


def test_an_origin_with_the_git_suffix_still_matches_the_configured_repo(
    tmp_path, monkeypatch
):
    """The suffix strip takes the trailing `.git` only, not every occurrence of it."""
    _pin_forge(monkeypatch, "https://github.com/owner/name.git", (True, "[]", ""))
    names, _ = scaffold._forge_label_names(tmp_path, _config())
    assert names == []


def test_an_origin_pointing_somewhere_else_is_not_asked_about(tmp_path, monkeypatch):
    _pin_forge(monkeypatch, "https://github.com/other/thing.git", (True, "[]", ""))
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names is None
    assert "other/thing" in reason


def test_a_mismatched_origin_does_not_carry_its_credential_into_the_report(
    tmp_path, monkeypatch
):
    """The refusal is the line most likely to be pasted, so it must not carry a token.

    `https://x-access-token:TOKEN@host/o/r` is an ordinary remote spelling -- a CI
    checkout leaves one behind, and several credential helpers write one. The mismatch
    half of this fixture is the positive control: an assertion that the token is absent
    also passes when the refusal stopped being printed at all.
    """
    _pin_forge(
        monkeypatch,
        "https://x-access-token:ghp_SECRETVALUE@github.com/other/thing.git",
        (True, "[]", ""),
    )
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names is None
    assert "ghp_SECRETVALUE" not in reason
    assert "x-access-token" not in reason
    # ... and the refusal still says which repo it saw and which it wanted.
    assert "other/thing" in reason
    assert "owner/name" in reason


def test_a_token_standing_alone_as_the_userinfo_is_redacted_too(tmp_path, monkeypatch):
    """GitHub accepts the token as the whole username, with no password field at all."""
    _pin_forge(monkeypatch, "https://ghp_SECRETVALUE@github.com/other/thing", (True, "[]", ""))
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names is None
    assert "ghp_SECRETVALUE" not in reason
    assert "other/thing" in reason


def test_an_ordinary_ssh_origin_is_still_quoted_in_full(tmp_path, monkeypatch):
    """The control on the redaction: it must not swallow the URL it was given.

    A sanitiser that returns a placeholder for everything passes every "the secret is
    absent" assertion above while telling the maintainer nothing about their remote.
    """
    _pin_forge(monkeypatch, "git@github.com:other/thing.git", (True, "[]", ""))
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names is None
    assert "github.com:other/thing" in reason


def test_a_query_string_is_dropped_from_a_quoted_origin(tmp_path, monkeypatch):
    """Userinfo is not the only place a URL holds a secret; `?access_token=` is another.

    The scheme is what makes the cut safe: a query is a URL's, and a path that happens to
    contain `?` is not one. The marker is left behind so the reader knows the URL they are
    reading is shorter than the one on disk.
    """
    _pin_forge(
        monkeypatch, "https://github.com/other/thing.git?token=ghp_SECRETVALUE", (True, "[]", "")
    )
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names is None
    assert "ghp_SECRETVALUE" not in reason
    assert "other/thing" in reason
    assert "[redacted]" in reason


def test_an_origin_whose_userinfo_cannot_be_recognised_is_not_quoted_at_all(
    tmp_path, monkeypatch
):
    """A spelling that cannot be normalised is reported as such, never passed through.

    A local-path remote holding an `@` is the honest cost of that rule: nothing in it is
    secret, and it is still withheld, because at this point the string has already failed
    to be either URL shape and nothing about it is known. The refusal still names the repo
    that was wanted, which is the half a reader acts on.
    """
    _pin_forge(monkeypatch, "/srv/mirrors/me@work/thing.git", (True, "[]", ""))
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names is None
    assert "me@work" not in reason
    assert "not shown" in reason
    assert "owner/name" in reason


def test_a_userinfo_holding_a_literal_at_sign_is_redacted_whole(tmp_path, monkeypatch):
    """The delimiter is the *last* `@` before the path, not the first.

    An email as the username is an ordinary spelling on more than one forge, and curl --
    which is what git drives for https -- reads the authority that way. Splitting on the
    first `@` leaves the password on the right of the split, still printed.
    """
    _pin_forge(
        monkeypatch,
        "https://me@corp.example:ghp_SECRETVALUE@github.com/other/thing.git",
        (True, "[]", ""),
    )
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names is None
    assert "ghp_SECRETVALUE" not in reason
    assert "other/thing" in reason


def test_a_windows_path_with_an_at_sign_is_not_mistaken_for_a_credential(tmp_path):
    r"""`C:\Users\bob@corp\repo` holds no userinfo -- a drive letter is not a username.

    Reading one as a credential does not disclose anything, but it prints `[redacted]`
    over a path that was never secret, which teaches the reader to distrust the marker.
    A backslash never separates a URL's authority from its path, so it bounds the span
    a credential can occupy exactly as `/` does.
    """
    windows_path = r"C:\Users\bob@corp\repo"
    assert scaffold._without_credentials(windows_path) == windows_path


def test_the_unreadable_origin_arm_does_not_echo_a_credential_from_git_stderr(
    tmp_path, monkeypatch
):
    """git echoes the URL in its own error text, and that text is interpolated too."""
    monkeypatch.setattr(scaffold.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(
        scaffold,
        "_run",
        lambda command: (
            False,
            "",
            "git remote get-url exited 128: could not read "
            "https://x-access-token:ghp_SECRETVALUE@github.com/other/thing.git",
        ),
    )
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names is None
    assert "ghp_SECRETVALUE" not in reason
    # ... and the arm still reports what it could not do, and about which repo.
    assert "exited 128" in reason
    assert "owner/name" in reason


def test_the_stderr_arm_redacts_a_userinfo_holding_a_literal_at_sign(tmp_path, monkeypatch):
    """This arm has no `not shown` fallback, so its redaction must be right on its own.

    `_safe_origin` knows it holds one whole URL and can refuse to quote a spelling it
    could not normalise. A line of git's stderr is prose with a URL somewhere inside it,
    so suppressing the line would cost the reader the error itself -- which makes the
    span the redaction takes the only thing standing between a token and the report.
    """
    monkeypatch.setattr(scaffold.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(
        scaffold,
        "_run",
        lambda command: (
            False,
            "",
            "git remote get-url exited 128: could not read "
            "https://me@corp.example:ghp_SECRETVALUE@github.com/other/thing.git",
        ),
    )
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names is None
    assert "ghp_SECRETVALUE" not in reason
    assert "exited 128" in reason


def test_an_unauthenticated_gh_is_unknown_with_its_own_words(tmp_path, monkeypatch):
    _pin_forge(
        monkeypatch,
        "https://github.com/owner/name",
        (False, "", "gh label list exited 4: gh auth login required"),
    )
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names is None
    assert "gh auth login required" in reason
    assert scaffold.check_changelog_label(names, reason=reason)[0]["state"] == "unknown"


def test_gh_output_that_is_not_json_is_unknown_rather_than_empty(tmp_path, monkeypatch):
    """An unparseable answer read as `[]` would report the label missing on no evidence."""
    _pin_forge(monkeypatch, "https://github.com/owner/name", (True, "not json", ""))
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names is None
    assert "JSON" in reason


def test_gh_json_that_is_not_a_list_is_unknown(tmp_path, monkeypatch):
    _pin_forge(monkeypatch, "https://github.com/owner/name", (True, '{"name": "bug"}', ""))
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names is None
    assert "not a list" in reason


def test_an_origin_whose_slug_merely_starts_with_the_configured_one_is_refused(
    tmp_path, monkeypatch
):
    """`owner/name` occurs inside `owner/name-fork`, and a substring test would match.

    The failure that guards against is quieter than a mismatch: the query goes to a
    real repo that is not this one and the answer comes back looking authoritative.
    """
    _pin_forge(monkeypatch, "https://github.com/owner/name-fork.git", (True, "[]", ""))
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names is None
    assert "owner/name-fork" in reason


def test_an_ssh_origin_is_matched_on_the_colon(tmp_path, monkeypatch):
    """The positive control for the case above: anchoring must not reject a real match."""
    _pin_forge(monkeypatch, "git@github.com:owner/name.git", (True, "[]", ""))
    names, _ = scaffold._forge_label_names(tmp_path, _config())
    assert names == []


def test_an_origin_with_a_trailing_slash_still_matches(tmp_path, monkeypatch):
    _pin_forge(monkeypatch, "https://github.com/owner/name/", (True, "[]", ""))
    names, _ = scaffold._forge_label_names(tmp_path, _config())
    assert names == []


def test_a_full_page_of_labels_is_unknown_rather_than_a_verdict(tmp_path, monkeypatch):
    """A truncated read reporting `missing` is this module's own defect class.

    The label may sit on the page nobody fetched, and "not in what we saw" would
    render as "not in the repo".
    """
    page = json.dumps([{"name": "l{}".format(n)} for n in range(scaffold._LABEL_PAGE)])
    _pin_forge(monkeypatch, "https://github.com/owner/name", (True, page, ""))
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names is None
    assert "truncated" in reason
    assert scaffold.check_changelog_label(names, reason=reason)[0]["state"] == "unknown"


def test_one_short_of_a_full_page_is_a_real_answer(tmp_path, monkeypatch):
    """The positive control: the truncation guard must not swallow every read."""
    page = json.dumps([{"name": "l{}".format(n)} for n in range(scaffold._LABEL_PAGE - 1)])
    _pin_forge(monkeypatch, "https://github.com/owner/name", (True, page, ""))
    names, reason = scaffold._forge_label_names(tmp_path, _config())
    assert names is not None and reason == ""
    assert scaffold.check_changelog_label(names)[0]["state"] == "missing"


def test_a_measured_absence_does_not_tell_you_to_go_and_check():
    """The run just read the list. Repeating "check with gh label list" contradicts it."""
    detail = scaffold.check_changelog_label(["bug"])[0]["detail"]
    assert "gh label create" in detail
    assert "gh label list" not in detail
    unknown = scaffold.check_changelog_label(None, reason="gh is not on PATH")[0]["detail"]
    assert "gh label list" in unknown


def test_output_that_cannot_be_decoded_is_a_reason_not_a_traceback(monkeypatch):
    """UnicodeDecodeError is not an OSError, so it would otherwise escape _run."""

    def boom(*args, **kwargs):
        raise UnicodeDecodeError("utf-8", bytes([255]), 0, 1, "invalid start byte")

    monkeypatch.setattr(scaffold.subprocess, "run", boom)
    ok, out, detail = scaffold._run(["gh", "label", "list"])
    assert ok is False
    assert "decode" in detail


# --------------------------------------------------------------- required checks

# `check_ci` and the six tests over it were deleted with the key in #113. What replaces
# them is tests/test_required_checks_left_the_config.py, which asserts the absence: no
# script reads `required_checks`, `scaffold` has no `check_ci`, and an `.oss.json` still
# carrying the block on somebody else's disk still validates.


def test_scaffold_writes_no_ci_block_of_its_own(tmp_path):
    """The property the deleted checker was defending, kept: a guessed number on disk
    is indistinguishable from a measured one, so none is written.
    """
    config = _config()
    scaffold.apply(tmp_path, config, plugin_root=REPO_ROOT)
    assert "ci" not in config
    assert not (tmp_path / ".oss.json").exists()


# -------------------------------------------------------------- the tests in CI


def test_a_verified_test_command_that_no_workflow_runs_is_reported(tmp_path):
    _with_workflow(tmp_path, "name: changelog\njobs:\n  fragment:\n    runs-on: ubuntu-latest\n")
    findings = scaffold.check_test_ci(tmp_path, _config(test_command="pytest"))
    assert findings and findings[0]["state"] == "unenforced"
    assert "pytest" in findings[0]["detail"]


def test_a_test_command_a_workflow_runs_is_not_reported(tmp_path):
    """The positive control for the assertion above: it can come back clean."""
    _with_workflow(tmp_path, "jobs:\n  test:\n    steps:\n      - run: pytest\n")
    assert scaffold.check_test_ci(tmp_path, _config(test_command="pytest")) == []


def test_a_workflow_that_mentions_the_runner_but_not_the_command_is_unclear(tmp_path):
    """Third state again: something runs unittest, and it is not this command."""
    _with_workflow(
        tmp_path,
        "jobs:\n  test:\n    steps:\n      - run: python3 -m unittest tests.test_one\n",
    )
    findings = scaffold.check_test_ci(
        tmp_path, _config(test_command="python3 -m unittest discover -s tests")
    )
    assert findings and findings[0]["state"] == "unclear"



@pytest.mark.parametrize(
    "command, expected",
    [
        ("uv run --extra dev pytest -q", "pytest"),
        ("uv run --extra dev pytest tests/ -q -rs", "pytest"),
        ("python -m pytest tests/ -q -rs", "pytest"),
        ("uv run pytest -q", "pytest"),
        ("npx --yes jest --ci", "jest"),
        ("poetry run --directory sub pytest", "pytest"),
    ],
)
def test_runner_token_does_not_return_an_options_value_681(command, expected):
    """#681, reproduced against the shipped function before the fix: a separated
    option value ('dev' from '--extra dev', 'sub' from '--directory sub') came
    back as the runner. All six of the reporter's spellings, run against the
    fixed function, must resolve to the actual test runner.
    """
    assert scaffold._runner_token(command) == expected


def test_runner_token_declines_rather_than_guessing_an_unknown_option_681():
    """The case none of the six spellings cover: an option this function has
    never seen, immediately followed by a value it cannot classify. Guessing
    that value IS the runner is #681's defect; guessing it is NOT (and
    returning whatever follows) is the same guess wearing the other face.
    Decline instead of guessing either way.
    """
    assert (
        scaffold._runner_token("uv run --frobnicate value pytest")
        is scaffold._AMBIGUOUS_RUNNER
    )


def test_check_test_ci_no_longer_false_alarms_on_the_681_reproduction(tmp_path):
    """The reported defect, end to end. The real workflow runs pytest under a
    different exact invocation than test_command. The buggy token ('dev', from
    '--extra dev') does not appear in the workflow text, so the unfixed
    function asserted 'unenforced' -- a claim that nothing runs the tests, made
    because the check went looking for 'dev' instead of 'pytest'.
    """
    _with_workflow(
        tmp_path, "jobs:\n  test:\n    steps:\n      - run: python -m pytest tests/ -q -rs\n"
    )
    findings = scaffold.check_test_ci(
        tmp_path, _config(test_command="uv run --extra dev pytest -q")
    )
    assert findings and findings[0]["state"] == "unclear"
    assert "pytest" in findings[0]["detail"]


def test_check_test_ci_never_asserts_unenforced_off_an_ambiguous_token_681(tmp_path):
    """The 'must not fire' half of the pair below: an unclassifiable token must
    never fall through to 'unenforced', which is a claim about every workflow in
    the repo that this function has not established when it cannot even name
    the runner it is looking for.
    """
    _with_workflow(tmp_path, "jobs:\n  test:\n    steps:\n      - run: pytest\n")
    findings = scaffold.check_test_ci(
        tmp_path, _config(test_command="uv run --frobnicate value pytest")
    )
    assert findings and findings[0]["state"] == "ambiguous"


def test_the_ambiguous_state_never_shadows_an_unreadable_workflow_681(tmp_path):
    """Self-review finding on this issue: the `ambiguous` arm was first written
    ahead of the `unreadable` check, so a workflow directory that could not be
    scanned at all was reported only as 'check this token by hand' -- silently
    dropping the one fact (which path, which cause) #134 exists to carry. An
    unread directory is a fact about the repo and has to survive whatever else
    could not be classified, the same way #124 already reasons about `unclear`.
    """
    _workflow_named_that_will_not_stat(tmp_path, _FORGED_WORKFLOW_NAME)
    findings = scaffold.check_test_ci(
        tmp_path, _config(test_command="uv run --frobnicate value pytest")
    )
    assert findings and findings[0]["state"] == "unreadable"
    assert scaffold.CAUSE_ENTRY_UNSTATTABLE in findings[0]["causes"]


def test_module_flag_with_an_inline_value_is_not_discarded_681():
    """Self-review finding on this issue: the generic 'self-contained, skip it'
    branch for an '=' token ran BEFORE the module-flag check, so
    '--module=pytest' and '-m=pytest' were discarded whole -- the same silent
    misclassification #681 was filed over, just for the '=' spelling of the
    module flag this fix itself introduced special handling for.
    """
    assert scaffold._runner_token("python --module=pytest tests/") == "pytest"
    assert scaffold._runner_token("python -m=pytest") == "pytest"


def test_check_test_ci_still_reports_unenforced_when_the_runner_is_clear_681(tmp_path):
    """The 'must fire' positive control paired with the test above: a command
    whose runner IS clearly determined, and genuinely not run anywhere, must
    still be reported unenforced.
    """
    _with_workflow(
        tmp_path, "name: changelog\njobs:\n  fragment:\n    runs-on: ubuntu-latest\n"
    )
    findings = scaffold.check_test_ci(
        tmp_path, _config(test_command="uv run --extra dev pytest -q")
    )
    assert findings and findings[0]["state"] == "unenforced"


def test_no_test_command_reads_differently_from_one_nothing_runs(tmp_path):
    unknown = scaffold.check_test_ci(tmp_path, _config(test_command=None))
    unenforced = scaffold.check_test_ci(tmp_path, _config(test_command="pytest"))
    assert unknown and unknown[0]["state"] == "unknown"
    assert unenforced and unenforced[0]["state"] == "unenforced"
    assert unknown[0]["detail"] != unenforced[0]["detail"]


def test_the_scaffolded_repo_itself_lands_in_the_unenforced_state(tmp_path):
    """The whole of it: one workflow installed, and it is not the tests."""
    scaffold.apply(tmp_path, _config(test_command="pytest"), plugin_root=REPO_ROOT)
    findings = scaffold.check_test_ci(tmp_path, _config(test_command="pytest"))
    assert findings and findings[0]["state"] == "unenforced"
    assert "green" in findings[0]["detail"]


def test_scaffold_writes_no_test_workflow(tmp_path):
    """Report, do not generate: runner, matrix and language version are unmeasured,
    and a generated wrong answer is read as a measured one.
    """
    scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT)
    workflows = sorted(p.name for p in (tmp_path / ".github" / "workflows").iterdir())
    assert workflows == ["oss-changelog.yml"]


# ------------------------------------------- a filename forging a row of the receipt
#
# #204. A workflow filename is walked out of the MANAGED repository, so it is data. A
# newline in one ends the `tests    ` line and starts the rest at column 0, where it is
# indistinguishable from a row scaffold wrote itself. The payload below is chosen to
# forge the `changelog` row specifically, which is why the "every line begins with a
# known label" assertion further down is NOT on its own enough: the forged line begins
# with a known label too. It is the pair that has teeth.

_FORGED_ROW = "changelog OK: this repo already runs a gate.yml"
_FORGED_WORKFLOW_NAME = "ci.yml could not be read\n" + _FORGED_ROW


def _workflow_named_that_will_not_stat(root, name):
    """Put `name` in the workflow directory in a state the scan reports `unreadable`.

    A measurement, never a given. A newline is a legal POSIX filename character and a
    self-referential symlink is what git actually tracks, but several filesystems
    refuse one or the other, and Windows refuses the symlink without a privilege. Every
    arm that could not establish the condition skips carrying the errno and the
    sentence naming what went untested -- it never asserts against a table of platform
    error codes, and it never asserts on a condition it did not establish.
    """
    directory = root / ".github" / "workflows"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(name, str(directory / name))
    except OSError as exc:
        pytest.skip(
            "this filesystem would not create a self-referential symlink named across "
            "two lines (errno {}, {}): untested here is whether a workflow filename "
            "carrying a newline can forge a row of scaffold's receipt".format(
                exc.errno, type(exc).__name__
            )
        )
    _files, unreadable = scaffold._workflow_scan(root)
    if not any(entry["path"].endswith(name) for entry in unreadable):
        pytest.skip(
            "the symlink was created and this platform still stats it, so the "
            "`unreadable` arm was never reached: untested here is whether a workflow "
            "filename carrying a newline can forge a row of scaffold's receipt"
        )
    return unreadable


def test_a_workflow_filename_with_a_newline_cannot_forge_a_row_of_the_receipt(tmp_path):
    """The harm is a line at column 0 of what `/oss:scaffold` prints, so that is what
    is asserted -- not the return value of a joiner, which would pass over a caller
    that never called it.
    """
    _workflow_named_that_will_not_stat(tmp_path, _FORGED_WORKFLOW_NAME)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        scaffold._print_findings(tmp_path, _config(test_command="pytest", repo=""))
    output = buffer.getvalue()

    # Must fire. The filename is evidence about the repo and the reader needs it: a
    # fix that dropped the name would pass every assertion below and tell a maintainer
    # nothing. It also proves the fixture reached the arm at all.
    assert _FORGED_ROW in output, output

    # Must not fire.
    for line in output.splitlines():
        assert not line.startswith(_FORGED_ROW), output
    labels = {"radar", "tests", "label", "changelog"}
    for line in output.splitlines():
        assert line.split(" ", 1)[0] in labels, output


def test_the_unreadable_detail_is_one_line_for_a_consumer_that_does_not_print(tmp_path):
    """`doctor` renders this same finding from its own row, so the flattening has to be
    in the detail rather than only at scaffold's own print.
    """
    _workflow_named_that_will_not_stat(tmp_path, _FORGED_WORKFLOW_NAME)
    findings = scaffold.check_test_ci(tmp_path, _config(test_command="pytest"))
    assert findings and findings[0]["state"] == "unreadable"
    assert scaffold.CAUSE_ENTRY_UNSTATTABLE in findings[0]["causes"]
    assert len(findings[0]["detail"].splitlines()) == 1, findings[0]["detail"]


# --------------------------------- a rule-layer filename forging a row of the receipt
#
# #223, and the second instance of #204's class in this file in two releases. The names
# in `.claude/jit-context/<dim>/01-oss/` are walked out of the MANAGED repository, so
# they are data. `_layer_scan` joined one into a `remove` row with a bare `.format()`,
# and two print statements -- neither among the four `d02e95a` flattened -- put that row
# on stdout. A newline in the name ends the row and starts whatever follows at column 0,
# where it is indistinguishable from a line scaffold wrote itself. (#223 named three
# prints; the third renders `plan()`'s template rows, whose paths this plugin ships.)
#
# The payload forges the run's own `WROTE:` summary, which is why the "every line begins
# with a known label" assertion is NOT on its own enough on the apply path: `WROTE:` is a
# label the receipt really uses. The teeth are in the pair -- the label sweep, plus
# "exactly one WROTE: line and it is the one reporting what was actually written".
#
# The sweep is deliberately over the WHOLE receipt rather than over the rows the fix
# touches. A per-site fix is what #204 did and it is how this recurred; asserting the
# rendered receipt as a whole is what makes a print statement added next year fail here
# rather than in a release audit.

_FORGED_WROTE = "WROTE: 0 template(s), replaced 0 file(s) in the 01-oss rule layer"
_FORGED_RULE_NAME = "stale.md\n" + _FORGED_WROTE + "\nremoved  everything.md"
_FLAT_RULE_NAME = " ".join(_FORGED_RULE_NAME.split())

_PLAN_LABELS = {
    "create", "replace", "remove", "declined", "present",
    "layer", "tests", "label", "radar", "changelog", "PLAN:", "NOTE",
}
_APPLY_LABELS = {
    "created", "ours", "declined", "removed", "replaced",
    "layer", "tests", "label", "radar", "changelog", "WROTE:", "NOTE",
}


def _rule_layer_file_named(root, name):
    """Put `name` in a managed repo's own rule layer, or skip saying what went untested.

    A measurement, never a given. A newline is a legal POSIX filename character and it
    was constructible on APFS, but several filesystems refuse one and Windows refuses it
    outright. The skip carries the errno and the exception type rather than asserting
    against a table of platform error codes, and the listdir check below is the second
    half of the same rule: a filesystem that stored the name under some other spelling
    never established the condition either.
    """
    directory = root / ".claude" / "jit-context" / "paths" / scaffold.oss_rules.LAYER
    directory.mkdir(parents=True, exist_ok=True)
    try:
        (directory / name).write_text("stale\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        pytest.skip(
            "this filesystem would not create a file named across two lines in the "
            "rule layer (errno {}, {}): untested here is whether a rule-layer filename "
            "carrying a newline can forge a row of scaffold's receipt".format(
                getattr(exc, "errno", None), type(exc).__name__
            )
        )
    if name not in os.listdir(str(directory)):
        pytest.skip(
            "the file was created and this filesystem does not return that name from "
            "listdir, so the newline never reaches the receipt: untested here is "
            "whether a rule-layer filename carrying a newline can forge a row"
        )
    present, _unreadable = scaffold._layer_scan(root, {"paths": {}})
    assert any(entry.endswith(name) for entry in present), present
    return directory


def _receipt(tmp_path, monkeypatch, *extra):
    """Everything the CLI printed, with the one network seam pinned."""
    project, local = oss_config.split(_config())
    (tmp_path / oss_config.CONFIG_NAME).write_text(json.dumps(project), encoding="utf-8")
    (tmp_path / oss_config.LOCAL_CONFIG_NAME).write_text(
        json.dumps(local), encoding="utf-8"
    )
    monkeypatch.setattr(
        scaffold, "_forge_label_names", lambda root, config: ([], "pinned by the test")
    )
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        scaffold._main(
            [
                "--root",
                str(tmp_path),
                "--config",
                str(tmp_path / oss_config.CONFIG_NAME),
            ]
            + list(extra)
        )
    return out.getvalue()


def test_a_rule_layer_filename_with_a_newline_cannot_forge_a_row_of_the_plan(
    tmp_path, monkeypatch
):
    """The plan path: `scripts/scaffold.py --root . --config .oss.json`, no --apply."""
    _rule_layer_file_named(tmp_path, _FORGED_RULE_NAME)
    output = _receipt(tmp_path, monkeypatch)

    # Must fire. The name is the evidence a maintainer needs in order to know what
    # --apply would delete; a fix that dropped it would satisfy every assertion below
    # and tell them nothing. It also proves the fixture reached the removal arm.
    assert _FLAT_RULE_NAME in output, output

    # Must not fire.
    for line in output.splitlines():
        assert not line.startswith("WROTE:"), output
        assert line.split(" ", 1)[0] in _PLAN_LABELS, output


def test_a_rule_layer_filename_with_a_newline_cannot_forge_a_row_of_the_apply_receipt(
    tmp_path, monkeypatch
):
    """The apply receipt, where the forged `WROTE:` landed eleven lines above the real
    one and a reader taking the first was told nothing had been written."""
    _rule_layer_file_named(tmp_path, _FORGED_RULE_NAME)
    output = _receipt(tmp_path, monkeypatch, "--apply")

    # Must fire, twice over: the name survives, and the run's real summary is present.
    assert _FLAT_RULE_NAME in output, output
    wrote = [line for line in output.splitlines() if line.startswith("WROTE:")]
    assert len(wrote) == 1, wrote
    assert wrote[0] != _FORGED_WROTE, output
    assert re.match(
        r"^WROTE: [1-9]\d* template\(s\), replaced [1-9]\d* file\(s\) ", wrote[0]
    ), wrote[0]

    # Must not fire.
    for line in output.splitlines():
        assert line.split(" ", 1)[0] in _APPLY_LABELS, output


def test_every_rule_plan_row_is_one_line_for_a_consumer_that_does_not_print(tmp_path):
    """The invariant both print statements now rely on, asserted on the structure
    rather than on any one caller: a consumer added later inherits it without having to
    remember. Paired with the two receipt tests above, which are what would catch a
    repo-derived value entering the receipt through some other door."""
    _rule_layer_file_named(tmp_path, _FORGED_RULE_NAME)
    rules_plan = scaffold.plan_rules(tmp_path, _config())
    rows = rules_plan["entries"]
    assert any(row["action"] == "remove" for row in rows), rows
    for row in rows:
        assert len(row["path"].splitlines()) == 1, row
        assert len(row["reason"].splitlines()) == 1, row


# ------------------------------------------- collision with an existing changelog gate
#
# #86 / #105: `present` used to be computed per path, not per function. A repo that
# already assembles its own changelog under a different name got a second gate on top
# of it -- two jobs named `fragment`, two assemblers, a check count that moved by one
# with nothing pointing at it.


def test_a_repo_with_no_gate_is_clean(tmp_path):
    """Positive control: nothing installed, nothing detected, the trio still planned
    as replace. Pair with the collision tests below or "declines" would pass on a
    harness that detects nothing at all."""
    assert scaffold.check_changelog_gate(tmp_path, _config()) == []
    paths = {e["path"]: e["action"] for e in scaffold.plan(tmp_path, _config())}
    for name in scaffold.OWNED:
        assert paths[name] == "replace"


def test_another_workflow_running_the_assembler_is_detected(tmp_path):
    _with_workflow(
        tmp_path,
        "name: changelog\njobs:\n  fragment:\n    steps:\n      - run: python3 "
        ".github/scripts/assemble_changelog.py --check --dir changelog.d\n",
        name="changelog.yml",
    )
    findings = scaffold.check_changelog_gate(tmp_path, _config())
    assert findings and findings[0]["state"] == "found"


def test_an_assembler_file_under_a_different_name_is_also_detected(tmp_path):
    """Second signal from #86: a file named assemble_changelog*, with no workflow
    text this scan would otherwise match on."""
    scripts = tmp_path / ".github" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "assemble_changelog.py").write_text("# ours\n", encoding="utf-8")
    findings = scaffold.check_changelog_gate(tmp_path, _config())
    assert findings and findings[0]["state"] == "found"


def test_the_no_changelog_label_reference_in_another_workflow_is_also_detected(tmp_path):
    """Third signal: a workflow that already gates on the same escape-hatch label."""
    _with_workflow(
        tmp_path,
        "name: gate\njobs:\n  check:\n    steps:\n      - if: "
        "\"!contains(github.event.pull_request.labels.*.name, 'no-changelog')\"\n"
        "        run: echo needs a fragment\n",
        name="gate.yml",
    )
    findings = scaffold.check_changelog_gate(tmp_path, _config())
    assert findings and findings[0]["state"] == "found"


def test_our_own_generated_workflow_is_not_mistaken_for_someone_elses_gate(tmp_path):
    """Positive control for the detector itself: re-scaffolding an already scaffolded
    repo must not detect our own file as somebody else's gate, or the trio could
    never be replaced again."""
    scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT)
    assert scaffold.check_changelog_gate(tmp_path, _config()) == []


def test_an_unreadable_workflow_is_unknown_not_none(tmp_path, monkeypatch):
    """Third state: an unreadable workflow is not the same as no other workflow at
    all, and must not render as "none found"."""
    _with_workflow(tmp_path, "name: mystery\n", name="mystery.yml")
    real_read_text = Path.read_text

    def _boom(self, *args, **kwargs):
        if self.name == "mystery.yml":
            raise OSError("permission denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _boom)
    findings = scaffold.check_changelog_gate(tmp_path, _config())
    assert findings and findings[0]["state"] == "unknown"


def test_plan_declines_the_owned_trio_when_a_gate_already_exists(tmp_path):
    _with_workflow(
        tmp_path,
        "name: changelog\njobs:\n  fragment:\n    steps:\n      - run: python3 "
        ".github/scripts/assemble_changelog.py --check\n",
        name="changelog.yml",
    )
    paths = {e["path"]: e["action"] for e in scaffold.plan(tmp_path, _config())}
    for name in scaffold.CHANGELOG_OWNED:
        assert paths[name] == "decline", name


def test_apply_does_not_write_the_owned_trio_when_a_gate_already_exists(tmp_path):
    _with_workflow(
        tmp_path,
        "name: changelog\njobs:\n  fragment:\n    steps:\n      - run: python3 "
        ".github/scripts/assemble_changelog.py --check\n",
        name="changelog.yml",
    )
    result = scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT)
    # The gated files are declined; the ungated ones are still written, which is the
    # split #479 introduced and the reason this is not `replaced == []` any more.
    assert result["replaced"] == sorted(set(scaffold.OWNED) - set(scaffold.CHANGELOG_OWNED))
    assert result["declined"] == sorted(scaffold.CHANGELOG_OWNED)
    assert not (tmp_path / ".oss" / "assemble_changelog.py").exists()
    assert not (tmp_path / ".github" / "workflows" / "oss-changelog.yml").exists()


def test_apply_still_writes_ours_on_a_repo_with_no_existing_gate(tmp_path):
    """Positive control for the assertion above: declining is not the default state
    -- a repo with nothing already there still gets the trio."""
    result = scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT)
    assert result["replaced"] == sorted(scaffold.OWNED)
    assert result["declined"] == []


def test_an_unreadable_workflow_also_blocks_writing_the_trio(tmp_path, monkeypatch):
    """The unknown state must not render as safe to write either -- the risk here is
    one-directional (writing a second gate), so it is treated like a found collision,
    not like none."""
    _with_workflow(tmp_path, "name: mystery\n", name="mystery.yml")
    real_read_text = Path.read_text

    def _boom(self, *args, **kwargs):
        if self.name == "mystery.yml":
            raise OSError("permission denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _boom)
    result = scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT)
    assert result["declined"] == sorted(scaffold.CHANGELOG_OWNED)


def test_force_owned_writes_the_trio_anyway(tmp_path):
    """The explicit override for a maintainer who checked by hand and decided the
    detected match is not a real conflict."""
    _with_workflow(
        tmp_path,
        "name: changelog\njobs:\n  fragment:\n    steps:\n      - run: python3 "
        ".github/scripts/assemble_changelog.py --check\n",
        name="changelog.yml",
    )
    result = scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT, force_owned=True)
    assert result["replaced"] == sorted(scaffold.OWNED)
    assert result["declined"] == []


# ------------------------------------- a directory the process is not allowed to read
#
# #124. Two mechanisms, one theme: the question "did I read this whole tree?" was put
# to calls that discard the answer. `Path.is_dir()` answers True for a directory that
# exists and cannot be entered, and `iterdir()` then raised through doctor's exit code;
# `Path.rglob()` swallows PermissionError while walking and yields nothing for the
# subtree, so `except OSError` around it was a guard that could never fire and could
# never be told from a guard that had nothing to catch.
#
# Every test below pairs the denied arm with a positive control on the *identical*
# tree, differing only in the mode bit -- otherwise "reported unreadable" would pass
# on a harness that reports unreadable for everything.


@contextlib.contextmanager
def _denied(path):
    """Deny reads on ``path``, or skip saying what went untested.

    The mode bit is not assumed to have taken: root ignores it, some filesystems
    ignore it, and Windows' ``os.chmod`` only toggles a read-only attribute that does
    not stop a directory listing. So the deny is *measured* by attempting the exact
    operation the code under test performs. Asserting on a platform's error code from
    a table would report "this platform behaves" for a platform that does not.
    """
    os.chmod(str(path), 0o000)
    try:
        try:
            os.listdir(str(path))
        except PermissionError:
            pass
        except OSError as exc:
            pytest.skip(
                "chmod 000 on {} produced {} (errno {}) rather than a denied listing, so "
                "the unreadable arm could not be set up and went untested".format(
                    path, type(exc).__name__, exc.errno
                )
            )
        else:
            pytest.skip(
                "chmod 000 on {} still allows listing it -- running as root, or a "
                "filesystem/platform that does not enforce the mode bit. The unreadable "
                "arm of this test went untested; the readable control still ran "
                "elsewhere.".format(path)
            )
        yield
    finally:
        os.chmod(str(path), 0o755)


def test_an_unreadable_workflow_directory_is_reported_rather_than_raised(tmp_path):
    """Mechanism 1. The scan must answer, not raise: doctor's contract is one VERDICT
    line and exit 0, and an uncaught PermissionError here took both."""
    _with_workflow(tmp_path, "name: ci\n", name="ci.yml")
    directory = tmp_path / ".github" / "workflows"

    with _denied(directory):
        files, unreadable = scaffold._workflow_scan(tmp_path)
        assert files == []
        assert unreadable, "the denied directory was not reported as unreadable"

    # Positive control, same tree, mode bit restored by the context manager.
    files, unreadable = scaffold._workflow_scan(tmp_path)
    assert [p.name for p in files] == ["ci.yml"]
    assert unreadable == []


def test_the_three_causes_behind_one_unreadable_state_are_each_observed(
    tmp_path, monkeypatch
):
    """The dynamic half of #134, and the one no static pass can do.

    `check_test_ci` emits `unreadable` from ONE site, correctly: all three situations
    below mean "this process could not look", which is the single distinction the
    state carries against `unenforced`, and they share a remedy. What was wrong was
    throwing the distinction away at the point it was recorded -- an entry that would
    not stat and a file that would not read produced a byte-identical detail string
    for the same path, so the reader was told strictly less than the process knew.

    Every cause is driven here and the observed set is compared with what the module
    exports -- in that order. A table checked against a set nobody populated is
    trivially complete, which is the shape this whole file exists to refuse.

    The two entry-level arms are reached by replacing `os.scandir`, not by a mode bit.
    `_denied` skips as root and on any platform that does not enforce the bit, and a
    guard whose only real assertion is "three causes exist" must not be able to skip
    into silence on the legs that matter. The mode-bit path keeps its own test above
    as the real-OS control for cause one.
    """
    _with_workflow(tmp_path, "name: ci\njobs:\n  t:\n    steps:\n      - run: pytest\n")
    config = _config(test_command="pytest")
    observed = {}

    # Positive control first, on the untouched tree: nothing unreadable, no finding.
    # Without it, three "the cause was reported" assertions would still pass against a
    # scan that reported an unreadable file unconditionally.
    files, unreadable = scaffold._workflow_scan(tmp_path)
    assert [p.name for p in files] == ["ci.yml"]
    assert unreadable == []
    assert scaffold.check_test_ci(tmp_path, config) == []

    real_scandir = os.scandir

    class _Entry(object):
        name = "ci.yml"

        def is_file(self):
            raise OSError(13, "cannot stat")

    class _Scan(object):
        def __init__(self, entries):
            self._entries = entries

        def __enter__(self):
            return iter(self._entries)

        def __exit__(self, *exc):
            return False

    # Cause 1: the directory itself will not open.
    monkeypatch.setattr(
        scaffold.os, "scandir", lambda path: _raise(OSError(13, "denied"))
    )
    findings = scaffold.check_test_ci(tmp_path, config)
    assert findings and findings[0]["state"] == "unreadable"
    observed["directory"] = findings[0]

    # Cause 2: the directory opens, one child will not stat.
    monkeypatch.setattr(scaffold.os, "scandir", lambda path: _Scan([_Entry()]))
    findings = scaffold.check_test_ci(tmp_path, config)
    assert findings and findings[0]["state"] == "unreadable"
    observed["entry"] = findings[0]

    # Cause 3: the child stats fine and the file will not read.
    monkeypatch.setattr(scaffold.os, "scandir", real_scandir)
    monkeypatch.setattr(
        Path, "read_text", lambda self, *a, **k: _raise(OSError(13, "denied"))
    )
    findings = scaffold.check_test_ci(tmp_path, config)
    assert findings and findings[0]["state"] == "unreadable"
    observed["file"] = findings[0]

    causes = set()
    for finding in observed.values():
        assert finding["causes"], "an unreadable finding carried no cause at all"
        causes.update(finding["causes"])
    assert causes == set(scaffold.WORKFLOW_SCAN_CAUSES), (
        "the causes observed by driving all three situations are {0}; the module "
        "exports {1}. A cause nobody can reach, or one nobody declared, is the "
        "absence this registry exists to make visible.".format(
            sorted(causes), sorted(scaffold.WORKFLOW_SCAN_CAUSES)
        )
    )
    assert len(causes) == 3, sorted(causes)

    # The pair #134 is actually about: same path, same state, and until now the same
    # bytes. The detail has to tell them apart or the cause was recorded and then
    # discarded one layer further down.
    entry_detail = observed["entry"]["detail"]
    file_detail = observed["file"]["detail"]
    assert scaffold.WORKFLOW_DIR + "/ci.yml" in entry_detail
    assert scaffold.WORKFLOW_DIR + "/ci.yml" in file_detail
    assert entry_detail != file_detail, (
        "an entry that would not stat and a file that would not read still render "
        "identically for the same path"
    )


def _raise(exc):
    raise exc


def test_an_absent_workflow_directory_is_not_unreadable(tmp_path):
    """The third state must not swallow the second: no directory is a fact about the
    repo, an unreadable one is a fact about this process."""
    files, unreadable = scaffold._workflow_scan(tmp_path)
    assert files == []
    assert unreadable == []


# The `check_ci` half of this trio went with the key in #113. `check_test_ci` below
# carries the same conflation guard off the same `_workflow_scan`, so "this process
# could not look" is still tested as distinct from "this repo has no CI".


def test_check_test_ci_does_not_call_a_command_unenforced_over_an_unread_tree(tmp_path):
    """Third instance of the same conflation, downstream of the same scan: "nothing in
    .github/workflows/ runs it" is a measurement, and it was being printed for a
    directory nothing had read."""
    _with_workflow(tmp_path, "name: ci\njobs:\n  t:\n    steps:\n      - run: pytest\n")
    config = _config(test_command="pytest")
    directory = tmp_path / ".github" / "workflows"

    with _denied(directory):
        findings = scaffold.check_test_ci(tmp_path, config)
        assert findings and findings[0]["state"] == "unreadable"
        assert scaffold.WORKFLOW_DIR in findings[0]["detail"]
        assert "could not be read" in findings[0]["detail"]

    # Positive control: readable, the workflow does run the command, so no finding.
    assert scaffold.check_test_ci(tmp_path, config) == []


def test_a_subtree_that_could_not_be_walked_is_unknown_not_none(tmp_path):
    """Mechanism 2, isolated to the mode bit alone. The two arms differ in nothing
    else: same tree, same contents, no assembler anywhere. Denied must be `unknown`
    and readable must be `none`, or "could not read the tree" and "read the whole tree
    and there is no gate" are the same answer -- which is what shipped."""
    private = tmp_path / "private"
    private.mkdir()
    (private / "notes.txt").write_text("nothing to see\n", encoding="utf-8")

    with _denied(private):
        state, detail = scaffold._detect_changelog_gate(tmp_path, _config())
        assert state == "unknown", "an unwalkable subtree reported as {!r}".format(state)
        assert "private" in detail

    assert scaffold._detect_changelog_gate(tmp_path, _config()) == ("none", "")


def test_an_assembler_hidden_behind_a_denied_directory_is_unknown_not_none(tmp_path):
    """The signal exists and is lost to the permission bit alone -- the pair the issue
    measured. Readable finds the assembler; denied must not report a clean repo."""
    private = tmp_path / "private"
    private.mkdir()
    (private / "assemble_changelog.py").write_text("# theirs\n", encoding="utf-8")

    with _denied(private):
        state, _ = scaffold._detect_changelog_gate(tmp_path, _config())
        assert state == "unknown"

    state, detail = scaffold._detect_changelog_gate(tmp_path, _config())
    assert state == "found"
    assert "assemble_changelog.py" in detail


def test_the_trio_is_declined_over_a_tree_that_could_not_be_read(tmp_path):
    """What #86 and #105 said scaffold must never do: write the owned trio into a
    repository whose tree it could not finish reading."""
    private = tmp_path / "private"
    private.mkdir()
    (private / "notes.txt").write_text("nothing to see\n", encoding="utf-8")

    with _denied(private):
        actions = {e["path"]: e["action"] for e in scaffold.plan(tmp_path, _config())}
        for name in scaffold.CHANGELOG_OWNED:
            assert actions[name] == "decline"
        result = scaffold.apply(tmp_path, _config(), plugin_root=REPO_ROOT)
        assert result["declined"] == sorted(scaffold.CHANGELOG_OWNED)
        assert not (tmp_path / ".github" / "workflows" / "oss-changelog.yml").exists()

    # Positive control on the identical tree: readable, the trio is planned as replace.
    actions = {e["path"]: e["action"] for e in scaffold.plan(tmp_path, _config())}
    for name in scaffold.OWNED:
        assert actions[name] == "replace"


def test_skip_dirs_are_pruned_at_every_depth_not_just_the_top(tmp_path):
    """The walk skips node_modules and friends to stay bounded. Matching only the
    first path component left a nested one both walked and reported."""
    nested = tmp_path / "packages" / "app" / "node_modules" / "pkg"
    nested.mkdir(parents=True)
    (nested / "assemble_changelog.js").write_text("// theirs\n", encoding="utf-8")
    assert scaffold._detect_changelog_gate(tmp_path, _config()) == ("none", "")

    # Positive control: the same file outside a skipped directory is still a signal,
    # so the assertion above is not passing because the scan matches nothing at all.
    (tmp_path / "packages" / "app" / "assemble_changelog.js").write_text(
        "// theirs\n", encoding="utf-8"
    )
    state, _ = scaffold._detect_changelog_gate(tmp_path, _config())
    assert state == "found"


def test_a_bytecode_cache_is_not_evidence_that_a_gate_runs(tmp_path):
    """`__pycache__` holds derived content, and the skip list already says derived
    trees are not evidence -- it named `dist` and `build` and missed the Python one.
    The artifact is gitignored in every repo that has one, so it cannot run in anybody
    else's CI, which is the question being asked. It matters on its own and not just as
    inflated detail: delete the source, leave the cache, and the stale `.pyc` declines
    the trio by itself."""
    cache = tmp_path / "scripts" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "assemble_changelog.cpython-311.pyc").write_bytes(b"\x00compiled")
    assert scaffold._detect_changelog_gate(tmp_path, _config()) == ("none", "")

    # Positive control: the source beside it is still a signal, so the assertion above
    # is not passing because nothing under scripts/ is scanned at all.
    (tmp_path / "scripts" / "assemble_changelog.py").write_text("# theirs\n", encoding="utf-8")
    state, detail = scaffold._detect_changelog_gate(tmp_path, _config())
    assert state == "found"
    assert detail.count("assemble_changelog") == 1, detail


def test_a_dangling_symlink_is_not_a_gate_and_a_real_one_still_is(tmp_path):
    """The rglob form filtered matches through `is_file()`, which is False for a
    broken symlink; os.walk hands a broken symlink straight to `filenames`. Restoring
    the filter cannot go back to `is_file()` -- that swallows OSError and would drop an
    unstattable match silently, which is the defect being fixed one level down. One
    stat, and the exception in hand says which of the two it is."""
    link = tmp_path / "assemble_changelog.py"
    try:
        os.symlink(str(tmp_path / "nowhere"), str(link))
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip(
            "could not create a symlink ({}: {}) -- Windows needs the privilege or "
            "developer mode. The dangling-symlink arm went untested; nothing else "
            "covers it.".format(type(exc).__name__, exc)
        )
    assert scaffold._detect_changelog_gate(tmp_path, _config()) == ("none", "")

    # Positive control on the identical name: point it at something that exists and it
    # is a signal again, so the assertion above is not passing because the walk has
    # stopped matching anything at all.
    (tmp_path / "nowhere").write_text("# theirs\n", encoding="utf-8")
    state, detail = scaffold._detect_changelog_gate(tmp_path, _config())
    assert state == "found"
    assert "assemble_changelog.py" in detail


def test_the_paths_a_finding_names_are_separator_stable(tmp_path):
    """Every path in a signal or unreadable list is posix-form, whatever built it.
    They land in one comma-joined sentence, and some came from `str(PurePath)` and some
    from `as_posix()` -- on Windows that renders one list in two conventions."""
    nested = tmp_path / ".github" / "scripts"
    nested.mkdir(parents=True)
    (nested / "assemble_changelog.py").write_text("# theirs\n", encoding="utf-8")
    state, detail = scaffold._detect_changelog_gate(tmp_path, _config())
    assert state == "found"
    assert ".github/scripts/assemble_changelog.py" in detail
    assert "\\" not in detail


# ------------------------------------------------------ --force-owned, in every path
#
# #125. `force_owned` was a parameter of `apply()` alone, so the dry run advised
# passing the flag that had just been passed and `--show` previewed nothing for three
# files it was about to overwrite. `plan()` owns the decision now and `show()` inherits
# it, so one function decides what all three paths report.


def _with_readable_gate(root):
    directory = root / ".github" / "workflows"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "changelog.yml").write_text(
        "name: changelog\njobs:\n  fragment:\n    steps:\n      - run: python3 "
        "tools/assemble_changelog.py --check\n",
        encoding="utf-8",
    )


def test_the_plan_honours_force_owned_and_still_declines_without_it(tmp_path):
    """Both arms, one fixture. Asserting only the forced arm passes if the decline
    logic silently stops working, which would make the flag meaningless."""
    _with_readable_gate(tmp_path)

    forced = {
        e["path"]: e["action"] for e in scaffold.plan(tmp_path, _config(), force_owned=True)
    }
    for name in scaffold.OWNED:
        assert forced[name] == "replace"

    unforced = {e["path"]: e["action"] for e in scaffold.plan(tmp_path, _config())}
    for name in scaffold.CHANGELOG_OWNED:
        assert unforced[name] == "decline"


def test_the_preview_shows_the_three_files_force_owned_is_about_to_overwrite(tmp_path):
    """show() walks plan(), so the empty preview was the same defect one call down.
    A maintainer who forces past a collision previews first; that is the responsible
    move and it was the one that showed nothing."""
    _with_readable_gate(tmp_path)

    forced = {
        path: action
        for path, action, _ in scaffold.show(
            tmp_path, _config(), plugin_root=REPO_ROOT, force_owned=True
        )
    }
    for name in scaffold.OWNED:
        assert forced.get(name) == "replace"

    unforced = {path for path, _, _ in scaffold.show(tmp_path, _config(), plugin_root=REPO_ROOT)}
    for name in scaffold.CHANGELOG_OWNED:
        assert name not in unforced


def test_forcing_past_a_gate_and_forcing_past_an_unreadable_tree_differ(tmp_path):
    """A user who forces past "I saw your gate" is not the user who forces past "I
    could not read your repository". The flag overrides both -- a maintainer with the
    credentials the process lacks is exactly who can settle an unreadable tree, and a
    tool with no override for an environment condition is one people re-run as root.
    But the receipt must record which of the two was overridden, or the third state is
    collapsed at the flag instead of at the walk."""
    _with_readable_gate(tmp_path)
    first = sorted(scaffold.OWNED)[0]
    found_reason = {
        e["path"]: e["reason"] for e in scaffold.plan(tmp_path, _config(), force_owned=True)
    }[first]

    other = tmp_path / "private"
    other.mkdir()
    (other / "notes.txt").write_text("nothing to see\n", encoding="utf-8")
    with _denied(other):
        unknown_reason = {
            e["path"]: e["reason"] for e in scaffold.plan(tmp_path, _config(), force_owned=True)
        }[first]

    assert found_reason != unknown_reason
    assert "could not" in unknown_reason
    assert "private" in unknown_reason


def test_the_changelog_finding_does_not_deny_a_write_force_owned_just_made(tmp_path):
    """`--force-owned --apply` printed "ours (replaced)" and then a finding saying the
    trio "was NOT written". Both lines came from the same run."""
    _with_readable_gate(tmp_path)

    forced = scaffold.check_changelog_gate(tmp_path, _config(), force_owned=True)
    assert forced and "NOT written" not in forced[0]["detail"]
    assert "--force-owned" in forced[0]["detail"]

    unforced = scaffold.check_changelog_gate(tmp_path, _config())
    assert unforced and "NOT written" in unforced[0]["detail"]


def test_doctor_keeps_its_verdict_line_over_an_unreadable_workflow_directory(tmp_path):
    """The contract mechanism 1 broke belongs to doctor.py -- exit 0 always, one
    VERDICT line -- and it broke from a raise three frames away in this module. Run as
    a subprocess so the exit code is the real one."""
    config = {
        "repo": "owner/name",
        "default_branch": "main",
        "branch_pattern": "fix/{issue}",
        "test_command": "pytest",
        "version_sites": ["README.md"],
        "changelog_dir": "changelog.d",
        "docs_targets": ["README.md"],
        "labels": {"priority": [], "lanes": []},
        "ci": {"required_checks": 0},
    }
    local = {
        "clone": str(tmp_path),
        "worktree_root": str(tmp_path / "wt"),
        "state_file": ".max/oss-watch.json",
    }
    (tmp_path / ".oss.json").write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / ".oss.local.json").write_text(json.dumps(local), encoding="utf-8")
    _with_workflow(tmp_path, "name: ci\n", name="ci.yml")

    with _denied(tmp_path / ".github" / "workflows"):
        done = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "doctor.py"), "--root", str(tmp_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        assert done.returncode == 0, done.stdout[-2000:]
        assert "VERDICT" in done.stdout, done.stdout[-2000:]


# ------------------------------------------------- finding the config from a worktree


def _git(args, cwd):
    done = subprocess.run(
        ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"] + args,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    assert done.returncode == 0, "git {}: {}".format(" ".join(args), done.stdout)
    return done.stdout


def _clone_with_worktree(tmp_path):
    """A real clone and a real git worktree of it.

    Not a subdirectory dressed up as one: a worktree's `.git` is a *file* pointing at
    the clone's git dir, and a walk upward that works on a plain subdirectory can
    still fail here.
    """
    clone = tmp_path / "clone"
    clone.mkdir()
    _git(["init", "-q"], clone)
    _git(["symbolic-ref", "HEAD", "refs/heads/main"], clone)
    (clone / "README.md").write_text("seed\n", encoding="utf-8")
    _git(["add", "README.md"], clone)
    _git(["commit", "-qm", "seed"], clone)
    worktree = tmp_path / "wt" / "53"
    _git(["worktree", "add", "-q", "-b", "fix/53", str(worktree)], clone)
    assert (worktree / ".git").is_file(), "fixture is not a worktree"
    return clone, worktree


def _write_config(directory, **overrides):
    project, local = oss_config.split(_config(**overrides))
    (directory / oss_config.CONFIG_NAME).write_text(json.dumps(project), encoding="utf-8")
    (directory / oss_config.LOCAL_CONFIG_NAME).write_text(json.dumps(local), encoding="utf-8")


def test_a_worktree_reads_the_clones_config_instead_of_reporting_none(
    tmp_path, monkeypatch, capsys
):
    """The documented invocation, run where a developer actually stands."""
    clone, worktree = _clone_with_worktree(tmp_path)
    _write_config(clone)
    monkeypatch.chdir(worktree)

    assert scaffold._main(["--root", ".", "--config", ".oss.json"]) == 0
    out = capsys.readouterr().out
    assert "Run /oss:setup" not in out, "the wrong remedy for a repo that has a config"
    assert str(clone) in out, "where the config came from is not printed"


def test_a_config_in_the_worktree_still_wins(tmp_path, monkeypatch):
    """Positive control for the search above: it must not reach past a local file."""
    clone, worktree = _clone_with_worktree(tmp_path)
    _write_config(clone, repo="owner/clone-half")
    _write_config(worktree, repo="owner/worktree-half")
    monkeypatch.chdir(worktree)

    resolved, origin, _ = oss_config.resolve_config_path(".oss.json")
    assert origin == "here"
    assert Path(resolved).resolve().parent == worktree.resolve()


def test_no_config_anywhere_does_not_read_like_one_found_in_the_clone(
    tmp_path, monkeypatch, capsys
):
    """Third state. The clone was checked and has none -- say so, and say where."""
    clone, worktree = _clone_with_worktree(tmp_path)
    monkeypatch.chdir(worktree)

    assert scaffold._main(["--root", ".", "--config", ".oss.json"]) == 1
    out = capsys.readouterr().out
    assert "Run /oss:setup" in out, "here the remedy really is to write one"
    assert str(clone) in out, "a search naming no clone reads as a search that did not run"


def test_a_directory_in_no_repository_says_it_could_not_look(tmp_path, monkeypatch, capsys):
    """The state this repo is named after: git could not answer, so the message must
    not claim there is no enclosing clone."""
    loose = tmp_path / "loose"
    loose.mkdir()
    monkeypatch.chdir(loose)

    assert scaffold._main(["--root", ".", "--config", ".oss.json"]) == 1
    out = capsys.readouterr().out
    assert "Run /oss:setup" in out
    assert "No enclosing clone could be checked" in out, "an unanswerable search must say so"
    assert "Not in the enclosing clone" not in out, (
        "a search that could not run must not render as a search that came back empty"
    )


def test_standing_in_the_clone_itself_says_so_rather_than_naming_it(
    tmp_path, monkeypatch, capsys
):
    """A clone is its own enclosing clone. Reporting "not in the enclosing clone at
    <here>" would send the reader looking one directory up for a directory they are
    already standing in."""
    clone, _ = _clone_with_worktree(tmp_path)
    monkeypatch.chdir(clone)

    assert scaffold._main(["--root", ".", "--config", ".oss.json"]) == 1
    out = capsys.readouterr().out
    assert "This directory is the clone" in out
    assert "Not in the enclosing clone" not in out


def test_the_three_origins_are_distinguishable(tmp_path, monkeypatch):
    clone, worktree = _clone_with_worktree(tmp_path)
    monkeypatch.chdir(worktree)

    resolved, origin, detail = oss_config.resolve_config_path(".oss.json")
    assert (resolved, origin) == (None, "missing")
    assert str(clone) in detail

    _write_config(clone)
    resolved, origin, _ = oss_config.resolve_config_path(".oss.json")
    assert origin == "clone"
    assert Path(resolved).resolve() == (clone / oss_config.CONFIG_NAME).resolve()

    _write_config(worktree)
    _, origin, _ = oss_config.resolve_config_path(".oss.json")
    assert origin == "here"


def test_a_config_under_a_directory_absent_here_is_still_found_in_the_clone(
    tmp_path, monkeypatch
):
    """`configs/.oss.json` excluded the same way leaves no `configs/` in the worktree.
    Asking git from a directory that does not exist fails to start the subprocess, and
    "git could not answer" is the wrong sentence about a repo git answers about fine."""
    clone, worktree = _clone_with_worktree(tmp_path)
    (clone / "configs").mkdir()
    _write_config(clone / "configs")
    monkeypatch.chdir(worktree)
    assert not (worktree / "configs").exists(), "fixture no longer covers the case"

    resolved, origin, detail = oss_config.resolve_config_path("configs/.oss.json")
    assert origin == "clone", detail
    assert Path(resolved).resolve() == (clone / "configs" / oss_config.CONFIG_NAME).resolve()


def test_one_line_defuses_an_ansi_escape_that_would_repaint_the_terminal():
    """#228: `_one_line` folded whitespace but let a control byte through.

    `str.split()` splits on whitespace only, so an ESC-led ANSI sequence -- which
    contains none -- survived flattening intact and could repaint the surrounding
    receipt (colour, cursor movement, erase-in-line) during interactive review,
    without ever breaking the line-structure guarantee #204/#223 established.

    Asserted on the actual rendered bytes, not on line structure: a check for
    "no line starts with a known label" cannot see this, because the harm here
    is what the terminal does with the bytes on one line, not a second line.
    """
    forged = "evil\x1b[31mRED\x1b[0m.txt"
    flattened = scaffold._one_line(forged)
    assert "\x1b" not in flattened, (
        "the ESC byte must not reach the receipt -- it is what lets a filename "
        "repaint the terminal around it"
    )

    # Must-fire pair: the escape is neutralised.
    assert "\x1b[31m" not in flattened and "\x1b[0m" not in flattened

    # Must-NOT-fire pair, in the same fixture: the evidence a maintainer needs to
    # judge a deletion is not destroyed along with the escape. A function that
    # neutralised everything, including the filename, would also pass the
    # assertions above -- this is what tells the two apart.
    assert "evil" in flattened and "RED" in flattened and ".txt" in flattened


def test_join_names_defuses_an_ansi_escape_too():
    """`_join_names` calls `_one_line` per name -- the same defence, one caller over."""
    names = ["plain.txt", "evil\x1b[31mRED\x1b[0m.txt"]
    joined = scaffold._join_names(names)
    assert "\x1b" not in joined
    assert "plain.txt" in joined and "evil" in joined and "RED" in joined


def test_print_row_receipt_bytes_carry_no_escape_byte(capsys):
    """The actual printed bytes of a receipt row, not a claim about the function.

    `_print_row` is what a maintainer's terminal receives. Asserting on its
    captured stdout, rather than only on `_one_line`'s return value, is the
    difference between "the function is safe" and "the receipt is safe" --
    the issue's own distinction between a line-structure guarantee and a
    rendering one.
    """
    scaffold._print_row("radar", {"detail": "evil\x1b[31mRED\x1b[0m.txt"})
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert "evil" in out and "RED" in out

    # The pair: ordinary text is printed unchanged, so the assertions above are
    # about the escape and not about `_print_row` mangling everything it touches.
    capsys.readouterr()
    scaffold._print_row("radar", {"detail": "ordinary-file.txt"})
    assert capsys.readouterr().out.strip() == "radar    ordinary-file.txt"


def test_an_absolute_config_path_is_never_widened(tmp_path, monkeypatch):
    """A path somebody typed in full is an answer, not a starting point."""
    clone, worktree = _clone_with_worktree(tmp_path)
    _write_config(clone)
    monkeypatch.chdir(worktree)

    resolved, origin, detail = oss_config.resolve_config_path(worktree / ".oss.json")
    assert (resolved, origin) == (None, "missing")
    assert str(clone) not in detail

def test_the_owned_file_count_in_the_doc_matches_scaffold_owned():
    """#487's second, smaller instance: `commands/scaffold.md` said "the last three"
    while `scaffold.OWNED` (the table it is describing) already had four entries --
    `.oss/statusline.py` landed in #479 and the sentence was never updated. Derived
    from `scaffold.OWNED` itself, so a fifth owned file added later fails this test
    instead of silently going stale the same way.
    """
    doc = (REPO_ROOT / "commands" / "scaffold.md").read_text(encoding="utf-8")
    match = re.search(r"The last (\w+) are ours", doc)
    assert match, 'expected a "The last <N> are ours" sentence in commands/scaffold.md'
    words = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
    assert match.group(1) == words[len(scaffold.OWNED)], (
        "commands/scaffold.md says {!r} owned files; scaffold.OWNED has {}".format(
            match.group(1), len(scaffold.OWNED)
        )
    )
