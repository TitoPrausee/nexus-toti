"""
NEXUS v8.2 — Agent Team System
Unternehmen-Struktur: CEO, Research, Engineering, Creative, Operations.
Each department uses specialist models via Ollama Cloud.
Self-improvement: if Nexus can't do something, it delegates or researches how to.
"""

import logging
import time
from typing import Optional, List
from dataclasses import dataclass

from nexus.core.llm_client import LLMClient, Message, LLMResponse

log = logging.getLogger("nexus.team")


@dataclass
class TeamTask:
    """A task assigned to a team department."""
    task_id: str
    description: str
    department: str
    priority: int = 5  # 1=critical, 5=low
    status: str = "pending"  # pending, in_progress, completed, failed
    result: str = ""
    elapsed: float = 0.0


class AgentTeam:
    """
    Unternehmen-artige Agent-Organisation.
    
    Abteilungen:
    - CEO: Priorisiert, entscheidet, delegiert
    - Research: Recherchiert, analysiert, findet Fakten
    - Engineering: Codet, baut, fixt, deployed
    - Creative: Design, Text, Präsentationen
    - Operations: Verwaltung, Monitoring, Planung
    
    Self-Improvement Loop:
    Wenn Nexus etwas nicht kann → Research rechschiert Lösung → 
    Engineering baut es → Operations integriert es.
    """

    DEPARTMENTS = {
        "ceo": {
            "name": "CEO",
            "model": "orchestrator",
            "role": "Entscheidet Prioritaeten, delegiert Aufgaben, prueft Ergebnisse.",
            "max_turns": 2,
        },
        "research": {
            "name": "Research",
            "model": "allrounder",
            "role": "Recherchiert Fakten, analysiert, beschafft Informationen. "
                     "Nutzt web_search und web_fetch um aktuelle Daten zu finden.",
            "max_turns": 3,
        },
        "engineering": {
            "name": "Engineering",
            "model": "coding",
            "role": "Schreibt Code, baut Features, fixt Bugs, deployed. "
                     "Nutzt terminal, file_write, code_exec.",
            "max_turns": 5,
        },
        "creative": {
            "name": "Creative",
            "model": "creative",
            "role": "Design, Texte, UI/UX, Praesentationen. "
                     "Kreativ und professionell.",
            "max_turns": 3,
        },
        "operations": {
            "name": "Operations",
            "model": "fast",
            "role": "Planung, Organisation, Monitoring, Reporting. "
                     "Schnell und effizient.",
            "max_turns": 2,
        },
    }

    def __init__(self, llm: LLMClient, config: dict = None):
        self.llm = llm
        self.config = config or {}
        self._task_history = []  # type: List[TeamTask]
        self._task_counter = 0

    def _next_task_id(self) -> str:
        self._task_counter += 1
        return f"T{self._task_counter:04d}"

    def delegate(self, task_description: str, department: str = "auto",
                 context: str = "") -> TeamTask:
        """
        Delegate a task to a department.
        If department='auto', CEO decides which department handles it.
        """
        task_id = self._next_task_id()

        if department == "auto":
            department = self._ceo_classify(task_description, context)

        if department not in self.DEPARTMENTS:
            department = "research"  # safe default

        dept = self.DEPARTMENTS[department]
        task = TeamTask(
            task_id=task_id,
            description=task_description,
            department=department,
        )
        task.status = "in_progress"
        start = time.time()

        # Build specialist prompt
        system_prompt = (
            f"Du bist {dept['name']} bei Nexus. {dept['role']}\n"
            f"Antworte direkt und ergebnisorientiert. Keine Einleitung, keine Floskeln.\n"
            f"Liefere konkrete Ergebnisse, keine Beschreibungen was du tun wuerdest.\n"
        )
        if context:
            system_prompt += f"\nKontext: {context}\n"

        messages = [
            Message("system", system_prompt),
            Message("user", task_description),
        ]

        response = self.llm.chat(messages, model_key=dept["model"])

        if response.success:
            task.result = response.content
            task.status = "completed"
        else:
            task.result = f"Fehler: {response.error}"
            task.status = "failed"

        task.elapsed = time.time() - start
        self._task_history.append(task)
        log.info(f"Team task {task_id} -> {dept['name']}: {task.status} ({task.elapsed:.1f}s)")

        return task

    def research_and_build(self, task_description: str, context: str = "") -> str:
        """
        Self-improvement loop: Research how to do something, then build it.
        
        1. CEO: Classify and plan
        2. Research: Find out how (if unknown)
        3. Engineering: Build it
        4. Operations: Verify/report
        
        Returns combined result.
        """
        results = []

        # Phase 1: CEO planning
        plan_task = self.delegate(
            f"Analysiere diese Aufgabe und plane die Umsetzung. "
            f"Welche Abteilung muss was tun? Aufgabe: {task_description}",
            department="ceo",
            context=context,
        )
        if plan_task.status == "completed":
            results.append(f"[CEO] {plan_task.result}")

        # Phase 2: Research (if task requires knowledge)
        research_task = self.delegate(
            f"Recherchiere alles noetige fuer: {task_description}",
            department="research",
            context=context + "\n" + plan_task.result if plan_task.result else context,
        )
        if research_task.status == "completed":
            results.append(f"[Research] {research_task.result}")

        # Phase 3: Engineering (if task requires building/coding)
        eng_context = context
        if research_task.status == "completed":
            eng_context += "\n\nRecherche-Ergebnisse:\n" + research_task.result
        if plan_task.status == "completed":
            eng_context += "\n\nPlan:\n" + plan_task.result

        eng_task = self.delegate(
            f"Setze um: {task_description}",
            department="engineering",
            context=eng_context,
        )
        if eng_task.status == "completed":
            results.append(f"[Engineering] {eng_task.result}")

        return "\n\n".join(results)

    def _ceo_classify(self, task: str, context: str = "") -> str:
        """CEO classifies which department should handle a task."""
        messages = [
            Message("system",
                "Du bist der CEO. Klassifiziere welche Abteilung die Aufgabe bearbeiten soll. "
                "Antworte NUR mit einem Wort: ceo, research, engineering, creative, operations.\n\n"
                "research: Recherchieren, Fakten finden, Analysieren, Informieren\n"
                "engineering: Coden, Bauen, Fixen, Deployen, Technisch umsetzen\n"
                "creative: Design, Text, UI, Kreativ, Präsentation\n"
                "operations: Planen, Organisieren, Monitoring, Reporting\n"
                "ceo: Strategisch entscheiden, Priorisieren"),
            Message("user", f"Aufgabe: {task}\nKontext: {context[:500]}"),
        ]

        response = self.llm.chat(messages, model_key="fast")

        if response.success:
            content = response.content.strip().lower()
            for dept in self.DEPARTMENTS:
                if dept in content:
                    return dept

        return "research"  # safe default

    def get_team_status(self) -> str:
        """Get current team status summary."""
        total = len(self._task_history)
        completed = sum(1 for t in self._task_history if t.status == "completed")
        failed = sum(1 for t in self._task_history if t.status == "failed")
        dept_stats = {}
        for t in self._task_history:
            dept_stats.setdefault(t.department, {"count": 0, "avg_time": 0, "times": []})
            dept_stats[t.department]["count"] += 1
            dept_stats[t.department]["times"].append(t.elapsed)

        lines = ["**Nexus Team Status**", ""]
        for dept_name, info in self.DEPARTMENTS.items():
            stats = dept_stats.get(dept_name, {"count": 0, "times": []})
            count = stats["count"]
            avg = sum(stats["times"]) / len(stats["times"]) if stats["times"] else 0
            lines.append(f"  {info['name']}: {count} Aufgaben (Ø {avg:.1f}s)")

        lines.append("")
        lines.append(f"Gesamt: {total} Aufgaben, {completed} erfolgreich, {failed} fehlgeschlagen")
        return "\n".join(lines)