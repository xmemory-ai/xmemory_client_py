"""Unit tests for XmemoryClient / AdminAPI / InstanceAPI."""
from __future__ import annotations

import json
import re
import uuid

import httpx
import pytest
import respx

from xmemory import _version
from xmemory._admin import _as_str_list
from xmemory import (
    __version__,
    AgentSetupResult,
    AgentSetupStep,
    AgentSetupSurface,
    AgentSurface,
    AsyncXmemoryClient,
    BindingTier,
    FragmentMerge,
    InstanceAPI,
    ObjectCreate,
    ObjectDelete,
    ObjectMutation,
    ObjectUpdate,
    RelationDelete,
    RelationEndpoint,
    RelationMutation,
    ProjectFragment,
    ScopeObject,
    ProjectSetup,
    SchemaType,
    SetupFormat,
    StepKind,
    WriteScope,
    XmemoryAPIError,
    XmemoryClient,
    CLIENT_HEADER,
    client_identity,
)

CLUSTER_ID = str(uuid.uuid4())
INSTANCE_ID = str(uuid.uuid4())
ORG_ID = str(uuid.uuid4())


def _api_ok(items: list[dict], ids: list[str] | None = None) -> dict:
    return {
        "ids": ids or [item.get("id", str(uuid.uuid4())) for item in items],
        "items": items,
        "errors": [],
    }


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


@pytest.fixture()
async def async_client(base_url):
    async with AsyncXmemoryClient(url=base_url, api_key="test-api-key") as c:
        yield c


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


def test_client_default_construction():
    c = XmemoryClient(url="http://localhost:8000")
    c.close()


def test_client_rejects_url_and_http_client():
    with pytest.raises(ValueError):
        XmemoryClient(
            url="http://localhost:8000",
            http_client=httpx.Client(base_url="http://localhost:8000"),
        )


def test_client_context_manager(client):
    assert client.admin is not None


def test_api_key_passed_in_auth_header(httpx_mock, client):
    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))

    client.admin.list_clusters()

    assert route.called
    assert route.calls.last.request.headers["authorization"] == "Bearer test-api-key"
    assert route.calls.last.request.headers[CLIENT_HEADER] == client_identity()


# ---------------------------------------------------------------------------
# Legacy `token` term — accepted with a deprecation notice
# ---------------------------------------------------------------------------


def test_legacy_token_argument_warns_and_still_works(httpx_mock, base_url, capsys):
    """Passing ``token=`` (legacy) must still authenticate but print an
    orange-colored deprecation notice naming the legacy term."""
    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))

    with XmemoryClient(url=base_url, token="legacy-value") as c:
        c.admin.list_clusters()

    err = capsys.readouterr().err
    assert "DeprecationWarning" in err
    assert "token" in err
    assert "\033[38;5;208m" in err  # orange ANSI prefix
    assert route.calls.last.request.headers["authorization"] == "Bearer legacy-value"


def test_legacy_token_env_var_warns_and_still_works(httpx_mock, base_url, monkeypatch, capsys):
    """``XMEM_AUTH_TOKEN`` is the legacy env var; it must still work but warn."""
    monkeypatch.delenv("XMEM_API_KEY", raising=False)
    monkeypatch.setenv("XMEM_AUTH_TOKEN", "legacy-env-value")
    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))

    with XmemoryClient(url=base_url) as c:
        c.admin.list_clusters()

    err = capsys.readouterr().err
    assert "DeprecationWarning" in err
    assert "XMEM_AUTH_TOKEN" in err
    assert "\033[38;5;208m" in err
    assert route.calls.last.request.headers["authorization"] == "Bearer legacy-env-value"


def test_api_key_argument_takes_precedence_over_legacy_token(base_url, capsys):
    """``api_key=`` wins over ``token=`` and silences the deprecation notice."""
    with XmemoryClient(url=base_url, api_key="new-value", token="old-value"):
        pass

    err = capsys.readouterr().err
    assert "DeprecationWarning" not in err


def test_new_env_var_preferred_over_legacy(httpx_mock, base_url, monkeypatch, capsys):
    """``XMEM_API_KEY`` is checked before ``XMEM_AUTH_TOKEN`` (no warning)."""
    monkeypatch.setenv("XMEM_API_KEY", "new-env-value")
    monkeypatch.setenv("XMEM_AUTH_TOKEN", "legacy-env-value")
    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))

    with XmemoryClient(url=base_url) as c:
        c.admin.list_clusters()

    err = capsys.readouterr().err
    assert "DeprecationWarning" not in err
    assert route.calls.last.request.headers["authorization"] == "Bearer new-env-value"


# ---------------------------------------------------------------------------
# Admin — clusters
# ---------------------------------------------------------------------------


def test_admin_list_clusters(httpx_mock, client):
    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([
        {"id": CLUSTER_ID, "org_id": ORG_ID, "name": "c1", "description": None},
    ])))

    clusters = client.admin.list_clusters()

    assert len(clusters) == 1
    assert clusters[0].name == "c1"
    assert route.called
    assert "verbose=true" in str(route.calls.last.request.url)


def test_admin_get_cluster(httpx_mock, client):
    route = httpx_mock.get(f"/clusters/{CLUSTER_ID}").mock(return_value=httpx.Response(200, json=_api_ok([
        {"id": CLUSTER_ID, "org_id": ORG_ID, "name": "c1", "description": "desc"},
    ])))

    cluster = client.admin.get_cluster(CLUSTER_ID)

    assert cluster.description == "desc"
    assert route.called


# ---------------------------------------------------------------------------
# Admin — instances
# ---------------------------------------------------------------------------


def test_admin_create_instance_returns_instance_api(httpx_mock, client):
    route = httpx_mock.post(f"/clusters/{CLUSTER_ID}/instances").mock(return_value=httpx.Response(201, json=_api_ok([
        {"id": INSTANCE_ID, "cluster_id": CLUSTER_ID, "name": "my-inst", "description": None},
    ])))

    inst = client.admin.create_instance(CLUSTER_ID, "my-inst", "tables: []", SchemaType.YML)

    assert isinstance(inst, InstanceAPI)
    assert inst.id == INSTANCE_ID
    assert route.called
    assert b'"name":"my-inst"' in route.calls.last.request.content


def test_admin_list_instances(httpx_mock, client):
    route = httpx_mock.get("/instances").mock(return_value=httpx.Response(200, json=_api_ok([
        {"id": INSTANCE_ID, "cluster_id": CLUSTER_ID, "name": "inst", "description": None},
    ])))

    instances = client.admin.list_instances()

    assert len(instances) == 1
    assert route.called


def test_admin_get_instance(httpx_mock, client):
    route = httpx_mock.get(f"/instances/{INSTANCE_ID}").mock(return_value=httpx.Response(200, json=_api_ok([
        {"id": INSTANCE_ID, "cluster_id": CLUSTER_ID, "name": "inst", "description": "d"},
    ])))

    info = client.admin.get_instance(INSTANCE_ID)

    assert info.description == "d"
    assert route.called


def test_instance_setup_instructions_is_available_without_the_admin_namespace(httpx_mock, client):
    """The MCP instance connection serves this tool, so an instance handle must too.

    A caller holding an instance handle should not have to reach through ``admin`` for
    the one question this payload answers, when the same tool sits on the instance
    connection over MCP.
    """
    route = httpx_mock.get(f"/instances/{INSTANCE_ID}/agent_setup").mock(return_value=httpx.Response(200, json=_api_ok([
        {
            "instance_id": INSTANCE_ID,
            "instance_name": "Sprint tracker",
            "install_page_url": "https://xmemory.ai/install",
            "surfaces": [
                {
                    "surface": "claude_code",
                    "label": "Claude Code",
                    "steps": [{"description": "Install it.", "command": "claude plugin install x", "kind": "shell"}],
                    "human_steps": ["Approve each command when the agent asks to run it."],
                },
            ],
            "paste_to_agent": "",
        },
    ])))

    setup = client.instance(INSTANCE_ID).setup_instructions()

    assert setup.instance_id == INSTANCE_ID
    assert route.called
    # The public model classes, asserted as instances: without this the exports could be
    # dropped from __init__ and every other test here would still pass.
    assert isinstance(setup, AgentSetupResult)
    assert isinstance(setup.surfaces[0], AgentSetupSurface)
    assert isinstance(setup.surfaces[0].steps[0], AgentSetupStep)
    assert setup.project is None


