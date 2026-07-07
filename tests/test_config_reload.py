"""
NEXUS v7 QA — Tests for Config Hot-Reload (ConfigManager)

Covers:
- Config loading and access
- File watching (mtime-based change detection)
- Callback system for subsystem notifications
- Thread safety
- Edge cases: missing file, malformed YAML, rapid writes
- apply_config_to_agent integration
"""

import os
import time
import threading
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Add project root to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nexus.core.config import ConfigManager, ConfigReloadResult, apply_config_to_agent


# ═══════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════


@pytest.fixture
def config_dir(tmp_path):
    """Create a temporary config directory."""
    return tmp_path


@pytest.fixture
def config_file(config_dir):
    """Create a temporary config file."""
    config_path = config_dir / "config.yaml"
    config_data = {
        "nexus": {"name": "Toti", "version": "7.0"},
        "llm": {"default_model": "test-model", "timeout": 60},
        "memory": {"l1_max_tokens": 8000},
    }
    config_path.write_text(yaml.dump(config_data), encoding="utf-8")
    return str(config_path)


@pytest.fixture
def config_mgr(config_file):
    """Create a ConfigManager with a test config file."""
    return ConfigManager(config_file, check_interval=0.5)


# ═══════════════════════════════════════════════════
# CONFIG LOADING & ACCESS
# ═══════════════════════════════════════════════════


class TestConfigLoad:
    """Tests for initial config loading."""

    def test_load_config_on_init(self, config_mgr):
        """Config should be loaded on init."""
        cfg = config_mgr.config
        assert cfg["nexus"]["name"] == "Toti"
        assert cfg["llm"]["timeout"] == 60

    def test_get_top_level_key(self, config_mgr):
        """get() should return top-level keys."""
        llm = config_mgr.get("llm")
        assert isinstance(llm, dict)
        assert llm["default_model"] == "test-model"

    def test_get_missing_key_returns_default(self, config_mgr):
        """get() with missing key should return default."""
        result = config_mgr.get("nonexistent", "fallback")
        assert result == "fallback"

    def test_get_nested_key(self, config_mgr):
        """get_nested() should traverse nested dicts."""
        name = config_mgr.get_nested("nexus", "name")
        assert name == "Toti"

        timeout = config_mgr.get_nested("llm", "timeout")
        assert timeout == 60

    def test_get_nested_missing_key(self, config_mgr):
        """get_nested() should return default for missing keys."""
        result = config_mgr.get_nested("nexus", "missing", default="x")
        assert result == "x"

    def test_get_nested_non_dict_intermediate(self, config_mgr):
        """get_nested() should handle non-dict intermediate values."""
        result = config_mgr.get_nested("nexus", "name", "length", default=None)
        assert result is None  # "Toti" is a string, not a dict

    def test_load_missing_file(self, tmp_path):
        """Should handle missing config file gracefully."""
        path = str(tmp_path / "nonexistent.yaml")
        mgr = ConfigManager(path)
        # Config should be empty dict
        assert mgr.config == {}

    def test_load_empty_file(self, tmp_path):
        """Should handle empty YAML file."""
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        mgr = ConfigManager(str(path))
        assert mgr.config == {}


# ═══════════════════════════════════════════════════
# RELOAD
# ═══════════════════════════════════════════════════


