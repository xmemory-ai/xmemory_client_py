"""Unit tests for the schema-evolution surface (admin + instance methods)."""
from __future__ import annotations

import uuid

import httpx
import pytest
import respx

from xmemory import (
    AddField,
    ApplyPendingDecisionsResult,
    ChangeField,
    ConsolidatedProposal,
    DecideSuggestionsResult,
    DecisionInput,
    DryRunResult,
    EnhanceSchemaResult,
    FieldSpec,
    ListMigrationsResult,
    MigrationPlan,
    MigrationRecord,
    RenameField,
    ReviewSuggestionsResult,
    SchemaType,
    XmemoryAPIError,
    XmemoryClient,
    parse_migration_op,
    parse_migration_plan,
)
from xmemory._schema_evolution import (
    AddObject,
    AddRelation,
    ChangeObject,
    ChangeRelation,
    RemoveField,
    RemoveObject,
    RemoveRelation,
    RenameObject,
    RenameRelation,
)

CLUSTER_ID = str(uuid.uuid4())
INSTANCE_ID = str(uuid.uuid4())
MIGRATION_ID = str(uuid.uuid4())


def _api_ok(items: list[dict]) -> dict:
    return {"ids": [], "items": items, "errors": []}


@pytest.fixture()
def base_url():
    return "https://api.xmemory.ai"


@pytest.fixture(autouse=True)
def httpx_mock(base_url):
    with respx.mock(base_url=base_url) as mock:
        yield mock


@pytest.fixture()
def client(base_url):
    with XmemoryClient(url=base_url, api_key="test-api-key") as c:
        yield c


# ---------------------------------------------------------------------------
# DTO round-trip — every op type survives serialize -> parse unchanged.
# ---------------------------------------------------------------------------


def test_migration_plan_round_trip_all_ops():
    plan = MigrationPlan(
        ops=[
            RenameObject(old_name="Person", new_name="Contact"),
            RenameField(object_name="Contact", old_name="mail", new_name="email"),
            RenameRelation(old_name="WorksAt", new_name="EmployedBy"),
            ChangeField(
                object_name="Contact",
                field_name="age",
                new_type="int",
                cast_strategy="safe_implicit",
            ),
            AddObject(
                name="Company",
                primary_key=["name"],
                fields=[FieldSpec(name="name", type="str", required=True)],
            ),
            AddField(object_name="Contact", field_name="phone", field_type="str"),
            AddRelation(name="Knows", objects={"a": "Contact", "b": "Contact"}),
            ChangeObject(name="Contact", new_description="A person we track"),
            ChangeRelation(name="EmployedBy", new_description="employment edge"),
            RemoveField(object_name="Contact", field_name="legacy_id"),
            RemoveObject(name="Obsolete"),
            RemoveRelation(name="OldRel"),
        ]
    )
    dumped = plan.model_dump(mode="json")
    reparsed = parse_migration_plan(dumped)
    assert reparsed == plan
    # The discriminator is preserved on every op.
    assert [op["op_type"] for op in dumped["ops"]] == [
        "rename_object",
        "rename_field",
        "rename_relation",
        "change_field",
        "add_object",
        "add_field",
        "add_relation",
        "change_object",
        "change_relation",
        "remove_field",
        "remove_object",
        "remove_relation",
    ]


def test_parse_migration_op_discriminates():
    op = parse_migration_op({"op_type": "add_field", "object_name": "Contact", "field_name": "x", "field_type": "str"})
    assert isinstance(op, AddField)
    assert op.field_name == "x"


# ---------------------------------------------------------------------------
# admin.enhance_schema
# ---------------------------------------------------------------------------


def test_enhance_schema_parses_migration_plan(httpx_mock, client):
    payload = {
        "data_schema": {"objects": {}},
        "migration_plan": {"ops": [{"op_type": "rename_field", "object_name": "P", "old_name": "a", "new_name": "b"}]},
        "summary": "rename a to b",
        "warnings": [{"severity": "warn", "message": "heads up"}],
        "repair_log": [],
    }
    httpx_mock.post(f"/clusters/{CLUSTER_ID}/instances/generate_schema").mock(
        return_value=httpx.Response(200, json=_api_ok([payload]))
    )

    result = client.admin.enhance_schema(CLUSTER_ID, "rename a to b", "objects:\n  P: {}")

    assert isinstance(result, EnhanceSchemaResult)
    assert result.migration_plan is not None
    assert isinstance(result.migration_plan.ops[0], RenameField)
    assert result.summary == "rename a to b"
    assert result.warnings[0]["message"] == "heads up"


# ---------------------------------------------------------------------------
# admin.update_instance_schema — body shape + migration response fields
# ---------------------------------------------------------------------------


