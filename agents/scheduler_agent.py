from core.agent import Agent

class SchedulerAgent(Agent):
    def __init__(self, interval=5):
        super().__init__(name="scheduler_agent")
        self.interval = interval

    def handle(self, message_type, payload):
        pass
