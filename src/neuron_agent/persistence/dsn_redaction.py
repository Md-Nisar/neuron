# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Keep database passwords out of psycopg's own log records (issue #204).

When a connection fails, `psycopg_pool` logs the driver's message at WARNING on the
`psycopg.pool` logger, and libpq echoes the whole connection string in some errors (for
example a malformed URI). Those records bypass structlog, so they are scrubbed here instead.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote, unquote

import psycopg.conninfo

_LOGGERS = ("psycopg", "psycopg.pool")
_REDACTED = "***"
# Fallbacks for a string `conninfo_to_dict` cannot parse: `://user:password@` and `password=...`.
_URI_PASSWORD = re.compile(r"(://[^/\s:@]*:)[^\s]*(@)")
_KEYWORD_PASSWORD = re.compile(r"(password\s*=\s*)('(?:[^'\\]|\\.)*'|\S+)", re.IGNORECASE)


class DsnRedactionFilter(logging.Filter):
    """Replace the DSN and its password in a record's message and exception text."""

    def __init__(self, *dsns: str) -> None:
        super().__init__()
        secrets: set[str] = set()
        for dsn in dsns:
            secrets.add(dsn)
            try:
                password = psycopg.conninfo.conninfo_to_dict(dsn).get("password")
            except Exception:  # an unparsable DSN is covered by the regex fallbacks below
                password = None
            if password:
                text = str(password)
                secrets.update({text, quote(text, safe=""), unquote(text)})
        # Longest first, so the whole DSN is replaced before any part of it.
        self._secrets = sorted((s for s in secrets if s), key=len, reverse=True)

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, _REDACTED)
        text = _URI_PASSWORD.sub(rf"\g<1>{_REDACTED}\g<2>", text)
        return _KEYWORD_PASSWORD.sub(rf"\g<1>{_REDACTED}", text)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.getMessage())
        record.args = None
        if record.exc_info:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = self.redact(formatted)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        return True


_known_dsns: set[str] = set()


def install_dsn_redaction(*dsns: str) -> DsnRedactionFilter:
    """Attach a redaction filter to psycopg's loggers covering every DSN seen so far.

    Additive: a second call (another `Settings` in the same process) keeps the earlier DSNs.
    """
    _known_dsns.update(dsns)
    redactor = DsnRedactionFilter(*sorted(_known_dsns))
    for name in _LOGGERS:
        target = logging.getLogger(name)
        for existing in [f for f in target.filters if isinstance(f, DsnRedactionFilter)]:
            target.removeFilter(existing)
        target.addFilter(redactor)
    return redactor
