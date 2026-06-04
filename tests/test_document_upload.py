import tempfile
import unittest
from pathlib import Path

from models.document import Document


class FakeQuery:
    def __init__(self, existing_doc=None):
        self.existing_doc = existing_doc

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.existing_doc


class FakeDb:
    def __init__(self, existing_doc=None):
        self.existing_doc = existing_doc
        self.added = []
        self.committed = False
        self.refreshed = None

    def query(self, model):
        self.queried_model = model
        return FakeQuery(self.existing_doc)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        self.refreshed = obj


class FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, func, *args):
        self.tasks.append((func, args))


class FakeUploadFile:
    def __init__(self, filename, chunks):
        self.filename = filename
        self._chunks = list(chunks)

    async def read(self, _size=-1):
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


class DocumentUploadTest(unittest.IsolatedAsyncioTestCase):
    async def test_upload_document_uses_storage_metadata_and_schedules_parse(self):
        from services import document_service

        with tempfile.TemporaryDirectory() as tmp_dir:
            original_storage = document_service.storage_service
            document_service.storage_service = document_service.LocalStorageService(tmp_dir)
            try:
                db = FakeDb()
                background_tasks = FakeBackgroundTasks()
                upload = FakeUploadFile("demo.txt", [b"hello", b" rag"])

                result = await document_service.upload_document(upload, db, background_tasks)

                self.assertFalse(result["duplicate"])
                self.assertEqual(result["status"], "processing")
                self.assertEqual(len(db.added), 1)
                saved_doc = db.added[0]
                self.assertEqual(saved_doc.filename, "demo.txt")
                self.assertEqual(saved_doc.file_size, 9)
                self.assertTrue(Path(saved_doc.file_path).exists())
                self.assertEqual(Path(saved_doc.file_path).read_bytes(), b"hello rag")
                self.assertTrue(db.committed)
                self.assertEqual(len(background_tasks.tasks), 1)
                task_func, task_args = background_tasks.tasks[0]
                self.assertIs(task_func, document_service.parse_document)
                self.assertEqual(task_args, (saved_doc.document_id, saved_doc.file_path, ".txt"))
            finally:
                document_service.storage_service = original_storage

    async def test_upload_document_does_not_store_duplicate_file(self):
        from services import document_service

        existing_doc = Document(
            document_id="existing",
            filename="demo.txt",
            file_type="txt",
            file_path="somewhere",
            file_md5="5d41402abc4b2a76b9719d911017c592",
            file_size=5,
            status="completed",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            original_storage = document_service.storage_service
            document_service.storage_service = document_service.LocalStorageService(tmp_dir)
            try:
                db = FakeDb(existing_doc=existing_doc)
                background_tasks = FakeBackgroundTasks()

                result = await document_service.upload_document(
                    FakeUploadFile("demo.txt", [b"hello"]),
                    db,
                    background_tasks,
                )

                self.assertTrue(result["duplicate"])
                self.assertEqual(result["document_id"], "existing")
                self.assertEqual(db.added, [])
                self.assertEqual(background_tasks.tasks, [])
            finally:
                document_service.storage_service = original_storage


if __name__ == "__main__":
    unittest.main()
