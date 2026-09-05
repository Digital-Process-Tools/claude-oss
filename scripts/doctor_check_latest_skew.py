"""``check_latest_skew`` -- doctor cross-references the status line's cached
`latest` for this repo against the newest published version read live (#551).

Two mechanisms in this plugin answer "am I current", from different sources on
different clocks: `check_auto_update` (`scripts/doctor_check_auto_update.py`)
reads `plugin_update`'s own receipt, and the status line caches a manifest-version
reading refreshed on `statusline.LATEST_REFRESH_AFTER`. When the status line
rendered a stale `ahead` marker for this plugin on 2026-08-25, `doctor` was run
twice during the investigation and said nothing about it -- it answered a
different, true question (`OK auto-update: oss already current`) from a
different source, and nothing compared the two. This check is that comparison.

Follows the #497 relocation convention: reaches every shared name through
`import doctor` rather than `from doctor import name`, so a test that
monkeypatches `doctor.<name>` still reaches code called from here, and this
module is imported back into `doctor.py` immediately after its own definition.

Must never repair. `doctor`'s contract is diagnose, exit 0, one VERDICT line --
a diagnostic that clears or refreshes the cache here destroys the evidence of
the skew this line exists to report, and the reader loses the ability to
re-read it. Considered and rejected explicitly (#551). Nothing below writes to
the cache file; `read_text` is the only I/O this module performs against it.

Read through `statusline.cache_path`/`cache_dir` rather than re-derived here
(#551's own note): two copies of that path is a fact about one machine living
in two places, and they drift.
"""

import json
import time

import doctor

try:
    import statusline
except ImportError:  # pragma: no cover - the module sits beside this file
    statusline = None


def _age_text(stamp, now):
    if not isinstance(stamp, (int, float)):
        return "no stamp"
    return "{}s old".format(int(max(0.0, now - stamp)))


def _is_plugin_source_repo(project_dir, repo):
    """Is `repo` one of the source repositories `statusline.refresh()` can ever
    write a `latest` reading for -- an installed plugin's own manifest-declared
    `repository`, resolved for this project (#615)?

    `refresh()`'s `latest` map is keyed by ``repo_from_url(record["repository"])``
    for each of ``installed_plugins(project_dir)``'s entries -- nothing else ever
    populates it. A managed repo that is not itself an installed plugin can never
    appear there, so asking whether the cache carries a reading for it is asking a
    question the cache can never answer, no matter how many times it refreshes.
    """
    for record in statusline.installed_plugins(project_dir).values():
        if statusline.repo_from_url(record.get("repository")) == repo:
            return True
    return False


