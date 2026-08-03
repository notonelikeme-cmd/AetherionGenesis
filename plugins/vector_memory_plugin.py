# plugins/vector_memory_plugin.py

import threading
import time

from core.agent_base import Agent
from core.vector_memory import VectorMemory
from core.bus_rpc import call as bus_call


class VectorMemoryAgent(Agent):
    """
    Computes embeddings for each message and stores them in a FAISS
    index. Runs through the AgentAI bridge (agentai.embed → Ollama's
    nomic-embed-text, 768 dims) instead of OpenAI's ada-002 (1536
    dims) — no API key required, fully local.

    Excludes high-frequency plumbing messages (ticks, pulses, echoes,
    bridge traffic) so it embeds meaningful content rather than
    flooding the local embed model with bus noise every second.
    """
    EXCLUDED = {
        "tick", "pulse", "agent_silent", "echo", "stats_request", "stats_reply",
        "agentai.complete", "agentai.result", "agentai.embed", "agentai.embed_result", "agentai.error",
    }

    def __init__(self, name, bus, dim=768):
        super().__init__(name)
        self.bus = bus
        self.vmemory = VectorMemory(dim)
        setattr(bus, 'vmemory', self.vmemory)
        bus.register_agent(name, self)

    def handle(self, message_type, payload):
        if message_type in self.EXCLUDED:
            return
        threading.Thread(target=self._embed_and_store, args=(message_type, payload), daemon=True).start()

    def _embed_and_store(self, message_type, payload):
        text = f"{message_type}:{payload}"
        msg_type, reply = bus_call(
            self.bus,
            request_type="agentai.embed",
            payload={"agent_id": "vector_memory", "text": text},
            reply_types={"agentai.embed_result"},
            timeout=15,
        )
        if msg_type != "agentai.embed_result" or not reply.get("vector"):
            print(f"[VectorMemoryAgent] embed unavailable/timed out ({msg_type}), skipping '{message_type}'")
            return

        self.vmemory.add(reply["vector"], {
            "type": message_type,
            "payload": payload,
            "timestamp": time.time(),
        })


def register(bus):
    VectorMemoryAgent("vector_memory", bus)
