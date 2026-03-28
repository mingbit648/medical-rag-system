import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.doc_ingestion import DuplicateDocumentError, import_document
from app.core.rag_engine import LegalRagService
from app.core.text_utils import ChunkRecord
from app.repositories.pg_repository import PgRepository


class CaptureRepo:
    def __init__(self):
        self.payload = None
        self.duplicate = None
        self.cleared_doc_ids = []
        self.documents = {}

    def upsert_document(self, payload):
        self.payload = payload

    def find_document_by_source_fingerprint(self, _kb_id, _source_fingerprint):
        return self.duplicate

    def get_document(self, doc_id, *, include_text=True, kb_id=None):
        return self.documents.get(doc_id)

    def clear_document_index(self, doc_id):
        self.cleared_doc_ids.append(doc_id)


class FakeDocRepo:
    def __init__(self, doc):
        self.doc = doc
        self.include_text_calls = []

    def get_document(self, doc_id, *, include_text=True):
        self.include_text_calls.append(include_text)
        if doc_id != self.doc["doc_id"]:
            return None
        return self.doc


class FakeViewerRepo:
    def __init__(self, doc, citation):
        self.doc = doc
        self.citation = citation
        self.include_text_calls = []

    def get_document(self, doc_id, *, include_text=True):
        self.include_text_calls.append(include_text)
        if doc_id != self.doc["doc_id"]:
            return None
        return self.doc

    def get_citation(self, citation_id):
        if citation_id != self.citation["citation_id"]:
            return None
        return self.citation


class FakeDetailRepo:
    def __init__(self, doc, chunk_rows):
        self.doc = doc
        self.chunk_rows = chunk_rows

    def get_document(self, doc_id, *, include_text=True):
        if doc_id != self.doc["doc_id"]:
            return None
        return self.doc

    def list_chunks(self, doc_id=None, indexed_only=False):
        if indexed_only:
            return []
        if doc_id and doc_id != self.doc["doc_id"]:
            return []
        return self.chunk_rows


class FakeIndexJobRepo:
    def __init__(self, doc=None, claim_result=None):
        self.doc = doc
        self.claim_result = claim_result
        self.enqueue_payload = None
        self.status_updates = []
        self.completed_jobs = []
        self.failed_jobs = []

    def get_document(self, doc_id, *, include_text=True):
        if self.doc and doc_id == self.doc["doc_id"]:
            return self.doc
        return None

    def enqueue_index_job(self, **kwargs):
        self.enqueue_payload = kwargs
        return {
            **kwargs,
            "status": "queued",
            "attempts": 0,
            "payload": kwargs["payload"],
        }

    def update_document_index_status(self, doc_id, parse_status, chunks=None, *, meta_updates=None):
        self.status_updates.append(
            {
                "doc_id": doc_id,
                "parse_status": parse_status,
                "chunks": chunks,
                "meta_updates": meta_updates,
            }
        )

    def claim_next_index_job(self, *, now_value):
        return self.claim_result

    def complete_index_job(self, job_id, *, finished_at):
        self.completed_jobs.append({"job_id": job_id, "finished_at": finished_at})

    def fail_index_job(self, job_id, *, error_message, finished_at):
        self.failed_jobs.append({"job_id": job_id, "error_message": error_message, "finished_at": finished_at})


