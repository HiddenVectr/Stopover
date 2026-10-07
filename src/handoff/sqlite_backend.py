"""Single-owner SQLite backend for the local, single-workspace deployment."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .backend import Backend, Transaction
from .context import LOCAL_WORKSPACE
from .domain import DomainError, canonical, token_hash

# Row field -> column, for fields whose names differ.
COLUMNS = {"record_sha256": "record_hash", "project_key": "project", "target_client": "target",
           "source_client": "source", "token_hash": "token"}
JSON_FIELDS = ("record", "completion")


class OwnerLock:
    def __init__(self, path):
        self.file = open(path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                if not self.file.read(1):
                    self.file.write(b"0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("Another Handoff service already owns this data directory") from None

    def close(self):
        self.file.close()


def handoff_row(row):
    if row is None:
        return None
    result = {field: row[COLUMNS.get(field, field)] for field in (
        "id", "record_sha256", "title", "project_key", "target_client", "source_client", "status", "revision",
        "created", "updated", "generation", "holder", "token_hash", "expires")}
    result["record"] = json.loads(row["record"])
    result["completion"] = json.loads(row["completion"]) if row["completion"] else None
    return result


def memory_row(row):
    if row is None:
        return None
    return {"id": row["id"], "key": row["key"], "revision": row["revision"], "created": row["created"],
            "updated": row["updated"], "deleted": bool(row["deleted"]),
            "body": json.loads(row["body"]) if row["body"] is not None else None}


def translate(exc):
    code = getattr(exc, "sqlite_errorcode", None)
    if code in (5, 6) or (code is None and "locked" in str(exc).lower()):
        return DomainError("STORE_BUSY", "Store is busy; retry the identical operation")
    if code == 13 or (code is None and "full" in str(exc).lower()):
        return DomainError("STORE_FULL", "The local store is full")
    return DomainError("STORE_UNAVAILABLE", "The local store could not complete this request")


class SQLiteTransaction(Transaction):
    def __init__(self, db):
        self.db = db

    def one(self, sql, *values):
        return self.db.execute(sql, values).fetchone()

    # Handoffs
    def get_handoff(self, handoff_id):
        return handoff_row(self.one("SELECT * FROM handoffs WHERE id=?", handoff_id))

    def list_handoffs(self, *, status, project_key, target_client, q, after, limit, now):
        conditions, values = ["1=1"], []
        if status is not None:
            conditions.append("CASE WHEN status='claimed' AND expires<=? THEN 'available' ELSE status END = ?")
            values.extend([now, status])
        for value, column in ((project_key, "project"), (target_client, "target")):
            if value is not None:
                conditions.append(f"{column}=?")
                values.append(value)
        if q:
            conditions.append("(instr(lower(title),lower(?))>0 OR instr(lower(coalesce(project,'')),lower(?))>0 OR instr(id,?)>0)")
            values.extend([q] * 3)
        if after is not None:
            conditions.append("(created<? OR (created=? AND id<?))")
            values.extend([after[0], after[0], after[1]])
        rows = self.db.execute("SELECT * FROM handoffs WHERE " + " AND ".join(conditions) +
                               " ORDER BY created DESC,id DESC LIMIT ?", [*values, limit]).fetchall()
        return [handoff_row(row) for row in rows]

    def insert_handoff(self, row):
        self.db.execute("""INSERT INTO handoffs(id,record,record_hash,title,project,target,source,status,revision,created,updated)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (row["id"], canonical(row["record"]), row["record_sha256"], row["title"], row["project_key"],
                         row["target_client"], row["source_client"], row["status"], row["revision"], row["created"], row["updated"]))

    def update_handoff(self, handoff_id, **fields):
        columns = [f"{COLUMNS.get(field, field)}=?" for field in fields]
        values = [canonical(v) if field in JSON_FIELDS and v is not None else v for field, v in fields.items()]
        self.db.execute(f"UPDATE handoffs SET {','.join(columns)} WHERE id=?", (*values, handoff_id))

    def delete_handoff(self, handoff_id):
        for table, column in (("events", "handoff_id"), ("receipts", "handoff_id"), ("handoffs", "id")):
            self.db.execute(f"DELETE FROM {table} WHERE {column}=?", (handoff_id,))

    def count_handoffs(self):
        return self.one("SELECT count(*) FROM handoffs")[0]

    def completed_before(self, cutoff):
        return [r[0] for r in self.db.execute("SELECT id FROM handoffs WHERE status='completed' AND updated<?", (cutoff,))]

    def overview(self, now):
        rows = self.db.execute("SELECT CASE WHEN status='claimed' AND expires<=? THEN 'available' ELSE status END AS state,"
                               "count(*) AS count FROM handoffs GROUP BY state", (now,)).fetchall()
        counts = {"available": 0, "claimed": 0, "completed": 0}
        counts.update({row["state"]: row["count"] for row in rows})
        return {"counts": counts, "memories": self.count_memories(active_only=True),
                "projects": [r[0] for r in self.db.execute("SELECT DISTINCT project FROM handoffs WHERE project IS NOT NULL ORDER BY project")],
                "targets": [r[0] for r in self.db.execute("SELECT DISTINCT target FROM handoffs WHERE target IS NOT NULL ORDER BY target")]}

    # Events
    def add_event(self, handoff_id, event, at, revision, details):
        self.db.execute("INSERT INTO events(handoff_id,event,at,revision,details) VALUES (?,?,?,?,?)",
                        (handoff_id, event, at, revision, canonical(details)))

    def list_events(self, handoff_id, before, limit):
        rows = self.db.execute("SELECT * FROM events WHERE handoff_id=? AND sequence<? ORDER BY sequence DESC LIMIT ?",
                               (handoff_id, before or 9223372036854775807, limit)).fetchall()
        return [{"sequence": r["sequence"], "event": r["event"], "at": r["at"], "revision": r["revision"],
                 "details": json.loads(r["details"])} for r in rows]

    # Receipts
    def get_receipt(self, scope, tool, operation):
        table = "receipts" if scope == "handoff" else "memory_receipts"
        row = self.one(f"SELECT request_hash,result FROM {table} WHERE tool=? AND operation=?", tool, operation)
        return {"request_hash": row["request_hash"], "result": json.loads(row["result"])} if row else None

    def put_receipt(self, scope, tool, operation, request_hash, result, at, handoff_id=None):
        if scope == "handoff":
            self.db.execute("INSERT INTO receipts VALUES (?,?,?,?,?,?)", (tool, operation, request_hash, handoff_id, canonical(result), at))
        else:
            self.db.execute("INSERT INTO memory_receipts VALUES (?,?,?,?,?)", (tool, operation, request_hash, canonical(result), at))

    def prune_receipts(self, cutoff):
        self.db.execute("DELETE FROM receipts WHERE at<?", (cutoff,))
        self.db.execute("DELETE FROM memory_receipts WHERE at<?", (cutoff,))

    def count_receipts(self, scope):
        return self.one(f"SELECT count(*) FROM {'receipts' if scope == 'handoff' else 'memory_receipts'}")[0]

    def scrub_claim_tokens(self, handoff_id):
        self.db.execute("UPDATE receipts SET result=json_remove(result,'$.claim_token') "
                        "WHERE handoff_id=? AND tool IN ('handoff_claim','handoff_resume')", (handoff_id,))

    # Meta
    def get_meta(self, key):
        row = self.one("SELECT value FROM meta WHERE key=?", key)
        return row[0] if row else None

    def set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))

    # Memories
    def get_memory(self, key):
        return memory_row(self.one("SELECT * FROM personal_memories WHERE key=?", key))

    def save_memory(self, row):
        self.db.execute("""INSERT INTO personal_memories VALUES (?,?,?,?,?,?,?)
                           ON CONFLICT(key) DO UPDATE SET id=excluded.id,revision=excluded.revision,created=excluded.created,
                           updated=excluded.updated,deleted=excluded.deleted,body=excluded.body""",
                        (row["key"], row["id"], row["revision"], row["created"], row["updated"], int(row["deleted"]),
                         canonical(row["body"]) if row["body"] is not None else None))

    def list_memories(self, *, after, key, since_revision, include_deleted, category, q, limit):
        conditions, values = ["key > ?"], [after or ""]
        if key is not None:
            conditions.append("key=?")
            values.append(key)
        if since_revision is not None:
            conditions.append("revision>?")
            values.append(since_revision)
        elif not include_deleted:
            conditions.append("deleted=0")
        if category is not None:
            conditions.append("(deleted=1 OR json_extract(body,'$.category')=?)")
            values.append(category)
        if q:
            conditions.append("(deleted=1 OR instr(lower(key),lower(?))>0 OR instr(lower(json_extract(body,'$.content')),lower(?))>0)")
            values.extend([q, q])
        rows = self.db.execute("SELECT * FROM personal_memories WHERE " + " AND ".join(conditions) +
                               " ORDER BY key LIMIT ?", [*values, limit]).fetchall()
        return [memory_row(row) for row in rows]

    def count_memories(self, *, active_only=False):
        return self.one("SELECT count(*) FROM personal_memories" + (" WHERE deleted=0" if active_only else ""))[0]


