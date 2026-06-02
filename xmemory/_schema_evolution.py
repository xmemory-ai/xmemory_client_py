"""Typed DTOs for the schema-evolution surface.

These models mirror the server-side wire formats one-to-one (snake_case
field names), so a JSON payload round-trips through them unchanged. They
back the schema-evolution methods on :class:`xmemory._admin.AdminAPI`
(``enhance_schema`` / ``update_instance_schema`` / ``dry_run_migration`` /
``list_migrations`` / ``get_migration``) and on
:class:`xmemory._instance.InstanceAPI` (``review_suggestions`` /
``decide_suggestions`` / ``apply_pending_decisions``).

Migration ops are a discriminated union keyed on ``op_type``. Fields that
the server keeps as forward-compatible raw JSON (``ProposalItem.op``,
``MigrationRecord.ops``, ``DecisionInput.edits``) are kept as plain dicts
here too, so a client one version behind the server can still read the
rest of the payload when a new ``op_type`` lands. Use
:func:`parse_migration_op` / :func:`parse_migration_plan` to validate
those into typed ops when you need them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

# ---------------------------------------------------------------------------
# Shared literal/value types (mirror xmmodel.dto.migration_ops + xmm_description)
# ---------------------------------------------------------------------------

FieldType = Literal["str", "string", "int", "integer", "float", "bool", "boolean"]
OnDelete = Literal["nullify", "cascade"]
CastStrategy = Literal["safe_implicit", "explicit_using", "lossy"]
DecisionKind = Literal["accept", "reject", "defer"]
MigrationSource = Literal["direct", "suggestion_engine"]

DefaultValue = str | int | float | bool | None
EnumValues = list[str | int | float | bool] | None


# ---------------------------------------------------------------------------
# Migration ops — discriminated union on ``op_type``.
# ---------------------------------------------------------------------------


class FieldSpec(BaseModel):
    """Subset of an object field sufficient to add a field via a migration op."""

    name: str
    type: FieldType
    required: bool = False
    description: str | None = None
    default: DefaultValue = None
    enum: EnumValues = None


class AddObject(BaseModel):
    op_type: Literal["add_object"] = "add_object"
    name: str
    description: str | None = None
    primary_key: list[str] = []
    fields: list[FieldSpec] = []
    should_backfill: bool = False


class RemoveObject(BaseModel):
    op_type: Literal["remove_object"] = "remove_object"
    name: str


class RenameObject(BaseModel):
    op_type: Literal["rename_object"] = "rename_object"
    old_name: str
    new_name: str


class ChangeObject(BaseModel):
    op_type: Literal["change_object"] = "change_object"
    name: str
    new_primary_key: list[str] | None = None
    new_description: str | None = None


class AddField(BaseModel):
    op_type: Literal["add_field"] = "add_field"
    object_name: str
    field_name: str
    field_type: FieldType
    required: bool = False
    description: str | None = None
    default: DefaultValue = None
    enum: EnumValues = None
    should_backfill: bool = False


class RemoveField(BaseModel):
    op_type: Literal["remove_field"] = "remove_field"
    object_name: str
    field_name: str


class RenameField(BaseModel):
    op_type: Literal["rename_field"] = "rename_field"
    object_name: str
    old_name: str
    new_name: str


class ChangeField(BaseModel):
    op_type: Literal["change_field"] = "change_field"
    object_name: str
    field_name: str
    new_type: FieldType | None = None
    new_required: bool | None = None
    new_description: str | None = None
    new_default: DefaultValue = None
    new_enum: EnumValues = None
    clear_default: bool = False
    clear_enum: bool = False
    cast_strategy: CastStrategy | None = None
    using_expression: str | None = None
    confirm_data_loss: bool = False


class AddRelation(BaseModel):
    op_type: Literal["add_relation"] = "add_relation"
    name: str
    description: str | None = None
    objects: dict[str, str]
    keys: dict[str, list[str]] | None = None
    on_delete: dict[str, OnDelete] | None = None
    should_backfill: bool = False


class RemoveRelation(BaseModel):
    op_type: Literal["remove_relation"] = "remove_relation"
    name: str


class RenameRelation(BaseModel):
    op_type: Literal["rename_relation"] = "rename_relation"
    old_name: str
    new_name: str


class ChangeRelation(BaseModel):
    op_type: Literal["change_relation"] = "change_relation"
    name: str
    new_keys: dict[str, list[str]] | None = None
    new_on_delete: dict[str, OnDelete] | None = None
    new_description: str | None = None


MigrationOp = Annotated[
    AddObject
    | RemoveObject
    | RenameObject
    | ChangeObject
    | AddField
    | RemoveField
    | RenameField
    | ChangeField
    | AddRelation
    | RemoveRelation
    | RenameRelation
    | ChangeRelation,
    Field(discriminator="op_type"),
]


class MigrationPlan(BaseModel):
    """An ordered sequence of migration ops — the stable wire format the
    server emits from ``enhance_schema`` and consumes on
    ``update_instance_schema`` / ``dry_run_migration``."""

    ops: list[MigrationOp] = []


_MIGRATION_OP_ADAPTER: TypeAdapter[MigrationOp] = TypeAdapter(MigrationOp)


def parse_migration_op(op: dict[str, Any]) -> MigrationOp:
    """Validate a raw op dict (e.g. ``ProposalItem.op``) into a typed op."""
    return _MIGRATION_OP_ADAPTER.validate_python(op)


def parse_migration_plan(plan: dict[str, Any]) -> MigrationPlan:
    """Validate a raw ``{"ops": [...]}`` dict into a typed :class:`MigrationPlan`."""
    return MigrationPlan.model_validate(plan)


# ---------------------------------------------------------------------------
# enhance_schema result.
# ---------------------------------------------------------------------------


class EnhanceSchemaResult(BaseModel):
    """Return shape of :meth:`AdminAPI.enhance_schema`.

    ``data_schema`` is the produced XMD as a dict. ``migration_plan`` is the
    reconciled, executor-ready plan you pass straight to
    ``update_instance_schema`` / ``dry_run_migration``. ``warnings`` and
    ``repair_log`` are raw dicts (non-fatal reconciler observations and
    auto-repairs applied to the LLM output)."""

    data_schema: dict[str, Any]
    migration_plan: MigrationPlan | None = None
    summary: str | None = None
    warnings: list[dict[str, Any]] = []
    repair_log: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Dry-run + migration history.
# ---------------------------------------------------------------------------


class PlanSummary(BaseModel):
    """Per-op-type breakdown of a migration plan."""

    count_by_op_type: dict[str, int] = {}
    total: int = 0


class DryRunResult(BaseModel):
    """Return shape of :meth:`AdminAPI.dry_run_migration` — the planned DDL
    statements and a plan summary, with nothing applied."""

    status: Literal["ok"] = "ok"
    instance_id: str
    current_version: int
    statements: list[str] = []
    warnings: list[str] = []
    plan_summary: PlanSummary = PlanSummary()
    requires_metadata_sync: bool = False


class MigrationRecord(BaseModel):
    """One applied-migration history row.

    ``ops`` is the raw ops list (kept as dicts for forward compat).
    ``yaml_before`` / ``yaml_after`` are populated only when the call
    requested ``include_yaml=True``."""

    id: str
    applied_at: datetime
    source: str
    decided_by: str | None = None
    prior_version: int
    new_version: int
    ops: list[dict[str, Any]] = []
    ops_summary: PlanSummary = PlanSummary()
    notes: str | None = None
    yaml_before: str | None = None
    yaml_after: str | None = None


class ListMigrationsResult(BaseModel):
    """Return shape of :meth:`AdminAPI.list_migrations` — newest first.

    ``next_before_id`` is the pagination cursor: pass it as ``before_id`` on
    the follow-up call. ``None`` when the current page is the tail."""

    status: Literal["ok"] = "ok"
    instance_id: str
    items: list[MigrationRecord] = []
    next_before_id: str | None = None
    has_more: bool = False


class GetMigrationResult(BaseModel):
    status: Literal["ok"] = "ok"
    instance_id: str
    record: MigrationRecord


# ---------------------------------------------------------------------------
# Suggestion engine — review / decide / apply.
# ---------------------------------------------------------------------------


class ProposalItem(BaseModel):
    """One accept/reject/defer-able item inside a consolidated proposal.

    ``op`` is a raw dict (forward-compatible). Use
    :func:`parse_migration_op` to validate it into a typed op."""

    item_fingerprint: str
    op: dict[str, Any]
    evidence_feedback_ids: list[str] = []
    evidence_query_samples: list[str] = []
    frequency: int = 0
    depends_on: list[str] = []
    current_decision: str | None = None
    rationale: str = ""


class ConsolidatedProposal(BaseModel):
    """The single rolling proposal for an instance.

    ``proposal_version`` is the optimistic-concurrency token you pass back to
    ``decide_suggestions`` / ``apply_pending_decisions``."""

    instance_id: str
    proposal_version: str
    schema_version: int
    items: list[ProposalItem] = []
    generated_at: datetime
    notes: list[str] = []


class ReviewSuggestionsResult(BaseModel):
    """Return shape of :meth:`InstanceAPI.review_suggestions`.

    ``status == "ok"`` carries ``proposal``; ``status ==
    "evolution_in_progress"`` carries ``retry_after_seconds`` so you can back
    off rather than block on an in-flight migration."""

    status: Literal["ok", "evolution_in_progress"]
    instance_id: str
    proposal: ConsolidatedProposal | None = None
    retry_after_seconds: int | None = None


class DecisionInput(BaseModel):
    """One decision in a :meth:`InstanceAPI.decide_suggestions` batch.

    ``edits`` is an optional structured-op override; it must keep the same
    ``op_type`` as the proposed op."""

    item_fingerprint: str
    decision: DecisionKind
    edits: dict[str, Any] | None = None


class RecordedDecision(BaseModel):
    item_fingerprint: str
    decision_id: str


class DependencyWarning(BaseModel):
    """Advisory (non-blocking) dependency warning from ``decide_suggestions``."""

    kind: str
    item_fingerprint: str
    related_fingerprints: list[str] = []
    related_summaries: list[str] = []
    guidance: str


class DecideSuggestionsResult(BaseModel):
    """Return shape of :meth:`InstanceAPI.decide_suggestions`.

    ``next_proposal_version`` is the token after the batch landed — pass it
    straight to ``apply_pending_decisions`` without re-reviewing."""

    status: Literal["ok"] = "ok"
    instance_id: str
    decisions_recorded: list[RecordedDecision] = []
    warnings: list[DependencyWarning] = []
    next_proposal_version: str


class ApplyPendingDecisionsResult(BaseModel):
    """Return shape of :meth:`InstanceAPI.apply_pending_decisions`.

    ``status == "ok"`` means a migration committed; ``status ==
    "nothing_to_apply"`` means no accepted items were left to apply."""

    status: Literal["ok", "nothing_to_apply"]
    instance_id: str
    migration_id: str | None = None
    prior_version: int
    new_version: int
    applied_items: list[str] = []
    summary: str = ""
    warnings: list[str] = []
    notes: list[str] = []


# ---------------------------------------------------------------------------
# Internal request bodies.
# ---------------------------------------------------------------------------


def _serialize_plan(plan: MigrationPlan | dict[str, Any] | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    if isinstance(plan, MigrationPlan):
        return plan.model_dump(mode="json")
    return plan


class _ReviewSuggestionsRequest(BaseModel):
    session_id: str | None = None


class _DecideSuggestionsRequest(BaseModel):
    proposal_version: str
    decisions: list[DecisionInput]
    session_id: str | None = None


class _ApplyPendingDecisionsRequest(BaseModel):
    proposal_version: str
    session_id: str | None = None