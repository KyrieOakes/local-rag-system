"""Versioned ingestion and document-registry regression tests."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.ingestion import bulk_writer
from app.rag.ingestion.checksum_store import (
    ChecksumStore,
    make_document_id,
    make_legacy_document_id,
)
from app.rag.ingestion.ingest_pipeline import (
    _ingest_one,
    _retry_pending_cleanups,
    _load_and_split_file,
    _reconcile_removed_files,
    build_pipeline_fingerprint,
    ingest_directory,
)


def _registry_record(**overrides):
    record = {
        "document_id": "doc-1",
        "collection_name": "test-collection",
        "identity_key": "upload:guide.md",
        "source": "guide.md",
        "stored_path": "data/raw/old.md",
        "content_md5": "old-md5",
        "pipeline_fingerprint": "old-fingerprint",
        "version_id": "old-version",
        "chunk_count": 2,
        "origin": "upload",
        "scan_root": "",
    }
    record.update(overrides)
    return record


class ChecksumStoreRegistryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "ingestion.db"
        self.db_patcher = patch(
            "app.rag.ingestion.checksum_store.DB_PATH",
            self.db_path,
        )
        self.db_patcher.start()

    def tearDown(self):
        self.db_patcher.stop()
        self.temp_dir.cleanup()

    def test_registry_replaces_stored_path_for_stable_document_id(self):
        store = ChecksumStore()
        first = _registry_record()
        second = _registry_record(
            stored_path="data/raw/new.md",
            content_md5="new-md5",
            version_id="new-version",
        )

        store.upsert_document(first)
        store.upsert_document(second)
        # Re-opening the store reruns migration; the mirrored legacy checksum
        # row must not create a second path-based registry identity.
        store = ChecksumStore()

        current = store.get_by_document_id("doc-1", "test-collection")
        self.assertEqual(current["stored_path"], "data/raw/new.md")
        self.assertIsNone(store.get("data/raw/old.md", "test-collection"))
        self.assertEqual(len(store.find_by_source("guide.md", "test-collection")), 1)

        self.assertTrue(store.delete_document("doc-1", "test-collection"))
        self.assertEqual(store.all(), {})

    def test_legacy_checksum_rows_are_migrated_without_claiming_a_version(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE file_checksums (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE NOT NULL,
                    md5 TEXT NOT NULL,
                    last_ingested_at TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    collection_name TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO file_checksums (
                    file_path, md5, last_ingested_at, chunk_count, collection_name
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("data/raw/legacy.md", "abc", "2026-01-01T00:00:00", 3, "legacy"),
            )

        store = ChecksumStore()
        migrated = store.get("data/raw/legacy.md", "legacy")

        self.assertIsNotNone(migrated)
        self.assertEqual(migrated["content_md5"], "abc")
        self.assertEqual(migrated["version_id"], "")
        self.assertEqual(migrated["origin"], "legacy")
        self.assertEqual(
            migrated["document_id"],
            make_legacy_document_id("legacy", "data/raw/legacy.md"),
        )

    def test_activation_atomically_persists_old_version_cleanup(self):
        store = ChecksumStore()
        previous = _registry_record()
        current = _registry_record(
            stored_path="data/raw/new.md",
            content_md5="new-md5",
            version_id="new-version",
        )
        store.upsert_document(previous)

        store.activate_document(current, [previous])

        active = store.get_by_document_id("doc-1", "test-collection")
        pending = store.list_pending_cleanups("test-collection", "doc-1")
        self.assertEqual(active["version_id"], "new-version")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["previous_version_id"], "old-version")
        self.assertEqual(pending[0]["active_version_id"], "new-version")

        self.assertTrue(
            store.complete_pending_cleanup(pending[0]["cleanup_id"])
        )
        self.assertEqual(
            store.list_pending_cleanups("test-collection", "doc-1"),
            [],
        )

    def test_deleting_one_collection_keeps_other_collection_registry(self):
        store = ChecksumStore()
        shared_path = "data/engineering/shared.md"
        first = _registry_record(
            document_id="doc-one",
            collection_name="one",
            stored_path=shared_path,
        )
        second = _registry_record(
            document_id="doc-two",
            collection_name="two",
            stored_path=shared_path,
        )
        store.upsert_document(first)
        store.upsert_document(second)

        self.assertTrue(store.delete_document("doc-one", "one"))

        self.assertIsNotNone(store.get_by_document_id("doc-two", "two"))
        self.assertEqual(store.get(shared_path)["collection_name"], "two")


class PipelineIdentityTest(unittest.TestCase):
    def test_document_id_is_stable_and_collection_scoped(self):
        first = make_document_id("one", "upload:guide.md")
        again = make_document_id("one", "upload:guide.md")
        other_collection = make_document_id("two", "upload:guide.md")

        self.assertEqual(first, again)
        self.assertNotEqual(first, other_collection)

    def test_pipeline_fingerprint_changes_with_chunk_or_embedding_config(self):
        baseline = build_pipeline_fingerprint("collection")
        with patch.object(settings, "chunk_size", settings.chunk_size + 1):
            chunk_changed = build_pipeline_fingerprint("collection")
        with patch.object(settings, "embedding_model", "different-model"):
            embedding_changed = build_pipeline_fingerprint("collection")
        with patch.object(settings, "embedding_revision", "quantization-v2"):
            revision_changed = build_pipeline_fingerprint("collection")

        self.assertNotEqual(baseline, chunk_changed)
        self.assertNotEqual(baseline, embedding_changed)
        self.assertNotEqual(baseline, revision_changed)
        self.assertNotEqual(
            baseline,
            build_pipeline_fingerprint("different-collection"),
        )

    @patch("app.rag.ingestion.ingest_pipeline.split_documents")
    @patch("app.rag.ingestion.ingest_pipeline.load_document")
    def test_chunk_index_restarts_for_each_file(self, load_mock, split_mock):
        load_mock.return_value = [Document(page_content="raw")]
        split_mock.return_value = [
            Document(page_content="first"),
            Document(page_content="second"),
        ]

        chunks = _load_and_split_file(
            Path("/tmp/guide.md"),
            source="guide.md",
            document_id="doc",
            version_id="version",
            pipeline_fingerprint="fingerprint",
            content_md5="md5",
        )

        self.assertEqual([chunk.metadata["chunk_index"] for chunk in chunks], [0, 1])
        self.assertTrue(all(chunk.metadata["document_id"] == "doc" for chunk in chunks))
        self.assertTrue(all(chunk.metadata["stored_path"] == "/tmp/guide.md" for chunk in chunks))


class BulkWriterValidationTest(unittest.TestCase):
    @patch("app.rag.ingestion.bulk_writer._get_client")
    def test_count_mismatch_is_rejected_before_qdrant(self, client_mock):
        chunk = Document(
            page_content="one",
            metadata={
                "document_id": "doc",
                "version_id": "version",
                "chunk_index": 0,
                "source": "guide.md",
                "stored_path": "/tmp/guide.md",
                "md5": "md5",
                "pipeline_fingerprint": "fingerprint",
            },
        )

        with self.assertRaisesRegex(ValueError, "count mismatch"):
            bulk_writer.bulk_upsert_chunks([chunk], [])

        client_mock.assert_not_called()

    @patch("app.rag.ingestion.bulk_writer._get_client")
    def test_existing_collection_dimension_mismatch_fails_before_upsert(
        self,
        client_factory,
    ):
        client = MagicMock()
        client.collection_exists.return_value = True
        client.get_collection.return_value = SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors=SimpleNamespace(size=3),
                )
            )
        )
        client_factory.return_value = client
        chunk = Document(
            page_content="one",
            metadata={
                "document_id": "doc",
                "version_id": "version",
                "chunk_index": 0,
                "source": "guide.md",
                "stored_path": "/tmp/guide.md",
                "md5": "md5",
                "pipeline_fingerprint": "fingerprint",
            },
        )

        with self.assertRaisesRegex(ValueError, "does not match collection"):
            bulk_writer.bulk_upsert_chunks(
                [chunk],
                [[0.1, 0.2]],
                "existing",
            )

        client.upsert.assert_not_called()

    def test_point_id_changes_across_pipeline_versions(self):
        first = bulk_writer._make_point_id("doc", "version-1", 0)
        again = bulk_writer._make_point_id("doc", "version-1", 0)
        changed = bulk_writer._make_point_id("doc", "version-2", 0)

        self.assertEqual(first, again)
        self.assertNotEqual(first, changed)

    @patch("app.rag.ingestion.bulk_writer._scroll_metadata")
    def test_same_source_legacy_groups_receive_distinct_stable_ids(
        self,
        scroll_mock,
    ):
        scroll_mock.return_value = [
            {
                "source": "guide.md",
                "file_path": "data/raw/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.md",
            },
            {
                "source": "guide.md",
                "file_path": "data/raw/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.md",
            },
        ]

        matches = bulk_writer.find_indexed_documents_by_source(
            "guide.md",
            "collection",
        )

        self.assertEqual(len(matches), 2)
        self.assertTrue(all(match["legacy"] for match in matches))
        self.assertTrue(all(match["document_id"] for match in matches))
        self.assertNotEqual(
            matches[0]["document_id"],
            matches[1]["document_id"],
        )


class SafeReplacementTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_path = Path(self.temp_dir.name) / "guide.md"
        self.file_path.write_text("new content", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("app.rag.ingestion.ingest_pipeline.delete_chunks_by_document_version")
    @patch("app.rag.ingestion.ingest_pipeline.bulk_upsert_chunks")
    @patch("app.rag.ingestion.ingest_pipeline.embed_texts")
    @patch("app.rag.ingestion.ingest_pipeline._load_and_split_file")
    def test_registry_activation_precedes_old_version_cleanup(
        self,
        load_mock,
        embed_mock,
        upsert_mock,
        delete_mock,
    ):
        events = []
        load_mock.return_value = [Document(page_content="chunk", metadata={})]
        embed_mock.return_value = [[0.1, 0.2]]
        upsert_mock.side_effect = lambda *_args, **_kwargs: events.append("upsert") or 1
        delete_mock.side_effect = lambda *_args, **_kwargs: events.append("delete") or 2
        store = MagicMock()
        store.get_by_document_id.return_value = _registry_record(
            document_id=make_document_id(
                "test-collection",
                f"directory:{self.file_path.resolve()}",
            ),
            origin="directory",
            stored_path=str(self.file_path.resolve()),
        )
        pending = []

        def activate(record, previous_records):
            events.append("state")
            previous = previous_records[0]
            pending.append(
                {
                    "cleanup_id": 1,
                    "active_document_id": record["document_id"],
                    "active_version_id": record["version_id"],
                    "collection_name": record["collection_name"],
                    "previous_document_id": previous["document_id"],
                    "previous_version_id": previous["version_id"],
                    "previous_stored_path": previous["stored_path"],
                    "previous_content_md5": previous["content_md5"],
                    "previous_origin": previous["origin"],
                }
            )

        store.activate_document.side_effect = activate
        store.list_pending_cleanups.side_effect = (
            lambda *_args, **_kwargs: list(pending)
        )
        store.complete_pending_cleanup.side_effect = (
            lambda cleanup_id: pending.clear() or cleanup_id == 1
        )

        result = _ingest_one(
            self.file_path,
            collection_name="test-collection",
            batch_size=64,
            source="guide.md",
            origin="directory",
            scan_root=self.temp_dir.name,
            store=store,
        )

        self.assertEqual(result["status"], "indexed")
        self.assertFalse(result["cleanup_pending"])
        self.assertEqual(events, ["upsert", "state", "delete"])

    @patch("app.rag.ingestion.ingest_pipeline.bulk_upsert_chunks")
    @patch("app.rag.ingestion.ingest_pipeline.embed_texts")
    @patch("app.rag.ingestion.ingest_pipeline._load_and_split_file")
    def test_embedding_count_mismatch_does_not_write_or_advance_state(
        self,
        load_mock,
        embed_mock,
        upsert_mock,
    ):
        load_mock.return_value = [Document(page_content="chunk", metadata={})]
        embed_mock.return_value = []
        store = MagicMock()
        store.get_by_document_id.return_value = _registry_record()

        with self.assertRaisesRegex(ValueError, "unexpected number"):
            _ingest_one(
                self.file_path,
                collection_name="test-collection",
                batch_size=64,
                source="guide.md",
                origin="directory",
                scan_root=self.temp_dir.name,
                store=store,
            )

        upsert_mock.assert_not_called()
        store.upsert_document.assert_not_called()

    @patch("app.rag.ingestion.ingest_pipeline.delete_chunks_by_document_version")
    @patch("app.rag.ingestion.ingest_pipeline.bulk_upsert_chunks", return_value=1)
    @patch("app.rag.ingestion.ingest_pipeline.embed_texts", return_value=[[0.1]])
    @patch(
        "app.rag.ingestion.ingest_pipeline._load_and_split_file",
        return_value=[Document(page_content="chunk", metadata={})],
    )
    def test_old_cleanup_failure_keeps_active_version_and_durable_retry(
        self,
        _load_mock,
        _embed_mock,
        _upsert_mock,
        delete_mock,
    ):
        delete_mock.side_effect = RuntimeError("old cleanup failed")
        store = MagicMock()
        store.get_by_document_id.return_value = _registry_record()
        pending = []

        def activate(record, previous_records):
            previous = previous_records[0]
            pending.append(
                {
                    "cleanup_id": 1,
                    "active_document_id": record["document_id"],
                    "active_version_id": record["version_id"],
                    "collection_name": record["collection_name"],
                    "previous_document_id": previous["document_id"],
                    "previous_version_id": previous["version_id"],
                    "previous_stored_path": previous["stored_path"],
                    "previous_content_md5": previous["content_md5"],
                    "previous_origin": previous["origin"],
                }
            )

        store.activate_document.side_effect = activate
        store.list_pending_cleanups.side_effect = (
            lambda *_args, **_kwargs: list(pending)
        )

        result = _ingest_one(
            self.file_path,
            collection_name="test-collection",
            batch_size=64,
            source="guide.md",
            origin="directory",
            scan_root=self.temp_dir.name,
            store=store,
        )

        self.assertTrue(result["cleanup_pending"])
        delete_mock.assert_called_once()
        self.assertEqual(delete_mock.call_args.args[1], "old-version")
        store.complete_pending_cleanup.assert_not_called()

    @patch("app.rag.ingestion.ingest_pipeline.delete_chunks_by_document_version")
    @patch("app.rag.ingestion.ingest_pipeline.bulk_upsert_chunks", return_value=1)
    @patch("app.rag.ingestion.ingest_pipeline.embed_texts", return_value=[[0.1]])
    @patch(
        "app.rag.ingestion.ingest_pipeline._load_and_split_file",
        return_value=[Document(page_content="chunk", metadata={})],
    )
    def test_registry_activation_failure_rolls_back_only_new_version(
        self,
        _load_mock,
        _embed_mock,
        _upsert_mock,
        delete_mock,
    ):
        store = MagicMock()
        store.get_by_document_id.return_value = _registry_record()
        store.activate_document.side_effect = RuntimeError("sqlite unavailable")

        with self.assertRaisesRegex(RuntimeError, "sqlite unavailable"):
            _ingest_one(
                self.file_path,
                collection_name="test-collection",
                batch_size=64,
                source="guide.md",
                origin="directory",
                scan_root=self.temp_dir.name,
                store=store,
            )

        delete_mock.assert_called_once()
        rollback_args = delete_mock.call_args.args
        self.assertNotEqual(rollback_args[1], "old-version")
        store.complete_pending_cleanup.assert_not_called()

    @patch("app.rag.ingestion.ingest_pipeline.delete_chunks_by_document_version")
    @patch(
        "app.rag.ingestion.ingest_pipeline.bulk_upsert_chunks",
        side_effect=ValueError("Embedding dimension 2 does not match collection"),
    )
    @patch("app.rag.ingestion.ingest_pipeline.embed_texts", return_value=[[0.1, 0.2]])
    @patch(
        "app.rag.ingestion.ingest_pipeline._load_and_split_file",
        return_value=[Document(page_content="chunk", metadata={})],
    )
    def test_dimension_failure_never_deletes_old_version(
        self,
        _load_mock,
        _embed_mock,
        _upsert_mock,
        delete_mock,
    ):
        document_id = make_document_id(
            "test-collection",
            f"directory:{self.file_path.resolve()}",
        )
        store = MagicMock()
        store.get_by_document_id.return_value = _registry_record(
            document_id=document_id,
            version_id="old-version",
        )

        with self.assertRaisesRegex(ValueError, "dimension"):
            _ingest_one(
                self.file_path,
                collection_name="test-collection",
                batch_size=64,
                source="guide.md",
                origin="directory",
                scan_root=self.temp_dir.name,
                store=store,
            )

        self.assertEqual(delete_mock.call_count, 1)
        rollback_args = delete_mock.call_args.args
        self.assertEqual(rollback_args[0], document_id)
        self.assertNotEqual(rollback_args[1], "old-version")
        store.upsert_document.assert_not_called()


class DurableCleanupAndLegacyUploadTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "ingestion.db"
        self.upload_root = Path(self.temp_dir.name) / "raw"
        self.upload_root.mkdir()
        self.db_patcher = patch(
            "app.rag.ingestion.checksum_store.DB_PATH",
            self.db_path,
        )
        self.root_patcher = patch(
            "app.rag.ingestion.ingest_pipeline.UPLOAD_ROOT",
            self.upload_root,
        )
        self.db_patcher.start()
        self.root_patcher.start()

    def tearDown(self):
        self.root_patcher.stop()
        self.db_patcher.stop()
        self.temp_dir.cleanup()

    @patch(
        "app.rag.ingestion.ingest_pipeline.delete_chunks_by_document_version",
        return_value=2,
    )
    def test_pending_cleanup_is_idempotently_retried(self, delete_mock):
        store = ChecksumStore()
        previous = _registry_record(
            document_id="doc",
            collection_name="collection",
            stored_path=str(Path(self.temp_dir.name) / "guide.md"),
            origin="directory",
        )
        current = _registry_record(
            document_id="doc",
            collection_name="collection",
            stored_path=str(Path(self.temp_dir.name) / "guide.md"),
            version_id="new-version",
            content_md5="new-md5",
            origin="directory",
        )
        store.upsert_document(previous)
        store.activate_document(current, [previous])

        self.assertEqual(_retry_pending_cleanups(store, "collection", "doc"), 0)

        delete_mock.assert_called_once_with(
            "doc",
            "old-version",
            "collection",
        )
        self.assertEqual(
            store.list_pending_cleanups("collection", "doc"),
            [],
        )

    @patch(
        "app.rag.ingestion.ingest_pipeline.delete_legacy_file_version",
        return_value=2,
    )
    @patch(
        "app.rag.ingestion.ingest_pipeline.find_indexed_documents_by_source",
    )
    @patch("app.rag.ingestion.ingest_pipeline.bulk_upsert_chunks", return_value=1)
    @patch("app.rag.ingestion.ingest_pipeline.embed_texts", return_value=[[0.1]])
    @patch(
        "app.rag.ingestion.ingest_pipeline._load_and_split_file",
        return_value=[Document(page_content="chunk", metadata={})],
    )
    def test_legacy_uuid_upload_is_adopted_by_original_filename_identity(
        self,
        _load_mock,
        _embed_mock,
        _upsert_mock,
        find_mock,
        delete_legacy_mock,
    ):
        collection = "collection"
        legacy_path = self.upload_root / ("a" * 32 + ".md")
        legacy_path.write_text("old", encoding="utf-8")
        new_path = self.upload_root / ("b" * 32 + ".md")
        new_path.write_text("new", encoding="utf-8")

        store = ChecksumStore()
        legacy_id = make_legacy_document_id(collection, str(legacy_path))
        store.upsert_document(
            _registry_record(
                document_id=legacy_id,
                collection_name=collection,
                identity_key=f"directory:{legacy_path.resolve()}",
                source=legacy_path.name,
                stored_path=str(legacy_path),
                content_md5="legacy-md5",
                pipeline_fingerprint="",
                version_id="",
                origin="legacy",
            )
        )
        find_mock.return_value = [
            {
                "document_id": legacy_id,
                "legacy": True,
                "source": "guide.md",
                "stored_path": str(legacy_path),
                "file_path": str(legacy_path),
                "md5": "legacy-md5",
                "chunks": 2,
            }
        ]

        result = _ingest_one(
            new_path,
            collection_name=collection,
            batch_size=64,
            source="guide.md",
            origin="upload",
            scan_root="",
            store=store,
        )

        active_id = make_document_id(collection, "upload:guide.md")
        self.assertEqual(result["document_id"], active_id)
        self.assertIsNotNone(store.get_by_document_id(active_id, collection))
        self.assertIsNone(store.get_by_document_id(legacy_id, collection))
        self.assertFalse(legacy_path.exists())
        self.assertTrue(new_path.exists())
        self.assertEqual(store.list_pending_cleanups(collection, active_id), [])
        delete_legacy_mock.assert_called_once()


class RemovedFileReconciliationTest(unittest.TestCase):
    @patch(
        "app.rag.ingestion.ingest_pipeline.delete_chunks_by_document_id",
        return_value=2,
    )
    def test_only_registered_paths_inside_current_root_are_removed(self, delete_mock):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            inside = str(root / "deleted.md")
            outside = str(root.parent / "outside.md")
            store = MagicMock()
            store.list_for_scan_root.return_value = [
                _registry_record(
                    document_id="inside",
                    stored_path=inside,
                    origin="directory",
                    scan_root=str(root),
                ),
                _registry_record(
                    document_id="outside",
                    stored_path=outside,
                    origin="directory",
                    scan_root=str(root),
                ),
            ]

            removed, failures = _reconcile_removed_files(
                scan_root=root,
                collection_name="test-collection",
                scanned_paths=set(),
                store=store,
            )

        self.assertEqual(removed, 1)
        self.assertEqual(len(failures), 1)
        delete_mock.assert_called_once_with("inside", "test-collection")
        store.delete_document.assert_called_once_with("inside", "test-collection")

    @patch(
        "app.rag.ingestion.ingest_pipeline.delete_chunks_by_document_id",
        return_value=2,
    )
    @patch("app.rag.ingestion.ingest_pipeline.ChecksumStore")
    def test_empty_directory_still_reconciles_removed_files(
        self,
        store_class,
        delete_mock,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            store = MagicMock()
            store.list_for_scan_root.return_value = [
                _registry_record(
                    document_id="removed",
                    stored_path=str(root / "gone.md"),
                    origin="directory",
                    scan_root=str(root),
                )
            ]
            store_class.return_value = store

            result = ingest_directory(
                str(root),
                collection_name="test-collection",
            )

        self.assertEqual(result["status"], "indexed")
        self.assertEqual(result["removed_files"], 1)
        self.assertEqual(result["total_files"], 0)
        delete_mock.assert_called_once_with("removed", "test-collection")


if __name__ == "__main__":
    unittest.main()
