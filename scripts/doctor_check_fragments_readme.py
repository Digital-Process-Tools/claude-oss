"""``check_fragments_readme`` -- moved out of ``scripts/doctor.py`` (#497).

`doctor.py` keeps `main()`, the check registry and the shared contract (exit 0
always, one VERDICT line, `report()` / `unmeasured()`); this module holds one
check, its own private helper and constant, and nothing else. Every shared
name -- `report`, `unmeasured`, `NO_SCAFFOLD`, `oss_config`, `_safe_is_file`,
`_os_error_detail` -- is reached through `doctor` imported as a module
(`import doctor`), never `from doctor import name`, the same reason spelled
out in full in `scripts/doctor_check_statusline.py`: a name looked up this way
is always the current value in `doctor`'s own namespace, which is what keeps
a test's `monkeypatch.setattr(doctor, ...)` reaching code that used to be
inline in `doctor.py`.

`doctor.py` imports `check_fragments_readme` back out of this module
immediately after this docstring's own code is defined, so
`doctor.check_fragments_readme` keeps answering exactly as it did before the
move -- a pure relocation, not a rewrite; see #497.
"""

from pathlib import Path

import doctor

#: The literal template line scaffold's fragments-README writes for a `removed`
#: fragment (#259). `release_version.py` quotes this same text in its own refusal, so
#: matching it here rather than a looser pattern means "documents the bullet" answers
#: the identical question that refusal already asks.
COMPATIBILITY_BULLET = "- Compatibility: breaking|compatible - <reason>"


def _fragments_directory(project_dir, config):
    """The changelog fragments directory this repo actually uses, or ``None`` when
    nothing here can name one.

    Mirrors `release_version._fragment_dir`'s resolution for the config-file half
    (`--dir` on a command line is that function's own first arm and has no
    equivalent here): an explicit, valid `changelog_dir` wins; a null or invalid
    one falls through to `oss_config.scaffolded_changelog_gate`, which reads the
    directory back out of the scaffolded gate workflow on disk rather than
    guessing the default. A `changelog_dir` that fails validation returns `None`
    here rather than silently trying the default -- the value is broken, not
    absent, and a directory picked in its place would be one nobody named.
    """
    named = config.get("changelog_dir")
    if isinstance(named, str) and named.strip():
        if doctor.oss_config.changelog_dir_problem(named):
            return None
        return Path(project_dir) / named
    state, detail = doctor.oss_config.scaffolded_changelog_gate(project_dir)
    if state == "present":
        return Path(project_dir) / doctor.oss_config.DEFAULT_FRAGMENTS_DIR
    if state == "present-other-dir":
        return Path(project_dir) / detail
    # `absent` (never adopted), `unknown` (the gate could not be read),
    # `present-refused-dir` (the gate names a directory that cannot be used) and
    # `present-bare-dir` (a `--dir` flag on disk with no argument) all resolve to
    # "nothing to check" here, deliberately collapsed rather than given the four
    # distinct refusal messages `release_version._fragment_dir` returns for them:
    # those exist to steer a release-blocking failure with a remedy per cause,
    # and this is a non-blocking diagnostic whose only obligation on this arm is
    # "do not warn" -- one directory-not-found answer satisfies all four.
    return None


