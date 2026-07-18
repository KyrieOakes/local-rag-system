"""文档上传、列表与删除 API 测试。"""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


class DocumentsApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @patch("app.api.documents.ingest_document")
    @patch("app.api.documents.save_upload_file", new_callable=AsyncMock)
    def test_upload_indexes_document(self, save_upload_mock, ingest_mock):
        save_upload_mock.return_value = "data/raw/generated.md"
        ingest_mock.return_value = {
            "status": "indexed",
            "files_processed": 1,
            "chunks": 3,
        }

        response = self.client.post(
            "/documents/upload",
            files={"file": ("guide.md", b"# Guide", "text/markdown")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["chunks"], 3)
        upload = save_upload_mock.call_args.args[0]
        self.assertEqual(upload.filename, "guide.md")
        ingest_mock.assert_called_once_with(
            file_path="data/raw/generated.md",
            original_filename="guide.md",
        )

    def test_upload_rejects_unsupported_extension(self):
        response = self.client.post(
            "/documents/upload",
            files={"file": ("malware.exe", b"binary", "application/octet-stream")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported file type", response.json()["detail"])

    @patch("app.api.documents.ingest_document")
    @patch("app.api.documents.save_upload_file", new_callable=AsyncMock)
    def test_upload_maps_ingestion_error_to_500(self, save_upload_mock, ingest_mock):
        save_upload_mock.return_value = "data/raw/generated.pdf"
        ingest_mock.side_effect = RuntimeError("embedding server offline")

        response = self.client.post(
            "/documents/upload",
            files={"file": ("guide.pdf", b"pdf", "application/pdf")},
        )

        self.assertEqual(response.status_code, 500)
        self.assertIn("Document ingestion failed", response.json()["detail"])

    @patch("app.api.documents.ingest_document")
    @patch("app.api.documents.save_upload_file", new_callable=AsyncMock)
    def test_batch_upload_reports_partial_failure(self, save_upload_mock, ingest_mock):
        save_upload_mock.side_effect = [
            "data/raw/first.md",
            ValueError("Unsupported file type: .exe"),
        ]
        ingest_mock.return_value = {"status": "indexed", "chunks": 2}

        response = self.client.post(
            "/documents/upload-batch",
            files=[
                ("files", ("first.md", b"# First", "text/markdown")),
                ("files", ("second.exe", b"bad", "application/octet-stream")),
            ],
        )

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(results[0]["status"], "indexed")
        self.assertEqual(results[1]["status"], "error")
        self.assertEqual(results[1]["filename"], "second.exe")
        ingest_mock.assert_called_once_with(
            file_path="data/raw/first.md",
            original_filename="first.md",
        )

    @patch("app.api.documents.list_documents")
    def test_list_documents_returns_service_result(self, list_documents_mock):
        list_documents_mock.return_value = [
            {"source": "guide.md", "file_type": ".md", "chunks": 3}
        ]

        response = self.client.get("/documents")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["source"], "guide.md")
        list_documents_mock.assert_called_once_with()

    @patch("app.api.documents.list_documents")
    def test_list_documents_maps_service_error_to_500(self, list_documents_mock):
        list_documents_mock.side_effect = RuntimeError("qdrant offline")

        response = self.client.get("/documents")

        self.assertEqual(response.status_code, 500)
        self.assertIn("Failed to list documents", response.json()["detail"])

    @patch("app.api.documents.delete_document")
    def test_delete_document_returns_deleted_result(self, delete_document_mock):
        delete_document_mock.return_value = {
            "source": "folder/guide.md",
            "deleted_chunks": 3,
            "file_deleted": False,
            "status": "deleted",
        }

        response = self.client.delete("/documents/folder/guide.md")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted_chunks"], 3)
        delete_document_mock.assert_called_once_with("folder/guide.md")

    @patch("app.api.documents.delete_document")
    def test_delete_document_returns_404_when_missing(self, delete_document_mock):
        delete_document_mock.return_value = {
            "source": "missing.md",
            "deleted_chunks": 0,
            "file_deleted": False,
            "status": "not_found",
        }

        response = self.client.delete("/documents/missing.md")

        self.assertEqual(response.status_code, 404)
        self.assertIn("Document not found", response.json()["detail"])

    @patch("app.api.documents.delete_document")
    def test_delete_document_maps_service_error_to_500(self, delete_document_mock):
        delete_document_mock.side_effect = RuntimeError("delete failed")

        response = self.client.delete("/documents/guide.md")

        self.assertEqual(response.status_code, 500)
        self.assertIn("Failed to delete document", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
