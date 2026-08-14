# plugins/webapi_plugin.py

import threading
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from core.agent_base import Agent
from core.message import new_message
from core import caps, task_store, goal_store

_SESSION_COOKIE = 'nexus_kanban_session'


class WebAPIHandler(BaseHTTPRequestHandler):
    def _cookie(self, name):
        for part in self.headers.get('Cookie', '').split(';'):
            k, _, v = part.strip().partition('=')
            if k == name:
                return v
        return None

    def _require_scope(self, scope, qs):
        """Kanban data/HTML can carry task descriptions and verdicts from
        anywhere leads.write can reach — require a capability token like
        the POST endpoints already do.

        Priority: header (curl/scripts) > session cookie (the browser's
        own follow-up requests, e.g. /kanban.json fetched by the page
        itself) > `token` query param (a one-time bootstrap for plain
        browser navigation only). A query-param token is never treated as
        equivalent to a real session — it authorizes exactly one request,
        because URLs persist in browser history and server/proxy access
        logs. See _bootstrap_session below for how /kanban exchanges a
        query token for a cookie instead of relying on the URL long-term.

        Returns (ok, info, via_query) — via_query tells the caller whether
        this specific request only authenticated via the URL, so it knows
        whether to bootstrap a session.
        """
        token = self.headers.get('X-Cap-Token', '') or self._cookie(_SESSION_COOKIE)
        if token:
            ok, info = caps.verify(token, required_scope=scope)
            return ok, info, False
        qs_token = qs.get('token', [''])[0]
        ok, info = caps.verify(qs_token, required_scope=scope)
        return ok, info, ok

    def _bootstrap_session(self, location, token):
        """Exchange a one-time query-param token for an HttpOnly session
        cookie and redirect to a clean URL, so the token doesn't linger in
        the address bar/history on repeat views of the page."""
        self.send_response(302)
        self.send_header('Location', location)
        self.send_header('Set-Cookie', f'{_SESSION_COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=300')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        graph = self.server.bus.graph.graph

        if path in ('/kanban.json', '/kanban'):
            ok, info, via_query = self._require_scope('kanban:read', qs)
            if not ok:
                self._send_json(401, {'error': f'unauthorized: {info}'})
                return
            if path == '/kanban' and via_query:
                self._bootstrap_session('/kanban', qs.get('token', [''])[0])
                return

        if path == '/nodes':
            resp = list(graph.nodes(data=True))
        elif path == '/edges':
            resp = list(graph.edges(data=True))
        elif path == '/neighbors':
            node = qs.get('node', [None])[0]
            resp = list(graph.successors(node)) if node else {'error': 'node param required'}
        elif path == '/path':
            src = qs.get('src', [None])[0]
            dst = qs.get('dst', [None])[0]
            resp = self.server.bus.graph.find_path(src, dst) if src and dst else {'error': 'src & dst required'}
        elif path == '/kanban.json':
            resp = {
                'tasks': task_store.board(200),
                'stats': task_store.stats(),
                'goals': goal_store.get_all(),
            }
        elif path == '/kanban':
            self._send_html(200, _KANBAN_PAGE)
            return
        else:
            self.send_response(404)
            self.end_headers()
            return

        self._send_json(200, resp)

    def do_POST(self):
        parsed = urlparse(self.path)
        parts = parsed.path.strip('/').split('/')

        if parts == ['leads']:
            self._handle_lead_post()
            return

        if len(parts) != 2 or parts[0] != 'webhooks' or not parts[1]:
            self.send_response(404)
            self.end_headers()
            return
        name = parts[1]

        token = self.headers.get('X-Cap-Token', '')
        ok, info = caps.verify(token, required_scope=f"webhook:{name}")
        if not ok:
            self._send_json(401, {'error': f'unauthorized: {info}'})
            return

        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length) if length else b'{}'
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self._send_json(400, {'error': 'invalid JSON body'})
            return

        msg_type = f"webhook.{name}"
        self.server.bus.dispatch(msg_type, new_message(msg_type, body))
        self._send_json(200, {'status': 'accepted', 'type': msg_type})

    def _handle_lead_post(self):
        token = self.headers.get('X-Cap-Token', '')
        ok, info = caps.verify(token, required_scope="leads:write")
        if not ok:
            self._send_json(401, {'error': f'unauthorized: {info}'})
            return

        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length) if length else b'{}'
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self._send_json(400, {'error': 'invalid JSON body'})
            return

        description = body.get('description', '')
        if not description:
            self._send_json(400, {'error': 'description required'})
            return

        step_index = task_store.enqueue_lead(description)
        self.server.bus.dispatch('leads.queued', new_message('leads.queued', {'step_index': step_index, 'description': description}))
        self._send_json(200, {'status': 'queued', 'step_index': step_index})

    def _send_json(self, status, resp):
        body = json.dumps(resp).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, html):
        body = html.encode()
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


