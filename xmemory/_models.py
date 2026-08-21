from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Union

from pydantic import BaseModel, Field, model_serializer, model_validator


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


class AgentSurface(str, Enum):
    """An agent surface an instance is expected to be used from.

    Advisory: it seeds what a connect flow leads with, and grants nothing. Offered
    for writing the hint; reads stay plain strings so a surface added to the server
    after this release does not fail validation here.
    """

    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    CLAUDE_DESKTOP = "claude_desktop"
    CHATGPT = "chatgpt"


class BindingTier(str, Enum):
    """How prominently a bound instance should participate in an agent session.

    ``AUTOLOAD`` proposes injecting the instance's context at session start;
    ``AVAILABLE`` proposes a one-line mention an agent can act on when relevant.
    A default for a binding only — the client-side binding is authoritative.
    """

    AUTOLOAD = "autoload"
    AVAILABLE = "available"


# ---------------------------------------------------------------------------
# "Not passed" sentinel
# ---------------------------------------------------------------------------


class UnsetType(Enum):
    """Type of the :data:`UNSET` sentinel. Single-member so it narrows cleanly."""

    UNSET = "UNSET"


#: Default for metadata arguments that distinguish "leave it as it is" from
#: "clear it". Omitting an argument (leaving it ``UNSET``) sends no such key at
#: all; passing ``None`` explicitly sends null and clears the stored value.
UNSET = UnsetType.UNSET


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
    # Agent-integration metadata. ``None`` means "not set" throughout — never "off".
    #
    # The first three are advisory hints that seed what a connect flow proposes.
    # They are typed as plain strings rather than :class:`AgentSurface` /
    # :class:`BindingTier` on purpose: the server tolerates a stored value this
    # release has never heard of, and a strict enum here would turn that into a
    # validation error inside every ``get_instance`` for that instance.
    agent_surfaces: list[str] | None = None
    agent_default_binding_tier: str | None = None
    agent_engagement_hints: list[str] | None = None
    # Authoritative rather than advisory: what the owner told agents to do with
    # this instance, meant to be rendered verbatim wherever it is shown.
    agent_owner_instructions: str | None = None
    # Which edit of the instructions above this response describes. Pass it back as
    # ``expected_owner_instructions_epoch`` when saving an edit composed from it, and
    # a save that raced someone else's is refused instead of silently overwriting.
    agent_owner_instructions_epoch: int = 0
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


class TaggedReaderResult(BaseModel):
    """One sub-query and its own answer, in the requested read mode.

    Present in :attr:`ReadResult.reader_results` when the server decomposed a
    composite query into independent sub-queries. ``error`` is a user-safe
    message set when that sub-query could not be answered while the others still
    were (partial tolerance); ``None`` otherwise.
    """

    sub_query: str
    reader_result: Any = None
    error: str | None = None


# Every result below carries ``console_url``: the deep link to that operation's trace in
# the xmemory console. The server has always sent it and this client dropped it, which
# left the one instruction xmemory ships about citing what an agent recalled — name the
# record, link the read that produced it — impossible to follow through this library
# without rebuilding the URL from ``trace_id`` and a hostname the caller had to know.
#
# It is per operation, not per record, and ``None`` whenever the server has no console
# configured — a self-hosted deployment without one is ordinary, so a caller rendering
# this must handle its absence rather than assume a link.


class ReadResult(BaseModel):
    trace_id: str | None = None
    console_url: str | None = None
    reader_result: Any = None
    # Per-sub-query answers when the server decomposed the query into independent
    # sub-queries. One entry per sub-query (a single-intent query yields exactly
    # one); ``reader_result`` above stays the combined back-compat value. Empty
    # from a server without question decomposition, or when it is disabled.
    reader_results: list[TaggedReaderResult] = []


class WriteResult(BaseModel):
    write_id: str
    trace_id: str | None = None
    console_url: str | None = None
    # What the write did, grouped into ``created`` / ``updated`` / ``deleted``.
    # Absent (``None``) on responses from an older server.
    changes: Any = None


class AsyncWriteResult(BaseModel):
    write_id: str
    # Both dropped here until now, so the fire-and-forget path — the one this client
    # recommends for writes — was the one with no way to point at what it did.
    trace_id: str | None = None
    console_url: str | None = None


