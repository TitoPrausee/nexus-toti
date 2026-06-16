"""
NEXUS v9.2 — Agent Team System
Unternehmen-Struktur: CEO, Research, Engineering, Creative, Operations.
v9.2: Parallel delegation, complexity-based agent count, agent profiles.

Each department uses specialist models via Ollama Cloud.
Self-improvement: if Nexus can't do something, it delegates or researches how to.
Parallel execution: complex tasks are split across N agents using ThreadPoolExecutor.
"""

import logging
import time
import json
from typing import Optional, List
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    complexity: str = "moderate"  # simple, moderate, complex, critical


class AgentTeam:
    """
    Unternehmen-artige Agent-Organisation.

    Abteilungen:
    - CEO: Priorisiert, entscheidet, delegiert
    - Research: Recherchiert, analysiert, findet Fakten
    - Engineering: Codet, baut, fixt, deployed
    - Creative: Design, Text, Präsentationen
    - Operations: Verwaltung, Monitoring, Planung

    v9.2 additions:
    - classify_complexity(): determines how many agents to spawn
    - delegate_parallel(): runs N agents concurrently
    - synthesize_results(): CEO merges parallel results
    - Agent profiles from YAML (loaded dynamically)
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

    # Complexity → agent count and departments mapping
    COMPLEXITY_CONFIG = {
        "simple": {
            "agents": 1,
            "departments": ["operations"],  # fast, single agent
            "synthesis": False,
        },
        "moderate": {
            "agents": 2,
            "departments": ["research", "engineering"],
            "synthesis": False,
        },
        "complex": {
            "agents": 3,
            "departments": ["research", "engineering", "creative"],
            "synthesis": True,
        },
        "critical": {
            "agents": 4,
            "departments": ["ceo", "research", "engineering", "operations"],
            "synthesis": True,
        },
    }

    def __init__(self, llm: LLMClient, config: dict = None):
        self.llm = llm
        self.config = config or {}
        self._task_history = []  # type: List[TeamTask]
        self._task_counter = 0
        self._max_workers = self.config.get("max_parallel_workers", 4)

        # Load agent profiles from YAML if available
        self._profiles_loaded = False
        self._load_profiles()

    def _next_task_id(self) -> str:
        self._task_counter += 1
        return f"T{self._task_counter:04d}"

    def _load_profiles(self):
        """Load agent profiles from data/agents/ directory."""
        try:
            from nexus.core.agent_profiles import load_all_profiles
            profiles = load_all_profiles()
            if profiles:
                # Override hardcoded departments with profile data
                for name, profile in profiles.items():
                    dept_name = name.lower()
                    if dept_name in self.DEPARTMENTS:
                        self.DEPARTMENTS[dept_name]["name"] = profile.get("name", dept_name.capitalize())
                        self.DEPARTMENTS[dept_name]["role"] = profile.get("role", self.DEPARTMENTS[dept_name]["role"])
                        self.DEPARTMENTS[dept_name]["model"] = profile.get("model", self.DEPARTMENTS[dept_name]["model"])
                        # Prepend custom system prompt from profile
                        custom_prompt = profile.get("system_prompt", "")
                        if custom_prompt:
                            self.DEPARTMENTS[dept_name]["role"] = custom_prompt
                    else:
                        # New department from profile
                        self.DEPARTMENTS[dept_name] = {
                            "name": profile.get("name", name),
                            "model": profile.get("model", "default"),
                            "role": profile.get("role", f"Spezialist fuer {name}"),
                            "max_turns": profile.get("max_turns", 3),
                        }
                self._profiles_loaded = True
                log.info(f"Loaded {len(profiles)} agent profiles")
        except ImportError:
            log.debug("agent_profiles module not available, using hardcoded departments")
        except Exception as e:
            log.warning(f"Failed to load agent profiles: {e}")

    def classify_complexity(self, task_description: str, context: str = "",
                            routing_complexity: str = "moderate") -> str:
        """
        Classify task complexity to determine how many agents to spawn.

        Uses routing decision complexity as a base, then refines based on
        task characteristics. Returns: simple, moderate, complex, critical.
        """
        # Start with routing decision
        complexity = routing_complexity

        # Refine based on task description
        msg_lower = task_description.lower()
        word_count = len(task_description.split())

        # Upgrade complexity for multi-part tasks
        multi_part_markers = ["und", " und ", "außerdem", "zusätzlich", "gleichzeitig",
                             "auch", "dazu", "sowie", "both", "also", "additionally"]
        multi_part_count = sum(1 for m in multi_part_markers if m in msg_lower)

        # Upgrade if multiple domains are involved
        domain_keywords = {
            "code": 0, "programmier": 0, "implementier": 0, "refactor": 0,
            "recherchier": 1, "analysier": 1, "vergleiche": 1, "such": 1,
            "design": 2, "layout": 2, "kreativ": 2, "präsentation": 2,
            "deploy": 0, "server": 0, "konfigurier": 3, "monitoring": 3,
        }
        domains_hit = set()
        for keyword, domain in domain_keywords.items():
            if keyword in msg_lower:
                domains_hit.add(domain)

        # Adjust complexity
        if len(domains_hit) >= 3 or multi_part_count >= 2:
            complexity = "critical"
        elif len(domains_hit) >= 2 or multi_part_count >= 1 or word_count > 40:
            if complexity == "simple":
                complexity = "moderate"
            elif complexity == "moderate":
                complexity = "complex"

        return complexity

    def delegate(self, task_description: str, department: str = "auto",
                 context: str = "", complexity: str = None) -> TeamTask:
        """
        Delegate a task to a department.
        If department='auto', CEO decides which department handles it.
        If complexity is set, may trigger parallel delegation.
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
            complexity=complexity or "moderate",
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

        # Update agent profile performance metrics
        self._update_profile_performance(department, task)

        return task

    def delegate_parallel(self, task_description: str, context: str = "",
                          complexity: str = "moderate",
                          progress_callback=None) -> List[TeamTask]:
        """
        Delegate a task to multiple departments in parallel.

        Args:
            task_description: The task to handle
            context: Additional context
            complexity: Task complexity (determines agent count and departments)
            progress_callback: Called with (event_type, dept, task) for lifecycle events.
                event_type: "agent_start" before task begins, "agent_done" after completion.

        Returns:
            List of completed TeamTasks
        """
        config = self.COMPLEXITY_CONFIG.get(complexity, self.COMPLEXITY_CONFIG["moderate"])
        departments = config["departments"][:config["agents"]]
        need_synthesis = config["synthesis"]

        log.info(f"Parallel delegation: complexity={complexity}, departments={[self.DEPARTMENTS.get(d, {}).get('name', d) for d in departments]}")

        results = []
        completed_count = 0

        with ThreadPoolExecutor(max_workers=min(config["agents"], self._max_workers)) as executor:
            # Submit all tasks
            future_to_dept = {}
            for dept in departments:
                dept_config = self.DEPARTMENTS.get(dept, self.DEPARTMENTS["research"])
                task_prompt = self._build_parallel_prompt(task_description, dept, dept_config, context)

                # Emit agent_start before submitting
                if progress_callback:
                    progress_callback("agent_start", dept, None)

                future = executor.submit(
                    self._execute_department_task,
                    task_description=task_description,
                    department=dept,
                    custom_prompt=task_prompt,
                )
                future_to_dept[future] = dept

            # Collect results as they come in
            for future in as_completed(future_to_dept):
                dept = future_to_dept[future]
                try:
                    task = future.result()
                    results.append(task)
                    completed_count += 1

                    if progress_callback:
                        progress_callback("agent_done", dept, task)

                    log.info(f"Parallel task completed: {dept} in {task.elapsed:.1f}s")
                except Exception as e:
                    log.error(f"Parallel task failed: {dept}: {e}")
                    failed_task = TeamTask(
                        task_id=self._next_task_id(),
                        description=task_description,
                        department=dept,
                        status="failed",
                        result=f"Fehler: {e}",
                        elapsed=0,
                    )
                    results.append(failed_task)
                    if progress_callback:
                        progress_callback("agent_done", dept, failed_task)

        # Synthesize results if needed
        if need_synthesis and len(results) > 1:
            synthesis = self.synthesize_results(task_description, results)
            # Add synthesis as a final result
            results.append(synthesis)

        return results

    def _build_parallel_prompt(self, task_description: str, department: str,
                               dept_config: dict, context: str) -> str:
        """Build a department-specific prompt for parallel execution."""
        dept_name = dept_config.get("name", department.capitalize())
        dept_role = dept_config.get("role", "")

        # Research-specific prompt
        if department == "research":
            return (
                f"Du bist {dept_name} bei Nexus. {dept_role}\n"
                f"Fokus: Fakten sammeln, Quellen prüfen, Informationen strukturieren.\n"
                f"Antworte direkt und ergebnisorientiert.\n"
                f"Aufgabe: {task_description}\n"
            )
        # Engineering-specific prompt
        elif department == "engineering":
            return (
                f"Du bist {dept_name} bei Nexus. {dept_role}\n"
                f"Fokus: Konkrete Lösung implementieren, Code-Beispiele, technische Details.\n"
                f"Antworte direkt und ergebnisorientiert.\n"
                f"Aufgabe: {task_description}\n"
            )
        # Creative-specific prompt
        elif department == "creative":
            return (
                f"Du bist {dept_name} bei Nexus. {dept_role}\n"
                f"Fokus: Kreative Perspektive, Design-Ideen, alternative Ansätze.\n"
                f"Antworte direkt und ergebnisorientiert.\n"
                f"Aufgabe: {task_description}\n"
            )
        # CEO prompt (for critical tasks)
        elif department == "ceo":
            return (
                f"Du bist {dept_name} bei Nexus. {dept_role}\n"
                f"Fokus: Strategische Entscheidung, Priorisierung, Risikobewertung.\n"
                f"Antworte direkt und ergebnisorientiert.\n"
                f"Aufgabe: {task_description}\n"
            )
        # Default prompt
        else:
            return (
                f"Du bist {dept_name} bei Nexus. {dept_role}\n"
                f"Antworte direkt und ergebnisorientiert.\n"
                f"Aufgabe: {task_description}\n"
            )

    def _execute_department_task(self, task_description: str, department: str,
                                  custom_prompt: str = "") -> TeamTask:
        """Execute a single department task (for ThreadPoolExecutor)."""
        dept = self.DEPARTMENTS.get(department, self.DEPARTMENTS["research"])
        task_id = self._next_task_id()
        task = TeamTask(
            task_id=task_id,
            description=task_description,
            department=department,
            complexity="parallel",
        )
        task.status = "in_progress"
        start = time.time()

        messages = [
            Message("system", custom_prompt or f"Du bist {dept['name']}. {dept['role']}"),
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
        self._update_profile_performance(department, task)

        return task

    def synthesize_results(self, original_task: str, results: List[TeamTask]) -> TeamTask:
        """
        CEO synthesizes parallel results into a coherent final answer.
        Called after all parallel agents have completed.
        """
        start = time.time()

        # Build synthesis prompt with all results
        result_parts = []
        for r in results:
            if r.status == "completed":
                dept_name = self.DEPARTMENTS.get(r.department, {}).get("name", r.department)
                result_parts.append(f"**{dept_name}**:\n{r.result[:1500]}")
            else:
                result_parts.append(f"**{r.department}** (fehlgeschlagen): {r.result[:500]}")

        results_text = "\n\n".join(result_parts)

        messages = [
            Message("system",
                "Du bist der CEO bei Nexus. Synthetisiere die Ergebnisse deiner Teammitglieder "
                "zu einer klaren, zusammenhängenden Antwort. Keine Wiederholungen, kein Fülltext. "
                "Fasse die wichtigsten Punkte zusammen und ergänze wo nötig."),
            Message("user", f"Original-Aufgabe: {original_task}\n\nTeam-Ergebnisse:\n{results_text}"),
        ]

        response = self.llm.chat(messages, model_key="orchestrator")

        task = TeamTask(
            task_id=self._next_task_id(),
            description=f"Synthese: {original_task[:100]}",
            department="ceo",
            status="completed" if response.success else "failed",
            result=response.content if response.success else f"Synthese-Fehler: {response.error}",
            elapsed=time.time() - start,
            complexity="synthesis",
        )

        self._task_history.append(task)
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

    def _update_profile_performance(self, department: str, task: TeamTask):
        """Update agent profile performance metrics after a task completes."""
        try:
            from nexus.core.agent_profiles import update_performance
            update_performance(
                department,
                success=(task.status == "completed"),
                elapsed=task.elapsed,
            )
        except (ImportError, Exception) as e:
            log.debug(f"Profile performance update skipped for {department}: {e}")

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