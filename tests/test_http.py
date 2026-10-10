import anyio
import pytest
from starlette.testclient import TestClient

from stopover.server import create_app


def test_local_dashboard_and_api_need_no_token(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/healthz").json()["ready"]
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="login-form"' not in page.text
        assert "set-cookie" not in page.headers
        assert client.get("/api/handoffs").json()["data"]["items"] == []
        assert client.get("/api/overview").status_code == 200
        assert client.post("/api/login", json={"token": "old"}).status_code == 404
        assert client.post("/api/logout").status_code == 404
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert client.post("/mcp", content=b"x" * 65537).status_code == 413
        # A stale credential left in an older client config is no longer required or used.
        assert client.get("/api/overview", headers={"authorization": "Bearer obsolete"}).status_code == 200
    assert not (tmp_path / "token").exists()


@pytest.mark.parametrize("base_url,origin", [
    ("https://handoff.example-tailnet.ts.net", "https://handoff.example-tailnet.ts.net"),
    ("https://handoff.example-tailnet.ts.net:8445", "https://handoff.example-tailnet.ts.net:8445"),
    ("http://localhost:8765", "http://localhost:8765"),
    ("http://handoff.example-tailnet.ts.net", "https://handoff.example-tailnet.ts.net"),  # TLS ends at the proxy
])
def test_remote_dashboard_and_api_accept_their_own_origin(tmp_path, base_url, origin):
    with TestClient(create_app(tmp_path), base_url=base_url, headers={"origin": origin}) as client:
        assert client.get("/").status_code == 200
        assert client.get("/healthz").json()["ready"]
        assert client.get("/api/handoffs").json()["data"]["items"] == []
        assert client.get("/api/overview").status_code == 200
        assert client.post("/mcp", content=b"x" * 65537).status_code == 413


@pytest.mark.parametrize("origin", ["https://attacker.example", "null", "http://localhost:9999", "https://evil.ts.net",
                                    "https://localhost:8765/path", "localhost:8765", "javascript:alert(1)"])
def test_foreign_or_invalid_origins_cannot_use_mcp_or_the_api(tmp_path, record, origin):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://localhost:8765", headers={"origin": origin}) as client:
        saved = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                          "params": {"name": "stopover_save", "arguments": {"record": record}}},
                            headers={"accept": "application/json, text/event-stream"})
        assert saved.status_code == 403 and saved.json() == {"error": "Origin not allowed"}
        assert client.get("/api/handoffs").status_code == 403
        assert app.state.service.execute("stopover_list", {"status": "all"})["data"]["items"] == []  # nothing was saved


def test_native_clients_without_origin_are_unaffected(tmp_path, record):
    with TestClient(create_app(tmp_path), base_url="http://localhost:8765") as client:
        saved = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                          "params": {"name": "stopover_save", "arguments": {"record": record}}},
                            headers={"accept": "application/json, text/event-stream"})
        assert saved.status_code == 200 and saved.json()["result"]["structuredContent"]["ok"]


@pytest.mark.parametrize("host", ["127.0.0.1:8765/public?x=", "[::1]/public?x=", "localhost:", "localhost:99999",
                                  "user@localhost", "local host", "[::1", "localhost:80:80", "a..ts.net", ""])
@pytest.mark.parametrize("allowed", [None, ["*"]])
def test_malformed_host_headers_are_refused_even_with_a_wildcard(tmp_path, host, allowed):
    with TestClient(create_app(tmp_path, allowed_hosts=allowed), base_url="http://localhost:8765") as client:
        assert client.get("/api/handoffs", headers={"host": host}).status_code == 403


def test_cross_site_navigations_are_allowed_but_not_requests(tmp_path):
    navigate = {"sec-fetch-site": "cross-site", "sec-fetch-mode": "navigate", "sec-fetch-dest": "document"}
    with TestClient(create_app(tmp_path), base_url="https://handoff.example-tailnet.ts.net") as client:
        # Following a link from another site (or a sign-in provider redirecting back) works.
        assert client.get("/", headers=navigate).status_code == 200
        assert client.get("/memories", headers=navigate).status_code == 200
        # Everything else from another site is still refused.
        assert client.post("/mcp", json={}, headers=navigate).status_code == 403  # cross-site form POST
        assert client.get("/api/handoffs", headers={**navigate, "sec-fetch-mode": "cors", "sec-fetch-dest": "empty"}).status_code == 403
        assert client.get("/api/handoffs", headers={**navigate, "sec-fetch-dest": "iframe"}).status_code == 403
        assert client.get("/api/handoffs", headers={"sec-fetch-site": "cross-site", "sec-fetch-mode": "no-cors",
                                                    "sec-fetch-dest": "image"}).status_code == 403


def test_cross_site_browser_requests_are_rejected(tmp_path):
    with TestClient(create_app(tmp_path), base_url="https://handoff.example-tailnet.ts.net") as client:
        headers = {"sec-fetch-site": "cross-site"}
        assert client.get("/api/handoffs", headers=headers).status_code == 403
        assert client.post("/mcp", json={}, headers=headers).status_code == 403
        assert client.get("/api/overview", headers={"sec-fetch-site": "same-origin"}).status_code == 200


def test_all_details_and_events_are_read_only(tmp_path, record):
    import uuid
    app = create_app(tmp_path)
    saved = app.state.store.execute("stopover_save", {"operation_id": str(uuid.uuid4()), "record": record})["data"]
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        detail = client.get("/api/handoffs/" + saved["id"]).json()["data"]
        assert detail["record"]["context"]["constraints"] == record["context"]["constraints"]
        assert detail["revision"] == 1
        assert client.get("/api/handoffs/" + saved["id"] + "/events").json()["items"][0]["event"] == "pushed"
        assert client.get("/api/handoffs/" + saved["id"]).json()["data"]["revision"] == 1
        assert client.get("/api/handoffs?limit=oops").status_code == 400
        assert client.get("/api/handoffs/not-an-id").status_code == 400


def test_committed_schemas_match_models():
    import json
    from pathlib import Path
    from stopover.models import INPUTS, Record
    schemas = Path(__file__).resolve().parents[1] / "schemas"
    for name, model in {**INPUTS, "record": Record}.items():
        assert json.loads((schemas / f"{name}.json").read_text()) == model.model_json_schema(), name


@pytest.mark.parametrize("headers", [
    [(b"host", b"localhost:8765"), (b"origin", b"https://[")],
    [(b"host", b"localhost:8765"), (b"origin", b"http://localhost:\xb2")],
    [(b"host", b"localhost:\xb2")],
    [(b"host", b"[::1")],
    [(b"host", b"localhost:8765"), (b"origin", b"\xff\xfe")],
])
def test_malformed_headers_get_a_clean_403_not_a_crash(tmp_path, headers):
    """Raw ASGI requests, because HTTP clients refuse to send some of these headers."""
    app = create_app(tmp_path)
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "GET", "path": "/api/overview", "raw_path": b"/api/overview", "query_string": b"",
             "headers": headers, "scheme": "http", "server": ("127.0.0.1", 8765), "client": ("127.0.0.1", 1),
             "asgi": {"version": "3.0"}, "http_version": "1.1", "root_path": ""}
    anyio.run(app, scope, receive, send)
    assert sent[0]["status"] == 403
