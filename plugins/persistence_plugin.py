# plugins/persistence_plugin.py

import json
from core.agent_base import Agent

class PersistenceAgent(Agent):
    """
    Persists the MemoryGraph to disk on each 'tick'.
    """
    def __init__(self, name, bus, filename='graph.json'):
        super().__init__(name)
        self.bus = bus
        self.filename = filename
        bus.register_agent(name, self)

    def handle(self, message_type, payload):
        if message_type == 'tick':
            graph = getattr(self.bus, 'graph', None)
            if graph is None:
                return
            data = {
                'nodes': list(graph.graph.nodes(data=True)),
                'edges': list(graph.graph.edges(data=True))
            }
            with open(self.filename, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"[{self.name}] Persisted graph to {self.filename}")

def register(bus):
    PersistenceAgent('persistence', bus)
