"""
AgentAI Bridge Plugin — connects AetherionGenesis kernel to AgentAI's 3-tier
model router. Exposes the router as a bus-addressable service so any agent
can request LLM completions or embeddings without importing model_router
directly, and without any agent needing its own OpenAI (or other) client.

Bus messages handled:
  agentai.complete  {agent_id, prompt, system, gate, think, code, max_tokens, fast}
                    → fast=True: priority lane, always local gemma4, no
                      cloud attempt, no reasoning mode (model_router.complete_fast()).
                      Otherwise routes via model_router.complete(), emits agentai.result
  agentai.embed     {agent_id, text}
                    → routes via model_router.embed(), emits agentai.embed_result

Bus messages emitted:
  agentai.result        {agent_id, result, tier, route}
  agentai.embed_result  {agent_id, vector}
  agentai.error         {agent_id, error}
"""

import threading

from core.agent_base import Agent
from core.agentai_loader import load as load_agentai


class AgentAIBridgeAgent(Agent):
    def __init__(self, bus):
        super().__init__(name="agentai_bridge")
        self._bus    = bus
        self._router = None

    def _get_router(self):
        if self._router is None:
            try:
                model_router = load_agentai("core.model_router")
                self._router = model_router.ModelRouter()
                self._agent_tier = model_router.agent_tier
            except Exception as e:
                print(f"[agentai_bridge] model_router unavailable: {e}")
        return self._router

    def handle(self, message_type, payload):
        if message_type == "agentai.complete":
            # Run in thread — model calls block
            threading.Thread(target=self._handle_complete, args=(payload,), daemon=True).start()
        elif message_type == "agentai.embed":
            threading.Thread(target=self._handle_embed, args=(payload,), daemon=True).start()

    def _handle_complete(self, payload):
        request_id = payload.get("request_id")
        router = self._get_router()
        if not router:
            self._bus.dispatch("agentai.error", {
                "agent_id": payload.get("agent_id", "?"),
                "request_id": request_id,
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
        fast       = payload.get("fast", False)

        try:
            if fast:
                result = router.complete_fast(prompt=prompt, system=system)
            else:
                result = router.complete(
                    prompt=prompt,
                    system=system,
                    gate=gate,
                    max_tokens=max_tokens,
                    think=think,
                    code=code,
                    agent_id=agent_id or None,
                )
            tier  = "fast" if fast else (self._agent_tier(agent_id) if agent_id and hasattr(self, "_agent_tier") else "?")
            route = getattr(router, "_last_route", "?")
            print(f"[agentai_bridge] {agent_id or 'anon'} tier={tier} route={route} → {len(result)} chars")
            self._bus.dispatch("agentai.result", {
                "agent_id": agent_id,
                "request_id": request_id,
                "result":   result,
                "tier":     tier,
                "route":    route,
            })
        except Exception as e:
            print(f"[agentai_bridge] complete error ({agent_id}): {e}")
            self._bus.dispatch("agentai.error", {"agent_id": agent_id, "request_id": request_id, "error": str(e)})

    def _handle_embed(self, payload):
        request_id = payload.get("request_id")
        router = self._get_router()
        agent_id = payload.get("agent_id", "")
        text = payload.get("text", "")

        if not router:
            self._bus.dispatch("agentai.error", {
                "agent_id": agent_id,
                "request_id": request_id,
                "error": "model_router not available",
            })
            return

        try:
            vector = router.embed(text)
            print(f"[agentai_bridge] {agent_id or 'anon'} embed → {len(vector)} dims")
            self._bus.dispatch("agentai.embed_result", {
                "agent_id": agent_id, "request_id": request_id, "vector": vector,
            })
        except Exception as e:
            print(f"[agentai_bridge] embed error ({agent_id}): {e}")
            self._bus.dispatch("agentai.error", {"agent_id": agent_id, "request_id": request_id, "error": str(e)})


def register(bus):
    agent = AgentAIBridgeAgent(bus)
    bus.register(agent, subscriptions={"agentai.complete", "agentai.embed"})
    print("[plugin] agentai_bridge registered")