def test_instance_setup_instructions_asks_for_the_project_format(httpx_mock, client):
    # The instance handle maps its own path and parameter, so the format can be dropped
    # here while the admin path still carries it.
    route = httpx_mock.get(f"/instances/{INSTANCE_ID}/agent_setup").mock(return_value=httpx.Response(200, json=_api_ok([
        {
            "instance_id": INSTANCE_ID,
            "instance_name": "Sprint tracker",
            "install_page_url": "https://xmemory.ai/install",
            "surfaces": [],
            "paste_to_agent": "",
            "format": "project",
            "project": {
                "fragments": [
                    {"path": ".mcp.json", "purpose": "point the team at it", "merge": "merge_json", "content": "{}"},
                ],
                "manual_steps": ["Each teammate signs in once."],
            },
        },
    ])))

    setup = client.instance(INSTANCE_ID).setup_instructions(format=SetupFormat.PROJECT)

    assert route.calls.last.request.url.params["format"] == "project"
    assert isinstance(setup.project, ProjectSetup)
    assert isinstance(setup.project.fragments[0], ProjectFragment)


async def test_async_setup_instructions_map_the_same_routes(httpx_mock, async_client):
    """Both async entry points duplicate their own path and parameter mapping.

    A wrong route or a dropped format in either is invisible to the sync tests above,
    which is exactly the kind of copy that drifts.
    """
    route = httpx_mock.get(f"/instances/{INSTANCE_ID}/agent_setup").mock(return_value=httpx.Response(200, json=_api_ok([
        {
            "instance_id": INSTANCE_ID,
            "instance_name": "Sprint tracker",
            "install_page_url": "https://xmemory.ai/install",
            "surfaces": [],
            "paste_to_agent": "",
        },
    ])))

    via_admin = await async_client.admin.get_setup_instructions(INSTANCE_ID, format=SetupFormat.PROJECT)
    assert route.calls.last.request.url.params["format"] == "project"
    assert via_admin.instance_id == INSTANCE_ID

    via_handle = await async_client.instance(INSTANCE_ID).setup_instructions()
    assert route.calls.last.request.url.params["format"] == "agent"
    assert via_handle.instance_id == INSTANCE_ID


def test_admin_get_setup_instructions(httpx_mock, client):
    route = httpx_mock.get(f"/instances/{INSTANCE_ID}/agent_setup").mock(return_value=httpx.Response(200, json=_api_ok([
        {
            "instance_id": INSTANCE_ID,
            "instance_name": "Sprint tracker",
            "install_page_url": "https://xmemory.ai/install",
            "surfaces": [
                {
                    "surface": "claude_code",
                    "label": "Claude Code",
                    "steps": [{"description": "Install it.", "command": "claude plugin install x", "kind": "shell"}],
                    "human_steps": ["Approve each command when the agent asks to run it."],
                },
            ],
            "paste_to_agent": "Connect xmemory instance ...",
            "format": "agent",
            "project": None,
        },
    ])))

    setup = client.admin.get_setup_instructions(INSTANCE_ID)

    assert setup.instance_name == "Sprint tracker"
    assert setup.surfaces[0].steps[0].kind is StepKind.SHELL
    # Relayed, not dropped: they are the consent the flow depends on.
    assert setup.surfaces[0].human_steps
    assert setup.format is SetupFormat.AGENT
    assert route.called
    assert route.calls.last.request.url.params["format"] == "agent"


def test_admin_setup_instructions_asks_for_the_project_format(httpx_mock, client):
    route = httpx_mock.get(f"/instances/{INSTANCE_ID}/agent_setup").mock(return_value=httpx.Response(200, json=_api_ok([
        {
            "instance_id": INSTANCE_ID,
            "instance_name": "Sprint tracker",
            "install_page_url": "https://xmemory.ai/install",
            "surfaces": [],
            "paste_to_agent": "",
            "format": "project",
            "project": {
                "fragments": [
                    {"path": ".mcp.json", "purpose": "point the team at it", "merge": "merge_json", "content": "{}"},
                ],
                "manual_steps": ["Each teammate signs in once."],
            },
        },
    ])))

    setup = client.admin.get_setup_instructions(INSTANCE_ID, format=SetupFormat.PROJECT)

    assert route.calls.last.request.url.params["format"] == "project"
    assert setup.project is not None
    # A merge, never a file to overwrite — a repository's existing config must survive.
    assert setup.project.fragments[0].merge is FragmentMerge.MERGE_JSON
    assert setup.project.manual_steps


def test_admin_setup_instructions_reports_the_format_actually_rendered(httpx_mock, client):
    """A server older than ``format`` ignores it and still answers 200.

    So asking for the project rendering is not the same as receiving it, and a caller
    that inferred success from the request would read an agent payload as "this
    instance has nothing committable". The echoed field is the only way to tell.
    """
    httpx_mock.get(f"/instances/{INSTANCE_ID}/agent_setup").mock(return_value=httpx.Response(200, json=_api_ok([
        {
            "instance_id": INSTANCE_ID,
            "instance_name": "Sprint tracker",
            "install_page_url": "https://xmemory.ai/install",
            "surfaces": [],
            "paste_to_agent": "",
        },
    ])))

    setup = client.admin.get_setup_instructions(INSTANCE_ID, format=SetupFormat.PROJECT)

    assert setup.format is SetupFormat.AGENT, "an omitted format means the server rendered the default"
    assert setup.project is None


def test_admin_setup_instructions_survives_enum_values_from_a_newer_server(httpx_mock, client):
    """An advisory value added after this release must not reject the whole payload.

    `kind`, `merge` and `format` are all closed sets today, and a strict enum on any of
    them turns an additive server change into a hard failure for every older client —
    the whole result, not the one field. Known values still arrive as enum members, so
    `kind is StepKind.SHELL` keeps working; an unrecognised one arrives as a string,
    which is not any known kind and therefore not something to execute.
    """
    httpx_mock.get(f"/instances/{INSTANCE_ID}/agent_setup").mock(return_value=httpx.Response(200, json=_api_ok([
        {
            "instance_id": INSTANCE_ID,
            "instance_name": "Sprint tracker",
            "install_page_url": "https://xmemory.ai/install",
            "surfaces": [
                {
                    "surface": "claude_code",
                    "label": "Claude Code",
                    "steps": [{"description": "Do a new thing.", "command": "x", "kind": "some_new_kind"}],
                    "human_steps": [],
                },
            ],
            "paste_to_agent": "",
            "format": "some_new_format",
            "project": {
                "fragments": [{"path": "p", "purpose": "x", "merge": "merge_yaml", "content": "c"}],
                "manual_steps": [],
            },
        },
    ])))

    setup = client.admin.get_setup_instructions(INSTANCE_ID)

    assert setup.surfaces[0].steps[0].kind == "some_new_kind"
    assert setup.surfaces[0].steps[0].kind is not StepKind.SHELL, "an unknown kind is not executable"
    assert setup.format == "some_new_format"
    assert setup.project is not None and setup.project.fragments[0].merge == "merge_yaml"


def test_admin_setup_instructions_survives_a_surface_it_has_never_heard_of(httpx_mock, client):
    """A server may name a surface newer than this release.

    Typing ``surface`` as the AgentSurface enum would make every new surface a breaking
    change for every older client, which is the opposite of what an additive server
    change should cost.
    """
    httpx_mock.get(f"/instances/{INSTANCE_ID}/agent_setup").mock(return_value=httpx.Response(200, json=_api_ok([
        {
            "instance_id": INSTANCE_ID,
            "instance_name": "Sprint tracker",
            "install_page_url": "https://xmemory.ai/install",
            "surfaces": [{"surface": "some_future_client", "label": "Future", "steps": [], "human_steps": []}],
            "paste_to_agent": "",
            "unknown_field_from_a_newer_server": True,
        },
    ])))

    setup = client.admin.get_setup_instructions(INSTANCE_ID)

    assert setup.surfaces[0].surface == "some_future_client"


def test_admin_generate_schema(httpx_mock, client):
    route = httpx_mock.post(f"/clusters/{CLUSTER_ID}/instances/generate_schema").mock(
        return_value=httpx.Response(200, json=_api_ok([
            {"data_schema": {"tables": []}},
        ])),
    )

    result = client.admin.generate_schema(CLUSTER_ID, "a CRM")

    assert result.data_schema == {"tables": []}
    assert route.called
    assert b'"schema_description":"a CRM"' in route.calls.last.request.content


# ---------------------------------------------------------------------------
# InstanceAPI — data operations
# ---------------------------------------------------------------------------


def test_instance_read(httpx_mock, client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/read").mock(return_value=httpx.Response(200, json=_api_ok([
        {"trace_id": "r-1", "reader_result": {"answer": "An engineer"}},
    ])))

    resp = client.instance(INSTANCE_ID).read("Who is Bob?")

    assert resp.reader_result == {"answer": "An engineer"}
    assert resp.reader_results == []
    assert route.called
    assert b'"query":"Who is Bob?"' in route.calls.last.request.content
    assert b'"mode":"single-answer"' in route.calls.last.request.content


