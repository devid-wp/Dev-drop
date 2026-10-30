import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from app.main import open_unique_upload, safe_upload_name


class UploadHelperTests(unittest.TestCase):
    def test_safe_upload_name_keeps_ordinary_filename(self) -> None:
        self.assertEqual(safe_upload_name("report.txt"), "report.txt")

    def test_safe_upload_name_removes_path_components(self) -> None:
        self.assertEqual(safe_upload_name("../../photos/image.jpg"), "image.jpg")
        self.assertEqual(safe_upload_name(r"C:\photos\image.jpg"), "image.jpg")

    def test_safe_upload_name_replaces_special_characters(self) -> None:
        self.assertEqual(safe_upload_name("bad:name?.txt"), "bad_name_.txt")
        self.assertEqual(safe_upload_name("... "), "upload.bin")

    def test_safe_upload_name_replaces_control_characters(self) -> None:
        self.assertEqual(safe_upload_name("bad\nname.txt"), "bad_name.txt")

    def test_open_unique_upload_does_not_overwrite_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            existing = session_dir / "photo.jpg"
            existing.write_bytes(b"original")

            path, output = open_unique_upload(session_dir, "photo.jpg")
            with output:
                output.write(b"new upload")

            self.assertEqual(path.name, "photo (1).jpg")
            self.assertEqual(existing.read_bytes(), b"original")
            self.assertEqual(path.read_bytes(), b"new upload")

    def test_open_unique_upload_increments_suffix_for_repeated_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            names = []
            for _ in range(3):
                path, output = open_unique_upload(session_dir, "note.txt")
                output.close()
                names.append(path.name)

            self.assertEqual(names, ["note.txt", "note (1).txt", "note (2).txt"])

    def test_open_unique_upload_rejects_path_outside_session_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory) / "session"
            session_dir.mkdir()

            with self.assertRaises(HTTPException) as error:
                open_unique_upload(session_dir, "../outside.txt")

            self.assertEqual(error.exception.status_code, 400)
            self.assertFalse((Path(temporary_directory) / "outside.txt").exists())

    def test_legacy_imports_remain_available_from_app_main(self) -> None:
        from app import main
        from app import uploads

        self.assertIs(main.safe_upload_name, uploads.safe_upload_name)
        self.assertIs(main.open_unique_upload, uploads.open_unique_upload)


if __name__ == "__main__":
    unittest.main()
