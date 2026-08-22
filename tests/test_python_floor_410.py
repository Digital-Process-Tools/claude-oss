"""The declared Python floor, and every site that has to agree with it (#410).

Nothing in this repository stated which Python versions it supports. The only floor
that existed was the CI matrix in `.github/workflows/tests.yml`, and **a matrix is a
statement about what is tested, not about what is supported.** The two were read as
one everywhere, including by a README badge that has claimed `python-3.9+` for this
project's whole life without anything behind it.

The absence was not inert. The `fix/398` lane declined to harden `doctor.sh`'s
sentinel probe with a `sys.version_info` gate, and the reason it gave was exactly
this: adding one would convert a working 3.8 install into `VERDICT: could not run`
on the strength of a fact this project had never stated.

## What was measured before the floor was declared

`>=3.9` is a decision, not a derivation, and it is only honest if the code does not
already require something newer. Measured at `abccde3` over all 132 tracked `.py`
files:

* **Syntax.** Every file parses under `ast.parse(..., feature_version=(3, 7))`. No
  match statement, no `except*`, no positional-only-parameter or walrus construct
  above 3.7. `python3.11 -m compileall scripts tests bin` exits 0, which additionally
  rules out any PEP 701 f-string that only 3.12 can tokenise.
* **Annotations.** Zero subscripted builtin generics (`list[str]`) and zero `X | Y`
  annotations anywhere -- the modules use `typing.List` / `typing.Optional`. Every
  `|` in the tree is a set, `re` flag or `stat` mode union; none is a dict merge.
* **Standard library.** No `tomllib`, `zoneinfo`, `graphlib`, `functools.cache`,
  `importlib.resources.files`, `contextlib.chdir`, `Path.walk`, `datetime.UTC`,
  `itertools.pairwise` or any other post-3.9 name. Every `walk` is `os.walk` or
  `ast.walk`; every `chdir` is `monkeypatch.chdir`.

So the code is portable well below 3.9 and the floor is a support decision rather
than a technical bound. It is set at 3.9 because 3.9 is the oldest version anything
here has ever been demonstrated on.

## Source and derived

**Source: `pyproject.toml`'s `[project].requires-python`.** It is the only
standardised, machine-readable place a Python project states this, so a tool that
was never told about this repository can still read it. `[project]` deliberately
carries no `version` key: `oss_config.VERSION_CANDIDATES` probes exactly
`[project] version` and would otherwise propose `pyproject.toml` as a fifth version
site that nothing in `.oss.json` maintains.

**Derived, and derived means "checked here" rather than "computed":** a workflow
matrix, a shields.io badge and a shell `for` list cannot read a manifest key at parse
time. So the agreement is a test, and these are the four sites:

* the CI matrix's lowest entry;
* the README support badge;
* the `Python X.Y compatible` line eight modules under `scripts/` carry in their
  docstrings;
* the oldest explicit `python3.N` in `doctor.sh`'s candidate walk.

`scripts/assemble_changelog.py` is deliberately not swept. It is the one vendored
file left, it spells the claim differently (`this file runs on 3.9`), and it is
upstream's document about upstream's repository -- pinning this repository's floor
into it would be the trap `CLAUDE.md` names about vendored copies.

## Not passing vacuously

Every comparison below runs through `_disagreements`, and that function is driven by
fixtures in both directions: a set of sites that agree must produce nothing, and a
set that diverges must produce a sentence naming the site. A test that only read the
real files would pass against a `_disagreements` that returns `[]` unconditionally.
Each real site additionally asserts that it *found* something to compare, because an
empty survey and a clean survey are the same `[]`.

Python 3.9 compatible.
"""

import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"
README = REPO_ROOT / "README.md"
DOCTOR_SH = REPO_ROOT / "scripts" / "doctor.sh"

try:
    import yaml
except ImportError:  # pragma: no cover - exercised by the guard test below
    yaml = None


# --------------------------------------------------------------------------- #
# Reading the source
# --------------------------------------------------------------------------- #

