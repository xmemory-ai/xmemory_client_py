from __future__ import annotations

import os
from datetime import datetime
from enum import Enum
from typing import Any, Literal, TypeVar

import httpx
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class XmemoryAPIError(Exception):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


class XmemoryHealthCheckError(XmemoryAPIError):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message, status=status)


# ---------------------------------------------------------------------------
# Schema type (public)
# ---------------------------------------------------------------------------


class SchemaType(Enum):
    YML = 0
    JSON = 1


class ExtractionLogic(str, Enum):
    FAST = "fast"
    REGULAR = "regular"
    DEEP = "deep"


class ReadMode(str, Enum):
    SINGLE_ANSWER = "single-answer"
    RAW_TABLES = "raw-tables"
    XRESPONSE = "xresponse"


# ---------------------------------------------------------------------------
# Response models (public)
# Complex nested fields (reader_result, cleaned_objects, etc.) are typed as
# Any — they reflect the server's JSON verbatim and users can traverse freely.
# ---------------------------------------------------------------------------


class ReadResponse(BaseModel):
    status: Literal["ok", "error"]
    read_id: str | None = None
    reader_result: Any = None
    error_message: str | None = None


class WriteResponse(BaseModel):
    status: Literal["ok", "error"]
    extract_write_id: str | None = None
    cleaned_objects: Any = None
    diff_plan: Any = None
    error_message: str | None = None


class ExtractionResponse(BaseModel):
    status: Literal["ok", "error"]
    extract_write_id: str | None = None
    objects_extracted: Any = None
    error_message: str | None = None


class GenerateSchemaResponse(BaseModel):
    status: Literal["ok", "error"]
    generated_schema: dict[str, Any] | None = None
    error_message: str | None = None


class CreateInstanceResponse(BaseModel):
    status: Literal["ok", "error"]
    instance_id: str | None = None
    error_message: str | None = None


class AsyncWriteResponse(BaseModel):
    status: Literal["ok", "error"]
    write_id: str | None = None
    error_message: str | None = None


class WriteQueueStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_FOUND = "not_found"


class WriteStatusResponse(BaseModel):
    status: Literal["ok", "error"]
    write_id: str
    write_status: WriteQueueStatus
    error_detail: str | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


class GetSchemaResponse(BaseModel):
    instance_id: str
    schema_yaml: str


# ---------------------------------------------------------------------------
# Internal request / response models
# ---------------------------------------------------------------------------


class _ReadRequest(BaseModel):
    instance_id: str
    query: str
    mode: ReadMode = ReadMode.SINGLE_ANSWER


class _WriteRequest(BaseModel):
    instance_id: str
    text: str
    extraction_logic: ExtractionLogic


class _ExtractionRequest(BaseModel):
    instance_id: str
    text: str
    extraction_logic: ExtractionLogic


class _GenerateSchemaRequest(BaseModel):
    schema_description: str
    current_yml_schema: str | dict[str, Any] | None = None


class _CreateInstanceYMLRequest(BaseModel):
    yml_schema: str | dict[str, Any] | None = None


class _CreateInstanceJSONRequest(BaseModel):
    json_schema: str | dict[str, Any] | None = None


class _UpdateInstanceYMLRequest(BaseModel):
    instance_id: str
    yml_schema: str | dict[str, Any] | None = None


class _UpdateInstanceJSONRequest(BaseModel):
    instance_id: str
    json_schema: str | dict[str, Any]


class _UpdateInstanceResponse(BaseModel):
    status: Literal["ok", "error"]


class _WriteStatusRequest(BaseModel):
    write_id: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_T = TypeVar("_T", bound=BaseModel)


