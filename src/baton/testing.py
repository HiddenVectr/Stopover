"""Backend conformance suite: behaviour every Baton storage backend must provide.

Use it from any project that implements baton.backend.Backend:

    from baton.testing import *  # noqa: F401,F403  (collects the tests and fixtures)

    @pytest.fixture
    def make_service(...):
        def make(clock=time.time, policy=None):
            return BatonService(MyBackend(...empty store...), clock=clock, policy=policy)
        yield make
        # close backends and clean up here

Override the ``supports_workspaces`` fixture to return True if the backend keeps workspaces apart.
Every test starts from an empty store and uses only the public service API.
"""
from __future__ import annotations

import copy
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from .context import RequestContext
from .domain import RECEIPT_TTL, Policy
from .sample import sample_record

T0 = 2_000_000_000.0


@pytest.fixture
def record():
    return copy.deepcopy(sample_record())


@pytest.fixture
def supports_workspaces():
    return False


@pytest.fixture
def service(make_service):
    return make_service()


@pytest.fixture
def clocked(make_service):
    """A service with a controllable clock: returns (service, clock list)."""
    clock = [T0]
    return make_service(clock=lambda: clock[0]), clock


def ok(result):
    assert result["ok"], result
    return result["data"]


def push(service, record, **changes):
    data = copy.deepcopy(record)
    data.update(changes)
    return ok(service.execute("baton_push", {"operation_id": str(uuid.uuid4()), "record": data}))


def results_for(record, outcome="pass"):
    return [{"index": i, "result": outcome, "evidence": "Observed"} for i in range(len(record["context"]["acceptance_criteria"]))]


def entry(key="communication.length", content="Prefers concise answers.", revision=0, **extra):
    return {"key": key, "content": content, "expected_revision": revision, "category": "preference",
            "basis": "stated", "source": {"client": "codex"}, "evidence": "Stated by the user.", **extra}


def update(*entries, client="codex", **extra):
    return {"operation_id": str(uuid.uuid4()), "client": client, "memories": list(entries), **extra}


# Handoffs

def test_conformance_push_is_idempotent_under_concurrency(service, record):
    args = {"operation_id": str(uuid.uuid4()), "record": record}
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.execute("baton_push", args), range(40)))
    assert all(r["ok"] for r in results), [r for r in results if not r["ok"]][:1]
    assert len({r["data"]["id"] for r in results}) == 1
    assert sum(not r["replayed"] for r in results) == 1
    changed = copy.deepcopy(args)
    changed["record"]["title"] = "Different"
    assert service.execute("baton_push", changed)["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert service.overview()["total"] == 1


def test_conformance_get_returns_the_saved_record(service, record):
    saved = push(service, record)
    data = ok(service.execute("baton_get", {"id": saved["id"]}))
    assert data["record"]["context"]["objective"] == record["context"]["objective"]
    assert data["record"]["title"] == record["title"] and data["record_sha256"] == saved["record_sha256"]
    assert data["revision"] == 1 and data["effective_status"] == "available"
    assert service.execute("baton_get", {"id": str(uuid.uuid4())})["error"]["code"] == "NOT_FOUND"


def test_conformance_only_one_concurrent_claim_wins(service, record):
    saved = push(service, record)
    args = lambda _: {"operation_id": str(uuid.uuid4()), "id": saved["id"], "holder_label": "agent"}  # noqa: E731
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: service.execute("baton_claim", args(i)), range(16)))
    assert sum(r["ok"] for r in results) == 1
    assert all(r["ok"] or r["error"]["code"] == "ALREADY_CLAIMED" for r in results)


def test_conformance_lease_expiry_and_fencing(clocked, record):
    service, clock = clocked
    saved = push(service, record)
    first = ok(service.execute("baton_claim", {"id": saved["id"], "holder_label": "codex", "lease_seconds": 60}))
    clock[0] += 61
    assert ok(service.execute("baton_get", {"id": saved["id"]}))["effective_status"] == "available"
    assert ok(service.execute("baton_claim", {"id": saved["id"], "action": "renew", "claim_token": first["claim_token"]}))["claim"]["active"]
    clock[0] += 3601
    second = ok(service.execute("baton_claim", {"id": saved["id"], "holder_label": "claude-code"}))
    assert second["claim_generation"] == 2
    stale = service.execute("baton_complete", {"id": saved["id"], "claim_token": first["claim_token"],
                                               "completion": {"outcome": "blocked", "summary": "Too late"}})
    assert stale["error"]["code"] == "INVALID_CLAIM"


