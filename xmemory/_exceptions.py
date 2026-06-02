from __future__ import annotations

from typing import Any


class XmemoryAPIError(Exception):
    """Raised for any failed xmemory API call.

    ``status`` is the HTTP status code (when the failure came from the server).
    ``code`` is the structured error code when the server returned one — for
    the schema-evolution endpoints this is the ``error_type`` discriminator
    (e.g. ``"stale_proposal_version"``, ``"dependency_closure_failed"``,
    ``"destructive_confirmation_required"``). ``details`` carries the optional
    structured ``details`` object the server attaches to some errors. Pattern
    match on ``code`` rather than parsing the message string.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details


class XmemoryHealthCheckError(XmemoryAPIError):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message, status=status)