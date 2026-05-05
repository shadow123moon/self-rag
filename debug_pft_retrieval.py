"""Debug PFT retrieval paths separately: BM25, Vector, and final RRF hybrid.

Run from app root:
    D:\anaconda\envs\lc\python.exe -X utf8 debug_pft_retrieval.py

Useful variants:
    D:\anaconda\envs\lc\python.exe -X utf8 debug_pft_retrieval.py --case-id pft_001
    D:\anaconda\envs\lc\python.exe -X utf8 debug_pft_retrieval.py --query "PFT 的 PFA 机制是什么？"

Outputs:
    debug_outputs/pft_retrieval_debug.txt
    debug_outputs/pft_retrieval_debug.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from config import settings
from services.bm25_service import bm25_search
from services.search_service import search_similar_with_score


BASE_DIR = Path(__file__).resolve().parent
CASE_PATH = BASE_DIR / "eval" / "eval_cases.json"
DEFAULT_OUTPUT_DIR = BASE_DIR / "debug_outputs"
RRF_K = 60


def load_pft_cases(case_id: str | None = None, custom_query: str | None = None) -> list[dict[str, Any]]:
    if custom_query:
        return [
            {
                "id": "custom_query",
                "question": custom_query,
                "expected_documents": ["2503.20337v1.pdf"],
                "expected_keywords": [],
                "should_have_references": True,
            }
        ]

    cases = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    pft_cases = [case for case in cases if str(case.get("id", "")).startswith("pft_")]
    if case_id:
        pft_cases = [case for case in pft_cases if case.get("id") == case_id]
    return pft_cases


def doc_key(doc: Any) -> str:
    return (doc.metadata or {}).get("chunk_id") or f"no_chunk_id:{id(doc)}"


def compact_doc(doc: Any, score: float, rank: int, score_name: str, expected_docs: list[str]) -> dict[str, Any]:
    metadata = doc.metadata or {}
    filename = metadata.get("filename")
    return {
        "rank": rank,
        score_name: score,
        "is_expected_document": filename in expected_docs,
        "filename": filename,
        "page_number": metadata.get("page_number"),
        "chunk_index": metadata.get("chunk_index"),
        "chunk_id": metadata.get("chunk_id"),
        "document_id": metadata.get("document_id"),
        "content_preview": (doc.page_content or "")[:1200],
    }


def fuse_with_rrf(
    bm25_results: list[tuple[Any, float]],
    vector_results: list[tuple[Any, float]],
    top_k: int,
) -> list[dict[str, Any]]:
    """Replicate search_service.hybrid_search fusion without calling embedding twice."""
    best_bm25_score = bm25_results[0][1] if bm25_results else 0
    has_vector_signal = len(vector_results) > 0
    has_strong_bm25_signal = best_bm25_score >= settings.BM25_STRONG_SCORE
    if not has_vector_signal and not has_strong_bm25_signal:
        return []

    rrf_scores: dict[str, float] = {}
    doc_map: dict[str, Any] = {}
    bm25_map: dict[str, dict[str, Any]] = {}
    vector_map: dict[str, dict[str, Any]] = {}

    for rank, (doc, score) in enumerate(bm25_results, start=1):
        key = doc_key(doc)
        rrf_scores[key] = rrf_scores.get(key, 0.0) + 1 / (RRF_K + rank)
        doc_map[key] = doc
        bm25_map[key] = {"rank": rank, "score": score}

    for rank, (doc, distance) in enumerate(vector_results, start=1):
        key = doc_key(doc)
        rrf_scores[key] = rrf_scores.get(key, 0.0) + 1 / (RRF_K + rank)
        doc_map[key] = doc
        vector_map[key] = {"rank": rank, "distance": distance}

    sorted_keys = sorted(rrf_scores.keys(), key=lambda key: rrf_scores[key], reverse=True)
    fused: list[dict[str, Any]] = []
    for final_rank, key in enumerate(sorted_keys[:top_k], start=1):
        doc = doc_map[key]
        metadata = doc.metadata or {}
        in_bm25 = key in bm25_map
        in_vector = key in vector_map
        if in_bm25 and in_vector:
            source = "both"
        elif in_bm25:
            source = "bm25_only"
        else:
            source = "vector_only"

        fused.append(
            {
                "rank": final_rank,
                "rrf_score": rrf_scores[key],
                "source": source,
                "bm25_rank": bm25_map.get(key, {}).get("rank"),
                "bm25_score": bm25_map.get(key, {}).get("score"),
                "vector_rank": vector_map.get(key, {}).get("rank"),
                "vector_distance": vector_map.get(key, {}).get("distance"),
                "filename": metadata.get("filename"),
                "page_number": metadata.get("page_number"),
                "chunk_index": metadata.get("chunk_index"),
                "chunk_id": metadata.get("chunk_id"),
                "document_id": metadata.get("document_id"),
                "content_preview": (doc.page_content or "")[:1200],
            }
        )
    return fused


def write_txt_report(report: list[dict[str, Any]], output_path: Path) -> None:
    lines: list[str] = []
    lines.append("PFT retrieval debug report\n")
    lines.append(f"RAG_MAX_DISTANCE: {settings.RAG_MAX_DISTANCE}\n")
    lines.append(f"BM25_MIN_SCORE: {settings.BM25_MIN_SCORE}\n")
    lines.append(f"BM25_STRONG_SCORE: {settings.BM25_STRONG_SCORE}\n")
    lines.append(f"RRF_K: {RRF_K}\n")

    for item in report:
        case = item["case"]
        expected_docs = case.get("expected_documents", [])
        lines.append("\n" + "#" * 120 + "\n")
        lines.append(f"[{case.get('id')}] {case.get('question')}\n")
        lines.append(f"expected_documents: {expected_docs}\n")
        lines.append(
            "summary: "
            f"bm25_count={len(item['bm25'])}, "
            f"vector_raw_count={len(item['vector_raw'])}, "
            f"vector_kept_count={len(item['vector_kept'])}, "
            f"hybrid_count={len(item['hybrid'])}\n"
        )
        lines.append(
            "best: "
            f"bm25={item['best_bm25_score']}, "
            f"vector_distance={item['best_vector_distance']}\n"
        )

        for section_name, section_title in [
            ("bm25", "BM25 返回"),
            ("vector_raw", "Vector 原始返回"),
            ("vector_kept", "Vector 阈值过滤后"),
            ("hybrid", "Hybrid/RRF 最终融合"),
        ]:
            lines.append("\n" + "=" * 40 + f" {section_title} " + "=" * 40 + "\n")
            results = item[section_name]
            if not results:
                lines.append("无结果\n")
                continue

            for result in results:
                filename = result.get("filename")
                pollution = "OK" if filename in expected_docs else "POLLUTION"
                lines.append("\n" + "-" * 100 + "\n")
                lines.append(f"rank: {result.get('rank')} | {pollution}\n")
                for field in [
                    "bm25_score",
                    "vector_distance",
                    "rrf_score",
                    "source",
                    "bm25_rank",
                    "vector_rank",
                    "filename",
                    "page_number",
                    "chunk_index",
                    "chunk_id",
                ]:
                    if field in result and result.get(field) is not None:
                        lines.append(f"{field}: {result.get(field)}\n")
                lines.append("content_preview:\n")
                lines.append(result.get("content_preview", ""))
                lines.append("\n")

    output_path.write_text("".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug PFT BM25/vector/hybrid retrieval separately.")
    parser.add_argument("--case-id", help="Only run one PFT case id, e.g. pft_001")
    parser.add_argument("--query", help="Run one custom query instead of eval PFT cases")
    parser.add_argument("--top-k", type=int, default=5, help="Final hybrid top_k")
    parser.add_argument("--bm25-top-k", type=int, default=10)
    parser.add_argument("--vector-top-k", type=int, default=10)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cases = load_pft_cases(case_id=args.case_id, custom_query=args.query)
    if not cases:
        raise ValueError("没有找到要调试的 PFT case")

    report: list[dict[str, Any]] = []
    for case in cases:
        query = case["question"]
        expected_docs = case.get("expected_documents", [])

        print(f"\n调试: [{case.get('id')}] {query}")
        bm25_results = bm25_search(query, args.bm25_top_k)
        vector_raw = search_similar_with_score(query, args.vector_top_k)
        vector_kept = [(doc, distance) for doc, distance in vector_raw if distance <= settings.RAG_MAX_DISTANCE]
        hybrid = fuse_with_rrf(bm25_results, vector_kept, args.top_k)

        report.append(
            {
                "case": case,
                "best_bm25_score": bm25_results[0][1] if bm25_results else None,
                "best_vector_distance": vector_raw[0][1] if vector_raw else None,
                "bm25": [
                    compact_doc(doc, score, rank, "bm25_score", expected_docs)
                    for rank, (doc, score) in enumerate(bm25_results, start=1)
                ],
                "vector_raw": [
                    compact_doc(doc, distance, rank, "vector_distance", expected_docs)
                    for rank, (doc, distance) in enumerate(vector_raw, start=1)
                ],
                "vector_kept": [
                    compact_doc(doc, distance, rank, "vector_distance", expected_docs)
                    for rank, (doc, distance) in enumerate(vector_kept, start=1)
                ],
                "hybrid": hybrid,
            }
        )

    json_path = output_dir / "pft_retrieval_debug.json"
    txt_path = output_dir / "pft_retrieval_debug.txt"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_txt_report(report, txt_path)

    print("\n已生成：")
    print(txt_path)
    print(json_path)


if __name__ == "__main__":
    main()
