"""
评测入口 — 自动运行 20 条 ground truth Q&A 并输出报告

用法:
  python eval/run_eval.py
  python eval/run_eval.py --output results.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from serve.rag_chain import RAGChain
from eval.metrics import run_batch_eval

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("eval")


def load_ground_truth() -> list[dict]:
    """加载 ground truth 数据"""
    gt_path = Path(__file__).parent / "ground_truth.json"
    if not gt_path.exists():
        logger.error(f"Ground truth file not found: {gt_path}")
        return []

    with open(gt_path, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "items" in data:
        return data["items"]

    logger.error("Unknown ground truth format")
    return []


def main():
    parser = argparse.ArgumentParser(description="Run evaluation on mining intel pipeline")
    parser.add_argument("--output", default="eval/results.json", help="Output path for results")
    args = parser.parse_args()

    # 加载 ground truth
    ground_truths = load_ground_truth()
    if not ground_truths:
        logger.error("No ground truth items found. Please create eval/ground_truth.json first.")
        return

    logger.info(f"Loaded {len(ground_truths)} ground truth items")

    # 初始化 RAG Chain
    rag = RAGChain()
    logger.info("RAG chain initialized")

    # 运行评测
    logger.info("Running evaluation...")
    results = run_batch_eval(ground_truths, rag)

    # 输出
    print("\n" + "=" * 60)
    print("📊 Evaluation Results")
    print("=" * 60)
    print(f"  Recall@5:       {results['recall_at_5']:.1%}")
    print(f"  Faithfulness:   {results['avg_faithfulness']:.3f}")
    print(f"  Questions:      {len(ground_truths)}")
    print("-" * 60)
    for item in results["per_question"]:
        status = "✅" if item["recall@5"] > 0 else "❌"
        print(f"  {status} {item['id']}: recall={item['recall@5']}, faith={item['faithfulness']:.3f} | {item['question'][:60]}...")
    print("=" * 60)

    # 保存
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"Results saved to {output_path}")


if __name__ == "__main__":
    main()
