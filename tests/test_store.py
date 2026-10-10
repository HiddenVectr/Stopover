import copy
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from stopover.store import Store


def claim_args(handoff, **overrides):
    return {"operation_id": str(uuid.uuid4()), "id": handoff["id"], "expected_revision": handoff["revision"], "holder_label": "claude-code", **overrides}


def test_push_replay_and_changed_payload(store, record):
    args = {"operation_id": str(uuid.uuid4()), "record": record}
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda _: store.execute("stopover_save", args), range(100)))
    assert all(result["ok"] for result in results)
    assert len({r["data"]["id"] for r in results}) == 1
    assert sum(not r["replayed"] for r in results) == 1
    args["record"]["title"] = "Changed content"
    assert store.execute("stopover_save", args)["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert store.overview()["total"] == 1


def test_competing_claims(store, push):
    handoff = push()
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(lambda _: store.execute("stopover_claim", claim_args(handoff)), range(20)))
    assert sum(r["ok"] for r in results) == 1
    assert all(r["ok"] or r["error"]["code"] == "REVISION_CONFLICT" for r in results)


def test_lease_expiry_fencing_and_renewal_replay(store, push):
    clock = [2_000_000_000.0]
    store.clock = lambda: clock[0]
    handoff = push()
    acquired = store.execute("stopover_claim", claim_args(handoff, lease_seconds=60))["data"]
    renew = {"operation_id": str(uuid.uuid4()), "id": handoff["id"], "expected_revision": acquired["revision"],
             "action": "renew", "claim_token": acquired["claim_token"], "claim_generation": acquired["claim_generation"], "lease_seconds": 60}
    renewed = store.execute("stopover_claim", renew)
    clock[0] += 59
    replay = store.execute("stopover_claim", renew)
    assert replay["replayed"] and replay["data"] == renewed["data"]
    assert store.execute("stopover_get", {"id": handoff["id"]})["data"]["effective_status"] == "claimed"
    clock[0] += 1
    current = store.execute("stopover_get", {"id": handoff["id"]})["data"]
    assert current["effective_status"] == "available"
    fresh = store.execute("stopover_claim", claim_args(current, holder_label="codex"))["data"]
    assert fresh["claim_generation"] == 2
    stale = {**renew, "operation_id": str(uuid.uuid4()), "expected_revision": fresh["revision"]}
    assert store.execute("stopover_claim", stale)["error"]["code"] == "INVALID_CLAIM"
    assert acquired["claim_token"] not in json.dumps(store.execute("stopover_get", {"id": handoff["id"]}))
    assert fresh["claim_token"] not in json.dumps(store.events(handoff["id"]))


def test_completion_requires_owner_and_evidence(store, push, record):
    handoff = push()
    acquired = store.execute("stopover_claim", claim_args(handoff))["data"]
    args = {"operation_id": str(uuid.uuid4()), "id": handoff["id"], "expected_revision": acquired["revision"],
            "claim_token": acquired["claim_token"], "claim_generation": acquired["claim_generation"],
            "completion": {"outcome": "succeeded", "summary": "Verified context recovery", "acceptance_results": []}}
    assert store.execute("stopover_complete", args)["error"]["code"] == "VALIDATION_ERROR"
    args["completion"]["acceptance_results"] = [{"criterion": text, "result": "pass", "evidence": "Observed by the local test client"} for text in record["context"]["acceptance_criteria"]]
    wrong = {**args, "claim_token": "x" * 43}
    assert store.execute("stopover_complete", wrong)["error"]["code"] == "INVALID_CLAIM"
    completed = store.execute("stopover_complete", args)
    assert completed["ok"] and completed["data"]["status"] == "completed"
    assert store.execute("stopover_complete", args)["replayed"]
    assert store.execute("stopover_complete", {**args, "operation_id": str(uuid.uuid4())})["error"]["code"] == "ALREADY_COMPLETED"
    full = store.execute("stopover_get", {"id": handoff["id"]})["data"]
    assert full["completion"]["summary"] == "Verified context recovery"


def test_release_keeps_context_and_allows_new_owner(store, push):
    handoff = push()
    acquired = store.execute("stopover_claim", claim_args(handoff))["data"]
    released = store.execute("stopover_claim", {"operation_id": str(uuid.uuid4()), "id": handoff["id"], "expected_revision": acquired["revision"], "action": "release", "claim_token": acquired["claim_token"], "claim_generation": acquired["claim_generation"]})
    assert released["ok"] and released["data"]["effective_status"] == "available"
    assert store.execute("stopover_get", {"id": handoff["id"]})["data"]["record_sha256"] == handoff["record_sha256"]


