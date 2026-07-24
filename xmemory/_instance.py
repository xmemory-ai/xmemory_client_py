import threading
import time
from typing import Any

from pydantic import BaseModel

from xmemory._models import (
    AsyncWriteResult,
    DescribeResult,
    ExtractResult,
    ExtractionLogic,
    InstanceSchemaInfo,
    ReadMode,
    ReadResult,
    ReadScope,
    WriteMutation,
    WriteResult,
    WriteStatusResult,
    _ExtractRequest,
    _ReadRequest,
    _WriteRequest,
    _WriteStatusRequest,
)
from xmemory._schema_evolution import (
    ApplyPendingDecisionsResult,
    DecideSuggestionsResult,
    DecisionInput,
    ReviewSuggestionsResult,
    _ApplyPendingDecisionsRequest,
    _DecideSuggestionsRequest,
    _ReviewSuggestionsRequest,
)
from xmemory._transport import AsyncTransport, SyncTransport

_DEFAULT_DESCRIBE_TTL_SECONDS: float = 300.0  # 5 minutes


def _build_write_request(
    text: str,
    structured_mutations: list[WriteMutation | dict[str, Any]] | None,
    extraction_logic: ExtractionLogic,
    diff_engine: bool | None,
) -> _WriteRequest:
    """Validate the text/structured_mutations exclusivity and build the request body."""
    if bool(text) == (structured_mutations is not None):
        raise ValueError("Provide exactly one of 'text' or 'structured_mutations'.")
    if structured_mutations is not None and not structured_mutations:
        raise ValueError("'structured_mutations' must contain at least one mutation.")
    return _WriteRequest(
        text=text,
        extraction_logic=extraction_logic,
        use_diff_engine=diff_engine,
        structured_mutations=None if structured_mutations is None else [
            m.model_dump() if isinstance(m, BaseModel) else m for m in structured_mutations
        ],
    )