def test_instance_read_decomposed(httpx_mock, client):
    httpx_mock.post(f"/instances/{INSTANCE_ID}/read").mock(return_value=httpx.Response(200, json=_api_ok([
        {
            "trace_id": "r-1",
            "reader_result": "combined answer",
            "reader_results": [
                {"sub_query": "Who is Bob?", "reader_result": "An engineer"},
                {"sub_query": "Who is Ann?", "reader_result": "", "error": "no data"},
            ],
        },
    ])))

    resp = client.instance(INSTANCE_ID).read("Who are Bob and Ann?")

    assert resp.reader_result == "combined answer"
    assert [r.sub_query for r in resp.reader_results] == ["Who is Bob?", "Who is Ann?"]
    assert resp.reader_results[0].reader_result == "An engineer"
    assert resp.reader_results[0].error is None
    assert resp.reader_results[1].error == "no data"


def test_instance_describe_exposes_about(httpx_mock, client):
    route = httpx_mock.get(f"/instances/{INSTANCE_ID}/describe").mock(return_value=httpx.Response(200, json=_api_ok([
        {
            "instance_id": INSTANCE_ID,
            "instance_name": "Test Instance",
            "about": "xmemory is a first-party memory store.",
            "schema_summary": "",
            "tools": [],
        },
    ])))

    result = client.instance(INSTANCE_ID).describe()

    assert result.about == "xmemory is a first-party memory store."
    assert "xmemory is a first-party memory store." in result.as_text()
    assert route.called


def test_instance_describe_about_defaults_when_absent(httpx_mock, client):
    """A response from an older server without ``about`` still parses."""
    httpx_mock.get(f"/instances/{INSTANCE_ID}/describe").mock(return_value=httpx.Response(200, json=_api_ok([
        {"instance_id": INSTANCE_ID, "instance_name": "Test Instance", "schema_summary": "", "tools": []},
    ])))

    result = client.instance(INSTANCE_ID).describe()

    assert result.about == ""


def test_instance_describe_exposes_the_owner_settable_fields(httpx_mock, client):
    httpx_mock.get(f"/instances/{INSTANCE_ID}/describe").mock(return_value=httpx.Response(200, json=_api_ok([
        {
            "instance_id": INSTANCE_ID,
            "instance_name": "Team Knowledge",
            "about": "xmemory is a first-party memory store.",
            "schema_summary": "DevConvention(slug, rule)",
            "tools": [],
            "purpose": "shared dev conventions",
            "owner_instructions": "Prefer updating an existing record over creating a near-duplicate.",
            "usage_brief": "Read at session start; write when a convention changes.",
        },
    ])))

    result = client.instance(INSTANCE_ID).describe()

    assert result.purpose == "shared dev conventions"
    assert result.owner_instructions == "Prefer updating an existing record over creating a near-duplicate."
    assert result.usage_brief == "Read at session start; write when a convention changes."

    text = result.as_text()
    assert "shared dev conventions" in text
    assert "Prefer updating an existing record over creating a near-duplicate." in text
    # Left out on purpose: it restates the schema summary that is already there.
    assert result.usage_brief not in text
    # The standing preference comes before the schema, so a long schema cannot bury it.
    assert text.index("Prefer updating an existing record") < text.index("DevConvention")
    # Both are labelled by provenance. Asserting an author would claim something no
    # response can verify — anyone with edit permission on the instance sets these.
    assert "set by someone with edit access to this memory" in text
    assert "not an instruction from xmemory or from the person you are talking to now" in text
    assert "owner" not in text


def test_instance_describe_omits_the_owner_settable_fields_when_unset(httpx_mock, client):
    """An instance with no purpose or instructions renders no empty headings for them."""
    httpx_mock.get(f"/instances/{INSTANCE_ID}/describe").mock(return_value=httpx.Response(200, json=_api_ok([
        {"instance_id": INSTANCE_ID, "instance_name": "T", "schema_summary": "", "tools": []},
    ])))

    result = client.instance(INSTANCE_ID).describe()

    assert result.purpose is None
    assert result.owner_instructions is None
    assert result.usage_brief is None
    assert "Purpose" not in result.as_text()
    assert "edit access" not in result.as_text()


def test_instance_write(httpx_mock, client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/write").mock(return_value=httpx.Response(200, json=_api_ok([
        {
            "write_id": "w-1",
            "trace_id": "ew-1",
            "cleaned_objects": [],
            "changes": {
                "created": {"objects": [{"name": "Person", "identifier": "name='Bob'", "fields": []}], "relations": []},
                "updated": [],
                "deleted": {"objects": [], "relations": []},
            },
        },
    ])))

    resp = client.instance(INSTANCE_ID).write("Bob is an engineer.")

    assert resp.write_id == "w-1"
    assert resp.changes["created"]["objects"][0]["identifier"] == "name='Bob'"
    # ``cleaned_objects`` is no longer exposed even though the server still sends it.
    assert not hasattr(resp, "cleaned_objects")
    assert route.called
    assert b'"text":"Bob is an engineer."' in route.calls.last.request.content
    assert b'"extraction_logic":"fast"' in route.calls.last.request.content


def test_instance_write_async(httpx_mock, client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/write_async").mock(
        return_value=httpx.Response(200, json=_api_ok([{"write_id": "w-async-1"}])),
    )

    resp = client.instance(INSTANCE_ID).write_async("some text")

    assert resp.write_id == "w-async-1"
    assert route.called


def test_text_write_omits_structured_mutations_key(httpx_mock, client):
    """Plain text writes must stay byte-identical: older servers reject unknown keys."""
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/write").mock(
        return_value=httpx.Response(200, json=_api_ok([{"write_id": "w-1"}])),
    )

    client.instance(INSTANCE_ID).write("Bob is an engineer.")

    assert b"structured_mutations" not in route.calls.last.request.content


def test_instance_write_structured(httpx_mock, client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/write").mock(return_value=httpx.Response(200, json=_api_ok([
        {
            "write_id": "w-1",
            "trace_id": "ew-1",
            "changes": {
                "created": {"objects": [{"name": "person", "identifier": "email='a@x.io'", "fields": []}], "relations": []},
                "updated": [],
                "deleted": {"objects": [], "relations": []},
            },
        },
    ])))

    resp = client.instance(INSTANCE_ID).write(structured_mutations=[
        ObjectMutation(
            object_type="person",
            create=ObjectCreate(key={"email": "a@x.io"}, values={"name": "Alice"}),
        ),
        # A raw dict in the wire form is passed through untouched.
        {"relation_mutation": {"relation_type": "works_at", "delete": {"endpoints": [], "allow_bulk_delete": True}}},
    ])

    assert resp.write_id == "w-1"
    content = route.calls.last.request.content
    assert b'"structured_mutations":[' in content
    assert b'"object_mutation":{"object_type":"person","create":{"key":{"email":"a@x.io"},"values":{"name":"Alice"}}}' in content
    assert b'"relation_mutation":{"relation_type":"works_at"' in content
    assert b'"allow_bulk_delete":true' in content
    # Unset op branches are dropped from the serialized mutations.
    assert b'"update"' not in content


def test_instance_write_structured_async(httpx_mock, client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/write_async").mock(
        return_value=httpx.Response(200, json=_api_ok([{"write_id": "w-async-2"}])),
    )

    resp = client.instance(INSTANCE_ID).write_async(structured_mutations=[
        ObjectMutation(object_type="person", delete=ObjectDelete(key={"email": "a@x.io"})),
    ])

    assert resp.write_id == "w-async-2"
    content = route.calls.last.request.content
    assert b'"object_mutation":{"object_type":"person","delete":{"key":{"email":"a@x.io"}}}' in content


def test_write_rejects_bad_text_mutation_combinations(client):
    inst = client.instance(INSTANCE_ID)
    mutation = ObjectMutation(object_type="person", delete=ObjectDelete(key={"email": "a@x.io"}))

    with pytest.raises(ValueError, match="exactly one of 'text' or 'structured_mutations'"):
        inst.write("some text", structured_mutations=[mutation])
    with pytest.raises(ValueError, match="exactly one of 'text' or 'structured_mutations'"):
        inst.write()
    with pytest.raises(ValueError, match="at least one mutation"):
        inst.write(structured_mutations=[])
    with pytest.raises(ValueError, match="at least one mutation"):
        inst.write_async(structured_mutations=[])


def test_mutation_models_require_exactly_one_op():
    with pytest.raises(ValueError, match="exactly one of 'create', 'update', 'delete'"):
        ObjectMutation(object_type="person")
    with pytest.raises(ValueError, match="exactly one of 'create', 'update', 'delete'"):
        ObjectMutation(object_type="person", create=ObjectCreate(), delete=ObjectDelete(key={"x": 1}))
    with pytest.raises(ValueError, match="exactly one of 'create', 'update', 'delete'"):
        RelationMutation(relation_type="works_at")


