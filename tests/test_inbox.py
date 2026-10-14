"""Dashboard inbox actions: answering open questions, the Needs you view, and deleting from the dashboard."""
import copy
import uuid

from starlette.testclient import TestClient

from stopover.server import create_app
from stopover.service import StopoverService
from stopover.sqlite_backend import SQLiteBackend

QUESTIONS = ["Which columns go in the export?", "Should dates be UTC?"]


def asking(record, title="Add CSV export"):
    data = copy.deepcopy(record)
    data["title"] = title
    data["context"]["open_questions"] = list(QUESTIONS)
    return data


def save(store, record):
    result = store.execute("stopover_save", {"operation_id": str(uuid.uuid4()), "record": record})
    assert result["ok"], result
    return result["data"]["id"]


def test_answers_reach_the_next_agent_without_changing_the_record(store, record):
    handoff = save(store, asking(record))
    before = store.execute("stopover_get", {"id": handoff})["data"]
    assert before["answers"] == []
    answered = store.answer(handoff, [{"index": 1, "answer": "  Yes, UTC everywhere. "}])
    assert answered["ok"] and answered["data"]["revision"] == before["revision"] + 1
    store.answer(handoff, [{"index": 0, "answer": "Date and amount"}, {"index": 1, "answer": "No: local time"}])
    resumed = store.execute("stopover_resume", {"id": handoff, "holder_label": "codex"})["data"]
    assert [(a["index"], a["question"], a["answer"]) for a in resumed["answers"]] == [
        (0, QUESTIONS[0], "Date and amount"), (1, QUESTIONS[1], "No: local time")]
    # The saved record and its hash never change; answers sit beside it.
    assert resumed["record"] == before["record"] and resumed["record_sha256"] == before["record_sha256"]
    events = store.events(handoff)["items"]
    assert [e["event"] for e in events][:3] == ["acquire", "answered", "answered"]


def test_answers_are_validated(store, record):
    handoff = save(store, asking(record))
    assert store.answer(handoff, [{"index": 2, "answer": "x"}])["error"]["code"] == "VALIDATION_ERROR"
    assert store.answer(handoff, [{"index": 0, "answer": "   "}])["error"]["code"] == "VALIDATION_ERROR"
    assert store.answer(handoff, [])["error"]["code"] == "VALIDATION_ERROR"
    assert store.answer(handoff, None)["error"]["code"] == "VALIDATION_ERROR"
    assert store.answer(str(uuid.uuid4()), [{"index": 0, "answer": "x"}])["error"]["code"] == "NOT_FOUND"
    claim = store.execute("stopover_resume", {"id": handoff, "holder_label": "codex"})["data"]
    criteria = claim["record"]["context"]["acceptance_criteria"]
    done = store.execute("stopover_complete", {"id": handoff, "claim_token": claim["claim_token"], "completion": {
        "outcome": "succeeded", "summary": "Done",
        "acceptance_results": [{"index": i, "result": "pass", "evidence": "ok"} for i in range(len(criteria))]}})
    assert done["ok"], done
    assert store.answer(handoff, [{"index": 0, "answer": "x"}])["error"]["code"] == "ALREADY_COMPLETED"


def test_needs_you_lists_open_handoffs_with_unanswered_questions(store, record):
    first = save(store, asking(record, "First"))
    second = save(store, asking(record, "Second"))
    save(store, record)  # no questions
    listed = lambda: [i["title"] for i in store.execute("stopover_list", {"status": "needs_you"})["data"]["items"]]
    assert listed() == ["Second", "First"] and store.overview()["counts"]["needs_you"] == 2
    item = store.execute("stopover_list", {"status": "all"})["data"]["items"][1]
    assert item["needs_you"] and item["questions"] == {"open": 2, "answered": 0}
    store.answer(first, [{"index": 0, "answer": "a"}])
    assert listed() == ["Second", "First"]  # one question is still unanswered
    store.answer(first, [{"index": 1, "answer": "b"}])
    assert listed() == ["Second"] and store.overview()["counts"]["needs_you"] == 1
    # A claimed handoff still waits on you until its questions are answered.
    store.execute("stopover_resume", {"id": second, "holder_label": "codex"})
    assert listed() == ["Second"]
    page = store.execute("stopover_list", {"status": "needs_you", "limit": 1})["data"]
    assert page["next_cursor"] is None and len(page["items"]) == 1


def test_needs_you_pages_and_filters(store, record):
    for n in range(3):
        save(store, asking(record, f"Ask {n}") | {"project_key": "api" if n else "web"})
    page = store.execute("stopover_list", {"status": "needs_you", "limit": 1, "project_key": "api"})["data"]
    rest = store.execute("stopover_list", {"status": "needs_you", "limit": 1, "project_key": "api", "cursor": page["next_cursor"]})["data"]
    assert [i["title"] for i in page["items"] + rest["items"]] == ["Ask 2", "Ask 1"] and rest["next_cursor"] is None


def test_answer_events_carry_no_content(tmp_path, record):
    seen = []
    store = StopoverService(SQLiteBackend(tmp_path), on_event=lambda ctx, event: seen.append(event))
    try:
        handoff = save(store, asking(record))
        store.answer(handoff, [{"index": 1, "answer": "secret detail"}])
        assert seen[-1]["type"] == "handoff.answered" and seen[-1]["details"] == {"questions": [1]}
        assert "secret" not in repr(seen)
    finally:
        store.close()


def test_dashboard_api_answers_and_deletes(tmp_path, record):
    app = create_app(tmp_path)
    store = app.state.store
    handoff = save(store, asking(record))
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        url = "/api/handoffs/" + handoff
        response = client.post(url + "/answers", json={"answers": [{"index": 0, "answer": "Date only"}]})
        assert response.status_code == 200 and response.json()["data"]["answers"][0]["answer"] == "Date only"
        assert client.get(url).json()["data"]["answers"][0]["question"] == QUESTIONS[0]
        assert client.post(url + "/answers", content=b"not json").status_code == 400
        assert client.post(url + "/answers", json={"answers": [{"index": 9, "answer": "x"}]}).status_code == 400
        assert client.post(url + "/answers", json=["x"]).status_code == 400
        # Unlike the agent tool, the dashboard can delete a handoff an agent has claimed.
        store.execute("stopover_resume", {"id": handoff, "holder_label": "codex"})
        assert store.execute("stopover_delete", {"id": handoff})["error"]["code"] == "ALREADY_CLAIMED"
        assert client.delete(url).json()["data"] == {"id": handoff, "deleted": True}
        assert client.get(url).status_code == 404
        assert client.delete(url).status_code == 404
        assert client.delete("/api/handoffs/not-an-id").status_code == 400
        # Other sites can't use these writes.
        other = save(store, asking(record))
        assert client.delete("/api/handoffs/" + other, headers={"origin": "https://evil.example"}).status_code == 403
        assert client.post(f"/api/handoffs/{other}/answers", json={"answers": [{"index": 0, "answer": "x"}]},
                           headers={"sec-fetch-site": "cross-site"}).status_code == 403
        assert client.get("/api/handoffs/" + other).status_code == 200
