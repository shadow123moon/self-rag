import json
from pathlib import Path

from services.rag_service import RagService


ragservice = RagService()
BASE_DIR = Path(__file__).resolve().parent


def calc_mrr(references, expected_docs):
    for rank, ref in enumerate(references, start=1):
        if ref.get("filename") in expected_docs:
            return 1 / rank
    return 0.0


def safe_avg(values):
    return sum(values) / len(values) if values else 0.0


with open(BASE_DIR / "eval" / "eval_cases.json", "r", encoding="utf-8") as f:
    data = json.load(f)

user_id = "test"

# ===== 汇总指标 =====
document_hits = []
mrr_scores = []
answer_keyword_rates = []
reference_keyword_rates = []
reference_expected_hits = []
negative_reject_hits = []

for case in data:
    answer = ""
    question = case["question"]
    session_id = case["id"]
    references = []

    for event in ragservice.stream_answer(
        question,
        user_id,
        session_id,
        top_k=5,
        save_history=False,
    ):
        if event["type"] == "chunk":
            answer += event["content"]
        elif event["type"] == "done":
            references = event.get("references", [])

    expected_docs = case.get("expected_documents", [])
    expected_keywords = case.get("expected_keywords", [])
    expected_reference_keywords = case.get(
        "expected_reference_keywords",
        expected_keywords,
    )
    should_have_references = case.get("should_have_references", True)

    # ===== 单条 case 指标 =====
    has_file = any(ref.get("filename") in expected_docs for ref in references)
    answer_matched = [kw for kw in expected_keywords if kw in answer]
    all_reference_content = " ".join(ref.get("content", "") for ref in references)
    ref_matched = [kw for kw in expected_reference_keywords if kw in all_reference_content]
    mrr = calc_mrr(references, expected_docs)

    if expected_docs:
        document_hits.append(1 if has_file else 0)
        mrr_scores.append(mrr)

    if expected_keywords:
        answer_keyword_rates.append(len(answer_matched) / len(expected_keywords))

    if expected_reference_keywords and should_have_references:
        reference_keyword_rates.append(len(ref_matched) / len(expected_reference_keywords))

    if should_have_references:
        reference_expected_hits.append(1 if len(references) > 0 else 0)
    else:
        reference_expected_hits.append(1 if len(references) == 0 else 0)
        negative_reject_hits.append(1 if len(references) == 0 else 0)

    # ===== 打印单条结果 =====
    print(f"\n[{case['id']}] {question}")
    print(f"文档命中: {has_file}")
    print(f"答案匹配: {answer_matched}")
    print(f"答案命中率: {len(answer_matched)}/{len(expected_keywords)}")
    print(f"引用匹配: {ref_matched}")
    print(f"引用命中率: {len(ref_matched)}/{len(expected_reference_keywords)}")
    print(f"引用数量: {len(references)}")
    print(f"MRR: {mrr:.4f}")

# ===== 打印汇总结果 =====
print("\n========== 简易 RAG 评估汇总 ==========")
print(f"总题数: {len(data)}")
print(f"文档命中率: {safe_avg(document_hits):.2%}")
print(f"平均 MRR: {safe_avg(mrr_scores):.2%}")
print(f"平均答案关键词覆盖率: {safe_avg(answer_keyword_rates):.2%}")
print(f"平均引用关键词覆盖率: {safe_avg(reference_keyword_rates):.2%}")
print(f"引用预期准确率: {safe_avg(reference_expected_hits):.2%}")
print(f"无关问题拒引率: {safe_avg(negative_reject_hits):.2%}")
print("======================================")
