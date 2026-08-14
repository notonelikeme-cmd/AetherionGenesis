# agents/loop_orchestrator.py
"""
CycleAgent — drives the full agent loop:

  discovery > plan > execute > verify > optimize > state > memory > integrate >> loop

Trigger with a 'loop_start' message: {'goal': '<description>', 'continuous': bool}.

Each stage reuses infrastructure that already exists elsewhere in the
system (MemoryGraph, VectorMemory, GoalAgent, the AgentAI bridge,
Nexus Trinity) rather than reimplementing it — this agent is the
conductor, not a new instrument:

  discovery  -> bus.graph size + bus.vmemory similarity search
  plan       -> 'goal' message -> GoalAgent -> 'goal_result'
  execute    -> DeFi-shaped steps go to nexus.hypothesis (Gate 1);
                orchestration-shaped steps spawn a capped sub-cycle;
                everything else goes through agentai.complete
  verify     -> agentai.complete asked to give a PASS/FAIL verdict
  optimize   -> one retry pass on FAILs, using the verdict as critique
  integrate  -> writes goal/task/verdict nodes+edges into bus.graph
  state      -> dispatches 'tick' (drives PersistenceAgent to persist
                bus.graph to disk) — runs after integrate so the
                persisted graph includes this cycle's nodes/edges
  memory     -> dispatches 'cycle_result' (VectorMemoryAgent embeds
                and stores it automatically)
  loop       -> emits 'loop_result'; if continuous and something
                failed, re-enters at discovery with a follow-up goal

Steering: send a 'cycle.steer' message {goal_id, instruction} while a
goal is in flight. Instructions queue FIFO and are drained (a) at the
start of each _plan() call and (b) before each step in _execute() —
so a correction lands on the next step without killing the run, and
a queue of corrections left while you're away drains in order as the
cycle progresses.
"""
import os
import threading
import time
import uuid

from core.agent_base import Agent
from core.message import new_message
from core.bus_rpc import call as bus_call
from core import goal_store, task_store

MAX_ORCHESTRATOR_DEPTH = 2
MAX_FANOUT = 5

_ORCHESTRATION_KEYWORDS = ("for each", "spawn", "assign a specialist", "delegate to", "in parallel", "sub-agent", "recruit")


