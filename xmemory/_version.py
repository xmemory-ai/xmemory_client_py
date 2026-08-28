from __future__ import annotations

import platform
import re

# Twin of `[project].version` in pyproject.toml; bump both in one edit (see AGENTS.md).
# `test_version_matches_pyproject` fails if they drift.
__version__ = "0.17.0"

# The header this library sends its identity in. A dedicated field rather than ``User-Agent``: that one
# belongs to whoever built the request -- you, httpx, or the platform hosting your code -- and this
# library taking it would mean deciding which of them to overrule.
CLIENT_HEADER = "X-Xmemory-Client"

# Everything outside this set is dropped from the platform note. An allowlist rather than a
# ban-list because the set of characters that must not reach a header value is open-ended:
# control characters are rejected outright when the request is sent, and non-ASCII bytes cannot
# be encoded at all.
_UNSAFE_HINT_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_HINT_LEN = 64


def _hint_field(value: str) -> str:
    """Reduce one host detail to something a header value may safely carry.

    Capped before the separators are trimmed, never after: a value cut at the wrong place would
    otherwise leave a dangling separator that trimming had already removed. All three the allowlist
    admits are trimmed, not just the one the note joins on -- a cut at 64 can equally land after a
    ``.`` or a ``_``. Falls back to ``unknown`` when nothing survives, so a field is never empty.
    """
    return _UNSAFE_HINT_CHARS.sub("", value)[:_MAX_HINT_LEN].strip("-._") or "unknown"


def _platform_hint() -> str:
    """Build the parenthesized platform note for the client-identity header.

    Two fields: the Python version, then the OS name and machine architecture. The interpreter
    version is the one host fact worth acting on — it is what says whether a Python release can be
    dropped — so it leads. Never ``platform.node()``, which would leak a hostname.

    No value here is the operating system's to guarantee: on Windows the machine string is read
    straight out of an environment variable, so each field is sanitized rather than trusted. The
    allowlist admits no semicolon or parenthesis, so a field cannot forge the separators this
    joins on or close the parenthetical early.
    """
    runtime = _hint_field(platform.python_version())
    host = _hint_field(f"{platform.system()}-{platform.machine()}")
    return f"python {runtime}; {host}"


def client_identity() -> str:
    """Build the ``X-Xmemory-Client`` header value this library sends on every request it issues.

    Shaped as ``xmemory-python/<major>.<minor>.<patch> (<platform>)``. Exposed so you can set it on
    an HTTP client you build yourself; the library sends it on the requests it issues either way,
    including on a client you supplied. Your ``User-Agent`` is never read or written.

    Reading the platform note must never be the reason a request fails, so an ordinary failure to
    obtain it degrades to ``unknown`` instead of propagating. The note is built per request, so a
    ``platform`` module that raises would otherwise fail every call rather than only construction.
    A ``BaseException`` still propagates, deliberately: a ``KeyboardInterrupt`` must not be swallowed
    into a header value.
    """
    try:
        hint = _platform_hint()
    except Exception:
        hint = "unknown"
    return f"xmemory-python/{__version__} ({hint})"
