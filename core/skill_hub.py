"""
NEXUS Skill Hub — Dynamic skill loading from built-in and external skill repositories.

The Skill Hub allows NEXUS to:
1. Load built-in skills from the skills/ directory
2. Download skills from the NEXUS Skill Hub (GitHub-based)
3. Convert Hermes-compatible skills to NEXUS format
4. Auto-update skills on startup

Each skill is a Python module with an execute() function and metadata.

Usage:
    from core.skill_hub import SkillHub

    hub = SkillHub()
    await hub.initialize()

    # List available skills
    skills = hub.list_skills()

    # Execute a skill
    result = await hub.execute("web_research", query="python async patterns")

    # Install a skill from the hub
    await hub.install("sentiment_analysis")
"""

import json
import os
import importlib
import asyncio
import hashlib
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from pathlib import Path
from enum import Enum


class SkillStatus(Enum):
    AVAILABLE = "available"       # Installed and ready
    INSTALLED = "installed"       # Installed but not verified
    DOWNLOADING = "downloading"  # Currently downloading
    ERROR = "error"              # Has errors
    DISABLED = "disabled"         # Manually disabled


@dataclass
class SkillMetadata:
    """Metadata for a NEXUS skill."""
    name: str
    version: str = "1.0.0"
    description: str = ""
    category: str = "general"      # coding, research, devops, creative, analysis, general
    author: str = "NEXUS"
    tags: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)   # Required skills
    packages: List[str] = field(default_factory=list)    # Required pip packages
    agents: List[str] = field(default_factory=list)      # Recommended agents
    status: SkillStatus = SkillStatus.AVAILABLE
    installed_at: float = 0.0
    updated_at: float = 0.0
    source: str = "built-in"       # "built-in", "hub", "local"
    hub_url: str = ""             # Download URL for hub skills

    @property
    def is_available(self) -> bool:
        return self.status in (SkillStatus.AVAILABLE, SkillStatus.INSTALLED)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "requires": self.requires,
            "agents": self.agents,
            "status": self.status.value,
            "source": self.source,
        }


@dataclass
class SkillResult:
    """Result from executing a skill."""
    success: bool
    data: Any = None
    error: str = ""
    skill_name: str = ""
    execution_time: float = 0.0
    tokens_used: int = 0


# ── Built-in skills with metadata ────────────────────────────────────

BUILTIN_SKILLS = {
    "web_research": SkillMetadata(
        name="web_research",
        version="2.0.0",
        description="Tiefgehende Web-Recherche mit Quellen-Triangulation",
        category="research",
        tags=["web", "research", "search", "analysis"],
        agents=["SCOUT", "LENS"],
    ),
    "code_debug": SkillMetadata(
        name="code_debug",
        version="2.0.0",
        description="Code debuggen mit Error-Root-Cause-Analyse",
        category="coding",
        tags=["code", "debug", "error", "fix"],
        agents=["FORGE", "SCOUT"],
    ),
    "code_review": SkillMetadata(
        name="code_review",
        version="2.0.0",
        description="Code-Review mit Qualitäts-Bewertung",
        category="coding",
        tags=["code", "review", "quality"],
        agents=["SCOUT", "FORGE"],
    ),
    "security_scan": SkillMetadata(
        name="security_scan",
        version="2.0.0",
        description="Sicherheits-Scan für Code und Dependencies",
        category="devops",
        tags=["security", "vulnerability", "audit"],
        agents=["GHOST", "FORGE"],
    ),
    "data_extract": SkillMetadata(
        name="data_extract",
        version="2.0.0",
        description="Daten aus verschiedenen Quellen extrahieren",
        category="research",
        tags=["data", "extraction", "parsing"],
        agents=["SCOUT", "LENS"],
    ),
    "test_gen": SkillMetadata(
        name="test_gen",
        version="2.0.0",
        description="Test-Code automatisch generieren",
        category="coding",
        tags=["testing", "generation", "quality"],
        agents=["FORGE"],
    ),
    "doc_gen": SkillMetadata(
        name="doc_gen",
        version="2.0.0",
        description="Dokumentation generieren",
        category="creative",
        tags=["documentation", "writing", "generation"],
        agents=["HERALD"],
    ),
    "deploy_prep": SkillMetadata(
        name="deploy_prep",
        version="2.0.0",
        description="Deployment vorbereiten und validieren",
        category="devops",
        tags=["deployment", "ci-cd", "validation"],
        agents=["FORGE", "GHOST"],
    ),
    "dependency_check": SkillMetadata(
        name="dependency_check",
        version="2.0.0",
        description="Dependencies prüfen auf Updates und Konflikte",
        category="devops",
        tags=["dependencies", "packages", "updates"],
        agents=["GHOST"],
    ),
    "performance": SkillMetadata(
        name="performance",
        version="2.0.0",
        description="Performance-Analyse und Optimierung",
        category="coding",
        tags=["performance", "optimization", "profiling"],
        agents=["FORGE", "LENS"],
    ),
}

