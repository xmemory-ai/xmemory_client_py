from __future__ import annotations

from xmemory._models import (
    AsyncWriteResult,
    ExtractResult,
    ExtractionLogic,
    InstanceSchemaInfo,
    ReadMode,
    ReadResult,
    WriteResult,
    WriteStatusResult,
    _ExtractRequest,
    _ReadRequest,
    _WriteRequest,
    _WriteStatusRequest,
)
from xmemory._transport import AsyncTransport, SyncTransport


class InstanceAPI:
    """Instance-bound client for data operations and instance management (sync)."""

    def __init__(self, instance_id: str, transport: SyncTransport) -> None:
        self._id = instance_id
        self._t = transport

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


class AsyncInstanceAPI:
    """Instance-bound client for data operations and instance management (async)."""

    def __init__(self, instance_id: str, transport: AsyncTransport) -> None:
        self._id = instance_id
        self._t = transport

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