class XmemoryAPI:
    """Synchronous client for the Xmemory API."""

    def __init__(
        self,
        url: str | None = None,
        *,
        timeout: float = 60,
        instance_id: str | None = None,
        token: str | None = None,
        http_client: httpx.Client | None = None
    ) -> None:
        """Create a synchronous Xmemory client.

        Args:
            url: Base URL of the Xmemory API. Falls back to the XMEM_API_URL env var,
                then https://api.xmemory.ai. Cannot be combined with http_client.
            timeout: Default request timeout in seconds. Ignored when http_client is provided.
            instance_id: ID of the memory instance to operate on. Can also be set later
                via client.instance_id or create_instance().
            token: Bearer token for authentication. Falls back to the XMEM_AUTH_TOKEN env var.
            http_client: An existing httpx.Client to use. Must have base_url set.
                The client will not be closed when this instance is closed.

        """
        self.timeout = timeout
        self.instance_id: str | None = instance_id
        self.token: str | None = token or os.environ.get("XMEM_AUTH_TOKEN")

        if http_client is not None:
            if not isinstance(http_client, httpx.Client):
                raise XmemoryAPIError("http_client must be an instance of httpx.Client")

            if url is not None:
                raise XmemoryAPIError("Cannot specify both 'url' and 'http_client' — set base_url on the client directly")

            if not http_client.base_url.host:
                raise XmemoryAPIError("http_client must have base_url set — or omit it and pass url= instead")

            self.base_url = http_client.base_url
            self._client = http_client
            self._owns_client = False

        else:
            self.base_url = httpx.URL(url or os.environ.get("XMEM_API_URL") or "https://api.xmemory.ai")
            self._client = httpx.Client(base_url=self.base_url, timeout=timeout)
            self._owns_client = True

    def _auth_headers(self) -> dict[str, str]:
        if self.token:
            return {"Authorization": "Bearer " + self.token}
        return {}

    def _post(
        self,
        path: str,
        body: BaseModel,
        response_type: type[_T],
        *,
        timeout: float | None = None,
    ) -> _T:
        used_timeout = timeout if timeout is not None else self.timeout
        try:
            resp = self._client.post(path, json=body.model_dump(), headers=self._auth_headers(), timeout=used_timeout)
            resp.raise_for_status()
            payload_json = resp.json() if resp.text else {}
            if isinstance(payload_json, dict) and payload_json.get("status") == "error":
                error_msg = payload_json.get("error_message") or payload_json.get("error") or str(payload_json)
                raise XmemoryAPIError(path + " failed: " + error_msg, status=resp.status_code)
            try:
                return response_type.model_validate(payload_json)
            except Exception as ve:
                raise XmemoryAPIError(
                    "Response does not match expected schema: " + str(ve) + "\nPayload: " + str(payload_json),
                    status=resp.status_code,
                ) from ve
        except XmemoryAPIError:
            raise
        except httpx.HTTPStatusError as e:
            msg = "HTTP " + str(e.response.status_code)
            detail = e.response.text.strip() if e.response.text else None
            if detail:
                msg = msg + " — " + detail
            raise XmemoryAPIError(msg, status=e.response.status_code) from e
        except httpx.ConnectError as e:
            raise XmemoryAPIError("Connection error: " + str(e)) from e
        except Exception as e:
            raise XmemoryAPIError("Unexpected error: " + str(e)) from e

    def _get(
        self,
        path: str,
        response_type: type[_T],
        *,
        params: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> _T:
        used_timeout = timeout if timeout is not None else self.timeout
        try:
            resp = self._client.get(path, params=params, headers=self._auth_headers(), timeout=used_timeout)
            resp.raise_for_status()
            payload_json = resp.json() if resp.text else {}
            try:
                return response_type.model_validate(payload_json)
            except Exception as ve:
                raise XmemoryAPIError(
                    "Response does not match expected schema: " + str(ve) + "\nPayload: " + str(payload_json),
                    status=resp.status_code,
                ) from ve
        except XmemoryAPIError:
            raise
        except httpx.HTTPStatusError as e:
            msg = "HTTP " + str(e.response.status_code)
            detail = e.response.text.strip() if e.response.text else None
            if detail:
                msg = msg + " — " + detail
            raise XmemoryAPIError(msg, status=e.response.status_code) from e
        except httpx.ConnectError as e:
            raise XmemoryAPIError("Connection error: " + str(e)) from e
        except Exception as e:
            raise XmemoryAPIError("Unexpected error: " + str(e)) from e

    def _require_instance_id(self, op: str) -> str:
        if not self.instance_id:
            raise XmemoryAPIError(f"instance_id is required for {op}() — pass it to the constructor or set client.instance_id directly.")
        return self.instance_id

    def check_health(self) -> None:
        """Verify the API server is reachable. Raises XmemoryHealthCheckError on failure."""
        try:
            resp = self._client.get("/healthz", timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise XmemoryHealthCheckError(
                "Health check HTTP error " + str(e.response.status_code),
                status=e.response.status_code,
            ) from e
        except httpx.ConnectError as e:
            raise XmemoryHealthCheckError("Health check connection error: " + str(e)) from e
        except Exception as e:
            raise XmemoryHealthCheckError("Health check failed: " + str(e)) from e

    def read(
        self,
        query: str,
        *,
        read_mode: ReadMode = ReadMode.SINGLE_ANSWER,
        timeout: float | None = None,
    ) -> ReadResponse:
        """Query the active instance and return a structured answer.

        Args:
            query: Natural language question to ask the instance.
            read_mode: Controls the format of the response.
            timeout: Request timeout in seconds. Overrides the client default.
        """
        iid = self._require_instance_id("read")
        return self._post(
            "/read",
            _ReadRequest(instance_id=iid, query=query, mode=read_mode),
            ReadResponse,
            timeout=timeout,
        )

    def write(self, text: str, *, extraction_logic: ExtractionLogic = ExtractionLogic.DEEP, timeout: float | None = None) -> WriteResponse:
        """Extract structured data from text and persist it to the active instance.

        Args:
            text: The text to extract structured data from.
            extraction_logic: Controls the depth and speed of extraction.
            timeout: Request timeout in seconds. Overrides the client default.
        """
        iid = self._require_instance_id("write")
        return self._post(
            "/write",
            _WriteRequest(instance_id=iid, text=text, extraction_logic=extraction_logic),
            WriteResponse,
            timeout=timeout,
        )

    def extract(
        self, text: str, *, extraction_logic: ExtractionLogic = ExtractionLogic.DEEP, timeout: float | None = None
    ) -> ExtractionResponse:
        """Extract structured data from text without persisting it.

        Args:
            text: The text to extract structured data from.
            extraction_logic: Controls the depth and speed of extraction.
            timeout: Request timeout in seconds. Overrides the client default.
        """
        iid = self._require_instance_id("extract")
        return self._post(
            "/extract",
            _ExtractionRequest(instance_id=iid, text=text, extraction_logic=extraction_logic),
            ExtractionResponse,
            timeout=timeout,
        )

    def generate_schema(
        self, schema_description: str, *, old_schema_yml: str | None = None, timeout: float | None = None
    ) -> GenerateSchemaResponse:
        """Generate a YML schema from a natural language description.

        Args:
            schema_description: Natural language description of the desired schema.
            old_schema_yml: Existing YML schema to refine instead of generating from scratch.
            timeout: Request timeout in seconds. Overrides the client default.
        """
        return self._post(
            "/instance/generate_schema",
            _GenerateSchemaRequest(schema_description=schema_description, current_yml_schema=old_schema_yml),
            GenerateSchemaResponse,
            timeout=timeout,
        )

    def create_instance(self, schema_text: str, schema_type: SchemaType, *, timeout: float | None = None) -> CreateInstanceResponse:
        """Create a new memory instance from a schema. Sets instance_id on success.

        Args:
            schema_text: The schema definition as a YML or JSON string.
            schema_type: Whether schema_text is YML or JSON.
            timeout: Request timeout in seconds. Overrides the client default.
        """
        if schema_type == SchemaType.YML:
            req_model: BaseModel = _CreateInstanceYMLRequest(yml_schema=schema_text)
        else:
            req_model = _CreateInstanceJSONRequest(json_schema=schema_text)
        response = self._post(
            "/instance/create",
            req_model,
            CreateInstanceResponse,
            timeout=timeout,
        )
        if response.status == "ok" and response.instance_id:
            self.instance_id = response.instance_id
        return response

    def update_schema(self, schema_text: str, schema_type: SchemaType, *, timeout: float | None = None) -> bool:
        """Update the schema of the active instance. Returns True on success.

        Args:
            schema_text: The updated schema definition as a YML or JSON string.
            schema_type: Whether schema_text is YML or JSON.
            timeout: Request timeout in seconds. Overrides the client default.
        """
        iid = self._require_instance_id("update_schema")
        if schema_type == SchemaType.YML:
            req_model: BaseModel = _UpdateInstanceYMLRequest(instance_id=iid, yml_schema=schema_text)
        else:
            req_model = _UpdateInstanceJSONRequest(instance_id=iid, json_schema=schema_text)
        response = self._post(
            "/instance/update",
            req_model,
            _UpdateInstanceResponse,
            timeout=timeout,
        )
        return response.status == "ok"

    def get_schema(self, *, timeout: float | None = None) -> GetSchemaResponse:
        """Fetch the current schema of the active instance.

        Args:
            timeout: Request timeout in seconds. Overrides the client default.
        """
        iid = self._require_instance_id("get_schema")
        return self._get("/instance/schema", GetSchemaResponse, params={"instance_id": iid}, timeout=timeout)

    def write_async(self, text: str, *, extraction_logic: ExtractionLogic = ExtractionLogic.DEEP, timeout: float | None = None) -> AsyncWriteResponse:
        """Submit a write job and return immediately with a write_id for polling.

        Args:
            text: The text to extract structured data from.
            extraction_logic: Controls the depth and speed of extraction.
            timeout: Request timeout in seconds. Overrides the client default.
        """
        iid = self._require_instance_id("write_async")
        return self._post(
            "/write_async",
            _WriteRequest(instance_id=iid, text=text, extraction_logic=extraction_logic),
            AsyncWriteResponse,
            timeout=timeout,
        )

    def write_status(self, write_id: str, *, timeout: float | None = None) -> WriteStatusResponse:
        """Poll the status of an async write job.

        Args:
            write_id: The write_id returned by write_async().
            timeout: Request timeout in seconds. Overrides the client default.
        """
        return self._post("/write_status", _WriteStatusRequest(write_id=write_id), WriteStatusResponse, timeout=timeout)

    def close(self) -> None:
        """Close the underlying HTTP client. No-op if the client was externally provided."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> XmemoryAPI:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Async public API
# ---------------------------------------------------------------------------


class AsyncXmemoryAPI:
    """Asynchronous client for the Xmemory API."""

    def __init__(
        self,
        url: str | None = None,
        *,
        timeout: float = 60,
        instance_id: str | None = None,
        token: str | None = None,
        http_client: httpx.AsyncClient | None = None,

    ) -> None:
        """Create an asynchronous Xmemory client.

        Args:
            url: Base URL of the Xmemory API. Falls back to the XMEM_API_URL env var,
                then https://api.xmemory.ai. Cannot be combined with http_client.
            timeout: Default request timeout in seconds. Ignored when http_client is provided.
            instance_id: ID of the memory instance to operate on. Can also be set later
                via client.instance_id or create_instance().
            token: Bearer token for authentication. Falls back to the XMEM_AUTH_TOKEN env var.
            http_client: An existing httpx.AsyncClient to use. Must have base_url set.
                The client will not be closed when this instance is closed.

        """
        self.timeout = timeout
        self.instance_id: str | None = instance_id
        self.token: str | None = token or os.environ.get("XMEM_AUTH_TOKEN")

        if http_client is not None:
            if not isinstance(http_client, httpx.AsyncClient):
                raise XmemoryAPIError("http_client must be an instance of httpx.AsyncClient")

            if url is not None:
                raise XmemoryAPIError("Cannot specify both 'url' and 'http_client' — set base_url on the client directly")

            if not http_client.base_url.host:
                raise XmemoryAPIError("http_client must have base_url set — or omit it and pass url= instead")

            self.base_url = http_client.base_url
            self._client = http_client
            self._owns_client = False

        else:
            self.base_url = httpx.URL(url or os.environ.get("XMEM_API_URL") or "https://api.xmemory.ai")
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)
            self._owns_client = True

    def _auth_headers(self) -> dict[str, str]:
        if self.token:
            return {"Authorization": "Bearer " + self.token}
        return {}

    async def _post(
        self,
        path: str,
        body: BaseModel,
        response_type: type[_T],
        *,
        timeout: float | None = None,
    ) -> _T:
        used_timeout = timeout if timeout is not None else self.timeout
        try:
            resp = await self._client.post(path, json=body.model_dump(), headers=self._auth_headers(), timeout=used_timeout)
            resp.raise_for_status()
            payload_json = resp.json() if resp.text else {}
            if isinstance(payload_json, dict) and payload_json.get("status") == "error":
                error_msg = payload_json.get("error_message") or payload_json.get("error") or str(payload_json)
                raise XmemoryAPIError(path + " failed: " + error_msg, status=resp.status_code)
            try:
                return response_type.model_validate(payload_json)
            except Exception as ve:
                raise XmemoryAPIError(
                    "Response does not match expected schema: " + str(ve) + "\nPayload: " + str(payload_json),
                    status=resp.status_code,
                ) from ve
        except XmemoryAPIError:
            raise
        except httpx.HTTPStatusError as e:
            msg = "HTTP " + str(e.response.status_code)
            detail = e.response.text.strip() if e.response.text else None
            if detail:
                msg = msg + " — " + detail
            raise XmemoryAPIError(msg, status=e.response.status_code) from e
        except httpx.ConnectError as e:
            raise XmemoryAPIError("Connection error: " + str(e)) from e
        except Exception as e:
            raise XmemoryAPIError("Unexpected error: " + str(e)) from e

    async def _get(
        self,
        path: str,
        response_type: type[_T],
        *,
        params: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> _T:
        used_timeout = timeout if timeout is not None else self.timeout
        try:
            resp = await self._client.get(path, params=params, headers=self._auth_headers(), timeout=used_timeout)
            resp.raise_for_status()
            payload_json = resp.json() if resp.text else {}
            try:
                return response_type.model_validate(payload_json)
            except Exception as ve:
                raise XmemoryAPIError(
                    "Response does not match expected schema: " + str(ve) + "\nPayload: " + str(payload_json),
                    status=resp.status_code,
                ) from ve
        except XmemoryAPIError:
            raise
        except httpx.HTTPStatusError as e:
            msg = "HTTP " + str(e.response.status_code)
            detail = e.response.text.strip() if e.response.text else None
            if detail:
                msg = msg + " — " + detail
            raise XmemoryAPIError(msg, status=e.response.status_code) from e
        except httpx.ConnectError as e:
            raise XmemoryAPIError("Connection error: " + str(e)) from e
        except Exception as e:
            raise XmemoryAPIError("Unexpected error: " + str(e)) from e

    def _require_instance_id(self, op: str) -> str:
        if not self.instance_id:
            raise XmemoryAPIError(f"instance_id is required for {op}() — pass it to the constructor or set client.instance_id directly.")
        return self.instance_id

    async def check_health(self) -> None:
        """Verify the API server is reachable. Raises XmemoryHealthCheckError on failure."""
        try:
            resp = await self._client.get("/healthz", timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise XmemoryHealthCheckError(
                "Health check HTTP error " + str(e.response.status_code),
                status=e.response.status_code,
            ) from e
        except httpx.ConnectError as e:
            raise XmemoryHealthCheckError("Health check connection error: " + str(e)) from e
        except Exception as e:
            raise XmemoryHealthCheckError("Health check failed: " + str(e)) from e

    async def read(
        self,
        query: str,
        *,
        read_mode: ReadMode = ReadMode.SINGLE_ANSWER,
        timeout: float | None = None,
    ) -> ReadResponse:
        """Query the active instance and return a structured answer.

        Args:
            query: Natural language question to ask the instance.
            read_mode: Controls the format of the response.
            timeout: Request timeout in seconds. Overrides the client default.
        """
        iid = self._require_instance_id("read")
        return await self._post(
            "/read",
            _ReadRequest(instance_id=iid, query=query, mode=read_mode),
            ReadResponse,
            timeout=timeout,
        )

    async def write(self, text: str, *, extraction_logic: ExtractionLogic = ExtractionLogic.DEEP, timeout: float | None = None) -> WriteResponse:
        """Extract structured data from text and persist it to the active instance.

        Args:
            text: The text to extract structured data from.
            extraction_logic: Controls the depth and speed of extraction.
            timeout: Request timeout in seconds. Overrides the client default.
        """
        iid = self._require_instance_id("write")
        return await self._post(
            "/write",
            _WriteRequest(instance_id=iid, text=text, extraction_logic=extraction_logic),
            WriteResponse,
            timeout=timeout,
        )

    async def extract(
        self, text: str, *, extraction_logic: ExtractionLogic = ExtractionLogic.DEEP, timeout: float | None = None
    ) -> ExtractionResponse:
        """Extract structured data from text without persisting it.

        Args:
            text: The text to extract structured data from.
            extraction_logic: Controls the depth and speed of extraction.
            timeout: Request timeout in seconds. Overrides the client default.
        """
        iid = self._require_instance_id("extract")
        return await self._post(
            "/extract",
            _ExtractionRequest(instance_id=iid, text=text, extraction_logic=extraction_logic),
            ExtractionResponse,
            timeout=timeout,
        )

    async def generate_schema(
        self, schema_description: str, *, old_schema_yml: str | None = None, timeout: float | None = None
    ) -> GenerateSchemaResponse:
        """Generate a YML schema from a natural language description.

        Args:
            schema_description: Natural language description of the desired schema.
            old_schema_yml: Existing YML schema to refine instead of generating from scratch.
            timeout: Request timeout in seconds. Overrides the client default.
        """
        return await self._post(
            "/instance/generate_schema",
            _GenerateSchemaRequest(schema_description=schema_description, current_yml_schema=old_schema_yml),
            GenerateSchemaResponse,
            timeout=timeout,
        )

    async def create_instance(self, schema_text: str, schema_type: SchemaType, *, timeout: float | None = None) -> CreateInstanceResponse:
        """Create a new memory instance from a schema. Sets instance_id on success.

        Args:
            schema_text: The schema definition as a YML or JSON string.
            schema_type: Whether schema_text is YML or JSON.
            timeout: Request timeout in seconds. Overrides the client default.
        """
        if schema_type == SchemaType.YML:
            req_model: BaseModel = _CreateInstanceYMLRequest(yml_schema=schema_text)
        else:
            req_model = _CreateInstanceJSONRequest(json_schema=schema_text)
        response = await self._post(
            "/instance/create",
            req_model,
            CreateInstanceResponse,
            timeout=timeout,
        )
        if response.status == "ok" and response.instance_id:
            self.instance_id = response.instance_id
        return response

    async def update_schema(self, schema_text: str, schema_type: SchemaType, *, timeout: float | None = None) -> bool:
        """Update the schema of the active instance. Returns True on success.

        Args:
            schema_text: The updated schema definition as a YML or JSON string.
            schema_type: Whether schema_text is YML or JSON.
            timeout: Request timeout in seconds. Overrides the client default.
        """
        iid = self._require_instance_id("update_schema")
        if schema_type == SchemaType.YML:
            req_model: BaseModel = _UpdateInstanceYMLRequest(instance_id=iid, yml_schema=schema_text)
        else:
            req_model = _UpdateInstanceJSONRequest(instance_id=iid, json_schema=schema_text)
        response = await self._post(
            "/instance/update",
            req_model,
            _UpdateInstanceResponse,
            timeout=timeout,
        )
        return response.status == "ok"

    async def get_schema(self, *, timeout: float | None = None) -> GetSchemaResponse:
        """Fetch the current schema of the active instance.

        Args:
            timeout: Request timeout in seconds. Overrides the client default.
        """
        iid = self._require_instance_id("get_schema")
        return await self._get("/instance/schema", GetSchemaResponse, params={"instance_id": iid}, timeout=timeout)

    async def write_async(self, text: str, *, extraction_logic: ExtractionLogic = ExtractionLogic.DEEP, timeout: float | None = None) -> AsyncWriteResponse:
        """Submit a write job and return immediately with a write_id for polling.

        Args:
            text: The text to extract structured data from.
            extraction_logic: Controls the depth and speed of extraction.
            timeout: Request timeout in seconds. Overrides the client default.
        """
        iid = self._require_instance_id("write_async")
        return await self._post(
            "/write_async",
            _WriteRequest(instance_id=iid, text=text, extraction_logic=extraction_logic),
            AsyncWriteResponse,
            timeout=timeout,
        )

    async def write_status(self, write_id: str, *, timeout: float | None = None) -> WriteStatusResponse:
        """Poll the status of an async write job.

        Args:
            write_id: The write_id returned by write_async().
            timeout: Request timeout in seconds. Overrides the client default.
        """
        return await self._post("/write_status", _WriteStatusRequest(write_id=write_id), WriteStatusResponse, timeout=timeout)

    async def aclose(self) -> None:
        """Close the underlying HTTP client. No-op if the client was externally provided."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> AsyncXmemoryAPI:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


def xmemory_instance(
    *, url: str | None = None, instance_id: str | None = None, token: str | None = None, timeout: float = 60
) -> XmemoryAPI:
    return XmemoryAPI(url=url, timeout=timeout, token=token, instance_id=instance_id)


def async_xmemory_instance(
    *, url: str | None = None, instance_id: str | None = None, token: str | None = None, timeout: float = 60
) -> AsyncXmemoryAPI:
    return AsyncXmemoryAPI(url=url, timeout=timeout, token=token, instance_id=instance_id)