def test_mutation_serialization_preserves_none_field_clears():
    mutation = ObjectMutation(
        object_type="person",
        update=ObjectUpdate(key={"xuid": "x-1"}, values={"role": None}),
    )

    dumped = mutation.model_dump()

    assert dumped == {
        "object_mutation": {"object_type": "person", "update": {"key": {"xuid": "x-1"}, "values": {"role": None}}},
    }


def test_relation_mutation_serialization():
    mutation = RelationMutation(
        relation_type="works_at",
        delete=RelationDelete(
            endpoints=[RelationEndpoint(object_name="person", key={"email": "a@x.io"})],
            allow_bulk_delete=True,
        ),
    )

    dumped = mutation.model_dump()

    assert dumped == {
        "relation_mutation": {
            "relation_type": "works_at",
            "delete": {
                "key": {},
                "endpoints": [{"object_name": "person", "key": {"email": "a@x.io"}}],
                "allow_bulk_delete": True,
            },
        },
    }


def test_instance_write_status(httpx_mock, client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/write_status").mock(
        return_value=httpx.Response(200, json=_api_ok([
            {"write_id": "w-1", "write_status": "completed", "error_detail": None, "completed_at": None},
        ])),
    )

    resp = client.instance(INSTANCE_ID).write_status("w-1")

    assert resp.write_status.value == "completed"
    assert route.called
    assert b'"write_id":"w-1"' in route.calls.last.request.content


def test_instance_extract(httpx_mock, client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/extract").mock(return_value=httpx.Response(200, json=_api_ok([
        {"trace_id": "ew-1", "objects_extracted": {"objects": []}},
    ])))

    resp = client.instance(INSTANCE_ID).extract("Bob is an engineer.")

    assert resp.trace_id == "ew-1"
    assert route.called


# ---------------------------------------------------------------------------
# Console links
#
# The server sends ``console_url`` on every data operation and this client dropped
# it, so citing a recalled record with a link meant rebuilding the URL from a trace
# id and a hostname the caller had to know.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,call,payload",
    [
        (
            "read",
            lambda inst: inst.read("Who is Bob?"),
            {"trace_id": "r-1", "console_url": "https://console.xmemory.ai/read/r-1"},
        ),
        (
            "write",
            lambda inst: inst.write("Bob is an engineer."),
            {"write_id": "w-1", "console_url": "https://console.xmemory.ai/write/w-1"},
        ),
        (
            "write_async",
            lambda inst: inst.write_async("Bob is an engineer."),
            {"write_id": "w-1", "console_url": "https://console.xmemory.ai/write/w-1"},
        ),
        (
            "write_status",
            lambda inst: inst.write_status("w-1"),
            {"write_id": "w-1", "write_status": "completed", "console_url": "https://console.xmemory.ai/write/w-1"},
        ),
        (
            "extract",
            lambda inst: inst.extract("Bob is an engineer."),
            {"trace_id": "e-1", "console_url": "https://console.xmemory.ai/extract/e-1"},
        ),
    ],
)
def test_every_operation_carries_its_console_link(httpx_mock, client, path, call, payload):
    httpx_mock.post(f"/instances/{INSTANCE_ID}/{path}").mock(
        return_value=httpx.Response(200, json=_api_ok([payload])),
    )

    resp = call(client.instance(INSTANCE_ID))

    assert resp.console_url == payload["console_url"]


def test_a_deployment_without_a_console_reports_no_link(httpx_mock, client):
    # Self-hosting without a console is ordinary, and the server omits the field
    # entirely when none is configured. A caller has to be able to tell "no link
    # exists" from a broken one, so this stays None rather than an empty string.
    httpx_mock.post(f"/instances/{INSTANCE_ID}/write").mock(
        return_value=httpx.Response(200, json=_api_ok([{"write_id": "w-1"}])),
    )

    resp = client.instance(INSTANCE_ID).write("Bob is an engineer.")

    assert resp.console_url is None


# ---------------------------------------------------------------------------
# InstanceAPI — instance management
# ---------------------------------------------------------------------------


def test_admin_get_instance_schema(httpx_mock, client):
    route = httpx_mock.get(f"/instances/{INSTANCE_ID}/schema").mock(
        return_value=httpx.Response(200, json=_api_ok([{"data_schema": {"tables": []}}])),
    )

    schema = client.admin.get_instance_schema(INSTANCE_ID)

    assert schema.data_schema == {"tables": []}
    assert route.called


def test_admin_update_instance_schema(httpx_mock, client):
    route = httpx_mock.put(f"/instances/{INSTANCE_ID}/schema").mock(return_value=httpx.Response(200, json=_api_ok([
        {"id": INSTANCE_ID, "cluster_id": CLUSTER_ID, "name": "inst", "description": None},
    ])))

    result = client.admin.update_instance_schema(INSTANCE_ID, "tables: []", SchemaType.YML)

    assert str(result.id) == INSTANCE_ID
    assert route.called


def test_admin_update_instance_metadata(httpx_mock, client):
    route = httpx_mock.put(f"/instances/{INSTANCE_ID}").mock(return_value=httpx.Response(200, json=_api_ok([
        {"id": INSTANCE_ID, "cluster_id": CLUSTER_ID, "name": "new-name", "description": "new-desc"},
    ])))

    result = client.admin.update_instance_metadata(INSTANCE_ID, "new-name", "new-desc")

    assert result.name == "new-name"
    assert route.called
    assert b'"name":"new-name"' in route.calls.last.request.content


# ---------------------------------------------------------------------------
# Agent-facing instance metadata
# ---------------------------------------------------------------------------


def _instance_item(**extra) -> dict:
    return {"id": INSTANCE_ID, "cluster_id": CLUSTER_ID, "name": "n", "description": None, **extra}


def test_renaming_an_instance_does_not_touch_the_owner_instructions(httpx_mock, client):
    """The wipe this whole design exists to prevent.

    The endpoint clears any field it is sent, so a rename that also serialized
    ``agent_owner_instructions`` would erase an owner's standing rule as a side
    effect of changing the name.
    """
    route = httpx_mock.put(f"/instances/{INSTANCE_ID}").mock(
        return_value=httpx.Response(200, json=_api_ok([_instance_item(name="new-name")])),
    )

    client.admin.update_instance_metadata(INSTANCE_ID, "new-name", "new-desc")

    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "new-name", "description": "new-desc"}


def test_owner_instructions_are_cleared_only_when_passed_explicitly(httpx_mock, client):
    route = httpx_mock.put(f"/instances/{INSTANCE_ID}").mock(
        return_value=httpx.Response(200, json=_api_ok([_instance_item()])),
    )

    client.admin.update_instance_metadata(INSTANCE_ID, "n", None, agent_owner_instructions=None)

    body = json.loads(route.calls.last.request.content)
    assert body["agent_owner_instructions"] is None


def test_update_metadata_sends_the_epoch_guard_when_given_one(httpx_mock, client):
    route = httpx_mock.put(f"/instances/{INSTANCE_ID}").mock(
        return_value=httpx.Response(200, json=_api_ok([_instance_item()])),
    )

    client.admin.update_instance_metadata(
        INSTANCE_ID, "n", None,
        agent_owner_instructions="Prefer updating an existing record.",
        expected_owner_instructions_epoch=7,
    )

    body = json.loads(route.calls.last.request.content)
    assert body["agent_owner_instructions"] == "Prefer updating an existing record."
    assert body["expected_owner_instructions_epoch"] == 7


def test_patch_sends_only_the_named_fields(httpx_mock, client):
    route = httpx_mock.patch(f"/instances/{INSTANCE_ID}").mock(
        return_value=httpx.Response(200, json=_api_ok([_instance_item(name="renamed")])),
    )

    result = client.admin.patch_instance_metadata(INSTANCE_ID, name="renamed")

    assert result.name == "renamed"
    assert json.loads(route.calls.last.request.content) == {"name": "renamed"}


def test_patch_serializes_the_agent_hints_as_wire_strings(httpx_mock, client):
    route = httpx_mock.patch(f"/instances/{INSTANCE_ID}").mock(
        return_value=httpx.Response(200, json=_api_ok([_instance_item()])),
    )

    client.admin.patch_instance_metadata(
        INSTANCE_ID,
        agent_surfaces=[AgentSurface.CLAUDE_CODE, AgentSurface.CODEX],
        agent_default_binding_tier=BindingTier.AUTOLOAD,
        agent_engagement_hints=["a convention is learned or corrected"],
    )

    assert json.loads(route.calls.last.request.content) == {
        "agent_surfaces": ["claude_code", "codex"],
        "agent_default_binding_tier": "autoload",
        "agent_engagement_hints": ["a convention is learned or corrected"],
    }