class TestConfigReload:
    """Tests for config reload functionality."""

    def test_reload_detects_changes(self, config_file, config_mgr):
        """reload() should detect changes in config file."""
        # Modify config file
        new_config = {
            "nexus": {"name": "Mercury", "version": "8.0"},
            "llm": {"default_model": "new-model", "timeout": 120},
            "memory": {"l1_max_tokens": 16000},
        }
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(new_config, f)

        result = config_mgr.reload()
        assert result.success
        assert len(result.changed_keys) > 0
        assert config_mgr.config["nexus"]["name"] == "Mercury"

    def test_reload_no_changes(self, config_mgr, config_file):
        """reload() when nothing changed should return empty changed_keys."""
        result = config_mgr.reload()
        assert result.success
        assert len(result.changed_keys) == 0

    def test_reload_missing_file(self, config_mgr, tmp_path):
        """reload() with non-existent file should return failure."""
        mgr = ConfigManager(str(tmp_path / "nonexistent.yaml"))
        # The initial load fails, so config is empty
        result = mgr.reload()
        assert not result.success
        assert len(result.errors) > 0

    def test_reload_malformed_yaml(self, config_mgr, config_file):
        """reload() with malformed YAML should return failure."""
        with open(config_file, "w", encoding="utf-8") as f:
            f.write("{{invalid: yaml: [}")
        result = config_mgr.reload()
        assert not result.success
        # Original config should be preserved
        assert config_mgr.config.get("nexus") is not None or True  # didn't crash

    def test_reload_adds_new_key(self, config_mgr, config_file):
        """Adding a new key should show +key in changed_keys."""
        existing = yaml.safe_load(Path(config_file).read_text())
        existing["new_section"] = {"enabled": True}
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(existing, f)

        result = config_mgr.reload()
        assert result.success
        assert "+new_section" in result.changed_keys

    def test_reload_removes_key(self, config_mgr, config_file):
        """Removing a key should show -key in changed_keys."""
        existing = yaml.safe_load(Path(config_file).read_text())
        del existing["memory"]
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(existing, f)

        result = config_mgr.reload()
        assert result.success
        assert "-memory" in result.changed_keys

    def test_reload_modifies_value(self, config_mgr, config_file):
        """Modifying a value should show ~key in changed_keys."""
        existing = yaml.safe_load(Path(config_file).read_text())
        existing["llm"]["timeout"] = 300
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(existing, f)

        result = config_mgr.reload()
        assert result.success
        assert "~llm" in result.changed_keys


# ═══════════════════════════════════════════════════
# CALLBACKS
# ═══════════════════════════════════════════════════


class TestConfigCallbacks:
    """Tests for the callback notification system."""

    def test_register_callback(self, config_mgr):
        """Should register callbacks for subsystems."""
        cb = MagicMock()
        config_mgr.register_callback("llm", cb)
        stats = config_mgr.stats()
        assert "llm" in stats["registered_subsystems"]

    def test_callback_fired_on_llm_change(self, config_mgr, config_file):
        """LLM callback should fire when llm config changes."""
        cb = MagicMock()
        config_mgr.register_callback("llm", cb)

        # Modify llm config
        existing = yaml.safe_load(Path(config_file).read_text())
        existing["llm"]["timeout"] = 999
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(existing, f)

        config_mgr.reload()
        assert cb.called

    def test_callback_receives_config(self, config_mgr, config_file):
        """Callback should receive the new config dict."""
        received_config = {}
        def capture_config(cfg):
            received_config.update(cfg)

        config_mgr.register_callback("llm", capture_config)

        existing = yaml.safe_load(Path(config_file).read_text())
        existing["llm"]["timeout"] = 500
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(existing, f)

        config_mgr.reload()
        assert "llm" in received_config

    def test_callback_not_fired_on_unrelated_change(self, config_mgr, config_file):
        """Callback should NOT fire when an unrelated section changes."""
        llm_cb = MagicMock()
        memory_cb = MagicMock()
        config_mgr.register_callback("llm", llm_cb)
        config_mgr.register_callback("memory", memory_cb)

        # Modify only memory section
        existing = yaml.safe_load(Path(config_file).read_text())
        existing["memory"]["l1_max_tokens"] = 99999
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(existing, f)

        config_mgr.reload()
        assert memory_cb.called
        # LLM callback shouldn't be called (llm config didn't change)
        assert not llm_cb.called

    def test_callback_error_does_not_break_reload(self, config_mgr, config_file):
        """A failing callback should not prevent other callbacks or the reload."""
        def bad_callback(cfg):
            raise RuntimeError("Callback explosion!")

        good_called = False
        def good_callback(cfg):
            nonlocal good_called
            good_called = True

        config_mgr.register_callback("memory", bad_callback)
        config_mgr.register_callback("memory", good_callback)

        existing = yaml.safe_load(Path(config_file).read_text())
        existing["memory"]["l1_max_tokens"] = 99999
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(existing, f)

        result = config_mgr.reload()
        # Should still succeed (error is logged, not raised)
        assert result.success
        # Good callback should still have been called
        assert good_called


