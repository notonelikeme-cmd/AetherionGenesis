# core/branch.py
"""
Session forking — the analog of Hermes's `/branch`. Git-branch
semantics on top of core/snapshot.py's capture/apply machinery:

  fork(name)    — save current live state as a named branch (like
                  `git branch <name>` — does NOT switch to it)
  switch(name)  — load a named branch's state into the live bus (like
                  `git checkout <name>`)
  merge(name)   — union a branch's graph into the live graph; on
                  node/edge conflicts the branch's version wins
  list_branches()

Use cases: what-if exploration (fork before a risky change, switch
back if it goes wrong), A/B audit strategies on the same target,
per-engagement isolation, and named timeline snapshots you return to
months later.
"""
import json
import os
import time

import networkx as nx

from core import snapshot

BRANCH_ROOT = os.getenv("BRANCH_ROOT", "var/branches")
_CURRENT_FILE = os.path.join(BRANCH_ROOT, ".current")


def _contain(root: str, path: str) -> str:
    """Resolve `path` and ensure it stays within `root`; raise if a
    caller-supplied name (e.g. an absolute path or one containing '..')
    would let it escape root."""
    root_abs = os.path.abspath(root)
    path_abs = os.path.abspath(path)
    if path_abs != root_abs and not path_abs.startswith(root_abs + os.sep):
        raise ValueError(f"invalid branch name: escapes {root!r}")
    return path_abs


def current() -> str:
    if os.path.exists(_CURRENT_FILE):
        with open(_CURRENT_FILE) as f:
            return f.read().strip()
    return None


def _set_current(name):
    os.makedirs(BRANCH_ROOT, exist_ok=True)
    with open(_CURRENT_FILE, "w") as f:
        f.write(name)


def fork(bus, name) -> dict:
    path = _contain(BRANCH_ROOT, os.path.join(BRANCH_ROOT, name or ""))
    captured = snapshot.capture_into(bus, path)
    with open(os.path.join(path, "manifest.json"), "w") as f:
        json.dump({"created_at": time.time(), "name": name, "forked_from": current()}, f, indent=2)
    return {"name": name, "path": path, "captured": captured}


def switch(bus, name) -> dict:
    path = _contain(BRANCH_ROOT, os.path.join(BRANCH_ROOT, name or ""))
    if not os.path.isdir(path):
        raise FileNotFoundError(f"no such branch: {name}")
    restored = snapshot.apply_from(bus, path)
    _set_current(name)
    return {"name": name, "restored": restored}


def merge(bus, name) -> dict:
    """Union `name`'s graph into the live graph. Branch's attributes
    win on node/edge conflicts."""
    path = _contain(BRANCH_ROOT, os.path.join(BRANCH_ROOT, name or ""))
    graph_path = os.path.join(path, "graph.json")
    if not os.path.exists(graph_path):
        raise FileNotFoundError(f"branch {name} has no captured graph")

    with open(graph_path) as f:
        data = json.load(f)
    branch_graph = nx.DiGraph()
    for node_id, attrs in data.get("nodes", []):
        branch_graph.add_node(node_id, **attrs)
    for src, dst, attrs in data.get("edges", []):
        branch_graph.add_edge(src, dst, **attrs)

    live = bus.graph.graph
    merged = nx.compose(live, branch_graph)
    before = live.number_of_nodes()
    live.clear()
    live.update(merged)

    return {
        "merged_from": name,
        "nodes_before": before,
        "nodes_after": live.number_of_nodes(),
        "nodes_added": live.number_of_nodes() - before,
    }


def list_branches() -> list:
    if not os.path.isdir(BRANCH_ROOT):
        return []
    cur = current()
    out = []
    for name in sorted(os.listdir(BRANCH_ROOT)):
        if name.startswith('.'):
            continue
        manifest_path = os.path.join(BRANCH_ROOT, name, "manifest.json")
        manifest = {}
        if os.path.exists(manifest_path):
            with open(manifest_path) as f:
                manifest = json.load(f)
        out.append({"name": name, "current": name == cur, **manifest})
    return out