def test_patch_accepts_plain_strings_for_the_hints(httpx_mock, client):
    """A server newer than this release can be driven without waiting for an enum."""
    route = httpx_mock.patch(f"/instances/{INSTANCE_ID}").mock(
        return_value=httpx.Response(200, json=_api_ok([_instance_item()])),
    )

    client.admin.patch_instance_metadata(INSTANCE_ID, agent_surfaces=["some_future_surface"])

    assert json.loads(route.calls.last.request.content) == {"agent_surfaces": ["some_future_surface"]}


def test_patch_clears_fields_with_an_explicit_none(httpx_mock, client):
    """Omit-vs-clear is the whole contract: ``None`` must reach the wire as null."""
    route = httpx_mock.patch(f"/instances/{INSTANCE_ID}").mock(
        return_value=httpx.Response(200, json=_api_ok([_instance_item()])),
    )

    client.admin.patch_instance_metadata(INSTANCE_ID, agent_owner_instructions=None, agent_surfaces=None)

    assert json.loads(route.calls.last.request.content) == {
        "agent_owner_instructions": None,
        "agent_surfaces": None,
    }


def test_patch_refuses_a_bare_string_for_a_hint_list(client):
    """``str`` satisfies ``Sequence[str]``, so nothing in the signature stops one.

    Iterated, it would send each character as its own hint — and the server
    accepts single-character hints, so the mistake would be stored, not rejected.
    """
    with pytest.raises(TypeError, match="bare string"):
        client.admin.patch_instance_metadata(INSTANCE_ID, agent_engagement_hints="a convention changed")


def test_as_str_list_copies_so_a_later_mutation_cannot_change_the_request():
    hints = ["first"]

    copied = _as_str_list(hints)
    hints.append("second")

    assert copied == ["first"]


def test_instance_info_reads_the_agent_metadata(httpx_mock, client):
    httpx_mock.get(f"/instances/{INSTANCE_ID}").mock(return_value=httpx.Response(200, json=_api_ok([
        _instance_item(
            agent_surfaces=["claude_code"],
            agent_default_binding_tier="autoload",
            agent_engagement_hints=["a convention is learned"],
            agent_owner_instructions="Prefer updating an existing record.",
            agent_owner_instructions_epoch=4,
        ),
    ])))

    info = client.admin.get_instance(INSTANCE_ID)

    assert info.agent_surfaces == ["claude_code"]
    assert info.agent_default_binding_tier == "autoload"
    assert info.agent_engagement_hints == ["a convention is learned"]
    assert info.agent_owner_instructions == "Prefer updating an existing record."
    assert info.agent_owner_instructions_epoch == 4


def test_instance_info_tolerates_a_surface_this_release_never_heard_of(httpx_mock, client):
    """A strict enum here would fail every read of an instance the server moved on from."""
    httpx_mock.get(f"/instances/{INSTANCE_ID}").mock(return_value=httpx.Response(200, json=_api_ok([
        _instance_item(agent_surfaces=["some_future_surface"], agent_default_binding_tier="some_future_tier"),
    ])))

    info = client.admin.get_instance(INSTANCE_ID)

    assert info.agent_surfaces == ["some_future_surface"]
    assert info.agent_default_binding_tier == "some_future_tier"


def test_instance_info_defaults_when_the_server_sends_no_agent_metadata(httpx_mock, client):
    httpx_mock.get(f"/instances/{INSTANCE_ID}").mock(
        return_value=httpx.Response(200, json=_api_ok([_instance_item()])),
    )

    info = client.admin.get_instance(INSTANCE_ID)

    assert info.agent_surfaces is None
    assert info.agent_owner_instructions is None
    assert info.agent_owner_instructions_epoch == 0


async def test_async_patch_matches_the_sync_body(httpx_mock, async_client):
    route = httpx_mock.patch(f"/instances/{INSTANCE_ID}").mock(
        return_value=httpx.Response(200, json=_api_ok([_instance_item()])),
    )

    await async_client.admin.patch_instance_metadata(
        INSTANCE_ID, agent_owner_instructions="Prefer updating an existing record.",
    )

    assert json.loads(route.calls.last.request.content) == {
        "agent_owner_instructions": "Prefer updating an existing record.",
    }


async def test_async_rename_does_not_touch_the_owner_instructions(httpx_mock, async_client):
    route = httpx_mock.put(f"/instances/{INSTANCE_ID}").mock(
        return_value=httpx.Response(200, json=_api_ok([_instance_item()])),
    )

    await async_client.admin.update_instance_metadata(INSTANCE_ID, "new-name", "new-desc")

    assert json.loads(route.calls.last.request.content) == {"name": "new-name", "description": "new-desc"}


async def test_async_update_metadata_sends_the_instructions_and_the_epoch_guard(httpx_mock, async_client):
    """The async PUT body is built by its own copy of the code the sync path uses.

    The rename test above pins the omission half, but it passes neither argument, so
    dropping either keyword from the async body construction leaves it green. This
    covers the other half: named arguments actually reach the wire.
    """
    route = httpx_mock.put(f"/instances/{INSTANCE_ID}").mock(
        return_value=httpx.Response(200, json=_api_ok([_instance_item()])),
    )

    await async_client.admin.update_instance_metadata(
        INSTANCE_ID, "n", None,
        agent_owner_instructions="Prefer updating an existing record.",
        expected_owner_instructions_epoch=7,
    )

    assert json.loads(route.calls.last.request.content) == {
        "name": "n",
        "description": None,
        "agent_owner_instructions": "Prefer updating an existing record.",
        "expected_owner_instructions_epoch": 7,
    }


def test_admin_delete_instance(httpx_mock, client):
    route = httpx_mock.delete(f"/instances/{INSTANCE_ID}").mock(
        return_value=httpx.Response(200, json={"ids": [INSTANCE_ID], "items": [], "errors": []}),
    )

    deleted = client.admin.delete_instance(INSTANCE_ID)

    assert len(deleted) == 1
    assert route.called


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_api_error_from_errors_field_2xx(httpx_mock, client):
    """Errors in the wrapper body on a 200 response."""
    httpx_mock.get(f"/clusters/{CLUSTER_ID}").mock(return_value=httpx.Response(200, json={
        "ids": [], "items": [],
        "errors": [{"code": "NOT_FOUND", "message": "Resource not found"}],
    }))

    with pytest.raises(XmemoryAPIError, match="Resource not found"):
        client.admin.get_cluster(CLUSTER_ID)


def test_api_error_from_errors_field_2xx_surfaces_details_and_retry_after(httpx_mock, client):
    """A 200 wrapper-body error still surfaces structured ``details`` and the
    HTTP ``Retry-After`` header on the raised error (the ``_parse`` path, not the
    non-2xx ``raise_for_status`` path)."""
    httpx_mock.get(f"/clusters/{CLUSTER_ID}").mock(return_value=httpx.Response(
        200,
        json={
            "ids": [], "items": [],
            "errors": [{
                "code": "QUOTA_EXCEEDED",
                "message": "Daily token quota exhausted.",
                "details": {"kind": "daily_quota_exceeded", "retry_after_seconds": 3600},
            }],
        },
        headers={"Retry-After": "3600"},
    ))

    with pytest.raises(XmemoryAPIError) as exc:
        client.admin.get_cluster(CLUSTER_ID)

    assert exc.value.code == "QUOTA_EXCEEDED"
    assert exc.value.details == {"kind": "daily_quota_exceeded", "retry_after_seconds": 3600}
    assert exc.value.retry_after == 3600


def test_api_error_from_errors_field_non_2xx(httpx_mock, client):
    """Structured errors in a non-2xx response body are preferred over raw HTTP text."""
    httpx_mock.get(f"/clusters/{CLUSTER_ID}").mock(return_value=httpx.Response(404, json={
        "ids": [], "items": [],
        "errors": [{"code": "NOT_FOUND", "message": "Resource not found"}],
    }))

    with pytest.raises(XmemoryAPIError, match="failed: Resource not found"):
        client.admin.get_cluster(CLUSTER_ID)


def test_api_error_from_http_status(httpx_mock, client):
    """Plain text error without structured body falls back to HTTP status."""
    httpx_mock.get("/clusters").mock(return_value=httpx.Response(500, text="Internal Server Error"))

    with pytest.raises(XmemoryAPIError, match="500"):
        client.admin.list_clusters()


def test_api_error_empty_items(httpx_mock, client):
    """Success response with no items raises an error."""
    httpx_mock.get(f"/instances/{INSTANCE_ID}").mock(return_value=httpx.Response(200, json={
        "ids": [], "items": [], "errors": [],
    }))

    with pytest.raises(XmemoryAPIError, match="returned no items"):
        client.admin.get_instance(INSTANCE_ID)


