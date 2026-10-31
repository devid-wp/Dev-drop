import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import cli


class CliTests(unittest.TestCase):
    def invoke(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = cli.main(list(argv))
            except SystemExit as error:
                code = error.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_help_version_and_command_set(self):
        help_code, help_output, _ = self.invoke("--help")
        self.assertEqual(0, help_code)
        self.assertIn("devices", help_output)
        code, output, _ = self.invoke("version")
        self.assertEqual(0, code)
        self.assertIn("DevDrop 2.0.0", output)
        code, output, _ = self.invoke("version", "--json")
        self.assertEqual({"name": "DevDrop", "version": "2.0.0"}, json.loads(output))
        self.assertNotIn("send", cli.build_parser().format_help())

    def test_status_redacts_pairing_code_and_supports_json(self):
        payload = {"app": "DevDrop", "pairing_code": "123456789", "connected_devices": 2}
        with patch.object(cli, "_api", return_value=payload.copy()):
            code, output, _ = self.invoke("status", "--json")
        self.assertEqual(0, code)
        self.assertNotIn("123456789", output)
        self.assertEqual(2, json.loads(output)["connected_devices"])

    def test_pair_explicitly_displays_code_and_transfers_decide(self):
        with patch.object(cli, "_api", return_value={"code": "987654321", "expires_in": 20}) as api:
            code, output, _ = self.invoke("pair")
        self.assertEqual(0, code)
        self.assertIn("987 654 321", output)
        api.assert_called_once_with("GET", "/api/pairing-code")
        with patch.object(cli, "_api", return_value={"id": "request-id", "status": "approved"}) as api:
            code, output, _ = self.invoke("transfers", "--approve", "request-id")
        self.assertEqual(0, code)
        api.assert_called_once_with("POST", "/api/transfer-requests/request-id/approve", {})
        self.assertIn("approved", output)

    def test_pending_transfers_history_and_config_json(self):
        with patch.object(cli, "_api", return_value={"requests": [{"id": "r1", "files": [], "size": 0}]}):
            code, output, _ = self.invoke("transfers", "--json")
        self.assertEqual("r1", json.loads(output)["requests"][0]["id"])
        with patch.object(cli, "_api", return_value={"transfers": [{"filename": "a"}, {"filename": "b"}]}):
            code, output, _ = self.invoke("history", "--json")
        self.assertEqual(["b", "a"], [row["filename"] for row in json.loads(output)["transfers"]])
        with tempfile.TemporaryDirectory() as temp:
            config_file = Path(temp) / "config.json"
            with patch.object(cli, "config_path", return_value=config_file):
                with patch("app.config.config_path", return_value=config_file):
                    code, _, _ = self.invoke("config", "--port", "9123", "--session-root", temp)
                    self.assertEqual(0, code)
                    saved = json.loads(config_file.read_text())
        self.assertEqual(9123, saved["port"])
        self.assertEqual(temp, saved["session_root"])

    def test_api_failures_use_unavailable_exit_and_do_not_echo_secrets(self):
        with patch.object(cli, "_api", side_effect=cli.CliError("Could not reach the local HTTPS server.", cli.EXIT_UNAVAILABLE)):
            code, _, error = self.invoke("status")
        self.assertEqual(cli.EXIT_UNAVAILABLE, code)
        self.assertIn("HTTPS server", error)
        self.assertNotIn("Bearer", error)
        with patch.object(cli, "_api", side_effect=cli.CliError("offline", cli.EXIT_UNAVAILABLE)):
            code, _, error = self.invoke("status", "--json")
        self.assertEqual(3, code)
        self.assertEqual(3, json.loads(error)["exit_code"])

    def test_invalid_port_and_conflicting_decisions_fail(self):
        code, _, error = self.invoke("config", "--port", "99999")
        self.assertEqual(2, code)
        self.assertIn("1 to 65535", error)
        code, _, error = self.invoke("transfers", "--approve", "a", "--reject", "b")
        self.assertEqual(2, code)
        self.assertIn("not allowed", error)


if __name__ == "__main__":
    unittest.main()
