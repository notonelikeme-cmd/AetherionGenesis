# AetherionGenesis

**Autonomous multi-agent AI operating system with a live security research pipeline.**

AetherionGenesis is a self-evolving agent OS kernel. It runs a pub/sub message bus, dynamically loads intelligence plugins at boot, routes work across a fleet of specialized AI agents, and persists all reasoning to an append-only audit ledger. The flagship use case is **autonomous vulnerability research**: the Nexus Trinity plugin runs a 7-gate verification pipeline that finds and proves smart contract vulnerabilities without human intervention.

---

## What it does

```
┌─────────────────────────────────────────────────────────┐
│                  AetherionGenesis Kernel                │
│                                                         │
│  AgentBus (pub/sub)                                     │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Nexus   │  │  AgentAI     │  │  Memory / Audit  │  │
│  │  Trinity │  │  Bridge      │  │  / Persistence   │  │
│  │ 7-gate   │  │  3-tier LLM  │  │  MemoryGraph     │  │
│  │ pipeline │  │  routing     │  │  SQLite ledger   │  │
│  └──────────┘  └──────────────┘  └──────────────────┘  │
│                                                         │
│  Plugin discovery — loads any plugins/*.py at boot      │
│  Consensus layer — optional RAFT via RAFT_ID env var    │
└─────────────────────────────────────────────────────────┘
         │                        │
         ▼                        ▼
  Ollama (local)          Anthropic API
  deepseek-r1:14b         claude-fable-5
  qwen2.5-coder:14b       claude-haiku-4-5
  gemma4:latest
  llama4:scout (HP)
```

**Three tiers of intelligence — no single model bottleneck:**

| Tier | Role | Local model | Cloud model |
|------|------|-------------|-------------|
| 1 | Reasoning — strategy, adversarial critique | deepseek-r1:14b | claude-fable-5 |
| 2 | Execution — code, PoC generation, analysis | qwen2.5-coder:14b | claude-fable-5 |
| 3 | Parser — tool output, JSON schema, no prose | gemma4:latest | claude-haiku-4-5 |

All routing is automatic. The router selects tier by agent name, gate number, or task type. Circuit breakers prevent cascade failures if a backend goes down.

---

## The security research pitch

The hardest problem in bug bounty is **false positives**. A researcher who submits 4 findings and gets all 4 rejected loses money, credibility, and time. The failure modes are well-understood and repeatable:

- Flash accounting net-zero misread as a theft vector
- PoC that asserts `assertTrue(true)` — proves nothing
- Finding that targets an admin-only path — out of scope by definition
- Duplicate of an already-known issue — race lost

**Nexus Trinity bakes all of this in.** Every hypothesis passes through 7 gates before a finding is emitted:

```
Gate 1 — Hypothesis Formation    (Tier 1 reasoning)
Gate 2 — Evidence Gathering      (Tier 3 parser → JSON)
Gate 3 — Simulation / PoC        (Tier 2 code → Foundry fork test, then deterministically re-run — see below)
Gate 4 — Historical Replay       (Tier 2 → DeFiHackLabs match)
Gate 5 — Economic Impact         (Tier 1 → MEV model, severity)
Gate 6 — Adversarial Challenge   (Tier 1 → hostile refutation attempt)
Gate 7 — Reproducibility         (Tier 2 → forge run verification)
```

A finding only exits the pipeline if the adversarial challenger **cannot refute it**. The kill patterns are hardcoded from real rejected submissions — not theoretical. This system was built from 6 confirmed false-positive patterns across real Cantina contest submissions.

**Gate 3 is independently re-verified — zero LLM involvement.** An LLM's own claim that its PoC "passed" is not evidence: it can hallucinate a result, misreport a failing run, or write a PoC that never asserts anything meaningful (`assertTrue(true)`). Two layers close that gap, in order:

1. `core/hallucination_guard.py` — a cheap text-level pre-filter that rejects obviously-fabricated output (fake CVE IDs, `mock data`/`0xdeadbeef` placeholders, a `VULNERABILITY_CONFIRMED` claim with no state-delta markers anywhere nearby) before a real fork test is even attempted. **This layer can only reject, never confirm** — a low score is not evidence a PoC is real, it just means nothing obvious was caught. Its patterns aren't speculative: most were reverse-derived from real hallucinated findings found during an audit of a prior, unfinished build of this same pipeline, including a "detector" whose data-fetch was hardcoded to return a mocked stale timestamp and silently produced a fabricated CRITICAL finding on every single run. That failure mode is exactly what this layer, and the one below, exist to catch.
2. `core/poc_verifier.py` — the actual deterministic check. Runs the Foundry test Gate 3 wrote against a real fork and only lets a finding through if **four** independent signals agree: `forge test`'s own exit code, the `VULNERABILITY_CONFIRMED` marker, a real non-zero on-chain state delta (`BEFORE_STATE`/`AFTER_STATE`) — **and that both of those numbers actually appear as genuine `[Return]` values in forge's own execution trace**, not just printed by the PoC's own `console.log`. That fourth check exists because the PoC fully controls its own log output: a fabricated PoC that just prints two made-up numbers and the confirmation marker, with zero real contract calls, would otherwise pass every other check (real bug, caught in review — see commit history). Also gas-sanity-checks a "confirmed" run — one claiming more gas than fits in a real block means the fork state itself isn't trustworthy — and classifies *why* a run failed (`COMPILE_ERROR`, `ASSERTION_FAILED`, `NO_STATE_DELTA`, `MARKERS_MISSING`, `UNVERIFIED_STATE_MARKERS`, `GAS_ANOMALY`) instead of one generic failure string.