def test_conformance_completion_rules(service, record):
    record["context"]["acceptance_criteria"] = ["Tests pass", "Docs updated"]
    saved = push(service, record)
    token = ok(service.execute("baton_claim", {"id": saved["id"], "holder_label": "codex"}))["claim_token"]
    base = {"id": saved["id"], "claim_token": token}
    partial = service.execute("baton_complete", {**base, "completion": {"outcome": "succeeded", "summary": "Done",
        "acceptance_results": [{"index": 0, "result": "pass", "evidence": "pytest"}]}})
    assert partial["error"]["code"] == "VALIDATION_ERROR" and "[1] Docs updated" in partial["error"]["message"]
    args = {**base, "operation_id": str(uuid.uuid4()), "completion": {"outcome": "succeeded", "summary": "Done",
            "acceptance_results": [{"criterion": "tests PASS", "result": "pass", "evidence": "pytest"},
                                   {"index": 1, "result": "pass", "evidence": "README"}]}}
    done = service.execute("baton_complete", args)
    assert done["ok"] and done["data"]["status"] == "completed"
    assert service.execute("baton_complete", args)["replayed"]
    assert service.execute("baton_complete", {**args, "operation_id": str(uuid.uuid4())})["error"]["code"] == "ALREADY_COMPLETED"
    stored = ok(service.execute("baton_get", {"id": saved["id"]}))["completion"]["acceptance_results"]
    assert [(r["index"], r["criterion"]) for r in stored] == [(0, "Tests pass"), (1, "Docs updated")]


def test_conformance_release_and_resume(service, record):
    saved = push(service, record)
    token = ok(service.execute("baton_claim", {"id": saved["id"], "holder_label": "codex"}))["claim_token"]
    released = ok(service.execute("baton_claim", {"id": saved["id"], "action": "release", "claim_token": token}))
    assert released["effective_status"] == "available"
    op = str(uuid.uuid4())
    resumed = ok(service.execute("baton_resume", {"operation_id": op, "id": saved["id"], "holder_label": "claude-code"}))
    assert resumed["record"]["title"] == record["title"] and resumed["claim_token"]
    replay = service.execute("baton_resume", {"operation_id": op, "id": saved["id"], "holder_label": "claude-code"})
    assert replay["replayed"] and replay["data"]["claim_token"] == resumed["claim_token"]
    assert service.execute("baton_resume", {"id": saved["id"], "holder_label": "other"})["error"]["code"] == "ALREADY_CLAIMED"


def test_conformance_claim_tokens_never_appear_in_reads(service, record):
    saved = push(service, record)
    token = ok(service.execute("baton_claim", {"id": saved["id"], "holder_label": "codex"}))["claim_token"]
    reads = [service.execute("baton_get", {"id": saved["id"]}), service.execute("baton_list", {"status": "all"}),
             service.events(saved["id"]), service.overview()]
    assert token not in json.dumps(reads)


