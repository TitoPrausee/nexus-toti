"""
NEXUS CLI Interface — Toti Edition v2.0
Rich Terminal UI mit Error-Learning, LLM-Health, Skill-System und State-Display.
"""

import sys
import time
import asyncio
from typing import Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.prompt import Prompt
    from rich.theme import Theme
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from core.llm_client import LLMClient
from core.memory import MemorySystem
from core.tools import ToolRegistry
from core.state import StateManager
from core.guards import NexusGuards
from core.error_learning import ErrorLearningSystem
from agents.toti import TotiAgent
from agents.scout import ScoutAgent
from agents.forge import ForgeAgent
from agents.lens import LensAgent
from agents.herald import HeraldAgent
from agents.ghost import GhostAgent


TOTI_THEME = {
    "toti.brand": "#ff6b35 bold",
    "toti.agent": "#00d4ff bold",
    "toti.success": "#00ff88",
    "toti.warning": "#ffdd00",
    "toti.error": "#ff3366",
    "toti.dim": "#666666",
    "toti.info": "#888888",
}


class NexusCLI:
    """Terminal Interface für Toti-powered NEXUS v2.0."""

    def __init__(self, session_id: Optional[str] = None):
        self.console = Console(theme=Theme(TOTI_THEME)) if RICH_AVAILABLE else None
        self.llm = LLMClient()
        self.memory = MemorySystem(session_id=session_id)
        self.tools = ToolRegistry()
        self.state = StateManager()
        self.guards = NexusGuards()
        self.error_learning = ErrorLearningSystem()

        self.toti = TotiAgent(
            self.llm, self.memory, self.tools,
            self.state, self.guards, self.error_learning,
        )
        self._register_agents()
        self.running = False

    def _register_agents(self):
        agents = {
            "SCOUT": ScoutAgent(self.llm, self.memory, self.tools,
                                state=self.state, guards=self.guards, error_learning=self.error_learning),
            "FORGE": ForgeAgent(self.llm, self.memory, self.tools,
                                state=self.state, guards=self.guards, error_learning=self.error_learning),
            "LENS": LensAgent(self.llm, self.memory, self.tools,
                              state=self.state, guards=self.guards, error_learning=self.error_learning),
            "HERALD": HeraldAgent(self.llm, self.memory, self.tools,
                                  state=self.state, guards=self.guards, error_learning=self.error_learning),
            "GHOST": GhostAgent(self.llm, self.memory, self.tools,
                                state=self.state, guards=self.guards, error_learning=self.error_learning),
        }
        for aid, agent in agents.items():
            self.toti.register_agent(aid, agent)

        # Standard Scheduler-Tasks registrieren
        ghost = agents["GHOST"]
        ghost.register_scheduled_task("state_persist", "INTERVAL_TRIGGER",
                                       fn=lambda: self.state.save(), interval_seconds=60)
        ghost.register_scheduled_task("memory_compress", "INTERVAL_TRIGGER",
                                       fn=lambda: self.memory._compress_rolling_summary(), interval_seconds=300)
        ghost.register_scheduled_task("error_consolidate", "INTERVAL_TRIGGER",
                                       fn=lambda: self.error_learning.consolidate(), interval_seconds=600)

    def print(self, message: str, style: str = None):
        if self.console:
            self.console.print(message, style=style)
        else:
            print(message)

    def print_banner(self):
        banner = """
╔═══════════════════════════════════════════════════════╗
║                                                       ║
║   ████████╗ ██████╗ ██████╗ ███████╗                 ║
║   ╚══██╔══╝██╔═══██╗██╔══██╗██╔════╝                 ║
║      ██║   ██║   ██║██████╔╝███████╗                 ║
║      ██║   ██║   ██║██╔══██╗╚════██║                 ║
║      ██║   ╚██████╔╝██║  ██║███████║                 ║
║      ╚═╝    ╚═════╝ ╚═╝  ╚═╝╚══════╝                 ║
║                                                       ║
║   NEXUS System · Toti v2.0 · GLM Powered             ║
║   Error Learning · 22 Tools · 10 Skills              ║
║   Autonom · Direkt · Lernt aus Fehlern               ║
║                                                       ║
╚═══════════════════════════════════════════════════════╝
"""
        if self.console:
            self.console.print(banner, style="toti.brand")
        else:
            print(banner)

    def print_status_bar(self):
        guards = self.guards.get_status()
        llm_stats = self.llm.get_stats()
        error_stats = self.error_learning.get_error_stats()
        task = self.state.get("current_task.status", "idle")
        cli_status = "✓" if llm_stats["cli_available"] else "✗"

        self.print(
            f"  State: [toti.info]{task}[/] | "
            f"Budget: [toti.info]{guards['budget_used_pct']}%[/] | "
            f"Steps: [toti.info]{guards['steps']}/{guards['max_steps']}[/] | "
            f"LLM: [toti.info]{cli_status} {llm_stats['total_calls']} calls[/] | "
            f"Errors: [toti.info]{error_stats['total_unique_errors']} known/{error_stats['session_avoided']} avoided[/]"
        )

        # LLM Health
        health = self.llm.get_health_status()
        if health:
            models = health.get("health", {})
            model_status = " | ".join(
                f"{'✓' if v else '✗'}{k.split('-')[1][:5]}" for k, v in models.items()
            )
            self.print(f"  Models: [toti.info]{model_status}[/]")

    def run(self):
        self.running = True
        self.print_banner()

        # LLM Health-Check beim Start
        self.print("  [toti.dim]Prüfe LLM-Modelle...[/]")
        self.llm.run_health_check()
        self.print_status_bar()
        self.print("")
        self.print("  [toti.success]Toti v2.0 online. Fehler-Tracking aktiv. 22 Tools, 10 Skills bereit.[/]")
        self.print("  [toti.dim]/help für Befehle · Ctrl+C oder /quit zum Beenden.[/]")
        self.print("")

        while self.running:
            try:
                if self.console:
                    user_input = Prompt.ask("[toti.brand]Toti >[/]", console=self.console)
                else:
                    user_input = input("Toti > ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ("/quit", "/exit", "quit", "exit"):
                    self._shutdown()
                    break

                self.print("")
                start = time.time()

                try:
                    response = self.toti.process(user_input)
                    elapsed = time.time() - start

                    if self.console:
                        self.console.print(
                            Panel(
                                Markdown(response) if len(response) > 100 else response,
                                title="[toti.brand]Toti[/]",
                                subtitle=f"[toti.dim]{elapsed:.1f}s | Budget: {self.guards.get_status()['budget_used_pct']}%[/]",
                                border_style="toti.brand",
                            )
                        )
                    else:
                        print(f"\n--- Toti ({elapsed:.1f}s) ---")
                        print(response)
                        print("---")

                except Exception as e:
                    self.print(f"  [toti.error]Error: {str(e)}[/]")
                    # Fehler im Error-Learning aufzeichnen
                    self.error_learning.record_error(
                        error_class="AGENT_ERROR",
                        context=user_input[:200],
                        action=f"process({user_input[:100]})",
                        error_message=str(e),
                        agent="TOTI",
                    )

                # Auto-Save State
                self.state.save()
                self.memory.session_save()
                self.print("")

            except KeyboardInterrupt:
                self.print("\n  [toti.warning]Interrupted. /quit zum Beenden.[/]")
                continue
            except EOFError:
                self._shutdown()
                break

    def _shutdown(self):
        self.print("")
        self.print("  [toti.warning]Shutting down...[/]")

        # State speichern
        self.state.save()
        self.memory.session_save()

        # GHOST: persist
        ghost = self.toti.delegation._agents.get("GHOST")
        if ghost:
            ghost.save_session_state()

        # Error-Learning konsolidieren
        self.error_learning.consolidate()

        self.print("  [toti.success]State gespeichert. Fehler-DB aktualisiert. Bis dann.[/]")

    def process_single(self, task: str) -> str:
        """Single-Task-Modus — kein interaktiver Loop."""
        response = self.toti.process(task)
        self.state.save()
        self.memory.session_save()
        self.error_learning.consolidate()
        return response
