"""
NEXUS v9.2 — Agent Profiles
Persistent agent configuration with performance tracking and auto-evolution.

Each agent has a YAML profile with:
- System prompt (pre-trained from skills)
- Model assignment
- Skill pack (which skills the agent knows)
- Performance metrics (success rate, avg time, tasks completed)
- Evolution insights (learned patterns, auto-evolved prompts)

Profiles are loaded at startup and updated after each task.
Auto-evolution runs periodically to improve agent prompts based on success patterns.
"""

import os
import yaml
import json
import time
import logging
from pathlib import Path
from typing import Optional, List, Dict
from dataclasses import dataclass, field, asdict

log = logging.getLogger("nexus.agent_profiles")

PROFILES_DIR = Path("data/agents")
MAX_EVOLUTION_INSIGHTS = 20  # Keep last N insights per agent
EVOLUTION_INTERVAL = 10  # Run auto-evolution every N tasks


@dataclass
class PerformanceMetrics:
    """Performance tracking for an agent."""
    tasks_completed: int = 0
    tasks_failed: int = 0
    success_rate: float = 0.0
    avg_time_s: float = 0.0
    total_time_s: float = 0.0
    last_updated: str = ""

    @property
    def total_tasks(self) -> int:
        return self.tasks_completed + self.tasks_failed


@dataclass
class EvolutionInsight:
    """A learned pattern or prompt improvement."""
    date: str
    insight: str
    from_task: str = ""  # Task ID that generated this insight
    impact: str = "neutral"  # positive, neutral, negative


@dataclass
class AgentProfile:
    """Complete agent profile with configuration and performance data."""
    name: str
    role: str = ""
    model: str = "default"
    system_prompt: str = ""
    max_turns: int = 3
    skills: List[str] = field(default_factory=list)
    performance: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    evolution: List[Dict] = field(default_factory=list)
    created: str = ""
    version: str = "1.0.0"

    def to_dict(self) -> dict:
        """Convert to dict for YAML serialization."""
        d = {
            "name": self.name,
            "role": self.role,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "max_turns": self.max_turns,
            "skills": self.skills,
            "performance": asdict(self.performance),
            "evolution": self.evolution,
            "created": self.created or time.strftime("%Y-%m-%d"),
            "version": self.version,
        }
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "AgentProfile":
        """Create from dict (loaded from YAML)."""
        perf_data = data.get("performance", {})
        performance = PerformanceMetrics(
            tasks_completed=perf_data.get("tasks_completed", 0),
            tasks_failed=perf_data.get("tasks_failed", 0),
            success_rate=perf_data.get("success_rate", 0.0),
            avg_time_s=perf_data.get("avg_time_s", 0.0),
            total_time_s=perf_data.get("total_time_s", 0.0),
            last_updated=perf_data.get("last_updated", ""),
        )
        return cls(
            name=data.get("name", "unknown"),
            role=data.get("role", ""),
            model=data.get("model", "default"),
            system_prompt=data.get("system_prompt", ""),
            max_turns=data.get("max_turns", 3),
            skills=data.get("skills", []),
            performance=performance,
            evolution=data.get("evolution", []),
            created=data.get("created", ""),
            version=data.get("version", "1.0.0"),
        )


def load_profile(name: str) -> Optional[AgentProfile]:
    """Load an agent profile from YAML file."""
    profile_path = PROFILES_DIR / f"{name}.yaml"
    if not profile_path.exists():
        # Try with .yml extension
        profile_path = PROFILES_DIR / f"{name}.yml"
        if not profile_path.exists():
            return None

    try:
        data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return AgentProfile.from_dict(data)
    except Exception as e:
        log.warning(f"Failed to load agent profile {name}: {e}")
    return None


