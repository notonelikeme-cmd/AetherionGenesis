# Capabilities

Mapped to AetherionGenesis's actual components — not a generic feature list. Tools/Tasks below reference real files in this repo (or the sibling `~/AgentAI`), not generic ML tooling (no Flask/Django/BERT/TensorFlow — this system runs on the `AgentBus` + `model_router.py`'s 3-tier Ollama/Claude routing). "Confirmed" means actually exercised live this session; everything else is implemented-but-unverified or not-yet-built.

### Core Features

1. **Natural Language Understanding (NLU)**
   - **Specifics**: Handled by whichever model `model_router.py` selects for the calling `agent_id`/`gate` — deepseek-r1 (Tier 1, reasoning), qwen2.5-coder (Tier 2, execution), or gemma4 (Tier 3, parsing/JSON). No dedicated NLU layer; understanding quality is the underlying model's.
   - **Testing Plan**:
     - **Exp**: Confirmed.
       - **Tasks**: Dispatch a raw prompt through `agentai.complete` and inspect the parsed reply.
       - **Tools**: `core/bus_rpc.py` (`call()`), `plugins/agentai_bridge_plugin.py`.
       - **Evaluation**: Direct `router.complete()` calls returned coherent, on-topic responses this session.
     - **Beta**: Confirmed.
       - **Tasks**: Feed a free-text goal into `GoalAgent` and check the parsed step list is sane.
       - **Tools**: `plugins/goal_agent_plugin.py`.
       - **Evaluation**: Live-verified — "say hello in two creative ways" decomposed into 5 coherent, on-topic steps.
     - **Test**: Not yet run.
       - **Tasks**: Run Nexus Trinity Gate 2 (Evidence Gathering) against a real contract and check the strict-JSON output parses.
       - **Tools**: `plugins/nexus_trinity_plugin.py` (`_GATES[2]`), `core/agentai_loader.py`.
       - **Evaluation**: Would require `_parse_output(2, raw)` to return valid JSON on a live gate run — not exercised yet.

2. **Text Generation**
   - **Specifics**: `agentai.complete` is the single generation entry point for every agent — no separate generation subsystem.
   - **Testing Plan**:
     - **Exp**: Confirmed.
       - **Tasks**: Round-trip a completion request through the bridge.
       - **Tools**: `plugins/agentai_bridge_plugin.py` `_handle_complete()`.
       - **Evaluation**: Bridge correctly returned tier/route metadata alongside output.
     - **Beta**: Confirmed.
       - **Tasks**: Run a full `CycleAgent` execute stage on non-DeFi steps.
       - **Tools**: `agents/loop_orchestrator.py` (`_execute_via_completion`).
       - **Evaluation**: Generated real multi-paragraph outputs (a poem, ASL instructions) verified coherent by the verify stage.
     - **Test**: Partially confirmed.
       - **Tasks**: Run Nexus Trinity Gate 3 against a live contract; confirm the Foundry PoC compiles and runs.
       - **Tools**: `nexus_trinity_plugin.py` (`_GATES[3]` template).
       - **Evaluation**: Template/constraints verified by inspection this session; no live fork-test run yet.

3. **Question Answering**
   - **Specifics**: No dedicated QA agent; any `agentai.complete` call with a question-shaped prompt is answered by the routed model.
   - **Testing Plan**:
     - **Exp**: Confirmed.
       - **Tasks**: Ad-hoc `router.complete()` calls with factual prompts.
       - **Tools**: `~/AgentAI/core/model_router.py`.
       - **Evaluation**: Correct, on-topic answers returned this session.
     - **Beta**: Not yet.
       - **Tasks**: Would need a QA-shaped `CycleAgent` goal (multi-step lookup + synthesis) to validate multi-turn accuracy.
       - **Tools**: `agents/loop_orchestrator.py`.
       - **Evaluation**: Not run.
     - **Test**: Not applicable yet — no domain-specific QA benchmark wired in.

4. **Conversational Agents**
   - **Specifics**: `core/repl.py` gives a live, interactive `kernel` object for manual dispatch — not a persistent multi-turn conversational agent. No session/history state is threaded between calls today.
   - **Testing Plan**:
     - **Exp**: Confirmed.
       - **Tasks**: Boot the kernel interactively and dispatch commands via the REPL.
       - **Tools**: `core/repl.py`, `core/kernel.py`.
       - **Evaluation**: REPL accepts input and evaluates against the live `kernel` object.
     - **Beta**: Not built — no conversation-history-aware agent exists yet. Would need a new agent threading prior turns as context into each `agentai.complete` call.
     - **Test**: Not applicable.

