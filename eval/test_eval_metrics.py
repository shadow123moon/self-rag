import unittest

from eval_rag import calculate_metrics


class EvalMetricsTest(unittest.TestCase):
    def test_calculate_metrics(self):
        case = {
            "expected_documents": ["redis.pdf"],
            "expected_keywords": ["内存", "单线程", "IO多路复用"],
            "expected_reference_keywords": ["内存", "多路复用", "跳跃表"],
            "should_have_references": True,
        }
        answer = "Redis 基于内存操作，并使用单线程模型减少线程切换。"
        references = [
            {"filename": "redis.pdf", "content": "Redis 使用内存和 IO 多路复用提升性能。"},
            {"filename": "other.pdf", "content": "无关内容。"},
        ]

        metrics = calculate_metrics(case, answer, references)

        self.assertIs(metrics["document_hit"], True)
        self.assertEqual(metrics["keyword_recall"], 2 / 3)
        self.assertIs(metrics["reference_expected_correct"], True)
        self.assertEqual(metrics["reference_precision"], 1 / 2)
        self.assertEqual(metrics["reference_keyword_recall"], 2 / 3)
        self.assertEqual(metrics["reference_keyword_hits"], ["内存", "多路复用"])


if __name__ == "__main__":
    unittest.main()
