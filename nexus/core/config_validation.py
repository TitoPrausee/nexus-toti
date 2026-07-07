#!/usr/bin/env python3
"""
NEXUS v7 — Config Schema Validation

Validates config.yaml at startup with clear error messages.
Checks required sections, types, value ranges, and env var availability.
"""

import os
import sys
from typing import Any


# ── Schema Definition ──────────────────────────────────────────────
# Each key: { required: bool, type: type, default: val, range: (min, max), keys: {...} }

CONFIG_SCHEMA = {
    "nexus": {
        "required": True,
        "type": dict,
        "keys": {
            "name": {"required": True, "type": str, "default": "Toti"},
            "version": {"required": True, "type": str, "default": "7.0"},
            "language": {"required": False, "type": str, "default": "de"},
        },
    },
    "llm": {
        "required": True,
        "type": dict,
        "keys": {
            "base_url": {"required": True, "type": str, "default": "http://localhost:11434"},
            "local_url": {"required": False, "type": str, "default": "http://localhost:11434"},
            "api_key_env": {"required": True, "type": str, "default": "OLLAMA_API_KEY"},
            "mode": {"required": True, "type": str, "choices": ["cloud", "local", "hybrid"]},
            "default_model": {"required": True, "type": str},
            "default_temperature": {"required": False, "type": (int, float), "default": 0.7, "range": (0.0, 2.0)},
            "default_max_tokens": {"required": False, "type": int, "default": 4096, "range": (1, 100000)},
            "models": {"required": True, "type": dict},
            "fallback": {"required": True, "type": list},
            "max_retries": {"required": False, "type": int, "default": 2, "range": (0, 10)},
            "timeout": {"required": False, "type": int, "default": 120, "range": (5, 600)},
            "stream": {"required": False, "type": bool, "default": True},
        },
    },
    "soul": {
        "required": True,
        "type": dict,
        "keys": {
            "enabled": {"required": False, "type": bool, "default": True},
            "file": {"required": False, "type": str, "default": "soul/soul.yaml"},
            "auto_save": {"required": False, "type": bool, "default": True},
        },
    },
    "memory": {
        "required": True,
        "type": dict,
        "keys": {
            "l1_max_tokens": {"required": False, "type": int, "default": 8000, "range": (1000, 100000)},
            "l2_max_entries": {"required": False, "type": int, "default": 50, "range": (5, 500)},
            "l2_max_age_hours": {"required": False, "type": int, "default": 48, "range": (1, 720)},
            "l3_max_entries": {"required": False, "type": int, "default": 200, "range": (10, 5000)},
            "l4_permanent": {"required": False, "type": bool, "default": True},
            "auto_compress": {"required": False, "type": bool, "default": True},
            "compress_threshold": {"required": False, "type": (int, float), "default": 0.7, "range": (0.1, 0.99)},
        },
    },
    "tools": {
        "required": True,
        "type": dict,
        "keys": {
            "enabled": {"required": True, "type": list},
            "dangerous_requires_confirmation": {"required": False, "type": list, "default": []},
        },
    },
    "telegram": {
        "required": False,
        "type": dict,
        "keys": {
            "token_env": {"required": False, "type": str, "default": "NEXUS_TG_TOKEN"},
            "authorized_users_env": {"required": False, "type": str, "default": "NEXUS_TG_USERS"},
            "streaming": {"required": False, "type": bool, "default": True},
            "typing_indicator": {"required": False, "type": bool, "default": True},
            "max_message_length": {"required": False, "type": int, "default": 4096, "range": (100, 8192)},
            "parse_mode": {"required": False, "type": str, "default": "MarkdownV2"},
        },
    },
    "performance": {
        "required": False,
        "type": dict,
        "keys": {
            "max_tokens_per_turn": {"required": False, "type": int, "default": 8000, "range": (1000, 100000)},
            "max_tokens_per_conversation": {"required": False, "type": int, "default": 100000, "range": (10000, 1000000)},
            "max_tool_calls_per_turn": {"required": False, "type": int, "default": 15, "range": (1, 50)},
        },
    },
}


