"""Bounded upload streaming tests."""

from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import UploadFile

from app.utils.file_utils import (
    UploadTooLargeError,
    remove_upload_file,
    save_upload_file,
)


class UploadFileUtilsTest(unittest.IsolatedAsyncioTestCase):
    async def test_streamed_upload_is_saved_under_uuid_name(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.utils.file_utils.UPLOAD_DIR",
            Path(temp_dir),
        ):
            upload = UploadFile(
                filename="guide.md",
                file=io.BytesIO(b"# Guide"),
            )

            saved = await save_upload_file(upload, max_bytes=64)

            saved_path = Path(saved)
            self.assertEqual(saved_path.read_bytes(), b"# Guide")
            self.assertEqual(saved_path.suffix, ".md")
            self.assertNotEqual(saved_path.name, "guide.md")

    async def test_oversized_partial_file_is_removed(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.utils.file_utils.UPLOAD_DIR",
            Path(temp_dir),
        ), patch(
            "app.utils.file_utils.UPLOAD_READ_CHUNK_BYTES",
            3,
        ):
            upload = UploadFile(
                filename="large.txt",
                file=io.BytesIO(b"123456"),
            )

            with self.assertRaises(UploadTooLargeError):
                await save_upload_file(upload, max_bytes=4)

            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    async def test_pdf_extension_requires_pdf_magic_and_cleans_temp_file(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.utils.file_utils.UPLOAD_DIR",
            Path(temp_dir),
        ):
            upload = UploadFile(
                filename="spoofed.pdf",
                file=io.BytesIO(b"not a PDF"),
            )

            with self.assertRaisesRegex(ValueError, "Invalid PDF"):
                await save_upload_file(upload, max_bytes=64)

            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    async def test_docx_requires_word_document_xml(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types />")
        buffer.seek(0)

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.utils.file_utils.UPLOAD_DIR",
            Path(temp_dir),
        ):
            upload = UploadFile(filename="spoofed.docx", file=buffer)

            with self.assertRaisesRegex(ValueError, "Invalid DOCX"):
                await save_upload_file(upload, max_bytes=1024)

            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    async def test_valid_docx_container_is_accepted(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "word/document.xml",
                "<w:document xmlns:w='urn:test' />",
            )
        buffer.seek(0)

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.utils.file_utils.UPLOAD_DIR",
            Path(temp_dir),
        ):
            upload = UploadFile(filename="guide.docx", file=buffer)

            saved = await save_upload_file(upload, max_bytes=2048)

            self.assertTrue(Path(saved).exists())

    async def test_text_upload_must_be_utf8(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.utils.file_utils.UPLOAD_DIR",
            Path(temp_dir),
        ):
            upload = UploadFile(
                filename="broken.txt",
                file=io.BytesIO(b"\xff\xfe"),
            )

            with self.assertRaisesRegex(ValueError, "valid UTF-8"):
                await save_upload_file(upload, max_bytes=64)

            self.assertEqual(list(Path(temp_dir).iterdir()), [])

    def test_cleanup_refuses_path_outside_upload_root(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as outside_dir, patch(
            "app.utils.file_utils.UPLOAD_DIR",
            Path(temp_dir),
        ):
            outside = Path(outside_dir) / "keep.md"
            outside.write_text("keep", encoding="utf-8")

            self.assertFalse(remove_upload_file(outside))
            self.assertTrue(outside.exists())


if __name__ == "__main__":
    unittest.main()
