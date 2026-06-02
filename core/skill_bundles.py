"""
NEXUS Skill Bundle System — Group skills into themed bundles for agent routing.

A Skill Bundle is a collection of related skills that can be loaded together
as a unit. Agents specify which bundles they need, and the system loads all
skills from those bundles automatically.

Inspired by Hermes Agent's skill_bundles.py, adapted for NEXUS's
per-agent routing architecture.
"""

import json
import os
import importlib
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SkillBundle:
    """A named collection of skills grouped by theme."""
    name: str
    description: str
    skills: List[str]            # Skill module names (e.g., "code_debug", "web_research")
    required_agents: List[str]    # Which agents should have this bundle
    priority: int = 50           # Load priority (lower = higher priority)
    tags: List[str] = field(default_factory=list)

    @property
    def skill_count(self) -> int:
        return len(self.skills)


# ── Predefined Bundles ──────────────────────────────────────────────

BUNDLES: Dict[str, SkillBundle] = {
    "coding": SkillBundle(
        name="coding",
        description="Code generation, review, debugging, and testing",
        skills=["code_debug", "code_review", "test_gen", "dependency_check", "performance"],
        required_agents=["SCOUT", "FORGE"],
        priority=10,
        tags=["development", "code", "testing"],
    ),
    "research": SkillBundle(
        name="research",
        description="Web research, data extraction, and documentation",
        skills=["web_research", "data_extract", "doc_gen"],
        required_agents=["SCOUT", "LENS"],
        priority=20,
        tags=["research", "web", "documentation"],
    ),
    "devops": SkillBundle(
        name="devops",
        description="Deployment, security scanning, and dependency management",
        skills=["deploy_prep", "security_scan", "dependency_check"],
        required_agents=["FORGE", "GHOST"],
        priority=30,
        tags=["devops", "deployment", "security"],
    ),
    "creative": SkillBundle(
        name="creative",
        description="Content creation, documentation, and presentation",
        skills=["doc_gen", "web_research", "data_extract"],
        required_agents=["HERALD"],
        priority=40,
        tags=["creative", "writing", "content"],
    ),
    "monitoring": SkillBundle(
        name="monitoring",
        description="System monitoring, error checking, and background tasks",
        skills=["security_scan", "dependency_check", "performance"],
        required_agents=["GHOST"],
        priority=50,
        tags=["monitoring", "maintenance", "background"],
    ),
    "full": SkillBundle(
        name="full",
        description="All skills loaded — maximum capability",
        skills=["web_research", "code_debug", "code_review", "security_scan",
                "data_extract", "test_gen", "doc_gen", "deploy_prep",
                "dependency_check", "performance"],
        required_agents=["NEXUS-0"],
        priority=100,
        tags=["full", "all", "maximum"],
    ),
}


class SkillBundleManager:
    """
    Manages skill bundles for the NEXUS agent system.
    Loads and validates skills, resolves bundle dependencies.
    """

    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = Path(skills_dir)
        self._loaded_skills: Dict[str, object] = {}
        self._available_skills: Set[str] = set()
        self._bundle_skills: Dict[str, Set[str]] = {}  # bundle_name -> set of skill names
        self._skill_bundles: Dict[str, Set[str]] = {}  # skill_name -> set of bundle names
        self._scan_skills()

    def _scan_skills(self):
        """Scan the skills directory for available skill modules."""
        if not self.skills_dir.exists():
            return

        for f in self.skills_dir.iterdir():
            if f.is_file() and f.suffix == ".py" and f.name != "__init__.py":
                skill_name = f.stem
                self._available_skills.add(skill_name)

        # Build reverse mapping
        for bundle_name, bundle in BUNDLES.items():
            self._bundle_skills[bundle_name] = set()
            for skill_name in bundle.skills:
                if skill_name not in self._skill_bundles:
                    self._skill_bundles[skill_name] = set()
                self._skill_bundles[skill_name].add(bundle_name)
                self._bundle_skills[bundle_name].add(skill_name)

    def get_bundles_for_agent(self, agent_name: str) -> List[SkillBundle]:
        """Get all bundles that an agent should have loaded."""
        bundles = []
        for bundle in BUNDLES.values():
            if agent_name in bundle.required_agents:
                bundles.append(bundle)
        bundles.sort(key=lambda b: b.priority)
        return bundles

    def get_skills_for_agent(self, agent_name: str) -> List[str]:
        """Get all skill names for an agent based on its bundles."""
        bundles = self.get_bundles_for_agent(agent_name)
        seen = set()
        skills = []
        for bundle in bundles:
            for skill in bundle.skills:
                if skill not in seen:
                    seen.add(skill)
                    skills.append(skill)
        return skills

    def load_skill(self, skill_name: str) -> Optional[object]:
        """Load a skill module by name."""
        if skill_name in self._loaded_skills:
            return self._loaded_skills[skill_name]

        try:
            module = importlib.import_module(f"skills.{skill_name}")
            self._loaded_skills[skill_name] = module
            return module
        except ImportError as e:
            print(f"[SkillBundle] Failed to load skill '{skill_name}': {e}")
            return None

    def load_bundles_for_agent(self, agent_name: str) -> Dict[str, List[str]]:
        """
        Load all skills for an agent's bundles.
        Returns dict of {bundle_name: [loaded_skill_names]}.
        """
        bundles = self.get_bundles_for_agent(agent_name)
        result = {}

        for bundle in bundles:
            loaded = []
            for skill_name in bundle.skills:
                if self.load_skill(skill_name):
                    loaded.append(skill_name)
            result[bundle.name] = loaded

        return result

    def list_available_skills(self) -> List[str]:
        """List all available skill names."""
        return sorted(self._available_skills)

    def list_bundles(self) -> Dict[str, SkillBundle]:
        """List all predefined bundles."""
        return BUNDLES.copy()

    def create_custom_bundle(self, name: str, description: str, skills: List[str],
                            agents: List[str] = None, tags: List[str] = None) -> SkillBundle:
        """Create a custom skill bundle at runtime."""
        bundle = SkillBundle(
            name=name,
            description=description,
            skills=[s for s in skills if s in self._available_skills],
            required_agents=agents or [],
            priority=60,
            tags=tags or [],
        )
        BUNDLES[name] = bundle

        # Update reverse mappings
        self._bundle_skills[name] = set(bundle.skills)
        for skill_name in bundle.skills:
            if skill_name not in self._skill_bundles:
                self._skill_bundles[skill_name] = set()
            self._skill_bundles[skill_name].add(name)

        return bundle

    def get_skill_description(self, skill_name: str) -> Optional[str]:
        """Get a human description of a skill from its docstring."""
        module = self.load_skill(skill_name)
        if module and module.__doc__:
            return module.__doc__.strip().split('\n')[0]
        return None

    def get_bundle_summary(self) -> str:
        """Get a formatted summary of all bundles."""
        lines = ["NEXUS Skill Bundles:", "=" * 40]
        for name, bundle in sorted(BUNDLES.items(), key=lambda x: x[1].priority):
            lines.append(f"\n📦 {name} (P{bundle.priority})")
            lines.append(f"   {bundle.description}")
            lines.append(f"   Skills: {', '.join(bundle.skills)}")
            lines.append(f"   Agents: {', '.join(bundle.required_agents)}")
        return "\n".join(lines)