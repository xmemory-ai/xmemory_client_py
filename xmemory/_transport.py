from __future__ import annotations


from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from xmemory._exceptions import XmemoryAPIError
from xmemory._models import _RawApiResponse
from xmemory._version import CLIENT_HEADER, client_identity

_T = TypeVar("_T", bound=BaseModel)


def _structured_error(payload: Any) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Extract ``(code, message, details)`` from an error body.

    Handles two server shapes: the schema-evolution
    ``{"status": "error", "error_type", "error_message", "details"}`` payload
    (where ``error_type`` is the structured code), and the standard
    ``{"errors": [{"code", "message"}]}`` envelope. Returns ``(None, None,
    None)`` if neither shape is present.
    """
    if not isinstance(payload, dict):
        return None, None, None
    if payload.get("status") == "error" and "error_type" in payload:
        details = payload.get("details")
        return (
            payload.get("error_type"),
            payload.get("error_message"),
            details if isinstance(details, dict) else None,
        )
    errors = payload.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        details = errors[0].get("details")
        return (
            errors[0].get("code"),
            errors[0].get("message"),
            details if isinstance(details, dict) else None,
        )
    return None, None, None


def _retry_after_seconds(resp: httpx.Response) -> int | None:
    """Parse the integer ``Retry-After`` response header (seconds), if present.

    Only the delta-seconds form is recognised; an HTTP-date value yields
    ``None``. The server sends this on resettable rate-limit / quota responses.
    """
    raw = resp.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0, int(raw.strip()))
    except (TypeError, ValueError):
        return None


def _error_from_response(resp: httpx.Response, path: str) -> XmemoryAPIError:
    """Build a structured :class:`XmemoryAPIError` from an error response."""
    code: str | None = None
    message: str | None = None
    details: dict[str, Any] | None = None
    try:
        if resp.text:
            code, message, details = _structured_error(resp.json())
    except Exception:
        pass
    if message is None:
        msg = "HTTP " + str(resp.status_code)
        detail = resp.text.strip() if resp.text else None
        if detail:
            msg = msg + " — " + detail
    else:
        msg = path + " failed: " + message
    return XmemoryAPIError(
        msg,
        status=resp.status_code,
        code=code,
        details=details,
        retry_after=_retry_after_seconds(resp),
    )


def attribution_headers() -> dict[str, str]:
    """The identity header every request this library issues carries.

    Unconditional, and per request rather than set on the client: nothing else on the wire claims this
    field, so there is no caller intent to infer and no state to read back. A client you supplied gets
    the same header as one this library built, and neither one's ``User-Agent`` is touched.

    A fresh dict each call, because callers add ``Authorization`` to it.
    """
    return {CLIENT_HEADER: client_identity()}


class SyncTransport:
    """Synchronous HTTP transport with ApiResponse wrapper handling."""

    def __init__(
        self,
        client: httpx.Client,
        api_key: str | None,
        timeout: float,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = attribution_headers()
        if self._api_key:
            headers["Authorization"] = "Bearer " + self._api_key
        return headers

    def _parse(self, resp: httpx.Response, path: str) -> _RawApiResponse:
        payload = resp.json() if resp.text else {}
        parsed = _RawApiResponse.model_validate(payload)
        if parsed.errors:
            err = parsed.errors[0]
            raise XmemoryAPIError(
                path + " failed: " + err.message,
                status=resp.status_code,
                code=err.code,
                details=err.details,
                retry_after=_retry_after_seconds(resp),
            )
        return parsed

    def request(
        self,
        method: str,
        path: str,
        *,
        body: BaseModel | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> _RawApiResponse:
        t = timeout if timeout is not None else self.timeout
        try:
            json_data = body.model_dump(by_alias=True) if body is not None else None
            resp = self._client.request(
                method,
                path,
                json=json_data,
                params=params,
                headers=self._headers(),
                timeout=t,
            )
            resp.raise_for_status()
            return self._parse(resp, path)
        except XmemoryAPIError:
            raise
        except httpx.HTTPStatusError as e:
            raise _error_from_response(e.response, path) from e
        except httpx.ConnectError as e:
            raise XmemoryAPIError("Connection error: " + str(e)) from e
        except Exception as e:
            raise XmemoryAPIError("Unexpected error: " + str(e)) from e

    def request_one(
        self,
        method: str,
        path: str,
        response_type: type[_T],
        *,
        body: BaseModel | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> _T:
        api_resp = self.request(method, path, body=body, params=params, timeout=timeout)
        if not api_resp.items:
            raise XmemoryAPIError(path + " returned no items")
        return response_type.model_validate(api_resp.items[0])

    def request_list(
        self,
        method: str,
        path: str,
        response_type: type[_T],
        *,
        body: BaseModel | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> list[_T]:
        api_resp = self.request(method, path, body=body, params=params, timeout=timeout)
        return [response_type.model_validate(item) for item in api_resp.items]

    def request_ids(
        self,
        method: str,
        path: str,
        *,
        body: BaseModel | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> list[str]:
        return self.request(method, path, body=body, params=params, timeout=timeout).ids


class AsyncTransport:
    """Asynchronous HTTP transport with ApiResponse wrapper handling."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str | None,
        timeout: float,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = attribution_headers()
        if self._api_key:
            headers["Authorization"] = "Bearer " + self._api_key
        return headers

    def _parse(self, resp: httpx.Response, path: str) -> _RawApiResponse:
        payload = resp.json() if resp.text else {}
        parsed = _RawApiResponse.model_validate(payload)
        if parsed.errors:
            err = parsed.errors[0]
            raise XmemoryAPIError(
                path + " failed: " + err.message,
                status=resp.status_code,
                code=err.code,
                details=err.details,
                retry_after=_retry_after_seconds(resp),
            )
        return parsed

    async def request(
        self,
        method: str,
        path: str,
        *,
        body: BaseModel | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> _RawApiResponse:
        t = timeout if timeout is not None else self.timeout
        try:
            json_data = body.model_dump(by_alias=True) if body is not None else None
            resp = await self._client.request(
                method,
                path,
                json=json_data,
                params=params,
                headers=self._headers(),
                timeout=t,
            )
            resp.raise_for_status()
            return self._parse(resp, path)
        except XmemoryAPIError:
            raise
        except httpx.HTTPStatusError as e:
            raise _error_from_response(e.response, path) from e
        except httpx.ConnectError as e:
            raise XmemoryAPIError("Connection error: " + str(e)) from e
        except Exception as e:
            raise XmemoryAPIError("Unexpected error: " + str(e)) from e

    async def request_one(
        self,
        method: str,
        path: str,
        response_type: type[_T],
        *,
        body: BaseModel | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> _T:
        api_resp = await self.request(method, path, body=body, params=params, timeout=timeout)
        if not api_resp.items:
            raise XmemoryAPIError(path + " returned no items")
        return response_type.model_validate(api_resp.items[0])

    async def request_list(
        self,
        method: str,
        path: str,
        response_type: type[_T],
        *,
        body: BaseModel | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> list[_T]:
        api_resp = await self.request(method, path, body=body, params=params, timeout=timeout)
        return [response_type.model_validate(item) for item in api_resp.items]

    async def request_ids(
        self,
        method: str,
        path: str,
        *,
        body: BaseModel | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> list[str]:
        return (await self.request(method, path, body=body, params=params, timeout=timeout)).ids
