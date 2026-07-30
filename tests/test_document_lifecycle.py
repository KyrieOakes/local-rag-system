"""Exact document deletion and legacy-source compatibility tests."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.rag.ingestion.checksum_store import make_legacy_document_id
from app.services.document_service import delete_document


def _registered_record(**overrides):
    record = {
        "document_id": "doc-1",
        "collection_name": "local_rag_docs",
        "source": "guide.md",
        "stored_path": "data/raw/uuid.md",
        "version_id": "version-1",
        "origin": "upload",
    }
    record.update(overrides)
    return record


class DocumentLifecycleServiceTest(unittest.TestCase):
    @patch("app.services.document_service.remove_upload_file", return_value=True)
    @patch(
        "app.services.document_service.delete_chunks_by_document_id",
        return_value=3,
    )
    @patch("app.services.document_service.ChecksumStore")
    def test_document_id_deletes_exact_qdrant_file_and_state(
        self,
        store_class,
        delete_chunks_mock,
        remove_file_mock,
    ):
        store = MagicMock()
        store.get_by_document_id.return_value = _registered_record()
        store.delete_document.return_value = True
        store_class.return_value = store

        result = delete_document("doc-1")

        self.assertEqual(result["status"], "deleted")
        self.assertEqual(result["deleted_chunks"], 3)
        self.assertTrue(result["file_deleted"])
        delete_chunks_mock.assert_called_once_with("doc-1", "local_rag_docs")
        remove_file_mock.assert_called_once_with("data/raw/uuid.md")
        store.delete_document.assert_called_once_with("doc-1", "local_rag_docs")

    @patch("app.services.document_service.ChecksumStore")
    def test_duplicate_source_is_reported_as_ambiguous(self, store_class):
        store = MagicMock()
        store.get_by_document_id.return_value = None
        store.find_by_source.return_value = [
            _registered_record(document_id="doc-1"),
            _registered_record(
                document_id="doc-2",
                stored_path="data/raw/other.md",
            ),
        ]
        store_class.return_value = store

        result = delete_document("guide.md")

        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(len(result["candidates"]), 2)

    @patch("app.services.document_service.remove_upload_file", return_value=True)
    @patch(
        "app.services.document_service.delete_chunks_by_filepath",
        return_value=4,
    )
    @patch("app.services.document_service.find_indexed_documents_by_source")
    @patch("app.services.document_service.ChecksumStore")
    def test_legacy_source_uses_exact_indexed_file_path(
        self,
        store_class,
        find_mock,
        delete_path_mock,
        remove_file_mock,
    ):
        store = MagicMock()
        store.get_by_document_id.return_value = None
        store.find_by_source.return_value = []
        store_class.return_value = store
        find_mock.return_value = [
            {
                "document_id": None,
                "source": "guide.md",
                "stored_path": "data/raw/legacy-uuid.md",
                "file_path": "data/raw/legacy-uuid.md",
                "chunks": 4,
            }
        ]

        result = delete_document("guide.md")

        self.assertEqual(result["status"], "deleted")
        self.assertEqual(result["deleted_chunks"], 4)
        delete_path_mock.assert_called_once_with(
            "data/raw/legacy-uuid.md",
            "local_rag_docs",
        )
        store.delete.assert_called_once_with(
            "data/raw/legacy-uuid.md",
            "local_rag_docs",
        )
        remove_file_mock.assert_called_once_with("data/raw/legacy-uuid.md")

    @patch("app.services.document_service.remove_upload_file", return_value=True)
    @patch(
        "app.services.document_service.delete_chunks_by_filepath",
        return_value=4,
    )
    @patch("app.services.document_service.find_indexed_document_by_id")
    @patch("app.services.document_service.ChecksumStore")
    def test_legacy_path_id_can_delete_one_ambiguous_candidate(
        self,
        store_class,
        find_by_id_mock,
        delete_path_mock,
        remove_file_mock,
    ):
        stored_path = "data/raw/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.md"
        legacy_id = make_legacy_document_id("local_rag_docs", stored_path)
        store = MagicMock()
        store.get_by_document_id.return_value = None
        store_class.return_value = store
        find_by_id_mock.return_value = {
            "document_id": legacy_id,
            "legacy": True,
            "source": "guide.md",
            "stored_path": stored_path,
            "file_path": stored_path,
            "chunks": 4,
        }

        result = delete_document(legacy_id)

        self.assertEqual(result["status"], "deleted")
        self.assertEqual(result["document_id"], legacy_id)
        delete_path_mock.assert_called_once_with(
            stored_path,
            "local_rag_docs",
        )
        store.delete.assert_called_once_with(stored_path, "local_rag_docs")
        remove_file_mock.assert_called_once_with(stored_path)


if __name__ == "__main__":
    unittest.main()
