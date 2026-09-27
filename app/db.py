import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  aliases TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS groups (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  invite_code TEXT NOT NULL UNIQUE,
  origin TEXT NOT NULL DEFAULT 'app',
  kind TEXT,
  blurb TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
  group_id INTEGER NOT NULL REFERENCES groups(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  role TEXT NOT NULL CHECK (role IN ('president','treasurer','member')),
  PRIMARY KEY (group_id, user_id)
);
CREATE TABLE IF NOT EXISTS obligations (
  id INTEGER PRIMARY KEY,
  group_id INTEGER NOT NULL REFERENCES groups(id),
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  amount_due_kobo INTEGER NOT NULL CHECK (amount_due_kobo > 0),
  due_date TEXT NOT NULL,
  series TEXT
);
CREATE TABLE IF NOT EXISTS entries (
  id INTEGER PRIMARY KEY,
  group_id INTEGER NOT NULL REFERENCES groups(id),
  direction TEXT NOT NULL CHECK (direction IN ('in','out')),
  obligation_id INTEGER REFERENCES obligations(id),
  member_id INTEGER REFERENCES users(id),
  claimed_name TEXT,
  counterparty TEXT,
  description TEXT,
  amount_kobo INTEGER NOT NULL CHECK (amount_kobo > 0),
  occurred_on TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('app','whatsapp_import','seed')),
  status TEXT NOT NULL CHECK (status IN ('reported','documented','needs_review','verified','rejected','requested','approved','declined')),
  reasons TEXT NOT NULL DEFAULT '[]',
  proof_path TEXT,
  proof_sha256 TEXT,
  proof_reference TEXT,
  extraction TEXT,
  source_text TEXT,
  created_by INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL,
  decided_by INTEGER REFERENCES users(id),
  decided_at TEXT,
  decision_note TEXT,
  approved_by INTEGER REFERENCES users(id),
  approved_at TEXT,
  approval_note TEXT,
  receipt_by INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS ix_entries_group ON entries(group_id);
CREATE TABLE IF NOT EXISTS ledger_events (
  id INTEGER PRIMARY KEY,
  group_id INTEGER NOT NULL REFERENCES groups(id),
  entry_id INTEGER,
  actor_id INTEGER,
  action TEXT NOT NULL,
  detail TEXT NOT NULL,
  created_at TEXT NOT NULL,
  prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_group ON ledger_events(group_id, id);
"""

GENESIS = "0" * 64


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path=None) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def tx(path=None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _event_hash(prev_hash: str, body: dict) -> str:
    payload = prev_hash + json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def append_event(conn, group_id: int, action: str, detail: dict,
                 entry_id: int | None = None, actor_id: int | None = None,
                 created_at: str | None = None) -> None:
    """Append-only and hash-chained per group: editing any past event breaks the chain."""
    row = conn.execute(
        "SELECT hash FROM ledger_events WHERE group_id=? ORDER BY id DESC LIMIT 1", (group_id,)
    ).fetchone()
    prev = row["hash"] if row else GENESIS
    created_at = created_at or now_iso()
    body = {"group_id": group_id, "entry_id": entry_id, "actor_id": actor_id,
            "action": action, "detail": detail, "created_at": created_at}
    conn.execute(
        "INSERT INTO ledger_events(group_id,entry_id,actor_id,action,detail,created_at,prev_hash,hash)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (group_id, entry_id, actor_id, action, json.dumps(detail, sort_keys=True),
         created_at, prev, _event_hash(prev, body)),
    )


def verify_chain(conn, group_id: int) -> dict:
    prev = GENESIS
    count = 0
    for r in conn.execute("SELECT * FROM ledger_events WHERE group_id=? ORDER BY id", (group_id,)):
        body = {"group_id": r["group_id"], "entry_id": r["entry_id"], "actor_id": r["actor_id"],
                "action": r["action"], "detail": json.loads(r["detail"]), "created_at": r["created_at"]}
        if r["prev_hash"] != prev or _event_hash(prev, body) != r["hash"]:
            return {"intact": False, "events": count, "broken_at_event": r["id"]}
        prev = r["hash"]
        count += 1
    return {"intact": True, "events": count, "head": prev}
