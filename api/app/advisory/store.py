"""SQLite state for advisories and their audit log: api/data/state/tempest.db (git-ignored).

One connection per operation. `transaction()` takes the write lock up front (BEGIN IMMEDIATE),
so a status check and the update that follows can't interleave with another request's.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import API_DIR
from app.schemas import Advisory, AuditEvent

DB_PATH: Path = API_DIR / "data" / "state" / "tempest.db"  # tests point this at tmp_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS advisories (
    id TEXT PRIMARY KEY,
    block_id TEXT NOT NULL,
    timestep TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS advisories_status ON advisories (status);
CREATE INDEX IF NOT EXISTS advisories_block ON advisories (block_id, timestep);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    advisory_id TEXT,
    action TEXT NOT NULL,
    actor TEXT,
    at TEXT NOT NULL,
    details TEXT
);
CREATE INDEX IF NOT EXISTS audit_advisory ON audit_events (advisory_id);
"""


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    """Create the database and tables if missing (on app start, and before first use)."""
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    init()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def save(conn: sqlite3.Connection, advisory: Advisory) -> None:
    p = advisory.properties
    conn.execute(
        "INSERT OR REPLACE INTO advisories (id, block_id, timestep, status, created_at, data) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            p.id,
            p.block_id,
            p.timestep,
            p.status,
            p.created_at.isoformat(),
            advisory.model_dump_json(),
        ),
    )


def load(conn: sqlite3.Connection, advisory_id: str) -> Advisory | None:
    row = conn.execute("SELECT data FROM advisories WHERE id = ?", (advisory_id,)).fetchone()
    return Advisory.model_validate_json(row["data"]) if row else None


def get(advisory_id: str) -> Advisory | None:
    with transaction() as conn:
        return load(conn, advisory_id)


def list_advisories(
    status: str | None = None, block_id: str | None = None, timestep: str | None = None
) -> list[Advisory]:
    where, args = [], []
    for column, value in (("status", status), ("block_id", block_id), ("timestep", timestep)):
        if value is not None:
            where.append(f"{column} = ?")
            args.append(value)
    sql = "SELECT data FROM advisories"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, id"
    with transaction() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [Advisory.model_validate_json(r["data"]) for r in rows]


def audit(
    conn: sqlite3.Connection,
    advisory_id: str | None,
    action: str,
    actor: str | None = None,
    details: dict | str | None = None,
) -> None:
    if isinstance(details, dict):
        details = json.dumps(details, ensure_ascii=False)
    conn.execute(
        "INSERT INTO audit_events (advisory_id, action, actor, at, details) VALUES (?, ?, ?, ?, ?)",
        (advisory_id, action, actor, now().isoformat(), details),
    )


def events(advisory_id: str | None = None) -> list[AuditEvent]:
    sql = "SELECT id, advisory_id, action, actor, at, details FROM audit_events"
    args: tuple = ()
    if advisory_id is not None:
        sql += " WHERE advisory_id = ?"
        args = (advisory_id,)
    with transaction() as conn:
        rows = conn.execute(sql + " ORDER BY id", args).fetchall()
    return [AuditEvent.model_validate(dict(r)) for r in rows]
