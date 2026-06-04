import os
import uuid
import hashlib
from fastapi import UploadFile, HTTPException

ALLOWED_EXTENSIONS = {".txt", ".pdf", ".docx"}


def validate_file_type(file: UploadFile) -> str:
    """校验文件类型，返回小写扩展名"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"File type not allowed: {ext}")

    # 只对 pdf 做魔数校验（docx 也有魔数，可加）
    if ext == ".pdf":
        # 注意：这里不移动文件指针，需要外部 seek(0)
        # 但建议在路由或服务层保留指针位置处理
        ...
    return ext


def generate_document_id() -> str:
    return uuid.uuid4().hex


def compute_md5(file_path: str) -> str:
    """计算文件的 MD5（已保存到磁盘后）"""
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


