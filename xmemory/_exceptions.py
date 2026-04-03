from __future__ import annotations


class XmemoryAPIError(Exception):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


class XmemoryHealthCheckError(XmemoryAPIError):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message, status=status)