def test_pagination_filters_and_invalid_cursor(store, push):
    ids = {push(title=f"Record {i}")["id"] for i in range(55)}
    found, cursor = [], None
    while True:
        query = {"status": "all", "cursor": cursor}
        page = store.execute("stopover_list", query)["data"]
        found.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(found) == 55 and set(found) == ids
    cursor = store.execute("stopover_list", {"status": "all"})["data"]["next_cursor"]
    assert store.execute("stopover_list", {"cursor": cursor, "q": "another"})["error"]["code"] == "INVALID_CURSOR"
    assert store.execute("stopover_list", {"cursor": "%%%"})["error"]["code"] == "INVALID_CURSOR"
    assert len(store.execute("stopover_list", {"q": "Record 54"})["data"]["items"]) == 1


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
    result = store.execute("stopover_save", {"operation_id": str(uuid.uuid4()), "record": record})
    assert not result["ok"] and result["error"]["code"] == "VALIDATION_ERROR"
    assert store.overview()["total"] == 0


def test_rollback_before_receipt(store, record, monkeypatch):
    def fail(*args):
        raise sqlite3.OperationalError("Injected failure before receipt")
    monkeypatch.setattr(store, "_event", fail)
    result = store.execute("stopover_save", {"operation_id": str(uuid.uuid4()), "record": record})
    assert not result["ok"]
    assert store.db.execute("SELECT count(*) FROM handoffs").fetchone()[0] == 0
    assert store.db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 0


def test_store_reopen_and_owner_lock(tmp_path, record):
    store = Store(tmp_path)
    args = {"operation_id": str(uuid.uuid4()), "record": record}
    saved = store.execute("stopover_save", args)
    acquired = store.execute("stopover_claim", claim_args(saved["data"]))["data"]
    with pytest.raises(RuntimeError, match="already owns"):
        Store(tmp_path)
    store.close()
    reopened = Store(tmp_path)
    try:
        current = reopened.execute("stopover_get", {"id": saved["data"]["id"]})["data"]
        assert current["claim"]["expires_at"] == acquired["claim"]["expires_at"]
        assert current["revision"] == acquired["revision"]
        assert reopened.execute("stopover_save", args)["replayed"]
        assert reopened.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        reopened.close()


def test_expired_claim_completes_until_someone_else_acquires(store, push, record):
    clock = [2_000_000_000.0]
    store.clock = lambda: clock[0]
    handoff = push()
    token = store.execute("stopover_claim", {"id": handoff["id"], "holder_label": "codex", "lease_seconds": 60})["data"]["claim_token"]
    clock[0] += 3600
    assert store.execute("stopover_get", {"id": handoff["id"]})["data"]["effective_status"] == "available"
    renewed = store.execute("stopover_claim", {"id": handoff["id"], "action": "renew", "claim_token": token, "lease_seconds": 60})
    assert renewed["ok"] and renewed["data"]["claim"]["active"]
    clock[0] += 3600
    results = [{"index": i, "result": "pass", "evidence": "Observed"} for i in range(len(record["context"]["acceptance_criteria"]))]
    done = store.execute("stopover_complete", {"id": handoff["id"], "claim_token": token,
                                              "completion": {"outcome": "succeeded", "summary": "Finished late", "acceptance_results": results}})
    assert done["ok"], done


def test_expired_claim_is_fenced_after_new_acquire(store, push):
    clock = [2_000_000_000.0]
    store.clock = lambda: clock[0]
    handoff = push()
    old = store.execute("stopover_claim", {"id": handoff["id"], "holder_label": "codex", "lease_seconds": 60})["data"]["claim_token"]
    clock[0] += 61
    assert store.execute("stopover_claim", {"id": handoff["id"], "holder_label": "claude-code"})["ok"]
    late = store.execute("stopover_complete", {"id": handoff["id"], "claim_token": old,
                                              "completion": {"outcome": "blocked", "summary": "Too late"}})
    assert late["error"]["code"] == "INVALID_CLAIM"


def test_lease_limits(store, push):
    handoff = push()
    assert store.execute("stopover_claim", {"id": handoff["id"], "holder_label": "codex", "lease_seconds": 86401})["error"]["code"] == "VALIDATION_ERROR"
    claimed = store.execute("stopover_claim", {"id": handoff["id"], "holder_label": "codex"})["data"]
    assert claimed["claim"]["expires_at"] == store.execute("stopover_get", {"id": handoff["id"]})["data"]["claim"]["expires_at"]