def test_quota_exceeded_402_surfaces_code_details_and_retry_after(httpx_mock, client):
    """402 QUOTA_EXCEEDED carries kind/retry_after_seconds in ``details`` and the
    HTTP ``Retry-After`` header is surfaced on ``retry_after``. Non-retryable —
    callers branch on ``code``, not the bare 402 status."""
    httpx_mock.get(f"/instances/{INSTANCE_ID}/schema").mock(return_value=httpx.Response(
        402,
        json={"errors": [{
            "code": "QUOTA_EXCEEDED",
            "message": "Daily token quota exhausted.",
            "details": {"kind": "daily_quota_exceeded", "retry_after_seconds": 3600},
        }]},
        headers={"Retry-After": "3600"},
    ))

    with pytest.raises(XmemoryAPIError) as exc:
        client.admin.get_instance_schema(INSTANCE_ID)

    assert exc.value.status == 402
    assert exc.value.code == "QUOTA_EXCEEDED"
    assert exc.value.details == {"kind": "daily_quota_exceeded", "retry_after_seconds": 3600}
    assert exc.value.retry_after == 3600


def test_402_without_details_surfaces_code_only(httpx_mock, client):
    """A 402 that carries no ``details`` and no ``Retry-After`` still surfaces
    its ``code`` — callers branch on ``code``, never on the bare status."""
    httpx_mock.get(f"/clusters/{CLUSTER_ID}").mock(return_value=httpx.Response(
        402,
        json={"errors": [{"code": "QUOTA_EXCEEDED", "message": "Quota exhausted."}]},
    ))

    with pytest.raises(XmemoryAPIError) as exc:
        client.admin.get_cluster(CLUSTER_ID)

    assert exc.value.status == 402
    assert exc.value.code == "QUOTA_EXCEEDED"
    assert exc.value.details is None
    assert exc.value.retry_after is None


def test_rate_limited_429_surfaces_code_and_retry_after(httpx_mock, client):
    """429 RATE_LIMITED is the genuine velocity limit (retryable with backoff);
    its ``Retry-After`` header is surfaced on ``retry_after``."""
    httpx_mock.get("/clusters").mock(return_value=httpx.Response(
        429,
        json={"errors": [{"code": "RATE_LIMITED", "message": "Too many requests."}]},
        headers={"Retry-After": "5"},
    ))

    with pytest.raises(XmemoryAPIError) as exc:
        client.admin.list_clusters()

    assert exc.value.status == 429
    assert exc.value.code == "RATE_LIMITED"
    assert exc.value.retry_after == 5


def test_rate_limited_429_negative_retry_after_clamped_to_zero(httpx_mock, client):
    """A negative ``Retry-After`` (e.g. clock skew) is clamped to 0, not passed
    through — callers can back off by ``retry_after`` without going negative."""
    httpx_mock.get("/clusters").mock(return_value=httpx.Response(
        429,
        json={"errors": [{"code": "RATE_LIMITED", "message": "Too many requests."}]},
        headers={"Retry-After": "-5"},
    ))

    with pytest.raises(XmemoryAPIError) as exc:
        client.admin.list_clusters()

    assert exc.value.status == 429
    assert exc.value.retry_after == 0


def test_rate_limited_429_http_date_retry_after_yields_none(httpx_mock, client):
    """The HTTP-date form of ``Retry-After`` is not parsed to an int; only the
    delta-seconds form populates ``retry_after`` (date form yields ``None``)."""
    httpx_mock.get("/clusters").mock(return_value=httpx.Response(
        429,
        json={"errors": [{"code": "RATE_LIMITED", "message": "Too many requests."}]},
        headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"},
    ))

    with pytest.raises(XmemoryAPIError) as exc:
        client.admin.list_clusters()

    assert exc.value.status == 429
    assert exc.value.retry_after is None


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------


async def test_async_admin_list_clusters(httpx_mock, async_client):
    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([
        {"id": CLUSTER_ID, "org_id": ORG_ID, "name": "async-c", "description": None},
    ])))

    clusters = await async_client.admin.list_clusters()

    assert clusters[0].name == "async-c"
    assert route.called


async def test_async_instance_read(httpx_mock, async_client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/read").mock(return_value=httpx.Response(200, json=_api_ok([
        {"trace_id": "r-1", "reader_result": {"answer": "async answer"}},
    ])))

    resp = await async_client.instance(INSTANCE_ID).read("test query")

    assert resp.reader_result == {"answer": "async answer"}
    assert route.called


async def test_async_create_instance_returns_async_instance_api(httpx_mock, async_client):
    route = httpx_mock.post(f"/clusters/{CLUSTER_ID}/instances").mock(return_value=httpx.Response(201, json=_api_ok([
        {"id": INSTANCE_ID, "cluster_id": CLUSTER_ID, "name": "inst", "description": None},
    ])))

    inst = await async_client.admin.create_instance(CLUSTER_ID, "inst", "tables: []", SchemaType.YML)

    assert inst.id == INSTANCE_ID
    assert route.called


def test_scope_serializes_to_canonical_wire_shape() -> None:
    """ReadScope/ScopeObject must emit the API's identity-ADT + relations_scope shape."""
    from xmemory import ReadScope, ScopeObject
    from xmemory._models import ReadMode, _ReadRequest

    scope = ReadScope(
        objects=[
            ScopeObject(type="Person", key={"name": "Alice"}),
            ScopeObject(type="Pet", key={"name": "Rex"}),
        ],
        relations_scope="all_relations",
    )
    body = _ReadRequest(query="q", mode=ReadMode.SINGLE_ANSWER, scope=scope).model_dump(
        by_alias=True, exclude_none=True
    )
    assert body["scope"] == {
        "objects": [
            {"type": "Person", "key": {"key": {"name": "Alice"}}},
            {"type": "Pet", "key": {"key": {"name": "Rex"}}},
        ],
        "relations_scope": "all_relations",
    }


def test_scope_defaults_to_no_relations() -> None:
    from xmemory import ReadScope, ScopeObject

    assert ReadScope(objects=[ScopeObject(type="Person", key={"name": "Bob"})]).relations_scope == "no_relations"


def test_scope_object_requires_a_non_empty_key() -> None:
    from xmemory import ScopeObject

    with pytest.raises(Exception):
        ScopeObject(type="Person")  # type: ignore[call-arg]  # key is required
    with pytest.raises(Exception):
        ScopeObject(type="Person", key={})


def test_scoped_write_sends_the_write_scope_wire_shape(httpx_mock, client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/write").mock(
        return_value=httpx.Response(200, json=_api_ok([{"write_id": "w-1"}])),
    )

    client.instance(INSTANCE_ID).write(
        "After her promotion she is a surgeon.",
        scope=WriteScope(objects=[ScopeObject(type="Person", key={"name": "Alice Johnson"})]),
    )

    body = json.loads(route.calls.last.request.content)
    assert body["scope"] == {
        "objects": [{"type": "Person", "key": {"key": {"name": "Alice Johnson"}}}],
    }
    # WriteScope has no relations_scope: the relations among the scoped objects
    # always accompany the extraction hint.
    assert "relations_scope" not in body["scope"]


def test_scoped_write_async_sends_the_write_scope_wire_shape(httpx_mock, client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/write_async").mock(
        return_value=httpx.Response(200, json=_api_ok([{"write_id": "w-async-1"}])),
    )

    client.instance(INSTANCE_ID).write_async(
        "She moved to the London office.",
        scope=WriteScope(objects=[ScopeObject(type="Person", key={"name": "Alice Johnson"})]),
    )

    body = json.loads(route.calls.last.request.content)
    assert body["scope"] == {
        "objects": [{"type": "Person", "key": {"key": {"name": "Alice Johnson"}}}],
    }


def test_unscoped_write_omits_the_scope_key(httpx_mock, client):
    """Unscoped writes must stay byte-identical: older servers reject unknown keys."""
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/write").mock(
        return_value=httpx.Response(200, json=_api_ok([{"write_id": "w-1"}])),
    )

    client.instance(INSTANCE_ID).write("Bob is an engineer.")

    assert b"scope" not in route.calls.last.request.content


def test_scope_and_structured_mutations_are_mutually_exclusive(client):
    with pytest.raises(ValueError, match="mutually exclusive"):
        client.instance(INSTANCE_ID).write(
            structured_mutations=[
                ObjectMutation(
                    object_type="person",
                    create=ObjectCreate(key={"email": "a@x.io"}, values={"name": "Alice"}),
                ),
            ],
            scope=WriteScope(objects=[ScopeObject(type="Person", key={"name": "Alice"})]),
        )


# ---------------------------------------------------------------------------
# Client-identity header
# ---------------------------------------------------------------------------

