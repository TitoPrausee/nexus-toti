# NEXUS Core Framework — Toti System v6.0
# ═══════════════════════════════════════════════════════════
# Core
# ═══════════════════════════════════════════════════════════
from .llm_client import LLMClient, Message, LLMResponse
from .memory import MemorySystem
from .tools import ToolRegistry
from .state import StateManager
from .guards import NexusGuards
from .scheduler import SmartScheduler

# ═══════════════════════════════════════════════════════════
# Security & Safety (Phase 1)
# ═══════════════════════════════════════════════════════════
from .error_classifier import ErrorClassifier, FailoverReason, ClassifiedError
from .redact import redact_text, contains_secrets, redact_dict, redact_tool_output
from .file_safety import is_safe_write_path, validate_write_path, is_safe_delete_path

# ═══════════════════════════════════════════════════════════
# Context & Performance (Phase 2)
# ═══════════════════════════════════════════════════════════
from .context_references import preprocess_context_references
from .rate_limit_tracker import RateLimitTracker, RateLimitState
from .iteration_budget import IterationBudgetManager, ConversationBudget, BudgetLimit

# ═══════════════════════════════════════════════════════════
# UX & Feedback (Phase 3)
# ═══════════════════════════════════════════════════════════
from .think_scrubber import scrub_thinking, has_thinking_blocks, extract_thinking
from .title_generator import generate_title, generate_conversation_title, TitleConfig
from .message_sanitization import sanitize_message, sanitize_for_telegram, sanitize_for_conversation_history

# ═══════════════════════════════════════════════════════════
# Advanced (Phase 4)
# ═══════════════════════════════════════════════════════════
from .skill_bundles import SkillBundleManager, SkillBundle, BUNDLES
from .credential_pool import CredentialPool, Credential, KeyStatus
from .skill_hub import SkillHub, SkillMetadata, SkillResult

# ═══════════════════════════════════════════════════════════
# Activity Feedback — Makes NEXUS feel alive
# ═══════════════════════════════════════════════════════════
from .activity_feedback import ActivityFeedback, StreamingFeedback, FeedbackType, FeedbackMessage

# ═══════════════════════════════════════════════════════════
# Error Learning (existing)
# ═══════════════════════════════════════════════════════════
from .error_learning import ErrorLearningSystem, ErrorClass, ErrorRecord

__all__ = [
    # Core
    "LLMClient", "Message", "LLMResponse", "MemorySystem", "ToolRegistry",
    "StateManager", "NexusGuards", "SmartScheduler",
    # Security
    "ErrorClassifier", "FailoverReason", "ClassifiedError",
    "redact_text", "contains_secrets", "redact_dict", "redact_tool_output",
    "is_safe_write_path", "validate_write_path", "is_safe_delete_path",
    # Context & Performance
    "preprocess_context_references",
    "RateLimitTracker", "RateLimitState",
    "IterationBudgetManager", "ConversationBudget", "BudgetLimit",
    # UX & Feedback
    "scrub_thinking", "has_thinking_blocks", "extract_thinking",
    "generate_title", "generate_conversation_title", "TitleConfig",
    "sanitize_message", "sanitize_for_telegram", "sanitize_for_conversation_history",
    # Advanced
    "SkillBundleManager", "SkillBundle", "BUNDLES",
    "CredentialPool", "Credential", "KeyStatus",
    "SkillHub", "SkillMetadata", "SkillResult",
    # Activity Feedback
    "ActivityFeedback", "StreamingFeedback", "FeedbackType", "FeedbackMessage",
    # Error Learning
    "ErrorLearningSystem", "ErrorClass", "ErrorRecord",
]
