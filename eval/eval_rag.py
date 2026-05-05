import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
os.chdir(APP_DIR)

from config import settings
from database import SessionLocal
from models.conversation import ConversationSession
from services.rag_service import RagService


CURRENT_DIR = Path(__file__).resolve().parent
DEFAULT_CASES_PATH = CURRENT_DIR / "eval_cases.json"
DEFAULT_OUTPUT_PATH = CURRENT_DIR / "eval_results.json"


def load_cases(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def contains_keyword(answer: str, keyword: str) -> bool:
    return keyword.lower() in answer.lower()


def calculate_metrics(case: dict, answer: str, references: list[dict]) -> dict:
    expected_documents = case.get("expected_documents", [])
    expected_keywords = case.get("expected_keywords", [])
    expected_reference_keywords = case.get("expected_reference_keywords", expected_keywords)
    should_have_references = case.get("should_have_references", True)

    retrieved_documents = [ref.get("filename", "") for ref in references]
    retrieved_document_set = set(retrieved_documents)

    keyword_hits = [
        keyword
        for keyword in expected_keywords
        if contains_keyword(answer, keyword)
    ]
    keyword_misses = [
        keyword
        for keyword in expected_keywords
        if keyword not in keyword_hits
    ]
    reference_text = "\n".join(ref.get("content", "") for ref in references)
    reference_keyword_hits = [
        keyword
        for keyword in expected_reference_keywords
        if contains_keyword(reference_text, keyword)
    ]
    reference_keyword_misses = [
        keyword
        for keyword in expected_reference_keywords
        if keyword not in reference_keyword_hits
    ]

    document_hit = None
    if expected_documents:
        document_hit = any(doc in retrieved_document_set for doc in expected_documents)

    keyword_recall = None
    if expected_keywords:
        keyword_recall = len(keyword_hits) / len(expected_keywords)

    reference_expected_correct = bool(references) == bool(should_have_references)

    reference_precision = None
    if references and expected_documents:
        correct_refs = sum(1 for filename in retrieved_documents if filename in expected_documents)
        reference_precision = correct_refs / len(references)

    mrr = None
    if expected_documents:
        mrr = 0.0
        for rank, filename in enumerate(retrieved_documents, start=1):
            if filename in expected_documents:
                mrr = 1 / rank
                break

    reference_keyword_recall = None
    if expected_reference_keywords:
        reference_keyword_recall = len(reference_keyword_hits) / len(expected_reference_keywords)

    return {
        "document_hit": document_hit,
        "mrr": mrr,
        "keyword_recall": keyword_recall,
        "keyword_hits": keyword_hits,
        "keyword_misses": keyword_misses,
        "reference_keyword_recall": reference_keyword_recall,
        "reference_keyword_hits": reference_keyword_hits,
        "reference_keyword_misses": reference_keyword_misses,
        "reference_expected_correct": reference_expected_correct,
        "reference_precision": reference_precision,
        "retrieved_documents": sorted(retrieved_document_set),
    }


def get_case_group(case: dict) -> str:
    if case.get("group"):
        return case["group"]
    case_id = case.get("id", "unknown")
    return case_id.split("_", 1)[0]


def run_case(
    rag_service: RagService,
    case: dict,
    user_id: str,
    run_id: str,
    top_k: int,
    save_history: bool,
) -> dict:
    case_id = case["id"]
    question = case["question"]
    session_id = f"{run_id}_{case_id}"

    answer = ""
    references = []

    for event in rag_service.stream_answer(
        query=question,
        user_id=user_id,
        session_id=session_id,
        top_k=top_k,
        save_history=save_history,
    ):
        if event["type"] == "chunk":
            answer += event["content"]
        elif event["type"] == "done":
            references = event.get("references", [])

    metrics = calculate_metrics(case, answer, references)

    return {
        "id": case_id,
        "group": get_case_group(case),
        "question": question,
        "expected_documents": case.get("expected_documents", []),
        "expected_keywords": case.get("expected_keywords", []),
        "expected_reference_keywords": case.get("expected_reference_keywords", case.get("expected_keywords", [])),
        "should_have_references": case.get("should_have_references", True),
        "answer": answer,
        "references": references,
        "metrics": metrics,
    }


def average(values: list[Any]) -> float | None:
    numbers = [value for value in values if value is not None]
    if not numbers:
        return None
    return mean(numbers)


def build_summary(results: list[dict]) -> dict:
    metrics = [result["metrics"] for result in results]
    negative_results = [
        result
        for result in results
        if not result.get("should_have_references", True)
    ]

    return {
        "total_cases": len(results),
        "document_hit_rate": average([item["document_hit"] for item in metrics]),
        "average_mrr": average([item["mrr"] for item in metrics]),
        "average_keyword_recall": average([item["keyword_recall"] for item in metrics]),
        "average_reference_keyword_recall": average([
            item["reference_keyword_recall"]
            for item in metrics
        ]),
        "reference_expectation_accuracy": average([
            item["reference_expected_correct"]
            for item in metrics
        ]),
        "average_reference_precision": average([
            item["reference_precision"]
            for item in metrics
        ]),
        "no_reference_accuracy": average([
            not bool(result["references"])
            for result in negative_results
        ]),
    }


def build_group_summaries(results: list[dict]) -> dict:
    grouped_results: dict[str, list[dict]] = {}
    for result in results:
        grouped_results.setdefault(result.get("group", "unknown"), []).append(result)
    return {
        group: build_summary(group_results)
        for group, group_results in sorted(grouped_results.items())
    }


def print_case_result(result: dict) -> None:
    metrics = result["metrics"]
    print(f"\n[{result['id']}] {result['question']}")
    print("  expected_documents:", result["expected_documents"])
    print("  retrieved_documents:", metrics["retrieved_documents"])
    print("  document_hit:", metrics["document_hit"])
    print("  mrr:", metrics["mrr"])
    print("  keyword_recall:", metrics["keyword_recall"])
    print("  keyword_hits:", metrics["keyword_hits"])
    print("  reference_keyword_recall:", metrics["reference_keyword_recall"])
    print("  reference_keyword_hits:", metrics["reference_keyword_hits"])
    print("  reference_expected_correct:", metrics["reference_expected_correct"])
    print("  reference_count:", len(result["references"]))


def print_summary(summary: dict) -> None:
    print("\n========== RAG 评估汇总 ==========")
    print("总题数:", summary["total_cases"])
    print("文档命中率:", format_rate(summary["document_hit_rate"]))
    print("平均 MRR:", format_rate(summary["average_mrr"]))
    print("平均关键词覆盖率:", format_rate(summary["average_keyword_recall"]))
    print("引用证据关键词覆盖率:", format_rate(summary["average_reference_keyword_recall"]))
    print("引用预期准确率:", format_rate(summary["reference_expectation_accuracy"]))
    print("平均引用精确率:", format_rate(summary["average_reference_precision"]))
    print("无关问题拒引率:", format_rate(summary["no_reference_accuracy"]))
    print("=================================\n")


def print_group_summaries(group_summaries: dict) -> None:
    if not group_summaries:
        return

    print("========== 分组评估汇总 ==========")
    for group, summary in group_summaries.items():
        print(f"[{group}]")
        print("  总题数:", summary["total_cases"])
        print("  文档命中率:", format_rate(summary["document_hit_rate"]))
        print("  平均 MRR:", format_rate(summary["average_mrr"]))
        print("  平均关键词覆盖率:", format_rate(summary["average_keyword_recall"]))
        print("  引用证据关键词覆盖率:", format_rate(summary["average_reference_keyword_recall"]))
        print("  引用预期准确率:", format_rate(summary["reference_expectation_accuracy"]))
        print("  平均引用精确率:", format_rate(summary["average_reference_precision"]))
        print("  无关问题拒引率:", format_rate(summary["no_reference_accuracy"]))
    print("=================================\n")


def format_rate(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.2f}%"


def save_report(output_path: Path, report: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)


def cleanup_eval_conversations(user_id: str, run_id: str) -> int:
    db = SessionLocal()
    try:
        session_prefix = f"{user_id}__{run_id}_"
        sessions = (
            db.query(ConversationSession)
            .filter(
                ConversationSession.user_id == user_id,
                ConversationSession.session_id.like(f"{session_prefix}%"),
            )
            .all()
        )
        deleted_count = len(sessions)
        for session in sessions:
            db.delete(session)
        db.commit()
        return deleted_count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run PaiSmart-mini RAG evaluation cases.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH), help="评估用例 JSON 路径")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="评估结果输出路径")
    parser.add_argument("--top-k", type=int, default=5, help="每题检索 top_k")
    parser.add_argument("--user-id", default="eval_user", help="评估使用的 user_id")
    parser.add_argument("--distance", type=float, default=None, help="临时覆盖 RAG_MAX_DISTANCE")
    parser.add_argument("--keep-db", action="store_true", help="保留本次评估产生的数据库会话记录")
    parser.add_argument("--save-history", action="store_true", help="评估时仍写入对话历史")
    return parser.parse_args()