_KANBAN_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>AetherionGenesis — Kanban</title>
<meta http-equiv="refresh" content="10">
<style>
  body { font-family: -apple-system, sans-serif; background: #0d1117; color: #c9d1d9; margin: 0; padding: 1.5rem; }
  h1 { font-size: 1.1rem; color: #58a6ff; }
  .stats { display: flex; gap: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
  .stat { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 0.5rem 1rem; }
  .board { display: flex; gap: 1rem; overflow-x: auto; }
  .col { flex: 1; min-width: 220px; background: #161b22; border-radius: 6px; padding: 0.75rem; }
  .col h2 { font-size: 0.85rem; text-transform: uppercase; color: #8b949e; margin: 0 0 0.5rem; }
  .card { background: #0d1117; border: 1px solid #30363d; border-radius: 4px; padding: 0.5rem; margin-bottom: 0.5rem; font-size: 0.8rem; }
  .card .cycle { color: #8b949e; font-size: 0.7rem; }
  .verdict-pass { color: #3fb950; } .verdict-fail { color: #f85149; }
</style></head>
<body>
  <h1>AetherionGenesis — Task Board</h1>
  <div class="stats" id="stats"></div>
  <div class="board" id="board"></div>
  <script>
    // Task descriptions/verdicts are persisted user/lead input (e.g. via
    // POST /leads) — escape before interpolating into innerHTML so a
    // crafted description can't execute as markup/script here.
    function esc(s) {
      return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }
    fetch('/kanban.json').then(r => r.json()).then(data => {
      const statsEl = document.getElementById('stats');
      const s = data.stats;
      statsEl.innerHTML = Object.entries(s.by_status || {}).map(([k,v]) => `<div class="stat">${esc(k)}: ${esc(v)}</div>`).join('')
        + `<div class="stat">leads pending: ${esc(s.leads_pending)}</div>`
        + (s.oldest_pending_seconds ? `<div class="stat">oldest: ${esc(Math.round(s.oldest_pending_seconds/60))}m</div>` : '');

      const cols = {running: [], executed: [], passed: [], failed: [], retried: []};
      for (const t of data.tasks) { (cols[t.status] = cols[t.status] || []).push(t); }
      const board = document.getElementById('board');
      board.innerHTML = Object.entries(cols).map(([status, tasks]) => `
        <div class="col"><h2>${esc(status)} (${tasks.length})</h2>
          ${tasks.map(t => `<div class="card">
            <div class="cycle">${esc(t.cycle_id)}</div>
            <div>${esc((t.description||'').slice(0,120))}</div>
            ${t.verdict ? `<div class="${t.verdict.toUpperCase().startsWith('PASS') ? 'verdict-pass' : 'verdict-fail'}">${esc(t.verdict.slice(0,80))}</div>` : ''}
          </div>`).join('')}
        </div>`).join('');
    });
  </script>
</body></html>"""

class WebAPIAgent(Agent):
    def __init__(self, name, bus, host='0.0.0.0', port=8000):
        super().__init__(name)
        self.bus = bus
        bus.register_agent(name, self)
        self.server = HTTPServer((host, port), WebAPIHandler)
        self.server.bus = bus
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        print(f"[{self.name}] HTTP API running at http://{host}:{port}")

    def handle(self, message_type, payload):
        pass  # does not consume bus messages

def register(bus):
    WebAPIAgent('webapi', bus)
