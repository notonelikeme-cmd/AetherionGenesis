# agents/heartbeat_agent.py
import threading
import time

from core.agent_base import Agent
from core.message import new_message


class PulseMonitor(Agent):
    """
    Emits a periodic pulse on the bus and tracks the last time each
    message type was observed. If a type goes quiet longer than
    `silence_after` seconds, emits an 'agent_silent' alert so other
    agents (or an operator watching the audit trail) can react.

    Messages carry no sender identity in this bus, so liveness is
    tracked per message *type* rather than per agent instance.
    """

    def __init__(self, bus, interval=5, silence_after=30):
        super().__init__(name="heartbeat_agent")
        self.bus = bus
        self.interval = interval
        self.silence_after = silence_after
        self._last_seen = {}
        self._lock = threading.Lock()
        bus.register(self)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            self._emit_pulse()
            self._check_silence()
            time.sleep(self.interval)

    def _emit_pulse(self):
        with self._lock:
            tracked = len(self._last_seen)
        msg = new_message("pulse", {"types_tracked": tracked})
        self.bus.dispatch(msg.type, msg)

    def _check_silence(self):
        now = time.time()
        with self._lock:
            stale = [
                (mtype, now - last)
                for mtype, last in self._last_seen.items()
                if now - last > self.silence_after
            ]
        for mtype, age in stale:
            alert = new_message("agent_silent", {"message_type": mtype, "silent_for": age})
            self.bus.dispatch(alert.type, alert)

    def handle(self, message_type, message):
        if message_type in ("pulse", "agent_silent"):
            return
        with self._lock:
            self._last_seen[message_type] = time.time()