# ── Hub skills available for download ────────────────────────────────

HUB_SKILLS = {
    "github_integration": SkillMetadata(
        name="github_integration",
        version="1.0.0",
        description="GitHub API Integration — Issues, PRs, Repos verwalten",
        category="coding",
        tags=["github", "git", "api"],
        agents=["FORGE", "GHOST"],
        source="hub",
        hub_url="https://raw.githubusercontent.com/***REMOVED***/nexus-skills/main/skills/github_integration.py",
    ),
    "gitlab_integration": SkillMetadata(
        name="gitlab_integration",
        version="1.0.0",
        description="GitLab API Integration — Issues, MRs, Pipelines",
        category="coding",
        tags=["gitlab", "git", "api"],
        agents=["FORGE"],
        source="hub",
        hub_url="https://raw.githubusercontent.com/***REMOVED***/nexus-skills/main/skills/gitlab_integration.py",
    ),
    "database_query": SkillMetadata(
        name="database_query",
        version="1.0.0",
        description="SQL und NoSQL Datenbank-Abfragen generieren und ausführen",
        category="coding",
        tags=["database", "sql", "query"],
        agents=["FORGE", "LENS"],
        source="hub",
        hub_url="https://raw.githubusercontent.com/***REMOVED***/nexus-skills/main/skills/database_query.py",
    ),
    "api_testing": SkillMetadata(
        name="api_testing",
        version="1.0.0",
        description="REST API Testing und Validation",
        category="coding",
        tags=["api", "testing", "rest"],
        agents=["FORGE", "SCOUT"],
        source="hub",
        hub_url="https://raw.githubusercontent.com/***REMOVED***/nexus-skills/main/skills/api_testing.py",
    ),
    "sentiment_analysis": SkillMetadata(
        name="sentiment_analysis",
        version="1.0.0",
        description="Sentiment-Analyse und Meinungs-Auswertung",
        category="analysis",
        tags=["sentiment", "nlp", "analysis"],
        agents=["LENS", "HERALD"],
        source="hub",
        hub_url="https://raw.githubusercontent.com/***REMOVED***/nexus-skills/main/skills/sentiment_analysis.py",
    ),
    "translation": SkillMetadata(
        name="translation",
        version="1.0.0",
        description="Mehrsprachige Übersetzung mit Kontext-Erhaltung",
        category="creative",
        tags=["translation", "language", "i18n"],
        agents=["HERALD"],
        source="hub",
        hub_url="https://raw.githubusercontent.com/***REMOVED***/nexus-skills/main/skills/translation.py",
    ),
    "diagram_gen": SkillMetadata(
        name="diagram_gen",
        version="1.0.0",
        description="Architektur-Diagramme und Flowcharts generieren",
        category="creative",
        tags=["diagram", "visualization", "architecture"],
        agents=["HERALD", "FORGE"],
        source="hub",
        hub_url="https://raw.githubusercontent.com/***REMOVED***/nexus-skills/main/skills/diagram_gen.py",
    ),
    "project_planning": SkillMetadata(
        name="project_planning",
        version="1.0.0",
        description="Projektplanung — Epics, Stories, Aufwandschätzung",
        category="analysis",
        tags=["planning", "project", "estimation"],
        agents=["NEXUS-0", "LENS"],
        source="hub",
        hub_url="https://raw.githubusercontent.com/***REMOVED***/nexus-skills/main/skills/project_planning.py",
    ),
    "image_analysis": SkillMetadata(
        name="image_analysis",
        version="1.0.0",
        description="Bildanalyse mit VLM — OCR, Beschreibung, Vergleich",
        category="analysis",
        tags=["image", "vision", "ocr"],
        agents=["LENS"],
        source="hub",
        hub_url="https://raw.githubusercontent.com/***REMOVED***/nexus-skills/main/skills/image_analysis.py",
    ),
    "system_monitoring": SkillMetadata(
        name="system_monitoring",
        version="1.0.0",
        description="System-Monitoring — CPU, RAM, Disk, Prozesse überwachen",
        category="devops",
        tags=["monitoring", "system", "health"],
        agents=["GHOST"],
        source="hub",
        hub_url="https://raw.githubusercontent.com/***REMOVED***/nexus-skills/main/skills/system_monitoring.py",
    ),
}


