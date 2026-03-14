import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.doc_ingestion import import_document
from app.core.rag_engine import LegalRagService
from app.core.text_utils import ChunkRecord
from app.repositories.pg_repository import PgRepository


class CaptureRepo:
    def __init__(self):
        self.payload = None

    def upsert_document(self, payload):
        self.payload = payload


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


class DocumentStorageTests(unittest.TestCase):
    def test_import_document_stores_content_text_outside_meta(self):
        repo = CaptureRepo()
        with patch("app.core.doc_ingestion._store_original_file", return_value="uploads/doc_test/original.txt"):
            with patch.object(settings, "UPLOAD_DIR", "data/uploads"):
                result = import_document(
                    repo,
                    file_name="sample.txt",
                    content=b"employment dispute evidence",
                    doc_type="text",
                )

        self.assertEqual(result["status"], "imported")
        self.assertIsNotNone(repo.payload)
        self.assertEqual(repo.payload["content_text"], "employment dispute evidence")
        self.assertEqual(repo.payload["file_path"], "uploads/doc_test/original.txt")
        self.assertNotIn("text", repo.payload["meta"])

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

    def test_document_viewer_content_returns_full_text_and_single_highlight_range(self):
        doc_id = "doc_view"
        citation_id = "c_view"
        full_text = "第一段\n\n第二段命中内容\n\n第三段"
        highlight_start = full_text.index("命中内容")
        highlight_end = highlight_start + len("命中内容")
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
                "payload": {"snippet": "命中内容"},
            },
        )
        service = object.__new__(LegalRagService)
        service.repo = repo
        service.chunk_lookup = {
            "chunk_view": ChunkRecord(
                chunk_id="chunk_view",
                doc_id=doc_id,
                chunk_index=0,
                chunk_text="命中内容",
                start_pos=highlight_start,
                end_pos=highlight_end,
            )
        }

        with patch.object(settings, "DATA_DIR", "data"):
            with patch("pathlib.Path.exists", return_value=True):
                result = LegalRagService.get_document_viewer_content(service, doc_id, citation_id)

        self.assertEqual(repo.include_text_calls, [True])
        self.assertEqual(result["text"], full_text)
        self.assertEqual(result["highlight"], {"start": highlight_start, "end": highlight_end})
        self.assertNotIn("blocks", result)


if __name__ == "__main__":
    unittest.main()
