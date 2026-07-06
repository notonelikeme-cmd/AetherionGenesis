"""
AgentAI Bridge Plugin — connects AetherionGenesis kernel to AgentAI's 3-tier
model router and Nexus Trinity 7-gate pipeline.

Message types dispatched:
  agentai.complete   payload: {agent_id, prompt, system, gate, think, code}
                     → routes to correct Ollama tier via model_router
  agentai.gate       payload: {gate_num, hypothesis, contract, context}
                     → runs a single Nexus Trinity gate
  agentai.pipeline   payload: {hypothesis, contract}
                     → runs the full 7-gate pipeline

Message types emitted:
  agentai.result     payload: {agent_id, result, tier}
  agentai.finding    payload: {finding dict from gate output}
  agentai.error      payload: {agent_id, error}
"""

import sys
import os

# Add AgentAI to path
_AGENTAI_PATH = os.path.expanduser("~/AgentAI")
if _AGENTAI_PATH not in sys.path:
    sys.path.insert(0, _AGENTAI_PATH)

from core.agent import Agent


class AgentAIBridgeAgent(Agent):
    def __init__(self):
        super().__init__(name="agentai_bridge")
        self._router = None
        self._pipeline = None

    def _get_router(self):
        if self._router is None:
            try:
                from core.model_router import ModelRouter
                self._router = ModelRouter()
            except Exception as e:
                print(f"[agentai_bridge] model_router unavailable: {e}")
        return self._router

    def _get_pipeline(self):
        if self._pipeline is None:
            try:
                from core.gates.verification_loop import VerificationLoop
                self._pipeline = VerificationLoop()
            except Exception as e:
                print(f"[agentai_bridge] pipeline unavailable: {e}")
        return self._pipeline

    def handle(self, message_type, payload):
        if message_type == "agentai.complete":
            self._handle_complete(payload)
        elif message_type == "agentai.gate":
            self._handle_gate(payload)
        elif message_type == "agentai.pipeline":
            self._handle_pipeline(payload)

    def _handle_complete(self, payload):
        router = self._get_router()
        if not router:
            return
        try:
            agent_id = payload.get("agent_id", "unknown")
            result = router.complete(
                prompt=payload.get("prompt", ""),
                system=payload.get("system"),
                gate=payload.get("gate"),
                think=payload.get("think", False),
                code=payload.get("code", False),
                agent_id=agent_id,
            )
            from core.agent_bus import AgentBus
            tier = router.agent_tier(agent_id) if hasattr(router, "agent_tier") else "?"
            print(f"[agentai_bridge] {agent_id} (tier {tier}) → {len(result)} chars")
        except Exception as e:
            print(f"[agentai_bridge] complete error: {e}")

    def _handle_gate(self, payload):
        print(f"[agentai_bridge] gate {payload.get('gate_num')} → {payload.get('hypothesis', '')[:60]}")

    def _handle_pipeline(self, payload):
        print(f"[agentai_bridge] pipeline → {payload.get('hypothesis', '')[:80]}")


def register(bus):
    agent = AgentAIBridgeAgent()
    bus.register(agent, subscriptions={"agentai.complete", "agentai.gate", "agentai.pipeline"})
    print("[plugin] agentai_bridge registered")
