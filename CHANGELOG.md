# Changelog

All notable changes to `xmemory-ai` are documented here.

## 0.6.0

Adds the **schema-evolution** surface. This release is purely additive —
existing methods are unchanged and older callers keep working.

### Added — admin (`client.admin`)

- `enhance_schema(cluster_id, schema_description, current_yml_schema)` → `EnhanceSchemaResult`.
  Evolves an existing schema and returns an executor-ready `migration_plan`.
- `dry_run_migration(instance_id, schema_text, schema_type, *, migration_plan, confirm_destructive)`
  → `DryRunResult`. Previews the planned DDL without applying it.
- `list_migrations(instance_id, *, limit, before_id, include_yaml)` → `ListMigrationsResult`.
- `get_migration(instance_id, migration_id, *, include_yaml)` → `MigrationRecord`.

### Added — instance (`client.instance(id)`)

- `review_suggestions()` → `ReviewSuggestionsResult` (the rolling consolidated proposal).
- `decide_suggestions(proposal_version, decisions)` → `DecideSuggestionsResult`.
- `apply_pending_decisions(proposal_version)` → `ApplyPendingDecisionsResult`.

### Changed (backwards-compatible)

- `update_instance_schema(...)` accepts optional `migration_plan` and
  `confirm_destructive`. Calls without them keep the legacy additive-only
  behaviour. The returned `InstanceInfo` now also carries `migration_id`,
  `prior_version`, `new_version`, and `migration_warnings` when a migration ran.
- `XmemoryAPIError` gained `.code` (structured error code, e.g.
  `stale_proposal_version`) and `.details`. Existing `.status` usage is
  unchanged.

### Added — DTOs (re-exported from `xmemory`)

- Migration ops: `MigrationPlan`, `MigrationOp`, `FieldSpec`, `AddObject`,
  `RemoveObject`, `RenameObject`, `ChangeObject`, `AddField`, `RemoveField`,
  `RenameField`, `ChangeField`, `AddRelation`, `RemoveRelation`,
  `RenameRelation`, `ChangeRelation`, plus `parse_migration_op` /
  `parse_migration_plan` helpers.
- Results: `EnhanceSchemaResult`, `DryRunResult`, `PlanSummary`,
  `MigrationRecord`, `ListMigrationsResult`, `ConsolidatedProposal`,
  `ProposalItem`, `ReviewSuggestionsResult`, `DecisionInput`,
  `RecordedDecision`, `DependencyWarning`, `DecideSuggestionsResult`,
  `ApplyPendingDecisionsResult`.

See `examples/suggestion_engine_flow.py` and `examples/direct_rename.py`, and
the [Python guide](https://xmemory.ai/python/) /
[API reference](https://xmemory.ai/api/#schema-evolution).