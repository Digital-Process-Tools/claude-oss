"""Link and image destinations in a changelog fragment are checked, not waved through.

`scan_fragment_body` refuses headings, raw HTML, unclosed fences and link-reference
definitions, because every one of those has been used to inject content into a released
`CHANGELOG.md`. It never looked at where a link or an image *points*, and the file is
vendored byte-for-byte into every scaffolded repo, so the gap shipped outward.

Two escapes are pinned here, and the second is the reason the fix is not the obvious one:

1. An image destination is a fetch. `![](https://evil.example/pixel.gif)` is a valid https
   URL and a beacon that fires for every reader of the changelog.
2. markdown-it's own `validateLink` refuses `javascript:` and leaves the source as literal
   text, so under the stock parser there is *no* `link_open` token to inspect. Walking
   tokens with a scheme allowlist and a stock parser would therefore refuse nothing at all
   for exactly the payload that motivated the check, while looking like it worked. The
   scanner parses with link validation disabled so that every destination CommonMark
   syntax produces is visible to the allowlist, and decides by name itself.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import assemble_changelog as ac  # noqa: E402

NAME = "999.fixed.md"


def _scan(body):
    return ac.scan_fragment_body(NAME, body)


def _one(body):
    findings = _scan(body)
    assert findings, "expected a refusal for:\n" + body
    return "\n".join(findings)


# --- refused -------------------------------------------------------------------------

def test_javascript_link_is_refused():
    """The payload the audit named. There is no `link_open` token for it under a stock
    parser, so a token walk alone does not see this one."""
    message = _one("- fixed the thing [x](javascript:alert(1))\n")
    assert "javascript" in message
    assert NAME in message


def test_entity_obfuscated_javascript_link_is_refused():
    """`java&#115;cript:` is `javascript:` after the parser decodes entities. Pinned
    because it is the case a destination regex would miss and the parser cannot."""
    message = _one("- fixed the thing [x](java&#115;cript:alert(1))\n")
    assert "javascript" in message


def test_uppercase_scheme_is_refused():
    assert _scan("- a [x](JAVASCRIPT:alert(1))\n")


def test_vbscript_and_file_links_are_refused():
    assert _scan("- a [x](vbscript:msgbox(1))\n")
    assert _scan("- a [x](file:///etc/passwd)\n")


def test_protocol_relative_link_is_refused():
    """`//evil.example/x` carries no scheme but is not local. Classifying `no scheme` as
    `relative` without this case would allow a remote destination through the allowlist."""
    message = _one("- a [x](//evil.example/x)\n")
    assert "evil.example" in message or "//" in message


def test_remote_image_is_refused_though_https_is_an_allowed_link_scheme():
    """The asymmetry, stated as a test: the same URL is allowed as a link and refused as
    an image, because an image is fetched without anyone deciding to fetch it."""
    body_image = "- fixed the thing ![](https://evil.example/pixel.gif)\n"
    body_link = "- fixed the thing [shot](https://evil.example/pixel.gif)\n"
    message = _one(body_image)
    assert "evil.example" in message
    assert _scan(body_link) == [], "an https *link* must stay allowed"


def test_remote_image_refusal_says_how_to_show_an_image():
    """A refusal that does not say what to write instead is a wall, not a guard."""
    message = _one("- a ![shot](https://user-images.githubusercontent.com/1/a.png)\n")
    assert "relative" in message.lower()


def test_data_image_is_refused_by_name():
    """Not remote, and refused anyway: an opaque unbounded blob in a file whose diff is
    the review. Named separately so the message is not `not on the allowlist`."""
    message = _one("- a ![](data:image/png;base64,iVBORw0KGgo=)\n")
    assert "data:" in message


def test_javascript_link_reference_definition_indented_under_a_bullet_is_refused():
    """A second escape from the same cause. A definition whose destination the parser
    refuses is never registered in `env['references']`, so the existing link-ref refusal
    never saw it; indented under a bullet the structural rule does not fire either, and
    the fragment passed `--check` clean."""
    assert _scan("- a\n\n  [lbl]: javascript:alert(1)\n")


def test_javascript_autolink_is_refused():
    assert _scan("- a <javascript:alert(1)>\n")


# --- allowed -------------------------------------------------------------------------

def test_relative_link_is_allowed():
    assert _scan("- see [the docs](./docs/releasing.md) for the order\n") == []


def test_root_relative_and_anchor_links_are_allowed():
    assert _scan("- see [x](/docs/releasing.md) and [y](#unreleased)\n") == []


def test_relative_image_is_allowed():
    assert _scan("- a ![the board](./docs/img/board.png)\n") == []


def test_http_and_https_links_are_allowed():
    assert _scan("- see [spec](https://spec.commonmark.org/0.31.2/)\n") == []
    assert _scan("- see [spec](http://example.com/x)\n") == []


def test_mailto_link_is_allowed():
    """Pinned deliberately: a security fragment pointing at a disclosure address is a real
    use, and `mailto:` opens a composer rather than fetching anything."""
    assert _scan("- report to [security](mailto:security@example.com)\n") == []


def test_https_autolink_is_allowed():
    assert _scan("- see <https://spec.commonmark.org/>\n") == []


# --- the rule is not over-broad ------------------------------------------------------

@pytest.mark.parametrize(
    "fragment",
    sorted(p for p in (REPO_ROOT / "changelog.d").glob("*.md") if p.name != "README.md"),
    ids=lambda p: p.name,
)
def test_every_fragment_in_this_repo_still_passes(fragment):
    """The negative control. A URL rule wide enough to refuse the repo's own pending
    fragments would be discovered at release time, by the release."""
    assert ac.scan_fragment_body(fragment.name, fragment.read_text(encoding="utf-8")) == []


# --- the second layer, over the assembled file ---------------------------------------

def test_verify_written_reports_a_destination_the_release_added():
    """`_verify_written` is the backstop for a per-fragment guard that has been wrong
    three times. It checked structure only, so it confirmed the file gained no headings
    while a destination went through underneath that confirmation."""
    before = "# Changelog\n\n## [Unreleased]\n"
    after = "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- a ![](https://evil.example/p.gif)\n"
    findings = ac._verify_written(before, after, ["### Fixed"], [])
    assert findings, "the assembled file gained a remote image and the verifier said nothing"
    assert "evil.example" in "\n".join(findings)


def test_verify_written_is_a_delta_and_not_a_whole_file_scan():
    """CHANGELOG.md's preamble already links out, and a release rewrites compare URLs.
    A verifier that re-judged the whole file would refuse every release forever."""
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert ac._verify_written(text, text, [], []) == []


def test_verify_written_destination_check_is_load_bearing(monkeypatch):
    """Would this test still pass if the implementation did nothing? Answered by making
    it do nothing: with the destination survey stubbed out, the assertion above fails."""
    monkeypatch.setattr(ac, "_disallowed_destinations", lambda text: ac.Counter())
    before = "# Changelog\n\n## [Unreleased]\n"
    after = "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- a ![](https://evil.example/p.gif)\n"
    assert ac._verify_written(before, after, ["### Fixed"], []) == []


# --- the receipt says what was established -------------------------------------------

def test_ok_receipt_states_that_destinations_were_checked(capsys, tmp_path):
    """The defect underneath the defect: a checker that closes every other hole in a
    class silently is read as closing the class. Nothing in the output said URLs were
    never looked at, so nothing has to change for that to be true again."""
    (tmp_path / "42.fixed.md").write_text("- named the thing (#42)\n", encoding="utf-8")
    assert ac.check(tmp_path) == ac.OK
    summary = capsys.readouterr().out
    assert "destination" in summary, (
        "the ok receipt does not mention link and image destinations -- a maintainer "
        "reading it cannot tell whether they were checked:\n" + summary
    )


def test_the_readme_example_body_still_passes():
    body = ("- The tag pattern is inferred from tags that already exist and stays null "
            "when none are recognised.\n")
    assert _scan(body) == []
