from core.agent import Agent

class HeartbeatAgent(Agent):
    def __init__(self):
        super().__init__(name="heartbeat_agent")

    def handle(self, message_type, payload):
        pass
