"""Unit tests for the schema-evolution surface (admin + instance methods)."""
from __future__ import annotations

import json
import uuid

import httpx
import pytest
import respx

from xmemory import (
    AddField,
    ApplyPendingDecisionsResult,
    AsyncXmemoryClient,
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


def test_an_add_relation_keeps_the_relations_own_fields():
    wire = {
        "op_type": "add_relation",
        "name": "employment",
        "objects": {"person": "person", "company": "company"},
        "fields": [
            {"name": "title", "type": "str", "description": "job title at this company"},
            {"name": "started_on", "type": "str"},
        ],
    }
    op = parse_migration_op(wire)
    assert isinstance(op, AddRelation)
    assert [f.name for f in op.fields or []] == ["title", "started_on"]
    assert op.fields is not None and op.fields[0].description == "job title at this company"

    dumped = MigrationPlan(ops=[op]).model_dump(mode="json")
    assert [f["name"] for f in dumped["ops"][0]["fields"]] == ["title", "started_on"]
    assert parse_migration_plan(dumped).ops == [op]


def test_an_add_relation_is_sent_back_without_a_key_this_client_does_not_model():
    # A server may add op keys a client does not know yet; sending one back could be refused,
    # so a parsed op carries only the keys modelled here.
    op = parse_migration_op(
        {
            "op_type": "add_relation",
            "name": "employment",
            "objects": {"person": "person", "company": "company"},
            "fields": [{"name": "title", "type": "str"}],
            "a_later_option": {"name": "title"},
        }
    )
    dumped = MigrationPlan(ops=[op]).model_dump(mode="json")["ops"][0]
    assert "a_later_option" not in dumped
    assert [f["name"] for f in dumped["fields"]] == ["title"]


def test_add_relation_serialization_json_schema_keeps_its_shape():
    schema = AddRelation.model_json_schema(mode="serialization")
    assert {"name", "objects", "fields"} <= set(schema["properties"])


@pytest.mark.parametrize("fields", [None, []])
def test_an_add_relation_without_fields_of_its_own_serializes_without_the_key(fields):
    op = AddRelation(name="Knows", objects={"a": "Contact", "b": "Contact"}, fields=fields)
    assert op.fields is None
    assert "fields" not in op.model_dump(mode="json")
    assert "fields" not in MigrationPlan(ops=[op]).model_dump(mode="json")["ops"][0]


# Format and label keys, as an enhanced plan carries them: each must survive a parse and a dump,
# since an op that lost its only change would be refused when sent back.
_FORMAT_AND_LABEL_OPS = [
    {"op_type": "change_field", "object_name": "Zelk", "field_name": "plix",
     "new_format": {"brask": "v1"}},
    {"op_type": "change_field", "object_name": "Zelk", "field_name": "plix", "clear_format": True},
    {"op_type": "change_field", "object_name": "Zelk", "field_name": "dovra", "new_field_kind": "drem"},
    {"op_type": "add_field", "object_name": "Zelk", "field_name": "quen", "field_type": "float",
     "format": {"osk": "pell", "drun": 2}, "field_kind": "frell"},
    {"op_type": "add_object", "name": "Morv", "primary_key": [],
     "fields": [{"name": "tarsk", "type": "str", "format": {"vorn": True}, "field_kind": "frell"}],
     "interval": True},
    {"op_type": "change_object", "name": "Morv", "new_interval": False},
    {"op_type": "add_relation", "name": "brindle", "objects": {"zelk": "Zelk", "morv": "Morv"},
     "fields": [{"name": "vasp", "type": "str", "field_kind": "skarn"}]},
]


@pytest.mark.parametrize("wire", _FORMAT_AND_LABEL_OPS, ids=lambda wire: wire["op_type"])
def test_a_format_or_label_key_survives_the_round_trip(wire):
    dumped = MigrationPlan(ops=[parse_migration_op(wire)]).model_dump(mode="json")["ops"][0]
    for key, value in wire.items():
        if key == "fields":
            assert [{k: f[k] for k in field} for f, field in zip(dumped[key], value)] == value
        else:
            assert dumped[key] == value
    assert parse_migration_plan({"ops": [dumped]}).ops == [parse_migration_op(wire)]


def test_format_and_label_keys_are_left_out_while_unset():
    assert set(ChangeField(object_name="Zelk", field_name="dovra", new_description="x").model_dump(mode="json")).isdisjoint(
        {"new_format", "clear_format", "new_field_kind"}
    )
    assert set(AddField(object_name="Zelk", field_name="x", field_type="str").model_dump(mode="json")).isdisjoint(
        {"format", "field_kind"}
    )
    assert set(FieldSpec(name="x", type="str").model_dump(mode="json")).isdisjoint({"format", "field_kind"})
    assert "interval" not in AddObject(name="Morv", fields=[FieldSpec(name="x", type="str")]).model_dump(mode="json")
    assert "new_interval" not in ChangeObject(name="Morv", new_description="x").model_dump(mode="json")
    # A stated `false` label is a value, not an unset key.
    assert AddObject(name="Morv", fields=[], interval=False).model_dump(mode="json")["interval"] is False


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


def test_enhance_schema_keeps_a_new_relations_own_fields(httpx_mock, client):
    add_employment = {
        "op_type": "add_relation",
        "name": "employment",
        "objects": {"person": "person", "company": "company"},
        "fields": [{"name": "title", "type": "str"}],
    }
    payload = {
        "data_schema": {"objects": {}},
        "migration_plan": {"ops": [add_employment]},
        "summary": "add employment",
        "warnings": [],
        "repair_log": [],
    }
    httpx_mock.post(f"/clusters/{CLUSTER_ID}/instances/generate_schema").mock(
        return_value=httpx.Response(200, json=_api_ok([payload]))
    )

    result = client.admin.enhance_schema(CLUSTER_ID, "add employment", "objects: {}")

    assert result.migration_plan is not None
    op = result.migration_plan.ops[0]
    assert isinstance(op, AddRelation)
    assert [f.name for f in op.fields or []] == ["title"]


# ---------------------------------------------------------------------------
# admin.enhance_instance_schema — the instance's own route
# ---------------------------------------------------------------------------

_ENHANCED = {
    "data_schema": {"objects": {}},
    "migration_plan": {"ops": [{"op_type": "rename_field", "object_name": "P", "old_name": "a", "new_name": "b"}]},
    "summary": "rename a to b",
    "warnings": [],
    "repair_log": [],
}


def test_enhance_instance_schema_posts_to_the_instances_route(httpx_mock, client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/schema/enhance").mock(
        return_value=httpx.Response(200, json=_api_ok([_ENHANCED]))
    )

    result = client.admin.enhance_instance_schema(INSTANCE_ID, "rename a to b", "objects:\n  P: {}")

    assert route.called
    assert json.loads(route.calls.last.request.content) == {
        "schema_description": "rename a to b",
        "current_yml_schema": "objects:\n  P: {}",
    }
    assert isinstance(result, EnhanceSchemaResult)
    assert result.migration_plan is not None
    assert isinstance(result.migration_plan.ops[0], RenameField)
    assert result.summary == "rename a to b"


async def test_enhance_instance_schema_posts_to_the_instances_route_async(httpx_mock, base_url):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/schema/enhance").mock(
        return_value=httpx.Response(200, json=_api_ok([_ENHANCED]))
    )

    async with AsyncXmemoryClient(url=base_url, api_key="test-api-key") as async_client:
        result = await async_client.admin.enhance_instance_schema(INSTANCE_ID, "rename a to b", "objects:\n  P: {}")

    assert route.called
    assert json.loads(route.calls.last.request.content) == {
        "schema_description": "rename a to b",
        "current_yml_schema": "objects:\n  P: {}",
    }
    assert isinstance(result, EnhanceSchemaResult)
    assert result.summary == "rename a to b"


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


