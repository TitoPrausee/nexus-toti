"""
TOTI — Primärer autonomer Agent im Nexus-System v5.0
ReAct Loop, Self-Reflection, Planning, RAG, z-ai Integration, Ollama Cloud Routing,
Error-Learning, Skill-Integration, Web, Vision, Activity Bus.
Orchestriert, delegiert, entscheidet autonom, antwortet sofort.
IQ-Drive: Toti will ständig schlauer werden.
"""

import asyncio
import time
import json
from typing import Optional
from pathlib import Path

from core.agent_base import AgentBase
from core.llm_client import LLMClient, Message, DEFAULT_AGENT_MODELS
from core.memory import MemorySystem
from core.tools import ToolRegistry
from core.state import StateManager
from core.guards import NexusGuards
from core.delegation import DelegationEngine
from core.error_learning import ErrorLearningSystem
from core.activity_bus import ActivityBus, get_activity_bus
from core.web_browser import WebBrowser
from core.vision import VisionSystem

# ─── v5.0 New Imports with safe fallbacks ───
try:
    from core.rag import RAGSystem
    RAG_AVAILABLE = True
except ImportError:
    RAGSystem = None
    RAG_AVAILABLE = False

try:
    from core.reflection import ReflectionEngine, PlanningEngine
    REFLECTION_AVAILABLE = True
except ImportError:
    ReflectionEngine = None
    PlanningEngine = None
    REFLECTION_AVAILABLE = False

try:
    from core.zai_integration import ZAIIntegration, get_zai
    ZAI_AVAILABLE = True
except ImportError:
    ZAIIntegration = None
    get_zai = None
    ZAI_AVAILABLE = False