def test_criteria_by_index_or_reworded_text(store, record):
    record["context"]["acceptance_criteria"] = ["Tests pass", "Docs   updated"]
    handoff = store.execute("stopover_save", {"record": record})["data"]
    token = store.execute("stopover_claim", {"id": handoff["id"], "holder_label": "codex"})["data"]["claim_token"]
    base = {"id": handoff["id"], "claim_token": token}
    missing = store.execute("stopover_complete", {**base, "completion": {"outcome": "succeeded", "summary": "Done",
        "acceptance_results": [{"criterion": "Tests pass", "result": "pass", "evidence": "pytest"}]}})
    assert missing["error"]["code"] == "VALIDATION_ERROR" and "[1] Docs   updated" in missing["error"]["message"]
    bad_index = store.execute("stopover_complete", {**base, "completion": {"outcome": "succeeded", "summary": "Done",
        "acceptance_results": [{"index": 5, "result": "pass", "evidence": "pytest"}]}})
    assert "index 5" in bad_index["error"]["message"]
    done = store.execute("stopover_complete", {**base, "completion": {"outcome": "succeeded", "summary": "Done",
        "acceptance_results": [{"criterion": "tests PASS", "result": "pass", "evidence": "pytest"},
                               {"index": 1, "result": "pass", "evidence": "README"}]}})
    assert done["ok"], done
    stored = store.execute("stopover_get", {"id": handoff["id"]})["data"]["completion"]["acceptance_results"]
    assert [(r["index"], r["criterion"]) for r in stored] == [(0, "Tests pass"), (1, "Docs   updated")]


def test_lenient_inputs_and_helpful_errors(store, record):
    record["context"]["next_steps"][0]["id"] = "read and restate"
    upper = store.execute("stopover_save", {"operation_id": str(uuid.uuid4()).upper(), "record": record})
    assert upper["ok"], upper
    handoff_id = upper["data"]["id"]
    assert store.execute("stopover_get", {"id": handoff_id.upper()})["ok"]
    assert store.execute("stopover_get", {"id": handoff_id})["data"]["record"]["context"]["next_steps"][0]["id"] == "read-and-restate"
    assert store.execute("stopover_save", {"operation_id": str(uuid.uuid1()), "record": record})["ok"]
    assert store.execute("stopover_save", {"record": record})["ok"]
    assert len(store.execute("stopover_list", {"limit": "2"})["data"]["items"]) == 2
    record["source"]["captured_at"] = "2026-10-06T12:00:00+02:00"
    error = store.execute("stopover_save", {"record": record})["error"]
    assert "record.source" in error["message"] and "UTC" in error["message"]
    assert "must be a UUID" in store.execute("stopover_get", {"id": "nope"})["error"]["message"]


def test_clock_moving_backward_keeps_times_monotonic(store, push):
    clock = [2_000_000_000.0]
    store.clock = lambda: clock[0]
    handoff = push()
    clock[0] -= 3600
    claimed = store.execute("stopover_claim", {"id": handoff["id"], "holder_label": "codex"})
    assert claimed["ok"], claimed
    assert claimed["data"]["receipt_at"] >= handoff["receipt_at"]


def test_claim_tokens_are_not_stored_in_plain_text(store, push):
    handoff = push()
    token = store.execute("stopover_claim", {"id": handoff["id"], "holder_label": "codex"})["data"]["claim_token"]
    # The acquire receipt keeps the token only so a lost response can be retried.
    assert store.db.execute("SELECT count(*) FROM handoffs WHERE token=?", (token,)).fetchone()[0] == 0
    store.execute("stopover_claim", {"id": handoff["id"], "action": "release", "claim_token": token})
    assert token not in "\n".join(store.db.iterdump())


def test_receipts_expire_and_retention_purges_completed(tmp_path, record):
    clock = [2_000_000_000.0]
    store = Store(tmp_path, clock=lambda: clock[0], retention_days=30)
    try:
        args = {"operation_id": str(uuid.uuid4()), "record": record}
        first = store.execute("stopover_save", args)["data"]
        token = store.execute("stopover_claim", {"id": first["id"], "holder_label": "codex"})["data"]["claim_token"]
        store.execute("stopover_complete", {"id": first["id"], "claim_token": token, "completion": {"outcome": "abandoned", "summary": "No longer needed"}})
        clock[0] += 8 * 86400
        retried = store.execute("stopover_save", args)
        assert not retried["replayed"] and retried["data"]["id"] != first["id"]
        assert store.execute("stopover_get", {"id": first["id"]})["ok"]
        clock[0] += 31 * 86400
        store.execute("stopover_save", {"record": record})
        assert store.execute("stopover_get", {"id": first["id"]})["error"]["code"] == "NOT_FOUND"
        assert store.db.execute("SELECT count(*) FROM events WHERE handoff_id=?", (first["id"],)).fetchone()[0] == 0
    finally:
        store.close()


