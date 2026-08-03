# plugins/goal_agent_plugin.py

import threading

from core.agent_base import Agent
from core.message import Message
from core.bus_rpc import call as bus_call


class GoalAgent(Agent):
    """
    Converts high-level 'goal' messages into concrete 'task' messages.

    Decomposition runs through the AgentAI bridge (agentai.complete),
    which routes to claude-fable-5 when ANTHROPIC_API_KEY is set, or
    falls back to local Ollama models (deepseek-r1/qwen/gemma4) with no
    key required at all. Falls back further to a naive heuristic split
    only if the bridge itself is unavailable or times out.
    """
    def __init__(self, name, bus):
        super().__init__(name)
        self.bus = bus
        bus.register_agent(name, self, subscriptions={'goal'})

    def handle(self, message_type, message):
        if message_type != 'goal':
            return
        payload = getattr(message, "payload", message)
        description = (payload.get('description', '') if isinstance(payload, dict) else '').strip()
        request_id = payload.get('request_id') if isinstance(payload, dict) else None
        threading.Thread(target=self._process, args=(description, request_id), daemon=True).start()

    def _process(self, description, request_id=None):
        steps = self._decompose(description)
        for step in steps:
            self.bus.dispatch('task', Message(type='task', payload={'description': step, 'request_id': request_id}))
        self.bus.dispatch('goal_result', Message(
            type='goal_result',
            payload={'goal': description, 'steps': steps, 'request_id': request_id},
        ))

    def _decompose(self, text: str):
        msg_type, reply = bus_call(
            self.bus,
            request_type="agentai.complete",
            payload={
                "agent_id": "goals",
                "prompt": f"Decompose this goal into 5 concrete, numbered steps:\n{text}",
                "system": "You are a planning assistant. Reply with a numbered list only.",
                "think": True,
            },
            reply_types={"agentai.result"},
            timeout=45,
        )
        if msg_type == "agentai.result":
            content = reply.get("result", "")
            steps = [
                line.split('.', 1)[1].strip()
                for line in content.splitlines()
                if line.strip() and line[0].isdigit() and '.' in line
            ]
            if steps:
                return steps
            print("[GoalAgent] bridge returned no parseable steps, using naive fallback")
        else:
            print(f"[GoalAgent] bridge unavailable/timed out ({msg_type}), using naive fallback")

        return self._naive_fallback(text)

    def _naive_fallback(self, text: str):
        if "path" in text and "->" in text:
            parts = [p.strip() for p in text.split("->")]
            if len(parts) == 2:
                a, b = parts
                return [f"Plan route from {a} to {b}", f"Summarize route from {a} to {b}"]
        return [text]


def register(bus):
    GoalAgent("goals", bus)
