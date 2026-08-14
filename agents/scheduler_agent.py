# agents/scheduler_agent.py
import threading
import time

from core.agent_base import Agent
from core.message import new_message


class ChronoAgent(Agent):
    """
    Runs any number of independently-named interval schedules instead of
    a single fixed tick. Add one with a 'schedule_add' message
    ({'name', 'interval'}), remove with 'schedule_cancel' ({'name'}).
    Emits a 'tick' message per firing, tagged with the schedule name.
    """

    def __init__(self, bus, default_interval=5):
        super().__init__(name="scheduler_agent")
        self.bus = bus
        self._schedules = {}  # name -> {"interval": n, "stop": Event, "count": 0}
        self._lock = threading.Lock()
        bus.register(self)
        self.add_schedule("default", default_interval)

    def add_schedule(self, name, interval):
        if not isinstance(interval, (int, float)) or interval <= 0:
            print(f"[scheduler_agent] rejecting schedule '{name}': interval must be > 0 (got {interval!r})")
            return
        with self._lock:
            if name in self._schedules:
                return
            self._schedules[name] = {"interval": interval, "stop": threading.Event(), "count": 0}
        threading.Thread(target=self._run, args=(name,), daemon=True).start()

    def cancel_schedule(self, name):
        with self._lock:
            sched = self._schedules.pop(name, None)
        if sched:
            sched["stop"].set()

    def _run(self, name):
        while True:
            with self._lock:
                sched = self._schedules.get(name)
            if sched is None or sched["stop"].is_set():
                return
            time.sleep(sched["interval"])
            with self._lock:
                sched = self._schedules.get(name)
                if sched is None:
                    return
                sched["count"] += 1
                count = sched["count"]
            msg = new_message("tick", {"schedule": name, "count": count, "timestamp": time.time()})
            self.bus.dispatch(msg.type, msg)

    def handle(self, message_type, message):
        payload = getattr(message, "payload", message)
        if not isinstance(payload, dict):
            return
        if message_type == "schedule_add":
            self.add_schedule(payload.get("name", "unnamed"), payload.get("interval", 5))
        elif message_type == "schedule_cancel":
            self.cancel_schedule(payload.get("name"))
