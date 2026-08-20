#!/usr/bin/env python3
"""GUI smoke tests (headless/offscreen).

Verifies the main window and settings dialog construct without exceptions and
that key widgets are present. Networking is stubbed so tests never bind a port.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


class GUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)
        cls.app.setApplicationName("DevDropTest")
        cls._created: list = []

        # Prevent the window from starting a real backend or polling the network.
        cls.patchers = [
            patch("devdrop_gui.BackendManager.ensure_backend"),
            patch("devdrop_gui.MainWindow.refresh_status"),
            patch("devdrop_gui.BackendManager._is_devdrop_available", return_value=True),
        ]
        for patcher in cls.patchers:
            patcher.start()
        cls.patchers_active = True

    @classmethod
    def tearDownClass(cls) -> None:
        if getattr(cls, "patchers_active", False):
            for patcher in cls.patchers:
                patcher.stop()
        # Deterministically release the Qt widgets instead of leaving them to
        # Python's garbage collector. Otherwise the wrapped C++ objects are
        # freed at an arbitrary later point (e.g. while another test module's
        # uvicorn thread is running) and can crash the whole test process.
        for widget in cls._created:
            widget.close()
            widget.deleteLater()
        cls.app.processEvents()
        cls._created.clear()
        import gc

        gc.collect()

    def _track(self, widget) -> None:
        self.__class__._created.append(widget)
        return widget

    def test_main_window_constructs_and_has_key_widgets(self) -> None:
        import devdrop_gui

        window = self._track(devdrop_gui.MainWindow())
        self.assertEqual(window.windowTitle(), "DevDrop")
        for widget in (
            window.address_value,
            window.code_value,
            window.status_value,
            window.session_value,
            window.files_value,
            window.size_value,
            window.qr_code_value,
        ):
            self.assertIsNotNone(widget)
        self.assertIsNotNone(window.history_list)
        self.assertIsNotNone(window.drop_area)

    def test_settings_dialog_constructs(self) -> None:
        import devdrop_gui
        from app.config import DevDropConfig

        dialog = self._track(
            devdrop_gui.SettingsDialog(
                DevDropConfig(session_root=Path("C:/DevDrop"), port=8765)
            )
        )
        self.assertEqual(dialog.port_input.value(), 8765)
        self.assertEqual(dialog.root_input.text().replace("\\", "/"), "C:/DevDrop")

    def test_format_bytes(self) -> None:
        import devdrop_gui

        self.assertEqual(devdrop_gui.format_bytes(0), "0 B")
        self.assertEqual(devdrop_gui.format_bytes(1024), "1.0 KB")
        self.assertEqual(devdrop_gui.format_bytes(5 * 1024 * 1024), "5.0 MB")

    def test_format_code(self) -> None:
        import devdrop_gui

        self.assertEqual(devdrop_gui.format_code("123456789"), "123 456 789")


if __name__ == "__main__":
    unittest.main()