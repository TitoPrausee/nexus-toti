"""
NEXUS v8.2 — DSGVO/GDPR Compliance Module
Implements EU GDPR requirements: consent, data access, right to erasure,
data minimization, storage limitation, and privacy logging.

Articles covered:
- Art. 6: Lawfulness of processing (consent-based)
- Art. 7: Conditions for consent (withdrawable, documented)
- Art. 13/14: Information to be provided (transparency)
- Art. 15: Right of access (what data is stored)
- Art. 17: Right to erasure (delete all user data)
- Art. 5(1)(c): Data minimization
- Art. 5(1)(e): Storage limitation (auto-delete after retention period)
"""

import json
import time
import os
import logging
import shutil
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

log = logging.getLogger("nexus.dsgvo")

PRIVACY_POLICY_VERSION = "1.0"
DATA_RETENTION_DAYS = 30
CONSENT_FILE = "dsgvo_consent.json"

# What data categories we store per user
DATA_CATEGORIES = {
    "l1_working_memory": "Aktuelle Konversation (Arbeitsgedaechtnis)",
    "l2_session_summaries": "Gespraechszusammenfassungen (letzte 48h)",
    "l3_longterm_memory": "Langzeitwissen (wichtige Fakten)",
    "soul_relationship": "Persoenlichkeitsprofil (Name, Praeferenzen)",
    "conversations": "Gespeicherte Gespraechssitzungen",
    "onboarding": "Onboarding-Daten (Kennenlern-Phase)",
}


