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

    def test_pending_request_buttons_use_selected_id(self) -> None:
        import devdrop_gui
        from PySide6.QtCore import Qt
        window = self._track(devdrop_gui.MainWindow())
        window.pending_list.addItem("file | Claimed sender | 5 B")
        window.pending_list.item(0).setData(Qt.ItemDataRole.UserRole, "request-id")
        window.pending_list.setCurrentRow(0)
        with patch("devdrop_gui.background") as worker:
            window.approve_button.click()
            work = worker.call_args.args[1]
            with patch.object(window.client, "transfer_request") as client:
                work()
                client.assert_called_once_with("POST", "/api/transfer-requests/request-id/approve")
            window.reject_button.click()
            work = worker.call_args.args[1]
            with patch.object(window.client, "transfer_request") as client:
                work()
                client.assert_called_once_with("POST", "/api/transfer-requests/request-id/reject")

    def test_outgoing_file_offer_and_cancel_use_background_work(self) -> None:
        import devdrop_gui
        from PySide6.QtCore import Qt
        window = self._track(devdrop_gui.MainWindow())
        window.recipient_box.addItem("Browser session", "recipient-id")
        with patch("devdrop_gui.QFileDialog.getOpenFileName", return_value=("/tmp/chosen.txt", "")), patch(
            "devdrop_gui.background"
        ) as worker:
            window.offer_button.click()
            self.assertTrue(window._creating_offer)
            self.assertFalse(window.offer_button.isEnabled())
            work = worker.call_args.args[1]
            with patch.object(window.client, "transfer_request") as client:
                work()
                client.assert_called_once_with("POST", "/api/outgoing-offers",
                    {"path": "/tmp/chosen.txt", "recipient_id": "recipient-id"}, timeout=120)
            window.outgoing_list.addItem("chosen.txt | pending")
            window.outgoing_list.item(0).setData(Qt.ItemDataRole.UserRole, "offer-id")
            window.outgoing_list.setCurrentRow(0)
            window.cancel_offer_button.click()
            with patch.object(window.client, "transfer_request") as client:
                worker.call_args.args[1]()
                client.assert_called_once_with("POST", "/api/outgoing-offers/offer-id/cancel")

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