def test_update_instance_schema_sends_plan_and_destructive(httpx_mock, client):
    route = httpx_mock.put(f"/instances/{INSTANCE_ID}/schema").mock(
        return_value=httpx.Response(
            200,
            json=_api_ok(
                [
                    {
                        "id": INSTANCE_ID,
                        "cluster_id": CLUSTER_ID,
                        "name": "contacts",
                        "description": None,
                        "data_schema": {"objects": {}},
                        "migration_id": MIGRATION_ID,
                        "prior_version": 3,
                        "new_version": 4,
                        "migration_warnings": ["dropped legacy_id"],
                    }
                ]
            ),
        )
    )

    plan = MigrationPlan(ops=[RemoveField(object_name="Contact", field_name="legacy_id")])
    info = client.admin.update_instance_schema(
        INSTANCE_ID, "objects:\n  Contact: {}", SchemaType.YML,
        migration_plan=plan, confirm_destructive=True,
    )

    assert info.migration_id == MIGRATION_ID
    assert info.prior_version == 3
    assert info.new_version == 4
    assert info.migration_warnings == ["dropped legacy_id"]
    body = route.calls.last.request.read().decode()
    assert "remove_field" in body
    assert '"confirm_destructive":true' in body.replace(" ", "")


def test_update_instance_schema_back_compat_no_plan(httpx_mock, client):
    """Legacy callers that pass no plan still send a valid additive body."""
    route = httpx_mock.put(f"/instances/{INSTANCE_ID}/schema").mock(
        return_value=httpx.Response(
            200,
            json=_api_ok([{"id": INSTANCE_ID, "cluster_id": CLUSTER_ID, "name": "n", "description": None}]),
        )
    )
    info = client.admin.update_instance_schema(INSTANCE_ID, "objects:\n  Contact: {}", SchemaType.YML)
    assert info.migration_id is None
    body = route.calls.last.request.read().decode().replace(" ", "")
    assert '"migration_plan":null' in body
    assert '"confirm_destructive":false' in body


# ---------------------------------------------------------------------------
# admin.dry_run_migration / list_migrations / get_migration
# ---------------------------------------------------------------------------


def test_dry_run_migration(httpx_mock, client):
    httpx_mock.post(f"/instances/{INSTANCE_ID}/migrations/dry_run").mock(
        return_value=httpx.Response(
            200,
            json=_api_ok(
                [
                    {
                        "status": "ok",
                        "instance_id": INSTANCE_ID,
                        "current_version": 4,
                        "statements": ["ALTER TABLE contact RENAME COLUMN mail TO email"],
                        "warnings": [],
                        "plan_summary": {"count_by_op_type": {"rename_field": 1}, "total": 1},
                        "requires_metadata_sync": True,
                    }
                ]
            ),
        )
    )
    plan = MigrationPlan(ops=[RenameField(object_name="Contact", old_name="mail", new_name="email")])
    result = client.admin.dry_run_migration(INSTANCE_ID, "objects:\n  Contact: {}", SchemaType.YML, migration_plan=plan)
    assert isinstance(result, DryRunResult)
    assert result.current_version == 4
    assert result.plan_summary.total == 1
    assert result.requires_metadata_sync is True


def test_list_and_get_migration(httpx_mock, client):
    record = {
        "id": MIGRATION_ID,
        "applied_at": "2026-06-01T12:00:00Z",
        "source": "suggestion_engine",
        "decided_by": "api-key-123",
        "prior_version": 3,
        "new_version": 4,
        "ops": [{"op_type": "rename_field", "object_name": "Contact", "old_name": "mail", "new_name": "email"}],
        "ops_summary": {"count_by_op_type": {"rename_field": 1}, "total": 1},
        "notes": None,
        "yaml_before": None,
        "yaml_after": None,
    }
    list_route = httpx_mock.get(f"/instances/{INSTANCE_ID}/migrations").mock(
        return_value=httpx.Response(
            200,
            json=_api_ok([{"status": "ok", "instance_id": INSTANCE_ID, "items": [record], "next_before_id": None, "has_more": False}]),
        )
    )
    listed = client.admin.list_migrations(INSTANCE_ID, limit=10, include_yaml=False)
    assert isinstance(listed, ListMigrationsResult)
    assert listed.items[0].source == "suggestion_engine"
    assert listed.has_more is False
    # Query params encoded.
    assert "limit=10" in str(list_route.calls.last.request.url)
    assert "include_yaml=false" in str(list_route.calls.last.request.url)

    httpx_mock.get(f"/instances/{INSTANCE_ID}/migrations/{MIGRATION_ID}").mock(
        return_value=httpx.Response(
            200, json=_api_ok([{"status": "ok", "instance_id": INSTANCE_ID, "record": record}])
        )
    )
    got = client.admin.get_migration(INSTANCE_ID, MIGRATION_ID)
    assert isinstance(got, MigrationRecord)
    assert got.id == MIGRATION_ID
    assert got.new_version == 4


