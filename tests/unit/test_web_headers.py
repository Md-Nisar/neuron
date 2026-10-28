"""Reference headers for hosting `web/dist` (`scripts/web_headers.py`) and the web source's
conformance to them (ADR 0010, decision 7)."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from scripts import web_headers
from scripts.web_headers import HeaderConfigError

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
API = "https://api.example.com"
ISSUER = "https://id.example.com/realms/neuron"
DEV_API = "http://127.0.0.1:8000"
DEV_ISSUER = "http://localhost:8180/realms/neuron"


def directives(policy: str) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    for part in policy.split(";"):
        name, *values = part.split()
        assert name not in parsed, f"duplicate directive {name}"
        parsed[name] = values
    return parsed


def csp(**kwargs: object) -> dict[str, list[str]]:
    return directives(web_headers.content_security_policy(api_origin=API, issuer=ISSUER, **kwargs))  # type: ignore[arg-type]


class TestPolicy:
    def test_nothing_is_allowed_unless_listed(self) -> None:
        assert csp()["default-src"] == ["'none'"]

    @pytest.mark.parametrize("name", ["script-src", "style-src", "img-src", "font-src"])
    def test_resources_come_from_this_origin_only(self, name: str) -> None:
        assert csp()[name] == ["'self'"]

    def test_no_directive_allows_inline_eval_data_blob_wildcards_or_whole_schemes(self) -> None:
        for name, values in csp().items():
            for value in values:
                assert "unsafe" not in value, (name, value)
                assert value not in {"*", "data:", "blob:", "http:", "https:", "ws:", "wss:"}, (
                    name,
                    value,
                )
                assert "*" not in value, (name, value)
                assert not value.startswith("'nonce-") and not value.startswith("'sha"), (
                    name,
                    value,
                )

    def test_the_browser_may_talk_only_to_the_api_and_the_identity_provider(self) -> None:
        policy = csp()

        assert policy["connect-src"] == [API, "https://id.example.com"]
        assert policy["frame-src"] == ["'self'", "https://id.example.com"]

    def test_one_origin_is_listed_once(self) -> None:
        policy = directives(
            web_headers.content_security_policy(
                api_origin="https://x.example", issuer="https://x.example/realms/a"
            )
        )

        assert policy["connect-src"] == ["https://x.example"]

    def test_framing_is_limited_to_this_origin_for_silent_renew(self) -> None:
        """Silent renew loads this app inside a frame of itself, so 'none' would break it."""
        assert csp()["frame-ancestors"] == ["'self'"]

    @pytest.mark.parametrize("name", ["base-uri", "form-action", "object-src", "worker-src"])
    def test_unused_capabilities_are_off(self, name: str) -> None:
        assert csp()[name] == ["'none'"]

    def test_https_deployments_upgrade_insecure_requests_and_development_does_not(self) -> None:
        assert "upgrade-insecure-requests" in csp()
        dev = directives(
            web_headers.content_security_policy(
                api_origin=DEV_API, issuer=DEV_ISSUER, development=True
            )
        )
        assert "upgrade-insecure-requests" not in dev
        assert dev["connect-src"] == [DEV_API, "http://localhost:8180"]


class TestOrigins:
    @pytest.mark.parametrize(
        "value",
        [
            "https://a.example; script-src *",
            "https://a.example, https://evil.example",
            "https://a.example 'unsafe-inline'",
            'https://a.example"',
            "https://*.example.com",
            "*",
            "https://a.example/path",
            "https://a.example?x=1",
            "https://a.example#f",
            "https://user:pw@a.example",
            "https://a.example\r\nSet-Cookie: x=1",
            "https://bücher.example",
            "javascript:alert(1)",
            "data:text/html,x",
            "//a.example",
            "a.example",
            "",
            "https://-bad.example",
            "https://a.example:99999",
        ],
    )
    def test_values_that_could_change_the_policy_are_refused(self, value: str) -> None:
        with pytest.raises(HeaderConfigError):
            web_headers.origin_of(value)

    def test_plain_http_is_refused_except_on_loopback_in_development(self) -> None:
        with pytest.raises(HeaderConfigError):
            web_headers.origin_of("http://a.example")
        with pytest.raises(HeaderConfigError):
            web_headers.origin_of("http://127.0.0.1:8000")
        with pytest.raises(HeaderConfigError):
            web_headers.origin_of("http://a.example", development=True)
        assert (
            web_headers.origin_of("http://127.0.0.1:8000", development=True)
            == "http://127.0.0.1:8000"
        )
        assert web_headers.origin_of("http://[::1]:8000", development=True) == "http://[::1]:8000"

    def test_the_issuer_path_is_dropped_to_its_origin_but_the_api_must_be_a_bare_origin(
        self,
    ) -> None:
        assert web_headers.origin_of(ISSUER, allow_path=True) == "https://id.example.com"
        assert (
            web_headers.origin_of("https://id.example.com:8443/realms/x", allow_path=True)
            == "https://id.example.com:8443"
        )
        assert web_headers.origin_of("https://api.example.com/") == "https://api.example.com"
        with pytest.raises(HeaderConfigError):
            web_headers.origin_of(ISSUER)
        with pytest.raises(HeaderConfigError):
            web_headers.content_security_policy(
                api_origin="https://api.example.com/v1", issuer=ISSUER
            )

    def test_the_command_line_refuses_without_printing_a_header(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        status = web_headers.main(
            ["--api-origin", "https://a.example; img-src *", "--issuer", ISSUER]
        )

        assert status == 2
        assert capsys.readouterr().out == ""


class TestHeaders:
    def test_the_full_set_is_present(self) -> None:
        headers = web_headers.security_headers(api_origin=API, issuer=ISSUER)

        assert (
            headers["Referrer-Policy"] == "no-referrer"
        )  # the callback URL carries a one-time code
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "SAMEORIGIN"
        assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
        assert headers["Cross-Origin-Resource-Policy"] == "same-origin"
        assert headers["Strict-Transport-Security"].startswith("max-age=")
        for feature in ("camera", "microphone", "geolocation", "payment", "usb"):
            assert f"{feature}=()" in headers["Permissions-Policy"]

    def test_hsts_is_not_sent_in_development(self) -> None:
        headers = web_headers.security_headers(
            api_origin=DEV_API, issuer=DEV_ISSUER, development=True
        )

        assert "Strict-Transport-Security" not in headers

    def test_the_html_is_revalidated_and_hashed_assets_are_immutable(self) -> None:
        assert web_headers.CACHE_RULES["/index.html"] == "no-cache"
        assert "immutable" in web_headers.CACHE_RULES["/assets/*"]


class TestFormats:
    headers = web_headers.security_headers(api_origin=API, issuer=ISSUER)

    def test_json_round_trips(self) -> None:
        loaded = json.loads(web_headers.render_json(self.headers))

        assert loaded["headers"] == self.headers
        assert loaded["cache"] == web_headers.CACHE_RULES

    def test_headers_file_round_trips(self) -> None:
        text = web_headers.render_headers_file(self.headers)
        block = text.split("/index.html")[0].splitlines()[1:]
        parsed = dict(line.strip().split(": ", 1) for line in block)

        assert text.startswith("/*\n")
        assert parsed == self.headers
        assert "/assets/*\n  Cache-Control: public, max-age=31536000, immutable" in text

    def test_every_nginx_location_carries_the_whole_set_because_add_header_does_not_inherit(
        self,
    ) -> None:
        text = web_headers.render_nginx(self.headers)
        blocks = re.findall(r"location [^{]+\{(.*?)\n\}", text, re.DOTALL)

        assert len(blocks) == 3
        for body in blocks:
            for name, value in self.headers.items():
                assert f'add_header {name} "{value}" always;' in body, name
        assert 'add_header Cache-Control "no-cache" always;' in blocks[0]
        assert "immutable" in blocks[1]
        assert "Cache-Control" not in blocks[2]


# --- the web source conforms to the policy -------------------------------------------------


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.problems: list[str] = []
        self.scripts = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        names = {name for name, _ in attrs}
        values = dict(attrs)
        if tag == "script":
            self.scripts += 1
            if values.get("type") != "module" or not (values.get("src") or "").startswith("/"):
                self.problems.append("script must be a same-origin module")
        if tag in {"style", "base", "object", "embed", "iframe", "form"}:
            self.problems.append(f"<{tag}> not allowed")
        if tag == "link" and "href" in names and not (values.get("href") or "").startswith("/"):
            self.problems.append("link must be same-origin")
        if tag == "meta" and (values.get("http-equiv") or "").lower() in {
            "refresh",
            "content-security-policy",
        }:
            self.problems.append("meta http-equiv not allowed")
        for name in names:
            if name.startswith("on") or name == "style":
                self.problems.append(f"inline {name} attribute on <{tag}>")

    def handle_data(self, data: str) -> None:
        pass


def test_index_html_has_no_inline_script_style_or_handler_and_loads_only_this_origin() -> None:
    page = _Page()
    page.feed((WEB / "index.html").read_text(encoding="utf-8"))

    assert page.problems == []
    assert page.scripts == 1


def _source_files() -> list[Path]:
    return [
        path
        for path in sorted((WEB / "src").rglob("*.ts*"))
        if ".test." not in path.name and "test" not in path.relative_to(WEB / "src").parts[:1]
    ]


def test_the_source_to_check_is_really_there() -> None:
    names = {path.name for path in _source_files()}

    assert {"main.tsx", "session.ts", "client.ts", "Markdown.tsx", "ApprovalCard.tsx"} <= names
    assert len(names) > 25


_FORBIDDEN = [
    r"dangerouslySetInnerHTML",
    r"\.innerHTML\b",
    r"\.outerHTML\b",
    r"insertAdjacentHTML",
    r"document\.write",
    r"\beval\s*\(",
    r"new\s+Function\b",
    r"set(Timeout|Interval)\(\s*[\"'`]",
    r"sendBeacon",
    r"XMLHttpRequest",
    r"\bWebSocket\b",
    r"\bEventSource\b",
    r"importScripts",
    r"serviceWorker",
    r"new\s+(Shared)?Worker\b",
    r"new\s+Image\b",
    r"createElement\(\s*[\"'`](script|img|link|embed|object|style|form)[\"'`]",
    r"\.style\.cssText|setAttribute\(\s*[\"']style[\"']",
]


@pytest.mark.parametrize("pattern", _FORBIDDEN)
def test_the_source_never_uses(pattern: str) -> None:
    offenders = [
        f"{path.relative_to(WEB)}:{number}"
        for path in _source_files()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(pattern, line)
    ]

    assert offenders == []


def test_the_only_urls_written_in_the_source_are_the_loopback_development_defaults() -> None:
    found = {
        match
        for path in _source_files()
        for match in re.findall(r"https?://[^\s\"'`)>]+", path.read_text(encoding="utf-8"))
    }

    assert found <= {"http://127.0.0.1:8000", "http://localhost:8180/realms/neuron"}


_ANALYTICS = re.compile(
    r"^(@sentry/|@segment/|@amplitude/|@datadog/browser|@bugsnag/|@fullstory/|@logrocket/|"
    r"@vercel/analytics|@microsoft/applicationinsights|@opentelemetry/sdk-trace-web|"
    r"posthog|mixpanel|react-ga|ga-4|gtag|analytics$|logrocket|hotjar|heap-|newrelic|rollbar|"
    r"plausible|fathom|web-vitals|raygun|appsignal|honeybadger|clarity|smartlook|segment)"
)


def test_no_analytics_or_telemetry_package_is_installed() -> None:
    lock = json.loads((WEB / "package-lock.json").read_text(encoding="utf-8"))
    names = {path.rsplit("node_modules/", 1)[-1] for path in lock["packages"] if path}

    assert len(names) > 300
    assert sorted(name for name in names if _ANALYTICS.match(name)) == []


def test_the_page_follows_the_system_colour_scheme_and_scales_to_small_screens() -> None:
    """Dark mode follows the system and the layout fits 360 px (ADR 0010, decision 8)."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "src" / "index.css").read_text(encoding="utf-8")
    app = (WEB / "src" / "App.tsx").read_text(encoding="utf-8")
    chat = (WEB / "src" / "features" / "chat" / "ChatScreen.tsx").read_text(encoding="utf-8")

    assert 'name="color-scheme" content="light dark"' in html
    assert "color-scheme: light dark" in css
    assert "@media (prefers-color-scheme: dark)" in css
    # Zoom is never disabled, and the layout adapts instead of overflowing.
    assert "maximum-scale" not in html and "user-scalable" not in html
    assert "width=device-width, initial-scale=1.0" in html
    assert "p-4 sm:p-6" in app
    assert "ml-4" in chat and "sm:ml-8" in chat
    assert "flex-wrap" in chat
