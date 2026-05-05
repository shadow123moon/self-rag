from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


DocumentStatus = Literal["pending", "processing", "completed", "failed"]


class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    file_type: str
    chunk_count: int
    status: DocumentStatus
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentItem(BaseModel):
    document_id: str
    filename: str
    file_type: str
    chunk_count: int
    status: DocumentStatus
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentListResponse(BaseModel):
    items: list[DocumentItem]
    total: int
    page: int
    page_size: int


class DocumentDetailResponse(BaseModel):
    document_id: str
    filename: str
    file_type: str
    file_size: int
    file_md5: str
    chunk_count: int
    status: DocumentStatus
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChunkMetadata(BaseModel):
    source: str | None = None
    page: int | None = None


class DocumentChunkItem(BaseModel):
    chunk_id: str
    document_id: str
    chunk_index: int
    content: str
    metadata: ChunkMetadata

    model_config = ConfigDict(from_attributes=True)


class DocumentChunkListResponse(BaseModel):
    items: list[DocumentChunkItem]
    total: int
    page: int
    page_size: int


class DocumentDeleteResponse(BaseModel):
    document_id: str
    deleted: bool


class DocumentReindexResponse(BaseModel):
    document_id: str
    status: DocumentStatus = Field(default="processing")
