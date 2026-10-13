"""The storage contract. The service layer depends only on this; backends never contain business rules.

A backend hands out transactions scoped to one workspace. Rows cross this boundary as plain dicts with
JSON fields already decoded:

- handoff: id, record (dict), record_sha256, title, project_key, target_client, source_client, status,
  revision, created, updated, generation, holder, token_hash, expires, completion (dict | None)
- event: sequence, event, at, revision, details (dict)
- memory: id, key, revision, created, updated, deleted (bool), body (dict | None)

Times are POSIX seconds. Receipts live in two scopes, "handoff" and "memory".
Backends raise DomainError (for example STORE_BUSY, STORE_FULL, STORE_UNAVAILABLE) for storage failures.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager

from .context import RequestContext


class Transaction(ABC):
    # Handoffs
    @abstractmethod
    def get_handoff(self, handoff_id) -> dict | None: ...
    @abstractmethod
    def list_handoffs(self, *, status, project_key, target_client, q, after, limit, now) -> list[dict]:
        """Newest first by (created, id). status is an effective status or None; after is (created, id) or None."""
    @abstractmethod
    def insert_handoff(self, row: dict) -> None: ...
    @abstractmethod
    def update_handoff(self, handoff_id, **fields) -> None: ...
    @abstractmethod
    def delete_handoff(self, handoff_id) -> None:
        """Remove the handoff with its events and receipts."""
    @abstractmethod
    def count_handoffs(self) -> int: ...
    @abstractmethod
    def completed_before(self, cutoff) -> list[str]: ...
    @abstractmethod
    def inactive_before(self, cutoff, now) -> list[str]:
        """IDs of handoffs last changed before cutoff, in any status, except those with a claim still active at now."""
    @abstractmethod
    def overview(self, now) -> dict:
        """{"counts": {available, claimed, completed}, "memories": int, "projects": [...], "targets": [...]}"""

    # Events
    @abstractmethod
    def add_event(self, handoff_id, event, at, revision, details: dict) -> None: ...
    @abstractmethod
    def list_events(self, handoff_id, before, limit) -> list[dict]: ...

    # Retry receipts
    @abstractmethod
    def get_receipt(self, scope, tool, operation) -> dict | None:
        """{"request_hash": str, "result": dict} or None."""
    @abstractmethod
    def put_receipt(self, scope, tool, operation, request_hash, result: dict, at, handoff_id=None) -> None: ...
    @abstractmethod
    def prune_receipts(self, cutoff) -> None: ...
    @abstractmethod
    def count_receipts(self, scope) -> int: ...
    @abstractmethod
    def scrub_claim_tokens(self, handoff_id) -> None:
        """Drop raw claim tokens from this handoff's claim/resume receipts once the claim has ended."""

    # Small key/value state (e.g. last_time, memory_revision)
    @abstractmethod
    def get_meta(self, key) -> str | None: ...
    @abstractmethod
    def set_meta(self, key, value: str) -> None: ...

    # Personal memories
    @abstractmethod
    def get_memory(self, key) -> dict | None: ...
    @abstractmethod
    def save_memory(self, row: dict) -> None:
        """Insert or replace the memory row with this key."""
    @abstractmethod
    def list_memories(self, *, after, key, since_revision, include_deleted, category, q, limit) -> list[dict]:
        """Ordered by key, starting after the given key. Deleted rows match category/q filters (their content is gone)."""
    @abstractmethod
    def count_memories(self, *, active_only=False) -> int: ...


class Backend(ABC):
    @abstractmethod
    def transaction(self, ctx: RequestContext, write: bool = False) -> AbstractContextManager[Transaction]:
        """Commit on normal exit, roll back on exceptions. Write transactions are serialized."""
    @abstractmethod
    def ping(self) -> None: ...
    @abstractmethod
    def close(self) -> None: ...