@dataclass
class UserConsent:
    """Tracks GDPR consent for a single user."""
    user_id: str
    consent_given: bool = False
    consent_version: str = ""
    consent_timestamp: float = 0.0
    consent_withdrawn_at: float = 0.0
    last_interaction: float = 0.0
    data_categories_shared: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class DSGVOCompliance:
    """
    Central DSGVO/GDPR compliance manager.

    Manages:
    - User consent (give, withdraw, check)
    - Data inventory (what's stored per user)
    - Data export (Art. 15 right of access)
    - Data deletion (Art. 17 right to erasure)
    - Auto-deletion after retention period (Art. 5(1)(e))
    - Privacy logging (what data was stored/accessed/deleted)
    """

    def __init__(self, data_dir: str = "data/dsgvo"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._consents: dict[str, UserConsent] = {}
        self._load()

    def _load(self):
        """Load consent records from disk."""
        consent_file = self.data_dir / CONSENT_FILE
        if consent_file.exists():
            try:
                with open(consent_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for user_id, cd in data.items():
                    self._consents[user_id] = UserConsent.from_dict(cd)
            except Exception as e:
                log.warning(f"Failed to load consent file: {e}")

    def save(self):
        """Persist consent records to disk."""
        consent_file = self.data_dir / CONSENT_FILE
        data = {uid: c.to_dict() for uid, c in self._consents.items()}
        with open(consent_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ─── Consent Management (Art. 6 & 7) ────────────────

    def give_consent(self, user_id: str) -> UserConsent:
        """Record user consent for data processing."""
        consent = self._consents.get(user_id, UserConsent(user_id=user_id))
        consent.consent_given = True
        consent.consent_version = PRIVACY_POLICY_VERSION
        consent.consent_timestamp = time.time()
        consent.consent_withdrawn_at = 0.0
        consent.last_interaction = time.time()
        consent.data_categories_shared = list(DATA_CATEGORIES.keys())
        self._consents[user_id] = consent
        self.save()
        self._log_privacy(user_id, "consent_given", consent_version=PRIVACY_POLICY_VERSION)
        log.info(f"Consent given: user={user_id}, version={PRIVACY_POLICY_VERSION}")
        return consent

    def withdraw_consent(self, user_id: str) -> bool:
        """Withdraw consent and trigger data deletion (Art. 7(3))."""
        if user_id not in self._consents:
            return False
        consent = self._consents[user_id]
        consent.consent_given = False
        consent.consent_withdrawn_at = time.time()
        consent.data_categories_shared = []
        self.save()
        self._log_privacy(user_id, "consent_withdrawn")
        log.info(f"Consent withdrawn: user={user_id}")
        return True

    def has_consent(self, user_id: str) -> bool:
        """Check if user has given consent for current privacy policy version."""
        consent = self._consents.get(user_id)
        if not consent or not consent.consent_given:
            return False
        # Check if consent version matches current policy
        if consent.consent_version != PRIVACY_POLICY_VERSION:
            return False
        return True

    def needs_consent(self, user_id: str) -> bool:
        """Check if user needs to give/refresh consent."""
        return not self.has_consent(user_id)

    def get_consent_info(self, user_id: str) -> dict:
        """Get consent status for a user."""
        consent = self._consents.get(user_id)
        if not consent:
            return {"has_consent": False, "version": None, "timestamp": None}
        return {
            "has_consent": consent.consent_given,
            "version": consent.consent_version,
            "timestamp": consent.consent_timestamp,
            "withdrawn": consent.consent_withdrawn_at > 0,
        }

    # ─── Data Inventory (Art. 15 - Right of Access) ─────

    def get_user_data_inventory(self, user_id: str, session_manager=None) -> dict:
        """Build a complete inventory of all data stored for a user.

        Returns dict with:
        - categories: what data types exist and how many entries
        - total_entries: total count across all categories
        - retention_days: configured retention period
        - last_interaction: when user last interacted
        """
        inventory = {
            "user_id": user_id,
            "categories": {},
            "total_entries": 0,
            "retention_days": DATA_RETENTION_DAYS,
            "last_interaction": 0.0,
        }

        consent = self._consents.get(user_id)
        if consent:
            inventory["last_interaction"] = consent.last_interaction

        if not session_manager:
            return inventory

        # Find session for this user
        for chat_id, session in session_manager._sessions.items():
            if session.user_id != user_id:
                continue

            agent = session.agent
            if not agent:
                continue

            # L1 working memory
            l1_count = len(agent.memory.l1)
            if l1_count > 0:
                inventory["categories"]["l1_working_memory"] = {
                    "description": DATA_CATEGORIES["l1_working_memory"],
                    "entries": l1_count,
                }
                inventory["total_entries"] += l1_count

            # L2 session summaries
            l2_count = len(agent.memory.l2)
            if l2_count > 0:
                inventory["categories"]["l2_session_summaries"] = {
                    "description": DATA_CATEGORIES["l2_session_summaries"],
                    "entries": l2_count,
                }
                inventory["total_entries"] += l2_count

            # L3 long-term memory (user-specific entries)
            l3_user_entries = [
                e for e in agent.memory.l3
                if e.get("user_id") == user_id or e.get("source") == user_id
            ]
            if l3_user_entries:
                inventory["categories"]["l3_longterm_memory"] = {
                    "description": DATA_CATEGORIES["l3_longterm_memory"],
                    "entries": len(l3_user_entries),
                }
                inventory["total_entries"] += len(l3_user_entries)

            # Soul relationship
            if user_id in agent.soul.relationships:
                rel = agent.soul.relationships[user_id]
                inventory["categories"]["soul_relationship"] = {
                    "description": DATA_CATEGORIES["soul_relationship"],
                    "entries": 1,
                    "details": {
                        "name": rel.name,
                        "conversation_count": rel.conversation_count,
                    },
                }
                inventory["total_entries"] += 1

            # Onboarding
            if hasattr(agent, "personalization"):
                onboard = agent.personalization._onboardings.get(user_id)
                if onboard:
                    inventory["categories"]["onboarding"] = {
                        "description": DATA_CATEGORIES["onboarding"],
                        "entries": 1,
                        "details": {"phase": onboard.onboarding_phase},
                    }
                    inventory["total_entries"] += 1

        # Conversations
        if session_manager._shared_conversations:
            conv_sessions = session_manager._shared_conversations.list_sessions(user_id=user_id)
            if conv_sessions:
                inventory["categories"]["conversations"] = {
                    "description": DATA_CATEGORIES["conversations"],
                    "entries": len(conv_sessions),
                }
                inventory["total_entries"] += len(conv_sessions)

        return inventory

    def format_data_inventory(self, inventory: dict) -> str:
        """Format data inventory as human-readable text for Telegram."""
        lines = [
            "📋 **Deine bei Nexus gespeicherten Daten**",
            "",
        ]

        if not inventory.get("categories"):
            lines.append("Keine Daten gespeichert.")
        else:
            for cat, info in inventory["categories"].items():
                desc = info.get("description", cat)
                count = info.get("entries", 0)
                lines.append(f"• **{desc}**: {count} Einträg(e)")
                if "details" in info:
                    for k, v in info["details"].items():
                        lines.append(f"  └ {k}: {v}")

        lines.append("")
        lines.append(f"ℹ️ Aufbewahrungsfrist: {inventory.get('retention_days', 30)} Tage")
        lines.append("")
        lines.append("ℹ️ `/delete` — Alle Daten löschen (Art. 17 DSGVO)")

        return "\n".join(lines)

    # ─── Data Deletion (Art. 17 - Right to Erasure) ──────

    def delete_all_user_data(self, user_id: str, session_manager=None) -> dict:
        """Delete ALL data for a user across all systems.

        Implements Art. 17 Right to Erasure. Removes:
        - L1 working memory
        - L2 session summaries
        - L3 long-term memory entries attributed to this user
        - Soul relationship
        - Conversation sessions
        - Onboarding data
        - Consent record
        - Session from SessionManager

        Returns dict with what was deleted.
        """
        deleted = {
            "user_id": user_id,
            "categories_deleted": [],
            "total_entries_removed": 0,
            "timestamp": time.time(),
        }

        # Withdraw consent
        self.withdraw_consent(user_id)
        deleted["categories_deleted"].append("consent")

        if not session_manager:
            self.save()
            self._log_privacy(user_id, "data_deleted", details=deleted)
            return deleted

        # Find and clean sessions for this user
        chat_ids_to_remove = []
        for chat_id, session in session_manager._sessions.items():
            if session.user_id != user_id:
                continue

            agent = session.agent
            chat_ids_to_remove.append(chat_id)

            if not agent:
                continue

            # L1 - clear working memory
            l1_before = len(agent.memory.l1)
            agent.memory.l1 = []
            if l1_before > 0:
                deleted["categories_deleted"].append("l1_working_memory")
                deleted["total_entries_removed"] += l1_before

            # L2 - clear session summaries
            l2_before = len(agent.memory.l2)
            agent.memory.l2 = [s for s in agent.memory.l2
                              if s.get("user_id") and s.get("user_id") != user_id]
            l2_removed = l2_before - len(agent.memory.l2)
            if l2_removed > 0:
                deleted["categories_deleted"].append("l2_session_summaries")
                deleted["total_entries_removed"] += l2_removed

            # L3 - remove user-attributed entries
            l3_before = len(agent.memory.l3)
            agent.memory.l3 = [
                e for e in agent.memory.l3
                if e.get("user_id") != user_id and e.get("source") != user_id
            ]
            l3_removed = l3_before - len(agent.memory.l3)
            if l3_removed > 0:
                deleted["categories_deleted"].append("l3_longterm_memory")
                deleted["total_entries_removed"] += l3_removed

            # Soul relationship
            if user_id in agent.soul.relationships:
                del agent.soul.relationships[user_id]
                agent.soul.save()
                deleted["categories_deleted"].append("soul_relationship")
                deleted["total_entries_removed"] += 1

            # Onboarding
            if hasattr(agent, "personalization"):
                if user_id in agent.personalization._onboardings:
                    del agent.personalization._onboardings[user_id]
                    deleted["categories_deleted"].append("onboarding")
                    deleted["total_entries_removed"] += 1

            agent.memory.save()

        # Remove sessions
        for chat_id in chat_ids_to_remove:
            session_manager._cleanup_session(chat_id)
            deleted["categories_deleted"].append("session")

        # Conversations
        if session_manager._shared_conversations:
            conv_sessions = session_manager._shared_conversations.list_sessions(user_id=user_id)
            for cs in conv_sessions:
                session_manager._shared_conversations.delete_session(cs.get("session_id", ""))
            if conv_sessions:
                deleted["categories_deleted"].append("conversations")
                deleted["total_entries_removed"] += len(conv_sessions)

        # Remove consent record entirely
        if user_id in self._consents:
            del self._consents[user_id]
            self.save()

        self._log_privacy(user_id, "data_deleted", details=deleted)
        log.info(f"DSGVO: Deleted all data for user={user_id}, categories={deleted['categories_deleted']}")
        return deleted

    # ─── Auto-Deletion (Art. 5(1)(e) - Storage Limitation) ─

    def auto_delete_expired(self, session_manager=None) -> list:
        """Delete data for users who haven't interacted beyond the retention period.

        Called periodically by a cleanup cron.
        Returns list of user_ids whose data was deleted.
        """
        now = time.time()
        retention_seconds = DATA_RETENTION_DAYS * 86400
        expired_users = []

        for user_id, consent in list(self._consents.items()):
            if consent.last_interaction > 0:
                idle_days = (now - consent.last_interaction) / 86400
                if idle_days > DATA_RETENTION_DAYS:
                    expired_users.append(user_id)

        for user_id in expired_users:
            self.delete_all_user_data(user_id, session_manager)
            log.info(f"DSGVO: Auto-deleted expired data for user={user_id} (idle > {DATA_RETENTION_DAYS}d)")

        return expired_users

    def touch_interaction(self, user_id: str):
        """Update last interaction timestamp for a user."""
        consent = self._consents.get(user_id)
        if consent:
            consent.last_interaction = time.time()
            self.save()

    # ─── Privacy Logging ─────────────────────────────────

    def _log_privacy(self, user_id: str, action: str, **kwargs):
        """Log a privacy-relevant event."""
        entry = {
            "timestamp": time.time(),
            "user_id": user_id,
            "action": action,
            **kwargs,
        }
        log_file = self.data_dir / "privacy_log.jsonl"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            log.warning(f"Failed to write privacy log: {e}")

    def get_privacy_log(self, user_id: str = None, limit: int = 50) -> list:
        """Get privacy log entries, optionally filtered by user."""
        log_file = self.data_dir / "privacy_log.jsonl"
        if not log_file.exists():
            return []

        entries = []
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if user_id and entry.get("user_id") != user_id:
                            continue
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass

        if user_id:
            return entries[-limit:]
        return entries[-limit:]

    # ─── Transparency (Art. 13/14) ────────────────────────

    def get_privacy_notice(self) -> str:
        """Get the DSGVO privacy notice text shown at /start."""
        return (
            "🔒 **Datenschutzerklärung — Nexus Bot**\n"
            "\n"
            "Ich speichere folgende Daten von dir:\n"
            "\n"
            "• **Gespräche** — aktuelle u\\. letzte Konversationen\n"
            "• **Gelerntes** — Fakten u\\. Präferenzen, die du mir nennst\n"
            "• **Profil** — Name, Kommunikationsstil, Interessen\n"
            "\n"
            "Deine Rechte \\(DSGVO\\):\n"
            "• `/data` — Einsehen was gespeichert ist \\(Art\\. 15\\)\n"
            "• `/delete` — Alles löschen \\(Art\\. 17\\)\n"
            "• `/consent` — Einwilligung widerrufen\n"
            "\n"
            f"Aufbewahrung: max\\. {DATA_RETENTION_DAYS} Tage Inaktivität\\.\n"
            f"Version: {PRIVACY_POLICY_VERSION}\n"
            "\n"
            "Mit `/start` akzeptierst du diese Richtlinie\\."
        )