def check_fragments_readme(project_dir, config):
    """Does `<changelog_dir>/README.md` document the Compatibility bullet a `removed`
    fragment must carry (#260)?

    `scripts/release_version.py` already refuses a `removed` fragment with no
    compatibility verdict and quotes the required bullet in full, so nobody is
    stranded by this alone -- they are sent to a document that may be silent, with
    the answer already on their screen. This converts *discovered at the moment a
    release stops* into *reported before it does*.

    Why a `doctor` check and not a `scaffold` fix: the fragments README is a
    DEFAULT under this repository's ownership contract (see CLAUDE.md's "Three
    ownership contracts") -- created once when absent, then the repo's own forever.
    Scaffold's template gained the Compatibility section in #259, but a repo
    scaffolded before that change already carries the old file, and re-running
    `/oss:scaffold` will not deliver the new section to it: a default is never
    replaced, or the promise that a decision somebody made is never overwritten
    breaks. The only mechanism that can reach a repository already carrying the old
    file is one that REPORTS -- same shape as #205.

    Three states, and the third is load-bearing:

    * the file exists and carries the bullet -- OK.
    * the file exists and does not -- WARN, and the remedy must say
      `/oss:scaffold` will NOT fix it, because naming a command that declines to
      act reads as a fix and performs nothing (the `misdirects` row).
    * the file is absent or unreadable -- most repos have no fragment practice at
      all, so this is the ORDINARY state. It must not render as a finding (that
      would WARN on nearly every scaffolded repo) and the wording must not read as
      a verified pass either, so it reports OK with "not checked" in the text --
      the same shape `jit_index_drift`'s undecidable-and-untouched arm uses, and
      for the identical reason: "not a finding" only if the state doesn't say so.

    The directory is never just `config.get("changelog_dir")` or-else-the-default:
    a null `changelog_dir` is ambiguous between "never adopted fragments" and
    "adopted through scaffold's own fallback, which does not always pick the
    default directory" (#325). `release_version._fragment_dir` resolves that
    ambiguity by reading the directory back out of the scaffolded gate workflow
    on disk when the key is null, and this check reuses the exact same
    `oss_config.scaffolded_changelog_gate` lookup -- otherwise a repo whose
    `changelog_dir` was set at scaffold time and later nulled (legal; the key is
    in `NULLABLE_KEYS`) would have this check silently look at `changelog.d/`
    while the actual, gated, `removed`-fragment-refusing directory sits
    elsewhere entirely.
    """
    if config is None:
        doctor.unmeasured("fragments readme")
        return
    if doctor.oss_config is None:
        doctor.unmeasured("fragments readme", doctor.NO_SCAFFOLD)
        return
    directory = _fragments_directory(project_dir, config)
    if directory is None:
        doctor.report(
            "OK",
            "fragments readme: changelog_dir names no directory this run could "
            "resolve -- the ordinary state for a repo with no fragment practice, "
            "and not a finding on its own.",
        )
        return
    path = directory / "README.md"
    if not doctor._safe_is_file(path):
        doctor.report(
            "OK",
            "fragments readme: {} absent -- the ordinary state for a repo with no "
            "fragment practice, and not a finding on its own.".format(path),
        )
        return
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        doctor.report(
            "OK",
            "fragments readme: {} unreadable -- {}, so the Compatibility bullet "
            "could not be checked.".format(path, doctor._os_error_detail(exc)),
        )
        return
    if COMPATIBILITY_BULLET in text:
        doctor.report(
            "OK", "fragments readme: {} documents the Compatibility bullet".format(path)
        )
        return
    # The diagnostic clause above names `path` -- a file on disk -- and stays
    # absolute whenever `project_dir` is (which `scripts/doctor.sh` and
    # `CLAUDE_PROJECT_DIR` both produce). The remedy clause names a
    # `scaffold.show` argument instead, and `scaffold.show` matches by string
    # equality against REPO-RELATIVE template keys (`fragments_dir(config) +
    # "/README.md"`) -- so quoting the same absolute `path` there named a
    # command that fails everywhere except `--root .` (#438). `relative_to`
    # can only fail if `directory` ever escaped `project_dir`, which
    # `_fragments_directory` never returns; the `except` exists so a future
    # change to that invariant degrades to the pre-#438 (broken-under-abs-root)
    # message rather than raising out of a diagnostic that must always exit 0.
    try:
        shown_path = path.relative_to(Path(project_dir)).as_posix()
    except ValueError:
        shown_path = str(path)
    doctor.report(
        "WARN",
        "fragments readme: {} exists and does not document `{}`, which "
        "`scripts/release_version.py` requires on a `removed` fragment. "
        "/oss:scaffold will not fix it -- the file is a default and is never "
        "replaced once it exists. Paste the section by hand from "
        "`scripts/scaffold.py --show {}`.".format(
            path, COMPATIBILITY_BULLET, shown_path
        ),
    )
