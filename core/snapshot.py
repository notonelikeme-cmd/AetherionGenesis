# core/snapshot.py
"""
Snapshot/restore — the analog of Hermes's `/snapshot`. Bundles the
graph, audit ledger, goal store, and task store into one versioned,
restorable directory under var/snapshots/<timestamp>[_label]/.

(A plain directory rather than a literal tarball — same practical
effect: portable, timestamped, restorable — with less code and no new
dependency.)
"""
import json
import os
import shutil
import sqlite3
import time

from core import audit_store, goal_store, task_store

SNAPSHOT_ROOT = os.getenv("SNAPSHOT_ROOT", "var/snapshots")


def _backup_sqlite(src_path, dst_path):
    """Safe copy of a live sqlite db via the backup API (works even if
    another connection is mid-write, unlike a raw file copy)."""
    if not os.path.exists(src_path):
        return
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()


def capture_into(bus, path) -> list:
    """Core capture logic, shared by snapshot.create() and branch.fork().
    Writes graph/vmemory/audit/goals/tasks state into `path`. Returns
    the list of what was captured."""
    os.makedirs(path, exist_ok=True)
    captured = []

    graph = getattr(bus, "graph", None)
    if graph is not None:
        with open(os.path.join(path, "graph.json"), "w") as f:
            json.dump({
                "nodes": list(graph.graph.nodes(data=True)),
                "edges": list(graph.graph.edges(data=True)),
            }, f, indent=2)
        captured.append("graph")

    vmemory = getattr(bus, "vmemory", None)
    if vmemory is not None:
        with open(os.path.join(path, "vmemory_meta.json"), "w") as f:
            json.dump(vmemory.metadata, f, indent=2, default=str)
        captured.append("vmemory_meta")

    _backup_sqlite(audit_store.DB_PATH, os.path.join(path, "audit.db"))
    _backup_sqlite(goal_store.DB_PATH, os.path.join(path, "goals.db"))
    _backup_sqlite(task_store.DB_PATH, os.path.join(path, "tasks.db"))
    captured += [n for n in ("audit.db", "goals.db", "tasks.db") if os.path.exists(os.path.join(path, n))]

    return captured


def apply_from(bus, path) -> list:
    """Core restore logic, shared by snapshot.restore() and
    branch.switch(). NOTE: sqlite stores are file-swapped — safest run
    right after boot (no other writer mid-transaction)."""
    restored = []

    graph_path = os.path.join(path, "graph.json")
    graph = getattr(bus, "graph", None)
    if graph is not None and os.path.exists(graph_path):
        with open(graph_path) as f:
            data = json.load(f)
        graph.graph.clear()
        for node_id, attrs in data.get("nodes", []):
            graph.graph.add_node(node_id, **attrs)
        for src, dst, attrs in data.get("edges", []):
            graph.graph.add_edge(src, dst, **attrs)
        restored.append("graph")

    for name, db_path in (("audit.db", audit_store.DB_PATH), ("goals.db", goal_store.DB_PATH), ("tasks.db", task_store.DB_PATH)):
        src = os.path.join(path, name)
        if os.path.exists(src):
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            shutil.copyfile(src, db_path)
            restored.append(name)

    return restored


def create(bus, label=None) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dirname = f"{stamp}_{label}" if label else stamp
    path = os.path.join(SNAPSHOT_ROOT, dirname)
    capture_into(bus, path)

    with open(os.path.join(path, "manifest.json"), "w") as f:
        json.dump({"created_at": time.time(), "label": label}, f, indent=2)

    return path


def restore(bus, path) -> dict:
    return {"path": path, "restored": apply_from(bus, path)}


def list_snapshots() -> list:
    if not os.path.isdir(SNAPSHOT_ROOT):
        return []
    out = []
    for name in sorted(os.listdir(SNAPSHOT_ROOT)):
        manifest_path = os.path.join(SNAPSHOT_ROOT, name, "manifest.json")
        manifest = {}
        if os.path.exists(manifest_path):
            with open(manifest_path) as f:
                manifest = json.load(f)
        out.append({"name": name, **manifest})
    return out
