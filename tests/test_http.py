import pytest
from starlette.testclient import TestClient

from baton.server import create_app


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
    ("https://handoff.example-tailnet.ts.net:8445", "https://other.example.com"),
    ("http://localhost:8765", "null"),
])
def test_remote_dashboard_and_api_accept_host_and_origin(tmp_path, base_url, origin):
    with TestClient(create_app(tmp_path), base_url=base_url, headers={"origin": origin}) as client:
        assert client.get("/").status_code == 200
        assert client.get("/healthz").json()["ready"]
        assert client.get("/api/handoffs").json()["data"]["items"] == []
        assert client.get("/api/overview").status_code == 200
        assert client.post("/mcp", content=b"x" * 65537).status_code == 413


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
    saved = app.state.store.execute("baton_save", {"operation_id": str(uuid.uuid4()), "record": record})["data"]
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
    from baton.models import INPUTS, Record
    schemas = Path(__file__).resolve().parents[1] / "schemas"
    for name, model in {**INPUTS, "record": Record}.items():
        assert json.loads((schemas / f"{name}.json").read_text()) == model.model_json_schema(), name