# ---------------------------------------------------------------------------
# instance.review / decide / apply
# ---------------------------------------------------------------------------


def test_review_suggestions(httpx_mock, client):
    proposal = {
        "instance_id": INSTANCE_ID,
        "proposal_version": "abc123",
        "schema_version": 4,
        "items": [
            {
                "item_fingerprint": "fp1",
                "op": {"op_type": "add_field", "object_name": "Contact", "field_name": "phone", "field_type": "str"},
                "evidence_feedback_ids": [],
                "evidence_query_samples": ["what is bob's phone"],
                "frequency": 3,
                "depends_on": [],
                "current_decision": None,
                "rationale": "queried but missing",
            }
        ],
        "generated_at": "2026-06-01T12:00:00Z",
        "notes": [],
    }
    httpx_mock.post(f"/instances/{INSTANCE_ID}/suggestions/review").mock(
        return_value=httpx.Response(
            200, json=_api_ok([{"status": "ok", "instance_id": INSTANCE_ID, "proposal": proposal, "retry_after_seconds": None}])
        )
    )
    result = client.instance(INSTANCE_ID).review_suggestions()
    assert isinstance(result, ReviewSuggestionsResult)
    assert result.status == "ok"
    assert isinstance(result.proposal, ConsolidatedProposal)
    assert result.proposal.proposal_version == "abc123"
    # Forward-compat: op stays a dict, parseable on demand.
    parsed = parse_migration_op(result.proposal.items[0].op)
    assert isinstance(parsed, AddField)


def test_decide_suggestions_sends_decisions(httpx_mock, client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/suggestions/decide").mock(
        return_value=httpx.Response(
            200,
            json=_api_ok(
                [
                    {
                        "status": "ok",
                        "instance_id": INSTANCE_ID,
                        "decisions_recorded": [{"item_fingerprint": "fp1", "decision_id": str(uuid.uuid4())}],
                        "warnings": [],
                        "next_proposal_version": "def456",
                    }
                ]
            ),
        )
    )
    result = client.instance(INSTANCE_ID).decide_suggestions(
        "abc123", [DecisionInput(item_fingerprint="fp1", decision="accept")]
    )
    assert isinstance(result, DecideSuggestionsResult)
    assert result.next_proposal_version == "def456"
    body = route.calls.last.request.read().decode().replace(" ", "")
    assert '"proposal_version":"abc123"' in body
    assert '"decision":"accept"' in body


def test_apply_pending_decisions(httpx_mock, client):
    httpx_mock.post(f"/instances/{INSTANCE_ID}/suggestions/apply").mock(
        return_value=httpx.Response(
            200,
            json=_api_ok(
                [
                    {
                        "status": "ok",
                        "instance_id": INSTANCE_ID,
                        "migration_id": MIGRATION_ID,
                        "prior_version": 4,
                        "new_version": 5,
                        "applied_items": ["fp1"],
                        "summary": "added 1 field",
                        "warnings": [],
                        "notes": [],
                    }
                ]
            ),
        )
    )
    result = client.instance(INSTANCE_ID).apply_pending_decisions("def456")
    assert isinstance(result, ApplyPendingDecisionsResult)
    assert result.status == "ok"
    assert result.new_version == 5


# ---------------------------------------------------------------------------
# Structured errors — schema-evolution payload shape carries the code.
# ---------------------------------------------------------------------------


def test_stale_proposal_version_surfaces_code(httpx_mock, client):
    httpx_mock.post(f"/instances/{INSTANCE_ID}/suggestions/apply").mock(
        return_value=httpx.Response(
            409,
            json={
                "status": "error",
                "error_type": "stale_proposal_version",
                "error_message": "Proposal version is stale; re-review.",
                "details": {"current": "xyz"},
            },
        )
    )
    with pytest.raises(XmemoryAPIError) as exc:
        client.instance(INSTANCE_ID).apply_pending_decisions("old-token")
    assert exc.value.code == "stale_proposal_version"
    assert exc.value.status == 409
    assert exc.value.details == {"current": "xyz"}


def test_destructive_confirmation_required_surfaces_code(httpx_mock, client):
    httpx_mock.put(f"/instances/{INSTANCE_ID}/schema").mock(
        return_value=httpx.Response(
            409,
            json={
                "status": "error",
                "error_type": "destructive_confirmation_required",
                "error_message": "Set confirm_destructive=True.",
                "details": None,
            },
        )
    )
    plan = MigrationPlan(ops=[RemoveObject(name="Obsolete")])
    with pytest.raises(XmemoryAPIError) as exc:
        client.admin.update_instance_schema(INSTANCE_ID, "objects: {}", SchemaType.YML, migration_plan=plan)
    assert exc.value.code == "destructive_confirmation_required"