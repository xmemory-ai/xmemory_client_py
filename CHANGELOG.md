# Changelog

All notable changes to `xmemory-ai` are documented here.

## 0.8.0

Replaces the legacy `cleaned_objects` echo on the write response with the new
`changes` summary.

### Added

- `WriteResult.changes` — the `/write` response's summary of what the write did,
  grouped into `created` / `updated` / `deleted`. Exposed as-is; defaults to
  `None` when an older server omits it.

### Removed

- `WriteResult.cleaned_objects` — superseded by `changes`. The server still
  returns the field to direct/SDK callers, but it is no longer parsed or
  exposed. Read `changes` instead.

## 0.7.1

### Added

- `DescribeResult.about` — the describe endpoint's first-party-positioning
  string is now parsed and exposed, and surfaced in `as_text()`. Defaults to
  `""` when an older server omits it.

## 0.7.0

Adds **scoped reads**. This release is purely additive — existing `read()`
callers are unchanged.

### Added — instance (`client.instance(id)`)

- `read(...)` accepts an optional `scope=ReadScope(...)` to restrict the read to
  a set of concrete objects. Each object is named by a `ScopeObject(type=...,
  key={...})` identifying it by its user-defined primary key. By default only
  those objects are in scope; set `ReadScope.relations_scope="all_relations"` to
  also expose the relations among them.

### Added — DTOs (re-exported from `xmemory`)

- `ReadScope` and `ScopeObject`.

## 0.6.1

### Fixed

- `WriteQueueStatus` now includes the two-phase write-pipeline statuses
  `extracting`, `extracted`, and `applying`. Previously, polling
  `write_status` against a server running the parallel-extraction pipeline
  raised a Pydantic `ValidationError` on these values. They are non-terminal
  (in-progress) states — keep polling until `completed` / `failed`.

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