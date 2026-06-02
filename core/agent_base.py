"""
NEXUS Agent Base Class — Toti-derived v3.0
Per-Agent Ollama Cloud Modell-Routing, Error-Learning, Skills, Guards.
"""

import re
import json
import time
from typing import Optional, Any
from pathlib import Path

from .llm_client import LLMClient, Message, LLMResponse
from .memory import MemorySystem
from .tools import ToolRegistry
from .guards import NexusGuards, GuardResult
from .state import StateManager
from .error_learning import ErrorLearningSystem


class AgentBase:
    """Base class für alle NEXUS Agents — Per-Agent Modell, Error-Learning, Skills."""

    AGENT_ID: str = "BASE"
    AGENT_NAME: str = "Base Agent"
    SYSTEM_PROMPT_FILE: str = "base.txt"

    def __init__(
        self,
        llm: LLMClient,
        memory: MemorySystem,
        tools: ToolRegistry,
        state: Optional[StateManager] = None,
        guards: Optional[NexusGuards] = None,
        system_prompt: Optional[str] = None,
        error_learning: Optional[ErrorLearningSystem] = None,
    ):
        self.llm = llm
        self.memory = memory
        self.tools = tools
        self.state = state or StateManager()
        self.guards = guards or NexusGuards()
        self.error_learning = error_learning or ErrorLearningSystem()
        self._system_prompt = system_prompt or self._load_prompt()
        self._conversation: list[Message] = []
        self._max_retries = 2

    @property
    def agent_model(self) -> str:
        """Das diesem Agent zugewiesene Ollama Cloud Modell."""
        return self.llm.get_model_for_agent(self.AGENT_ID)

    @property
    def agent_model_config(self) -> dict:
        """Komplette Modell-Konfiguration für diesen Agent."""
        return self.llm.get_agent_config(self.AGENT_ID)

    def _load_prompt(self) -> str:
        prompt_dir = Path(__file__).parent.parent / "prompts"
        prompt_path = prompt_dir / self.SYSTEM_PROMPT_FILE
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return f"Du bist {self.AGENT_NAME}, ein Agent im Nexus-System."

    def _build_messages(self, user_input: str, context: Optional[str] = None) -> list[Message]:
        """Baue Message-Liste mit State, Memory, Error-Warnungen, Tool-Liste und Modell-Info."""
        messages = []

        # System-Prompt mit Kontext und State
        sys_content = self._system_prompt

        # Inject: Agent-Modell-Info
        model_cfg = self.agent_model_config
        sys_content += f"\n\n## DEIN MODELL\n"
        sys_content += f"Modell: {model_cfg.get('model', 'unknown')}\n"
        sys_content += f"Beschreibung: {model_cfg.get('description', 'N/A')}\n"
        sys_content += f"Temperatur: {model_cfg.get('temperature', 0.5)}\n"

        # Inject aktuellen State
        state_json = self.state.get_state_json()
        sys_content += f"\n\n## AKTUELLER STATE\n{state_json}"

        if context:
            sys_content += f"\n\n## CURRENT CONTEXT\n{context}"

        # Inject Memory
        mem_context = self.memory.build_context(user_input)
        if mem_context:
            sys_content += f"\n\n## MEMORY\n{mem_context}"

        # Inject Error-Learning Warnungen
        error_context = self.error_learning.build_error_context(user_input)
        if error_context:
            sys_content += f"\n\n## FEHLER-VERMEIDUNG\n{error_context}"

        # Inject verfügbare Tools
        tool_list = self.tools.list_tools()
        if tool_list:
            tool_desc = "\n".join(
                f"  - TOOL:{t['name']}({', '.join(f'{k}: {v}' for k, v in t['params'].items())}) — {t['description']}"
                for t in tool_list
            )
            sys_content += f"\n\n## VERFÜGBARE TOOLS ({len(tool_list)} Tools)\n{tool_desc}"

        # Inject verfügbare Skills
        skills = self._get_available_skills()
        if skills:
            skill_desc = "\n".join(f"  - SKILL:{name} — {desc}" for name, desc in skills.items())
            sys_content += f"\n\n## VERFÜGBARE SKILLS\n{skill_desc}"

        messages.append(Message(role="system", content=sys_content))
        messages.extend(self._conversation)
        messages.append(Message(role="user", content=user_input))

        return messages

    def _get_available_skills(self) -> dict[str, str]:
        """Liste verfügbare Skills auf."""
        return {
            "web_research": "Tiefgehende Web-Recherche mit Quellen-Triangulation",
            "code_debug": "Code debuggen mit Error-Root-Cause-Analyse",
            "code_review": "Code-Review mit Qualitäts-Bewertung",
            "security_scan": "Sicherheits-Scan für Code und Dependencies",
            "data_extract": "Daten aus verschiedenen Quellen extrahieren",
            "test_gen": "Test-Code automatisch generieren",
            "doc_gen": "Dokumentation generieren (README, API-Docs, CHANGELOG)",
            "deploy_prep": "Deployment vorbereiten und validieren",
            "dependency_check": "Dependencies prüfen auf Updates/Conflicts/Security",
            "performance": "Performance-Analyse und Optimierung",
        }

    def execute(self, task: str, context: Optional[str] = None,
                accept_if: Optional[str] = None, level: Optional[int] = None) -> dict:
        """
        Führe einen Task aus mit Guard-Checks, Error-Learning und strukturiertem Output.
        Verwendet automatisch das per-agent Ollama Cloud Modell.
        """
        # Pre-Check mit Guards
        guard_result = self.guards.pre_check(task)

        if not guard_result.allowed:
            self.error_learning.record_error(
                error_class="AGENT_ERROR",
                context=task[:300],
                action=task[:200],
                error_message=guard_result.reason,
                agent=self.AGENT_ID,
            )
            return {
                "status": "error",
                "message": guard_result.reason,
                "result": None,
                "next_action": "Task abgebrochen — Guards blockieren.",
                "flags": ["GUARD_BLOCKED"],
                "confidence": 0.0,
            }

        # Error-Learning: Vorab-Prüfung auf bekannte Fehler
        error_warnings = self.error_learning.get_warnings_text(task, context="")

        # Log Task-Start
        self.memory.session_log("task_start", task, self.AGENT_ID)

        # Baue Messages
        messages = self._build_messages(task, context)

        # LLM-Call mit Per-Agent Modell-Routing
        response = self.llm.chat(messages, agent_id=self.AGENT_ID)

        # Wenn LLM-Fehler → im Error-Learning aufzeichnen
        if response.content.startswith("[LLM ERROR"):
            self.error_learning.record_error(
                error_class="LLM_ERROR",
                context=task[:300],
                action=f"llm.chat(agent={self.AGENT_ID}, model={self.agent_model})",
                error_message=response.content[:300],
                agent=self.AGENT_ID,
            )

        # Speichere Conversation
        self._conversation.append(Message(role="user", content=task))
        self._conversation.append(Message(role="assistant", content=response.content))

        # Verarbeite Tool-Calls
        processed_content = self._process_tool_calls(response.content)

        # Loop-Detection
        if guard_result.loop_detected or self.guards.check_loop(processed_content):
            processed_content = "[LOOP ERKANNT — wechsle Ansatz]\n" + processed_content
            self.error_learning.record_error(
                error_class="LOOP_ERROR",
                context=task[:300],
                action=task[:200],
                error_message="Loop erkannt — wiederholte Aktion ohne Fortschritt",
                agent=self.AGENT_ID,
            )

        # Verarbeite Skill-Calls
        processed_content = self._process_skill_calls(processed_content, task)

        # State aktualisieren
        self.state.update_task(step=self.guards.steps)
        self.state.set("memory.last_output_summary", processed_content[:200])
        self.state.update_system(
            llm_calls=self.state.get("system.llm_calls", 0) + 1,
            total_tokens=self.state.get("system.total_tokens", 0) + response.usage.get("total_tokens", 0),
        )

        # Log Completion
        self.memory.session_log("task_complete", processed_content[:500], self.AGENT_ID)

        # Conversation trimmen
        if len(self._conversation) > 40:
            self._conversation = self._conversation[-40:]

        # Confidence bestimmen
        confidence = min(1.0, 0.9 - (0.1 if guard_result.loop_detected else 0))
        if response.fallback_used:
            confidence -= 0.1

        return {
            "status": "done",
            "message": processed_content[:500],
            "result": processed_content,
            "next_action": "",
            "flags": ["LOOP_DETECTED"] if guard_result.loop_detected else [],
            "confidence": confidence,
            "elapsed": response.elapsed,
            "model": self.agent_model,
            "backend": response.backend,
            "fallback_used": response.fallback_used,
        }

    def _process_tool_calls(self, content: str) -> str:
        """Verarbeite TOOL: Aufrufe im Agent-Output."""
        tool_pattern = re.compile(r'TOOL:(\w+)\(([^)]*)\)')
        matches = tool_pattern.findall(content)
        if not matches:
            return content
        result_parts = [content]
        for tool_name, params_str in matches:
            full_call = f"TOOL:{tool_name}({params_str})"
            tool_result = self.tools.parse_and_dispatch(full_call)
            self.error_learning.auto_record_from_result(
                tool_result, action=full_call, agent=self.AGENT_ID, tool=tool_name
            )
            if isinstance(tool_result, dict) and "error" in tool_result:
                result_str = f"[TOOL ERROR: {tool_result['error']}]"
            else:
                result_str = f"[TOOL RESULT: {json.dumps(tool_result, ensure_ascii=False)[:500]}]"
            result_parts.append(f"\n--- {full_call} → {result_str}")
        return "".join(result_parts)

    def _process_skill_calls(self, content: str, task: str = "") -> str:
        """Verarbeite SKILL: Aufrufe im Agent-Output."""
        skill_pattern = re.compile(r'SKILL:(\w+)\(([^)]*)\)')
        matches = skill_pattern.findall(content)
        if not matches:
            return content

        result_parts = [content]
        for skill_name, params_str in matches:
            skill_result = self._execute_skill(skill_name, params_str, task)
            if skill_result:
                result_str = json.dumps(skill_result, ensure_ascii=False, default=str)[:800]
                result_parts.append(f"\n--- SKILL:{skill_name} → {result_str}")

        return "".join(result_parts)

    def _execute_skill(self, skill_name: str, params_str: str, task: str = "") -> Optional[dict]:
        """Führe einen Skill aus."""
        try:
            kwargs = {}
            if params_str.strip():
                try:
                    kwargs = json.loads(params_str)
                except json.JSONDecodeError:
                    kwargs = {"query": params_str.strip().strip('"').strip("'")}

            skill_map = {
                "web_research": "skills.web_research",
                "code_debug": "skills.code_debug",
                "code_review": "skills.code_review",
                "security_scan": "skills.security_scan",
                "data_extract": "skills.data_extract",
                "test_gen": "skills.test_gen",
                "doc_gen": "skills.doc_gen",
                "deploy_prep": "skills.deploy_prep",
                "dependency_check": "skills.dependency_check",
                "performance": "skills.performance",
            }

            module_path = skill_map.get(skill_name)
            if not module_path:
                return {"error": f"Skill '{skill_name}' nicht gefunden"}

            import importlib
            module = importlib.import_module(module_path)

            result = module.execute(
                llm_client=self.llm,
                tools=self.tools,
                **kwargs,
            )

            self.error_learning.auto_record_from_result(
                result, action=f"SKILL:{skill_name}", agent=self.AGENT_ID, tool=skill_name,
            )

            return result

        except ImportError as e:
            return {"error": f"Skill-Modul nicht ladbar: {skill_name} — {str(e)}"}
        except Exception as e:
            self.error_learning.record_error(
                error_class="AGENT_ERROR",
                context=task[:300],
                action=f"SKILL:{skill_name}",
                error_message=str(e),
                agent=self.AGENT_ID,
                tool=skill_name,
            )
            return {"error": f"Skill '{skill_name}' fehlgeschlagen: {str(e)}"}

    def quick_response(self, message: str) -> str:
        """Schnelle Chat-Antwort — nutzt Agent-spezifisches Modell."""
        return self.llm.quick_response(message, agent_id=self.AGENT_ID)

    def reset_conversation(self):
        self._conversation.clear()
        self.guards.reset()

    def get_status(self) -> dict:
        return {
            "agent_id": self.AGENT_ID,
            "agent_name": self.AGENT_NAME,
            "model": self.agent_model,
            "model_config": self.agent_model_config,
            "conversation_length": len(self._conversation),
            "guards": self.guards.get_status(),
            "state_task": self.state.get("current_task.status", "idle"),
            "error_stats": self.error_learning.get_error_stats(),
        }