def save_profile(profile: AgentProfile) -> bool:
    """Save an agent profile to YAML file."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    profile_path = PROFILES_DIR / f"{profile.name}.yaml"

    try:
        data = profile.to_dict()
        content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        profile_path.write_text(content, encoding="utf-8")
        log.info(f"Saved agent profile: {profile.name}")
        return True
    except Exception as e:
        log.error(f"Failed to save agent profile {profile.name}: {e}")
        return False


def load_all_profiles() -> Dict[str, dict]:
    """
    Load all agent profiles as raw dicts (for AgentTeam initialization).
    Returns {name: profile_dict} mapping.
    """
    profiles = {}
    if not PROFILES_DIR.exists():
        return profiles

    for profile_file in PROFILES_DIR.glob("*.yaml"):
        try:
            data = yaml.safe_load(profile_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "name" in data:
                profiles[data["name"].lower()] = data
        except Exception as e:
            log.warning(f"Failed to load profile {profile_file}: {e}")

    # Also try .yml files
    for profile_file in PROFILES_DIR.glob("*.yml"):
        try:
            data = yaml.safe_load(profile_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "name" in data:
                profiles[data["name"].lower()] = data
        except Exception as e:
            log.warning(f"Failed to load profile {profile_file}: {e}")

    return profiles


def update_performance(department: str, success: bool, elapsed: float) -> bool:
    """Update agent profile performance metrics after a task."""
    profile = load_profile(department)
    if profile is None:
        # Create default profile if it doesn't exist
        profile = _create_default_profile(department)

    # Update metrics
    if success:
        profile.performance.tasks_completed += 1
    else:
        profile.performance.tasks_failed += 1

    total = profile.performance.tasks_completed + profile.performance.tasks_failed
    profile.performance.success_rate = (
        profile.performance.tasks_completed / total if total > 0 else 0.0
    )
    profile.performance.total_time_s += elapsed
    profile.performance.avg_time_s = (
        profile.performance.total_time_s / total if total > 0 else 0.0
    )
    profile.performance.last_updated = time.strftime("%Y-%m-%d")

    # Check if auto-evolution should run
    if total % EVOLUTION_INTERVAL == 0 and total > 0:
        _schedule_auto_evolution(profile)

    return save_profile(profile)


def _create_default_profile(name: str) -> AgentProfile:
    """Create a default profile for a department."""
    defaults = {
        "ceo": AgentProfile(
            name="ceo",
            role="Entscheidet Prioritaeten, delegiert Aufgaben, prueft Ergebnisse.",
            model="orchestrator",
            system_prompt="Du bist der CEO bei Nexus. Entscheide strategisch, priorisiere, delegiere. Antworte direkt und ergebnisorientiert.",
            max_turns=2,
        ),
        "research": AgentProfile(
            name="research",
            role="Recherchiert Fakten, analysiert, beschafft Informationen.",
            model="allrounder",
            system_prompt="Du bist Research bei Nexus. Recherchiere gründlich, prüfe Fakten, strukturiere Informationen. Nutze web_search und web_fetch.",
            max_turns=3,
        ),
        "engineering": AgentProfile(
            name="engineering",
            role="Schreibt Code, baut Features, fixt Bugs, deployed.",
            model="coding",
            system_prompt="Du bist Engineering bei Nexus. Schreibe sauberen Code, implementiere Features, fixe Bugs. Nutzt terminal, file_write, code_exec.",
            max_turns=5,
        ),
        "creative": AgentProfile(
            name="creative",
            role="Design, Texte, UI/UX, Präsentationen.",
            model="creative",
            system_prompt="Du bist Creative bei Nexus. Kreativ und professionell. Design, Text, UI/UX, Präsentationen.",
            max_turns=3,
        ),
        "operations": AgentProfile(
            name="operations",
            role="Planung, Organisation, Monitoring, Reporting.",
            model="fast",
            system_prompt="Du bist Operations bei Nexus. Schnell und effizient. Planung, Organisation, Monitoring, Reporting.",
            max_turns=2,
        ),
    }
    profile = defaults.get(name, AgentProfile(name=name, role=f"Spezialist fuer {name}"))
    profile.created = time.strftime("%Y-%m-%d")
    return profile


def _schedule_auto_evolution(profile: AgentProfile):
    """
    Analyze performance patterns and add evolution insights.
    This is a lightweight analysis — no LLM call, just pattern detection.
    Full LLM-based evolution can be triggered manually via /agent evolve.
    """
    perf = profile.performance

    insights = []

    # Pattern: Low success rate → suggest prompt refinement
    if perf.success_rate < 0.7 and perf.total_tasks >= 5:
        insights.append({
            "date": time.strftime("%Y-%m-%d"),
            "insight": f"Erfolgsrate niedrig ({perf.success_rate:.0%}). Prompt könnte spezifischer sein.",
            "from_task": "",
            "impact": "negative",
        })

    # Pattern: High success rate → positive reinforcement
    if perf.success_rate >= 0.9 and perf.total_tasks >= 5:
        insights.append({
            "date": time.strftime("%Y-%m-%d"),
            "insight": f"Hohe Erfolgsrate ({perf.success_rate:.0%}). Aktuelle Konfiguration funktioniert gut.",
            "from_task": "",
            "impact": "positive",
        })

    # Pattern: Slow responses → suggest model change
    if perf.avg_time_s > 20 and perf.total_tasks >= 3:
        insights.append({
            "date": time.strftime("%Y-%m-%d"),
            "insight": f"Langsame Antworten (Ø {perf.avg_time_s:.1f}s). Schnelleres Modell erwägen.",
            "from_task": "",
            "impact": "neutral",
        })

    # Add insights (keep only last MAX_EVOLUTION_INSIGHTS)
    profile.evolution.extend(insights)
    if len(profile.evolution) > MAX_EVOLUTION_INSIGHTS:
        profile.evolution = profile.evolution[-MAX_EVOLUTION_INSIGHTS:]


def create_profile(name: str, role: str, model: str = "default",
                   system_prompt: str = "", skills: List[str] = None) -> AgentProfile:
    """Create a new agent profile (for /agent create command)."""
    profile = AgentProfile(
        name=name.lower().strip(),
        role=role,
        model=model,
        system_prompt=system_prompt or f"Du bist {name} bei Nexus. {role}",
        skills=skills or [],
        created=time.strftime("%Y-%m-%d"),
    )
    save_profile(profile)
    log.info(f"Created agent profile: {profile.name}")
    return profile


def assign_skill(agent_name: str, skill_name: str) -> bool:
    """Assign a skill to an agent profile."""
    profile = load_profile(agent_name)
    if profile is None:
        log.warning(f"Agent profile not found: {agent_name}")
        return False

    if skill_name not in profile.skills:
        profile.skills.append(skill_name)
        return save_profile(profile)
    return True  # Already assigned


def list_profiles() -> List[Dict]:
    """List all agent profiles with basic stats."""
    profiles = load_all_profiles()
    result = []
    for name, data in profiles.items():
        perf = data.get("performance", {})
        result.append({
            "name": data.get("name", name),
            "role": data.get("role", ""),
            "model": data.get("model", "default"),
            "tasks_completed": perf.get("tasks_completed", 0),
            "success_rate": perf.get("success_rate", 0.0),
            "skills_count": len(data.get("skills", [])),
        })
    return result


def get_stats(agent_name: str) -> Optional[Dict]:
    """Get detailed stats for a specific agent."""
    profile = load_profile(agent_name)
    if profile is None:
        return None
    return {
        "name": profile.name,
        "role": profile.role,
        "model": profile.model,
        "skills": profile.skills,
        "performance": asdict(profile.performance),
        "evolution_count": len(profile.evolution),
        "last_evolution": profile.evolution[-1] if profile.evolution else None,
    }


def evolve_profile(agent_name: str, llm_client=None) -> Optional[AgentProfile]:
    """
    Run LLM-based auto-evolution for an agent profile.
    Analyzes performance data and evolution insights to improve the system prompt.
    """
    profile = load_profile(agent_name)
    if profile is None:
        log.warning(f"Agent profile not found for evolution: {agent_name}")
        return None

    if llm_client is None:
        log.info(f"LLM-based evolution not available for {agent_name}, using pattern-based only")
        _schedule_auto_evolution(profile)
        return profile

    # Use LLM to analyze and suggest prompt improvements
    perf_summary = (
        f"Aufgaben: {profile.performance.tasks_completed} erfolgreich, "
        f"{profile.performance.tasks_failed} fehlgeschlagen. "
        f"Erfolgsrate: {profile.performance.success_rate:.0%}. "
        f"Ø Zeit: {profile.performance.avg_time_s:.1f}s."
    )

    evolution_context = ""
    if profile.evolution:
        recent = profile.evolution[-5:]
        evolution_context = "\n".join(
            f"- {e.get('date', '?')}: {e.get('insight', '?')}"
            for e in recent
        )

    messages = [
        Message("system",
            "Du bist ein Agent-Optimierer. Analysiere die Performance-Daten eines KI-Agenten "
            "und schlage konkrete Verbesserungen für seinen System-Prompt vor. "
            "Maximal 3 konkrete, umsetzbare Vorschläge. Keine Floskeln."),
        Message("user", f"Agent: {profile.name}\nRolle: {profile.role}\n"
                f"Aktueller Prompt: {profile.system_prompt[:500]}\n"
                f"Performance: {perf_summary}\n"
                f"Letzte Insights:\n{evolution_context}\n\n"
                "Schlage konkrete Verbesserungen für den System-Prompt vor."),
    ]

    try:
        response = llm_client.chat(messages, model_key="fast", max_tokens=256)
        if response.success and response.content.strip():
            insight = response.content.strip()[:500]
            profile.evolution.append({
                "date": time.strftime("%Y-%m-%d"),
                "insight": f"LLM-Evolution: {insight}",
                "from_task": "evolution",
                "impact": "neutral",
            })
            if len(profile.evolution) > MAX_EVOLUTION_INSIGHTS:
                profile.evolution = profile.evolution[-MAX_EVOLUTION_INSIGHTS:]
            save_profile(profile)
            log.info(f"LLM-based evolution completed for {agent_name}")
    except Exception as e:
        log.warning(f"LLM-based evolution failed for {agent_name}: {e}")

    return profile