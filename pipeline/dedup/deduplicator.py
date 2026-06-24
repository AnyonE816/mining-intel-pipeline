"""
去重器 — 三重策略去重

去重优先级:
  1. URL 精确匹配 → 直接去重 (最强信号)
  2. 内容 MD5 → 完全一致的正文去重
  3. 标题相似度 > threshold + 同日期 → 大概率同一条新闻被不同源转载

已处理的文档维护在内存中, 跨批次可通过 JSONL 文件去重.
"""

import hashlib
import logging
from difflib import SequenceMatcher
from datetime import timedelta

from config import settings
from models import UnifiedDocument

logger = logging.getLogger(__name__)


class Deduplicator:
    """文档去重器"""

    def __init__(self, title_threshold: float | None = None):
        self.title_threshold = title_threshold or settings.DEDUP_TITLE_SIMILARITY_THRESHOLD
        # 内存索引
        self._seen_urls: set[str] = set()
        self._seen_hashes: set[str] = set()
        self._seen_titles: list[tuple[str, str]] = []  # [(date_str, title), ...]

    def add_seen(self, docs: list[UnifiedDocument]):
        """将已有文档加入去重索引 (用于跨批次去重)"""
        for doc in docs:
            self._seen_urls.add(doc.url)
            self._seen_hashes.add(hashlib.md5(doc.content.encode()).hexdigest())
            date_str = doc.published_at.strftime("%Y-%m-%d") if doc.published_at else ""
            self._seen_titles.append((date_str, doc.title))

    def is_duplicate(self, doc: UnifiedDocument) -> tuple[bool, str]:
        """
        判断文档是否与已存在的重复

        NOTE: 不做 URL 去重。同 URL 可产出多条不同记录 (如期货页面每天爬一次)
        """
        # 1. 内容 MD5 去重 (完全相同的内容才是真重复)
        content_hash = hashlib.md5(doc.content.encode()).hexdigest()
        if content_hash in self._seen_hashes:
            return True, "Content MD5 duplicate"

        # 2. 标题相似度 + 同日期去重
        doc_date = doc.published_at.strftime("%Y-%m-%d") if doc.published_at else ""
        for seen_date, seen_title in self._seen_titles:
            if seen_date != doc_date:
                continue
            similarity = SequenceMatcher(None, doc.title.lower(), seen_title.lower()).ratio()
            if similarity >= self.title_threshold:
                return True, f"Title similarity {similarity:.2f} >= {self.title_threshold}"

        return False, ""

    def deduplicate(self, docs: list[UnifiedDocument]) -> list[UnifiedDocument]:
        """对文档列表去重, 返回去重后的列表"""
        unique = []
        duplicates = 0

        for doc in docs:
            is_dup, reason = self.is_duplicate(doc)
            if is_dup:
                logger.debug(f"Dedup: {doc.title[:50]}... → {reason}")
                duplicates += 1
                continue

            unique.append(doc)
            # 加入索引
            self._seen_urls.add(doc.url)
            self._seen_hashes.add(hashlib.md5(doc.content.encode()).hexdigest())
            date_str = doc.published_at.strftime("%Y-%m-%d") if doc.published_at else ""
            self._seen_titles.append((date_str, doc.title))

        logger.info(f"Dedup: {len(unique)} kept, {duplicates} removed")
        return unique

    def deduplicate_cross_source(self, docs: list[UnifiedDocument]) -> list[UnifiedDocument]:
        """
        跨源去重 — 同一件事可能被 mining.com 和 中国稀土集团同时报道
        使用更宽松的标题阈值
        """
        self.title_threshold = 0.75  # 跨源更宽松
        result = self.deduplicate(docs)
        self.title_threshold = settings.DEDUP_TITLE_SIMILARITY_THRESHOLD  # 恢复
        return result
