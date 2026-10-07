import copy
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from handoff.store import Store


def claim_args(handoff, **overrides):
    return {"operation_id": str(uuid.uuid4()), "id": handoff["id"], "expected_revision": handoff["revision"], "holder_label": "claude-code", **overrides}


def test_push_replay_and_changed_payload(store, record):
    args = {"operation_id": str(uuid.uuid4()), "record": record}
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda _: store.execute("handoff_push", args), range(100)))
    assert all(result["ok"] for result in results)
    assert len({r["data"]["id"] for r in results}) == 1
    assert sum(not r["replayed"] for r in results) == 1
    args["record"]["title"] = "Changed content"
    assert store.execute("handoff_push", args)["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert store.overview()["total"] == 1


def test_competing_claims(store, push):
    handoff = push()
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(lambda _: store.execute("handoff_claim", claim_args(handoff)), range(20)))
    assert sum(r["ok"] for r in results) == 1
    assert all(r["ok"] or r["error"]["code"] == "REVISION_CONFLICT" for r in results)


def test_lease_expiry_fencing_and_renewal_replay(store, push):
    clock = [2_000_000_000.0]
    store.clock = lambda: clock[0]
    handoff = push()
    acquired = store.execute("handoff_claim", claim_args(handoff, lease_seconds=60))["data"]
    renew = {"operation_id": str(uuid.uuid4()), "id": handoff["id"], "expected_revision": acquired["revision"],
             "action": "renew", "claim_token": acquired["claim_token"], "claim_generation": acquired["claim_generation"], "lease_seconds": 60}
    renewed = store.execute("handoff_claim", renew)
    clock[0] += 59
    replay = store.execute("handoff_claim", renew)
    assert replay["replayed"] and replay["data"] == renewed["data"]
    assert store.execute("handoff_get", {"id": handoff["id"]})["data"]["effective_status"] == "claimed"
    clock[0] += 1
    current = store.execute("handoff_get", {"id": handoff["id"]})["data"]
    assert current["effective_status"] == "available"
    fresh = store.execute("handoff_claim", claim_args(current, holder_label="codex"))["data"]
    assert fresh["claim_generation"] == 2
    stale = {**renew, "operation_id": str(uuid.uuid4()), "expected_revision": fresh["revision"]}
    assert store.execute("handoff_claim", stale)["error"]["code"] == "INVALID_CLAIM"
    assert acquired["claim_token"] not in json.dumps(store.execute("handoff_get", {"id": handoff["id"]}))
    assert fresh["claim_token"] not in json.dumps(store.events(handoff["id"]))


def test_completion_requires_owner_and_evidence(store, push, record):
    handoff = push()
    acquired = store.execute("handoff_claim", claim_args(handoff))["data"]
    args = {"operation_id": str(uuid.uuid4()), "id": handoff["id"], "expected_revision": acquired["revision"],
            "claim_token": acquired["claim_token"], "claim_generation": acquired["claim_generation"],
            "completion": {"outcome": "succeeded", "summary": "Verified context recovery", "acceptance_results": []}}
    assert store.execute("handoff_complete", args)["error"]["code"] == "VALIDATION_ERROR"
    args["completion"]["acceptance_results"] = [{"criterion": text, "result": "pass", "evidence": "Observed by the local test client"} for text in record["context"]["acceptance_criteria"]]
    wrong = {**args, "claim_token": "x" * 43}
    assert store.execute("handoff_complete", wrong)["error"]["code"] == "INVALID_CLAIM"
    completed = store.execute("handoff_complete", args)
    assert completed["ok"] and completed["data"]["status"] == "completed"
    assert store.execute("handoff_complete", args)["replayed"]
    assert store.execute("handoff_complete", {**args, "operation_id": str(uuid.uuid4())})["error"]["code"] == "ALREADY_COMPLETED"
    full = store.execute("handoff_get", {"id": handoff["id"]})["data"]
    assert full["completion"]["summary"] == "Verified context recovery"


def test_release_keeps_context_and_allows_new_owner(store, push):
    handoff = push()
    acquired = store.execute("handoff_claim", claim_args(handoff))["data"]
    released = store.execute("handoff_claim", {"operation_id": str(uuid.uuid4()), "id": handoff["id"], "expected_revision": acquired["revision"], "action": "release", "claim_token": acquired["claim_token"], "claim_generation": acquired["claim_generation"]})
    assert released["ok"] and released["data"]["effective_status"] == "available"
    assert store.execute("handoff_get", {"id": handoff["id"]})["data"]["record_sha256"] == handoff["record_sha256"]


def test_pagination_filters_and_invalid_cursor(store, push):
    ids = {push(title=f"Record {i}")["id"] for i in range(55)}
    found, cursor = [], None
    while True:
        query = {"status": "all", "cursor": cursor}
        page = store.execute("handoff_list", query)["data"]
        found.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(found) == 55 and set(found) == ids
    cursor = store.execute("handoff_list", {"status": "all"})["data"]["next_cursor"]
    assert store.execute("handoff_list", {"cursor": cursor, "q": "another"})["error"]["code"] == "INVALID_CURSOR"
    assert store.execute("handoff_list", {"cursor": "%%%"})["error"]["code"] == "INVALID_CURSOR"
    assert len(store.execute("handoff_list", {"q": "Record 54"})["data"]["items"]) == 1


@pytest.mark.parametrize("change", [
    lambda r: r.update(schema_version="2.0"),
    lambda r: r.update(arbitrary="extra"),
    lambda r: r["context"].update(next_steps=[]),
    lambda r: r["context"].update(objective="x" * 8193),
    lambda r: r["context"].update(objective="😀" * 3000),
    lambda r: r["context"]["decisions"][0].update(evidence_ids=["missing"]),
    lambda r: r.update(references=[{"id": "bad", "kind": "url", "locator": "https://user:password@example.com", "purpose": "Invalid"}]),
])
def test_validation_has_no_partial_writes(store, record, change):
    change(record)
    result = store.execute("handoff_push", {"operation_id": str(uuid.uuid4()), "record": record})
    assert not result["ok"] and result["error"]["code"] == "VALIDATION_ERROR"
    assert store.overview()["total"] == 0


def test_rollback_before_receipt(store, record, monkeypatch):
    def fail(*args):
        raise sqlite3.OperationalError("Injected failure before receipt")
    monkeypatch.setattr(store, "_event", fail)
    result = store.execute("handoff_push", {"operation_id": str(uuid.uuid4()), "record": record})
    assert not result["ok"]
    assert store.db.execute("SELECT count(*) FROM handoffs").fetchone()[0] == 0
    assert store.db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 0


def test_store_reopen_and_owner_lock(tmp_path, record):
    store = Store(tmp_path)
    args = {"operation_id": str(uuid.uuid4()), "record": record}
    saved = store.execute("handoff_push", args)
    acquired = store.execute("handoff_claim", claim_args(saved["data"]))["data"]
    with pytest.raises(RuntimeError, match="already owns"):
        Store(tmp_path)
    store.close()
    reopened = Store(tmp_path)
    try:
        current = reopened.execute("handoff_get", {"id": saved["data"]["id"]})["data"]
        assert current["claim"]["expires_at"] == acquired["claim"]["expires_at"]
        assert current["revision"] == acquired["revision"]
        assert reopened.execute("handoff_push", args)["replayed"]
        assert reopened.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        reopened.close()
