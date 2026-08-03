# agents/perception_agent.py
import os

from core.agent_base import Agent
from core.message import new_message

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    _WATCHDOG_AVAILABLE = True
except ImportError:
    _WATCHDOG_AVAILABLE = False
    FileSystemEventHandler = object  # placeholder base so the class below still defines


def _classify_stub(image_path):
    """Placeholder classifier — swap in a real vision model call."""
    return ["object1", "object2"]


class _WatchHandler(FileSystemEventHandler):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def on_created(self, event):
        if event.is_directory or not event.src_path.lower().endswith((".png", ".jpg", ".jpeg")):
            return
        self.owner.ingest(event.src_path)


class SensorAgent(Agent):
    """
    Watches a directory for new images, classifies them (stub), records
    the result in the shared memory graph (bus.graph), and broadcasts a
    'perception' message for downstream agents.

    Uses a distinct watch directory (percepts/sensor) from
    plugins/perception_plugin.py's "percepts" so the two watchers don't
    double-process the same files if both are loaded.
    """

    def __init__(self, bus, watch_dir="percepts/sensor"):
        super().__init__(name="perception_agent")
        self.bus = bus
        self.watch_dir = watch_dir
        bus.register(self)

        if not _WATCHDOG_AVAILABLE:
            print(f"[{self.name}] watchdog not installed — filesystem watching disabled "
                  f"(pip install watchdog to enable; see requirements.txt)")
            return

        os.makedirs(watch_dir, exist_ok=True)
        handler = _WatchHandler(self)
        observer = Observer()
        observer.schedule(handler, path=watch_dir, recursive=False)
        observer.daemon = True
        observer.start()
        print(f"[{self.name}] watching {watch_dir}")

    def ingest(self, file_path):
        objects = _classify_stub(file_path)
        node_id = os.path.basename(file_path)

        graph = getattr(self.bus, "graph", None)
        if graph is not None:
            graph.add_node(node_id, {"type": "percept", "file": file_path})
            for obj in objects:
                graph.add_node(obj, {"type": "object"})
                graph.add_edge(node_id, obj, "contains")

        msg = new_message("perception", {"file": file_path, "objects": objects})
        self.bus.dispatch(msg.type, msg)

    def handle(self, message_type, message):
        # Reserved for future message-driven capture requests
        # (e.g. "capture_request" with an explicit file path).
        return
