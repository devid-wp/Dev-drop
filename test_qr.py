#!/usr/bin/env python3
"""Tests for QR code generation used by the desktop GUI."""
import unittest
from io import BytesIO

import qrcode


def render_qr(address: str) -> bytes:
    """Mirror the GUI's QR rendering path in devdrop_gui.MainWindow._update_qr_code."""
    qr = qrcode.QRCode(box_size=8, border=4)
    qr.add_data(address)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class QRTests(unittest.TestCase):
    def test_renders_valid_png_for_address(self) -> None:
        png = render_qr("http://192.168.1.50:8765")
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(png), 100)

    def test_different_addresses_produce_different_qrs(self) -> None:
        png_a = render_qr("http://192.168.1.50:8765")
        png_b = render_qr("http://192.168.1.51:8765")
        self.assertNotEqual(png_a, png_b)

    def test_qr_is_decodable_to_original_address(self) -> None:
        address = "http://10.0.0.4:8765"
        png = render_qr(address)
        try:
            from pyzbar.pyzbar import decode  # type: ignore
        except ImportError:
            self.skipTest("pyzbar not installed")
        decoded = decode(png)
        self.assertTrue(decoded)
        self.assertEqual(decoded[0].data.decode("utf-8"), address)


if __name__ == "__main__":
    unittest.main()