"""The seams a hosted build uses: host allowlist, authentication, workspaces, registry and storage boundary."""
import inspect

import pytest
from pydantic import BaseModel
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import baton.domain
import baton.memory
import baton.service
from baton.context import RequestContext
from baton.registry import Tool
from baton.server import create_app, host_allowed
from baton.service import core_registry
from baton.store import Store

MCP_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


def mcp_call(client, name, arguments, **headers):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    return client.post("/mcp", json=body, headers={**MCP_HEADERS, **headers})


@pytest.mark.parametrize("host,allowed", [
    ("127.0.0.1:8765", True), ("localhost", True), ("[::1]:8765", True), ("desktop.tailnet.ts.net:8445", True),
    ("evil.example.com", False), ("evil.example.com:8765", False), ("ts.net", False), ("100.64.0.10:8765", False),
    ("127.0.0.1.evil.example", False), ("", False),
])
def test_default_host_allowlist(host, allowed):
    assert host_allowed(host, ["localhost", "127.0.0.1", "::1", "*.ts.net"]) is allowed


def test_unknown_hosts_are_rejected_everywhere(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://attacker.example:8765") as client:
        for path in ("/", "/healthz", "/api/handoffs", "/api/memories"):
            response = client.get(path)
            assert response.status_code == 403 and "BATON_ALLOWED_HOSTS" in response.json()["error"]
        assert mcp_call(client, "baton_list", {}).status_code == 403


def test_allowed_hosts_can_be_extended(tmp_path, monkeypatch):
    monkeypatch.setenv("BATON_ALLOWED_HOSTS", "handoff.example.com, 100.64.0.10")
    with TestClient(create_app(tmp_path), base_url="http://100.64.0.10:8765") as client:
        assert client.get("/api/handoffs").status_code == 200
        assert client.get("/api/handoffs", headers={"host": "handoff.example.com"}).status_code == 200
        assert client.get("/api/handoffs", headers={"host": "other.example.com"}).status_code == 403


def test_allowlist_can_be_disabled(tmp_path):
    with TestClient(create_app(tmp_path, allowed_hosts=["*"]), base_url="http://anything.example") as client:
        assert client.get("/healthz").status_code == 200


def test_auth_hook_scopes_requests_and_records_actor(tmp_path, record):
    async def auth(request):
        return RequestContext(actor="alice") if request.headers.get("authorization") == "Bearer secret" else None

    extra = Route("/api/whoami", lambda request: JSONResponse({"actor": request.state.handoff_ctx.actor}))
    with TestClient(create_app(tmp_path, auth=auth, extra_routes=[extra]), base_url="http://127.0.0.1:8765") as client:
        assert client.get("/healthz").status_code == 200 and client.get("/").status_code == 200
        denied = client.get("/api/handoffs")
        assert denied.status_code == 401 and denied.headers["www-authenticate"] == "Bearer"
        assert mcp_call(client, "baton_list", {}).status_code == 401
        assert client.get("/api/whoami").status_code == 401
        token = {"authorization": "Bearer secret"}
        assert client.get("/api/whoami", headers=token).json() == {"actor": "alice"}
        pushed = mcp_call(client, "baton_save", {"record": record}, **token).json()["result"]["structuredContent"]
        assert pushed["ok"], pushed
        events = client.get(f"/api/handoffs/{pushed['data']['id']}/events", headers=token).json()["items"]
        assert events[0]["details"]["actor"] == "alice"


def test_sqlite_backend_serves_only_the_local_workspace(store, push):
    push()
    other = RequestContext(workspace="team-42")
    assert store.execute("baton_list", {"status": "all"}, other)["error"]["code"] == "UNKNOWN_WORKSPACE"
    assert len(store.execute("baton_list", {"status": "all"})["data"]["items"]) == 1


def test_registry_extension_adds_tools_without_touching_core(tmp_path):
    class Ping(BaseModel):
        message: str

    def ping(service, request, ctx, now):
        return {"echo": request["message"], "workspace": ctx.workspace}, False

    registry = core_registry().copy()
    registry.add_tool(Tool("handoff_ping", Ping, "Echo a message.", ping, read_only=True))
    registry.add_instructions("Extension instructions.")
    with pytest.raises(ValueError):
        registry.add_tool(Tool("handoff_ping", Ping, "Duplicate.", ping))
    service = Store(tmp_path, registry=registry)
    assert service.execute("handoff_ping", {"message": "hi"})["data"] == {"echo": "hi", "workspace": "local"}
    assert "handoff_ping" not in core_registry().tools
    with TestClient(create_app(service=service), base_url="http://127.0.0.1:8765") as client:
        result = mcp_call(client, "handoff_ping", {"message": "hi"}).json()["result"]["structuredContent"]
        assert result["data"]["echo"] == "hi"
        listed = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=MCP_HEADERS).json()
        assert "handoff_ping" in {tool["name"] for tool in listed["result"]["tools"]}
        assert len(listed["result"]["tools"]) == 12


@pytest.mark.parametrize("module", [baton.service, baton.memory, baton.domain])
def test_service_layer_never_touches_sqlite(module):
    source = inspect.getsource(module)
    assert "sqlite" not in source.lower() and "db.execute" not in source


def test_login_url_is_returned_for_dashboard_api_but_not_mcp(tmp_path):
    async def deny(request):
        return None

    with TestClient(create_app(tmp_path, auth=deny, login_url="/auth/login"), base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/handoffs").json() == {"error": "Authentication required", "login_url": "/auth/login"}
        assert "login_url" not in mcp_call(client, "baton_list", {}).json()


def test_mcp_challenge_points_clients_at_oauth_metadata(tmp_path):
    async def deny(request):
        return None

    def challenge(request):
        return f'Bearer resource_metadata="https://{request.headers["host"]}/.well-known/oauth-protected-resource/mcp"'

    with TestClient(create_app(tmp_path, auth=deny, mcp_challenge=challenge), base_url="http://127.0.0.1:8765") as client:
        response = mcp_call(client, "baton_list", {})
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == 'Bearer resource_metadata="https://127.0.0.1:8765/.well-known/oauth-protected-resource/mcp"'
        assert client.get("/api/handoffs").headers["www-authenticate"] == "Bearer"  # only /mcp gets the challenge
