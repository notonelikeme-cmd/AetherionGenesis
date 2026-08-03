# plugins/meta_learning_plugin.py

import os
import time
import random
import importlib
from deap import base, creator, tools
from core.agent_base import Agent
from core.message import Message
from core.bus_rpc import call as bus_call


class MetaLearningAgent(Agent):
    """
    Auto-generates, tests, and installs new agent plugins via LLM +
    genetic search. Code generation runs through the AgentAI bridge
    (agentai.complete → claude-fable-5 or local Ollama fallback)
    instead of a direct OpenAI call.

    NOTE: evaluate_candidate() writes LLM-generated code to disk and
    imports it unreviewed. That was true before this change too — it's
    a real risk (arbitrary code execution from model output) worth
    sandboxing or gating behind manual review before this runs
    unattended.
    """
    def __init__(self, name, bus, population=5, generations=3):
        super().__init__(name)
        self.bus = bus
        self.population = population
        self.generations = generations
        bus.register_agent(name, self)

    def handle(self, message_type, message):
        if message_type != 'meta_train':
            return

        creator.create("FitnessMax", base.Fitness, weights=(1.0,))
        creator.create("Individual", list, fitness=creator.FitnessMax)
        toolbox = base.Toolbox()
        toolbox.register("attr_prompt", self.random_prompt)
        toolbox.register("individual", tools.initRepeat, creator.Individual, toolbox.attr_prompt, n=3)
        toolbox.register("population", tools.initRepeat, list, toolbox.individual)
        toolbox.register("evaluate", self.evaluate_candidate)
        toolbox.register("mate", tools.cxTwoPoint)
        toolbox.register("mutate", tools.mutShuffleIndexes, indpb=0.2)
        toolbox.register("select", tools.selBest)

        pop = toolbox.population(n=self.population)
        for _ in range(self.generations):
            fitnesses = list(map(toolbox.evaluate, pop))
            for ind, fit in zip(pop, fitnesses):
                ind.fitness.values = (fit,)
            pop = toolbox.select(pop, k=self.population)
            offspring = tools.selRoulette(pop, k=self.population)
            offspring = list(map(toolbox.clone, offspring))
            for child1, child2 in zip(offspring[::2], offspring[1::2]):
                if random.random() < 0.5:
                    toolbox.mate(child1, child2)
                toolbox.mutate(child1)
            pop[:] = offspring

        best = tools.selBest(pop, k=1)[0]
        self.bus.dispatch('meta_result', Message(type='meta_result', payload={'best': best}))

    def random_prompt(self):
        return "Write a Python Agent plugin for Aetherion that logs every message with timestamp."

    def evaluate_candidate(self, individual):
        prompt = "\n".join(individual)
        msg_type, reply = bus_call(
            self.bus,
            request_type="agentai.complete",
            payload={"agent_id": "meta_learning", "prompt": prompt, "code": True},
            reply_types={"agentai.result"},
            timeout=60,
        )
        if msg_type != "agentai.result":
            print(f"[MetaLearningAgent] bridge unavailable/timed out ({msg_type}), fitness=0")
            return 0.0

        code = reply.get("result", "")
        fname = f"plugins/gen_{int(time.time())}.py"
        with open(fname, 'w') as f:
            f.write(code)
        try:
            importlib.import_module(f"plugins.{os.path.basename(fname)[:-3]}")
            start = time.time()
            self.bus.dispatch('heartbeat', Message(type='heartbeat', payload={}))
            duration = time.time() - start
            return max(0.0, 1.0 - duration)
        except Exception:
            return 0.0


def register(bus):
    MetaLearningAgent('meta_learning', bus)
