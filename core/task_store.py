# core/task_store.py
"""
Durable, queryable task queue — the lite analog of Hermes's kanban
board. CycleAgent writes each step's lifecycle here (pending -> running
-> passed/failed -> retried) instead of only holding it in an
in-memory list that vanishes when the cycle finishes. Lets an operator
(or another agent) query "what's this cycle actually done" without
replaying the full audit log.
"""
import sqlite3
import os
import time
import json

DB_PATH = os.getenv("TASK_DB", "var/tasks.db")


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id TEXT,
            step_index INTEGER,
            description TEXT,
            status TEXT,
            output TEXT,
            verdict TEXT,
            created_at REAL,
            updated_at REAL,
            UNIQUE(cycle_id, step_index)
        )
    """)
    return c


def upsert(cycle_id: str, step_index: int, description: str, status: str, output=None, verdict=None):
    conn = _conn()
    now = time.time()
    output_json = json.dumps(output) if output is not None else None
    conn.execute("""
        INSERT INTO tasks(cycle_id, step_index, description, status, output, verdict, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cycle_id, step_index) DO UPDATE SET
            status = excluded.status,
            output = excluded.output,
            verdict = excluded.verdict,
            updated_at = excluded.updated_at
    """, (cycle_id, step_index, description, status, output_json, verdict, now, now))
    conn.commit()
    conn.close()


def for_cycle(cycle_id: str) -> list:
    conn = _conn()
    rows = conn.execute(
        "SELECT step_index, description, status, output, verdict, updated_at FROM tasks "
        "WHERE cycle_id = ? ORDER BY step_index",
        (cycle_id,),
    ).fetchall()
    conn.close()
    return [
        {
            "step_index": r[0], "description": r[1], "status": r[2],
            "output": json.loads(r[3]) if r[3] else None, "verdict": r[4], "updated_at": r[5],
        }
        for r in rows
    ]


def board(limit: int = 50) -> list:
    """All tasks across all cycles, most recently updated first — the kanban view."""
    conn = _conn()
    rows = conn.execute(
        "SELECT cycle_id, step_index, description, status, verdict, updated_at FROM tasks "
        "WHERE cycle_id != '__leads__' ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {"cycle_id": r[0], "step_index": r[1], "description": r[2], "status": r[3], "verdict": r[4], "updated_at": r[5]}
        for r in rows
    ]


# ---- Lead queue (unattended dispatcher pipeline) ---------------------------
# Leads are tasks not yet attached to a real cycle — a pool an operator
# (or an external feed, e.g. a spreadsheet sync) enqueues into, which
# the opt-in dispatcher agent claims from and turns into real loop_start
# dispatches.

_LEADS_CYCLE = "__leads__"


def enqueue_lead(description: str) -> int:
    conn = _conn()
    now = time.time()
    next_index = conn.execute(
        "SELECT COALESCE(MAX(step_index), -1) + 1 FROM tasks WHERE cycle_id = ?", (_LEADS_CYCLE,)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO tasks(cycle_id, step_index, description, status, created_at, updated_at) VALUES (?, ?, ?, 'queued', ?, ?)",
        (_LEADS_CYCLE, next_index, description, now, now),
    )
    conn.commit()
    conn.close()
    return next_index


def claim_next_lead():
    """Atomically claim the oldest queued lead. Returns None if none pending."""
    conn = _conn()
    with conn:
        row = conn.execute(
            "SELECT step_index, description FROM tasks WHERE cycle_id = ? AND status = 'queued' "
            "ORDER BY created_at LIMIT 1",
            (_LEADS_CYCLE,),
        ).fetchone()
        if row is None:
            conn.close()
            return None
        step_index, description = row
        conn.execute(
            "UPDATE tasks SET status = 'claimed', updated_at = ? WHERE cycle_id = ? AND step_index = ?",
            (time.time(), _LEADS_CYCLE, step_index),
        )
    conn.close()
    return {"step_index": step_index, "description": description}


def stats() -> dict:
    conn = _conn()
    rows = conn.execute("SELECT status, COUNT(*) FROM tasks WHERE cycle_id != ? GROUP BY status", (_LEADS_CYCLE,)).fetchall()
    by_status = {status: count for status, count in rows}

    pending = conn.execute(
        "SELECT MIN(created_at) FROM tasks WHERE cycle_id = ? AND status = 'queued'", (_LEADS_CYCLE,)
    ).fetchone()[0]
    leads_pending = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE cycle_id = ? AND status = 'queued'", (_LEADS_CYCLE,)
    ).fetchone()[0]
    conn.close()

    return {
        "by_status": by_status,
        "leads_pending": leads_pending,
        "oldest_pending_seconds": (time.time() - pending) if pending else None,
    }