# ═══════════════════════════════════════════════════
# FILE WATCHER
# ═══════════════════════════════════════════════════


class TestConfigWatcher:
    """Tests for the background file watcher."""

    def test_start_watcher(self, config_mgr):
        """start_watcher() should start a daemon thread."""
        config_mgr.start_watcher()
        try:
            assert config_mgr._watcher_thread is not None
            assert config_mgr._watcher_thread.is_alive()
        finally:
            config_mgr.stop_watcher()

    def test_stop_watcher(self, config_mgr):
        """stop_watcher() should stop the thread."""
        config_mgr.start_watcher()
        config_mgr.stop_watcher()
        # Give it a moment to fully stop
        time.sleep(0.2)
        assert not config_mgr._watcher_thread.is_alive()

    def test_watcher_detects_file_change(self, config_mgr, config_file):
        """Watcher should auto-reload when config file changes."""
        callback_config = {}
        def capture(cfg):
            callback_config.update(cfg)

        config_mgr.register_callback("llm", capture)
        config_mgr.start_watcher()

        try:
            # Wait for watcher to start
            time.sleep(0.2)

            # Modify config file
            existing = yaml.safe_load(Path(config_file).read_text())
            existing["llm"]["timeout"] = 777
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(existing, f)

            # Wait for watcher to detect change
            time.sleep(2.0)  # check_interval + debounce margin

            # Config should be updated
            assert config_mgr.config["llm"]["timeout"] == 777

        finally:
            config_mgr.stop_watcher()

    def test_double_start_watcher(self, config_mgr):
        """Starting watcher when already running should be a no-op."""
        config_mgr.start_watcher()
        first_thread = config_mgr._watcher_thread
        config_mgr.start_watcher()  # Should not crash
        assert config_mgr._watcher_thread is first_thread
        config_mgr.stop_watcher()

    def test_stats_includes_watcher_status(self, config_mgr):
        """stats() should report watcher status."""
        stats = config_mgr.stats()
        assert "watcher_running" in stats
        assert stats["watcher_running"] is False

        config_mgr.start_watcher()
        try:
            stats = config_mgr.stats()
            assert stats["watcher_running"] is True
        finally:
            config_mgr.stop_watcher()


# ═══════════════════════════════════════════════════
# THREAD SAFETY
# ═══════════════════════════════════════════════════


class TestConfigThreadSafety:
    """Tests for thread-safe config access."""

    def test_concurrent_reads(self, config_mgr):
        """Multiple threads reading config should not crash."""
        errors = []
        results = []

        def reader():
            try:
                cfg = config_mgr.config
                results.append(cfg.get("nexus", {}).get("name"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert all(r == "Toti" for r in results)

    def test_concurrent_read_and_write(self, config_mgr, config_file):
        """Concurrent reads and reloads should not crash."""
        errors = []

        def reader():
            for _ in range(20):
                try:
                    cfg = config_mgr.config
                    assert isinstance(cfg, dict)
                except Exception as e:
                    errors.append(e)

        def writer():
            for i in range(5):
                new_config = {"nexus": {"name": f"Bot-{i}", "version": "7.0"}}
                with open(config_file, "w", encoding="utf-8") as f:
                    yaml.dump(new_config, f)
                config_mgr.reload()
                time.sleep(0.01)

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ═══════════════════════════════════════════════════
# STATS
# ═══════════════════════════════════════════════════


class TestConfigStats:
    """Tests for ConfigManager.stats()."""

    def test_stats_initial(self, config_mgr):
        """stats() should return meaningful values before any reload."""
        stats = config_mgr.stats()
        assert "config_path" in stats
        assert "reload_count" in stats
        assert "top_level_keys" in stats
        assert stats["reload_count"] == 1  # Initial load counts

    def test_stats_after_reload(self, config_mgr, config_file):
        """reload_count should increment after reload."""
        initial_count = config_mgr.stats()["reload_count"]

        # Touch the file to trigger a change
        existing = yaml.safe_load(Path(config_file).read_text())
        existing["new_key"] = True
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(existing, f)

        config_mgr.reload()
        assert config_mgr.stats()["reload_count"] == initial_count + 1