'''
首先定义函数的命令行参数：测试JSON路径、输出结果路径等等
接着加载测试文档，
enumerate：同时获取元素及其对应的索引
'''
def main() -> None:
    args = parse_args()
    if args.distance is not None:
        settings.RAG_MAX_DISTANCE = args.distance

    cases_path = Path(args.cases)
    output_path = Path(args.output)
    run_id = f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    cases = load_cases(cases_path)
    rag_service = RagService()
    results = []

    print("run_id:", run_id)
    print("cases:", cases_path)
    print("top_k:", args.top_k)
    print("max_distance:", settings.RAG_MAX_DISTANCE)

    try:
        for index, case in enumerate(cases, start=1):
            print(f"\n正在评估 {index}/{len(cases)}: {case['id']}")
            result = run_case(
                rag_service=rag_service,
                case=case,
                user_id=args.user_id,
                run_id=run_id,
                top_k=args.top_k,
                save_history=args.save_history,
            )
            results.append(result)
            print_case_result(result)

        summary = build_summary(results)
        group_summaries = build_group_summaries(results)
        report = {
            "run_id": run_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "settings": {
                "top_k": args.top_k,
                "rag_max_distance": settings.RAG_MAX_DISTANCE,
                "cases_path": str(cases_path),
                "save_history": args.save_history,
            },
            "summary": summary,
            "group_summaries": group_summaries,
            "results": results,
        }

        save_report(output_path, report)
        print_summary(summary)
        print_group_summaries(group_summaries)
        print("详细结果已保存:", output_path)
    finally:
        if args.keep_db:
            print("已保留本次评估产生的数据库会话记录")
        else:
            deleted_count = cleanup_eval_conversations(args.user_id, run_id)
            print(f"已清理本次评估数据库会话记录: {deleted_count} 个")


if __name__ == "__main__":
    main()