class InstanceAPI:
    """Instance-bound client for data operations (sync)."""

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
        scope: ReadScope | None = None,
        read_id: str | None = None,
        timeout: float | None = None,
    ) -> ReadResult:
        """Query this instance and return a structured answer.

        Pass ``scope`` (a :class:`ReadScope` of concrete :class:`ScopeObject`\\ s,
        each identified by its user-defined primary key) to restrict the read;
        set ``ReadScope.relations_scope='all_relations'`` to also expose relations among them.
        """
        return self._t.request_one(
            "POST", f"/instances/{self._id}/read", ReadResult,
            body=_ReadRequest(query=query, mode=read_mode, scope=scope, read_id=read_id),
            timeout=timeout,
        )

    def write(
        self,
        text: str = "",
        *,
        structured_mutations: list[WriteMutation | dict[str, Any]] | None = None,
        extraction_logic: ExtractionLogic = ExtractionLogic.FAST,
        diff_engine: bool | None = None,
        timeout: float | None = None,
    ) -> WriteResult:
        """Write to this instance: extract from free text, or apply structured mutations.

        Pass ``text`` to extract structured data from free-form text, or
        ``structured_mutations`` — a list of :class:`ObjectMutation` /
        :class:`RelationMutation` (or equivalent plain dicts in the wire form,
        e.g. ``{"object_mutation": {"object_type": "person", "update":
        {"key": {...}, "values": {...}}}}``) — to apply deterministic,
        LLM-free edits. Exactly
        one of the two must be provided. Mutations are applied in list order;
        later mutations may reference objects created earlier in the batch, and
        a ``None`` value in a mutation's ``values`` clears that field.

        ``extraction_logic`` and ``diff_engine`` only affect the ``text`` path.
        """
        return self._t.request_one(
            "POST", f"/instances/{self._id}/write", WriteResult,
            body=_build_write_request(text, structured_mutations, extraction_logic, diff_engine),
            timeout=timeout,
        )

    def write_async(
        self,
        text: str = "",
        *,
        structured_mutations: list[WriteMutation | dict[str, Any]] | None = None,
        extraction_logic: ExtractionLogic = ExtractionLogic.FAST,
        diff_engine: bool | None = None,
        timeout: float | None = None,
    ) -> AsyncWriteResult:
        """Submit a write job and return immediately with a write_id for polling.

        Accepts the same ``text`` / ``structured_mutations`` dual input as
        :meth:`write` (exactly one of the two).
        """
        return self._t.request_one(
            "POST", f"/instances/{self._id}/write_async", AsyncWriteResult,
            body=_build_write_request(text, structured_mutations, extraction_logic, diff_engine),
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
        extraction_logic: ExtractionLogic = ExtractionLogic.FAST,
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

    # -- Schema evolution (suggestion engine) ---------------------------------

    def review_suggestions(
        self, *, session_id: str | None = None, timeout: float | None = None,
    ) -> ReviewSuggestionsResult:
        """Return the current consolidated schema-improvement proposal.

        Step 1 of the suggestion-engine flow. The result's
        ``proposal.proposal_version`` is the optimistic-concurrency token you
        pass to :meth:`decide_suggestions` and :meth:`apply_pending_decisions`.
        ``status == "evolution_in_progress"`` means a migration is in flight —
        back off for ``retry_after_seconds`` and retry.
        """
        return self._t.request_one(
            "POST", f"/instances/{self._id}/suggestions/review", ReviewSuggestionsResult,
            body=_ReviewSuggestionsRequest(session_id=session_id),
            timeout=timeout,
        )

    def decide_suggestions(
        self,
        proposal_version: str,
        decisions: list[DecisionInput],
        *,
        session_id: str | None = None,
        timeout: float | None = None,
    ) -> DecideSuggestionsResult:
        """Record accept/reject/defer decisions for proposal items (step 2).

        ``proposal_version`` must be the token from the latest
        :meth:`review_suggestions`; a stale token raises ``XmemoryAPIError``
        with ``code == "stale_proposal_version"``. The result's
        ``next_proposal_version`` can be passed straight to
        :meth:`apply_pending_decisions`.
        """
        return self._t.request_one(
            "POST", f"/instances/{self._id}/suggestions/decide", DecideSuggestionsResult,
            body=_DecideSuggestionsRequest(
                proposal_version=proposal_version, decisions=decisions, session_id=session_id,
            ),
            timeout=timeout,
        )

    def apply_pending_decisions(
        self, proposal_version: str, *, session_id: str | None = None, timeout: float | None = None,
    ) -> ApplyPendingDecisionsResult:
        """Commit accepted decisions as a single migration (step 3).

        ``status == "nothing_to_apply"`` means no accepted items were left.
        A stale ``proposal_version`` or an unmet dependency raises
        ``XmemoryAPIError`` (``code == "stale_proposal_version"`` /
        ``"dependency_closure_failed"``).
        """
        return self._t.request_one(
            "POST", f"/instances/{self._id}/suggestions/apply", ApplyPendingDecisionsResult,
            body=_ApplyPendingDecisionsRequest(proposal_version=proposal_version, session_id=session_id),
            timeout=timeout,
        )

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
    """Instance-bound client for data operations (async)."""

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
        scope: ReadScope | None = None,
        read_id: str | None = None,
        timeout: float | None = None,
    ) -> ReadResult:
        """Query this instance and return a structured answer.

        Pass ``scope`` (a :class:`ReadScope` of concrete :class:`ScopeObject`\\ s,
        each identified by its user-defined primary key) to restrict the read;
        set ``ReadScope.relations_scope='all_relations'`` to also expose relations among them.
        """
        return await self._t.request_one(
            "POST", f"/instances/{self._id}/read", ReadResult,
            body=_ReadRequest(query=query, mode=read_mode, scope=scope, read_id=read_id),
            timeout=timeout,
        )

    async def write(
        self,
        text: str = "",
        *,
        structured_mutations: list[WriteMutation | dict[str, Any]] | None = None,
        extraction_logic: ExtractionLogic = ExtractionLogic.FAST,
        diff_engine: bool | None = None,
        timeout: float | None = None,
    ) -> WriteResult:
        """Write to this instance: extract from free text, or apply structured mutations.

        Pass ``text`` to extract structured data from free-form text, or
        ``structured_mutations`` — a list of :class:`ObjectMutation` /
        :class:`RelationMutation` (or equivalent plain dicts in the wire form,
        e.g. ``{"object_mutation": {"object_type": "person", "update":
        {"key": {...}, "values": {...}}}}``) — to apply deterministic,
        LLM-free edits. Exactly
        one of the two must be provided. Mutations are applied in list order;
        later mutations may reference objects created earlier in the batch, and
        a ``None`` value in a mutation's ``values`` clears that field.

        ``extraction_logic`` and ``diff_engine`` only affect the ``text`` path.
        """
        return await self._t.request_one(
            "POST", f"/instances/{self._id}/write", WriteResult,
            body=_build_write_request(text, structured_mutations, extraction_logic, diff_engine),
            timeout=timeout,
        )

    async def write_async(
        self,
        text: str = "",
        *,
        structured_mutations: list[WriteMutation | dict[str, Any]] | None = None,
        extraction_logic: ExtractionLogic = ExtractionLogic.FAST,
        diff_engine: bool | None = None,
        timeout: float | None = None,
    ) -> AsyncWriteResult:
        """Submit a write job and return immediately with a write_id for polling.

        Accepts the same ``text`` / ``structured_mutations`` dual input as
        :meth:`write` (exactly one of the two).
        """
        return await self._t.request_one(
            "POST", f"/instances/{self._id}/write_async", AsyncWriteResult,
            body=_build_write_request(text, structured_mutations, extraction_logic, diff_engine),
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
        extraction_logic: ExtractionLogic = ExtractionLogic.FAST,
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

    # -- Schema evolution (suggestion engine) ---------------------------------

    async def review_suggestions(
        self, *, session_id: str | None = None, timeout: float | None = None,
    ) -> ReviewSuggestionsResult:
        """Return the current consolidated schema-improvement proposal.

        Step 1 of the suggestion-engine flow. The result's
        ``proposal.proposal_version`` is the optimistic-concurrency token you
        pass to :meth:`decide_suggestions` and :meth:`apply_pending_decisions`.
        ``status == "evolution_in_progress"`` means a migration is in flight —
        back off for ``retry_after_seconds`` and retry.
        """
        return await self._t.request_one(
            "POST", f"/instances/{self._id}/suggestions/review", ReviewSuggestionsResult,
            body=_ReviewSuggestionsRequest(session_id=session_id),
            timeout=timeout,
        )

    async def decide_suggestions(
        self,
        proposal_version: str,
        decisions: list[DecisionInput],
        *,
        session_id: str | None = None,
        timeout: float | None = None,
    ) -> DecideSuggestionsResult:
        """Record accept/reject/defer decisions for proposal items (step 2).

        ``proposal_version`` must be the token from the latest
        :meth:`review_suggestions`; a stale token raises ``XmemoryAPIError``
        with ``code == "stale_proposal_version"``. The result's
        ``next_proposal_version`` can be passed straight to
        :meth:`apply_pending_decisions`.
        """
        return await self._t.request_one(
            "POST", f"/instances/{self._id}/suggestions/decide", DecideSuggestionsResult,
            body=_DecideSuggestionsRequest(
                proposal_version=proposal_version, decisions=decisions, session_id=session_id,
            ),
            timeout=timeout,
        )

    async def apply_pending_decisions(
        self, proposal_version: str, *, session_id: str | None = None, timeout: float | None = None,
    ) -> ApplyPendingDecisionsResult:
        """Commit accepted decisions as a single migration (step 3).

        ``status == "nothing_to_apply"`` means no accepted items were left.
        A stale ``proposal_version`` or an unmet dependency raises
        ``XmemoryAPIError`` (``code == "stale_proposal_version"`` /
        ``"dependency_closure_failed"``).
        """
        return await self._t.request_one(
            "POST", f"/instances/{self._id}/suggestions/apply", ApplyPendingDecisionsResult,
            body=_ApplyPendingDecisionsRequest(proposal_version=proposal_version, session_id=session_id),
            timeout=timeout,
        )

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