def test_update_instance_schema_sends_a_relations_own_fields(httpx_mock, client):
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
                    }
                ]
            ),
        )
    )

    plan = MigrationPlan(
        ops=[
            AddRelation(
                name="employment",
                objects={"person": "person", "company": "company"},
                fields=[FieldSpec(name="title", type="str")],
            )
        ]
    )
    client.admin.update_instance_schema(INSTANCE_ID, "objects: {}", SchemaType.YML, migration_plan=plan)

    sent = json.loads(route.calls.last.request.read())
    assert sent["migration_plan"]["ops"][0]["fields"] == [
        {"name": "title", "type": "str", "required": False, "description": None, "default": None, "enum": None}
    ]


def test_an_enhanced_format_change_is_sent_back_as_the_server_wrote_it(httpx_mock, client):
    change = {"op_type": "change_field", "object_name": "Zelk", "field_name": "plix",
              "new_format": {"brask": "v1"}}
    httpx_mock.post(f"/instances/{INSTANCE_ID}/schema/enhance").mock(
        return_value=httpx.Response(200, json=_api_ok([{**_ENHANCED, "migration_plan": {"ops": [change]}}]))
    )
    route = httpx_mock.put(f"/instances/{INSTANCE_ID}/schema").mock(
        return_value=httpx.Response(
            200,
            json=_api_ok(
                [
                    {
                        "id": INSTANCE_ID,
                        "cluster_id": CLUSTER_ID,
                        "name": "zelks",
                        "description": None,
                        "data_schema": {"objects": {}},
                        "migration_id": MIGRATION_ID,
                        "prior_version": 3,
                        "new_version": 4,
                    }
                ]
            ),
        )
    )

    enhanced = client.admin.enhance_instance_schema(INSTANCE_ID, "plix keeps its brask", "objects: {}")
    client.admin.update_instance_schema(
        INSTANCE_ID, "objects: {}", SchemaType.YML, migration_plan=enhanced.migration_plan
    )

    sent = json.loads(route.calls.last.request.read())["migration_plan"]["ops"][0]
    assert sent["new_format"] == {"brask": "v1"}
    assert "clear_format" not in sent and "new_field_kind" not in sent


