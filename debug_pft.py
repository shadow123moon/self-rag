"""Debug PFT parsing, chunking, and retrieval quality.

Run from app root:
    D:\anaconda\envs\lc\python.exe -X utf8 debug_pft.py

It writes three files under debug_outputs/:
    pft_parsed.txt   - text extracted from the PDF page by page
    pft_chunks.txt   - chunks stored in MySQL for this document
    pft_search.txt   - hybrid_search top results for several PFT queries
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pymupdf

from database import SessionLocal
from models.document import Document, DocumentChunk
from services.parser_service import clean_text
from services.search_service import hybrid_search


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PDF_PATH = Path(r"C:\Users\shadowmoon\Downloads\Documents\2503.20337v1.pdf")
DEFAULT_FILENAME = "2503.20337v1.pdf"
DEFAULT_QUERIES = [
    "Progressive Focused Transformer 的核心方法是什么？",
    "PFT 如何利用渐进式聚焦注意力进行图像超分辨率？",
    "Progressive Focused Transformer for Single Image Super-Resolution 讲讲这个论文",
    "PFT 中 Hadamard 乘积和注意力图有什么作用？",
]


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def export_parsed_pdf(pdf_path: Path, output_dir: Path) -> None:
    """Export cleaned PDF text page by page, so you can inspect parser quality."""
    if not pdf_path.exists():
        print(f"[parsed] PDF 不存在，跳过解析导出: {pdf_path}")
        return

    parts: list[str] = []
    with pymupdf.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf, start=1):
            raw_text = page.get_text()
            cleaned_text = clean_text(raw_text)
            parts.append(f"\n\n===== page {page_index} =====\n")
            parts.append(cleaned_text)

    out_path = output_dir / "pft_parsed.txt"
    write_text(out_path, "".join(parts))
    print(f"[parsed] 已导出 PDF 解析文本: {out_path}")


def export_db_chunks(filename: str, output_dir: Path) -> None:
    """Export chunks stored in DB, so you can inspect split quality."""
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.filename == filename).first()
        if not doc:
            print(f"[chunks] 数据库中找不到文档: {filename}")
            return

        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc.document_id)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )

        parts = [
            f"filename: {doc.filename}\n",
            f"document_id: {doc.document_id}\n",
            f"status: {doc.status}\n",
            f"chunk_count in document: {doc.chunk_count}\n",
            f"actual chunk rows: {len(chunks)}\n",
        ]

        for chunk in chunks:
            parts.append("\n" + "=" * 100 + "\n")
            parts.append(f"chunk_index: {chunk.chunk_index}\n")
            parts.append(f"chunk_id: {chunk.chunk_id}\n")
            parts.append(f"page_number: {chunk.page_number}\n")
            parts.append(f"vector_id: {chunk.vector_id}\n")
            parts.append(f"length: {len(chunk.content)}\n")
            parts.append("content:\n")
            parts.append(chunk.content)
            parts.append("\n")

        out_path = output_dir / "pft_chunks.txt"
        write_text(out_path, "".join(parts))
        print(f"[chunks] 已导出数据库 chunks: {out_path}")
    finally:
        db.close()


def export_search_results(queries: list[str], output_dir: Path, top_k: int) -> None:
    """Export top hybrid_search results for manual relevance inspection."""
    parts: list[str] = []

    for query in queries:
        parts.append("\n" + "#" * 120 + "\n")
        parts.append(f"query: {query}\n")
        parts.append("#" * 120 + "\n")

        results = hybrid_search(query, top_k=top_k, vector_top_k=10, bm25_top_k=10)
        if not results:
            parts.append("没有召回结果。\n")
            continue

        for rank, (doc, score) in enumerate(results, start=1):
            metadata = doc.metadata or {}
            parts.append("\n" + "-" * 100 + "\n")
            parts.append(f"rank: {rank}\n")
            parts.append(f"hybrid_score: {score}\n")
            parts.append(f"filename: {metadata.get('filename')}\n")
            parts.append(f"page_number: {metadata.get('page_number')}\n")
            parts.append(f"chunk_index: {metadata.get('chunk_index')}\n")
            parts.append(f"chunk_id: {metadata.get('chunk_id')}\n")
            parts.append("content preview:\n")
            parts.append(doc.page_content[:1500])
            parts.append("\n")

    out_path = output_dir / "pft_search.txt"
    write_text(out_path, "".join(parts))
    print(f"[search] 已导出检索结果: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug PFT parse/chunk/search quality.")
    parser.add_argument("--pdf", default=str(DEFAULT_PDF_PATH), help="PFT PDF path")
    parser.add_argument("--filename", default=DEFAULT_FILENAME, help="filename stored in documents table")
    parser.add_argument("--top-k", type=int, default=5, help="top_k for hybrid_search")
    parser.add_argument("--output-dir", default=str(BASE_DIR / "debug_outputs"), help="output directory")
    parser.add_argument("--query", action="append", help="custom query, can be passed multiple times")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    queries = args.query or DEFAULT_QUERIES

    export_parsed_pdf(Path(args.pdf), output_dir)
    export_db_chunks(args.filename, output_dir)
    export_search_results(queries, output_dir, args.top_k)

    print("\n看这三个文件：")
    print(f"1. {output_dir / 'pft_parsed.txt'}    看解析文本脏不脏")
    print(f"2. {output_dir / 'pft_chunks.txt'}    看 chunk 有没有切碎")
    print(f"3. {output_dir / 'pft_search.txt'}    看 top5 召回到底准不准")


if __name__ == "__main__":
    main()