def test_conformance_list_filters_and_pagination(service, record):
    ids = {push(service, record, title=f"Record {i:02}", project_key="alpha" if i % 2 else "beta")["id"] for i in range(45)}
    found, cursor = [], None
    while True:
        page = ok(service.execute("baton_list", {"status": "all", "limit": 20, "cursor": cursor}))
        found += [item["id"] for item in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(found) == 45 and set(found) == ids
    assert len(ok(service.execute("baton_list", {"status": "all", "project_key": "alpha", "limit": 20}))["items"]) == 20
    assert len(ok(service.execute("baton_list", {"status": "all", "q": "Record 07"}))["items"]) == 1
    first = ok(service.execute("baton_list", {"status": "all"}))["next_cursor"]
    assert service.execute("baton_list", {"status": "all", "q": "x", "cursor": first})["error"]["code"] == "INVALID_CURSOR"
    claimed = next(iter(ids))
    ok(service.execute("baton_claim", {"id": claimed, "holder_label": "codex"}))
    assert [i["id"] for i in ok(service.execute("baton_list", {"status": "claimed"}))["items"]] == [claimed]


def test_conformance_invalid_input_writes_nothing(service, record):
    record["context"]["next_steps"] = []
    assert service.execute("baton_push", {"record": record})["error"]["code"] == "VALIDATION_ERROR"
    assert service.overview()["total"] == 0


def test_conformance_delete(service, record):
    saved = push(service, record)
    token = ok(service.execute("baton_claim", {"id": saved["id"], "holder_label": "codex"}))["claim_token"]
    assert service.execute("baton_delete", {"id": saved["id"]})["error"]["code"] == "ALREADY_CLAIMED"
    ok(service.execute("baton_claim", {"id": saved["id"], "action": "release", "claim_token": token}))
    assert ok(service.execute("baton_delete", {"id": saved["id"]}))["deleted"]
    assert service.execute("baton_get", {"id": saved["id"]})["error"]["code"] == "NOT_FOUND"
    assert service.overview()["total"] == 0


def test_conformance_events_history(service, record):
    saved = push(service, record)
    token = ok(service.execute("baton_claim", {"id": saved["id"], "holder_label": "codex"}))["claim_token"]
    ok(service.execute("baton_complete", {"id": saved["id"], "claim_token": token, "completion": {"outcome": "abandoned", "summary": "Stop"}}))
    assert [e["event"] for e in service.events(saved["id"])["items"]] == ["completed", "acquire", "pushed"]


def test_conformance_retention_and_receipt_expiry(make_service, record):
    clock = [T0]
    service = make_service(clock=lambda: clock[0], policy=Policy(retention_days=30))
    args = {"operation_id": str(uuid.uuid4()), "record": record}
    first = ok(service.execute("baton_push", args))
    token = ok(service.execute("baton_claim", {"id": first["id"], "holder_label": "codex"}))["claim_token"]
    ok(service.execute("baton_complete", {"id": first["id"], "claim_token": token, "completion": {"outcome": "abandoned", "summary": "Stop"}}))
    clock[0] += RECEIPT_TTL + 60
    retried = service.execute("baton_push", args)
    assert not retried["replayed"] and retried["data"]["id"] != first["id"]
    clock[0] += 31 * 86400
    push(service, record)
    assert service.execute("baton_get", {"id": first["id"]})["error"]["code"] == "NOT_FOUND"


def test_conformance_policy_limits(make_service, record):
    service = make_service(policy=Policy(max_handoffs=2, max_memories=1))
    push(service, record)
    push(service, record)
    assert service.execute("baton_push", {"record": record})["error"]["code"] == "STORE_FULL"
    ok(service.execute("baton_memory_update", update(entry("a.one"))))
    assert service.execute("baton_memory_update", update(entry("a.two")))["error"]["code"] == "STORE_FULL"


def test_conformance_clock_moving_backward(clocked, record):
    service, clock = clocked
    saved = push(service, record)
    clock[0] -= 3600
    claimed = ok(service.execute("baton_claim", {"id": saved["id"], "holder_label": "codex"}))
    assert claimed["receipt_at"] >= saved["receipt_at"]


# Personal memories

def test_conformance_memory_update_conflicts_and_partial(service):
    saved = ok(service.execute("baton_memory_update", update(entry("a.one"), entry("a.two"))))
    assert [i["action"] for i in saved["items"]] == ["added", "added"] and saved["store_revision"] == 2
    stale = update(entry("a.one", "New"), entry("a.two", "New"), entry("a.three", "Three"))
    error = service.execute("baton_memory_update", stale)["error"]
    assert error["code"] == "REVISION_CONFLICT" and {c["key"] for c in error["conflicts"]} == {"a.one", "a.two"}
    assert len(ok(service.execute("baton_memory_read", {}))["items"]) == 2
    result = ok(service.execute("baton_memory_update", {**stale, "operation_id": str(uuid.uuid4()), "partial": True}))
    assert [i["action"] for i in result["items"]] == ["conflict", "conflict", "added"]


def test_conformance_memory_provenance_and_replay(service):
    args = update(entry())
    ok(service.execute("baton_memory_update", args))
    assert service.execute("baton_memory_update", args)["replayed"]
    resync = update(entry(revision=1, source={"client": "claude-code"}), client="claude-code")
    assert ok(service.execute("baton_memory_update", resync))["items"][0]["action"] == "unchanged"
    item = ok(service.execute("baton_memory_read", {}))["items"][0]
    assert item["source"]["client"] == "codex" and item["revision"] == 1


def test_conformance_memory_forget_and_recreate(service):
    ok(service.execute("baton_memory_update", update(entry(content="Private detail"))))
    ok(service.execute("baton_memory_forget", {"memories": [{"key": "communication.length"}]}))
    assert ok(service.execute("baton_memory_read", {}))["items"] == []
    marker = ok(service.execute("baton_memory_read", {"since_revision": 1}))["items"][0]
    assert marker["deleted"] and "content" not in marker
    assert "Private detail" not in json.dumps(ok(service.execute("baton_memory_export", {"include_deleted": True, "format": "markdown"})))
    assert service.execute("baton_memory_update", update(entry(revision=2)))["error"]["code"] == "MEMORY_DELETED"
    recreated = ok(service.execute("baton_memory_update", update(entry(content="Fresh", revision=2, recreate=True))))
    assert recreated["items"][0]["action"] == "recreated"


def test_conformance_memory_pagination_and_checkpoints(service):
    ok(service.execute("baton_memory_update", update(*(entry(f"topic.{i:02}", f"Memory {i}") for i in range(25)))))
    first = ok(service.execute("baton_memory_read", {"limit": 10}))
    ok(service.execute("baton_memory_update", update(entry("topic.12", "Changed", revision=13))))
    rest, cursor = [], first["next_cursor"]
    while cursor:
        page = ok(service.execute("baton_memory_read", {"limit": 10, "cursor": cursor}))
        assert page["store_revision"] == first["store_revision"] == 25
        rest += page["items"]
        cursor = page["next_cursor"]
    assert len(first["items"]) + len(rest) == 25
    assert [i["content"] for i in ok(service.execute("baton_memory_read", {"since_revision": 25}))["items"]] == ["Changed"]
    assert len(ok(service.execute("baton_memory_read", {"q": "Memory 2"}))["items"]) == 6
    assert ok(service.execute("baton_memory_read", {"category": "habit"}))["items"] == []


# Workspaces

def test_conformance_workspaces_are_isolated(make_service, supports_workspaces, record):
    if not supports_workspaces:
        pytest.skip("Backend serves a single workspace")
    service = make_service()
    a, b = RequestContext(workspace="ws-a", actor="alice"), RequestContext(workspace="ws-b", actor="bob")
    saved = ok(service.execute("baton_push", {"record": record}, a))
    ok(service.execute("baton_memory_update", update(entry()), a))
    assert ok(service.execute("baton_list", {"status": "all"}, b))["items"] == []
    assert service.execute("baton_get", {"id": saved["id"]}, b)["error"]["code"] == "NOT_FOUND"
    assert service.execute("baton_claim", {"id": saved["id"], "holder_label": "x"}, b)["error"]["code"] == "NOT_FOUND"
    assert service.execute("baton_delete", {"id": saved["id"]}, b)["error"]["code"] == "NOT_FOUND"
    assert ok(service.execute("baton_memory_read", {}, b))["items"] == []
    assert service.overview(b)["total"] == 0 and service.overview(a)["total"] == 1
    assert ok(service.execute("baton_memory_update", update(entry()), b))["items"][0]["action"] == "added"
    assert service.events(saved["id"], ctx=a)["items"][0]["details"]["actor"] == "alice"


__all__ = ["record", "service", "clocked", "supports_workspaces", *[name for name in dir() if name.startswith("test_conformance_")]]
