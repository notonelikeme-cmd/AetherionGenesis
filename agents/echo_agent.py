from core.agent import Agent

class EchoAgent(Agent):
    def __init__(self):
        super().__init__(name="echo_agent")

    def handle(self, message_type, payload):
        if message_type == "echo":
            print(f"[echo] {payload}")
