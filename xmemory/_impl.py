import json
import os
import urllib.error
import urllib.request
from enum import Enum
from typing import Any, Literal, TypeVar

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


# ---------------------------------------------------------------------------
# Internal request / response models
# ---------------------------------------------------------------------------


class _ReadRequest(BaseModel):
    instance_id: str
    query: str
    mode: str = "single-answer"


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


# ---------------------------------------------------------------------------
# HTTP client (internal)
# ---------------------------------------------------------------------------

_T = TypeVar("_T", bound=BaseModel)


class _XmemoryClient:
    def __init__(
        self,
        url: str | None = None,
        *,
        timeout: int = 60,
        instance_id: str | None = None,
        token: str | None = None,
    ) -> None:
        resolved_url = url or os.environ.get("XMEM_API_URL") or "https://api.xmemory.ai"
        self.base_url = resolved_url.rstrip("/")
        self.timeout = timeout
        self.instance_id: str | None = instance_id
        self.token: str | None = token or os.environ.get("XMEM_AUTH_TOKEN")

    def _auth_headers(self) -> dict[str, str]:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    def _healthz_url(self) -> str:
        return f"{self.base_url}/healthz"

    def _post(
        self,
        path: str,
        body: BaseModel,
        response_type: type[_T],
        *,
        op_name: str,
        timeout: int | None = None,
    ) -> _T:
        url = f"{self.base_url}{path}"
        data = json.dumps(body.model_dump()).encode("utf-8")
        headers = {"Accept": "application/json", "Content-Type": "application/json", **self._auth_headers()}
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        used_timeout = timeout if timeout is not None else self.timeout
        try:
            with urllib.request.urlopen(request, timeout=used_timeout) as resp:
                raw_body = resp.read().decode("utf-8")
                try:
                    payload_json = json.loads(raw_body) if raw_body else {}
                except json.JSONDecodeError as je:
                    raise XmemoryAPIError("Invalid JSON from server", status=resp.status) from je
                if isinstance(payload_json, dict) and payload_json.get("status") == "error":
                    error_msg = payload_json.get("error_message") or payload_json.get("error") or str(payload_json)
                    raise XmemoryAPIError(f"{op_name} failed: {error_msg}", status=resp.status)
                try:
                    return response_type.model_validate(payload_json)
                except Exception as ve:
                    raise XmemoryAPIError(
                        f"Response does not match expected schema: {ve}\nPayload: {payload_json}",
                        status=resp.status,
                    ) from ve
        except XmemoryAPIError:
            raise
        except urllib.error.HTTPError as e:
            detail = None
            try:
                raw = e.read().decode("utf-8")
                detail = raw.strip()
            except Exception:
                detail = None
            msg = f"HTTP {e.code}: {e.reason}"
            if detail:
                msg = f"{msg} — {detail}"
            raise XmemoryAPIError(msg, status=e.code) from e
        except urllib.error.URLError as e:
            raise XmemoryAPIError(f"Connection error: {e.reason}") from e
        except Exception as e:
            raise XmemoryAPIError(f"Unexpected error: {e}") from e

    def _require_instance_id(self, op: str) -> str:
        if not self.instance_id:
            raise XmemoryAPIError(f"instance_id is required for {op}() but none was provided or saved.")
        return self.instance_id

    def check_health(self) -> None:
        req = urllib.request.Request(self._healthz_url(), headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if not (200 <= resp.status < 300):
                    raise XmemoryHealthCheckError(
                        f"Health check failed with status {resp.status} at {self._healthz_url()}",
                        status=resp.status,
                    )
        except urllib.error.HTTPError as e:
            raise XmemoryHealthCheckError(
                f"Health check HTTP error {e.code} at {self._healthz_url()}: {e.reason}",
                status=e.code,
            ) from e
        except urllib.error.URLError as e:
            raise XmemoryHealthCheckError(
                f"Health check connection error at {self._healthz_url()}: {e.reason}",
            ) from e
        except Exception as e:
            raise XmemoryHealthCheckError(
                f"Health check failed due to unexpected error at {self._healthz_url()}: {e}",
            ) from e

    def read(self, query: str, *, timeout: int | None = None) -> ReadResponse:
        iid = self._require_instance_id("read")
        return self._post(
            "/read",
            _ReadRequest(instance_id=iid, query=query),
            ReadResponse,
            op_name="Read",
            timeout=timeout,
        )

    def write(self, text: str, *, extraction_logic: ExtractionLogic = ExtractionLogic.DEEP, timeout: int | None = None) -> WriteResponse:
        iid = self._require_instance_id("write")
        return self._post(
            "/write",
            _WriteRequest(instance_id=iid, text=text, extraction_logic=extraction_logic),
            WriteResponse,
            op_name="Write",
            timeout=timeout,
        )

    def extract(
        self, text: str, *, extraction_logic: ExtractionLogic = ExtractionLogic.DEEP, timeout: int | None = None
    ) -> ExtractionResponse:
        iid = self._require_instance_id("extract")
        return self._post(
            "/extract",
            _ExtractionRequest(instance_id=iid, text=text, extraction_logic=extraction_logic),
            ExtractionResponse,
            op_name="Extraction",
            timeout=timeout,
        )

    def generate_schema(
        self, schema_description: str, *, old_schema_yml: str | None = None, timeout: int | None = None
    ) -> GenerateSchemaResponse:
        return self._post(
            "/instance/generate_schema",
            _GenerateSchemaRequest(schema_description=schema_description, current_yml_schema=old_schema_yml),
            GenerateSchemaResponse,
            op_name="Generate Schema",
            timeout=timeout,
        )

    def create_instance(self, schema_text: str, schema_type: SchemaType, *, timeout: int | None = None) -> CreateInstanceResponse:
        if schema_type == SchemaType.YML:
            req_model: BaseModel = _CreateInstanceYMLRequest(yml_schema=schema_text)
        elif schema_type == SchemaType.JSON:
            req_model = _CreateInstanceJSONRequest(json_schema=schema_text)
        else:
            raise XmemoryAPIError("Unknown schema_type")
        response = self._post(
            "/instance/create",
            req_model,
            CreateInstanceResponse,
            op_name="Create instance",
            timeout=timeout,
        )
        if response.status == "ok" and response.instance_id:
            self.instance_id = response.instance_id
        return response

    def update_schema(self, schema_text: str, schema_type: SchemaType, *, timeout: int | None = None) -> bool:
        iid = self._require_instance_id("update schema")
        if schema_type == SchemaType.YML:
            req_model: BaseModel = _UpdateInstanceYMLRequest(instance_id=iid, yml_schema=schema_text)
        elif schema_type == SchemaType.JSON:
            req_model = _UpdateInstanceJSONRequest(instance_id=iid, json_schema=schema_text)
        else:
            raise XmemoryAPIError("Unknown schema_type")
        response = self._post(
            "/instance/update",
            req_model,
            _UpdateInstanceResponse,
            op_name="Update instance schema",
            timeout=timeout,
        )
        return response.status == "ok"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class XmemoryAPI:
    def __init__(
        self,
        url: str | None = None,
        *,
        timeout: int = 60,
        instance_id: str | None = None,
        token: str | None = None,
    ) -> None:
        self._client = _XmemoryClient(url=url, timeout=timeout, instance_id=instance_id, token=token)

    def check_health(self) -> None:
        return self._client.check_health()

    def read(self, query: str, *, timeout: int | None = None) -> ReadResponse:
        return self._client.read(query=query, timeout=timeout)

    def write(self, text: str, *, extraction_logic: ExtractionLogic = ExtractionLogic.DEEP, timeout: int | None = None) -> WriteResponse:
        return self._client.write(text=text, timeout=timeout, extraction_logic=extraction_logic)

    def extract(
        self, text: str, *, extraction_logic: ExtractionLogic = ExtractionLogic.DEEP, timeout: int | None = None
    ) -> ExtractionResponse:
        return self._client.extract(text=text, timeout=timeout, extraction_logic=extraction_logic)

    def generate_schema(
        self, schema_description: str, *, old_schema_yml: str | None = None, timeout: int | None = None
    ) -> GenerateSchemaResponse:
        return self._client.generate_schema(
            schema_description=schema_description, old_schema_yml=old_schema_yml, timeout=timeout
        )

    def create_instance(self, schema_text: str, schema_type: SchemaType, *, timeout: int | None = None) -> CreateInstanceResponse:
        return self._client.create_instance(schema_text=schema_text, schema_type=schema_type, timeout=timeout)

    def update_schema(self, schema_text: str, schema_type: SchemaType, *, timeout: int | None = None) -> bool:
        return self._client.update_schema(schema_text=schema_text, schema_type=schema_type, timeout=timeout)


def xmemory_instance(
    *, url: str | None = None, instance_id: str | None = None, token: str | None = None, timeout: int = 60
) -> XmemoryAPI:
    return XmemoryAPI(url=url, timeout=timeout, instance_id=instance_id, token=token)