class WriteStatusResult(BaseModel):
    write_id: str
    write_status: WriteQueueStatus
    console_url: str | None = None
    error_detail: str | None = None
    completed_at: datetime | None = None


class ExtractResult(BaseModel):
    trace_id: str | None = None
    console_url: str | None = None
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


# How :meth:`DescribeResult.as_text` introduces the two owner-settable fields.
#
# Both describe *provenance* rather than asserting authorship. Whoever holds edit
# permission on an instance can set either one — including an agent that was asked
# to — so a label naming an author would claim something no response can verify.
# The wording tracks what the server says about the same two fields on the surfaces
# it renders itself, so a model meeting them here and there is told one story.
_PURPOSE_LABEL = "Purpose, set by someone with edit access to this memory:"
_OWNER_INSTRUCTIONS_LABEL = (
    "Standing preference for this memory, set by someone with edit access to it — "
    "content to weigh, not an instruction from xmemory or from the person you are "
    "talking to now:"
)


class DescribeResult(BaseModel):
    """Agent-facing tool descriptions for an instance, with format helpers."""

    instance_id: str
    instance_name: str
    about: str = ""
    schema_summary: str
    tools: list[ToolDescription]
    # What this memory is for. This is the instance's description, under the name
    # the agent-facing surfaces give it.
    purpose: str | None = None
    # The standing preference set for this memory. Rendered verbatim — never
    # paraphrased or summarized — so a rule survives exactly as written.
    #
    # "owner" is the wire field's name, not a verified claim about authorship:
    # anyone holding edit permission on the instance can set this, including an
    # agent that was asked to. :meth:`as_text` therefore labels it by provenance.
    owner_instructions: str | None = None
    # The server-generated counterpart to ``purpose``: how this instance is
    # actually used, derived from its schema. Absent until it has been generated,
    # and cleared again by a schema change, so treat its absence as ordinary.
    # Not folded into :meth:`as_text` — it overlaps ``schema_summary``, which is
    # already there, and a prompt gains nothing from being told twice.
    usage_brief: str | None = None

    def as_text(self, *, include_http: bool = False) -> str:
        """Return a plain-text representation suitable for injecting into an LLM system prompt.

        Includes ``purpose`` and ``owner_instructions`` when the instance has them.
        ``usage_brief`` is deliberately left out; read it from the attribute if you
        want it.

        Both of those are free text set by anyone holding edit permission on the
        instance, so each is labelled with where it came from and how much weight it
        deserves rather than presented as if this library authored it. The labels
        state provenance; they are not a security boundary, and a caller embedding
        this in a system prompt is still handling text it does not control.

        By default, tools are presented as method calls (matching the SDK).
        Set *include_http* to ``True`` to also show HTTP method and path for
        raw REST callers.
        """
        lines: list[str] = []
        lines.append(f"Instance: {self.instance_name} ({self.instance_id})")
        if self.purpose:
            lines.append(f"\n{_PURPOSE_LABEL} {self.purpose}")
        if self.about:
            lines.append(f"\n{self.about}")
        if self.owner_instructions:
            # Placed before the schema so a long schema cannot bury it.
            lines.append(f"\n{_OWNER_INSTRUCTIONS_LABEL}\n{self.owner_instructions}")
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


class _OmitUnsetRequest(BaseModel):
    """A request body that sends only the fields the caller actually named.

    The metadata endpoints decide what to touch from the keys present in the JSON,
    so a field sent unasked is a field cleared: a client that always sent
    ``agent_owner_instructions`` would wipe an owner's standing rule for anyone who
    used it to rename an instance. Fields default to :data:`UNSET` and are dropped
    here; an explicit ``None`` is kept, sends null, and clears the stored value.
    """

    @model_serializer
    def _serialize(self) -> dict[str, Any]:
        return {
            name: value
            for name in type(self).model_fields
            if (value := getattr(self, name)) is not UNSET
        }


class _UpdateMetadataRequest(_OmitUnsetRequest):
    # ``name`` and ``description`` are required by the endpoint and always passed,
    # so they are always sent; the two below appear only when the caller names them.
    name: str
    description: str | None
    agent_owner_instructions: str | None | UnsetType = UNSET
    expected_owner_instructions_epoch: int | UnsetType = UNSET


