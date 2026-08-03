# agents/echo_agent.py
import threading
from collections import Counter

from core.agent_base import Agent
from core.message import new_message


class ReflexAgent(Agent):
    """
    Rebroadcasts any non-echo message onto the 'echo' topic, preserving
    causal lineage (parent_cid), and keeps a running count of traffic by
    message type. Send a 'stats_request' message to get a 'stats_reply'
    back with the current counts.
    """

    SUPPRESSED = {"echo", "pulse", "agent_silent", "stats_request", "stats_reply"}

    def __init__(self, bus):
        super().__init__(name="echo_agent")
        self.bus = bus
        self._counts = Counter()
        self._lock = threading.Lock()
        bus.register(self)

    def handle(self, message_type, message):
        with self._lock:
            self._counts[message_type] += 1

        if message_type == "stats_request":
            self._reply_stats(message)
            return

        if message_type in self.SUPPRESSED:
            return

        payload = getattr(message, "payload", message)
        parent_cid = getattr(message, "cid", None)
        echoed = new_message(
            "echo",
            {"type": message_type, "payload": payload},
            parent_cid=parent_cid,
        )
        self.bus.dispatch(echoed.type, echoed)

    def _reply_stats(self, message):
        with self._lock:
            snapshot = dict(self._counts)
        reply = new_message("stats_reply", snapshot, parent_cid=getattr(message, "cid", None))
        self.bus.dispatch(reply.type, reply)
