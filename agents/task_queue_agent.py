# agents/task_queue_agent.py
"""
TaskQueueAgent — read-only bus query surface over core/task_store.py.

Messages handled:
  tasks.list   {cycle_id}       -> tasks.list_result   {cycle_id, tasks}
  tasks.board  {limit?}         -> tasks.board_result  {tasks}
"""
from core.agent_base import Agent
from core.message import new_message
from core import task_store

_DEFAULT_BOARD_LIMIT = 50
_MAX_BOARD_LIMIT = 500


def _bound_limit(raw, default=_DEFAULT_BOARD_LIMIT, maximum=_MAX_BOARD_LIMIT):
    """Coerce a caller-supplied limit to a positive int capped at
    `maximum`. SQLite treats `LIMIT -1` (and other non-positive values)
    as "no limit", so an unvalidated value here would let a caller force
    a full-table dump."""
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return default
    if limit <= 0:
        return default
    return min(limit, maximum)


class TaskQueueAgent(Agent):
    def __init__(self, bus):
        super().__init__(name="task_queue")
        self.bus = bus
        bus.register(self, subscriptions={"tasks.list", "tasks.board"})

    def handle(self, message_type, message):
        payload = getattr(message, "payload", message)
        if not isinstance(payload, dict):
            payload = {}
        request_id = payload.get("request_id")

        if message_type == "tasks.list":
            cycle_id = payload.get("cycle_id", "")
            tasks = task_store.for_cycle(cycle_id)
            self.bus.dispatch("tasks.list_result", new_message(
                "tasks.list_result", {"cycle_id": cycle_id, "tasks": tasks, "request_id": request_id},
            ))
        elif message_type == "tasks.board":
            limit = _bound_limit(payload.get("limit", _DEFAULT_BOARD_LIMIT))
            self.bus.dispatch("tasks.board_result", new_message(
                "tasks.board_result", {"tasks": task_store.board(limit), "request_id": request_id},
            ))
