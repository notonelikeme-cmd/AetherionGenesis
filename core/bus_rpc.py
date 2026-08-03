# core/bus_rpc.py
"""
Synchronous request/reply helper over the async AgentBus.

The bus is fire-and-forget: dispatch() doesn't return the handler's
result, and services like agentai_bridge_plugin answer asynchronously
from a background thread. Several agents (goal decomposition, vector
memory, meta-learning, the loop orchestrator) need a plain call-and-wait
call shape on top of that. This is that shape, implemented once instead
of re-implemented per caller.
"""
import threading
import uuid


def call(bus, request_type, payload, reply_types, error_type="agentai.error", timeout=30):
    """
    Dispatch `request_type` with a unique request_id merged into `payload`,
    block until a message whose type is in `reply_types` (or `error_type`)
    carries that same request_id, then return (message_type, reply_payload).

    Returns (None, None) on timeout so callers can fall back gracefully
    instead of hanging forever if the bridge/router is unavailable.
    """
    request_id = str(uuid.uuid4())
    payload = dict(payload)
    payload["request_id"] = request_id

    done = threading.Event()
    result = {}
    accepted_types = set(reply_types) | {error_type}

    class _Listener:
        name = f"_rpc_{request_id}"

        def handle(self, message_type, message):
            reply_payload = getattr(message, "payload", message)
            if not isinstance(reply_payload, dict) or reply_payload.get("request_id") != request_id:
                return
            if message_type in accepted_types:
                result["type"] = message_type
                result["payload"] = reply_payload
                done.set()

    listener = _Listener()
    bus.register_agent(listener.name, listener, subscriptions=accepted_types)
    try:
        bus.dispatch(request_type, payload)
        done.wait(timeout)
    finally:
        bus.unregister_agent(listener.name)

    return result.get("type"), result.get("payload")
