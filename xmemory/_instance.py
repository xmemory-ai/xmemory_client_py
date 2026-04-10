import threading
import time

from xmemory._models import (
    AsyncWriteResult,
    DescribeResult,
    ExtractResult,
    ExtractionLogic,
    InstanceInfo,
    InstanceSchemaInfo,
    ReadMode,
    ReadResult,
    SchemaType,
    WriteResult,
    WriteStatusResult,
    _ExtractRequest,
    _ReadRequest,
    _UpdateMetadataRequest,
    _UpdateSchemaRequest,
    _WriteRequest,
    _WriteStatusRequest,
    build_instance_schema,
)
from xmemory._transport import AsyncTransport, SyncTransport

_DEFAULT_DESCRIBE_TTL_SECONDS: float = 300.0  # 5 minutes


class InstanceAPI:
    """Instance-bound client for data operations and instance management (sync)."""

    def __init__(self, instance_id: str, transport: SyncTransport) -> None:
        self._id = instance_id
        self._t = transport
        self._describe_cache: DescribeResult | None = None
        self._describe_cache_at: float = 0.0
        self._describe_ttl: float = _DEFAULT_DESCRIBE_TTL_SECONDS
        self._describe_lock = threading.Lock()

    @property
    def id(self) -> str:
        return self._id

    # -- Data operations ------------------------------------------------------

    def read(
        self,
        query: str,
        *,
        read_mode: ReadMode = ReadMode.SINGLE_ANSWER,
        read_id: str | None = None,
        timeout: float | None = None,
    ) -> ReadResult:
        """Query this instance and return a structured answer."""
        return self._t.request_one(
            "POST", f"/instances/{self._id}/read", ReadResult,
            body=_ReadRequest(query=query, mode=read_mode, read_id=read_id),
            timeout=timeout,
        )

    def write(
        self,
        text: str,
        *,
        extraction_logic: ExtractionLogic = ExtractionLogic.DEEP,
        diff_engine: bool | None = None,
        timeout: float | None = None,
    ) -> WriteResult:
        """Extract structured data from text and persist it to this instance."""
        return self._t.request_one(
            "POST", f"/instances/{self._id}/write", WriteResult,
            body=_WriteRequest(text=text, extraction_logic=extraction_logic, use_diff_engine=diff_engine),
            timeout=timeout,
        )

    def write_async(
        self,
        text: str,
        *,
        extraction_logic: ExtractionLogic = ExtractionLogic.DEEP,
        diff_engine: bool | None = None,
        timeout: float | None = None,
    ) -> AsyncWriteResult:
        """Submit a write job and return immediately with a write_id for polling."""
        return self._t.request_one(
            "POST", f"/instances/{self._id}/write_async", AsyncWriteResult,
            body=_WriteRequest(text=text, extraction_logic=extraction_logic, use_diff_engine=diff_engine),
            timeout=timeout,
        )

    def write_status(self, write_id: str, *, timeout: float | None = None) -> WriteStatusResult:
        """Poll the status of an async write job."""
        return self._t.request_one(
            "POST", f"/instances/{self._id}/write_status", WriteStatusResult,
            body=_WriteStatusRequest(write_id=write_id),
            timeout=timeout,
        )

    def extract(
        self,
        text: str,
        *,
        extraction_logic: ExtractionLogic = ExtractionLogic.DEEP,
        timeout: float | None = None,
    ) -> ExtractResult:
        """Extract structured data from text without persisting it."""
        return self._t.request_one(
            "POST", f"/instances/{self._id}/extract", ExtractResult,
            body=_ExtractRequest(text=text, extraction_logic=extraction_logic),
            timeout=timeout,
        )

    def get_schema(self, *, timeout: float | None = None) -> InstanceSchemaInfo:
        """Get the current schema of this instance."""
        return self._t.request_one(
            "GET", f"/instances/{self._id}/schema", InstanceSchemaInfo, timeout=timeout,
        )

    # -- Instance management ---------------------------------------------------

    def update_schema(
        self,
        schema_text: str,
        schema_type: SchemaType,
        *,
        timeout: float | None = None,
    ) -> InstanceInfo:
        """Replace the schema of this instance."""
        return self._t.request_one(
            "PUT", f"/instances/{self._id}/schema", InstanceInfo,
            body=_UpdateSchemaRequest(instance_schema=build_instance_schema(schema_text, schema_type)),
            timeout=timeout,
        )

    def update_metadata(
        self,
        name: str,
        description: str | None,
        *,
        timeout: float | None = None,
    ) -> InstanceInfo:
        """Update the name and description of this instance."""
        return self._t.request_one(
            "PUT", f"/instances/{self._id}", InstanceInfo,
            body=_UpdateMetadataRequest(name=name, description=description),
            timeout=timeout,
        )

    def delete(self, *, timeout: float | None = None) -> list[str]:
        """Delete this instance and all its data. Returns the list of deleted IDs."""
        return self._t.request_ids("DELETE", f"/instances/{self._id}", timeout=timeout)

    # -- Describe (agent tool descriptions) -----------------------------------

    def describe(self, *, timeout: float | None = None) -> DescribeResult:
        """Return agent-facing tool descriptions enriched with the instance schema.

        Results are cached locally with a TTL (default 5 min).
        Call ``clear_describe_cache()`` to force a refresh.
        Thread-safe.
        """
        with self._describe_lock:
            now = time.monotonic()
            if self._describe_cache is not None and (now - self._describe_cache_at) < self._describe_ttl:
                return self._describe_cache
        result = self._t.request_one(
            "GET", f"/instances/{self._id}/describe", DescribeResult, timeout=timeout,
        )
        with self._describe_lock:
            self._describe_cache = result
            self._describe_cache_at = time.monotonic()
        return result

    def clear_describe_cache(self) -> None:
        """Clear the cached describe result so the next ``describe()`` call fetches fresh data."""
        with self._describe_lock:
            self._describe_cache = None
            self._describe_cache_at = 0.0


