# core/agent_bus.py
import threading
import traceback

class AgentBus:
    """
    Message bus with topic subscriptions and a recursion guard.
    """
    def __init__(self):
        self._agents = {}          # name -> agent instance
        self._subscriptions = {}   # name -> set of message types or {'*'}
        self._registry_lock = threading.Lock()
        self._tls = threading.local()

    def register_agent(self, name: str, agent, subscriptions=None):
        """Register an agent and (optionally) restrict which topics it receives."""
        with self._registry_lock:
            self._agents[name] = agent
            self._subscriptions[name] = set(subscriptions) if subscriptions else {'*'}

    def register(self, agent, subscriptions=None):
        """Convenience: register an agent using its .name attribute."""
        self.register_agent(agent.name, agent, subscriptions)

    def unregister_agent(self, name: str):
        """Remove an agent (e.g. a one-shot RPC listener) from the bus."""
        with self._registry_lock:
            self._agents.pop(name, None)
            self._subscriptions.pop(name, None)

    def register_default_agents(self):
        """Reserved for built-ins (noop for now)."""
        pass

    def _targets(self, message_type: str):
        with self._registry_lock:
            agents = list(self._agents.items())
            subs_map = dict(self._subscriptions)
        targets = []
        for name, agent in agents:
            subs = subs_map.get(name, {'*'})
            if '*' in subs or message_type in subs:
                targets.append(agent)
        return targets

    def dispatch(self, message_type: str, payload):
        """
        Deliver a message only to subscribers.
        Snapshot the target list and guard against runaway recursion.
        """
        depth = getattr(self._tls, 'depth', 0)
        if depth > 10:
            print(f"[bus] drop '{message_type}': max dispatch depth reached")
            return
        self._tls.depth = depth + 1
        try:
            for agent in list(self._targets(message_type)):
                try:
                    agent.handle(message_type, payload)
                except NotImplementedError:
                    pass  # unimplemented stub — skip silently
                except Exception as e:
                    print(f"[bus] {agent.name} raised on '{message_type}': {e}\n{traceback.format_exc()}")
        finally:
            self._tls.depth = depth