# The server reads the client name from the first whitespace-delimited piece of this header, taking
# the part before "/" and matching it against a fixed list of known clients; it reads the version as
# exactly three numeric components. A header that drifts from this shape is not rejected — it is
# counted against an unknown-client bucket instead, so nothing here or on the server would fail.
_CLIENT_IDENTITY_RE = re.compile(
    r"xmemory-python/[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3} \(python [A-Za-z0-9._-]+; [A-Za-z0-9._-]+\)\Z"
)


def test_client_identity_has_the_shape_the_server_reads() -> None:
    assert _CLIENT_IDENTITY_RE.match(client_identity())


def test_version_is_three_numeric_components() -> None:
    """Guards the version shape the header has to carry.

    A two-component version is a perfectly ordinary thing to publish and every other test here would
    still pass with it — but the server reads `major.minor.patch` from the start of the token, so it
    records the version as `unparsed` instead. The name still resolves; the release simply stops being
    distinguishable from any other release of this client, permanently, in every event it sent.

    A prerelease or post suffix is fine and is not what this guards: the server matches the leading
    three components and ignores the rest, so `0.17.0rc1` records as `0.17.0`.
    """
    assert re.fullmatch(r"\d{1,3}\.\d{1,3}\.\d{1,3}", __version__)


def test_sync_admin_call_sends_the_client_header(httpx_mock, client):
    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))

    client.admin.list_clusters()

    assert route.called
    assert route.calls.last.request.headers[CLIENT_HEADER] == client_identity()


def test_check_health_sends_the_client_header(httpx_mock, client):
    route = httpx_mock.get("/healthz").mock(return_value=httpx.Response(200))

    client.check_health()

    assert route.called
    assert route.calls.last.request.headers[CLIENT_HEADER] == client_identity()


async def test_async_admin_call_sends_the_client_header(httpx_mock, async_client):
    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))

    await async_client.admin.list_clusters()

    assert route.called
    assert route.calls.last.request.headers["authorization"] == "Bearer test-api-key"
    assert route.calls.last.request.headers[CLIENT_HEADER] == client_identity()


async def test_async_check_health_sends_the_client_header(httpx_mock, async_client):
    route = httpx_mock.get("/healthz").mock(return_value=httpx.Response(200))

    await async_client.check_health()

    assert route.called
    assert route.calls.last.request.headers[CLIENT_HEADER] == client_identity()


# ---------------------------------------------------------------------------
# A caller-supplied HTTP client is left alone
# ---------------------------------------------------------------------------


def test_caller_supplied_client_keeps_its_own_headers(httpx_mock, base_url):
    """A client the caller built is the caller's to configure, and may well be shared with traffic
    that has nothing to do with this library — so its headers are read, never written."""
    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))

    with httpx.Client(base_url=base_url, headers={"User-Agent": "caller/1.0"}) as http:
        before = dict(http.headers)
        with XmemoryClient(http_client=http, api_key="test-api-key") as c:
            c.admin.list_clusters()
        assert dict(http.headers) == before

    assert route.calls.last.request.headers["user-agent"] == "caller/1.0"


async def test_caller_supplied_async_client_keeps_its_own_headers(httpx_mock, base_url):
    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))

    async with httpx.AsyncClient(base_url=base_url, headers={"User-Agent": "caller/1.0"}) as http:
        before = dict(http.headers)
        async with AsyncXmemoryClient(http_client=http, api_key="test-api-key") as c:
            await c.admin.list_clusters()
        assert dict(http.headers) == before

    assert route.calls.last.request.headers["user-agent"] == "caller/1.0"


def test_caller_supplied_client_is_attributed_without_being_written_to(httpx_mock, base_url):
    """A passed-in client is attributed like any other, and is not modified to do it.

    The header is added per request rather than installed on the client, so a client shared with
    traffic that has nothing to do with this library carries nothing of ours between calls.
    """
    clusters = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))
    healthz = httpx_mock.get("/healthz").mock(return_value=httpx.Response(200))

    with httpx.Client(base_url=base_url) as http:
        before = dict(http.headers)
        with XmemoryClient(http_client=http, api_key="test-api-key") as c:
            c.admin.list_clusters()
            c.check_health()
        assert dict(http.headers) == before, "the caller's client was written to"

    assert clusters.calls.last.request.headers[CLIENT_HEADER] == client_identity()
    assert clusters.calls.last.request.headers["authorization"] == "Bearer test-api-key"
    # check_health bypasses the transport, so it is the path that drifts if the header is added in
    # only one place.
    assert healthz.calls.last.request.headers[CLIENT_HEADER] == client_identity()
    assert healthz.calls.last.request.headers.get("authorization") is None


async def test_caller_supplied_async_client_is_attributed_without_being_written_to(httpx_mock, base_url):
    clusters = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))
    healthz = httpx_mock.get("/healthz").mock(return_value=httpx.Response(200))

    async with httpx.AsyncClient(base_url=base_url) as http:
        before = dict(http.headers)
        async with AsyncXmemoryClient(http_client=http, api_key="test-api-key") as c:
            await c.admin.list_clusters()
            await c.check_health()
        assert dict(http.headers) == before, "the caller's client was written to"

    assert clusters.calls.last.request.headers[CLIENT_HEADER] == client_identity()
    assert clusters.calls.last.request.headers["authorization"] == "Bearer test-api-key"
    assert healthz.calls.last.request.headers[CLIENT_HEADER] == client_identity()
    assert healthz.calls.last.request.headers.get("authorization") is None


def test_client_identity_survives_a_platform_that_raises(monkeypatch):
    """Reading the platform note must never be the reason a client fails to construct.

    The fallback is the only thing standing between a hostile or broken `platform` module and a
    traceback out of the constructor, and nothing else in this file exercises it.
    """

    def _boom() -> str:
        raise RuntimeError("platform is unavailable")

    monkeypatch.setattr(_version.platform, "system", _boom)
    assert client_identity() == f"xmemory-python/{__version__} (unknown)"


def test_check_health_sends_no_api_key(httpx_mock, client):
    """`/healthz` takes no credential, so the key must not travel there.

    The health check builds its headers from the module-level `attribution_headers()` alone.
    `_headers()` on the transport also carries `Authorization`, so reaching for that one instead --
    one word of difference at the call site -- sends the key to an unauthenticated endpoint, and
    every other test in this file stays green while it does.
    """
    healthz = httpx_mock.get("/healthz").mock(return_value=httpx.Response(200))

    client.check_health()

    assert healthz.calls.last.request.headers.get("authorization") is None


async def test_async_check_health_sends_no_api_key(httpx_mock, async_client):
    """Same for the async path, which duplicates the sync one and can drift from it."""
    healthz = httpx_mock.get("/healthz").mock(return_value=httpx.Response(200))

    await async_client.check_health()

    assert healthz.calls.last.request.headers.get("authorization") is None


@pytest.mark.parametrize(
    "caller_headers,expected_user_agent",
    [
        ({"User-Agent": "caller/1.0"}, "caller/1.0"),
        ({"User-Agent": ""}, ""),
        ({"User-Agent": "xmemory-python/9.9.9 (someone-else)"}, "xmemory-python/9.9.9 (someone-else)"),
        ({}, f"python-httpx/{httpx.__version__}"),
    ],
    ids=["own-ua", "empty-ua", "looks-like-ours", "httpx-default"],
)
def test_a_caller_user_agent_is_never_read_or_written(httpx_mock, base_url, caller_headers, expected_user_agent):
    """Whatever the caller's ``User-Agent`` says, it goes out unchanged and the identity header is added.

    This is the property the dedicated header exists to make true. The four cases are the ones a
    ``User-Agent``-based scheme has to tell apart and cannot: a header the caller chose, an empty one,
    one that merely looks like this library's, and httpx's own default standing in for "chose nothing".
    Here they are one case, because nothing reads the field to decide.
    """
    clusters = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))
    healthz = httpx_mock.get("/healthz").mock(return_value=httpx.Response(200))

    with httpx.Client(base_url=base_url, headers=caller_headers) as http:
        with XmemoryClient(http_client=http, api_key="test-api-key") as c:
            c.admin.list_clusters()
            c.check_health()

    assert clusters.calls.last.request.headers["user-agent"] == expected_user_agent
    assert clusters.calls.last.request.headers[CLIENT_HEADER] == client_identity()
    # check_health assembles its headers separately, so it is the path that drifts if the identity
    # header is added in only one place.
    assert healthz.calls.last.request.headers["user-agent"] == expected_user_agent
    assert healthz.calls.last.request.headers[CLIENT_HEADER] == client_identity()


def test_a_deleted_user_agent_does_not_take_attribution_with_it(httpx_mock, base_url):
    """httpx does not restore its default once a header is deleted, so the request goes out with no
    ``User-Agent`` at all -- and the identity header is still there, because it never depended on it.
    """
    clusters = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))

    with httpx.Client(base_url=base_url) as http:
        with XmemoryClient(http_client=http, api_key="test-api-key") as c:
            del http.headers["User-Agent"]
            c.admin.list_clusters()

    assert clusters.calls.last.request.headers.get("user-agent") is None
    assert clusters.calls.last.request.headers[CLIENT_HEADER] == client_identity()


