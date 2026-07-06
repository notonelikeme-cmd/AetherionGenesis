# core/agent_bus.py
import threading

class AgentBus:
    """
    Message bus with topic subscriptions and a recursion guard.
    """
    def __init__(self):
        self._agents = {}          # name -> agent instance
        self._subscriptions = {}   # name -> set of message types or {'*'}
        self._tls = threading.local()

    def register_agent(self, name: str, agent, subscriptions=None):
        """Register an agent and (optionally) restrict which topics it receives."""
        self._agents[name] = agent
        self._subscriptions[name] = set(subscriptions) if subscriptions else {'*'}

    def register(self, agent, subscriptions=None):
        """Convenience: register an agent using its .name attribute."""
        self.register_agent(agent.name, agent, subscriptions)

    def register_default_agents(self):
        """Reserved for built-ins (noop for now)."""
        pass

    def _targets(self, message_type: str):
        targets = []
        for name, agent in self._agents.items():
            subs = self._subscriptions.get(name, {'*'})
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
                agent.handle(message_type, payload)
        finally:
            self._tls.depth = depth
