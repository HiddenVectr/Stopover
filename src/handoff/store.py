"""The local deployment: HandoffService over the single-owner SQLite backend. Also re-exports shared names."""
import time

from .domain import RECEIPT_TTL, DomainError, canonical, normalized, token_hash, utc  # noqa: F401
from .registry import Registry
from .service import HandoffService
from .sqlite_backend import SQLiteBackend


class Store(HandoffService):
    def __init__(self, directory, clock=time.time, retention_days=None, registry: Registry | None = None):
        super().__init__(SQLiteBackend(directory, clock=clock), clock=clock, retention_days=retention_days, registry=registry)

    @property
    def db(self):
        return self.backend.db
