import hashlib
import os
import tempfile
import unittest
from pathlib import Path


class FakeUploadFile:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.read_sizes = []

    async def read(self, size=-1):
        self.read_sizes.append(size)
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


class StorageServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_local_storage_saves_upload_in_chunks_and_returns_metadata(self):
        from services.storage_service import LocalStorageService

        chunks = [b"hello", b" ", b"rag"]
        upload = FakeUploadFile(chunks)

        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = LocalStorageService(tmp_dir)

            stored = await storage.save_upload(upload, "docs/demo.txt", chunk_size=5)

            expected_content = b"hello rag"
            self.assertEqual(stored.size, len(expected_content))
            self.assertEqual(stored.md5, hashlib.md5(expected_content).hexdigest())
            self.assertEqual(Path(stored.path).read_bytes(), expected_content)
            self.assertEqual(Path(stored.path).parts[-2:], ("docs", "demo.txt"))
            self.assertEqual(upload.read_sizes, [5, 5, 5, 5])

    async def test_local_storage_rejects_paths_outside_root(self):
        from services.storage_service import LocalStorageService

        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = LocalStorageService(tmp_dir)

            with self.assertRaises(ValueError):
                await storage.save_upload(FakeUploadFile([b"x"]), "../escape.txt")

    def test_local_storage_accepts_existing_relative_paths_under_root(self):
        from services.storage_service import LocalStorageService

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
            root = Path(tmp_dir) / "storage" / "uploads"
            root.mkdir(parents=True)
            target = root / "old-doc.txt"
            target.write_text("old", encoding="utf-8")

            storage = LocalStorageService(str(root))
            old_relative_path = os.path.relpath(target, Path.cwd())

            self.assertTrue(storage.exists(old_relative_path))


if __name__ == "__main__":
    unittest.main()
