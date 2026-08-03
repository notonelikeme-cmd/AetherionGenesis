# core/goal_store.py
"""
Durable standing-task storage — the analog of Hermes's `/goal`: a task
the system keeps working on across turns/restarts until it's done,
instead of a one-shot dispatch that's forgotten once the process exits.

Status lifecycle: active -> done
                          -> needs_attention (single-shot cycle had failures)
"""
import sqlite3
import os
import time

DB_PATH = os.getenv("GOAL_DB", "var/goals.db")


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("""
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT,
            status TEXT,
            continuous INTEGER,
            latest_cycle_id TEXT,
            created_at REAL,
            updated_at REAL
        )
    """)
    return c


def create(description: str, continuous: bool = False) -> int:
    conn = _conn()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO goals(description, status, continuous, latest_cycle_id, created_at, updated_at) "
        "VALUES (?, 'active', ?, NULL, ?, ?)",
        (description, int(continuous), now, now),
    )
    conn.commit()
    goal_id = cur.lastrowid
    conn.close()
    return goal_id


def update(goal_id: int, status: str, latest_cycle_id: str = None):
    conn = _conn()
    conn.execute(
        "UPDATE goals SET status = ?, latest_cycle_id = COALESCE(?, latest_cycle_id), updated_at = ? WHERE id = ?",
        (status, latest_cycle_id, time.time(), goal_id),
    )
    conn.commit()
    conn.close()


def get_active() -> list:
    """Goals still in play — active (mid continuous run) or needs_attention (had failures, awaiting resume)."""
    conn = _conn()
    rows = conn.execute(
        "SELECT id, description, status, continuous, latest_cycle_id FROM goals "
        "WHERE status IN ('active', 'needs_attention') ORDER BY created_at"
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "description": r[1], "status": r[2], "continuous": bool(r[3]), "latest_cycle_id": r[4]}
        for r in rows
    ]


def get_all() -> list:
    conn = _conn()
    rows = conn.execute(
        "SELECT id, description, status, continuous, latest_cycle_id, created_at, updated_at FROM goals ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "description": r[1], "status": r[2], "continuous": bool(r[3]),
            "latest_cycle_id": r[4], "created_at": r[5], "updated_at": r[6],
        }
        for r in rows
    ]