def test_delete(store, push):
    handoff = push()
    token = store.execute("stopover_claim", {"id": handoff["id"], "holder_label": "codex"})["data"]["claim_token"]
    assert store.execute("stopover_delete", {"id": handoff["id"]})["error"]["code"] == "ALREADY_CLAIMED"
    store.execute("stopover_claim", {"id": handoff["id"], "action": "release", "claim_token": token})
    assert store.execute("stopover_delete", {"id": handoff["id"]})["data"] == {"id": handoff["id"], "deleted": True}
    assert store.execute("stopover_get", {"id": handoff["id"]})["error"]["code"] == "NOT_FOUND"
    assert store.overview()["total"] == 0


def test_migrates_v1_store(tmp_path, record):
    store = Store(tmp_path)
    handoff = store.execute("stopover_save", {"record": record})["data"]
    token = store.execute("stopover_claim", {"id": handoff["id"], "holder_label": "codex"})["data"]["claim_token"]
    # Rewrite the store into its v1 shape: plaintext token, no receipt timestamps.
    store.db.executescript(f"""
        UPDATE handoffs SET token='{token}';
        DROP INDEX receipt_age; ALTER TABLE receipts DROP COLUMN at;
        UPDATE meta SET value='1' WHERE key='schema';""")
    store.close()
    store = Store(tmp_path)
    try:
        assert store.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] == "2"
        assert store.db.execute("SELECT token FROM handoffs").fetchone()[0] != token
        assert store.execute("stopover_claim", {"id": handoff["id"], "action": "renew", "claim_token": token})["ok"]
    finally:
        store.close()


def test_resume_claims_and_returns_record(store, push, record):
    handoff = push()
    op = str(uuid.uuid4())
    resumed = store.execute("stopover_resume", {"operation_id": op, "id": handoff["id"], "holder_label": "codex"})
    assert resumed["ok"], resumed
    data = resumed["data"]
    assert data["record"]["context"]["objective"] == record["context"]["objective"]
    assert data["effective_status"] == "claimed" and data["claim"]["holder_label"] == "codex" and data["claim_token"]
    replay = store.execute("stopover_resume", {"operation_id": op, "id": handoff["id"], "holder_label": "codex"})
    assert replay["replayed"] and replay["data"]["claim_token"] == data["claim_token"]
    other = store.execute("stopover_resume", {"id": handoff["id"], "holder_label": "claude-code"})
    assert other["error"]["code"] == "ALREADY_CLAIMED"
    done = store.execute("stopover_complete", {"id": handoff["id"], "claim_token": data["claim_token"],
                                              "completion": {"outcome": "blocked", "summary": "Waiting on review"}})
    assert done["ok"], done
    assert store.execute("stopover_resume", {"id": handoff["id"], "holder_label": "codex"})["error"]["code"] == "ALREADY_COMPLETED"
    assert len(store.db.execute("SELECT result FROM receipts WHERE tool='stopover_resume'").fetchone()[0]) < 2000


def test_resume_receipt_token_is_scrubbed_when_claim_ends(store, push):
    handoff = push()
    token = store.execute("stopover_resume", {"operation_id": str(uuid.uuid4()), "id": handoff["id"], "holder_label": "codex"})["data"]["claim_token"]
    store.execute("stopover_complete", {"id": handoff["id"], "claim_token": token, "completion": {"outcome": "abandoned", "summary": "Stopped"}})
    assert token not in "\n".join(store.db.iterdump())


@pytest.mark.parametrize("legacy", ["baton.sqlite3", "handoff.sqlite3"])  # the names before each rename
def test_pre_rename_store_is_adopted(tmp_path, record, legacy):
    store = Store(tmp_path)
    saved = store.execute("stopover_save", {"record": record})["data"]
    store.close()
    (tmp_path / "stopover.sqlite3").rename(tmp_path / legacy)
    reopened = Store(tmp_path)
    try:
        assert reopened.execute("stopover_get", {"id": saved["id"]})["ok"]
        assert (tmp_path / "stopover.sqlite3").exists() and not (tmp_path / legacy).exists()
    finally:
        reopened.close()


def test_environment_variables_from_before_the_renames_still_work(monkeypatch):
    from stopover import env
    monkeypatch.setenv("HANDOFF_RETENTION_DAYS", "1")
    assert env("RETENTION_DAYS") == "1"
    monkeypatch.setenv("BATON_RETENTION_DAYS", "2")
    assert env("RETENTION_DAYS") == "2"
    monkeypatch.setenv("STOPOVER_RETENTION_DAYS", "3")
    assert env("RETENTION_DAYS") == "3"
    assert env("NOT_SET", "default") == "default"
