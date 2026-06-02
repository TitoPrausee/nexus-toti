"""
NEXUS Delegation Engine — Toti-style DAG Task Decomposition
"""

import time
import uuid
from typing import Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from .llm_client import LLMClient, Message
from .memory import MemorySystem
from .tools import ToolRegistry
from .state import StateManager


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    STUCK = "stuck"


@dataclass
class SubTask:
    task_id: str
    agent_id: str
    description: str
    context: str
    accept_if: str
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[dict] = None
    depends_on: list[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 2
    model_level: int = 1
    created_at: float = field(default_factory=time.time)


@dataclass
class DelegationPlan:
    plan_id: str
    parallel: list[SubTask]
    sequential: list[SubTask]
    output: Optional[SubTask] = None


class DelegationEngine:
    """Handles task decomposition and agent delegation."""

    AGENT_MAP = {"SCOUT": "scout", "FORGE": "forge", "LENS": "lens", "HERALD": "herald", "GHOST": "ghost"}

    def __init__(self, llm: LLMClient, memory: MemorySystem, tools: ToolRegistry):
        self.llm = llm
        self.memory = memory
        self.tools = tools
        self._agents: dict[str, Any] = {}

    def register_agent(self, agent_id: str, agent_instance: Any):
        self._agents[agent_id] = agent_instance

    def get_agent(self, agent_id: str) -> Any:
        return self._agents.get(agent_id)

    def decompose_task(self, task: str, context: Optional[str] = None) -> DelegationPlan:
        decomp_prompt = f"""Du bist ein Task-Decomposition-Engine. Zerlege die folgende Aufgabe in Sub-Tasks.

AUFGABE: {task}
{'KONTEXT: ' + context if context else ''}

Antworte AUSSCHLIESSLICH als JSON (kein Markdown, keine Erklärungen):
{{
  "parallel": [
    {{"agent": "SCOUT|FORGE|LENS|HERALD|GHOST", "task": "präzise Aufgabe", "context": "was der Agent wissen muss", "accept_if": "Kriterium", "model_level": 1}}
  ],
  "sequential": [
    {{"agent": "SCOUT|FORGE|LENS|HERALD|GHOST", "task": "Aufgabe", "context": "Kontext", "accept_if": "Kriterium", "depends_on": ["task_id"], "model_level": 1}}
  ],
  "output": {{
    "agent": "HERALD",
    "task": "Finale Aufbereitung",
    "context": "Ergebnisse zusammenführen",
    "accept_if": "Output ist klar"
  }}
}}

Regeln:
- Unabhängige Tasks → parallel (max 3)
- Abhängige Tasks → sequential
- model_level: 0=lokal, 1=fast, 2=standard, 3=heavy
- SCOUT=Recherche, FORGE=Code, LENS=Analyse, HERALD=Ausgabe, GHOST=Hintergrund"""

        messages = [
            Message(role="system", content="Du bist ein präziser Task-Decomposition-Engine. Antworte nur JSON."),
            Message(role="user", content=decomp_prompt),
        ]

        response = self.llm.chat(messages, level=2)
        return self._parse_decomposition(response.content, task)

    def _parse_decomposition(self, content: str, original_task: str) -> DelegationPlan:
        import json, re

        json_match = re.search(r'\{[\s\S]*\}', content)
        if not json_match:
            return DelegationPlan(
                plan_id=f"plan_{uuid.uuid4().hex[:8]}",
                parallel=[SubTask(
                    task_id=f"t_{uuid.uuid4().hex[:6]}", agent_id="SCOUT",
                    description=original_task, context=original_task,
                    accept_if="Ergebnis geliefert", model_level=1,
                )],
                sequential=[],
            )

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            return DelegationPlan(
                plan_id=f"plan_{uuid.uuid4().hex[:8]}",
                parallel=[SubTask(
                    task_id=f"t_{uuid.uuid4().hex[:6]}", agent_id="SCOUT",
                    description=original_task, context=original_task,
                    accept_if="Ergebnis geliefert", model_level=1,
                )],
                sequential=[],
            )

        plan_id = f"plan_{uuid.uuid4().hex[:8]}"

        def make_subtask(t: dict, idx: int, prefix: str) -> SubTask:
            return SubTask(
                task_id=t.get("task_id", f"{prefix}_{idx}"),
                agent_id=t.get("agent", "SCOUT"),
                description=t.get("task", ""),
                context=t.get("context", ""),
                accept_if=t.get("accept_if", "Ergebnis geliefert"),
                depends_on=t.get("depends_on", []),
                model_level=t.get("model_level", 1),
            )

        parallel = [make_subtask(t, i, "par") for i, t in enumerate(data.get("parallel", []))]
        sequential = [make_subtask(t, i, "seq") for i, t in enumerate(data.get("sequential", []))]
        output = make_subtask(data["output"], 0, "out") if "output" in data else None

        return DelegationPlan(plan_id=plan_id, parallel=parallel, sequential=sequential, output=output)

    def execute_plan(self, plan: DelegationPlan) -> dict:
        results: dict[str, dict] = {}

        # Phase 1: Parallel tasks
        for task in plan.parallel:
            result = self._execute_subtask(task)
            results[task.task_id] = result
            task.status = TaskStatus(result.get("status", "complete"))
            task.result = result

        # Phase 2: Sequential tasks
        for task in plan.sequential:
            dep_results = {dep_id: results[dep_id] for dep_id in task.depends_on if dep_id in results}
            if dep_results:
                task.context += "\n\n## DEPENDENCY RESULTS\n"
                for dep_id, dep_result in dep_results.items():
                    task.context += f"\n### {dep_id}\n{dep_result.get('result', 'No result')[:1000]}\n"
            result = self._execute_subtask(task)
            results[task.task_id] = result
            task.status = TaskStatus(result.get("status", "complete"))
            task.result = result

        # Phase 3: Output task
        if plan.output:
            all_results_str = "## ALL RESULTS\n\n"
            for tid, tres in results.items():
                all_results_str += f"### {tid}\n{tres.get('result', 'No result')[:1500]}\n\n"
            plan.output.context = all_results_str
            output_result = self._execute_subtask(plan.output)
            results[plan.output.task_id] = output_result
            plan.output.result = output_result

        if plan.output and plan.output.result:
            return plan.output.result
        return {"plan_id": plan.plan_id, "results": results}

    def _execute_subtask(self, task: SubTask) -> dict:
        agent = self._agents.get(task.agent_id)
        if not agent:
            return {"status": "failed", "agent": task.agent_id, "error": f"Agent '{task.agent_id}' not registered"}

        for attempt in range(task.max_retries + 1):
            try:
                result = agent.execute(
                    task=task.description, context=task.context,
                    accept_if=task.accept_if, level=task.model_level,
                )
                result["status"] = "complete"
                result["subtask_id"] = task.task_id
                self.memory.save_checkpoint(task.task_id, f"attempt_{attempt}", {
                    "result_preview": result.get("result", "")[:200], "status": "complete",
                })
                return result
            except Exception as e:
                task.retry_count += 1
                if attempt < task.max_retries:
                    continue
                return {"status": "failed", "agent": task.agent_id, "error": str(e), "retries": task.retry_count}

        return {"status": "failed", "agent": task.agent_id, "error": "Max retries exceeded"}
