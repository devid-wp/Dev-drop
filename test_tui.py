import asyncio
import threading
import time
import unittest
from pathlib import Path

from app.config import DevDropConfig
from app.tui import ConfirmDialog, DevDropTui, HelpDialog, TuiSnapshot
from textual.widgets import DataTable, Static


class FakeServices:
    def __init__(self, snapshot=None):
        self.data = snapshot or TuiSnapshot(config=DevDropConfig(Path("/tmp/DevDrop"), 8765))
        self.decisions = []

    def snapshot(self, cancelled=lambda: False):
        return self.data

    def decide(self, identity, approve):
        self.decisions.append((identity, approve))
        return {"id": identity, "status": "approved" if approve else "rejected"}

    def update_config(self, port, session_root):
        return DevDropConfig(Path(session_root), port)


def pending_request():
    return {
        "id": "request_1234567890",
        "status": "pending",
        "sender": "Phone A",
        "description": "Selected file",
        "size": 2048,
        "files": [{"name": "report.pdf", "size": 2048, "sha256": "a" * 64}],
    }


class TuiPilotTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_and_navigation(self):
        services = FakeServices(TuiSnapshot(config=DevDropConfig(Path("/tmp/DevDrop"), 8765)))
        app = DevDropTui(services)
        async with app.run_test(size=(100, 36)) as pilot:
            await pilot.pause(0.1)
            self.assertEqual("Dashboard", str(app.query_one("#screen-title", Static).renderable))
            await pilot.press("t")
            self.assertEqual("transfers", app.current_page)
            await pilot.press("h")
            self.assertEqual("history", app.current_page)
            await pilot.press("d")
            self.assertEqual("dashboard", app.current_page)
            await pilot.press("?")
            self.assertIsInstance(app.screen, HelpDialog)
            await pilot.press("escape")
            await pilot.press("q")
            await pilot.pause(0.05)

    async def test_empty_states_are_real_and_clear(self):
        app = DevDropTui(FakeServices())
        async with app.run_test(size=(100, 36)) as pilot:
            await pilot.pause(0.1)
            self.assertEqual(0, app.query_one("#devices-table", DataTable).row_count)
            self.assertIn("No other DevDrop devices", str(app.query_one("#devices-empty", Static).renderable))
            self.assertIn("No transfer activity", str(app.query_one("#dashboard-events", Static).renderable))
            await pilot.click("#nav-history")
            self.assertEqual(0, app.query_one("#history-table", DataTable).row_count)

    async def test_layout_adapts_to_a_narrow_terminal(self):
        app = DevDropTui(FakeServices())
        async with app.run_test(size=(50, 18)) as pilot:
            await pilot.pause(0.1)
            self.assertIn("tiny", app.classes)
            await pilot.click("#nav-devices")
            self.assertEqual("devices", app.current_page)

    async def test_outgoing_offer_progress_uses_backend_byte_counts(self):
        offer = {"id": "offer-1", "filename": "movie.mp4", "recipient_id": "a" * 64,
                 "status": "streaming", "sent_bytes": 512, "size": 2048}
        app = DevDropTui(FakeServices(TuiSnapshot(outgoing_offers=[offer], config=DevDropConfig(Path("/tmp/DevDrop"), 8765))))
        async with app.run_test(size=(110, 38)) as pilot:
            await pilot.pause(0.1)
            self.assertIn("1 PC → phone", str(app.query_one("#card-active", Static).renderable))
            await pilot.click("#nav-transfers")
            table = app.query_one("#outgoing-table", DataTable)
            self.assertEqual(1, table.row_count)
            self.assertIn("512 B / 2.0 KB", str(table.get_cell_at((0, 3))))

    async def _run_decision(self, approve):
        request = pending_request()
        services = FakeServices(TuiSnapshot(requests=[request], config=DevDropConfig(Path("/tmp/DevDrop"), 8765)))
        app = DevDropTui(services)
        async with app.run_test(size=(110, 38)) as pilot:
            await pilot.pause(0.1)
            await pilot.click("#nav-transfers")
            table = app.query_one("#transfer-table", DataTable)
            table.move_cursor(row=0, column=0)
            table.action_select_cursor()
            await pilot.pause(0.05)
            self.assertEqual(request["id"], app.selected_request["id"])
            await pilot.click("#approve-transfer" if approve else "#reject-transfer")
            self.assertIsInstance(app.screen, ConfirmDialog)
            dialog_text = " ".join(str(widget.renderable) for widget in app.screen.query(Static))
            self.assertIn("report.pdf", dialog_text)
            self.assertIn("Phone A", dialog_text)
            await pilot.click("#dialog-confirm")
            await pilot.pause(0.15)
            self.assertEqual([(request["id"], approve)], services.decisions)

    async def test_approval_requires_explicit_dialog_confirmation(self):
        await self._run_decision(True)

    async def test_rejection_uses_explicit_dialog_confirmation(self):
        await self._run_decision(False)

    async def test_connection_errors_are_shown_without_fake_online_state(self):
        services = FakeServices(TuiSnapshot(errors={"server": "Server offline"}, config=DevDropConfig(Path("/tmp/DevDrop"), 8765)))
        app = DevDropTui(services)
        async with app.run_test(size=(100, 36)) as pilot:
            await pilot.pause(0.1)
            self.assertEqual("Unavailable", str(app.query_one("#card-server", Static).renderable))
            self.assertIn("Server offline", str(app.query_one("#status-line", Static).renderable))


class BackgroundTaskTests(unittest.TestCase):
    def test_background_task_observes_cancellation_and_is_joined_on_shutdown(self):
        entered, cancelled = threading.Event(), threading.Event()
        app = DevDropTui(FakeServices())

        def blocking(cancel_event):
            entered.set()
            while not cancel_event.wait(0.01):
                pass
            cancelled.set()

        app._start_background("test", blocking)
        self.assertTrue(entered.wait(1))
        app._stop_background_tasks()
        self.assertTrue(cancelled.is_set())
        self.assertFalse(app._tasks)


if __name__ == "__main__":
    unittest.main()
