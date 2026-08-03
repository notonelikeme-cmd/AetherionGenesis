#!/usr/bin/env python3
"""
acp_main.py — minimal Agent Client Protocol (ACP) shim.

ACP is an open JSON-RPC 2.0 protocol (line-delimited JSON over
stdin/stdout) that lets any editor (Zed, JetBrains via a plugin, etc.)
talk to any agent. Three phases: initialize -> session/new ->
session/prompt, with session/update as a one-way streaming
notification.

HONESTY NOTE: this implements the documented method names and phase
structure (from agentclientprotocol.com's overview + the ACP GitHub
repo), not the full published JSON Schema — I did not have verified
field-level detail for every nested object (tool-call shapes, fs/
terminal capability negotiation) at build time. Treat this as a
starting point: boots, speaks the right method names, and round-trips
a prompt through the AetherionGenesis bus — but expect to need
adjustments after testing against a real ACP client (Zed's `zed --acp
python3 acp_main.py`, or the reference Python/TS SDKs).

Use cases this covers:
  - editor query -> verdict:  session/prompt with a code fragment,
    routed through agentai.complete
  - headless scripting: POST-free, just pipe JSON-RPC lines in/out
  - handoff continuity: goal_store/task_store are sqlite on disk, so
    a fresh ACP process on another machine sharing that storage sees
    the same cycle state — no bus-level session sharing needed for that.

Run: python3 acp_main.py   (stdio only — no output except JSON-RPC)
"""
import json
import sys
import threading
import time
import uuid

# Every agent/plugin in this codebase uses print() for logging, which
# goes to stdout by default — but ACP requires stdout reserved
# exclusively for JSON-RPC framing (standard practice for any
# stdio-based JSON-RPC server, same reasoning as LSP). Save the real
# stdout for protocol output, then redirect the process-wide stdout to
# stderr *before* booting the kernel so every print() downstream lands
# on stderr instead of corrupting the JSON-RPC stream.
_PROTOCOL_STDOUT = sys.stdout
sys.stdout = sys.stderr

# plugins/cli_plugin.py also reads stdin (for interactive CLI commands)
# in its own thread on every kernel boot — that races with this
# server's own stdin reads and silently steals JSON-RPC lines (see
# _read_loop there). This tells it to stay out of stdin entirely.
import os
os.environ["AETHER_NO_STDIN_CLI"] = "1"

from core.kernel import Kernel
from core.bus_rpc import call as bus_call

PROTOCOL_VERSION = "1"


class ACPServer:
    def __init__(self):
        self.kernel = Kernel()
        self.kernel.bootstrap()
        self.sessions = {}  # sessionId -> {"cwd": str}
        self._out_lock = threading.Lock()

    def _write(self, obj):
        line = json.dumps(obj)
        with self._out_lock:
            _PROTOCOL_STDOUT.write(line + "\n")
            _PROTOCOL_STDOUT.flush()

    def _respond(self, id_, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": id_}
        if error is not None:
            msg["error"] = error
        else:
            msg["result"] = result if result is not None else {}
        self._write(msg)

    def _notify(self, method, params):
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def run(self):
        # Explicit readline() loop, not `for line in sys.stdin` — the
        # iterator form does internal read-ahead buffering that can
        # withhold an already-available line instead of yielding it
        # immediately, which over a pipe means the first request never
        # gets processed until more data arrives (silent hang).
        while True:
            line = sys.stdin.readline()
            if not line:
                break  # EOF — client closed stdin
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            threading.Thread(target=self._dispatch, args=(req,), daemon=True).start()

    def _dispatch(self, req):
        method = req.get("method")
        params = req.get("params", {}) or {}
        id_ = req.get("id")

        try:
            if method == "initialize":
                self._respond(id_, {
                    "protocolVersion": PROTOCOL_VERSION,
                    "agentCapabilities": {"promptCapabilities": {"image": False, "audio": False}},
                    "agentInfo": {"name": "AetherionGenesis", "version": "0.1"},
                })
            elif method == "session/new":
                session_id = str(uuid.uuid4())
                self.sessions[session_id] = {"cwd": params.get("cwd")}
                self._respond(id_, {"sessionId": session_id})
            elif method == "session/prompt":
                self._handle_prompt(id_, params)
            else:
                self._respond(id_, error={"code": -32601, "message": f"method not found: {method}"})
        except Exception as e:
            self._respond(id_, error={"code": -32000, "message": str(e)})

    def _handle_prompt(self, id_, params):
        session_id = params.get("sessionId")
        prompt_blocks = params.get("prompt", [])
        text = " ".join(b.get("text", "") for b in prompt_blocks if isinstance(b, dict) and b.get("type") == "text")
        if not text:
            text = str(params.get("prompt", ""))

        self._notify("session/update", {
            "sessionId": session_id,
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "working..."}},
        })

        msg_type, reply = bus_call(
            self.kernel.bus, "agentai.complete",
            {"agent_id": "acp", "prompt": text, "think": True},
            reply_types={"agentai.result"}, timeout=90,
        )
        result_text = reply.get("result", "") if msg_type == "agentai.result" else f"[unavailable: {msg_type}]"

        self._notify("session/update", {
            "sessionId": session_id,
            "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": result_text}},
        })
        self._respond(id_, {"stopReason": "end_turn"})


if __name__ == "__main__":
    ACPServer().run()