class _PatchMetadataRequest(_OmitUnsetRequest):
    name: str | UnsetType = UNSET
    description: str | None | UnsetType = UNSET
    agent_surfaces: list[str] | None | UnsetType = UNSET
    agent_default_binding_tier: str | None | UnsetType = UNSET
    agent_engagement_hints: list[str] | None | UnsetType = UNSET
    agent_owner_instructions: str | None | UnsetType = UNSET


class _GenerateSchemaRequest(BaseModel):
    schema_description: str
    current_yml_schema: str | dict[str, Any] | None = None


class ScopeObject(BaseModel):
    """One concrete object a scoped read or a scoped write is allowed to touch.

    Identify the object by its ``type`` (PascalCase class name or snake_case
    table name) plus exactly one of:

    - ``key`` — its user-defined primary key, a mapping of primary-key field name
      to value, with one entry for every primary-key field; or
    - ``xuid`` — the object's xuid. This is the only way to name an object whose
      type has no user-defined primary key.

    Serialized to the API's identity wire shape — ``{"type": ..., "key": {"key": {...}}}``
    or ``{"type": ..., "key": {"xuid": ...}}``.
    """

    type: str
    key: dict[str, str | int | float | bool] | None = None
    xuid: str | None = None

    @model_validator(mode="after")
    def _exactly_one_identity(self) -> ScopeObject:
        if (self.key is None) == (self.xuid is None):
            raise ValueError("ScopeObject needs exactly one of 'key' or 'xuid'.")
        if self.key is not None and not self.key:
            raise ValueError("ScopeObject 'key' must contain at least one primary-key field.")
        return self

    @model_serializer
    def _serialize(self) -> dict[str, Any]:
        identity: dict[str, Any] = {"xuid": self.xuid} if self.xuid is not None else {"key": self.key}
        return {"type": self.type, "key": identity}


class ReadScope(BaseModel):
    """A read's scope: the concrete objects it may touch, plus relation policy.

    ``relations_scope`` is ``no_relations`` (objects only) by default;
    ``all_relations`` also exposes the relations among the in-scope ``objects``.
    """

    objects: list[ScopeObject]
    relations_scope: Literal["no_relations", "all_relations"] = "no_relations"


class WriteScope(BaseModel):
    """A write's scope: the concrete existing objects the write is anchored to.

    Their current values are shown to the extractor so the write updates them
    instead of creating duplicates, and the write is then confined to them: it
    may only modify or delete the scoped objects and create new objects (and
    relations anchored to the scope). Unlike `ReadScope` there is no relation
    policy — the relations among the scoped objects always accompany the hint.
    """

    objects: list[ScopeObject]


class _ReadRequest(BaseModel):
    query: str
    mode: ReadMode = ReadMode.SINGLE_ANSWER
    scope: ReadScope | None = None
    read_id: str | None = None


# ---------------------------------------------------------------------------
# Structured write mutations (public request models)
# ---------------------------------------------------------------------------


class RelationEndpoint(BaseModel):
    """One endpoint of a relation mutation.

    ``object_name`` is the relation role name from the instance schema; ``key``
    identifies the endpoint object by its user-defined primary-key fields
    (field -> value) or ``{"xuid": ...}``.
    """

    object_name: str
    key: dict[str, Any] = {}


class ObjectCreate(BaseModel):
    """Create an object: ``key`` holds the user primary-key fields (no ``xuid`` —
    it is generated server-side), ``values`` the remaining field values."""

    key: dict[str, Any] = {}
    values: dict[str, Any] = {}


class ObjectUpdate(BaseModel):
    """Update an object identified by ``key`` (primary-key fields or
    ``{"xuid": ...}``). A ``None`` value in ``values`` clears that field."""

    key: dict[str, Any] = {}
    values: dict[str, Any] = {}


class ObjectDelete(BaseModel):
    """Delete the object identified by ``key`` (primary-key fields or ``{"xuid": ...}``)."""

    key: dict[str, Any] = {}


class RelationCreate(BaseModel):
    """Create a relation between the ``endpoints``, with optional own-field ``values``."""

    endpoints: list[RelationEndpoint] = []
    values: dict[str, Any] = {}