async def test_the_async_client_sends_a_label_change_as_written(httpx_mock, base_url):
    route = httpx_mock.put(f"/instances/{INSTANCE_ID}/schema").mock(
        return_value=httpx.Response(
            200,
            json=_api_ok(
                [
                    {
                        "id": INSTANCE_ID,
                        "cluster_id": CLUSTER_ID,
                        "name": "zelks",
                        "description": None,
                        "data_schema": {"objects": {}},
                        "migration_id": MIGRATION_ID,
                        "prior_version": 3,
                        "new_version": 4,
                    }
                ]
            ),
        )
    )
    plan = parse_migration_plan(
        {"ops": [{"op_type": "change_field", "object_name": "Zelk", "field_name": "dovra", "new_field_kind": "drem"}]}
    )

    async with AsyncXmemoryClient(url=base_url, api_key="test-api-key") as async_client:
        await async_client.admin.update_instance_schema(INSTANCE_ID, "objects: {}", SchemaType.YML, migration_plan=plan)

    sent = json.loads(route.calls.last.request.read())["migration_plan"]["ops"][0]
    assert sent["new_field_kind"] == "drem"
    assert "new_format" not in sent and "clear_format" not in sent


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
    # A server that predates apply_blocked sends no flag; the item reads as appliable.
    assert result.proposal.items[0].apply_blocked is False


def test_review_suggestions_carries_apply_blocked(httpx_mock, client):
    blocked_rationale = (
        "cannot be applied: phone is already part of the proposed object Contact — "
        "accepting both fails the whole apply, and accepting the object alone already adds it"
    )
    proposal = {
        "instance_id": INSTANCE_ID,
        "proposal_version": "abc123",
        "schema_version": 4,
        "items": [
            {
                "item_fingerprint": "fp-object",
                "op": {"op_type": "add_object", "name": "Contact", "description": "A contact."},
                "rationale": "queried but missing",
                "apply_blocked": False,
            },
            {
                "item_fingerprint": "fp-field",
                "op": {"op_type": "add_field", "object_name": "Contact", "field_name": "phone", "field_type": "str"},
                "rationale": blocked_rationale,
                "apply_blocked": True,
            },
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
    assert result.proposal is not None
    by_fingerprint = {item.item_fingerprint: item for item in result.proposal.items}
    assert by_fingerprint["fp-object"].apply_blocked is False
    assert by_fingerprint["fp-field"].apply_blocked is True
    assert by_fingerprint["fp-field"].rationale == blocked_rationale
    appliable = [item.item_fingerprint for item in result.proposal.items if not item.apply_blocked]
    assert appliable == ["fp-object"]


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


def _schema_error_on_a_200(error_type: str, details: dict) -> httpx.Response:
    """A long-running call: 200 first, padding while it runs, then the error payload."""
    body = {"status": "error", "error_type": error_type, "error_message": "Re-review.", "details": details}
    return httpx.Response(200, content=b"   " + json.dumps(body).encode())


def test_schema_error_on_a_200_keeps_its_code(httpx_mock, client):
    httpx_mock.post(f"/instances/{INSTANCE_ID}/suggestions/apply").mock(
        return_value=_schema_error_on_a_200("apply_failed", {"detached_accept_fingerprints": ["fp1"]})
    )
    with pytest.raises(XmemoryAPIError) as exc:
        client.instance(INSTANCE_ID).apply_pending_decisions("tok-1")
    assert exc.value.code == "apply_failed"
    assert exc.value.details == {"detached_accept_fingerprints": ["fp1"]}
    assert exc.value.status == 200


async def test_schema_error_on_a_200_keeps_its_code_async(httpx_mock, base_url):
    httpx_mock.post(f"/instances/{INSTANCE_ID}/suggestions/decide").mock(
        return_value=_schema_error_on_a_200("stale_proposal_version", {"current": "xyz"})
    )
    async with AsyncXmemoryClient(url=base_url, api_key="test-api-key") as async_client:
        with pytest.raises(XmemoryAPIError) as exc:
            await async_client.instance(INSTANCE_ID).decide_suggestions(
                "abc123", [DecisionInput(item_fingerprint="fp1", decision="accept")]
            )
    assert exc.value.code == "stale_proposal_version"
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