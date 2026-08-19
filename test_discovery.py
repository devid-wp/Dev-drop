import unittest

from app.discovery import DiscoveryService, make_query, parse_message


class DiscoveryTests(unittest.TestCase):
    def test_query_round_trip(self) -> None:
        message = parse_message(make_query("test-nonce"))

        self.assertEqual(
            message,
            {
                "magic": "DEVDROP_DISCOVERY_V1",
                "action": "discover",
                "nonce": "test-nonce",
            },
        )

    def test_responder_returns_local_server(self) -> None:
        service = DiscoveryService(8765, "DevDrop-Test")
        service.start()
        try:
            servers = service.discover()
        finally:
            service.stop()

        self.assertTrue(
            any(
                server["name"] == "DevDrop-Test" and server["port"] == 8765
                for server in servers
            )
        )


if __name__ == "__main__":
    unittest.main()