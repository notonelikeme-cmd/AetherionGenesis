"""
AgentAI Bridge Plugin — connects AetherionGenesis kernel to AgentAI's 3-tier
model router. Exposes the router as a bus-addressable service so any agent
can request LLM completions without importing model_router directly.

Bus messages handled:
  agentai.complete  {agent_id, prompt, system, gate, think, code, max_tokens}
                    → routes via model_router.complete(), emits agentai.result

Bus messages emitted:
  agentai.result  {agent_id, result, tier, route}
  agentai.error   {agent_id, error}
"""

import sys, os, threading

_AGENTAI_PATH = os.path.expanduser("~/AgentAI")
if _AGENTAI_PATH not in sys.path:
    sys.path.insert(0, _AGENTAI_PATH)

from core.agent import Agent


class AgentAIBridgeAgent(Agent):
    def __init__(self, bus):
        super().__init__(name="agentai_bridge")
        self._bus    = bus
        self._router = None

    def _get_router(self):
        if self._router is None:
            try:
                from core.model_router import ModelRouter, agent_tier
                self._router = ModelRouter()
                self._agent_tier = agent_tier
            except Exception as e:
                print(f"[agentai_bridge] model_router unavailable: {e}")
        return self._router

    def handle(self, message_type, payload):
        if message_type == "agentai.complete":
            # Run in thread — model calls block
            threading.Thread(target=self._handle_complete, args=(payload,), daemon=True).start()

    def _handle_complete(self, payload):
        router = self._get_router()
        if not router:
            self._bus.dispatch("agentai.error", {
                "agent_id": payload.get("agent_id", "?"),
                "error": "model_router not available",
            })
            return

        agent_id   = payload.get("agent_id", "")
        prompt     = payload.get("prompt", "")
        system     = payload.get("system")
        gate       = payload.get("gate")
        think      = payload.get("think", False)
        code       = payload.get("code", False)
        max_tokens = payload.get("max_tokens", 4096)

        try:
            result = router.complete(
                prompt=prompt,
                system=system,
                gate=gate,
                max_tokens=max_tokens,
                think=think,
                code=code,
                agent_id=agent_id or None,
            )
            tier  = self._agent_tier(agent_id) if agent_id and hasattr(self, "_agent_tier") else "?"
            route = getattr(router, "_last_route", "?")
            print(f"[agentai_bridge] {agent_id or 'anon'} tier={tier} route={route} → {len(result)} chars")
            self._bus.dispatch("agentai.result", {
                "agent_id": agent_id,
                "result":   result,
                "tier":     tier,
                "route":    route,
            })
        except Exception as e:
            print(f"[agentai_bridge] complete error ({agent_id}): {e}")
            self._bus.dispatch("agentai.error", {"agent_id": agent_id, "error": str(e)})


def register(bus):
    agent = AgentAIBridgeAgent(bus)
    bus.register(agent, subscriptions={"agentai.complete"})
    print("[plugin] agentai_bridge registered")