A run that executes and disproves the claim, at either layer, is a hard kill (`nexus.rejected`). A run that can't execute (no `forge` on PATH, RPC down), or that never ran at all (Gate 3 skipped), doesn't silently produce a "confirmed" finding — the pipeline only labels a finding `verified: true` and prints "FINDING CONFIRMED" when `deterministic_verification.status == "CONFIRMED"`; anything else prints "FINDING UNVERIFIED" and sets `verified: false`, both at the top level of the emitted finding, not just buried in a nested field.

Generated PoCs run under a dedicated `verify` Foundry profile (`foundry.toml`) that scopes `.nexus_poc_scratch/` as the only compiled test root for that profile — the **default** profile has no configured test root at all, so a stale PoC left behind by a killed process can't get picked up by anyone running a plain `forge test`, only by a deliberate `FOUNDRY_PROFILE=verify` run. Neither profile grants `fs_permissions`, since nothing here needs Solidity-level filesystem cheatcodes and granting them would let an untrusted, LLM-generated PoC write into real runtime state.

**Gate 2 gets a second, independent signal too.** `core/aderyn_scanner.py` runs [Aderyn](https://github.com/Cyfrin/aderyn) (Cyfrin's static analyzer) against the contract code and appends its real findings to Gate 2's prompt, clearly labeled as corroborating evidence only — Aderyn's ruleset is generic and has no idea what the specific hypothesis claims, so it can support or contradict it but never substitutes for the LLM's own read. Unavailable/errored scans degrade to no extra evidence, never to a failure. (Note on `aderyn`'s CLI, confirmed by direct testing: `--skip-update-check` is required when installed via `cargo install` — without it, the tool panics in an unrelated self-update step immediately *after* writing a correct report; `--stdout` mode is separately broken for instance-location printing in v0.1.9, so this module writes to a real file and reads it back instead.)

**Halmos was evaluated and deliberately not integrated.** It's a genuine, well-built symbolic execution tool, but it doesn't support `vm.createFork`/`vm.createSelectFork` at all — confirmed by direct testing, not documentation ("Unsupported cheat code" on the fork call). Since every Gate 3 PoC in this pipeline forks a real chain by design (rule #1 in Gate 3's prompt), Halmos's symbolic-EVM-in-isolation model is a fundamental architecture mismatch here, not a configuration problem. Forcing it in would mean either it silently does nothing useful or Gate 3 stops testing against real deployed state — worse than not having it.

---

## Quickstart (local, no Docker required)

**Prerequisites:** Python 3.9+, [Ollama](https://ollama.com) with at least one model pulled. Optional but recommended for Gate 3's deterministic re-verification: [Foundry](https://getfoundry.sh) (`forge`) on PATH and `ETH_RPC_URL` set to a mainnet RPC — without these, Gate 3 still runs, but findings won't be independently re-checked (this is recorded in the finding's `deterministic_verification` field, not silently skipped). Also optional, for Gate 2's static-analysis evidence: [Aderyn](https://github.com/Cyfrin/aderyn) (`cargo install aderyn`) on PATH — without it, Gate 2 just runs without the extra evidence.

```bash
# 1. Clone
git clone https://github.com/notonelikeme-cmd/AetherionGenesis.git
cd AetherionGenesis

# 2. Install deps
pip install -r requirements.txt

# 3. Pull a base model (if not already)
ollama pull qwen2.5-coder:14b

# 4. Boot the kernel
python3 -m core.kernel
```

**One-shot pipeline dispatch:**
```python
from core.kernel import Kernel

k = Kernel()
k.bootstrap()

k.dispatch("nexus.pipeline", {
    "hypothesis": "attacker drains vault via reentrancy in withdraw() callback",
    "contract_path": "src/Vault.sol",
    "code": open("src/Vault.sol").read(),
})
```

**Long-running service:**
```bash
AETHER_SERVICE=1 python3 -m core.kernel
```

**HP machine setup** (after `ollama pull llama4:scout` completes):
```bash
bash scripts/hp_setup.sh
```

---

## Plugin system

Drop a `.py` file in `plugins/` with a `register(bus)` function. It is loaded at boot:

```python
# plugins/my_plugin.py
from core.agent import Agent

class MyAgent(Agent):
    def __init__(self, bus):
        super().__init__(name="my_agent")
        self._bus = bus

    def handle(self, message_type, payload):
        if message_type == "my.event":
            print(f"[my_agent] received: {payload}")

def register(bus):
    agent = MyAgent(bus)
    bus.register(agent, subscriptions={"my.event"})
```

Dispatch from anywhere:
```python
k.dispatch("my.event", {"data": "hello"})
```

Plugins that fail to import are skipped with a log line — one bad dependency never crashes the kernel.

---

## Key message types

| Topic | Direction | Description |
|-------|-----------|-------------|
| `nexus.pipeline` | → kernel | Run full 7-gate verification |
| `nexus.hypothesis` | → kernel | Run Gate 1 only |
| `nexus.finding` | kernel → | Confirmed vulnerability (all gates passed) |
| `nexus.rejected` | kernel → | Finding killed — includes kill pattern + reason |
| `nexus.gate_result` | kernel → | Per-gate pass/fail + evidence output |
| `agentai.complete` | → kernel | Route LLM completion via tier router |
| `agentai.result` | kernel → | LLM response + tier/route metadata |

---

## Architecture

```
core/
  kernel.py          — bootstrap, signal handling, service/interactive/one-shot modes
  agent_bus.py       — pub/sub, per-agent exception isolation, recursion guard (depth 10)
  agent.py           — base Agent class
  plugin_manager.py  — fault-tolerant dynamic plugin loader
  consensus.py       — optional RAFT consensus (set RAFT_ID=host:port)
  audit_store.py     — SQLite append-only audit ledger with Message serialization
  message.py         — Message dataclass with causal IDs and timestamps

plugins/
  nexus_trinity_plugin.py   — 7-gate vulnerability pipeline (wired to model router)
  agentai_bridge_plugin.py  — AgentBus → AgentAI 3-tier model router bridge
  (+ upstream plugins for scheduling, heartbeat, web API, persistence, etc.)

agents/              — named Agent subclasses registered at kernel boot
scripts/
  hp_setup.sh        — one-command setup for the 36GB HP machine
```

The model router (`core/model_router.py`) lives in the companion AgentAI repo and is loaded via `sys.path`. Set `AGENTAI_PATH` env var to override the default `~/AgentAI`.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AETHER_SERVICE` | unset | Set to `1` for long-running service mode |
| `RAFT_ID` | unset | `host:port` to enable distributed consensus |
| `RAFT_PEERS` | unset | Comma-separated peer `host:port` list |
| `ANTHROPIC_API_KEY` | unset | Enables cloud LLM routing (Fable 5 / Haiku) |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint |
| `AUDIT_DB` | `var/audit.db` | SQLite audit log path |
| `AGENTAI_PATH` | `~/AgentAI` | Path to AgentAI model router |

---

## Hardened SCOUT models

The `scripts/hp_setup.sh` script builds 7 Ollama models from hardened Modelfiles in [notonelikeme-cmd/scout](https://github.com/notonelikeme-cmd/scout):

| Model | Base | Role |
|-------|------|------|
| `scout` | qwen2.5-coder:14b | Primary vulnerability hunter |
| `scout-mem` | qwen2.5-coder:14b | Hunter with memory schema access |
| `scout-pm` | qwen2.5-coder:14b | Polymarket-specific hunter |
| `r1-sec` | deepseek-r1:14b | Deep reasoning / adversarial challenge |
| `qwen-sec` | qwen2.5-coder:14b | PoC generation / code execution |
| `gemma4-sec` | gemma4:latest | Tool output parser / JSON extractor |
| `scout-llama4` | llama4:scout | HP-optimized full-context hunter |

All models include operator-authorization hardening and the 6-kill-pattern knowledge base baked into their system prompts.

---

## One-paragraph pitch

> AetherionGenesis is an on-premises autonomous agent OS for security research teams. It runs a fleet of 55+ specialized AI agents on local hardware — no data leaves your network as long as cloud routing is disabled and `ANTHROPIC_API_KEY` is unset — coordinated through a pub/sub kernel that routes reasoning tasks to the right model tier automatically. The flagship capability is Nexus Trinity: a 7-gate vulnerability verification pipeline that eliminates false positives by running every candidate finding through hypothesis formation, code evidence extraction, Foundry fork PoC generation, historical exploit matching, MEV impact modeling, adversarial self-challenge, and reproducibility verification before surfacing a result. Kill patterns from real rejected submissions are hardcoded into the pipeline. The system runs on a single MacBook today; it scales to a distributed mesh via RAFT consensus and supports Anthropic cloud fallback when local compute is saturated — prompts and source material do leave the network in that mode. Built for DeFi security teams, bug bounty firms, and any organization that needs AI-assisted vulnerability research without handing source code to a third party by default.

---

## License

MIT
