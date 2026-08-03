# agents/branch_agent.py
"""
BranchAgent — bus wrapper around core/branch.py.

Messages handled:
  branch.fork    {name}         -> branch.forked   {name, path, captured}
  branch.switch  {name}         -> branch.switched  {name, restored}
  branch.merge   {name}         -> branch.merged    {merged_from, nodes_before, nodes_after, nodes_added}
  branch.list    {}             -> branch.list_result {branches}
"""
from core.agent_base import Agent
from core.message import new_message
from core import branch


class BranchAgent(Agent):
    def __init__(self, bus):
        super().__init__(name="branch")
        self.bus = bus
        bus.register(self, subscriptions={"branch.fork", "branch.switch", "branch.merge", "branch.list"})

    def handle(self, message_type, message):
        payload = getattr(message, "payload", message)
        if not isinstance(payload, dict):
            payload = {}
        request_id = payload.get("request_id")
        name = payload.get("name")

        try:
            if message_type == "branch.fork":
                result = branch.fork(self.bus, name)
                print(f"[branch] forked '{name}' -> {result['path']}")
                self.bus.dispatch("branch.forked", new_message("branch.forked", {**result, "request_id": request_id}))

            elif message_type == "branch.switch":
                result = branch.switch(self.bus, name)
                print(f"[branch] switched to '{name}' ({result['restored']})")
                self.bus.dispatch("branch.switched", new_message("branch.switched", {**result, "request_id": request_id}))

            elif message_type == "branch.merge":
                result = branch.merge(self.bus, name)
                print(f"[branch] merged '{name}': +{result['nodes_added']} nodes")
                self.bus.dispatch("branch.merged", new_message("branch.merged", {**result, "request_id": request_id}))

            elif message_type == "branch.list":
                self.bus.dispatch("branch.list_result", new_message(
                    "branch.list_result", {"branches": branch.list_branches(), "request_id": request_id},
                ))
        except Exception as e:
            print(f"[branch] error on {message_type}: {e}")
            self.bus.dispatch("agentai.error", new_message("agentai.error", {"error": str(e), "request_id": request_id}))
