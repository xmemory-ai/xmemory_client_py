# Changelog

All notable changes to `xmemory-ai` are documented here.

## 0.16.0

Adds scoped writes. A write was previously all-or-nothing about what it could
touch: the extractor saw only the text, and whatever it produced was reconciled
against the whole instance — so a note about someone the instance already knows
could just as easily land as a second, near-identical record. A scope names the
records the write is about, which both tells the extractor what to fold the new
information into and confines the result to those records.

### Added

- `scope` on `write` and `write_async` (sync and async clients alike), taking a
  `WriteScope` of concrete existing objects. Their current values are shown to
  the extractor so the write updates them instead of creating duplicates, and
  the write is then confined to the scope: it may only modify or delete the
  scoped objects and create new objects and relations anchored to them. Anything
  else fails the write. The confinement is checked against the resulting plan
  rather than requested of the extractor, so it holds however the extraction
  turned out.
- `WriteScope`, re-exported from `xmemory`. It carries only `objects` — unlike
  `ReadScope` there is no relation policy, because the relations among the
  scoped objects always accompany the hint.
### Notes

A scope names its objects by user-defined primary key, so only types that
declare one can be scoped. That is deliberate: it keeps a scope expressed in the
same identity the rest of your schema uses, rather than in server-generated ids.

Scope applies to text writes only. Combining it with `structured_mutations`
raises a `ValueError` here rather than travelling to the server, because those
bypass extraction and leave a scope nothing to anchor to. Everything else stays
a server-side decision and surfaces as an `XmemoryAPIError` — including the
extraction logic a scope may be used with and the cap on how many objects one
scope may name, both of which are deployment configuration this library should
not be second-guessing or silently working around.

One thing worth knowing before granting it: a scoped write additionally requires
**read** permission on the instance. The scoped records' current field values
ride the extraction prompt, so a scope is not merely a restriction — it is also
a read of those rows, and a write-only caller is refused it.

## 0.15.0

Surfaces the console link the API has always sent with every data operation and this
client dropped.

### Added

- `console_url` on `ReadResult`, `WriteResult`, `AsyncWriteResult`, `WriteStatusResult`
  and `ExtractResult` — the deep link to that operation's trace in the xmemory console.
  `AsyncWriteResult` gains `trace_id` in the same pass: the fire-and-forget path this
  library recommends for writes was the one with no way to point at what it did.

### Notes

The link is per operation, not per record, and it is `None` whenever the server has no
console configured — self-hosting without one is ordinary, so a caller rendering it must
handle its absence rather than assume a link is always there.

Why it matters beyond convenience: the one instruction xmemory ships about how an agent
should talk about recalled data asks it to name the record an answer rests on and link
the read that produced it. Through this library that was not followable without
rebuilding the URL from a trace id and a hostname the caller had to know.

## 0.14.0

Adds the connect instructions for an instance — how to reach the same memory from
another agent surface — which the API, the MCP tools and `xmemcli instance setup`
already served and the SDKs did not.

### Added

- `AdminAPI.get_setup_instructions(instance_id)` and `InstanceAPI.setup_instructions()`,
  with async counterparts. On both because the MCP instance connection serves the same
  tool, so a caller holding an instance handle should not have to reach through `admin`.
- `format=SetupFormat.PROJECT` additionally returns the files a customer commits so a
  whole team gets an instance without each person running the steps by hand. Read
  `AgentSetupResult.format` on the way out: a server older than that parameter ignores
  it and still answers 200, so asking is not the same as receiving.
- New exports: `AgentSetupResult`, `AgentSetupSurface`, `AgentSetupStep`, `ProjectSetup`,
  `ProjectFragment`, `SetupFormat`, `StepKind`, `FragmentMerge`.

### Notes

Nothing returned carries a credential: the steps tell a reader to sign in themselves,
out of band, so an instance id remains an identifier rather than a key.

Advisory values tolerate what this release has not heard of: `AgentSetupSurface.surface`
is a plain string, and `AgentSetupStep.kind`, `ProjectFragment.merge` and `format` accept
an unknown value as a string while still resolving a known one to its enum member. A
strict enum on any of them would turn an additive server change into a validation error
over the whole result, not just that field. A `kind` you do not recognise is not
executable.

## 0.13.0

Surfaces the agent-facing instance metadata the API already returns: what a
memory is *for*, the standing preference set for how agents should use it, and
the advisory hints that seed a connect flow.

Nothing here is required. Older versions keep working against the same server —
they simply do not see these fields.

### Added

- `DescribeResult.purpose`, `.owner_instructions` and `.usage_brief`.
  `as_text()` now includes the first two — the purpose under the instance line,
  the standing preference above the schema summary so a long schema cannot bury
  it. Each is labelled with where it came from rather than as this library's own
  words, because anyone holding edit permission on an instance can set either
  one, so a label naming an author would claim something no response can verify.
  `usage_brief` is exposed as an attribute but deliberately left out of
  `as_text()`, because it restates the schema summary already in there.
- Agent metadata on `InstanceInfo`: `agent_surfaces`,
  `agent_default_binding_tier`, `agent_engagement_hints`,
  `agent_owner_instructions` and `agent_owner_instructions_epoch`. Typed as
  plain strings rather than enums so a value added to the server after this
  release is read rather than rejected.
- `admin.patch_instance_metadata(...)` (sync and async) — `PATCH
  /instances/{id}`. Every argument is optional and independent: omit one and the
  stored value is untouched, pass `None` to clear it.