def check_latest_skew(project_dir, config, now=None):
    """Compare the status line's cached `latest` for this repo against the
    newest published version read live.

    States, in this repository's usual shape:

    * ``OK`` -- the cache agrees with the live read. The stamp is reported
      anyway: a fresh agreement and an hour-old one are not the same evidence.
    * ``WARN`` -- they differ. Both values and the cache's age are named. This
      is a report about the *cache*, not a fault in the repo.
    * ``WARN ... could not be determined`` -- no cache file, an unreadable one,
      one that parses to the wrong shape, one carrying no reading for this
      repo *while it is one of the repositories the cache could carry a
      reading for*, or a live read that did not answer. Never folded into
      agreement, on the same reasoning as #216: the distinction between "no
      cache exists" and "a cache exists and could not be read" is worth
      keeping separate.
    * ``not-checked`` (via ``doctor.unmeasured``) -- no declared `repo`,
      `scripts/statusline.py` could not be imported, or `repo` does not
      appear among the installed plugins' own source repositories, so the
      cache's `latest` map cannot be assumed to carry a reading for it
      (#615). That last reason is deliberately hedged, not asserted as
      settled fact: `installed_plugins()` swallows a read failure on its own
      `installed_plugins.json` to `{}`, the identical shape as "no plugin
      installed at all", so this branch cannot tell "genuinely not a plugin
      source repo" from "the registry could not be read" and must not claim
      the former. Answers nothing about the repository itself, so it must
      not render as either state above.

    ``now`` is a parameter, defaulting to ``time.time()``, so a test can drive
    the age comparison without a real clock.
    """
    now = time.time() if now is None else now
    if statusline is None:
        doctor.unmeasured(
            "latest skew", "not checked -- scripts/statusline.py could not be imported"
        )
        return
    if not isinstance(config, dict) or not config.get("repo"):
        doctor.unmeasured("latest skew")
        return
    repo = config["repo"]
    path = statusline.cache_path(repo)
    # The cache's own DIRECTORY is named below, not the resolved file path -- the
    # file's basename is `statusline.cache_path`'s own slug of `repo` (every
    # non-alphanumeric character folded to `-`), the identical transform
    # `bin/oss-workspace` applies when it derives a watch-channel name from the
    # same config key for an unrelated purpose. Naming the full path here would
    # put that derived slug into this diagnostic's own text, which a caller
    # asserting the launcher derived nothing cannot tell apart from the launcher
    # having derived it -- not a claim about the repo, a collision between two
    # unrelated derivations of the one input.
    cache_dir = statusline.cache_dir()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        doctor.report(
            "WARN",
            "latest skew: could not be determined -- no cache for {} under {} "
            "(the status line has not run yet here, or writes to a different "
            "XDG_CACHE_HOME than this process).".format(repo, cache_dir),
        )
        return
    except OSError as exc:
        doctor.report(
            "WARN",
            "latest skew: could not be determined -- the cache for {} under {} "
            "could not be read ({}: {}).".format(
                repo, cache_dir, type(exc).__name__, exc
            ),
        )
        return
    try:
        document = json.loads(raw)
    except ValueError as exc:
        doctor.report(
            "WARN",
            "latest skew: could not be determined -- the cache for {} under {} "
            "did not parse ({}: {}).".format(repo, cache_dir, type(exc).__name__, exc),
        )
        return
    if not isinstance(document, dict):
        doctor.report(
            "WARN",
            "latest skew: could not be determined -- the cache for {} under {} "
            "is not a JSON object.".format(repo, cache_dir),
        )
        return
    cached_by_repo = document.get("latest")
    cached = cached_by_repo.get(repo) if isinstance(cached_by_repo, dict) else None
    age = _age_text(document.get("latest_fetched_at"), now)
    if cached is None:
        if not _is_plugin_source_repo(project_dir, repo):
            # Hedged rather than categorical (a real gap the auditor found on
            # review, #620/#615 bundle): `installed_plugins()` swallows a read
            # failure on `installed_plugins.json` to `{}`, the identical shape
            # as "no plugin is installed at all" -- this branch cannot tell
            # "genuinely not a plugin source repo" from "the registry could
            # not be read", so it must not assert the former as settled fact.
            doctor.unmeasured(
                "latest skew",
                "not checked -- {} does not appear among the installed "
                "plugins' own source repositories, so the status line's "
                "`latest` cache cannot be assumed to carry a reading for it "
                "(`refresh()` only ever writes readings for installed "
                "plugins; this is also what an unreadable installed-plugins "
                "registry would look like from here).".format(repo),
            )
            return
        doctor.report(
            "WARN",
            "latest skew: could not be determined -- the cache under {} carries "
            "no `latest` reading for {}.".format(cache_dir, repo),
        )
        return
    live = statusline._latest_release(repo)
    if live is None:
        doctor.report(
            "WARN",
            "latest skew: could not be determined -- the live read for {} did "
            "not answer (`gh` not on PATH, not authenticated, or the call "
            "failed); the cache says {} ({}).".format(repo, cached, age),
        )
        return
    if statusline._version_tuple(cached) == statusline._version_tuple(live):
        doctor.report(
            "OK",
            "latest skew: cache agrees with the live read for {} -- {} ({}).".format(
                repo, cached, age
            ),
        )
        return
    doctor.report(
        "WARN",
        "latest skew: cache says {} ({}), the live read says {} -- the status "
        "line's plugin-currency marker for {} may be off until its own refresh "
        "catches up. This is a report about the cache, not a fault in the "
        "repo.".format(cached, age, live, repo),
    )
