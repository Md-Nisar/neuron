"""validate_safe_url rejects literal-address SSRF forms (#167); it does no DNS."""

from __future__ import annotations

import pytest

from neuron_agent.errors.base import AuthorizationError, ValidationAppError
from neuron_agent.security.input_policy import validate_safe_url

_BLOCKED_ADDRESSES = [
    "http://localhost/",
    "http://localhost:8000/secrets",
    "http://localhost./",
    "http://LOCALHOST/",
    "http://printer.local/",
    "http://printer.local./",
    "http://127.0.0.1/",
    "http://127.0.0.2/",
    "http://127.1/",
    "http://[::1]/",
    "http://[::]/",
    "http://0.0.0.0/",
    "http://0/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[fe80::1]/",
    "http://10.0.0.1/",
    "http://172.16.0.1/",
    "http://172.31.255.255/",
    "http://192.168.1.1/",
    "http://100.64.0.1/",
    "http://224.0.0.1/",
    "http://[ff02::1]/",
    "http://240.0.0.1/",
    "http://255.255.255.255/",
    "http://[fc00::1]/",
    "http://[3fff::1]/",  # documentation range added in 2024
    "http://[3fff:fff:ffff::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://[::ffff:7f00:1]/",
    "http://[::ffff:169.254.169.254]/",
    "http://[::ffff:10.0.0.1]/",
    "http://[64:ff9b::7f00:1]/",
    "http://[2002:7f00:1::]/",
    "http://2130706433/",  # decimal 127.0.0.1
    "http://0x7f000001/",  # hex 127.0.0.1
    "http://0x7f.0.0.1/",
    "http://0177.0.0.1/",  # octal 127.0.0.1
    "http://017700000001/",
    "http://0251.0376.0251.0376/",  # octal 169.254.169.254
    "http://2852039166/",  # decimal 169.254.169.254
    "http://3232235777/",  # decimal 192.168.1.1
    "http://127.0.0.1./",
    "http://10.0.0.1./",
    "https://[::1]:8443/",
]
_MALFORMED = [
    "http://user@example.com/",
    "http://user:pass@example.com/",
    "http://example.com@127.0.0.1/",
    "http://127.0.0.1@example.com/",
    "http://@example.com/",
    "http://example.com\\@127.0.0.1/",
    "http://exa mple.com/",
    "http://example.com/\n",
    "http://[fe80::1%25eth0]/",
    "http://[::1/",
    "http://0xg.1/",
    "http://127\u30020\u30020\u30021/",  # ideographic full stop
    "http://127\uff0e0\uff0e0\uff0e1/",  # fullwidth full stop
    "http://127\uff610\uff610\uff611/",  # halfwidth ideographic full stop
    "http://127.0.0.1\u3002/",
    "http://localhost\u3002/",
    "http://foo.local\u3002/",
    "http://\uff4c\uff4f\uff43\uff41\uff4c\uff48\uff4f\uff53\uff54/",  # fullwidth localhost
    "http://\uff11\uff12\uff17.0.0.1/",  # fullwidth digits
    "http://\uff11\uff12\uff17\uff0e\uff10\uff0e\uff10\uff0e\uff11/",
    "http://ex\u0430mple.com/",  # Cyrillic a
    "http://b\u00fccher.example/",  # must be passed as punycode
    "http://local\u200bhost/",  # zero-width space
    "http://127.0.0.1\u200b/",
    "http://local\u00adhost/",  # soft hyphen
    "http://127.0.0.1\u00ad/",
    "http://127.0.0.1%2e/",
    "http://127.0.0.1%2E/",
    "http://localhost%2e/",
    "http://exa%6dple.com/",
    "http://1.2.3.4.5/",
    "http://999.1.1.1/",
    "http://0x/",
    "http://example.com:99999/",
    "http://example.com:abc/",
    "http:///path",
    "http://./",
    "ftp://example.com/",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "//example.com/",
    "",
]
_ALLOWED = [
    "https://example.com/",
    "http://example.com:8080/path?q=1#frag",
    "https://sub.example.co.uk/a/b",
    "https://example.com./",  # trailing dot on a public name is the same host
    "https://8.8.8.8/",
    "http://1.1.1.1:443/",
    "https://[2606:4700:4700::1111]/",
    "https://[2001:4860:4860::8888]/",
    "https://localhost.example.com/",
    "https://local.example.com/",
    "https://xn--bcher-kva.example/",
    "https://1password.com/",
    "https://0x.example.com/",
    "https://172.15.0.1/",  # just outside 172.16.0.0/12
    "https://[::ffff:8.8.8.8]/",
]


@pytest.mark.parametrize("url", _BLOCKED_ADDRESSES)
def test_safe_url_rejects_non_public_addresses(url: str) -> None:
    with pytest.raises(AuthorizationError):
        validate_safe_url(url)


@pytest.mark.parametrize("url", _MALFORMED)
def test_safe_url_rejects_malformed_and_ambiguous_urls(url: str) -> None:
    with pytest.raises(ValidationAppError):
        validate_safe_url(url)


@pytest.mark.parametrize("url", _ALLOWED)
def test_safe_url_accepts_public_hosts_unchanged(url: str) -> None:
    assert validate_safe_url(url) == url


def test_safe_url_never_resolves_names(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("validate_safe_url must not resolve names")

    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "inet_aton"):
        monkeypatch.setattr(socket, name, boom)
    assert validate_safe_url("https://internal.example.net/") == "https://internal.example.net/"
    with pytest.raises(AuthorizationError):
        validate_safe_url("http://2130706433/")


def test_safe_url_contract_names_what_fetching_tools_must_do() -> None:
    doc = " ".join((validate_safe_url.__doc__ or "").lower().split())
    for required in ("resolve once", "connect to the checked ip", "re-validate", "redirect"):
        assert required in doc, required
