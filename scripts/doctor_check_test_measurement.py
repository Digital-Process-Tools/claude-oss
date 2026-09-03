"""``check_test_measurement`` -- does the maintainer attest that this repo's own
pytest run measures what it needs to measure (#932)?

A scaffolded repo has no signal telling a maintainer whether their suite carries
`--durations` (so a slow test is visible without CI archaeology, the shape #925/
#926 hit) and a coverage flag. #932 asks for a maintainer ATTESTATION rather than
a derived fact -- `test_measurement_configured` in `.oss.json`, a plain boolean
set once a maintainer has confirmed their own `addopts` (or `pytest.ini` /
`setup.cfg`) carries both. Nothing here parses that file for the two flags: the
issue is explicit that checking the boolean's truth would turn "not yet
verified" into a second kind of drift the moment somebody spells a flag this
parser does not recognise, and deriving it would also make the check silently
narrower than the next flag pytest grows.

Checked before any of the three states below: is `test_command` even
pytest-shaped (#946)? `.oss.json`'s `test_command` is an arbitrary shell
command -- `npm test`, `go test ./...`, `cargo test` are all valid -- and this
check's advice is pytest-specific, so a *set* `test_command` that plainly
names a different runner short-circuits straight to `OK: not applicable`
before any of the three states below are reached. An absent/empty
`test_command` is not evidence either way and falls through to them exactly
as before -- see `_looks_pytest_shaped`.

Three states below that, following CLAUDE.md's own three-state rule -- ok /
finding / unknown, never collapsed:

* `true`, and some pytest-config-shaped file in this repo can actually be
  read -- OK. This is a minimal sanity floor, not a content check: it answers
  "is there anywhere this attestation could plausibly live", never "does that
  file actually carry `--durations` and a coverage flag".
* absent or `false` -- a finding, naming what to add and where.
* `true`, but no pytest-config-shaped file could be read at all -- `unknown`,
  never a silently-cleared `OK`: an attestation that cannot be corroborated
  even this far is not the same fact as one that was confirmed.

Every shared name -- `report`, `unmeasured`, `NO_CONFIG` -- is reached through
`doctor` imported as a module (`import doctor`), never `from doctor import
name`, the convention `scripts/doctor_check_statusline.py` spells out in full:
a name looked up this way is always the current value in `doctor`'s own
namespace, which is what keeps a test's `monkeypatch.setattr(doctor, ...)`
reaching this code.

Python 3.9 compatible.
"""

from pathlib import Path

import doctor

#: Files that could carry pytest's own config. Not pytest's real resolution
#: order (`pytest.ini` always wins there over the others) -- this only needs
#: a plausible file to name back in the OK line or in the remedy, not to
#: reproduce pytest's own precedence.
_PYTEST_CONFIG_FILES = ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini")


def _pytest_config_file(repo_root):
    """``(path, detail)`` -- the first pytest-config-shaped file in this repo
    that can actually be read, or ``(None, detail)`` naming what was tried.

    This never inspects the file's CONTENT for `--durations` or a coverage
    flag -- see the module docstring for why. It only asks whether there is a
    plausible file to point a maintainer at, or to name back in an OK line.
    """
    root = Path(repo_root)
    tried = []
    for name in _PYTEST_CONFIG_FILES:
        candidate = root / name
        try:
            if not candidate.is_file():
                tried.append("{}: not found".format(name))
                continue
            candidate.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            tried.append("{}: {}".format(name, exc))
            continue
        return candidate, ""
    return None, "; ".join(tried)


def _looks_pytest_shaped(test_command):
    """Is `test_command` evidence this repo runs pytest, or at least not
    evidence against it (#946 review finding on #932)?

    This check's advice -- `--durations`, `--cov`, `pyproject.toml`'s
    `addopts` -- is pytest-specific, but `.oss.json`'s `test_command` is
    documented (`scripts/oss_config.py`) as an arbitrary shell command:
    `npm test`, `go test ./...`, `cargo test` are all valid values, and for
    any of those this check firing pytest advice is simply wrong for that
    project -- CLAUDE.md's own governing rule (a fact about one repository,
    or here one *language*, baked into shared code) one level down.

    An absent or empty `test_command` is not evidence either way -- it means
    nobody has probed it, not that the repo isn't Python -- so it stays
    pytest-shaped by default and this check keeps firing exactly as it did
    before this function existed. Only a *set* `test_command` that plainly
    names a different runner turns this off.
    """
    if not test_command:
        return True
    return "pytest" in test_command.lower()


def check_test_measurement(project_dir, config):
    """One line, in every state -- see the module docstring.

    `project_dir` is the repository being diagnosed, not this plugin's own
    tree -- the pytest config this check looks for is the diagnosed repo's
    own suite, never this plugin's.
    """
    if config is None:
        doctor.unmeasured("test measurement (--durations + coverage)")
        return
    test_command = config.get("test_command")
    if not _looks_pytest_shaped(test_command):
        doctor.report(
            "OK",
            "test_measurement_configured: not applicable -- test_command "
            "({!r}) does not look pytest-shaped, so this pytest-specific "
            "attestation (--durations + coverage via addopts) does not "
            "apply here. Nothing else in this check is skipped -- only the "
            "pytest-specific advice.".format(test_command),
        )
        return
    attested = config.get("test_measurement_configured")
    if attested is not True:
        doctor.report(
            "WARN",
            "test_measurement_configured: {} in .oss.json -- pytest is not "
            "attested as measuring test duration and coverage. Add "
            "`--durations=25` (or similar) and a coverage flag (e.g. `--cov`) "
            "to this repo's own pytest config -- `pyproject.toml`'s "
            "`[tool.pytest.ini_options] addopts`, or `pytest.ini` / "
            "`setup.cfg` -- then set `\"test_measurement_configured\": true` "
            "in .oss.json. `--durations=25` plus a `pytest-cov` addopts entry "
            "is one plausible shape, not the only one. No threshold or trend "
            "check is implied -- this only makes the measurement exist and "
            "be visible.".format(
                "false" if attested is False else "absent"
            ),
        )
        return
    path, detail = _pytest_config_file(project_dir)
    if path is None:
        doctor.report(
            "WARN",
            "test_measurement_configured: true, but no pytest-config-shaped "
            "file ({}) could be read in this repository to corroborate it -- "
            "{}. Not reported OK, which would clear a gap nobody actually "
            "looked at.".format(", ".join(_PYTEST_CONFIG_FILES), detail),
        )
        return
    try:
        shown = path.relative_to(Path(project_dir)).as_posix()
    except ValueError:  # pragma: no cover - path is built from project_dir
        shown = path.name
    doctor.report(
        "OK",
        "test_measurement_configured: true, and {} is readable here. This "
        "does not check what `addopts` (or equivalent) actually says -- it "
        "is a maintainer attestation, not a derived fact.".format(shown),
    )