5. **Summarization**
   - **Specifics**: No dedicated summarization agent. Would route through `agentai.complete` with a summarization-specific prompt; `CycleAgent`'s verify/optimize stages already do a lightweight form of this (condensing a task+result+critique into a verdict).
   - **Testing Plan**:
     - **Exp**: Confirmed indirectly.
       - **Tasks**: Inspect verify-stage verdicts from the live `CycleAgent` run.
       - **Tools**: `agents/loop_orchestrator.py` (`_verify`).
       - **Evaluation**: Verdicts were accurate, concise summaries of whether output matched task intent (correctly flagged the "make a video" step as unachievable).
     - **Beta/Test**: Not built as a standalone capability.

6. **Translation**
   - **Specifics**: Not a current focus of this project. Would work today via `agentai.complete` with a translation system prompt — no dedicated agent or testing has been done.
   - **Testing Plan**: Untested at all tiers. **Tools** if built: same bridge path as every other capability — no new infrastructure needed, just a prompt template.

7. **Sentiment Analysis**
   - **Specifics**: Not implemented. Nexus Trinity's Gate 6 (Adversarial Challenge) is the closest analog — it evaluates a claim's *validity* rather than *sentiment*, using a hostile-reviewer system prompt.
   - **Testing Plan**: Untested as sentiment analysis specifically.
     - **Tools** (if reused): `nexus_trinity_plugin.py` `_GATES[6]` system prompt pattern, `_KILL_PATTERNS`.
     - **Evaluation**: Gate 6's adversarial-verdict pattern is proven by inspection but not exercised live this session.

8. **Text Classification**
   - **Specifics**: Nexus Trinity's fast kill-pattern matcher (`_kill_pattern_fast()`) is a real, working text classifier — it categorizes a hypothesis/output into one of 6 known-invalid patterns via keyword matching before any LLM call.
   - **Testing Plan**:
     - **Exp**: Confirmed.
       - **Tasks**: Trace `_kill_pattern_fast()`'s regex/substring logic against known trigger phrases.
       - **Tools**: `nexus_trinity_plugin.py`.
       - **Evaluation**: Deterministic, unit-testable — matches "flash accounting net-zero," `assertTrue(true)`, etc. by construction.
     - **Beta/Test**: Not yet exercised against a real contest hypothesis in this session.

### Advanced Features

9. **Code Generation**
   - **Specifics**: Nexus Trinity Gate 3 generates complete Foundry fork-test PoCs from a strict template (`_GATES[3]` system prompt) — real code generation with hard constraints (no mocks, assertion must be able to fail, exact forge command required).
   - **Testing Plan**:
     - **Exp**: Confirmed.
       - **Tasks**: Verify the Gate 3 prompt/template produces the required SPDX/pragma/imports/setUp shape.
       - **Tools**: `nexus_trinity_plugin.py` `_build_prompt(3, ...)`.
       - **Evaluation**: Template inspected and verified this session; not yet run against a live model.
     - **Beta**: Not yet.
       - **Tasks**: Dispatch `nexus.hypothesis` for a real vulnerability, run Gate 3, capture the generated Foundry test.
       - **Tools**: `agentai_loader.py` → `model_router.complete(gate=3, code=True)`.
       - **Evaluation**: Would check the output compiles with `forge build`.
     - **Test**: Not yet — reproducibility (Gate 7) depends on Gate 3 working correctly first.
       - **Tools**: `nexus_trinity_plugin.py` `_GATES[7]` (Foundry CI verification).

10. **Debugging Assistance**
    - **Specifics**: No dedicated debugging agent for *user* code. `AuditTrailAgent` (`agents/logging_agent.py`) gives full causal message-chain replay via sqlite, which is the actual debugging surface for this system's own behavior.
    - **Testing Plan**: Confirmed working.
      - **Tasks**: Run a live kernel session, dispatch several messages, then query `var/audit.db`.
      - **Tools**: `core/audit_store.py`, `agents/logging_agent.py`.
      - **Evaluation**: 780+ rows persisted and queryable with correct `cid`/`parent_cid` causal chains in the live test this session.

11. **Creative Writing**
    - **Specifics**: General `agentai.complete` capability — no dedicated agent.
    - **Testing Plan**: **Exp/Beta** confirmed.
      - **Tasks**: Run a `CycleAgent` goal that includes a creative-writing step, then check the verify stage's verdict.
      - **Tools**: `agents/loop_orchestrator.py`.
      - **Evaluation**: Live test generated a genuinely creative poem as one task output, correctly verified PASS.

