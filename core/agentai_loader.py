# core/agentai_loader.py
"""
Loads modules from ~/AgentAI's `core` package despite it sharing a
top-level package name with AetherionGenesis's own `core` package.

Both projects have a `core/` directory. Whichever one Python imports
first claims sys.modules['core'] for the rest of the process — and
AetherionGenesis's kernel imports its own `core` before any plugin
runs, so a naive `sys.path.insert(...); from core.model_router import
X` in a plugin silently resolves against the WRONG `core` package,
raises ImportError, gets caught, and gets logged as "router
unavailable". That's why the AgentAI bridge never actually worked.

This loader briefly evicts AetherionGenesis's core.* entries from
sys.modules, imports the requested AgentAI module fresh (so its own
internal `from core.X import Y` lines resolve against AgentAI's core),
then restores AetherionGenesis's entries so the rest of the process is
unaffected. Runs once per module name per process — cached after that.
"""
import sys
import os
import threading
import importlib

_AGENTAI_PATH = os.path.expanduser("~/AgentAI")
_lock = threading.Lock()
_cache = {}


def load(module_name):
    """Import `module_name` (e.g. 'core.model_router') from ~/AgentAI."""
    if module_name in _cache:
        return _cache[module_name]

    with _lock:
        if module_name in _cache:
            return _cache[module_name]

        saved = {k: v for k, v in sys.modules.items() if k == "core" or k.startswith("core.")}
        for k in saved:
            del sys.modules[k]

        if _AGENTAI_PATH not in sys.path:
            sys.path.insert(0, _AGENTAI_PATH)

        try:
            module = importlib.import_module(module_name)
        finally:
            for k in list(sys.modules.keys()):
                if k == "core" or k.startswith("core."):
                    del sys.modules[k]
            sys.modules.update(saved)

        _cache[module_name] = module
        return module
