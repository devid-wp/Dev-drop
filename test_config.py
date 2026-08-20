#!/usr/bin/env python3
"""Tests for DevDrop settings persistence (app/config.py)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import DevDropConfig, load_config, save_config, _coerce_port


class ConfigPersistenceTests(unittest.TestCase):
    def test_save_and_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.json"
            config = DevDropConfig(session_root=Path("C:/Data/DevDrop"), port=9123)
            with patch("app.config.config_path", return_value=config_path):
                save_config(config)
                loaded = load_config()

            self.assertEqual(loaded.session_root, Path("C:/Data/DevDrop"))
            self.assertEqual(loaded.port, 9123)

    def test_missing_config_uses_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.json"
            with patch("app.config.config_path", return_value=config_path):
                loaded = load_config()
            self.assertEqual(loaded.session_root, Path.home() / "DevDrop")
            self.assertEqual(loaded.port, 8765)

    def test_corrupt_config_falls_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.json"
            config_path.write_text("{ not valid json", encoding="utf-8")
            with patch("app.config.config_path", return_value=config_path):
                loaded = load_config()
            self.assertEqual(loaded.session_root, Path.home() / "DevDrop")
            self.assertEqual(loaded.port, 8765)

    def test_port_validation(self) -> None:
        self.assertEqual(_coerce_port(8765, 0), 8765)
        self.assertEqual(_coerce_port(0, 8765), 8765)
        self.assertEqual(_coerce_port(70000, 8765), 8765)
        self.assertEqual(_coerce_port("not-a-port", 8765), 8765)


if __name__ == "__main__":
    unittest.main()