class AsyncInstanceAPI:
    """Instance-bound client for data operations and instance management (async)."""

    def __init__(self, instance_id: str, transport: AsyncTransport) -> None:
        self._id = instance_id
        self._t = transport
        self._describe_cache: DescribeResult | None = None
        self._describe_cache_at: float = 0.0
        self._describe_ttl: float = _DEFAULT_DESCRIBE_TTL_SECONDS

    @property
    def id(self) -> str:
        return self._id

    # -- Data operations ------------------------------------------------------

    async def read(
        self,
        query: str,
        *,
        read_mode: ReadMode = ReadMode.SINGLE_ANSWER,
        read_id: str | None = None,
        timeout: float | None = None,
    ) -> ReadResult:
        """Query this instance and return a structured answer."""
        return await self._t.request_one(
            "POST", f"/instances/{self._id}/read", ReadResult,
            body=_ReadRequest(query=query, mode=read_mode, read_id=read_id),
            timeout=timeout,
        )

    async def write(
        self,
        text: str,
        *,
        extraction_logic: ExtractionLogic = ExtractionLogic.DEEP,
        diff_engine: bool | None = None,
        timeout: float | None = None,
    ) -> WriteResult:
        """Extract structured data from text and persist it to this instance."""
        return await self._t.request_one(
            "POST", f"/instances/{self._id}/write", WriteResult,
            body=_WriteRequest(text=text, extraction_logic=extraction_logic, use_diff_engine=diff_engine),
            timeout=timeout,
        )

    async def write_async(
        self,
        text: str,
        *,
        extraction_logic: ExtractionLogic = ExtractionLogic.DEEP,
        diff_engine: bool | None = None,
        timeout: float | None = None,
    ) -> AsyncWriteResult:
        """Submit a write job and return immediately with a write_id for polling."""
        return await self._t.request_one(
            "POST", f"/instances/{self._id}/write_async", AsyncWriteResult,
            body=_WriteRequest(text=text, extraction_logic=extraction_logic, use_diff_engine=diff_engine),
            timeout=timeout,
        )

    async def write_status(self, write_id: str, *, timeout: float | None = None) -> WriteStatusResult:
        """Poll the status of an async write job."""
        return await self._t.request_one(
            "POST", f"/instances/{self._id}/write_status", WriteStatusResult,
            body=_WriteStatusRequest(write_id=write_id),
            timeout=timeout,
        )

    async def extract(
        self,
        text: str,
        *,
        extraction_logic: ExtractionLogic = ExtractionLogic.DEEP,
        timeout: float | None = None,
    ) -> ExtractResult:
        """Extract structured data from text without persisting it."""
        return await self._t.request_one(
            "POST", f"/instances/{self._id}/extract", ExtractResult,
            body=_ExtractRequest(text=text, extraction_logic=extraction_logic),
            timeout=timeout,
        )

    async def get_schema(self, *, timeout: float | None = None) -> InstanceSchemaInfo:
        """Get the current schema of this instance."""
        return await self._t.request_one(
            "GET", f"/instances/{self._id}/schema", InstanceSchemaInfo, timeout=timeout,
        )

    # -- Instance management ---------------------------------------------------

    async def update_schema(
        self,
        schema_text: str,
        schema_type: SchemaType,
        *,
        timeout: float | None = None,
    ) -> InstanceInfo:
        """Replace the schema of this instance."""
        return await self._t.request_one(
            "PUT", f"/instances/{self._id}/schema", InstanceInfo,
            body=_UpdateSchemaRequest(instance_schema=build_instance_schema(schema_text, schema_type)),
            timeout=timeout,
        )

    async def update_metadata(
        self,
        name: str,
        description: str | None,
        *,
        timeout: float | None = None,
    ) -> InstanceInfo:
        """Update the name and description of this instance."""
        return await self._t.request_one(
            "PUT", f"/instances/{self._id}", InstanceInfo,
            body=_UpdateMetadataRequest(name=name, description=description),
            timeout=timeout,
        )

    async def delete(self, *, timeout: float | None = None) -> list[str]:
        """Delete this instance and all its data. Returns the list of deleted IDs."""
        return await self._t.request_ids("DELETE", f"/instances/{self._id}", timeout=timeout)

    # -- Describe (agent tool descriptions) -----------------------------------

    async def describe(self, *, timeout: float | None = None) -> DescribeResult:
        """Return agent-facing tool descriptions enriched with the instance schema.

        Results are cached locally with a TTL (default 5 min).
        Call ``clear_describe_cache()`` to force a refresh.
        """
        now = time.monotonic()
        if self._describe_cache is not None and (now - self._describe_cache_at) < self._describe_ttl:
            return self._describe_cache
        result = await self._t.request_one(
            "GET", f"/instances/{self._id}/describe", DescribeResult, timeout=timeout,
        )
        self._describe_cache = result
        self._describe_cache_at = now
        return result

    def clear_describe_cache(self) -> None:
        """Clear the cached describe result so the next ``describe()`` call fetches fresh data."""
        self._describe_cache = None
        self._describe_cache_at = 0.0