#: `requires-python` is read with a hand-rolled scan rather than `tomllib`, which is
#: 3.11+ while this file must run on the floor it is asserting. `scripts/oss_config.py`
#: reaches for the same shape and gives the same reason.
_REQUIRES_RE = re.compile(r"""^requires-python\s*=\s*["'](.+?)["']\s*(?:#.*)?$""")

#: Deliberately only `>=X.Y`. An upper bound or a compatible-release operator is a
#: different declaration with different consequences, and it should arrive with a
#: reader that understands it rather than be silently truncated to its first clause.
_SPEC_RE = re.compile(r"\A>=(\d+)\.(\d+)\Z")


def _requires_python_spec():
    """The raw `requires-python` string, or None with the reason it is None."""
    try:
        text = PYPROJECT.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - the manifest is tracked
        return None, "{} could not be read ({})".format(PYPROJECT, exc)
    section = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().strip('"')
            continue
        if section != "project":
            continue
        match = _REQUIRES_RE.match(stripped)
        if match:
            return match.group(1), ""
    return None, "no `requires-python` key under a `[project]` table in {}".format(PYPROJECT)


def declared_floor():
    """The floor as `(major, minor)`. Fails the calling test when it is not declared."""
    spec, why_not = _requires_python_spec()
    assert spec is not None, (
        "The Python floor is not declared: " + why_not + ".\n"
        "This repository's CI matrix is not a support statement, and #410 is what "
        "happens when the two are read as one -- a fix to scripts/doctor.sh was "
        "declined for want of a floor nobody had stated. Add\n"
        "    [project]\n"
        '    requires-python = ">=3.9"\n'
        "to pyproject.toml, and no `version` key beside it, or oss_config's version "
        "probe will start proposing pyproject.toml as a version site."
    )
    match = _SPEC_RE.match(spec)
    assert match is not None, (
        "requires-python is {!r}, and this file only reads the `>=X.Y` form. An upper "
        "bound or a `~=` operator changes what the sites below have to agree with, so "
        "it needs a reader that understands it rather than one that silently keeps "
        "the first clause.".format(spec)
    )
    return (int(match.group(1)), int(match.group(2)))


def _show(version):
    return "{}.{}".format(*version)


# --------------------------------------------------------------------------- #
# The comparison, as a pure function so it can be driven both ways
# --------------------------------------------------------------------------- #


def _disagreements(floor, sites):
    """One sentence per site whose version is not the floor.

    `sites` maps a human-readable site name to a `(major, minor)` tuple. Returning
    sentences rather than a bool is the point: a site that has drifted is only
    actionable if the failure says which one, and to what.
    """
    findings = []
    for name in sorted(sites):
        found = sites[name]
        if found != floor:
            findings.append(
                "{}: says Python {}, but the declared floor is {}. One of the two is "
                "stale; pyproject.toml's requires-python is the source.".format(
                    name, _show(found), _show(floor)
                )
            )
    return findings


def test_disagreements_is_silent_when_the_sites_agree():
    """The must-not-fire half. Alone it also passes against a function that never fires."""
    assert _disagreements((3, 9), {"a": (3, 9), "b": (3, 9)}) == []


def test_disagreements_names_the_site_that_drifted():
    """The must-fire half, and the positive control for every assertion below."""
    findings = _disagreements((3, 9), {"agrees": (3, 9), "drifted": (3, 10)})
    assert len(findings) == 1, findings
    assert "drifted" in findings[0]
    assert "3.10" in findings[0] and "3.9" in findings[0]


def test_disagreements_is_silent_on_an_empty_survey_and_that_is_why_sites_are_counted():
    """`[]` from nothing looked at and `[]` from everything agreeing are the same value.

    So every real check below asserts that it *found* its site before comparing it.
    This test exists to pin the reason those assertions are there.
    """
    assert _disagreements((3, 9), {}) == []


# --------------------------------------------------------------------------- #
# The source itself
# --------------------------------------------------------------------------- #