class SQLiteBackend(Backend):
    def __init__(self, directory, clock=time.time):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.clock = clock
        self.lock = threading.RLock()
        self.owner = OwnerLock(self.directory / "owner.lock")
        try:
            self.db = sqlite3.connect(self.directory / "handoff.sqlite3", isolation_level=None, check_same_thread=False)
            os.chmod(self.directory / "handoff.sqlite3", 0o600)
            self.db.row_factory = sqlite3.Row
            self._create_schema()
            if self.db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite integrity check failed")
        except Exception:
            if hasattr(self, "db"):
                self.db.close()
            self.owner.close()
            raise

    def _create_schema(self):
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            PRAGMA synchronous=FULL;
            PRAGMA busy_timeout=5000;
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS handoffs (
              id TEXT PRIMARY KEY, record TEXT NOT NULL, record_hash TEXT NOT NULL,
              title TEXT NOT NULL, project TEXT, target TEXT, source TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('available','claimed','completed')),
              revision INTEGER NOT NULL CHECK(revision>0), created REAL NOT NULL, updated REAL NOT NULL,
              generation INTEGER NOT NULL DEFAULT 0, holder TEXT, token TEXT, expires REAL,
              completion TEXT,
              CHECK((status='claimed' AND token IS NOT NULL AND expires IS NOT NULL AND holder IS NOT NULL)
                 OR (status!='claimed' AND token IS NULL)),
              CHECK((status='completed') = (completion IS NOT NULL))
            );
            CREATE TABLE IF NOT EXISTS receipts (
              tool TEXT NOT NULL, operation TEXT NOT NULL, request_hash TEXT NOT NULL,
              handoff_id TEXT NOT NULL REFERENCES handoffs(id), result TEXT NOT NULL,
              at REAL NOT NULL DEFAULT 0,
              PRIMARY KEY(tool,operation)
            );
            CREATE TABLE IF NOT EXISTS events (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT,
              handoff_id TEXT NOT NULL REFERENCES handoffs(id), event TEXT NOT NULL,
              at REAL NOT NULL, revision INTEGER NOT NULL, details TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS handoff_order ON handoffs(created DESC,id DESC);
            CREATE INDEX IF NOT EXISTS handoff_filters ON handoffs(project,target,status);
            CREATE INDEX IF NOT EXISTS handoff_events ON events(handoff_id,sequence DESC);
        """)
        version = self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        if version and version[0] == "1":
            self._migrate_v1()
        elif version and version[0] != "2":
            raise RuntimeError("Unsupported database schema; restore a compatible Handoff version")
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('schema','2')")
        self.db.execute("CREATE INDEX IF NOT EXISTS receipt_age ON receipts(at)")
        # Personal memories are additive tables on schema 2.
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS personal_memories (
                key TEXT PRIMARY KEY, id TEXT NOT NULL UNIQUE,
                revision INTEGER NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                deleted INTEGER NOT NULL CHECK(deleted IN (0,1)), body TEXT
            );
            CREATE TABLE IF NOT EXISTS memory_receipts (
                tool TEXT NOT NULL, operation TEXT NOT NULL, request_hash TEXT NOT NULL,
                result TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY(tool,operation)
            );
            CREATE INDEX IF NOT EXISTS memory_revision ON personal_memories(revision);
            CREATE INDEX IF NOT EXISTS memory_receipt_age ON memory_receipts(at);
            INSERT OR IGNORE INTO meta VALUES ('memory_revision','0');
        """)

    def _migrate_v1(self):
        """v2 adds receipt timestamps and stores only hashes of claim tokens."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if "at" not in [c["name"] for c in self.db.execute("PRAGMA table_info(receipts)")]:
                self.db.execute("ALTER TABLE receipts ADD COLUMN at REAL NOT NULL DEFAULT 0")
            self.db.execute("UPDATE receipts SET at=?", (self.clock(),))
            for row in self.db.execute("SELECT id,token FROM handoffs WHERE token IS NOT NULL").fetchall():
                self.db.execute("UPDATE handoffs SET token=? WHERE id=?", (token_hash(row["token"]), row["id"]))
            self.db.execute("""UPDATE receipts SET result=json_remove(result,'$.claim_token') WHERE tool='handoff_claim'
                               AND handoff_id NOT IN (SELECT id FROM handoffs WHERE status='claimed')""")
            self.db.execute("UPDATE meta SET value='2' WHERE key='schema'")
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    @contextmanager
    def transaction(self, ctx, write=False):
        if ctx.workspace != LOCAL_WORKSPACE:
            raise DomainError("UNKNOWN_WORKSPACE", "This store serves only the local workspace")
        with self.lock:
            try:
                if write:
                    self.db.execute("BEGIN IMMEDIATE")
                yield SQLiteTransaction(self.db)
                if write:
                    self.db.execute("COMMIT")
            except sqlite3.Error as exc:
                self._rollback()
                raise translate(exc) from None
            except BaseException:
                self._rollback()
                raise

    def _rollback(self):
        if self.db.in_transaction:
            self.db.execute("ROLLBACK")

    def ping(self):
        with self.lock:
            self.db.execute("SELECT 1").fetchone()

    def close(self):
        with self.lock:
            self.db.close()
            self.owner.close()