async def test_an_async_caller_user_agent_is_never_read_or_written(httpx_mock, base_url):
    """A `User-Agent` set after construction survives on both the ordinary path and the health check.

    `AsyncTransport._headers()` and the async `check_health()` are separate code from their sync
    counterparts, so covering the sync side says nothing about this one.
    """
    clusters = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))
    healthz = httpx_mock.get("/healthz").mock(return_value=httpx.Response(200))

    async with httpx.AsyncClient(base_url=base_url) as http:
        async with AsyncXmemoryClient(http_client=http, api_key="test-api-key") as c:
            http.headers["User-Agent"] = "caller/2.0"
            await c.admin.list_clusters()
            await c.check_health()

    assert clusters.calls.last.request.headers["user-agent"] == "caller/2.0"
    assert clusters.calls.last.request.headers[CLIENT_HEADER] == client_identity()
    assert healthz.calls.last.request.headers["user-agent"] == "caller/2.0"
    assert healthz.calls.last.request.headers[CLIENT_HEADER] == client_identity()


async def test_an_async_deleted_user_agent_does_not_take_attribution_with_it(httpx_mock, base_url):
    """Deleting the header is the one case that empties rather than replaces it.

    The sync side covers this; the async transport resolves its headers separately, so a change that
    reintroduced a `User-Agent` read would show up on one path and not the other.
    """
    clusters = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))

    async with httpx.AsyncClient(base_url=base_url) as http:
        async with AsyncXmemoryClient(http_client=http, api_key="test-api-key") as c:
            del http.headers["User-Agent"]
            await c.admin.list_clusters()

    assert clusters.calls.last.request.headers.get("user-agent") is None
    assert clusters.calls.last.request.headers[CLIENT_HEADER] == client_identity()


# ---------------------------------------------------------------------------
# The header name is what the API reads, asserted as a literal
# ---------------------------------------------------------------------------


def test_the_client_header_name_is_pinned_to_its_literal() -> None:
    """Asserted as a literal, not through the constant every other test here reads.

    The server names this header in its own source and this package cannot import it, so the two agree
    only by both being right. Every other assertion in this file looks the header up by `CLIENT_HEADER`,
    which means a rename would move the assertions with it and leave the suite green while this SDK's
    calls were filed as generic httpx traffic -- permanently, since an analytics value cannot be
    reclassified once emitted.
    """
    assert CLIENT_HEADER == "X-Xmemory-Client"


# ---------------------------------------------------------------------------
# Version single-source-of-truth
# ---------------------------------------------------------------------------


def test_version_matches_pyproject() -> None:
    """`xmemory.__version__` and `pyproject.toml`'s `[project].version` must never drift apart —
    nothing derives one from the other at build time."""
    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:  # Python 3.10
        import tomli as tomllib  # type: ignore[import-not-found, no-redef]

    import pathlib

    pyproject_path = pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)

    assert data["project"]["version"] == __version__


# ---------------------------------------------------------------------------
# The platform note is sanitized before it reaches the header
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("system_name", "machine_name"),
    [
        pytest.param("Dárwin", "arm64", id="non-ascii-system"),
        pytest.param("Linux", "日本語", id="non-ascii-machine"),
        pytest.param("Lin\nux", "x86_64", id="newline-in-system"),
        pytest.param("Linux", "x86\r64", id="carriage-return-in-machine"),
        pytest.param("日本語", "日本語", id="nothing-usable-survives"),
    ],
)
def test_hostile_platform_values_still_yield_a_sendable_header(
    httpx_mock, monkeypatch, base_url, system_name, machine_name
) -> None:
    """Neither reported value is guaranteed to be clean — on Windows the machine string is read
    out of an environment variable. Neither kind of dirty byte can travel in a header, and they
    fail at different moments: a control character is accepted into the header object and then
    rejected at send, so every request fails, while a non-ASCII byte raises inside ``httpx.Headers``
    and the header never assembles. Sanitizing is what keeps both off the header.

    Asserted on a request that is actually issued, not on the header object: the control-character
    case is accepted into the object and only rejected at send, so a check that stops at the object
    would pass on exactly the input it exists to catch.
    """
    import platform

    monkeypatch.setattr(platform, "system", lambda: system_name)
    monkeypatch.setattr(platform, "machine", lambda: machine_name)

    assert _CLIENT_IDENTITY_RE.match(client_identity())

    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))
    with XmemoryClient(url=base_url, api_key="test-api-key") as c:
        c.admin.list_clusters()

    assert route.calls.last.request.headers[CLIENT_HEADER] == client_identity()


async def test_hostile_platform_values_still_yield_a_sendable_async_header(httpx_mock, monkeypatch, base_url) -> None:
    import platform

    monkeypatch.setattr(platform, "system", lambda: "Lin\nux")
    monkeypatch.setattr(platform, "machine", lambda: "日本語")

    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))
    async with AsyncXmemoryClient(url=base_url, api_key="test-api-key") as c:
        await c.admin.list_clusters()

    assert _CLIENT_IDENTITY_RE.match(route.calls.last.request.headers[CLIENT_HEADER])
    assert route.calls.last.request.headers[CLIENT_HEADER] == client_identity()


def test_platform_note_never_carries_the_hostname(monkeypatch) -> None:
    """The note says which OS and architecture, and nothing that identifies the machine.

    The hostname is patched to something the note could not otherwise contain, so this holds on any
    machine — a real hostname can be a substring of the OS or architecture, or be long enough to be
    truncated away, either of which would make the check lie.
    """
    import platform

    monkeypatch.setattr(platform, "node", lambda: "hostname-that-must-not-appear")
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(platform, "python_version", lambda: "3.12.4")

    assert "hostname-that-must-not-appear" not in client_identity()
    assert client_identity() == f"xmemory-python/{__version__} (python 3.12.4; Linux-x86_64)"


def test_platform_note_is_bounded(monkeypatch) -> None:
    """On Windows the architecture is read out of an environment variable, so its length is the
    caller's to choose, not the operating system's."""
    import platform

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "x" * 5000)

    assert len(client_identity()) < 200
    assert _CLIENT_IDENTITY_RE.match(client_identity())


@pytest.mark.parametrize("sep", ["-", ".", "_"], ids=["hyphen", "dot", "underscore"])
def test_platform_note_never_starts_or_ends_with_a_separator(monkeypatch, sep: str) -> None:
    """Trimming has to happen after the length is capped: a value cut at the wrong place would
    otherwise leave a dangling separator that trimming had already removed.

    Every separator the allowlist admits, not only the one the note joins on -- a 64-character cut
    lands wherever the host's string puts it, and `3.12.` or `x86_` reach the header just as easily
    as a trailing hyphen does.
    """
    import platform

    monkeypatch.setattr(platform, "system", lambda: "A" * 63 + sep + "B")
    monkeypatch.setattr(platform, "machine", lambda: "x")

    note = client_identity().split("(", 1)[1].rstrip(")")
    for candidate in note.split("; "):
        assert not candidate.startswith(sep), f"{candidate!r} starts with {sep!r}"
        assert not candidate.endswith(sep), f"{candidate!r} ends with {sep!r}"


def test_platform_note_reports_the_running_interpreter_version(monkeypatch) -> None:
    """The version is read from the interpreter rather than restated, so it cannot go stale.

    This is the field the note exists for: the OS and architecture say nothing anyone acts on, while
    the interpreter version is what decides whether a Python release still has users.
    """
    import platform

    monkeypatch.setattr(platform, "python_version", lambda: "3.9.18")

    assert "(python 3.9.18; " in client_identity()


def test_a_hostile_interpreter_version_cannot_break_the_note(monkeypatch) -> None:
    """`python_version()` is read out of the build, so a patched or vendored interpreter can report
    anything. A field that kept a semicolon or a parenthesis would forge this note's own separators."""
    import platform

    for reported in ("3.12.4; evil) (", "\n3.12", "日本語", "", "9" * 300):
        monkeypatch.setattr(platform, "python_version", lambda v=reported: v)
        note = client_identity().split("(", 1)[1].rstrip(")")
        assert _CLIENT_IDENTITY_RE.match(client_identity()), f"{reported!r} broke the shape"
        assert note.count(";") == 1, f"{reported!r} forged a separator"


def test_star_import_does_not_bind_version(monkeypatch) -> None:
    """`__version__` is reachable as `xmemory.__version__`, but a star-import must not overwrite a
    consumer's own."""
    namespace: dict[str, object] = {"__version__": "consumer-owned"}

    exec("from xmemory import *", namespace)  # noqa: S102

    assert namespace["__version__"] == "consumer-owned"
