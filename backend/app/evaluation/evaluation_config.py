DATASET_FILES = {
    "customer_support_cases": "customer_support_cases.jsonl",
    "order_queries": "order_queries.jsonl",
    "refund_queries": "refund_queries.jsonl",
    "multilingual_queries": "multilingual_queries.jsonl",
    "adversarial_queries": "adversarial_queries.jsonl",
}
METRICS = ["correctness", "faithfulness", "groundedness", "relevance", "completeness", "tool_accuracy", "language_quality"]
PASS_SCORE = 4.0            # per-metric pass threshold on the 1-5 scale
JUDGE_WEIGHT = 0.5          # blend of judge score vs deterministic score when both exist