12. **Academic Assistance**
    - **Specifics**: Not a project focus; would work generically through `agentai.complete`.
    - **Testing Plan**: Untested at all tiers.

13. **Technical Documentation**
    - **Specifics**: This file and `README.md` were produced this way — describing the system's real architecture directly rather than through a dedicated agent.
    - **Testing Plan**: **Exp** confirmed by existence of `README.md` and this file. **Beta/Test**: not applicable — no automated doc-generation agent exists.

### Integration Features

14. **APIs and SDKs**
    - **Specifics**: `plugins/webapi_plugin.py` exposes bus/graph state over `http://0.0.0.0:8000`. `agentai.complete`/`agentai.embed` are the internal SDK surface — any agent gets LLM completions and embeddings without importing `model_router` directly.
    - **Testing Plan**: **Exp** confirmed.
      - **Tasks**: Boot the kernel, confirm the HTTP listener starts, dispatch `agentai.complete`/`agentai.embed` and check the reply shape.
      - **Tools**: `plugins/webapi_plugin.py`, `plugins/agentai_bridge_plugin.py`, `core/bus_rpc.py`.
      - **Evaluation**: `[webapi] HTTP API running at http://0.0.0.0:8000` confirmed at boot; bridge round-trips confirmed correct (`tier`/`route` metadata present) this session.
      - **Beta/Test**: Not yet — no external client has actually called the HTTP API; only internal bus messages have been exercised.

15. **Webhooks and Integrations**
    - **Specifics**: The `AgentBus` pub/sub model is the webhook layer — any plugin subscribes to any message type and reacts. `core/plugin_manager.py` auto-discovers `plugins/*.py` at boot. `core/agentai_loader.py` bridges to the sibling `~/AgentAI` project despite both sharing a top-level `core` package name.
    - **Testing Plan**: **Exp/Beta** confirmed.
      - **Tasks**: Fix the `core` package collision, verify `sys.modules['core']` is correctly restored after loading AgentAI's `model_router`.
      - **Tools**: `core/agentai_loader.py`.
      - **Evaluation**: Confirmed this session — was silently broken before (bridge always reported "unavailable"); now round-trips correctly and the AetherionGenesis kernel's own `core` package is unaffected afterward.
      - **Test**: Not yet — no external webhook source (e.g. GitHub, Slack) has been wired in, only internal plugin-to-plugin messaging.

### User Experience Features

16. **Personalization**
    - **Specifics**: `bus.graph` (MemoryGraph) and `bus.vmemory` (VectorMemory) give every agent shared persistent state — `CycleAgent`'s Discovery stage queries past cycles by semantic similarity before planning.
    - **Testing Plan**: **Exp** confirmed.
      - **Tasks**: Run a cycle, inspect `bus.graph.graph.number_of_nodes()`/`edges()` before and after, and confirm `agentai.embed` + `vmemory.search()` return related past entries.
      - **Tools**: `core/memory_graph.py`, `core/vector_memory.py`, `agents/loop_orchestrator.py` (`_discover`).
      - **Evaluation**: Graph counts and embed-based similarity search both ran correctly in the live test (0 related memories on a fresh graph, as expected for a first run).
      - **Beta/Test**: Not yet — needs multiple real cycles accumulated to validate that similarity search actually surfaces useful prior context.

