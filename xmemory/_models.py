from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Enums
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


class WriteQueueStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_FOUND = "not_found"


# ---------------------------------------------------------------------------
# Public resource models
# ---------------------------------------------------------------------------


class ClusterInfo(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None = None


class InstanceInfo(BaseModel):
    id: uuid.UUID
    cluster_id: uuid.UUID
    name: str
    description: str | None = None
    data_schema: dict[str, Any] | None = None


class InstanceSchemaInfo(BaseModel):
    data_schema: dict[str, Any]


# ---------------------------------------------------------------------------
# Public response models
# ---------------------------------------------------------------------------


class ReadResult(BaseModel):
    trace_id: str | None = None
    reader_result: Any = None


class WriteResult(BaseModel):
    write_id: str
    trace_id: str | None = None
    cleaned_objects: Any = None
    diff_plan: Any = None


class AsyncWriteResult(BaseModel):
    write_id: str


class WriteStatusResult(BaseModel):
    write_id: str
    write_status: WriteQueueStatus
    error_detail: str | None = None
    completed_at: datetime | None = None


class ExtractResult(BaseModel):
    trace_id: str | None = None
    objects_extracted: Any = None


class GenerateSchemaResult(BaseModel):
    generated_schema: dict[str, Any]


# ---------------------------------------------------------------------------
# Internal request models
# ---------------------------------------------------------------------------


class _SchemaPayload(BaseModel):
    value: str | dict[str, Any]


class _InstanceSchema(BaseModel):
    yml: _SchemaPayload | None = None
    json_schema: _SchemaPayload | None = None


class _CreateInstanceRequest(BaseModel):
    name: str
    description: str | None = None
    instance_schema: _InstanceSchema
    schema_description: str | None = None


class _UpdateSchemaRequest(BaseModel):
    instance_schema: _InstanceSchema


class _UpdateMetadataRequest(BaseModel):
    name: str
    description: str | None


class _GenerateSchemaRequest(BaseModel):
    schema_description: str
    current_yml_schema: str | dict[str, Any] | None = None


class _ReadRequest(BaseModel):
    query: str
    mode: ReadMode = ReadMode.SINGLE_ANSWER
    read_id: str | None = None


class _WriteRequest(BaseModel):
    text: str
    extraction_logic: ExtractionLogic = ExtractionLogic.DEEP
    use_diff_engine: bool | None = None


class _ExtractRequest(BaseModel):
    text: str
    extraction_logic: ExtractionLogic = ExtractionLogic.DEEP


class _WriteStatusRequest(BaseModel):
    write_id: str


# ---------------------------------------------------------------------------
# Internal response wrapper
# ---------------------------------------------------------------------------


class _ApiError(BaseModel):
    code: str
    message: str
    field: str | None = None
    resource_id: uuid.UUID | None = None


class _RawApiResponse(BaseModel):
    ids: list[uuid.UUID] = []
    items: list[Any] = []
    errors: list[_ApiError] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_instance_schema(schema_text: str, schema_type: SchemaType) -> _InstanceSchema:
    if schema_type == SchemaType.YML:
        return _InstanceSchema(yml=_SchemaPayload(value=schema_text))
    return _InstanceSchema(json_schema=_SchemaPayload(value=schema_text))