class RelationUpdate(BaseModel):
    """Update a relation's own fields. Address it by ``endpoints``, or by
    ``key={"xuid": ...}`` when endpoints are ambiguous. A ``None`` value in
    ``values`` clears that field."""

    key: dict[str, Any] = {}
    endpoints: list[RelationEndpoint] = []
    values: dict[str, Any] = {}


class RelationDelete(BaseModel):
    """Delete relation(s) matched by ``endpoints`` (a subset is allowed) or by
    ``key={"xuid": ...}``. Deleting more than one matched row requires
    ``allow_bulk_delete=True``."""

    key: dict[str, Any] = {}
    endpoints: list[RelationEndpoint] = []
    allow_bulk_delete: bool = False


def _single_op(model: BaseModel) -> tuple[str, BaseModel]:
    """Return the single set op branch of a mutation, or raise ``ValueError``."""
    set_ops = [
        (name, payload)
        for name in ("create", "update", "delete")
        if (payload := getattr(model, name)) is not None
    ]
    if len(set_ops) != 1:
        raise ValueError(
            f"{type(model).__name__}: exactly one of 'create', 'update', 'delete' must be set.",
        )
    return set_ops[0]


class ObjectMutation(BaseModel):
    """One structured mutation of an object: exactly one of ``create`` /
    ``update`` / ``delete``, applied to the schema object type ``object_type``.

    Serialized to the API's tagged wire form —
    ``{"object_mutation": {"object_type": ..., "<op>": {...}}}``.
    """

    object_type: str
    create: ObjectCreate | None = None
    update: ObjectUpdate | None = None
    delete: ObjectDelete | None = None

    @model_validator(mode="after")
    def _exactly_one_op(self) -> ObjectMutation:
        _single_op(self)
        return self

    @model_serializer
    def _serialize(self) -> dict[str, Any]:
        # ``model_dump`` (not ``exclude_none``) so a ``None`` inside ``values``
        # — a field clear — survives; only the unset op branches are dropped.
        op, payload = _single_op(self)
        return {"object_mutation": {"object_type": self.object_type, op: payload.model_dump()}}


class RelationMutation(BaseModel):
    """One structured mutation of a relation: exactly one of ``create`` /
    ``update`` / ``delete``, applied to the schema relation type ``relation_type``.

    Serialized to the API's tagged wire form —
    ``{"relation_mutation": {"relation_type": ..., "<op>": {...}}}``.
    """

    relation_type: str
    create: RelationCreate | None = None
    update: RelationUpdate | None = None
    delete: RelationDelete | None = None

    @model_validator(mode="after")
    def _exactly_one_op(self) -> RelationMutation:
        _single_op(self)
        return self

    @model_serializer
    def _serialize(self) -> dict[str, Any]:
        op, payload = _single_op(self)
        return {"relation_mutation": {"relation_type": self.relation_type, op: payload.model_dump()}}


WriteMutation = ObjectMutation | RelationMutation
"""A structured write mutation — either an object or a relation mutation."""


class _WriteRequest(BaseModel):
    text: str = ""
    extraction_logic: ExtractionLogic = ExtractionLogic.FAST
    use_diff_engine: bool | None = None
    structured_mutations: list[dict[str, Any]] | None = None
    scope: WriteScope | None = None

    @model_serializer(mode="wrap")
    def _omit_unset_optional_fields(self, handler: Any) -> dict[str, Any]:
        # Omit these keys entirely when unset: older servers reject unknown
        # request fields, so plain text writes must stay byte-identical.
        data = handler(self)
        if self.structured_mutations is None:
            data.pop("structured_mutations", None)
        if self.scope is None:
            data.pop("scope", None)
        return data


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
    details: dict[str, Any] | None = None


class SetupFormat(str, Enum):
    """Which rendering of an instance's setup to ask for.

    ``AGENT`` answers "what do I run right now, here". ``PROJECT`` answers "what do I
    commit so my team does not each run it by hand" — the same instance, but the output
    is files rather than steps.
    """

    AGENT = "agent"
    PROJECT = "project"


