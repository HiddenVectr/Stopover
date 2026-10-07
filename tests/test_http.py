import pytest
from starlette.testclient import TestClient

from handoff.server import create_app


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


@pytest.mark.parametrize("headers", [
    {"host": "evil.example:8765"},
    {"host": "localhost.evil.example:8765"},
    {"host": "192.168.1.20:8765"},
    {"host": "localhost:8765?bad=1"},
    {"host": "localhost:8765#bad"},
    {"host": "localhost:99999"},
    {"origin": "null"},
    {"origin": "https://evil.example"},
    {"origin": "http://localhost:8766"},
    {"sec-fetch-site": "cross-site"},
    [("host", "127.0.0.1:8765"), ("host", "evil.example:8765")],
    [("origin", "http://127.0.0.1:8765"), ("origin", "https://evil.example")],
])
def test_tokenless_access_keeps_local_request_boundary(tmp_path, headers):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/handoffs", headers=headers).status_code == 403
        assert client.post("/mcp", json={}, headers=headers).status_code == 403
        assert client.get("/api/overview", headers={"origin": "http://127.0.0.1:8765", "sec-fetch-site": "same-origin"}).status_code == 200


def test_all_details_and_events_are_read_only(tmp_path, record):
    import uuid
    app = create_app(tmp_path)
    saved = app.state.store.execute("handoff_push", {"operation_id": str(uuid.uuid4()), "record": record})["data"]
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        detail = client.get("/api/handoffs/" + saved["id"]).json()["data"]
        assert detail["record"]["context"]["constraints"] == record["context"]["constraints"]
        assert detail["revision"] == 1
        assert client.get("/api/handoffs/" + saved["id"] + "/events").json()["items"][0]["event"] == "pushed"
        assert client.get("/api/handoffs/" + saved["id"]).json()["data"]["revision"] == 1
        assert client.get("/api/handoffs?limit=oops").status_code == 400
        assert client.get("/api/handoffs/not-an-id").status_code == 400