def test_the_floor_is_declared():
    floor = declared_floor()
    assert floor[0] == 3, "a Python 2 floor is not a thing this project supports"


def test_pyproject_declares_no_version_beside_the_floor():
    """A `version` under `[project]` would become a version site nothing maintains.

    `scripts/oss_config.py`'s `VERSION_CANDIDATES` probes `pyproject.toml` for exactly
    `[project] version`, and `.oss.json`'s `version_sites` names four other files. A
    fifth that `/oss:release` does not bump is a stale version reading as a real one.
    """
    text = PYPROJECT.read_text(encoding="utf-8")
    section = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().strip('"')
            continue
        if section == "project" and re.match(r"^version\s*=", stripped):
            raise AssertionError(
                "pyproject.toml now carries `[project] version`. oss_config's probe "
                "will report it as a version site, .oss.json does not list it, and so "
                "/oss:release will not bump it. Either add it to version_sites or take "
                "it out."
            )


# --------------------------------------------------------------------------- #
# Derived site 1: the CI matrix
# --------------------------------------------------------------------------- #


def test_the_parser_this_file_needs_is_present_on_ci():
    """A skipped file and a clean file are the same tick, so CI must not skip this one."""
    if yaml is not None:
        return
    if os.environ.get("CI") == "true":
        pytest.fail(
            "pyyaml is not importable and CI=true, so the matrix half of #410 did not "
            "run on a runner. The pytest job installs it; if that line changed, this "
            "file went quiet rather than red."
        )
    pytest.skip("pyyaml is not installed here; the workflow installs it on CI")


needs_yaml = pytest.mark.skipif(yaml is None, reason="pyyaml is not installed here")


def _matrix_versions():
    """Every `python-version` entry of the pytest job, as `(major, minor)` tuples.

    Parsed, not matched. A regex over a workflow is the shape that keeps passing while
    the workflow is broken -- `tests/test_shell_leg_budget_303.py` says the same thing
    about the same file.
    """
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    entries = document["jobs"]["pytest"]["strategy"]["matrix"]["python-version"]
    versions = []
    for entry in entries:
        match = re.match(r"\A(\d+)\.(\d+)\Z", str(entry))
        assert match, (
            "matrix entry {!r} is not an `X.Y` version. YAML reads a bare 3.10 as the "
            "float 3.1, which is why these are quoted in the workflow.".format(entry)
        )
        versions.append((int(match.group(1)), int(match.group(2))))
    return versions


@needs_yaml
def test_the_matrix_has_entries_to_compare():
    """The must-fire control for the test below: an empty matrix agrees with everything."""
    versions = _matrix_versions()
    assert len(versions) >= 2, (
        "the pytest matrix has {} python-version entry/entries, so the floor "
        "comparison below is asserting almost nothing".format(len(versions))
    )


@needs_yaml
def test_the_matrix_floor_is_the_declared_floor():
    floor = declared_floor()
    versions = _matrix_versions()
    findings = _disagreements(floor, {"the CI matrix's lowest entry": min(versions)})
    assert not findings, "\n".join(findings) + (
        "\n\nThe matrix is what the code is demonstrated on and requires-python is "
        "what it promises. They are allowed to be different questions and not "
        "different answers: a floor CI never runs is a promise nothing checks, and a "
        "leg below the floor tests a version the project says it does not support."
    )


# --------------------------------------------------------------------------- #
# Derived site 2: the README badge
# --------------------------------------------------------------------------- #

_BADGE_RE = re.compile(r"badge/python-(\d+)\.(\d+)%2B")


def test_the_readme_badge_states_the_declared_floor():
    """The badge claimed `3.9+` before anything declared it. Now it has a source."""
    floor = declared_floor()
    match = _BADGE_RE.search(README.read_text(encoding="utf-8"))
    assert match is not None, (
        "the README's python support badge was not found by {}. If the badge moved or "
        "changed shape this check went quiet rather than red.".format(_BADGE_RE.pattern)
    )
    found = (int(match.group(1)), int(match.group(2)))
    findings = _disagreements(floor, {"the README support badge": found})
    assert not findings, "\n".join(findings)


