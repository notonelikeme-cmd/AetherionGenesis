import threading
import time
import signal
import os
import sys

from core.agent_bus import AgentBus
from core.plugin_manager import PluginManager
from core.message import Message
from core.consensus import ConsensusNode
from core.repl import start_repl


class Kernel:
    def __init__(self):
        self.bus     = AgentBus()
        self.plugins = PluginManager(self.bus)
        self._stop   = threading.Event()

    def bootstrap(self):
        print("🚀 Bootstrapping AetherionPrime Kernel...")

        # Core agents
        from agents.echo_agent       import EchoAgent
        from agents.logging_agent    import LoggingAgent
        from agents.heartbeat_agent  import HeartbeatAgent
        from agents.scheduler_agent  import SchedulerAgent
        from agents.perception_agent import PerceptionAgent

        self.bus.register(EchoAgent())
        self.bus.register(LoggingAgent())
        self.bus.register(HeartbeatAgent())
        self.bus.register(SchedulerAgent(interval=5))
        self.bus.register(PerceptionAgent())

        # Plugins — load in foreground so they're ready before we block
        self.plugins.load_plugins()

        # Consensus (optional)
        if os.environ.get("RAFT_ID"):
            consensus = ConsensusNode()
            threading.Thread(target=consensus.run, daemon=True).start()
        else:
            print("[consensus] Not configured. Set RAFT_ID to enable.")

        # Signal handlers for clean shutdown
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._handle_signal)

        # Interactive: hand off to REPL (blocks until user types exit)
        if sys.stdin.isatty():
            start_repl(self.bus)
        else:
            # Non-interactive (service / programmatic): keep process alive
            print("[kernel] Service mode — waiting for SIGTERM/SIGINT to stop.")
            self._stop.wait()
            print("[kernel] Shutdown complete.")

    def _handle_signal(self, signum, frame):
        print(f"\n[kernel] Signal {signum} received — shutting down.")
        self._stop.set()

    def dispatch(self, message_type: str, payload):
        """Convenience wrapper for external callers."""
        self.bus.dispatch(message_type, payload)


if __name__ == "__main__":
    Kernel().bootstrap()