- `AgentSurface` and `BindingTier` enums for the accepted hint values, plus the
  `UNSET` sentinel (and `UnsetType`) that distinguishes "leave it alone" from
  "clear it". Plain strings are accepted wherever an enum is, so a newer server
  can be driven without waiting for a release here.
- `admin.update_instance_metadata(...)` gained `agent_owner_instructions` and
  `expected_owner_instructions_epoch`. Pass the epoch from the response you
  composed your edit from and the server refuses a save that raced someone
  else's rather than overwriting it.

## 0.12.0

Structured writes: `write` and `write_async` now also accept
`structured_mutations` — an ordered list of deterministic, LLM-free
create/update/delete mutations of objects and relations, mutually exclusive
with `text`. Mutations can be built from the new typed models
(`ObjectMutation`, `RelationMutation`, `ObjectCreate/Update/Delete`,
`RelationCreate/Update/Delete`, `RelationEndpoint` — all exported) or passed as
plain dicts in the API's wire form; a `None` value inside a mutation's
`values` clears that field. Plain text writes are unchanged on the wire.

Requires a server with structured-writes support (`structured_mutations` on
`/write` and `/write_async`); older servers reject the new request field.

### Added

- `write(structured_mutations=[...])` / `write_async(structured_mutations=[...])`
  on both the sync and async instance APIs (`text` is now optional; exactly one
  of the two inputs must be provided, enforced client-side with `ValueError`).
- Typed mutation models: `WriteMutation`, `ObjectMutation`, `ObjectCreate`,
  `ObjectUpdate`, `ObjectDelete`, `RelationMutation`, `RelationCreate`,
  `RelationUpdate`, `RelationDelete`, `RelationEndpoint`.

## 0.11.0

Licensing-only release: the client library is now MIT-licensed. Package
metadata changes from `Proprietary` to `MIT`, and a `LICENSE` file ships in the
sdist and wheel. The MIT grant covers this client library only — the xmemory
service and the technology behind it stay proprietary to xmemory Inc., and use
of the service remains governed by its Terms & Conditions. No API or behavior
change.

## 0.10.1

Documentation-only release: removes `402 TRIAL_ENDED` from the documented error
contract. The server no longer emits it — trials were removed end-to-end — so
`402 Payment Required` now means `QUOTA_EXCEEDED` only. No API or behavior
change: `XmemoryAPIError.code` was always a passthrough of whatever the server
sent, so nothing in the client ever special-cased `TRIAL_ENDED`. Callers still
branch on `.code`, not the bare status. (The 0.9.0 note below stands as a record
of the old contract.)

## 0.10.0

Surfaces per-sub-query answers from the reader's question decomposition. When
the server splits a composite query (several independent questions in one
`read`) into sub-queries, the response now carries one answer per sub-query
alongside the existing combined answer. Purely additive — existing callers that
only read `reader_result` are unaffected.

### Added

- `ReadResult.reader_results` — a list of `TaggedReaderResult`, one entry per
  sub-query the server decomposed the query into (a single-intent query yields
  exactly one entry). `reader_result` stays the combined back-compat value (for
  `single-answer` mode, a labelled multi-part string). The list is empty against
  a server without question decomposition, or when it is disabled.
- `TaggedReaderResult` — carries `sub_query` (the sub-question), `reader_result`
  (its answer, in the requested read mode), and `error` (a user-safe message set
  when that one sub-query could not be answered while the others still were;
  `None` otherwise). Exported from the package root.

## 0.9.0

Surfaces the accounts API's new account/billing and rate-limit error contract.
The client stays status-agnostic, but now carries the discriminating `code`,
the structured `details`, and the `Retry-After` header all the way to callers.

### Added

- `XmemoryAPIError.retry_after` — the HTTP `Retry-After` response header parsed
  to a non-negative `int` number of seconds (delta-seconds form), or `None` when
  the server did not send one (or sent an HTTP-date). A negative delta is clamped
  to `0`, so `time.sleep(e.retry_after or 1)` never raises. Populated for
  resettable `QUOTA_EXCEEDED` (402) and `RATE_LIMITED` (429) responses. The
  library does **not** retry automatically — it only surfaces the value.

### Fixed

- `XmemoryAPIError.details` is now populated for the standard
  `{"errors": [{"code", "message", "details"}]}` envelope. Previously the
  transport dropped `details` for this shape and only propagated it for the
  schema-evolution `{"status": "error", "error_type", ...}` payload. This is how
  the new `402 QUOTA_EXCEEDED` quota metadata —
  `details.kind` (`daily_quota_exceeded` / `monthly_quota_exceeded`) and
  `details.retry_after_seconds` — reaches callers.

### Notes — accounts error contract

`402 Payment Required` now means two different things, discriminated by `code`,
never by the bare status: `QUOTA_EXCEEDED` (plan/usage allowance exhausted,
non-retryable) and `TRIAL_ENDED` (trial over / subscription lapsed,
non-retryable). Genuine velocity limits are now `429 RATE_LIMITED` (retryable
with backoff, honoring `Retry-After`) — quota is no longer a 429. Branch on
`code`, not on HTTP status. See the README "Error handling" section.

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
- `ExtractionLogic.REGULAR` — the server no longer supports the regular
  extraction mode. The enum is now `FAST` and `DEEP`, and `extraction_logic`
  continues to default to `ExtractionLogic.FAST`.

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