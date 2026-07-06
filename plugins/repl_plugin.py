# plugins/repl_plugin.py
from core.agent_base import Agent
from core.message import new_message

class ReplAgent(Agent):
    def __init__(self, name, bus):
        super().__init__(name)
        self.bus = bus
        bus.register_agent(name, self, subscriptions={})

    def start(self):
        import sys, threading
        if not sys.stdin.isatty():
            return
        def repl_loop():
            while True:
                try:
                    line = input(">> ")
                except (EOFError, KeyboardInterrupt):
                    break
                m = new_message("command", line.strip())
                self.bus.dispatch("command", m)
        threading.Thread(target=repl_loop, daemon=True, name="repl_loop").start()

def register(bus):
    agent = ReplAgent("repl", bus)
    agent.start()
