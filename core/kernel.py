import threading
import time
import signal
import os
import sys

from core.agent_bus import AgentBus
from core.plugin_manager import PluginManager
from core.memory_graph import MemoryGraph
from core.message import Message
from core.consensus import ConsensusNode
from core.repl import start_repl


class Kernel:
    def __init__(self):
        self.bus       = AgentBus()
        self.bus.graph = MemoryGraph()
        self.bus.graph.bootstrap()
        self.plugins   = PluginManager(self.bus)
        self._stop     = threading.Event()

    def bootstrap(self):
        print("🚀 Bootstrapping AetherionPrime Kernel...")

        # Core agents (self-register with the bus on construction)
        from agents.echo_agent       import ReflexAgent
        from agents.logging_agent    import AuditTrailAgent
        from agents.heartbeat_agent  import PulseMonitor
        from agents.scheduler_agent  import ChronoAgent
        from agents.perception_agent import SensorAgent
        from agents.loop_orchestrator import CycleAgent
        from agents.snapshot_agent import SnapshotAgent
        from agents.task_queue_agent import TaskQueueAgent
        from agents.branch_agent import BranchAgent
        from agents.dispatcher_agent import DispatcherAgent

        ReflexAgent(self.bus)
        AuditTrailAgent(self.bus)
        PulseMonitor(self.bus)
        ChronoAgent(self.bus, default_interval=5)
        SensorAgent(self.bus)
        SnapshotAgent(self.bus)
        TaskQueueAgent(self.bus)
        BranchAgent(self.bus)
        DispatcherAgent(self.bus)
        CycleAgent(self.bus)

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
        elif os.environ.get("AETHER_SERVICE"):
            # Explicit long-running service mode: block until signal
            print("[kernel] Service mode — waiting for SIGTERM/SIGINT to stop.")
            self._stop.wait()
            print("[kernel] Shutdown complete.")
        else:
            # Non-interactive one-shot (import, test, pipeline dispatch): return immediately
            print("[kernel] Ready.")

    def _handle_signal(self, signum, frame):
        print(f"\n[kernel] Signal {signum} received — shutting down.")
        self._stop.set()

    def dispatch(self, message_type: str, payload):
        """Convenience wrapper for external callers."""
        self.bus.dispatch(message_type, payload)


if __name__ == "__main__":
    Kernel().bootstrap()