# --------------------------------------------------------------------------- #
# Derived site 3: the `Python X.Y compatible` docstring lines
# --------------------------------------------------------------------------- #

_DOCSTRING_RE = re.compile(r"Python (\d+)\.(\d+) compatible")


def _docstring_claims():
    """Every `Python X.Y compatible` claim under `scripts/`, as `{path: version}`."""
    claims = {}
    for path in sorted((REPO_ROOT / "scripts").glob("*.py")):
        if path.name == "assemble_changelog.py":
            # The one vendored file left. It is upstream's document about upstream's
            # repository and spells the claim differently on purpose; pinning this
            # repository's floor into it is the vendoring trap CLAUDE.md names.
            continue
        match = _DOCSTRING_RE.search(path.read_text(encoding="utf-8"))
        if match:
            claims["scripts/" + path.name] = (int(match.group(1)), int(match.group(2)))
    return claims


def test_the_docstring_claims_were_actually_found():
    """The must-fire control: an empty sweep agrees with every floor there is."""
    claims = _docstring_claims()
    assert len(claims) >= 5, (
        "{} module(s) under scripts/ carry a `Python X.Y compatible` line, and eight "
        "did at abccde3. Either the convention was dropped -- in which case delete "
        "this check rather than let it pass on nothing -- or {} has stopped "
        "matching.".format(len(claims), _DOCSTRING_RE.pattern)
    )


def test_every_docstring_claim_states_the_declared_floor():
    floor = declared_floor()
    findings = _disagreements(floor, _docstring_claims())
    assert not findings, "\n".join(findings)


# --------------------------------------------------------------------------- #
# Derived site 4: doctor.sh's interpreter walk
# --------------------------------------------------------------------------- #

_CANDIDATE_LINE_RE = re.compile(r"^\s*for candidate in (python3.*?); do\s*$", re.MULTILINE)


def _doctor_sh_explicit_minors():
    """The explicit `python3.N` candidates in `doctor.sh`'s fallback walk."""
    text = DOCTOR_SH.read_text(encoding="utf-8")
    match = _CANDIDATE_LINE_RE.search(text)
    assert match is not None, (
        "doctor.sh's `for candidate in python3 ...` line was not found by {}. The walk "
        "moved or changed shape, so this check went quiet rather than "
        "red.".format(_CANDIDATE_LINE_RE.pattern)
    )
    return [
        (int(m.group(1)), int(m.group(2)))
        for m in re.finditer(r"\bpython(\d+)\.(\d+)\b", match.group(1))
    ]


def test_doctor_sh_offers_explicit_minors_at_all():
    """The must-fire control: a walk with no explicit minor has no oldest to compare."""
    minors = _doctor_sh_explicit_minors()
    assert len(minors) >= 4, (
        "doctor.sh's walk carries {} explicit `python3.N` candidate(s); it carried six "
        "at abccde3, spanning the CI band and two above it".format(len(minors))
    )


def test_doctor_sh_walks_down_to_the_declared_floor_and_no_further():
    """The oldest interpreter the launcher will look for is the oldest one supported.

    Below the floor is a version this project makes no promise about, and offering it
    would have the launcher select an interpreter nothing has ever run the suite on.
    Above the floor is a supported version the launcher would fail to find when it is
    the only one installed under an explicit name.

    Note what this is not: a *gate*. #398's lane declined to add a
    `sys.version_info >= floor` refusal to the sentinel probe, and declaring the floor
    does not make that obligatory -- the reasoning is in this issue's pull request.
    This asserts the shape of a fallback list, not a rejection of anything the machine
    offers.
    """
    floor = declared_floor()
    minors = _doctor_sh_explicit_minors()
    findings = _disagreements(
        floor, {"doctor.sh's oldest explicit python3.N candidate": min(minors)}
    )
    assert not findings, "\n".join(findings)