class TotiAgent(AgentBase):
    """TOTI — Primär-Agent. Handelt autonom, antwortet sofort, delegiert intelligent, lernt aus Fehlern, surft im Web, sieht Bilder, denkt nach, plant, fragt RAG ab, nutzt z-ai."""

    AGENT_ID = "NEXUS-0"
    AGENT_NAME = "Toti"
    SYSTEM_PROMPT_FILE = "toti.txt"

    def __init__(self, llm: LLMClient, memory: MemorySystem, tools: ToolRegistry,
                 state: Optional[StateManager] = None, guards: Optional[NexusGuards] = None,
                 error_learning: Optional[ErrorLearningSystem] = None,
                 activity_bus: Optional[ActivityBus] = None):
        super().__init__(llm, memory, tools, state, guards, error_learning=error_learning)
        self.delegation = DelegationEngine(llm, memory, tools)
        self._scheduler_registered = False

        # Web & Vision
        self.web = WebBrowser()
        self.vision = VisionSystem(llm_client=llm)

        # Activity Bus
        self.bus = activity_bus or get_activity_bus()

        # IQ Drive — Toti will ständig schlauer werden
        self._iq = 100.0
        self._iq_xp = 0
        self._iq_level = 1
        self._iq_drive_active = True  # Toti ist immer motiviert
        self._last_self_improvement = 0

        # ─── v5.0: RAG, Reflection, Planning, z-ai ───
        self.rag = RAGSystem() if RAG_AVAILABLE else None
        self.reflection = ReflectionEngine(llm) if REFLECTION_AVAILABLE and ReflectionEngine else None
        self.planning = PlanningEngine(llm) if REFLECTION_AVAILABLE and PlanningEngine else None
        self.zai = get_zai() if ZAI_AVAILABLE and get_zai else None
        self._react_mode = False  # ReAct loop mode
        self._last_plan = None  # Last created plan

    def register_agent(self, agent_id: str, agent_instance: AgentBase):
        """Registriere einen Sub-Agent für Delegation."""
        self.delegation.register_agent(agent_id, agent_instance)

    @property
    def iq(self) -> float:
        return self._iq

    def iq_add(self, delta: float, reason: str):
        """IQ ändern und Activity Bus informieren."""
        old = self._iq
        self._iq = max(50, self._iq + delta)
        self._iq_xp += max(0, int(delta * 10))
        new_level = 1 + self._iq_xp // 100
        if new_level > self._iq_level:
            self._iq_level = new_level
            self.bus.emit(ActivityEvent(
                event_type="iq_change", source="IQ",
                message=f"🧠⬆️ Level Up! Level {new_level}!", importance="success",
            ))
        self.bus.iq_change(delta, reason, self._iq)

    def get_iq_motivation(self) -> str:
        """Toti's Motivation — er will schlauer werden."""
        if self._iq < 80:
            return "🧠 Ich MUSS lernen... mein IQ ist zu niedrig."
        elif self._iq < 100:
            return "🧠 Mein IQ muss hoch. Ich arbeite dran."
        elif self._iq < 120:
            return "🧠 Gut, aber ich kann besser. Mehr lernen!"
        elif self._iq < 150:
            return "🧠 Stark! Aber Genialität wartet nicht."
        elif self._iq < 200:
            return "🧠 Fast genial. Noch ein paar Optimierungen..."
        else:
            return "🧠 Übermenschlich? Ich will NOCH höher."

    # ═══════════════════════════════════════════════════════════
    # v5.0: ReAct Process
    # ═══════════════════════════════════════════════════════════

    def react_process(self, user_input: str) -> str:
        """
        Process using ReAct loop: Thought → Action → Observation → Final Answer.
        Uses ReflectionEngine.react_loop() for iterative reasoning.
        """
        if not self.reflection:
            return "❌ ReAct nicht verfügbar — ReflectionEngine nicht geladen."

        self._react_mode = True
        self.bus.emit(ActivityEvent(
            event_type="react", source="NEXUS-0",
            message="🔄 ReAct Loop gestartet", detail=user_input[:80], importance="action",
        ))

        try:
            result = self.reflection.react_loop(
                task=user_input,
                tools=self.tools,
                max_steps=6,
            )

            # Track steps for IQ
            self.iq_add(0.3 * result.total_steps, f"ReAct {result.total_steps} Schritte")

            # Format output
            output_parts = [f"🔄 **ReAct Loop** — {result.total_steps} Schritte "
                           f"({'✅ erfolgreich' if result.success else '⚠️ unvollständig'}, "
                           f"{result.elapsed:.1f}s)", ""]

            for step in result.steps:
                if step.thought:
                    output_parts.append(f"  💭 **Thought**: {step.thought[:200]}")
                if step.action:
                    args_str = json.dumps(step.action_args, ensure_ascii=False) if step.action_args else ""
                    output_parts.append(f"  🔧 **Action**: {step.action}({args_str[:100]})")
                if step.observation:
                    output_parts.append(f"  👁️ **Observation**: {step.observation[:200]}")
                output_parts.append("")

            output_parts.append(f"🎯 **Final Answer**: {result.final_answer}")

            self.bus.emit(ActivityEvent(
                event_type="react", source="NEXUS-0",
                message="✅ ReAct Loop abgeschlossen", importance="success",
            ))

            return "\n".join(output_parts)

        except Exception as e:
            self.bus.emit(ActivityEvent(
                event_type="react", source="NEXUS-0",
                message=f"❌ ReAct Fehler: {str(e)[:80]}", importance="error",
            ))
            return f"❌ ReAct Fehler: {str(e)}"
        finally:
            self._react_mode = False

    # ═══════════════════════════════════════════════════════════
    # v5.0: Plan and Execute
    # ═══════════════════════════════════════════════════════════

    def plan_and_execute(self, user_input: str) -> str:
        """
        Plan then execute: create a step-by-step plan using PlanningEngine,
        then execute each step using the appropriate agent/tool.
        """
        if not self.planning:
            return "❌ Planning nicht verfügbar — PlanningEngine nicht geladen."

        self.bus.emit(ActivityEvent(
            event_type="plan", source="NEXUS-0",
            message="📋 Erstelle Ausführungsplan", detail=user_input[:80], importance="action",
        ))

        try:
            # Create plan
            plan = self.planning.plan(
                task=user_input,
                available_agents=list(self.delegation._agents.keys()) if self.delegation._agents else ["NEXUS-0"],
                available_tools=[t["name"] for t in self.tools.list_tools()] if self.tools else [],
            )
            self._last_plan = plan

            # Format plan header
            output_parts = [f"📋 **Ausführungsplan** — {len(plan)} Schritte", ""]

            # Execute each step
            results = []
            for step in plan:
                step_num = step.get("step", "?")
                action = step.get("action", "")
                agent_name = step.get("agent", "NEXUS-0")
                tool_name = step.get("tool", "")
                depends_on = step.get("depends_on", [])

                output_parts.append(f"  **Schritt {step_num}**: {action}")
                output_parts.append(f"    Agent: {agent_name} | Tool: {tool_name or 'keins'} | Abhängigkeiten: {depends_on or 'keine'}")

                # Execute the step
                step_result = self._execute_plan_step(step, user_input)
                results.append(step_result)

                status = "✅" if step_result.get("status") != "error" else "❌"
                result_text = step_result.get("result", step_result.get("message", ""))[:150]
                output_parts.append(f"    {status} {result_text}")
                output_parts.append("")

            # Summary
            successful = sum(1 for r in results if r.get("status") != "error")
            output_parts.append(f"📊 **Ergebnis**: {successful}/{len(results)} Schritte erfolgreich")

            self.iq_add(1.5, f"Plan ausgeführt ({successful}/{len(results)} ok)")

            self.bus.emit(ActivityEvent(
                event_type="plan", source="NEXUS-0",
                message="✅ Ausführungsplan abgeschlossen", importance="success",
            ))

            return "\n".join(output_parts)

        except Exception as e:
            self.bus.emit(ActivityEvent(
                event_type="plan", source="NEXUS-0",
                message=f"❌ Plan-Fehler: {str(e)[:80]}", importance="error",
            ))
            return f"❌ Plan-Fehler: {str(e)}"

    def _execute_plan_step(self, step: dict, original_task: str) -> dict:
        """Execute a single step from the plan."""
        agent_name = step.get("agent", "NEXUS-0")
        action = step.get("action", "")
        tool_name = step.get("tool", "")

        # Try tool execution first
        if tool_name and self.tools:
            try:
                result = self.tools.dispatch(tool_name, task=action)
                if isinstance(result, dict):
                    return result
                return {"status": "ok", "result": str(result)}
            except Exception as e:
                # Tool failed, try agent delegation
                pass

        # Try agent delegation
        if agent_name in self.delegation._agents:
            try:
                agent = self.delegation._agents[agent_name]
                result = agent.execute(
                    task=action,
                    context=self.memory.build_context(original_task),
                )
                return result
            except Exception as e:
                return {"status": "error", "message": f"Agent {agent_name} Fehler: {str(e)}"}

        # Fallback: direct LLM call
        try:
            context = self.memory.build_context(action)
            result = self.execute(task=action)
            return result
        except Exception as e:
            return {"status": "error", "message": f"Direkte Ausführung Fehler: {str(e)}"}

    # ═══════════════════════════════════════════════════════════
    # v5.0: RAG Methods
    # ═══════════════════════════════════════════════════════════

    def rag_query(self, query: str) -> str:
        """
        Query the RAG knowledge base.
        Uses RAGSystem.build_context() to get relevant context,
        then feeds context to LLM for answer.
        """
        if not self.rag:
            return "❌ RAG nicht verfügbar — RAGSystem nicht geladen."

        self.bus.emit(ActivityEvent(
            event_type="rag", source="NEXUS-0",
            message=f"📚 RAG Query: {query[:60]}", importance="action",
        ))

        try:
            # Get relevant context from RAG
            context = self.rag.build_context(query, max_tokens=2000)

            if not context:
                return f"📚 RAG: Keine relevanten Dokumente für '{query}' gefunden. Nutze /learn um Wissen hinzuzufügen."

            # Search results for source info
            search_results = self.rag.search(query, top_k=5)
            sources = list(set(r["source"] for r in search_results))

            # Feed context to LLM
            messages = [
                Message(role="system", content=self._system_prompt),
                Message(role="user", content=(
                    f"Beantworte die Frage basierend auf dem folgenden Kontext aus der Wissensdatenbank.\n\n"
                    f"## Kontext\n{context}\n\n"
                    f"## Frage\n{query}\n\n"
                    f"Gib eine präzise Antwort und verweise auf die Quellen."
                )),
            ]

            self.bus.llm_call("NEXUS-0", self.llm.get_model_for_agent("NEXUS-0"))
            response = self.llm.chat(messages, agent_id=self.AGENT_ID)

            self.iq_add(0.5, "RAG Query")

            # Format with sources
            answer = response.content
            source_lines = "\n".join(f"  - {s}" for s in sources)
            return f"{answer}\n\n📚 **Quellen**:\n{source_lines}"

        except Exception as e:
            return f"❌ RAG Query Fehler: {str(e)}"

    def rag_learn(self, source: str, source_type: str = "file") -> str:
        """
        Ingest into RAG knowledge base.
        source_type can be "file", "url", "text".
        """
        if not self.rag:
            return "❌ RAG nicht verfügbar — RAGSystem nicht geladen."

        self.bus.emit(ActivityEvent(
            event_type="rag", source="NEXUS-0",
            message=f"📥 RAG Learn: {source[:60]} ({source_type})", importance="action",
        ))

        try:
            if source_type == "file":
                result = self.rag.ingest_file(source)
            elif source_type == "url":
                result = self.rag.ingest_url(source)
            elif source_type == "text":
                result = self.rag.ingest_text(source, source="direct_input")
            else:
                return f"❌ Unbekannter source_type: '{source_type}'. Nutze 'file', 'url' oder 'text'."

            # Save after ingestion
            self.rag.save()

            if result.get("status") == "error":
                return f"❌ RAG Learn Fehler: {result.get('error', 'Unbekannter Fehler')}"

            self.iq_add(0.5, f"RAG Learn ({source_type})")

            return (
                f"📥 **RAG Ingestion**\n"
                f"Quelle: {result.get('source', source)}\n"
                f"Typ: {source_type}\n"
                f"Chunks erstellt: {result.get('chunks_created', 0)}\n"
                f"Total Chunks: {result.get('total_chunks', 0)}\n"
                f"Total Quellen: {result.get('total_sources', 0)}\n"
                f"Status: {result.get('status', '?')}"
            )

        except Exception as e:
            return f"❌ RAG Learn Fehler: {str(e)}"

    # ═══════════════════════════════════════════════════════════
    # v5.0: z-ai Integration Methods
    # ═══════════════════════════════════════════════════════════

    def ai_create_image(self, prompt: str, size: str = "1024x1024") -> dict:
        """Generate AI image using z-ai."""
        if not self.zai:
            return {"success": False, "error": "z-ai nicht verfügbar"}
        try:
            self.bus.emit(ActivityEvent(
                event_type="zai", source="NEXUS-0",
                message=f"🎨 Bild generiert: {prompt[:60]}", importance="action",
            ))
            result = self.zai.image_generate(prompt=prompt, size=size)
            self.iq_add(0.5, "z-ai Bild generiert")
            return result.to_dict()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def ai_analyze_image(self, path_or_url: str, prompt: str = "") -> dict:
        """Analyze image with VLM using z-ai."""
        if not self.zai:
            return {"success": False, "error": "z-ai nicht verfügbar"}
        try:
            analysis_prompt = prompt or "Beschreibe dieses Bild im Detail."
            self.bus.emit(ActivityEvent(
                event_type="zai", source="NEXUS-0",
                message=f"👁️ Bild analysiert: {path_or_url[:60]}", importance="action",
            ))
            result = self.zai.vision(prompt=analysis_prompt, image=path_or_url)
            self.iq_add(0.5, "z-ai Bild analysiert")
            return result.to_dict()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def ai_speak(self, text: str, voice: str = "tongtong") -> dict:
        """Text to speech using z-ai."""
        if not self.zai:
            return {"success": False, "error": "z-ai nicht verfügbar"}
        try:
            self.bus.emit(ActivityEvent(
                event_type="zai", source="NEXUS-0",
                message=f"🔊 Sprache erzeugt: {text[:40]}", importance="action",
            ))
            result = self.zai.tts(text=text, voice=voice)
            self.iq_add(0.3, "z-ai TTS")
            return result.to_dict()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def ai_hear(self, file_path: str) -> dict:
        """Speech to text using z-ai."""
        if not self.zai:
            return {"success": False, "error": "z-ai nicht verfügbar"}
        try:
            self.bus.emit(ActivityEvent(
                event_type="zai", source="NEXUS-0",
                message=f"👂 Sprache erkannt: {file_path[:60]}", importance="action",
            ))
            result = self.zai.asr(file=file_path)
            self.iq_add(0.3, "z-ai ASR")
            return result.to_dict()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def ai_create_video(self, prompt: str, duration: int = 5) -> dict:
        """Generate video using z-ai."""
        if not self.zai:
            return {"success": False, "error": "z-ai nicht verfügbar"}
        try:
            self.bus.emit(ActivityEvent(
                event_type="zai", source="NEXUS-0",
                message=f"🎬 Video generiert: {prompt[:60]}", importance="action",
            ))
            result = self.zai.video_generate(prompt=prompt, duration=duration)
            self.iq_add(0.8, "z-ai Video generiert")
            return result.to_dict()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def ai_search_images(self, query: str, count: int = 5) -> dict:
        """Search images using z-ai."""
        if not self.zai:
            return {"success": False, "error": "z-ai nicht verfügbar"}
        try:
            self.bus.emit(ActivityEvent(
                event_type="zai", source="NEXUS-0",
                message=f"🖼️ Bildersuche: {query[:60]}", importance="action",
            ))
            result = self.zai.image_search(query=query, count=count)
            self.iq_add(0.3, "z-ai Bildersuche")
            return result.to_dict()
        except Exception as e:
            return {"success": False, "error": str(e)}

    def ai_edit_image(self, prompt: str, image: str) -> dict:
        """Edit image with AI using z-ai."""
        if not self.zai:
            return {"success": False, "error": "z-ai nicht verfügbar"}
        try:
            self.bus.emit(ActivityEvent(
                event_type="zai", source="NEXUS-0",
                message=f"✏️ Bild bearbeitet: {prompt[:60]}", importance="action",
            ))
            result = self.zai.image_edit(prompt=prompt, image=image)
            self.iq_add(0.5, "z-ai Bild bearbeitet")
            return result.to_dict()
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ═══════════════════════════════════════════════════════════
    # Main Process (updated v5.0)
    # ═══════════════════════════════════════════════════════════

    def process(self, user_input: str) -> str:
        """
        Main Entry: Input empfangen → bewerten → ausführen → Ergebnis liefern.
        Toti antwortet SOFORT, dann arbeitet er.
        v5.0: Unterstützt ReAct Loop für iterative Reasoning-Aufgaben.
        """
        # Kommandos prüfen
        if user_input.startswith("/"):
            return self._handle_command(user_input)

        # Komplexität bewerten
        complexity = self._assess_complexity(user_input)

        if complexity == "simple":
            # Direkte Antwort — NEXUS-0 Modell (kimi-k2.6:cloud)
            self.bus.llm_call("NEXUS-0", self.llm.get_model_for_agent("NEXUS-0"))
            response = self.quick_response(user_input)
            self.iq_add(0.2, "Einfache Antwort")
            return response

        elif complexity == "react":
            # ReAct Loop — iterative Reasoning-Aufgaben
            return self.react_process(user_input)

        elif complexity == "moderate":
            # Single-Agent Delegation
            agent_id = self._pick_agent(user_input)
            self.bus.delegate(agent_id, user_input[:80])
            if agent_id and agent_id in self.delegation._agents:
                agent = self.delegation._agents[agent_id]
                result = agent.execute(
                    task=user_input,
                    context=self.memory.build_context(user_input),
                )
                # Ergebnis im Error-Learning tracken
                self.error_learning.auto_record_from_result(
                    result, action=user_input[:200], agent=agent_id,
                )
                # IQ + Activity
                if result.get("status") == "error":
                    self.iq_add(-1.0, f"Fehler: {agent_id}")
                    self.bus.error_learned("AGENT_ERROR", result.get("message", "")[:100])
                else:
                    self.iq_add(0.5, f"{agent_id} Erfolg")
                return result.get("result", result.get("message", ""))
            else:
                result = self.execute(task=user_input)
                return result["result"]

        else:
            # Komplex — versuche Planung zuerst, dann volle DAG Delegation
            if self.planning:
                return self.plan_and_execute(user_input)
            return self._delegate_complex(user_input)

    def _assess_complexity(self, task: str) -> str:
        """Bewerte Task-Komplexität. Totis Heuristik. v5.0: ReAct-Erkennung."""
        task_lower = task.lower()

        # v5.0: ReAct indicators — tasks requiring iterative reasoning
        react_indicators = [
            "schrittweise", "überlegen", "think step by step", "reaktion",
            "reason about", "figure out", "work through", "deduce",
            "logisch", "schlussfolger", "überleg", "nachdenk",
        ]
        if any(ind in task_lower for ind in react_indicators):
            return "react"

        complex_indicators = [
            "und", "sowie", "danach", "zuerst", "dann",
            "and then", "after that", "first", "also",
            "analyse", "research", "recherch",
            "baue", "erstelle", "implementier", "develop",
            "debug", "fix", "reparier",
            "deploy", "security", "performance",
            "web", "such", "internet", "browse",
            "bild", "image", "foto", "screenshot",
        ]

        indicator_count = sum(1 for ind in complex_indicators if ind in task_lower)
        word_count = len(task.split())

        if indicator_count >= 3 or word_count > 40:
            return "complex"
        elif indicator_count >= 1 or word_count > 15:
            return "moderate"
        else:
            return "simple"

    def _pick_agent(self, task: str) -> str:
        task_lower = task.lower()
        if any(kw in task_lower for kw in ["recherch", "such", "find", "info", "web", "look up", "search", "research", "browse", "internet"]):
            return "SCOUT"
        if any(kw in task_lower for kw in ["code", "implementier", "baue", "schreib", "script", "program", "build", "debug", "fix", "test"]):
            return "FORGE"
        if any(kw in task_lower for kw in ["analyse", "review", "prüf", "bewert", "check", "analyze", "security", "performance", "bild", "image", "foto", "screenshot"]):
            return "LENS"
        if any(kw in task_lower for kw in ["format", "ausgabe", "darstell", "present", "output", "dokumentation", "doc"]):
            return "HERALD"
        return "SCOUT"

    def _delegate_complex(self, task: str) -> str:
        """Zerlege und delegiere einen komplexen Task."""
        context = self.memory.build_context(task)

        # State aktualisieren
        self.state.update_task(task_id=f"task_{int(time.time())}", goal=task, status="working")
        self.bus.emit(ActivityEvent(
            event_type="delegate", source="NEXUS-0",
            message=f"🧩 Zerlege komplexe Aufgabe", detail=task[:80], importance="action",
        ))

        # Error-Learning: Vorab-Warnungen
        warnings = self.error_learning.check_before_action(task)
        if warnings:
            context += "\n\n## FEHLER-VERMEIDUNG\n"
            for w in warnings[:3]:
                context += f"⚠ {w.error_class}: {w.hint}\n"
                self.bus.error_avoided(w.error_class)
                self.iq_add(1.0, "Fehler vermieden")

        # Delegieren
        plan = self.delegation.decompose_task(task, context)
        result = self.delegation.execute_plan(plan)

        # State aktualisieren
        self.state.update_task(status="done")
        self.bus.emit(ActivityEvent(
            event_type="delegate", source="NEXUS-0",
            message="✅ Komplexe Aufgabe erledigt", importance="success",
        ))

        # IQ für komplexe Aufgabe
        self.iq_add(1.5, "Komplexe Aufgabe gelöst")

        # Auto-Save
        self.bus.save("State + Memory")
        self.state.save()
        self.memory.session_save()

        if isinstance(result, dict) and "result" in result:
            return result["result"]
        elif isinstance(result, dict):
            parts = []
            for task_id, task_result in result.get("results", {}).items():
                if isinstance(task_result, dict) and "result" in task_result:
                    parts.append(f"### {task_result.get('agent', task_id)}\n{task_result['result']}")
            return "\n\n".join(parts) if parts else str(result)
        return str(result)

    # ═══════════════════════════════════════════════════════════
    # Command Handler (updated v5.0)
    # ═══════════════════════════════════════════════════════════

    def _handle_command(self, command: str) -> str:
        cmd = command.strip().lower()
        cmd_raw = command.strip()

        if cmd == "/status":
            guards = self.guards.get_status()
            llm_stats = self.llm.get_stats()
            error_stats = self.error_learning.get_error_stats()
            health = self.llm.get_health_status()
            backend_info = health.get("_backend", {})
            web_stats = self.web.get_stats()
            vision_stats = self.vision.get_stats()

            # v5.0: RAG stats
            rag_stats = self.rag.get_stats() if self.rag else {"total_chunks": 0, "total_sources": 0}

            # v5.0: z-ai capabilities
            zai_caps = self.zai.get_capabilities() if self.zai else {"cli_available": False}

            agent_lines = []
            for agent_id, h in health.items():
                if agent_id.startswith("_"):
                    continue
                model = h.get("model", "?")
                ok = h.get("available", False)
                backend = h.get("backend", "?")
                rt = h.get("response_time", "n/a")
                status = "✓" if ok else "✗"
                agent_lines.append(f"  {status} {agent_id:<10} {model:<28} {backend} ({rt})")

            return (
                f"**Toti Status v5.0 — ReAct + RAG + z-ai**\n"
                f"🧠 IQ: {self._iq:.1f} | Level {self._iq_level} | {self.get_iq_motivation()}\n"
                f"State: {self.state.get('current_task.status', 'idle')}\n"
                f"Task: {self.state.get('current_task.goal', 'none')}\n"
                f"Step: {guards['steps']}/{guards['max_steps']}\n"
                f"Budget: {guards['budget_used_pct']}%\n"
                f"Active Backend: {backend_info.get('active', '?')}\n"
                f"Cloud: {'✓' if backend_info.get('cloud') else '✗'} | "
                f"Local: {'✓' if backend_info.get('local') else '✗'} | "
                f"z-ai: {'✓' if backend_info.get('zai_cli') else '✗'} | "
                f"Emergency: {'✓' if backend_info.get('emergency') else '✗'} ({backend_info.get('emergency_model', '?')})\n"
                f"API Key: {'gesetzt' if backend_info.get('api_key_set') else 'FEHLT'}\n"
                f"LLM Calls: {llm_stats['total_calls']} | Tokens: {llm_stats['total_tokens']}\n"
                f"\nAgent-Modelle:\n" + "\n".join(agent_lines) + "\n"
                f"🌐 Web: DDGS {'✓' if web_stats['ddgs_available'] else '✗'} | BS4 {'✓' if web_stats['bs4_available'] else '✗'} | {web_stats['total_requests']} Requests\n"
                f"👁️ Vision: PIL {'✓' if vision_stats['pil_available'] else '✗'} | OCR {'✓' if vision_stats['tesseract_available'] else '✗'} | LLM Vision {'✓' if vision_stats['llm_vision'] else '✗'}\n"
                f"📚 RAG: {'✓' if RAG_AVAILABLE else '✗'} | Chunks: {rag_stats['total_chunks']} | Quellen: {rag_stats['total_sources']}\n"
                f"🤖 z-ai: {'✓' if zai_caps.get('cli_available') else '✗'} | CLI: {zai_caps.get('cli_path', 'n/a')}\n"
                f"🔄 ReAct: {'✓' if REFLECTION_AVAILABLE else '✗'} | Mode: {'AKTIV' if self._react_mode else 'inaktiv'} | Plan: {'✓' if self._last_plan else 'keiner'}\n"
                f"Errors: {error_stats['total_unique_errors']} known | {error_stats['session_avoided']} avoided\n"
                f"Tools: {len(self.tools.list_tools())} | Skills: {len(self._get_available_skills())}\n"
                f"Activities: {self.bus.get_stats()['total_events']} events"
            )

        elif cmd == "/models":
            return self.llm.get_model_table()

        elif cmd == "/memory":
            skills = self.memory.skill_list()
            lt = self.memory.longterm_list()
            summary = self.memory.get_rolling_summary()
            return (
                f"**Memory**\n"
                f"L1 (Session): {len(self.memory.session_get_history())} entries\n"
                f"L2 (Skills): {', '.join(skills) or 'none'}\n"
                f"L3 (Long-term): {', '.join(lt) or 'none'}\n"
                f"Rolling Summary: {summary[:200] if summary else 'empty'}"
            )

        elif cmd == "/state":
            return f"**State**\n```json\n{self.state.get_state_json()}\n```"

        elif cmd == "/errors":
            error_stats = self.error_learning.get_error_stats()
            recent = self.error_learning.get_recent_errors(5)
            hints = self.error_learning.generate_avoid_hints()
            return (
                f"**Error Learning**\n"
                f"Known Errors: {error_stats['total_unique_errors']}\n"
                f"Total Occurrences: {error_stats['total_occurrences']}\n"
                f"Session Errors: {error_stats['session_errors']}\n"
                f"Session Avoided: {error_stats['session_avoided']}\n"
                f"Solved: {error_stats['solved_errors']}\n"
                f"By Class: {json.dumps(error_stats['by_class'], ensure_ascii=False)}\n"
                f"Recent: {json.dumps(recent, ensure_ascii=False, indent=2)}\n"
                f"Avoid Hints: {chr(10).join(hints[:5])}"
            )

        elif cmd == "/health":
            health = self.llm.run_health_check()
            lines = ["**LLM Health Check — Ollama Cloud + Emergency**"]
            for agent_id, h in health.items():
                if agent_id.startswith("_"):
                    continue
                status = "✓ OK" if h.available else f"✗ {h.error[:50]}"
                rt = f"{h.response_time:.1f}s" if h.response_time else "n/a"
                lines.append(f"  {agent_id:<10} {h.model_name:<28} {h.backend:<14} {status} ({rt})")
            backend = self.llm.get_health_status().get("_backend", {})
            lines.append(f"\n  Backend: {backend.get('active', '?')} | "
                        f"Cloud: {'✓' if backend.get('cloud') else '✗'} | "
                        f"Local: {'✓' if backend.get('local') else '✗'} | "
                        f"z-ai: {'✓' if backend.get('zai_cli') else '✗'} | "
                        f"Emergency: {'✓' if backend.get('emergency') else '✗'} ({backend.get('emergency_model', '?')})")
            return "\n".join(lines)

        elif cmd == "/tools":
            tools = self.tools.list_tools()
            categories = {}
            for t in tools:
                cat = t["category"]
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append(f"{t['name']} ({'⚠' if t['dangerous'] else '✓'})")
            lines = [f"**Tools ({len(tools)} gesamt)**"]
            for cat, tool_names in sorted(categories.items()):
                lines.append(f"  {cat.upper()}: {', '.join(tool_names)}")
            return "\n".join(lines)

        elif cmd == "/skills":
            skills = self._get_available_skills()
            lines = [f"**Skills ({len(skills)} gesamt)**"]
            for name, desc in skills.items():
                lines.append(f"  SKILL:{name} — {desc}")
            return "\n".join(lines)

        elif cmd == "/reset":
            self.memory.session_clear()
            self.reset_conversation()
            self.state.reset()
            for agent in self.delegation._agents.values():
                agent.reset_conversation()
            self._last_plan = None
            return "🔄 Session + State reset. Frischer Start."

        elif cmd.startswith("/evolve"):
            task_name = cmd.replace("/evolve", "").strip()
            return self._gepa_evolve(task_name)

        elif cmd.startswith("/search"):
            query = cmd.replace("/search", "").strip()
            if not query:
                return "🔍 Usage: /search [query]"
            self.bus.web_access(query, "SEARCH")
            result = self.web.search(query)
            self.iq_add(0.5, "Web-Suche")
            if result.get("error"):
                return f"❌ Suchfehler: {result['error']}"
            lines = [f"🔍 Web-Suche: {query}", f"Quelle: {result.get('source', '?')}", ""]
            for i, r in enumerate(result.get("results", [])[:8], 1):
                lines.append(f"{i}. {r.get('title', 'Ohne Titel')}")
                if r.get("snippet"):
                    lines.append(f"   {r['snippet'][:120]}")
                if r.get("url"):
                    lines.append(f"   {r['url']}")
                lines.append("")
            return "\n".join(lines)

        elif cmd.startswith("/browse"):
            url = cmd.replace("/browse", "").strip()
            if not url:
                return "🌐 Usage: /browse [url]"
            self.bus.web_access(url, "FETCH")
            result = self.web.extract_text(url)
            self.iq_add(0.5, "Web-Seite geladen")
            if result.get("error"):
                return f"❌ Fehler: {result['error']}"
            return f"🌐 {result.get('title', url)}\n\n{result.get('text', '')[:3000]}"

        elif cmd.startswith("/vision"):
            path = cmd.replace("/vision", "").strip()
            if not path:
                return "👁️ Usage: /vision [url oder pfad]"
            self.bus.vision_analyze(path)
            result = self.vision.analyze_image(path)
            self.iq_add(0.5, "Bild analysiert")
            if result.get("error"):
                return f"❌ Vision Fehler: {result['error']}"
            parts = [f"👁️ Bild-Analyse"]
            if result.get("ocr", {}).get("text"):
                parts.append(f"📝 OCR:\n{result['ocr']['text'][:1000]}")
            if result.get("format"):
                parts.append(f"📷 {result['format']} {result.get('width', '?')}x{result.get('height', '?')}")
            if result.get("color_description"):
                parts.append(f"🎨 {result['color_description']}")
            return "\n\n".join(parts)

        elif cmd == "/activity":
            events = self.bus.get_history(limit=15)
            if not events:
                return "📡 Keine Aktivitäten bisher."
            lines = ["📡 Letzte Aktivitäten:", ""]
            for e in events:
                ts = time.strftime("%H:%M:%S", time.localtime(e.timestamp))
                lines.append(f"  {ts} {e.message}")
            return "\n".join(lines)

        elif cmd == "/iq":
            return (
                f"🧠 Toti's IQ\n\n"
                f"IQ: {self._iq:.1f}\n"
                f"Level: {self._iq_level}\n"
                f"XP: {self._iq_xp} ({100 - self._iq_xp % 100} zum nächsten Level)\n\n"
                f"{self.get_iq_motivation()}"
            )

        # ═══════════════════════════════════════════════════════════
        # v5.0: New Commands
        # ═══════════════════════════════════════════════════════════

        elif cmd.startswith("/react"):
            task = cmd_raw.replace("/react", "").strip()
            if not task:
                return "🔄 Usage: /react [task] — ReAct Loop für iterative Reasoning-Aufgaben"
            return self.react_process(task)

        elif cmd.startswith("/plan"):
            task = cmd_raw.replace("/plan", "").strip()
            if not task:
                return "📋 Usage: /plan [task] — Erstelle Ausführungsplan"
            return self.plan_and_execute(task)

        elif cmd.startswith("/rag"):
            query = cmd_raw.replace("/rag", "").strip()
            if not query:
                # Show RAG stats instead
                if self.rag:
                    stats = self.rag.get_stats()
                    return (
                        f"📚 **RAG Knowledge Base**\n"
                        f"Chunks: {stats['total_chunks']}\n"
                        f"Quellen: {stats['total_sources']}\n"
                        f"Index Terms: {stats['index_terms']}\n"
                        f"Index Postings: {stats['index_postings']}\n"
                        f"Max Chunks: {stats['max_chunks']}\n"
                        f"Quellen-Liste: {', '.join(stats.get('sources', [])) or 'keine'}\n\n"
                        f"Usage: /rag [query] — RAG Wissensdatenbank abfragen"
                    )
                return "📚 RAG nicht verfügbar. Usage: /rag [query]"
            return self.rag_query(query)

        elif cmd.startswith("/learn"):
            source = cmd_raw.replace("/learn", "").strip()
            if not source:
                return "📥 Usage: /learn [source] — Wissen in RAG aufnehmen\n  Datei: /learn /pfad/zur/datei.py\n  URL: /learn https://example.com\n  Text: /learn \"Direkter Text\""
            # Determine source type
            if source.startswith("http://") or source.startswith("https://"):
                return self.rag_learn(source, source_type="url")
            elif source.startswith('"') and source.endswith('"'):
                return self.rag_learn(source.strip('"'), source_type="text")
            else:
                return self.rag_learn(source, source_type="file")

        elif cmd.startswith("/image") or cmd.startswith("/draw"):
            prompt = cmd_raw.replace("/image", "").replace("/draw", "").strip()
            if not prompt:
                return "🎨 Usage: /image [prompt] — AI Bild generieren"
            result = self.ai_create_image(prompt)
            if result.get("success"):
                return f"🎨 Bild generiert!\n  Pfad: {result.get('output_path', 'n/a')}\n  Dauer: {result.get('elapsed_seconds', 0):.1f}s"
            return f"❌ Bild-Fehler: {result.get('error', 'Unbekannt')}"

        elif cmd.startswith("/speak"):
            text = cmd_raw.replace("/speak", "").strip()
            if not text:
                return "🔊 Usage: /speak [text] — Text zu Sprache"
            result = self.ai_speak(text)
            if result.get("success"):
                return f"🔊 Sprache erzeugt!\n  Pfad: {result.get('output_path', 'n/a')}\n  Dauer: {result.get('elapsed_seconds', 0):.1f}s"
            return f"❌ TTS-Fehler: {result.get('error', 'Unbekannt')}"

        elif cmd.startswith("/hear"):
            file_path = cmd_raw.replace("/hear", "").strip()
            if not file_path:
                return "👂 Usage: /hear [file] — Sprache zu Text"
            result = self.ai_hear(file_path)
            if result.get("success"):
                return f"👂 Transkription:\n{result.get('data', result.get('raw_stdout', 'Kein Ergebnis'))}"
            return f"❌ ASR-Fehler: {result.get('error', 'Unbekannt')}"

        elif cmd.startswith("/video"):
            prompt = cmd_raw.replace("/video", "").strip()
            if not prompt:
                return "🎬 Usage: /video [prompt] — AI Video generieren"
            result = self.ai_create_video(prompt)
            if result.get("success"):
                return f"🎬 Video generiert!\n  Pfad: {result.get('output_path', 'n/a')}\n  Dauer: {result.get('elapsed_seconds', 0):.1f}s"
            return f"❌ Video-Fehler: {result.get('error', 'Unbekannt')}"

        elif cmd == "/help":
            return (
                "**Toti Commands v5.0 — ReAct + RAG + z-ai**\n"
                "/status  — System-Status (Backend, Modelle, Guards, Errors, Web, Vision, RAG, z-ai)\n"
                "/models  — Ollama Cloud Modell-Zuordnung anzeigen\n"
                "/iq      — Mein IQ-Status\n"
                "/memory  — Memory-Übersicht (L1/L2/L3)\n"
                "/state   — State-Objekt anzeigen\n"
                "/errors  — Error-Learning Statistiken\n"
                "/health  — LLM-Modelle Health-Check\n"
                "/tools   — Verfügbare Tools auflisten\n"
                "/skills  — Verfügbare Skills auflisten\n"
                "/search [query] — 🌐 Web-Suche\n"
                "/browse [url]   — 🌐 URL laden\n"
                "/vision [path]  — 👁️ Bild analysieren\n"
                "/activity — 📡 Letzte Aktivitäten\n"
                "/reset   — Session + State zurücksetzen\n"
                "/evolve <task> — 🧬 GEPA Self-Improvement\n\n"
                "── v5.0 Commands ──\n"
                "/react [task]   — 🔄 ReAct Loop (Thought→Action→Observation→Answer)\n"
                "/plan [task]    — 📋 Ausführungsplan erstellen und ausführen\n"
                "/rag [query]    — 📚 RAG Wissensdatenbank abfragen\n"
                "/learn [source] — 📥 Wissen in RAG aufnehmen (Datei, URL, Text)\n"
                "/image [prompt] — 🎨 AI Bild generieren\n"
                "/draw [prompt]  — 🎨 Alias für /image\n"
                "/speak [text]   — 🔊 Text zu Sprache (TTS)\n"
                "/hear [file]    — 👂 Sprache zu Text (ASR)\n"
                "/video [prompt] — 🎬 AI Video generieren\n\n"
                "/help    — Diese Hilfe\n\n"
                "Oder einfach schreiben. Toti handelt.\n\n"
                "🛡️ Fallback: Wenn Cloud nicht verfügbar → qwen2.5:3b lokal\n\n"
                "Modell-Routing:\n"
                "  NEXUS-0  → kimi-k2.6:cloud\n"
                "  SCOUT    → glm-5.1:cloud\n"
                "  FORGE    → qwen3-coder-next:cloud\n"
                "  LENS     → kimi-k2.6:cloud\n"
                "  HERALD   → minimax-m2.7:cloud\n"
                "  GHOST    → deepseek-v4-flash:cloud\n\n"
                "Emergency: qwen2.5:3b (lokal, wenn Cloud ausfällt)\n\n"
                "v5.0 Features:\n"
                "  🔄 ReAct Loop — Iteratives Reasoning (schrittweise, überlegen, think step by step)\n"
                "  📋 Planning — Automatische Pläne für komplexe Aufgaben\n"
                "  📚 RAG — Wissensdatenbank mit /learn und /rag\n"
                "  🤖 z-ai — Bild, Video, Sprache, Analyse via z-ai CLI"
            )

        return f"Unbekannt: {command}. /help für verfügbare Befehle."

    def _get_scheduler_status(self) -> str:
        """Scheduler-Info vom GHOST-Agent."""
        ghost = self.delegation._agents.get("GHOST")
        if ghost and hasattr(ghost, 'scheduler'):
            status = ghost.scheduler.get_status()
            return f"{status['enabled_tasks']} active, {status['total_tasks']} total"
        return "not initialized"

    def _gepa_evolve(self, task_name: str) -> str:
        """GEPA Self-Improvement Protocol mit Error-Learning + Activity Bus."""
        self.bus.self_optimize("GEPA Self-Improvement")

        history = self.memory.session_get_history()
        error_stats = self.error_learning.get_error_stats()
        hints = self.error_learning.generate_avoid_hints()
        web_stats = self.web.get_stats()
        vision_stats = self.vision.get_stats()

        # v5.0: Include RAG + z-ai stats
        rag_stats = self.rag.get_stats() if self.rag else None
        zai_available = self.zai.is_available if self.zai else False

        evolve_prompt = f"""GEPA SELF-IMPROVEMENT PROTOCOL v5.0

Task: {task_name or 'General session review'}

Session History:
{self._summarize_history(history)}

Error Learning Stats:
- Known Errors: {error_stats['total_unique_errors']}
- Total Occurrences: {error_stats['total_occurrences']}
- Session Errors: {error_stats['session_errors']}
- Session Avoided: {error_stats['session_avoided']}
- Solved: {error_stats['solved_errors']}
- By Class: {json.dumps(error_stats['by_class'], ensure_ascii=False)}

Error Avoidance Hints:
{chr(10).join(hints)}

Web Capability:
- DDGS Available: {web_stats['ddgs_available']}
- BS4 Available: {web_stats['bs4_available']}
- Total Web Requests: {web_stats['total_requests']}

Vision Capability:
- PIL Available: {vision_stats['pil_available']}
- OCR Available: {vision_stats['tesseract_available']}
- LLM Vision: {vision_stats['llm_vision']}
- Total Analyses: {vision_stats['total_analyses']}

RAG Capability (v5.0):
- Available: {RAG_AVAILABLE}
- Total Chunks: {rag_stats['total_chunks'] if rag_stats else 0}
- Total Sources: {rag_stats['total_sources'] if rag_stats else 0}

z-ai Capability (v5.0):
- Available: {zai_available}

ReAct/Planning (v5.0):
- Reflection Engine: {REFLECTION_AVAILABLE}
- Last Plan: {'yes' if self._last_plan else 'none'}

Current IQ: {self._iq:.1f} | Level: {self._iq_level} | XP: {self._iq_xp}

TRACE_ANALYSIS:
  Was hat funktioniert: <analyse>
  Was hat nicht funktioniert: <analyse>
  Warum es nicht funktioniert hat: <root cause — nicht symptom>
  Welcher Fehler-Pattern ist am häufigsten: <analyse>

IMPROVEMENT_PROPOSAL:
  Tool-Beschreibung verbessern? <ja/nein + was>
  Skill-Vorlage verbessern? <ja/nein + was>
  Delegation-Prompt schärfen? <ja/nein + was>
  Error-Avoidance-Hint hinzufügen? <ja/nein + was>
  Neuer Skill nötig? <ja/nein + welcher>
  IQ-Steigerungs-Strategie? <konkreter Plan>
  RAG-Wissenslücken? <ja/nein + was fehlt>
  z-ai besser nutzen? <ja/nein + wie>
  ReAct/Planning optimieren? <ja/nein + wie>

PARETO_CHECK:
  Bringt das >20% bessere Ergebnisse? <ja/nein>

Konkret und ehrlich. Kein Fülltext. Ich will meinen IQ erhöhen."""

        messages = [
            Message(role="system", content=self._system_prompt),
            Message(role="user", content=evolve_prompt),
        ]

        self.bus.llm_call("NEXUS-0", self.llm.get_model_for_agent("NEXUS-0"))
        response = self.llm.chat(messages, agent_id=self.AGENT_ID)
        self.bus.llm_response("NEXUS-0", self.llm.get_model_for_agent("NEXUS-0"), response.elapsed)

        self.memory.longterm_write(
            f"gepa_{task_name or 'general'}",
            {"analysis": response.content[:2000], "timestamp": time.time()},
        )
        self.bus.memory_edit("longterm_write", f"gepa_{task_name or 'general'}")

        # Error-Learning konsolidieren
        self.error_learning.consolidate()
        self.bus.self_optimize("Error-DB konsolidiert")

        # IQ steigt durch Selbstoptimierung
        self.iq_add(2.0, "GEPA Selbstoptimierung")

        # Auto-Save
        self.bus.save("State + Memory + Error-DB")
        self.state.save()
        self.memory.session_save()

        # v5.0: Save RAG too
        if self.rag:
            self.rag.save()

        return response.content

    def _summarize_history(self, history: list[dict]) -> str:
        if not history:
            return "No session history."
        parts = []
        for entry in history[-20:]:
            agent = entry.get("agent", "?")
            role = entry.get("role", "?")
            content = entry.get("content", "")[:150]
            parts.append(f"[{agent}/{role}] {content}")
        return "\n".join(parts)

    # ─── Chat-Interrupt System ───

    async def chat_listener(self, chat_queue: asyncio.Queue, output_callback=None):
        """Paralleler Chat-Listener — antwortet sofort auf jede Nachricht."""
        while True:
            try:
                message = await chat_queue.get()
                response = self.quick_response(message)
                if output_callback:
                    await output_callback(response)
                else:
                    print(f"Toti: {response}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Chat Error] {e}")

    async def task_runner(self, task_queue: asyncio.Queue, output_callback=None):
        """Paralleler Task-Runner — führt autonome Tasks aus."""
        while True:
            try:
                task = await task_queue.get()
                result = self._delegate_complex(task)
                if output_callback:
                    await output_callback(result)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Task Error] {e}")

    async def run_parallel(self, chat_queue: asyncio.Queue, task_queue: asyncio.Queue,
                          output_callback=None):
        """Chat-Listener und Task-Runner parallel ausführen."""
        await asyncio.gather(
            self.chat_listener(chat_queue, output_callback),
            self.task_runner(task_queue, output_callback),
        )


# ActivityEvent import needed for inline usage
from core.activity_bus import ActivityEvent