class DocumentStorageTests(unittest.TestCase):
    def test_import_document_stores_content_text_outside_meta(self):
        repo = CaptureRepo()
        with patch("app.core.doc_ingestion._store_original_file", return_value="uploads/doc_test/original.txt"):
            with patch.object(settings, "UPLOAD_DIR", "data/uploads"):
                result = import_document(
                    repo,
                    kb_id="kb_test",
                    uploaded_by="user_test",
                    file_name="sample.txt",
                    content=b"employment dispute evidence",
                    doc_type="text",
                )

        self.assertEqual(result["status"], "imported")
        self.assertIsNotNone(repo.payload)
        self.assertEqual(repo.payload["content_text"], "employment dispute evidence")
        self.assertEqual(repo.payload["file_path"], "uploads/doc_test/original.txt")
        self.assertNotIn("text", repo.payload["meta"])
        self.assertEqual(len(repo.payload["meta"]["source_fingerprint"]), 40)
        self.assertFalse(repo.payload["meta"]["semantic_chunking_enabled"])

    def test_doc_row_to_dict_prefers_content_text_and_falls_back_to_legacy_meta_text(self):
        current = PgRepository._doc_row_to_dict(
            {
                "doc_id": "doc_current",
                "file_path": "uploads/doc_current/original.txt",
                "content_text": "current text",
                "meta_json": {
                    "text": "legacy text",
                    "chunks": 3,
                    "original_file_name": "current.txt",
                    "mime_type": "text/plain",
                    "has_original_file": True,
                    "viewer_mode": "structured_text",
                    "source_version": 2,
                },
            }
        )
        legacy = PgRepository._doc_row_to_dict(
            {
                "doc_id": "doc_legacy",
                "file_path": "uploads/doc_legacy/original.txt",
                "content_text": None,
                "meta_json": {
                    "text": "legacy text",
                    "chunks": 1,
                    "original_file_name": "legacy.txt",
                    "mime_type": "text/plain",
                    "has_original_file": True,
                    "viewer_mode": "structured_text",
                    "source_version": 2,
                },
            }
        )

        self.assertEqual(current["text"], "current text")
        self.assertEqual(legacy["text"], "legacy text")

    def test_get_document_file_resolves_relative_storage_path_from_data_dir(self):
        doc_id = "doc_path"
        data_root = Path("data")
        stored_file = data_root / "uploads" / doc_id / "original.txt"
        repo = FakeDocRepo(
            {
                "doc_id": doc_id,
                "file_path": "uploads/doc_path/original.txt",
                "source_version": 2,
                "has_original_file": True,
                "mime_type": "text/plain",
                "original_file_name": "original.txt",
            }
        )
        service = object.__new__(LegalRagService)
        service.repo = repo

        with patch.object(settings, "DATA_DIR", str(data_root)):
            with patch("pathlib.Path.exists", return_value=True):
                result = LegalRagService.get_document_file(service, doc_id)

        self.assertEqual(repo.include_text_calls, [False])
        self.assertEqual(result["file_path"], stored_file)
        self.assertEqual(result["file_name"], "original.txt")

    def test_import_document_rejects_duplicate_source_fingerprint(self):
        repo = CaptureRepo()
        repo.duplicate = {
            "doc_id": "doc_existing",
            "title": "duplicate doc",
            "doc_type": "text",
            "parse_status": "indexed",
            "chunks": 3,
            "created_at": datetime(2026, 3, 19, 0, 0, tzinfo=timezone.utc),
            "original_file_name": "existing.txt",
        }

        with self.assertRaises(DuplicateDocumentError) as ctx:
            import_document(
                repo,
                kb_id="kb_test",
                uploaded_by="user_test",
                file_name="sample.txt",
                content=b"employment dispute evidence",
                doc_type="text",
            )

        self.assertIn("知识库已有《duplicate doc》", str(ctx.exception))
        self.assertEqual(ctx.exception.existing_doc["doc_id"], "doc_existing")
        self.assertEqual(ctx.exception.existing_doc["created_at"], "2026-03-19T00:00:00+00:00")

    def test_import_document_overwrite_reuses_existing_doc_id_and_clears_old_index(self):
        repo = CaptureRepo()
        repo.documents["doc_existing"] = {
            "doc_id": "doc_existing",
            "title": "old doc",
            "doc_type": "text",
            "parse_status": "indexed",
            "chunks": 4,
            "created_at": "2026-03-19T00:00:00Z",
        }

        with patch("app.core.doc_ingestion._clear_original_file_dir") as clear_original_dir:
            with patch("app.core.doc_ingestion._store_original_file", return_value="uploads/doc_existing/original.txt"):
                result = import_document(
                    repo,
                    kb_id="kb_test",
                    uploaded_by="user_test",
                    file_name="sample.txt",
                    content=b"new evidence",
                    doc_type="text",
                    overwrite_doc_id="doc_existing",
                )

        clear_original_dir.assert_called_once_with("doc_existing")
        self.assertEqual(repo.cleared_doc_ids, ["doc_existing"])
        self.assertEqual(result["doc_id"], "doc_existing")
        self.assertTrue(result["overwritten"])
        self.assertEqual(repo.payload["doc_id"], "doc_existing")

    def test_document_viewer_content_returns_full_text_and_single_highlight_range(self):
        doc_id = "doc_view"
        citation_id = "c_view"
        full_text = "first paragraph\n\nsecond paragraph hit text\n\nthird paragraph"
        highlight_start = full_text.index("hit text")
        highlight_end = highlight_start + len("hit text")
        repo = FakeViewerRepo(
            {
                "doc_id": doc_id,
                "title": "view.txt",
                "doc_type": "text",
                "text": full_text,
                "file_path": "uploads/doc_view/original.txt",
                "source_version": 2,
                "has_original_file": True,
                "viewer_mode": "structured_text",
            },
            {
                "citation_id": citation_id,
                "doc_id": doc_id,
                "chunk_id": "chunk_view",
                "payload": {"snippet": "hit text"},
            },
        )
        service = object.__new__(LegalRagService)
        service.repo = repo
        service._ensure_citation_access = Mock(return_value=repo.citation)
        service.chunk_lookup = {
            "chunk_view": ChunkRecord(
                chunk_id="chunk_view",
                doc_id=doc_id,
                chunk_index=0,
                chunk_text="hit text",
                start_pos=highlight_start,
                end_pos=highlight_end,
            )
        }

        with patch.object(settings, "DATA_DIR", "data"):
            with patch("pathlib.Path.exists", return_value=True):
                result = LegalRagService.get_document_viewer_content(service, "user_view", doc_id, citation_id)

        self.assertEqual(repo.include_text_calls, [True])
        self.assertEqual(result["text"], full_text)
        self.assertEqual(result["highlight"], {"start": highlight_start, "end": highlight_end})
        self.assertNotIn("blocks", result)

    def test_get_document_detail_returns_full_text_and_chunk_rows(self):
        doc_id = "doc_detail"
        repo = FakeDetailRepo(
            {
                "doc_id": doc_id,
                "title": "detail.txt",
                "doc_type": "text",
                "parse_status": "indexed",
                "chunks": 2,
                "created_at": "2026-03-19T00:00:00Z",
                "original_file_name": "detail.txt",
                "viewer_mode": "structured_text",
                "has_original_file": True,
                "text": "part one\n\npart two",
            },
            [
                {
                    "chunk_id": "chunk_1",
                    "chunk_index": 0,
                    "chunk_text": "part one",
                    "start_pos": 0,
                    "end_pos": 8,
                    "section": "sec-1",
                    "article_no": None,
                    "page_start": None,
                    "page_end": None,
                    "locator_json": {"unit_kind": "paragraph"},
                },
                {
                    "chunk_id": "chunk_2",
                    "chunk_index": 1,
                    "chunk_text": "part two",
                    "start_pos": 10,
                    "end_pos": 18,
                    "section": "sec-2",
                    "article_no": None,
                    "page_start": None,
                    "page_end": None,
                    "locator_json": {"unit_kind": "paragraph"},
                },
            ],
        )
        service = object.__new__(LegalRagService)
        service.repo = repo

        result = LegalRagService.get_document_detail(service, doc_id)

        self.assertEqual(result["title"], "detail.txt")
        self.assertEqual(result["download_url"], f"{settings.API_PREFIX}/docs/{doc_id}/file")
        self.assertEqual(result["text"], "part one\n\npart two")
        self.assertEqual(len(result["chunk_items"]), 2)
        self.assertEqual(result["chunk_items"][1]["chunk_text"], "part two")

    def test_enqueue_index_job_marks_document_indexing(self):
        repo = FakeIndexJobRepo(doc={"doc_id": "doc_job", "kb_id": "kb_job"})
        service = object.__new__(LegalRagService)
        service.repo = repo

        result = LegalRagService.enqueue_index_job(
            service,
            doc_id="doc_job",
            requested_by="user_job",
            options={"chunk": {"size": 1024, "overlap": 128}},
        )

        self.assertTrue(result["job_id"].startswith("idxjob_"))
        self.assertEqual(result["doc_id"], "doc_job")
        self.assertEqual(result["kb_id"], "kb_job")
        self.assertEqual(result["status"], "indexing")
        self.assertEqual(repo.enqueue_payload["requested_by"], "user_job")
        self.assertEqual(repo.enqueue_payload["payload"], {"chunk": {"size": 1024, "overlap": 128}})
        self.assertEqual(repo.status_updates, [{"doc_id": "doc_job", "parse_status": "indexing", "chunks": None, "meta_updates": None}])

    def test_process_next_index_job_completes_successfully(self):
        repo = FakeIndexJobRepo(
            claim_result={
                "job_id": "job_success",
                "doc_id": "doc_job",
                "kb_id": "kb_job",
                "payload": {
                    "chunk": {"size": 900, "overlap": 100},
                    "bm25": {"enabled": True},
                    "vector": {"enabled": True, "embed_model": "test-model"},
                },
            }
        )
        service = object.__new__(LegalRagService)
        service.repo = repo
        service.build_index = Mock(return_value={"doc_id": "doc_job", "status": "indexed", "chunks": 3})

        result = LegalRagService.process_next_index_job(service)

        self.assertEqual(result["status"], "indexed")
        service.build_index.assert_called_once_with(
            "doc_job",
            chunk_size=900,
            overlap=100,
            bm25_enabled=True,
            vector_enabled=True,
            embed_model="test-model",
        )
        self.assertEqual(repo.completed_jobs[0]["job_id"], "job_success")
        self.assertEqual(repo.failed_jobs, [])
        self.assertEqual(repo.status_updates, [])

    def test_process_next_index_job_marks_failed_status_when_build_raises(self):
        repo = FakeIndexJobRepo(
            claim_result={
                "job_id": "job_failed",
                "doc_id": "doc_job",
                "kb_id": "kb_job",
                "payload": {},
            }
        )
        service = object.__new__(LegalRagService)
        service.repo = repo
        service.build_index = Mock(side_effect=RuntimeError("boom"))

        with patch("app.core.rag_engine.logger.exception") as log_exception:
            result = LegalRagService.process_next_index_job(service)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "boom")
        log_exception.assert_called_once()
        self.assertEqual(repo.completed_jobs, [])
        self.assertEqual(repo.failed_jobs[0]["job_id"], "job_failed")
        self.assertEqual(repo.failed_jobs[0]["error_message"], "boom")
        self.assertEqual(repo.status_updates, [{"doc_id": "doc_job", "parse_status": "failed", "chunks": None, "meta_updates": None}])


if __name__ == "__main__":
    unittest.main()