class CycleAgent(Agent):
    def __init__(self, bus):
        super().__init__(name="loop_orchestrator")
        self.bus = bus
        self._steer_queues = {}
        self._steer_lock = threading.Lock()
        bus.register(self, subscriptions={"loop_start", "cycle.steer"})

        if os.environ.get("RESUME_GOALS"):
            for g in goal_store.get_active():
                print(f"[loop_orchestrator] resuming goal #{g['id']}: {g['description']}")
                threading.Thread(
                    target=self._run_cycle_loop,
                    args=(g["description"], g["continuous"], g["id"]),
                    daemon=True,
                ).start()

    def handle(self, message_type, message):
        payload = getattr(message, "payload", message)
        if not isinstance(payload, dict):
            return

        if message_type == "cycle.steer":
            goal_id = payload.get("goal_id")
            instruction = payload.get("instruction", "")
            if goal_id is None or not instruction:
                return
            with self._steer_lock:
                self._steer_queues.setdefault(goal_id, []).append(instruction)
            print(f"[loop_orchestrator] steer queued for goal #{goal_id}: {instruction}")
            self.bus.dispatch("cycle.steer_queued", new_message("cycle.steer_queued", {"goal_id": goal_id}))
            return

        if message_type != "loop_start":
            return
        goal = payload.get("goal", "")
        continuous = bool(payload.get("continuous", False))
        goal_id = payload.get("goal_id") or goal_store.create(goal, continuous)
        threading.Thread(target=self._run_cycle_loop, args=(goal, continuous, goal_id), daemon=True).start()

    def _drain_steer(self, goal_id):
        with self._steer_lock:
            instructions = self._steer_queues.get(goal_id, [])
            self._steer_queues[goal_id] = []
        return instructions

    def _run_cycle(self, goal, continuous, goal_id, depth=0):
        cycle_id = str(uuid.uuid4())[:8]
        print(f"[cycle {cycle_id}] === starting (depth={depth}): {goal}")

        context = self._discover(goal, cycle_id)
        steps = self._plan(goal, cycle_id, goal_id)
        results = self._execute(steps, cycle_id, goal_id, depth)
        results = self._verify(results, cycle_id)
        results = self._optimize(results, cycle_id)
        next_goal = self._integrate(cycle_id, goal, results)
        self._state(cycle_id)
        self._memory(cycle_id, goal, results)

        all_passed = all(r["verdict"].upper().startswith("PASS") for r in results) if results else True

        # Sub-cycles (depth > 0) don't own the goal's lifecycle — the
        # top-level caller (_execute_via_subcycle) reads `results` and
        # `next_goal` directly instead of relying on goal_store state.
        if depth == 0:
            if all_passed:
                goal_store.update(goal_id, "done", latest_cycle_id=cycle_id)
            elif continuous and next_goal:
                goal_store.update(goal_id, "active", latest_cycle_id=cycle_id)
            else:
                goal_store.update(goal_id, "needs_attention", latest_cycle_id=cycle_id)

            self.bus.dispatch("loop_result", new_message("loop_result", {
                "cycle_id": cycle_id, "goal": goal, "goal_id": goal_id, "results": results, "next_goal": next_goal,
            }))

        print(f"[cycle {cycle_id}] === complete (depth={depth}, {sum(1 for r in results if r['verdict'].upper().startswith('PASS'))}/{len(results)} passed)")

        return results, next_goal

    def _run_cycle_loop(self, goal, continuous, goal_id):
        """Entry point for depth-0 cycles. A continuous goal that keeps
        producing a follow-up iterates here instead of _run_cycle calling
        itself — Python has no tail-call optimization, so a long or
        endlessly-failing continuous run would otherwise grow the call
        stack until RecursionError."""
        current_goal = goal
        while True:
            results, next_goal = self._run_cycle(current_goal, continuous, goal_id, depth=0)
            if not (continuous and next_goal):
                return results, next_goal
            current_goal = next_goal

    # ---- Discovery ----------------------------------------------------------

    def _discover(self, goal, cycle_id):
        """Snapshot what the system already knows before planning."""
        graph = getattr(self.bus, "graph", None)
        node_count = graph.graph.number_of_nodes() if graph else 0
        edge_count = graph.graph.number_of_edges() if graph else 0

        related = []
        msg_type, reply = bus_call(
            self.bus, "agentai.embed", {"agent_id": "loop_orchestrator", "text": goal},
            reply_types={"agentai.embed_result"}, timeout=15,
        )
        vmemory = getattr(self.bus, "vmemory", None)
        if msg_type == "agentai.embed_result" and vmemory is not None and reply.get("vector"):
            try:
                related = [meta for meta, _dist in vmemory.search(reply["vector"], k=3)]
            except Exception as e:
                print(f"[cycle {cycle_id}] discovery: memory search failed: {e}")

        print(f"[cycle {cycle_id}] discovery: graph={node_count}n/{edge_count}e, {len(related)} related memories")
        return {"graph_nodes": node_count, "graph_edges": edge_count, "related": related}

    # ---- Plan -----------------------------------------------------------------

    def _plan(self, goal, cycle_id, goal_id):
        steering = self._drain_steer(goal_id)
        effective_goal = goal
        if steering:
            note = " ".join(steering)
            effective_goal = f"{goal}\n\nSteering notes from the operator (apply these): {note}"
            print(f"[cycle {cycle_id}] plan: applying {len(steering)} steering note(s)")

        msg_type, reply = bus_call(
            self.bus, "goal", {"description": effective_goal}, reply_types={"goal_result"}, timeout=60,
        )
        steps = reply.get("steps", [goal]) if msg_type == "goal_result" else [goal]
        if msg_type != "goal_result":
            print(f"[cycle {cycle_id}] plan: goal agent unavailable ({msg_type}), using goal as single step")
        print(f"[cycle {cycle_id}] plan: {len(steps)} step(s)")
        return steps

    # ---- Execute --------------------------------------------------------------

    def _execute(self, steps, cycle_id, goal_id, depth):
        results = []
        for i, step in enumerate(steps):
            steering = self._drain_steer(goal_id)
            if steering:
                step = f"{step}\n\nSteering notes from the operator (apply these): {' '.join(steering)}"
                print(f"[cycle {cycle_id}] execute: applying {len(steering)} steering note(s) to step {i}")

            task_store.upsert(cycle_id, i, step, "running")
            if self._looks_like_orchestration(step) and depth < MAX_ORCHESTRATOR_DEPTH:
                output, verdict = self._execute_via_subcycle(step, cycle_id, goal_id, depth)
            elif self._looks_like_defi_hypothesis(step):
                output, verdict = self._execute_via_nexus(step, cycle_id), None
            else:
                output, verdict = self._execute_via_completion(step, cycle_id), None
            task_store.upsert(cycle_id, i, step, "executed", output=output)
            results.append({"step": step, "output": output, "verdict": verdict})
        return results

    @staticmethod
    def _looks_like_defi_hypothesis(step):
        s = step.lower()
        return any(k in s for k in ("vulnerability", "exploit", "reentrancy", "hypothesis", "vault", "flash loan"))

    @staticmethod
    def _looks_like_orchestration(step):
        s = step.lower()
        return any(k in s for k in _ORCHESTRATION_KEYWORDS)

    def _execute_via_nexus(self, step, cycle_id):
        """Runs Gate 1 (hypothesis formation) only — a full 7-gate run is a
        deliberate follow-up (nexus.pipeline), not something a generic loop
        step should trigger blindly."""
        msg_type, reply = bus_call(
            self.bus, "nexus.hypothesis", {"hypothesis": step, "contract_path": "", "code": ""},
            reply_types={"nexus.gate_result"}, timeout=90,
        )
        if msg_type == "nexus.gate_result":
            return reply.get("output", "")
        print(f"[cycle {cycle_id}] execute: nexus bridge unavailable ({msg_type})")
        return None

    def _execute_via_completion(self, step, cycle_id, fast=False):
        msg_type, reply = bus_call(
            self.bus, "agentai.complete",
            {"agent_id": "loop_orchestrator", "prompt": f"Carry out this task and report the concrete result:\n{step}", "think": not fast, "fast": fast},
            reply_types={"agentai.result"}, timeout=60,
        )
        if msg_type == "agentai.result":
            return reply.get("result", "")
        print(f"[cycle {cycle_id}] execute: bridge unavailable ({msg_type}) for step: {step}")
        return None

    def _execute_via_subcycle(self, step, cycle_id, goal_id, depth):
        """Orchestrator role: decompose this single step into up to
        MAX_FANOUT sub-goals (reusing GoalAgent, same as top-level
        planning) and run a capped sub-cycle per sub-goal, then
        aggregate. depth is bounded by MAX_ORCHESTRATOR_DEPTH so this
        can never recurse unboundedly."""
        msg_type, reply = bus_call(
            self.bus, "goal", {"description": step}, reply_types={"goal_result"}, timeout=60,
        )
        sub_goals = reply.get("steps", [step])[:MAX_FANOUT] if msg_type == "goal_result" else [step]
        print(f"[cycle {cycle_id}] execute: orchestrating {len(sub_goals)} sub-cycle(s) at depth {depth + 1}")

        graph = getattr(self.bus, "graph", None)
        parent_task_node = f"task:{cycle_id}:orchestrated:{uuid.uuid4().hex[:6]}"

        sub_summaries = []
        all_sub_passed = True
        for sub_goal in sub_goals:
            sub_results, _next = self._run_cycle(sub_goal, continuous=False, goal_id=goal_id, depth=depth + 1)
            sub_passed = all(r["verdict"].upper().startswith("PASS") for r in sub_results) if sub_results else False
            all_sub_passed = all_sub_passed and sub_passed
            sub_summaries.append({"sub_goal": sub_goal, "passed": sub_passed, "steps": len(sub_results)})
            if graph is not None:
                graph.add_edge(parent_task_node, f"goal:{sub_goal[:40]}", "spawned")

        output = f"Orchestrated {len(sub_goals)} sub-cycle(s): " + "; ".join(
            f"{'PASS' if s['passed'] else 'FAIL'} — {s['sub_goal']}" for s in sub_summaries
        )
        verdict = "PASS: all sub-cycles passed" if all_sub_passed else "FAIL: one or more sub-cycles failed"
        return output, verdict

    # ---- Verify -----------------------------------------------------------------

    def _verify_step(self, r):
        if r["output"] is None:
            return "FAIL: no output produced"
        msg_type, reply = bus_call(
            self.bus, "agentai.complete",
            {
                "agent_id": "loop_orchestrator",
                "system": "You are a strict verifier. Reply with exactly PASS or FAIL: <reason>.",
                "prompt": f"Task: {r['step']}\n\nResult: {r['output']}\n\nDoes the result actually accomplish the task?",
            },
            reply_types={"agentai.result"}, timeout=45,
        )
        return reply.get("result", "").strip() if msg_type == "agentai.result" else "UNVERIFIED (bridge unavailable)"

    def _verify(self, results, cycle_id):
        for r in results:
            if r["verdict"] is not None:
                continue  # orchestrated sub-cycle steps already carry a verdict
            r["verdict"] = self._verify_step(r)
        for i, r in enumerate(results):
            status = "passed" if r["verdict"].upper().startswith("PASS") else "failed"
            task_store.upsert(cycle_id, i, r["step"], status, output=r["output"], verdict=r["verdict"])
        passed = sum(1 for r in results if r["verdict"].upper().startswith("PASS"))
        print(f"[cycle {cycle_id}] verify: {passed}/{len(results)} passed")
        return results

    # ---- Optimize ---------------------------------------------------------------

    def _optimize(self, results, cycle_id):
        """One retry pass for failed steps, using the verify verdict as critique."""
        for i, r in enumerate(results):
            if r["verdict"].upper().startswith("PASS"):
                continue
            msg_type, reply = bus_call(
                self.bus, "agentai.complete",
                {
                    "agent_id": "loop_orchestrator",
                    "prompt": f"Task: {r['step']}\n\nPrevious attempt: {r['output']}\n\nCritique: {r['verdict']}\n\nProduce an improved result.",
                    "think": True,
                },
                reply_types={"agentai.result"}, timeout=60,
            )
            if msg_type == "agentai.result":
                r["output"] = reply.get("result", r["output"])
                r["verdict"] = self._verify_step(r) + " (retried)"
                task_store.upsert(cycle_id, i, r["step"], "retried", output=r["output"], verdict=r["verdict"])
        return results

    # ---- State ---------------------------------------------------------------------

    def _state(self, cycle_id):
        # count/timestamp match the shape plugins/scheduler_plugin.py and
        # persistence_plugin.py already expect from a 'tick' message.
        self.bus.dispatch("tick", new_message("tick", {
            "schedule": "cycle", "cycle_id": cycle_id, "count": 0, "timestamp": time.time(),
        }))

    # ---- Memory ---------------------------------------------------------------------

    def _memory(self, cycle_id, goal, results):
        self.bus.dispatch("cycle_result", new_message("cycle_result", {
            "cycle_id": cycle_id, "goal": goal, "results": results,
        }))

    # ---- Integrate --------------------------------------------------------------------

    def _integrate(self, cycle_id, goal, results):
        graph = getattr(self.bus, "graph", None)
        if graph is not None:
            goal_node = f"goal:{cycle_id}"
            graph.add_node(goal_node, {"type": "goal", "description": goal})
            for i, r in enumerate(results):
                task_node = f"task:{cycle_id}:{i}"
                graph.add_node(task_node, {"type": "task", "description": r["step"], "verdict": r["verdict"]})
                graph.add_edge(goal_node, task_node, "decomposes_to")

        failed = [r for r in results if not r["verdict"].upper().startswith("PASS")]
        if failed:
            return f"Address remaining gaps from '{goal}': " + "; ".join(r["step"] for r in failed)
        return None