class ValidationResult:
    """Holds validation results with errors and warnings."""

    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.applied_defaults: list[str] = []

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def __repr__(self):
        status = "✓ VALID" if self.ok else "✗ INVALID"
        return f"ValidationResult({status}, {len(self.errors)} errors, {len(self.warnings)} warnings, {len(self.applied_defaults)} defaults)"


def _check_type(value: Any, expected_type) -> bool:
    """Check if value matches expected type. Supports tuple of types."""
    if isinstance(expected_type, tuple):
        return isinstance(value, expected_type)
    return isinstance(value, expected_type)


def validate_config(config: dict, strict: bool = False) -> ValidationResult:
    """
    Validate config.yaml against the schema.

    Args:
        config: The parsed config dict from YAML
        strict: If True, treat warnings as errors

    Returns:
        ValidationResult with errors, warnings, and applied defaults
    """
    result = ValidationResult()

    if not isinstance(config, dict):
        result.errors.append(f"Config must be a YAML dict, got {type(config).__name__}")
        return result

    # Check required top-level sections
    for section_key, section_spec in CONFIG_SCHEMA.items():
        if section_key not in config:
            if section_spec.get("required", False):
                result.errors.append(f"Missing required config section: '{section_key}'")
            else:
                result.warnings.append(f"Optional config section missing: '{section_key}' — defaults will be used")
            continue

        section = config[section_key]
        if not _check_type(section, section_spec["type"]):
            result.errors.append(
                f"Config section '{section_key}' must be {section_spec['type'].__name__}, "
                f"got {type(section).__name__}"
            )
            continue

        # Validate keys within section
        keys_spec = section_spec.get("keys", {})
        for key, key_spec in keys_spec.items():
            if key not in section:
                if key_spec.get("required", False):
                    if "default" in key_spec:
                        # Apply default
                        section[key] = key_spec["default"]
                        result.applied_defaults.append(f"{section_key}.{key} = {key_spec['default']!r}")
                    else:
                        result.errors.append(f"Missing required key: '{section_key}.{key}'")
                else:
                    if "default" in key_spec:
                        section[key] = key_spec["default"]
                        result.applied_defaults.append(f"{section_key}.{key} = {key_spec['default']!r}")
                continue

            val = section[key]

            # Type check
            if not _check_type(val, key_spec["type"]):
                result.errors.append(
                    f"'{section_key}.{key}' must be {key_spec['type'].__name__}, "
                    f"got {type(val).__name__}: {val!r}"
                )
                continue

            # Choices check
            if "choices" in key_spec and val not in key_spec["choices"]:
                result.errors.append(
                    f"'{section_key}.{key}' must be one of {key_spec['choices']}, got {val!r}"
                )

            # Range check (numeric)
            if "range" in key_spec:
                min_val, max_val = key_spec["range"]
                if isinstance(val, (int, float)):
                    if val < min_val or val > max_val:
                        result.errors.append(
                            f"'{section_key}.{key}' must be between {min_val} and {max_val}, got {val}"
                        )

    # Check env var availability
    env_checks = {
        "OLLAMA_API_KEY": ("Required for cloud LLM mode", "recommended"),
        "NEXUS_TG_TOKEN": ("Required for Telegram bot mode", "recommended"),
        "NEXUS_TG_USERS": ("Required for Telegram auth", "optional"),
    }
    for var, (reason, severity) in env_checks.items():
        if not os.environ.get(var):
            if severity == "recommended":
                result.warnings.append(f"Env var not set: {var} — {reason}")
            # optional ones don't even warrant a warning

    if strict:
        result.errors.extend(result.warnings)
        result.warnings.clear()

    return result


def print_validation_report(result: ValidationResult):
    """Print a human-readable validation report."""
    if result.ok:
        print("✓ Config validation passed")
    else:
        print("✗ Config validation FAILED")

    for err in result.errors:
        print(f"  ERROR: {err}")

    for warn in result.warnings:
        print(f"  WARN:  {warn}")

    for default in result.applied_defaults:
        print(f"  DEFAULT: {default}")

    return result.ok


if __name__ == "__main__":
    import yaml
    import sys

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"✗ Cannot load config: {e}")
        sys.exit(1)

    result = validate_config(config)
    ok = print_validation_report(result)
    sys.exit(0 if ok else 1)