import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredFile:
    storage_key: str
    path: str
    md5: str
    size: int


class LocalStorageService:
    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()

    async def save_upload(
        self,
        upload_file,
        object_name: str,
        chunk_size: int = 1024 * 1024,
    ) -> StoredFile:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")

        storage_key = self._normalize_key(object_name)
        target_path = self._resolve(storage_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = target_path.with_name(f"{target_path.name}.uploading")
        md5 = hashlib.md5()
        size = 0

        try:
            with open(temp_path, "wb") as output:
                while True:
                    chunk = await upload_file.read(chunk_size)
                    if not chunk:
                        break
                    md5.update(chunk)
                    size += len(chunk)
                    output.write(chunk)
            os.replace(temp_path, target_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

        return StoredFile(
            storage_key=storage_key,
            path=str(target_path),
            md5=md5.hexdigest(),
            size=size,
        )

    def delete(self, path_or_key: str) -> bool:
        path = self._resolve_path_or_key(path_or_key)
        if not path.exists():
            return False
        path.unlink()
        return True

    def exists(self, path_or_key: str) -> bool:
        return self._resolve_path_or_key(path_or_key).exists()

    def open(self, path_or_key: str, mode: str = "rb"):
        return self._resolve_path_or_key(path_or_key).open(mode)

    def _resolve_path_or_key(self, path_or_key: str) -> Path:
        candidate = Path(path_or_key)
        if candidate.is_absolute():
            resolved = candidate.resolve()
            self._ensure_inside_root(resolved)
            return resolved
        resolved_from_cwd = candidate.resolve()
        try:
            self._ensure_inside_root(resolved_from_cwd)
            return resolved_from_cwd
        except ValueError:
            pass
        return self._resolve(path_or_key)

    def _resolve(self, storage_key: str) -> Path:
        resolved = (self.root_dir / storage_key).resolve()
        self._ensure_inside_root(resolved)
        return resolved

    def _ensure_inside_root(self, path: Path) -> None:
        try:
            path.relative_to(self.root_dir)
        except ValueError as exc:
            raise ValueError("storage path must stay inside storage root") from exc

    @staticmethod
    def _normalize_key(object_name: str) -> str:
        normalized = object_name.replace("\\", "/").strip("/")
        if not normalized:
            raise ValueError("object_name must not be empty")
        return normalized
