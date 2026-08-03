# core/audit_store.py
import sqlite3, json, os

DB_PATH = os.getenv("AUDIT_DB", "var/audit.db")

def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("""
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            cid TEXT,
            parent_cid TEXT,
            type TEXT,
            payload TEXT,
            metadata TEXT
        )
    """)
    return c

class _MsgEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, '__dataclass_fields__'):
            return obj.__dict__
        return str(obj)

def append(message):
    conn = _conn()
    conn.execute(
        "INSERT INTO audit(ts, cid, parent_cid, type, payload, metadata) VALUES (?,?,?,?,?,?)",
        (
            message.ts,
            message.cid,
            message.parent_cid,
            message.type,
            json.dumps(message.payload, cls=_MsgEncoder),
            json.dumps(message.metadata or {}, cls=_MsgEncoder),
        ),
    )
    conn.commit()
    conn.close()
