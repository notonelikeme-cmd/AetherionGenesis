# agents/logging_agent.py
import time

from core.agent_base import Agent
from core.message import new_message
from core import audit_store


class AuditTrailAgent(Agent):
    """
    Persists every message crossing the bus into the sqlite audit store
    (core.audit_store) and prints a structured, timestamped console
    line. First real consumer of audit_store, which previously had no
    caller anywhere in the codebase.
    """

    def __init__(self, bus, verbose=True):
        super().__init__(name="logging_agent")
        self.bus = bus
        self.verbose = verbose
        bus.register(self)

    def handle(self, message_type, message):
        if not hasattr(message, "cid"):
            message = new_message(message_type, message)

        try:
            audit_store.append(message)
        except Exception as e:
            print(f"[audit_trail] failed to persist '{message_type}': {e}")

        if self.verbose:
            stamp = time.strftime("%H:%M:%S", time.localtime(message.ts or time.time()))
            print(f"[audit_trail {stamp}] {message_type} -> {message.payload}")