17. **Multimodal Support**
    - **Specifics**: `agents/perception_agent.py` (`SensorAgent`) watches a directory for images and routes them through classification into the memory graph. Text and image only — no audio/video.
    - **Testing Plan**: Not runnable currently.
      - **Tools**: `watchdog` (Python package) — not installed in this uv-managed environment.
      - **Evaluation**: Degrades gracefully (prints a clear message, doesn't crash boot) rather than failing; classification itself is a stub (`_classify_stub`) pending a real vision model call.

18. **Voice Interaction**
    - **Specifics**: Not implemented — no speech-to-text/voice pipeline exists in this codebase.
    - **Testing Plan**: Not applicable.

### Security Features

19. **Data Privacy**
    - **Specifics**: Local-first: with `ANTHROPIC_API_KEY` unset, every LLM call and embedding runs on-device via Ollama. `core/audit_store.py` gives an append-only local audit ledger with causal lineage.
    - **Testing Plan**: **Exp/Beta** confirmed.
      - **Tasks**: Run the full pipeline with no `ANTHROPIC_API_KEY` set and check `model_router`'s `_last_route` on every call.
      - **Tools**: `~/AgentAI/core/model_router.py` (`status()`, `_last_route`).
      - **Evaluation**: All completions this session routed locally (`route=qwen` in logs) — confirmed no cloud calls occurred.
      - **Test**: Not yet — no formal encryption-at-rest or access-control audit of `var/audit.db` (currently a plain local sqlite file).

20. **Ethical Use Policies**
    - **Specifics**: Nexus Trinity's 6 hardcoded kill patterns prevent surfacing known-invalid findings. The SCOUT model set bakes "operator-authorization hardening" into system prompts.
    - **Testing Plan**: **Known gap**, not a passed tier.
      - **Tasks**: Review `plugins/meta_learning_plugin.py`'s `evaluate_candidate()`, which writes LLM-generated code to disk and imports it unreviewed.
      - **Tools**: `plugins/meta_learning_plugin.py`.
      - **Evaluation**: Flagged this session as a real arbitrary-code-execution risk; not yet sandboxed or gated behind review.

### Monitoring and Maintenance

21. **Performance Monitoring**
    - **Specifics**: `agents/heartbeat_agent.py` (`PulseMonitor`) tracks per-message-type liveness, raises `agent_silent` alerts on timeout. `model_router.py`'s per-backend circuit breakers (Anthropic, DeepSeek, Qwen, Gemma4) open after repeated failures and auto-reset.
    - **Testing Plan**: **Exp** confirmed.
      - **Tasks**: Trigger repeated failures against a backend and observe the circuit breaker state.
      - **Tools**: `~/AgentAI/core/model_router.py` (`_CircuitBreaker`).
      - **Evaluation**: Circuit breaker actually tripped during this session's debugging (`[CircuitBreaker] qwen OPEN after 3 failures — pausing 45s`) and recovered correctly once the underlying `think=True` bug was fixed.
      - **Beta/Test**: Not yet — no sustained-load test of the breaker thresholds/reset timing.

22. **Regular Updates**
    - **Specifics**: No automated retraining/update pipeline. Local models updated manually via `ollama pull <model>`; SCOUT hardened models rebuilt via `scripts/hp_setup.sh`.
    - **Testing Plan**: Not applicable — manual process, not a tested system capability.

### Complete Testing Plan

1. **Experimental (Exp)** — *largely complete as of this session*
   - **Objective**: Validate that the core plumbing works at all — bus, bridge, agents wired correctly, no silent failures.
   - **Tasks done**: Fixed the `core` package name collision that silently broke the AgentAI bridge and Nexus Trinity end-to-end (`core/agentai_loader.py`). Fixed the Ollama `think=True` 400 error in `model_router.py`. Rebuilt all 5 `agents/*.py` from stubs into real bus-wired agents. Verified `agentai.complete`/`agentai.embed` round-trip locally with no API key.
   - **Tools used**: `core/agentai_loader.py`, `core/bus_rpc.py`, direct `python3 -c` boot scripts against `core/kernel.py`.
   - **Evaluation**: All of the above reproduced live and logged in this session; no open Exp-tier gaps identified.

2. **Beta** — *partially complete*
   - **Objective**: Exercise features under realistic, multi-step conditions and confirm they fail honestly rather than silently.
   - **Tasks done**: Live end-to-end `CycleAgent` run (discovery→plan→execute→verify→optimize→state→memory→integrate) on a 5-step real goal.
   - **Tools used**: `agents/loop_orchestrator.py`, `plugins/goal_agent_plugin.py`, `plugins/scheduler_plugin.py`/`persistence_plugin.py` (tick→graph persistence).
   - **Evaluation**: Verify stage correctly flagged a genuinely unachievable step (asked for a video, got FAIL, not a hallucinated PASS); optimize stage retried it; memory graph updated correctly (7 nodes after one cycle).
   - **Remaining**: `continuous=True` multi-cycle looping is implemented but never run live. `watchdog`, `deap`, `faiss` aren't installed in this environment, so perception, meta-learning, and vector-memory-storage paths degrade gracefully but are untested beyond the degrade path itself.

3. **Test** — *not started*
   - **Objective**: Full-complexity, production-grade validation — the bar for trusting a Nexus Trinity finding or an unattended multi-cycle loop run.
   - **Remaining tasks**: A real `nexus.pipeline` run (all 7 gates) against a live contract has not happened this session — only Gate 1 (hypothesis) has been exercised, indirectly, via the loop orchestrator's DeFi-shaped-step routing.
   - **Tools needed**: `nexus_trinity_plugin.py` full pipeline, a real target contract + Foundry fork setup, sandboxing for `meta_learning_plugin.py`'s code-write-and-import path.
   - **Evaluation criteria**: A finding survives all 7 gates end-to-end; circuit breakers hold up under sustained induced failure; `watchdog`/`deap`/`faiss` installed and their dependent agents verified live.
