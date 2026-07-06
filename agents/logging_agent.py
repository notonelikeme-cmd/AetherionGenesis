from core.agent import Agent

class LoggingAgent(Agent):
    def __init__(self):
        super().__init__(name="logging_agent")

    def handle(self, message_type, payload):
        pass
