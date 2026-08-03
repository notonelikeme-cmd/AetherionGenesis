# plugins/cli_plugin.py

import os
import threading
from core.agent_base import Agent
from core.message import Message

class CLIAgent(Agent):
    """
    Reads lines from stdin and dispatches them as 'command' messages.

    Skips its stdin reader entirely when AETHER_NO_STDIN_CLI is set —
    anything that needs exclusive ownership of stdin (e.g. acp_main.py's
    JSON-RPC server) sets this before booting the kernel, since two
    readers racing on the same stdin fd silently steal each other's
    lines (whichever thread's read happens to be waiting wins, with no
    way to tell which consumer a given line was meant for).
    """
    def __init__(self, name, bus):
        super().__init__(name)
        self.bus = bus
        bus.register_agent(name, self)
        if os.environ.get("AETHER_NO_STDIN_CLI"):
            print(f"[{name}] stdin reader disabled (AETHER_NO_STDIN_CLI set)")
            return
        threading.Thread(target=self._read_loop, daemon=True).start()

    def _read_loop(self):
        while True:
            try:
                cmd = input()
                if cmd.strip():
                    msg = Message(type="command", payload=cmd.strip())
                    self.bus.dispatch(msg.type, msg)
            except EOFError:
                break

    def handle(self, message_type, payload):
        if message_type == "command":
            print(f"[CLIAgent] Executing command: {payload}")

def register(bus):
    CLIAgent("cli", bus)
