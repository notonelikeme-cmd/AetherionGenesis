# core/plugin_manager.py
import importlib
import os

class PluginManager:
    """
    Dynamically discover and load agent plugins from the 'plugins' directory.
    """
    def __init__(self, bus):
        self.bus = bus

    def load_plugins(self):
        plugin_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'plugins')
        if not os.path.isdir(plugin_dir):
            return
        for fname in sorted(os.listdir(plugin_dir)):
            if not fname.endswith('.py') or fname == '__init__.py':
                continue
            mod_name = f"plugins.{fname[:-3]}"
            try:
                module = importlib.import_module(mod_name)
                if hasattr(module, 'register'):
                    module.register(self.bus)
            except Exception as e:
                print(f"[plugin_manager] skipped {fname}: {e}")
