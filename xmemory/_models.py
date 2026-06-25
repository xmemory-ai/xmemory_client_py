from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, model_serializer, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SchemaType(Enum):
    YML = 0
    JSON = 1


class ExtractionLogic(str, Enum):
    FAST = "fast"
    DEEP = "deep"


class ReadMode(str, Enum):
    SINGLE_ANSWER = "single-answer"
    RAW_TABLES = "raw-tables"
    XRESPONSE = "xresponse"


class WriteQueueStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    # Two-phase pipeline in-progress states (server returns these when the
    # parallel-extraction path is enabled). All non-terminal — keep polling.
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    APPLYING = "applying"
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_FOUND = "not_found"


# ---------------------------------------------------------------------------
# Public resource models
# ---------------------------------------------------------------------------


class ClusterInfo(BaseModel):
    id: str
    org_id: str
    name: str
    description: str | None = None


class InstanceInfo(BaseModel):
    id: str
    cluster_id: str
    name: str
    description: str | None = None
    data_schema: dict[str, Any] | None = None
    # Schema-evolution fields — populated only by ``update_instance_schema``
    # when the call ran a (non-no-op) migration. Absent (``None``) on
    # responses from endpoints that don't migrate (get/create/list).
    migration_id: str | None = None
    prior_version: int | None = None
    new_version: int | None = None
    migration_warnings: list[str] | None = None


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
    # What the write did, grouped into ``created`` / ``updated`` / ``deleted``.
    # Absent (``None``) on responses from an older server.
    changes: Any = None


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
    data_schema: dict[str, Any]


# ---------------------------------------------------------------------------
# Describe models
# ---------------------------------------------------------------------------


class ToolParameterDescription(BaseModel):
    name: str
    type: str
    description: str
    required: bool = True
    enum: list[str] | None = None
    default: str | None = None


class ToolDescription(BaseModel):
    name: str
    description: str
    when_to_use: str
    parameters: list[ToolParameterDescription]
    http_method: str
    http_path: str


