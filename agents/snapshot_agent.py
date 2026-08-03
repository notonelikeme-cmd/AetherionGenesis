# agents/snapshot_agent.py
"""
SnapshotAgent — bus wrapper around core/snapshot.py.

Messages handled:
  snapshot.create   {label?}         -> snapshot.created  {path}
  snapshot.restore  {path}           -> snapshot.restored {path, restored}
  snapshot.list     {}               -> snapshot.list_result {snapshots}
"""
from core.agent_base import Agent
from core.message import new_message
from core import snapshot


class SnapshotAgent(Agent):
    def __init__(self, bus):
        super().__init__(name="snapshot")
        self.bus = bus
        bus.register(self, subscriptions={"snapshot.create", "snapshot.restore", "snapshot.list"})

    def handle(self, message_type, message):
        payload = getattr(message, "payload", message)
        if not isinstance(payload, dict):
            payload = {}
        request_id = payload.get("request_id")

        if message_type == "snapshot.create":
            path = snapshot.create(self.bus, label=payload.get("label"))
            print(f"[snapshot] created {path}")
            self.bus.dispatch("snapshot.created", new_message("snapshot.created", {"path": path, "request_id": request_id}))

        elif message_type == "snapshot.restore":
            path = payload.get("path")
            if not path:
                self.bus.dispatch("agentai.error", new_message("agentai.error", {"error": "path required", "request_id": request_id}))
                return
            result = snapshot.restore(self.bus, path)
            print(f"[snapshot] restored {result['restored']} from {path}")
            self.bus.dispatch("snapshot.restored", new_message("snapshot.restored", {**result, "request_id": request_id}))

        elif message_type == "snapshot.list":
            snaps = snapshot.list_snapshots()
            self.bus.dispatch("snapshot.list_result", new_message("snapshot.list_result", {"snapshots": snaps, "request_id": request_id}))
