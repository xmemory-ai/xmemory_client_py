from __future__ import annotations

import uuid
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from xmemory._exceptions import XmemoryAPIError
from xmemory._models import _RawApiResponse

_T = TypeVar("_T", bound=BaseModel)


class SyncTransport:
    """Synchronous HTTP transport with ApiResponse wrapper handling."""

    def __init__(self, client: httpx.Client, token: str | None, timeout: float) -> None:
        self._client = client
        self._token = token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        if self._token:
            return {"Authorization": "Bearer " + self._token}
        return {}

    def _parse(self, resp: httpx.Response, path: str) -> _RawApiResponse:
        payload = resp.json() if resp.text else {}
        parsed = _RawApiResponse.model_validate(payload)
        if parsed.errors:
            raise XmemoryAPIError(path + " failed: " + parsed.errors[0].message, status=resp.status_code)
        return parsed

    def _parse_err(self, resp: httpx.Response, path: str) -> str:
        """Build an error message from the response, preferring structured errors."""
        try:
            if resp.text:
                parsed = _RawApiResponse.model_validate(resp.json())
                if parsed.errors:
                    return path + " failed: " + parsed.errors[0].message
        except Exception:
            pass
        msg = "HTTP " + str(resp.status_code)
        detail = resp.text.strip() if resp.text else None
        if detail:
            msg = msg + " — " + detail
        return msg

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
                method, path, json=json_data, params=params, headers=self._headers(), timeout=t,
            )
            resp.raise_for_status()
            return self._parse(resp, path)
        except XmemoryAPIError:
            raise
        except httpx.HTTPStatusError as e:
            raise XmemoryAPIError(self._parse_err(e.response, path), status=e.response.status_code) from e
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
    ) -> list[uuid.UUID]:
        return self.request(method, path, body=body, params=params, timeout=timeout).ids


class AsyncTransport:
    """Asynchronous HTTP transport with ApiResponse wrapper handling."""

    def __init__(self, client: httpx.AsyncClient, token: str | None, timeout: float) -> None:
        self._client = client
        self._token = token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        if self._token:
            return {"Authorization": "Bearer " + self._token}
        return {}

    def _parse(self, resp: httpx.Response, path: str) -> _RawApiResponse:
        payload = resp.json() if resp.text else {}
        parsed = _RawApiResponse.model_validate(payload)
        if parsed.errors:
            raise XmemoryAPIError(path + " failed: " + parsed.errors[0].message, status=resp.status_code)
        return parsed

    def _parse_err(self, resp: httpx.Response, path: str) -> str:
        """Build an error message from the response, preferring structured errors."""
        try:
            if resp.text:
                parsed = _RawApiResponse.model_validate(resp.json())
                if parsed.errors:
                    return path + " failed: " + parsed.errors[0].message
        except Exception:
            pass
        msg = "HTTP " + str(resp.status_code)
        detail = resp.text.strip() if resp.text else None
        if detail:
            msg = msg + " — " + detail
        return msg

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
                method, path, json=json_data, params=params, headers=self._headers(), timeout=t,
            )
            resp.raise_for_status()
            return self._parse(resp, path)
        except XmemoryAPIError:
            raise
        except httpx.HTTPStatusError as e:
            raise XmemoryAPIError(self._parse_err(e.response, path), status=e.response.status_code) from e
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
    ) -> list[uuid.UUID]:
        return (await self.request(method, path, body=body, params=params, timeout=timeout)).ids