class DescribeResult(BaseModel):
    """Agent-facing tool descriptions for an instance, with format helpers."""

    instance_id: str
    instance_name: str
    about: str = ""
    schema_summary: str
    tools: list[ToolDescription]

    def as_text(self, *, include_http: bool = False) -> str:
        """Return a plain-text representation suitable for injecting into an LLM system prompt.

        By default, tools are presented as method calls (matching the SDK).
        Set *include_http* to ``True`` to also show HTTP method and path for
        raw REST callers.
        """
        lines: list[str] = []
        lines.append(f"Instance: {self.instance_name} ({self.instance_id})")
        if self.about:
            lines.append(f"\n{self.about}")
        if self.schema_summary:
            lines.append(f"\n{self.schema_summary}")
        lines.append("\nAvailable tools:\n")
        for tool in self.tools:
            params_sig = ", ".join(
                p.name + ("?" if not p.required else "") for p in tool.parameters
            )
            lines.append(f"## {tool.name}({params_sig})")
            lines.append(tool.description)
            lines.append(f"When to use: {tool.when_to_use}")
            if include_http:
                lines.append(f"HTTP: {tool.http_method} {tool.http_path}")
            if tool.parameters:
                lines.append("Parameters:")
                for p in tool.parameters:
                    req = "required" if p.required else "optional"
                    parts = [f"  - {p.name} ({p.type}, {req}): {p.description}"]
                    if p.enum:
                        parts.append(f"    Allowed values: {', '.join(p.enum)}")
                    if p.default is not None:
                        parts.append(f"    Default: {p.default}")
                    lines.extend(parts)
            lines.append("")
        return "\n".join(lines)

    def as_anthropic_tools(self) -> list[dict[str, Any]]:
        """Return tool definitions in the Anthropic tool-use format."""
        result: list[dict[str, Any]] = []
        for tool in self.tools:
            properties: dict[str, Any] = {}
            required: list[str] = []
            for p in tool.parameters:
                prop: dict[str, Any] = {"type": p.type, "description": p.description}
                if p.enum:
                    prop["enum"] = p.enum
                properties[p.name] = prop
                if p.required:
                    required.append(p.name)
            result.append({
                "name": tool.name,
                "description": f"{tool.description}\n\nWhen to use: {tool.when_to_use}",
                "input_schema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            })
        return result

    def as_openai_tools(self) -> list[dict[str, Any]]:
        """Return tool definitions in the OpenAI function-calling format."""
        result: list[dict[str, Any]] = []
        for tool in self.tools:
            properties: dict[str, Any] = {}
            required: list[str] = []
            for p in tool.parameters:
                prop: dict[str, Any] = {"type": p.type, "description": p.description}
                if p.enum:
                    prop["enum"] = p.enum
                properties[p.name] = prop
                if p.required:
                    required.append(p.name)
            result.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": f"{tool.description}\n\nWhen to use: {tool.when_to_use}",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            })
        return result


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
    # Schema-evolution: a serialized MigrationPlan and the destructive gate.
    # Both default to the legacy additive-only behaviour, so old callers that
    # only set ``instance_schema`` are unaffected.
    migration_plan: dict[str, Any] | None = None
    confirm_destructive: bool = False


class _DryRunMigrationRequest(BaseModel):
    instance_schema: _InstanceSchema
    migration_plan: dict[str, Any] | None = None
    confirm_destructive: bool = False


class _UpdateMetadataRequest(BaseModel):
    name: str
    description: str | None


class _GenerateSchemaRequest(BaseModel):
    schema_description: str
    current_yml_schema: str | dict[str, Any] | None = None


class ScopeObject(BaseModel):
    """One concrete object a scoped read is allowed to touch.

    Identify the object by its ``type`` (PascalCase class name or snake_case
    table name) plus its user-defined primary ``key`` (a mapping of primary-key
    field name to value).

    Serialized to the API's identity wire shape — ``{"type": ..., "key": {"key": {...}}}``.
    """

    type: str
    key: dict[str, str | int | float | bool]

    @model_validator(mode="after")
    def _non_empty_key(self) -> ScopeObject:
        if not self.key:
            raise ValueError("ScopeObject 'key' must contain at least one primary-key field.")
        return self

    @model_serializer
    def _serialize(self) -> dict[str, Any]:
        return {"type": self.type, "key": {"key": self.key}}


class ReadScope(BaseModel):
    """A read's scope: the concrete objects it may touch, plus relation policy.

    ``relations_scope`` is ``no_relations`` (objects only) by default;
    ``all_relations`` also exposes the relations among the in-scope ``objects``.
    """

    objects: list[ScopeObject]
    relations_scope: Literal["no_relations", "all_relations"] = "no_relations"


class _ReadRequest(BaseModel):
    query: str
    mode: ReadMode = ReadMode.SINGLE_ANSWER
    scope: ReadScope | None = None
    read_id: str | None = None


class _WriteRequest(BaseModel):
    text: str
    extraction_logic: ExtractionLogic = ExtractionLogic.FAST
    use_diff_engine: bool | None = None


class _ExtractRequest(BaseModel):
    text: str
    extraction_logic: ExtractionLogic = ExtractionLogic.FAST


class _WriteStatusRequest(BaseModel):
    write_id: str


# ---------------------------------------------------------------------------
# Internal response wrapper
# ---------------------------------------------------------------------------


class _ApiError(BaseModel):
    code: str
    message: str
    field: str | None = None
    resource_id: str | None = None


class _RawApiResponse(BaseModel):
    ids: list[str] = []
    items: list[Any] = []
    errors: list[_ApiError] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_instance_schema(schema_text: str, schema_type: SchemaType) -> _InstanceSchema:
    if schema_type == SchemaType.YML:
        return _InstanceSchema(yml=_SchemaPayload(value=schema_text))
    return _InstanceSchema(json_schema=_SchemaPayload(value=schema_text))
