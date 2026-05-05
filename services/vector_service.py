import uuid
import chromadb
from models.document import DocumentChunk
from config import settings  # 假设你有一些配置
from services.embedding_service import embedding_provider

#获取chroma的向量数据库
def get_collection():
    chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    collection = chroma_client.get_or_create_collection(name=settings.CHROMA_COLLECTION_NAME)
    return collection


def store_to_chroma(chunks: list[DocumentChunk], embeddings: list[list[float]], filename: str):
    if len(chunks) != len(embeddings):
        raise RuntimeError("chunks 和 embeddings 数量不一致")
    if not chunks:
        return 0

    collection = get_collection()

    ids = []
    metadatas = []
    documents = []
    embeds = []
    for chunk, emb in zip(chunks, embeddings):

        chunk_vector_id = chunk.vector_id or str(uuid.uuid4())
        ids.append(chunk_vector_id)
        metadatas.append({
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "chunk_index": chunk.chunk_index,
            "page_number": chunk.page_number or 0,
            "source": chunk.source,
            "filename": filename,  # 需要传入文件名，见下方说明
        })
        documents.append(chunk.content)
        embeds.append(emb)
        # 回写 vector_id 到 chunk 对象上（还不需要 commit）
        chunk.vector_id = chunk_vector_id

    collection.add(
        ids=ids,
        embeddings=embeds,
        metadatas=metadatas,
        documents=documents,
    )
    return len(chunks)

def vectorize_chunks(chunks: list[DocumentChunk], filename: str) -> int:
    """对已有 chunks 生成 embedding，并写入 Chroma。"""
    if not chunks:
        raise ValueError("没有 chunks，无法向量化")
    for chunk in chunks:
        chunk.vector_id = None
    texts = [chunk.content for chunk in chunks]
    embeddings = embedding_provider.embed_texts(texts)
    return store_to_chroma(chunks, embeddings, filename)

#按文档索引删除向量
def delete_vectors_by_document_id(document_id: str):
    collection = get_collection()
    collection.delete(where={"document_id": document_id})

