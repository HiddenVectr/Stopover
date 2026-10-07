"""Run the shared backend conformance suite against the SQLite backend, plus service hook tests."""
import time
import uuid

import pytest

from baton.context import RequestContext
from baton.domain import Policy
from baton.service import BatonService
from baton.sqlite_backend import SQLiteBackend
from baton.testing import *  # noqa: F401,F403


@pytest.fixture
def make_service(tmp_path):
    backends = []

    def make(clock=time.time, policy=None):
        backend = SQLiteBackend(tmp_path / f"store{len(backends)}", clock=clock)
        backends.append(backend)
        return BatonService(backend, clock=clock, policy=policy)
    yield make
    for backend in backends:
        backend.close()


def test_events_are_emitted_after_commit(tmp_path, record):
    seen = []
    service = BatonService(SQLiteBackend(tmp_path), on_event=lambda ctx, event: seen.append((ctx.actor, event)))
    try:
        ctx = RequestContext(actor="alice")
        op = str(uuid.uuid4())
        saved = service.execute("baton_push", {"operation_id": op, "record": record}, ctx)["data"]
        service.execute("baton_push", {"operation_id": op, "record": record}, ctx)  # replay: no event
        token = service.execute("baton_claim", {"id": saved["id"], "holder_label": "codex"}, ctx)["data"]["claim_token"]
        service.execute("baton_claim", {"id": saved["id"], "action": "release", "claim_token": token}, ctx)
        service.execute("baton_delete", {"id": saved["id"]}, ctx)
        service.execute("baton_memory_update", {"client": "codex", "memories": [{"key": "k", "content": "Secret", "expected_revision": 0}]}, ctx)
        types = [event["type"] for _, event in seen]
        assert types == ["handoff.pushed", "handoff.acquire", "handoff.release", "handoff.deleted", "memory.updated"]
        assert all(actor == "alice" for actor, _ in seen)
        assert seen[0][1]["details"]["actor"] == "alice" and seen[-1][1]["items"] == [{"key": "k", "action": "added", "revision": 1}]
        assert "Secret" not in str(seen) and record["context"]["objective"] not in str(seen)
    finally:
        service.close()


def test_failed_transactions_and_handler_errors_do_not_leak(tmp_path, record):
    seen = []

    def handler(ctx, event):
        seen.append(event)
        raise RuntimeError("webhook down")
    service = BatonService(SQLiteBackend(tmp_path), on_event=handler)
    try:
        assert service.execute("baton_push", {"record": record})["ok"]  # handler error is logged, not raised
        record["parent_id"] = str(uuid.uuid4())
        assert service.execute("baton_push", {"record": record})["error"]["code"] == "NOT_FOUND"
        assert [event["type"] for event in seen] == ["handoff.pushed"]
    finally:
        service.close()


def test_policy_can_vary_by_workspace(tmp_path, record):
    service = BatonService(SQLiteBackend(tmp_path), policy=lambda ctx: Policy(max_handoffs=1 if ctx.actor == "free" else 100))
    try:
        free, pro = RequestContext(actor="free"), RequestContext(actor="pro")
        assert service.execute("baton_push", {"record": record}, free)["ok"]
        assert service.execute("baton_push", {"record": record}, free)["error"]["code"] == "STORE_FULL"
        assert service.execute("baton_push", {"record": record}, pro)["ok"]
    finally:
        service.close()
