# agents/dispatcher_agent.py
"""
DispatcherAgent — claims queued leads (core.task_store lead pool) and
turns them into real loop_start cycles, unattended.

Off by default — set DISPATCH_ENABLED=1 to run it. Auto-starting real
LLM-cost-incurring audit cycles without a human in the loop is exactly
the kind of thing that should require explicit opt-in, not be silently
on. Polls at most once per DISPATCH_INTERVAL seconds (default 60) and
claims at most one lead per poll, to avoid flooding the local model
router with concurrent cycles.

Enqueue a lead: dispatch 'leads.enqueue' {description}, or POST
/leads on the webapi (requires a leads:write capability token).
"""
import os
import threading
import time

from core.agent_base import Agent
from core.message import new_message
from core import task_store


class DispatcherAgent(Agent):
    def __init__(self, bus, interval=None):
        super().__init__(name="dispatcher")
        self.bus = bus
        self.interval = interval or int(os.environ.get("DISPATCH_INTERVAL", 60))
        bus.register(self, subscriptions={"leads.enqueue"})

        if os.environ.get("DISPATCH_ENABLED"):
            threading.Thread(target=self._run, daemon=True).start()
            print(f"[dispatcher] enabled, polling every {self.interval}s")
        else:
            print("[dispatcher] disabled (set DISPATCH_ENABLED=1 to enable unattended lead pickup)")

    def handle(self, message_type, message):
        if message_type != "leads.enqueue":
            return
        payload = getattr(message, "payload", message)
        description = payload.get("description", "") if isinstance(payload, dict) else ""
        if not description:
            return
        step_index = task_store.enqueue_lead(description)
        print(f"[dispatcher] lead queued (#{step_index}): {description}")
        self.bus.dispatch("leads.queued", new_message("leads.queued", {"step_index": step_index, "description": description}))

    def _run(self):
        while True:
            time.sleep(self.interval)
            lead = task_store.claim_next_lead()
            if lead is None:
                continue
            print(f"[dispatcher] claimed lead #{lead['step_index']}, dispatching: {lead['description']}")
            self.bus.dispatch("loop_start", new_message("loop_start", {
                "goal": lead["description"], "continuous": False,
            }))
