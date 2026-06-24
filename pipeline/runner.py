"""
管线运行器 — 一键执行 采集 → 清洗 → 去重 → 入库 全流程

用法:
  python pipeline/runner.py              # 全流程
  python pipeline/runner.py --step scrape  # 仅采集
  python pipeline/runner.py --step clean   # 仅清洗+去重
  python pipeline/runner.py --step ingest  # 仅入库
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# 确保项目根在 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from models import UnifiedDocument, SourceType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("runner")


async def step_scrape() -> list[UnifiedDocument]:
    """阶段 1: 采集"""
    from pipeline.scrapers.mining_news import MiningNewsScraper
    from pipeline.scrapers.policy import PolicyScraper
    from pipeline.scrapers.price import PriceScraper

    logger.info("=" * 50)
    logger.info("Phase 1: Scraping all sources")
    logger.info("=" * 50)

    all_docs = []

    # 源 1: 矿业新闻
    logger.info("→ Scraping mining news...")
    async with MiningNewsScraper() as scraper:
        news_docs = await scraper.scrape()
    all_docs.extend(news_docs)
    logger.info(f"  ✓ Mining news: {len(news_docs)} docs")

    # 源 2: 矿产政策
    logger.info("→ Scraping policies...")
    async with PolicyScraper() as scraper:
        policy_docs = await scraper.scrape()
    all_docs.extend(policy_docs)
    logger.info(f"  ✓ Policies: {len(policy_docs)} docs")

    # 源 3: 价格行情
    logger.info("→ Scraping prices...")
    async with PriceScraper() as scraper:
        price_docs = await scraper.scrape()
    all_docs.extend(price_docs)
    logger.info(f"  ✓ Prices: {len(price_docs)} docs")

    # 汇总
    by_type = {"news": 0, "policy": 0, "price": 0}
    for doc in all_docs:
        by_type[doc.source_type.value] += 1
    logger.info(f"Total raw: {len(all_docs)} (news={by_type['news']}, policy={by_type['policy']}, price={by_type['price']})")

    # 持久化原始汇总
    summary_path = settings.RAW_DIR / "_all_raw.jsonl"
    with open(summary_path, "w", encoding="utf-8") as f:
        for doc in all_docs:
            f.write(doc.model_dump_json() + "\n")
    logger.info(f"Saved all raw docs to {summary_path}")

    return all_docs


def step_clean(docs: list[UnifiedDocument]) -> list[UnifiedDocument]:
    """阶段 2: 清洗 + 去重"""
    from pipeline.cleaners.cleaner import DocumentCleaner
    from pipeline.dedup.deduplicator import Deduplicator

    logger.info("=" * 50)
    logger.info("Phase 2: Cleaning & Deduplication")
    logger.info("=" * 50)

    # 清洗
    logger.info(f"→ Cleaning {len(docs)} docs...")
    cleaned = DocumentCleaner.clean_batch(docs)
    logger.info(f"  ✓ Cleaned: {len(cleaned)} docs")

    # 先去重同一来源的
    dedup = Deduplicator()
    unique = dedup.deduplicate(cleaned)

    # 再去重跨源的
    unique = dedup.deduplicate_cross_source(unique)

    # 按源统计
    by_type = {"news": 0, "policy": 0, "price": 0}
    by_name = {}
    for doc in unique:
        by_type[doc.source_type.value] += 1
        by_name[doc.source_name] = by_name.get(doc.source_name, 0) + 1

    logger.info(f"After dedup: {len(unique)} docs")
    logger.info(f"  By type: {by_type}")
    logger.info(f"  By source: {by_name}")

    # 持久化
    output_path = settings.PROCESSED_DIR / "cleaned_deduped.jsonl"
    with open(output_path, "w", encoding="utf-8") as f:
        for doc in unique:
            f.write(doc.model_dump_json() + "\n")
    logger.info(f"Saved to {output_path}")

    return unique


def step_ingest(docs: list[UnifiedDocument]) -> int:
    """阶段 3: 向量库入库"""
    from pipeline.vectordb.store import VectorStoreManager

    logger.info("=" * 50)
    logger.info("Phase 3: Vector DB Ingestion")
    logger.info("=" * 50)

    logger.info(f"→ Ingesting {len(docs)} docs into ChromaDB...")
    store = VectorStoreManager()
    chunk_count = store.add_documents(docs)
    logger.info(f"  ✓ Ingested: {chunk_count} chunks")

    # 统计
    stats = store.get_stats()
    logger.info(f"  Total chunks in DB: {stats['total_chunks']}")
    logger.info(f"  Date range: {stats['date_range']}")

    return chunk_count


async def run_all():
    """一键运行全流程"""
    import time
    start = time.time()

    docs = await step_scrape()

    if len(docs) < 100:
        logger.warning(f"Only {len(docs)} docs scraped — check data sources!")
        # 不阻断, 允许继续

    cleaned = step_clean(docs)
    chunks = step_ingest(cleaned)

    elapsed = time.time() - start
    logger.info("=" * 50)
    logger.info(f"Pipeline complete in {elapsed:.1f}s")
    logger.info(f"  Documents: {len(cleaned)}")
    logger.info(f"  Chunks: {chunks}")
    logger.info("=" * 50)


# ── CLI ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Mining Intel Pipeline Runner")
    parser.add_argument("--step", choices=["scrape", "clean", "ingest"], help="Run single step")
    parser.add_argument("--all", action="store_true", help="Run full pipeline (default)")
    args = parser.parse_args()

    if args.step == "scrape":
        asyncio.run(step_scrape())
    elif args.step == "clean":
        # 从文件加载
        raw_file = settings.RAW_DIR / "_all_raw.jsonl"
        if not raw_file.exists():
            logger.error("No raw data found. Run --step scrape first.")
            return
        docs = []
        with open(raw_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    docs.append(UnifiedDocument.model_validate_json(line))
        step_clean(docs)
    elif args.step == "ingest":
        processed_file = settings.PROCESSED_DIR / "cleaned_deduped.jsonl"
        if not processed_file.exists():
            logger.error("No processed data found. Run --step scrape then --step clean first.")
            return
        docs = []
        with open(processed_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    docs.append(UnifiedDocument.model_validate_json(line))
        step_ingest(docs)
    else:
        asyncio.run(run_all())


if __name__ == "__main__":
    main()