class SkillHub:
    """
    Central skill registry and executor for NEXUS.

    Manages built-in skills, hub skills, and dynamic skill loading.
    """

    def __init__(self, skills_dir: str = "skills", data_dir: str = "data/skills"):
        self.skills_dir = Path(skills_dir)
        self.data_dir = Path(data_dir)
        self._registry: Dict[str, SkillMetadata] = {}
        self._modules: Dict[str, Any] = {}
        self._data_dir.mkdir(parents=True, exist_ok=True)

    async def initialize(self):
        """Initialize the skill hub — scan built-in skills and load registry."""
        # Register built-in skills
        for name, meta in BUILTIN_SKILLS.items():
            self._registry[name] = meta

        # Scan installed hub skills
        self._scan_hub_skills()

        # Load saved registry
        self._load_registry()

    def _scan_hub_skills(self):
        """Scan for installed hub skills in the data directory."""
        if not self.data_dir.exists():
            return

        for skill_dir in self.data_dir.iterdir():
            if skill_dir.is_dir():
                meta_file = skill_dir / "skill.json"
                if meta_file.exists():
                    try:
                        with open(meta_file) as f:
                            data = json.load(f)
                        meta = SkillMetadata(**data)
                        meta.status = SkillStatus.INSTALLED
                        meta.source = "hub"
                        self._registry[meta.name] = meta
                    except Exception:
                        pass

    def list_skills(self, category: str = None, agent: str = None) -> List[SkillMetadata]:
        """List all available skills, optionally filtered by category or agent."""
        skills = list(self._registry.values())

        if category:
            skills = [s for s in skills if s.category == category]

        if agent:
            skills = [s for s in skills if not s.agents or agent in s.agents]

        return sorted(skills, key=lambda s: (s.category, s.name))

    def list_hub_skills(self) -> List[SkillMetadata]:
        """List skills available in the hub but not yet installed."""
        installed = set(self._registry.keys())
        return [s for name, s in HUB_SKILLS.items() if name not in installed or s.source == "hub"]

    def get_skill(self, name: str) -> Optional[SkillMetadata]:
        """Get metadata for a specific skill."""
        return self._registry.get(name)

    async def execute(self, name: str, **kwargs) -> SkillResult:
        """Execute a skill by name."""
        start_time = time.time()

        meta = self._registry.get(name)
        if not meta:
            return SkillResult(
                success=False,
                error=f"Skill '{name}' not found",
                skill_name=name,
                execution_time=0.0,
            )

        if not meta.is_available:
            return SkillResult(
                success=False,
                error=f"Skill '{name}' is {meta.status.value}",
                skill_name=name,
                execution_time=0.0,
            )

        # Load module if not cached
        module = self._load_skill_module(name)
        if not module:
            return SkillResult(
                success=False,
                error=f"Cannot load skill module '{name}'",
                skill_name=name,
                execution_time=time.time() - start_time,
            )

        # Execute
        try:
            if asyncio.iscoroutinefunction(module.execute):
                result = await module.execute(**kwargs)
            else:
                result = module.execute(**kwargs)

            execution_time = time.time() - start_time

            if isinstance(result, dict):
                return SkillResult(
                    success=result.get("success", True),
                    data=result.get("data", result),
                    error=result.get("error", ""),
                    skill_name=name,
                    execution_time=execution_time,
                )
            else:
                return SkillResult(
                    success=True,
                    data=result,
                    skill_name=name,
                    execution_time=execution_time,
                )

        except Exception as e:
            return SkillResult(
                success=False,
                error=str(e),
                skill_name=name,
                execution_time=time.time() - start_time,
            )

    def _load_skill_module(self, name: str) -> Optional[Any]:
        """Load a skill module by name."""
        if name in self._modules:
            return self._modules[name]

        # Try built-in first
        try:
            module = importlib.import_module(f"skills.{name}")
            self._modules[name] = module
            return module
        except ImportError:
            pass

        # Try hub skill from data directory
        skill_path = self.data_dir / name / "skill.py"
        if skill_path.exists():
            try:
                spec = importlib.util.spec_from_file_location(f"skill_{name}", skill_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self._modules[name] = module
                return module
            except Exception:
                pass

        return None

    async def install_skill(self, name: str) -> SkillResult:
        """Install a skill from the hub."""
        hub_skill = HUB_SKILLS.get(name)
        if not hub_skill:
            return SkillResult(
                success=False,
                error=f"Skill '{name}' not found in hub",
                skill_name=name,
            )

        # Create skill directory
        skill_dir = self.data_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)

        # Download skill module
        try:
            import urllib.request
            urllib.request.urlretrieve(hub_skill.hub_url, skill_dir / "skill.py")
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Failed to download skill: {e}",
                skill_name=name,
            )

        # Save metadata
        meta_data = asdict(hub_skill)
        meta_data["status"] = SkillStatus.INSTALLED.value
        meta_data["installed_at"] = time.time()
        with open(skill_dir / "skill.json", "w") as f:
            json.dump(meta_data, f, indent=2)

        # Register
        hub_skill.status = SkillStatus.INSTALLED
        hub_skill.installed_at = time.time()
        self._registry[name] = hub_skill
        self._save_registry()

        return SkillResult(success=True, skill_name=name)

    def _load_registry(self):
        """Load the skill registry from disk."""
        registry_file = self.data_dir / "registry.json"
        if not registry_file.exists():
            return

        try:
            with open(registry_file) as f:
                data = json.load(f)
            for name, skill_data in data.get("skills", {}).items():
                if name not in self._registry:
                    meta = SkillMetadata(**skill_data)
                    self._registry[name] = meta
        except Exception:
            pass

    def _save_registry(self):
        """Save the skill registry to disk."""
        registry_file = self.data_dir / "registry.json"
        data = {
            "skills": {
                name: meta.to_dict() for name, meta in self._registry.items()
            },
            "last_updated": time.time(),
        }
        with open(registry_file, "w") as f:
            json.dump(data, f, indent=2)

    def get_categories(self) -> List[str]:
        """Get all unique skill categories."""
        return sorted(set(meta.category for meta in self._registry.values()))

    def get_skills_for_agent(self, agent: str) -> List[SkillMetadata]:
        """Get all skills recommended for an agent."""
        return [
            meta for meta in self._registry.values()
            if not meta.agents or agent in meta.agents
        ]

    def get_summary(self) -> dict:
        """Get a summary of the skill hub."""
        categories = {}
        for meta in self._registry.values():
            if meta.category not in categories:
                categories[meta.category] = []
            categories[meta.category].append(meta.name)

        return {
            "total_skills": len(self._registry),
            "built_in": len([m for m in self._registry.values() if m.source == "built-in"]),
            "hub_installed": len([m for m in self._registry.values() if m.source == "hub"]),
            "categories": categories,
            "hub_available": len(HUB_SKILLS) - len([
                m for m in self._registry.values() if m.source == "hub"
            ]),
        }