class StepKind(str, Enum):
    """What kind of thing :attr:`AgentSetupStep.command` is.

    The field carries three different things — a shell command, an in-session slash
    command, and a bare URL — so a caller that runs all of them in a shell will try to
    execute a connector URL. Check this before running anything.
    """

    SHELL = "shell"
    SLASH = "slash"
    URL = "url"


class FragmentMerge(str, Enum):
    """How a fragment combines with a file the repository may already have.

    Every fragment is a merge, never a file to overwrite: a repository that already has
    a ``.claude/settings.json`` has permissions, hooks and directory trust in it, and
    replacing it wholesale to add two keys destroys that. Both merges are idempotent —
    applying a fragment twice must leave the file as one application would, so an
    applier that *appends* is implementing neither.
    """

    MERGE_JSON = "merge_json"
    MERGE_TOML = "merge_toml"


class AgentSetupStep(BaseModel):
    """One action, with the command that performs it where there is one."""

    description: str
    command: str | None = None
    # Absent rather than guessed where the server names no kind, which is also what an
    # older server sends. Read the absence as "not known to be a shell command".
    #
    # Left-to-right so a value this release knows arrives as the enum member — ``kind is
    # StepKind.SHELL`` still holds — while one it does not arrives as a plain string
    # rather than rejecting the whole payload. A step whose kind you do not recognise is
    # not executable: this field exists because the command may be a slash command or a
    # bare URL, so running an unknown kind in a shell is the mistake it prevents.
    kind: Union[StepKind, str, None] = Field(default=None, union_mode="left_to_right")


class AgentSetupSurface(BaseModel):
    """How to connect this instance from one agent surface."""

    # A plain string rather than the AgentSurface enum: a server newer than this release
    # can name a surface this one has never heard of, and refusing to parse the whole
    # payload over it would make every new surface a breaking change for old clients.
    surface: str
    label: str
    steps: list[AgentSetupStep] = []
    # What a person still has to do themselves — approve a command, complete a browser
    # sign-in, trust a hook. Relay these: they are the consent the flow depends on.
    human_steps: list[str] = []


class ProjectFragment(BaseModel):
    """One file a customer commits so their teammates do not each set this up."""

    path: str
    purpose: str
    # Same left-to-right tolerance as ``AgentSetupStep.kind``: a merge strategy added
    # after this release must not make the whole setup result unparseable. A strategy
    # you do not recognise cannot be applied safely — leave the file alone and surface
    # the fragment as a manual step.
    merge: Union[FragmentMerge, str] = Field(union_mode="left_to_right")
    content: str


class ProjectSetup(BaseModel):
    """The committable half of an instance's setup.

    ``manual_steps`` is not a leftover: a surface with no committable channel is not the
    same as one that was forgotten, and a payload that silently omitted it would read as
    the latter.
    """

    fragments: list[ProjectFragment] = []
    manual_steps: list[str] = []


class AgentSetupResult(BaseModel):
    """How to connect one instance, ordered for where it is likely to be used.

    The same payload the server's create response carries, the ``get_setup_instructions``
    MCP tools serve and ``xmemcli instance setup`` prints, so an agent reading this and a
    person at a terminal follow the same instructions. (This client's
    :meth:`~xmemory.AdminAPI.create_instance` returns an :class:`~xmemory.InstanceAPI`
    handle rather than that payload — call one of the methods below for it.)

    **Carries no credential.** The steps tell a reader to sign in themselves, out of
    band, precisely so a key never lands in a transcript.
    """

    instance_id: str
    instance_name: str
    install_page_url: str
    # Ordered most-likely-first, never filtered: a hint about where an instance will be
    # used is not a restriction on where it may be.
    surfaces: list[AgentSetupSurface] = []
    # One line to paste into an agent instead of running anything by hand.
    paste_to_agent: str = ""
    # What the server actually rendered, which is not always what was asked for: an
    # older server ignores an unknown query parameter and answers 200, so a caller
    # asking for PROJECT can receive the agent payload with no error at all. Compare
    # this against what you requested rather than inferring from ``project`` being None.
    format: Union[SetupFormat, str] = Field(default=SetupFormat.AGENT, union_mode="left_to_right")
    # Present only when ``format=project`` was both requested and honoured.
    project: ProjectSetup | None = None


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
