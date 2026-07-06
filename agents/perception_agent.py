from core.agent import Agent

class PerceptionAgent(Agent):
    def __init__(self):
        super().__init__(name="perception_agent")

    def handle(self, message_type, payload):
        pass
