"""How schema text is sent, and what a refused write raises.

An XMD schema written as JSON is sent as XMD whichever ``SchemaType`` names it; any other JSON text is sent as JSON
Schema, with a ``DeprecationWarning``. A write the server answers with ``VALIDATION_ERROR`` raises
``WriteRejectedError``, an ``XmemoryAPIError``, carrying the server's ``rejection`` when it sends one; every other
failure raises what it raised before. Write results carry the server's ``warnings``, empty when it sends none.
"""

from __future__ import annotations

import json
import uuid
import warnings

import httpx
import pytest
import respx

from xmemory import (
    AsyncXmemoryClient,
    ExtractionLogic,
    SchemaType,
    WriteRejectedError,
    XmemoryAPIError,
    XmemoryClient,
)

CLUSTER_ID = str(uuid.uuid4())
INSTANCE_ID = str(uuid.uuid4())
BASE_URL = "https://api.xmemory.ai"

XMD_AS_JSON = json.dumps({"objects": {"Gadget": {"fields": {"label": {"type": "str"}}, "primary_key": ["label"]}}})
JSON_SCHEMA = json.dumps({"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]})
DEPRECATED = "JSON Schema input is deprecated: send an XMD schema (SchemaType.YML) instead."

# A rejection object with invented keys and values: the library passes it on as it is.
REJECTION = {"summary": "An invented summary.", "entries": [{"kind": "invented", "label": "Gizmo"}]}


def _ok(items: list[dict]) -> dict:
    return {"ids": [str(uuid.uuid4()) for _ in items], "items": items, "errors": []}


def _error(code: str, message: str, **extra: object) -> dict:
    return {"ids": [], "items": [], "errors": [{"code": code, "message": message, **extra}]}


@pytest.fixture(autouse=True)
def api():
    with respx.mock(base_url=BASE_URL) as mock:
        yield mock


@pytest.fixture()
def client():
    with XmemoryClient(url=BASE_URL, api_key="test-api-key") as c:
        yield c


@pytest.fixture()
async def async_client():
    async with AsyncXmemoryClient(url=BASE_URL, api_key="test-api-key") as c:
        yield c


def _sent_schema(route: respx.Route) -> dict:
    return json.loads(route.calls.last.request.content)["instance_schema"]


def _instance_created(api: respx.MockRouter) -> respx.Route:
    return api.post(f"/clusters/{CLUSTER_ID}/instances").mock(
        return_value=httpx.Response(201, json=_ok([{"id": INSTANCE_ID, "cluster_id": CLUSTER_ID, "name": "inst"}]))
    )


# ---------------------------------------------------------------------------
# Schema input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("schema_type", [SchemaType.JSON, SchemaType.YML])
def test_an_xmd_schema_written_as_json_is_sent_as_xmd_without_a_warning(api, client, schema_type):
    route = _instance_created(api)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        client.admin.create_instance(CLUSTER_ID, "inst", XMD_AS_JSON, schema_type)
    assert _sent_schema(route) == {"yml": {"value": XMD_AS_JSON}, "json_schema": None}


def test_a_json_schema_is_still_sent_as_json_schema_and_warns_once(api, client):
    route = _instance_created(api)
    with pytest.warns(DeprecationWarning) as caught:
        client.admin.create_instance(CLUSTER_ID, "inst", JSON_SCHEMA, SchemaType.JSON)
    assert [str(warning.message) for warning in caught] == [DEPRECATED]
    assert _sent_schema(route) == {"yml": None, "json_schema": {"value": JSON_SCHEMA}}


def test_text_that_is_not_json_named_json_is_sent_as_json_schema_as_before(api, client):
    route = _instance_created(api)
    with pytest.warns(DeprecationWarning):
        client.admin.create_instance(CLUSTER_ID, "inst", "not json at all", SchemaType.JSON)
    assert _sent_schema(route) == {"yml": None, "json_schema": {"value": "not json at all"}}


def test_yml_text_is_sent_as_before_without_a_warning(api, client):
    route = _instance_created(api)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        client.admin.create_instance(CLUSTER_ID, "inst", "objects: {}", SchemaType.YML)
    assert _sent_schema(route) == {"yml": {"value": "objects: {}"}, "json_schema": None}


def test_the_schema_update_and_its_dry_run_send_xmd_as_json_as_xmd(api, client):
    updated = api.put(f"/instances/{INSTANCE_ID}/schema").mock(
        return_value=httpx.Response(200, json=_ok([{"id": INSTANCE_ID, "cluster_id": CLUSTER_ID, "name": "inst"}]))
    )
    dry_run = api.post(f"/instances/{INSTANCE_ID}/migrations/dry_run").mock(
        return_value=httpx.Response(200, json=_ok([{"instance_id": INSTANCE_ID, "current_version": 1}]))
    )
    client.admin.update_instance_schema(INSTANCE_ID, XMD_AS_JSON, SchemaType.JSON)
    client.admin.dry_run_migration(INSTANCE_ID, XMD_AS_JSON, SchemaType.JSON)
    assert _sent_schema(updated) == {"yml": {"value": XMD_AS_JSON}, "json_schema": None}
    assert _sent_schema(dry_run) == {"yml": {"value": XMD_AS_JSON}, "json_schema": None}


async def test_the_async_create_sends_xmd_as_json_as_xmd(api, async_client):
    route = _instance_created(api)
    await async_client.admin.create_instance(CLUSTER_ID, "inst", XMD_AS_JSON, SchemaType.JSON)
    assert _sent_schema(route) == {"yml": {"value": XMD_AS_JSON}, "json_schema": None}


# ---------------------------------------------------------------------------
# Write rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 200])
def test_a_write_refused_with_validation_error_raises_write_rejected_error_with_its_rejection(api, client, status):
    api.post(f"/instances/{INSTANCE_ID}/write").mock(
        return_value=httpx.Response(status, json=_error("VALIDATION_ERROR", "An invented refusal.", details={"rejection": REJECTION}))
    )
    with pytest.raises(WriteRejectedError) as raised:
        client.instance(INSTANCE_ID).write("A teal gadget.")
    assert isinstance(raised.value, XmemoryAPIError)
    assert raised.value.code == "VALIDATION_ERROR"
    assert "An invented refusal." in str(raised.value)
    assert raised.value.rejection == REJECTION


def test_a_refused_write_without_a_rejection_still_raises_write_rejected_error(api, client):
    api.post(f"/instances/{INSTANCE_ID}/write").mock(
        return_value=httpx.Response(400, json=_error("VALIDATION_ERROR", "Exactly one of text or mutations."))
    )
    with pytest.raises(XmemoryAPIError) as raised:
        client.instance(INSTANCE_ID).write("A teal gadget.")
    error = raised.value
    assert isinstance(error, WriteRejectedError)
    assert error.rejection is None


def test_write_async_raises_write_rejected_error_too(api, client):
    api.post(f"/instances/{INSTANCE_ID}/write_async").mock(
        return_value=httpx.Response(400, json=_error("VALIDATION_ERROR", "Refused.", details={"rejection": REJECTION}))
    )
    with pytest.raises(WriteRejectedError) as raised:
        client.instance(INSTANCE_ID).write_async("A teal gadget.")
    assert raised.value.rejection == REJECTION


def test_a_status_poll_for_an_unknown_write_id_raises_what_it_raised_before(api, client):
    """write_status answers ``VALIDATION_ERROR`` for a write id it does not know: no write was refused."""
    api.post(f"/instances/{INSTANCE_ID}/write_status").mock(
        return_value=httpx.Response(400, json=_error("VALIDATION_ERROR", "Invalid write_id: w-unknown"))
    )
    with pytest.raises(XmemoryAPIError) as raised:
        client.instance(INSTANCE_ID).write_status("w-unknown")
    assert type(raised.value) is XmemoryAPIError and raised.value.code == "VALIDATION_ERROR"


async def test_an_async_write_refused_raises_write_rejected_error(api, async_client):
    api.post(f"/instances/{INSTANCE_ID}/write").mock(
        return_value=httpx.Response(400, json=_error("VALIDATION_ERROR", "Refused.", details={"rejection": REJECTION}))
    )
    with pytest.raises(WriteRejectedError) as raised:
        await async_client.instance(INSTANCE_ID).write("A teal gadget.")
    assert raised.value.rejection == REJECTION


def test_a_write_failing_with_another_code_raises_what_it_raised_before(api, client):
    api.post(f"/instances/{INSTANCE_ID}/write").mock(
        return_value=httpx.Response(429, json=_error("QUOTA_EXCEEDED", "Daily quota exhausted."))
    )
    with pytest.raises(XmemoryAPIError) as raised:
        client.instance(INSTANCE_ID).write("A teal gadget.")
    assert type(raised.value) is XmemoryAPIError and raised.value.code == "QUOTA_EXCEEDED"


def test_a_validation_error_on_a_call_that_is_no_write_raises_what_it_raised_before(api, client):
    api.post(f"/clusters/{CLUSTER_ID}/instances").mock(
        return_value=httpx.Response(400, json=_error("VALIDATION_ERROR", "The schema has no objects."))
    )
    with pytest.raises(XmemoryAPIError) as raised:
        client.admin.create_instance(CLUSTER_ID, "inst", "objects: {}", SchemaType.YML)
    assert type(raised.value) is XmemoryAPIError and raised.value.code == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Warnings on write results
# ---------------------------------------------------------------------------


NOTES = [{"code": "NOTE", "message": "An invented note.", "field": "text"}]


@pytest.mark.parametrize("call", ["write", "write_async"])
@pytest.mark.parametrize("sent", [NOTES, None], ids=["sent", "absent"])
def test_a_write_result_carries_the_responses_warnings_or_none(api, client, call, sent):
    body = {**_ok([{"write_id": "w-1"}]), **({"warnings": sent} if sent is not None else {})}
    api.post(f"/instances/{INSTANCE_ID}/{call}").mock(return_value=httpx.Response(200, json=body))
    result = getattr(client.instance(INSTANCE_ID), call)("A teal gadget.")
    assert result.warnings == (sent or [])


async def test_an_async_clients_write_result_carries_the_responses_warnings(api, async_client):
    body = {**_ok([{"write_id": "w-1"}]), "warnings": NOTES}
    api.post(f"/instances/{INSTANCE_ID}/write").mock(return_value=httpx.Response(200, json=body))
    assert (await async_client.instance(INSTANCE_ID).write("A teal gadget.")).warnings == NOTES


def test_a_call_that_is_no_write_leaves_the_responses_warnings_out_of_its_result(api, client):
    body = {**_ok([{"instance_id": INSTANCE_ID, "current_version": 1}]), "warnings": NOTES}
    api.post(f"/instances/{INSTANCE_ID}/migrations/dry_run").mock(return_value=httpx.Response(200, json=body))
    assert client.admin.dry_run_migration(INSTANCE_ID, "objects: {}", SchemaType.YML).warnings == []


@pytest.mark.parametrize("sent", [NOTES, None], ids=["sent", "absent"])
def test_write_status_carries_the_servers_warnings_or_none(api, client, sent):
    item = {"write_id": "w-1", "write_status": "completed", **({"warnings": sent} if sent is not None else {})}
    api.post(f"/instances/{INSTANCE_ID}/write_status").mock(return_value=httpx.Response(200, json=_ok([item])))
    assert client.instance(INSTANCE_ID).write_status("w-1").warnings == (sent or [])


# ---------------------------------------------------------------------------
# A failed write, as write_status reports it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("details", [{"rejection": REJECTION}, None], ids=["with rejection", "without"])
def test_a_failed_status_carries_the_writes_error_and_its_rejection_when_sent(api, client, details):
    error = {"code": "VALIDATION_ERROR", "message": "An invented refusal.", **({"details": details} if details else {})}
    item = {"write_id": "w-1", "write_status": "failed", "error_detail": "An invented refusal.", "error": error}
    api.post(f"/instances/{INSTANCE_ID}/write_status").mock(return_value=httpx.Response(200, json=_ok([item])))
    status = client.instance(INSTANCE_ID).write_status("w-1")
    assert status.write_status.value == "failed" and status.error_detail == "An invented refusal."
    assert status.error is not None
    assert (status.error.code, status.error.message) == ("VALIDATION_ERROR", "An invented refusal.")
    assert status.error.rejection == (REJECTION if details else None)


def test_a_completed_status_has_no_error(api, client):
    item = {"write_id": "w-1", "write_status": "completed"}
    api.post(f"/instances/{INSTANCE_ID}/write_status").mock(return_value=httpx.Response(200, json=_ok([item])))
    assert client.instance(INSTANCE_ID).write_status("w-1").error is None


# ---------------------------------------------------------------------------
# extraction_logic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("call", ["write", "write_async", "extract"])
def test_a_text_call_sends_no_extraction_logic_unless_given_one(api, client, call):
    route = api.post(f"/instances/{INSTANCE_ID}/{call}").mock(
        return_value=httpx.Response(200, json=_ok([{"write_id": "w-1"}]))
    )
    getattr(client.instance(INSTANCE_ID), call)("A teal gadget.")
    assert "extraction_logic" not in json.loads(route.calls.last.request.content)
    getattr(client.instance(INSTANCE_ID), call)("A teal gadget.", extraction_logic=ExtractionLogic.DEEP)
    assert json.loads(route.calls.last.request.content)["extraction_logic"] == "deep"
