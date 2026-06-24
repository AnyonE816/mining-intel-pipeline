"""
爬虫基类 — 所有 Scraper 必须继承此抽象类

设计原则:
  - 统一接口: 所有 scraper 返回 List[UnifiedDocument]
  - 异步优先: 使用 httpx.AsyncClient + asyncio
  - 自动限速: 基类处理请求间隔和并发控制
  - Mock 支持: MOCK_MODE 下从本地文件读取, 保障管线可运行
"""

import asyncio
import json
import logging
import random
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import httpx

from config import settings
from models import UnifiedDocument, SourceType

logger = logging.getLogger(__name__)

# 统一使用 Safari UA — 澳洲政府站/大部分网站均稳定通过
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15"


class BaseScraper(ABC):
    """所有数据源采集器的抽象基类"""

    source_name: str          # 子类必须定义, 如 "mining_com"
    source_type: SourceType   # 子类必须定义, 如 SourceType.NEWS

    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self.client = client
        self._owns_client = False

    async def __aenter__(self):
        await self._ensure_client()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def _ensure_client(self):
        """延迟创建 HTTP 客户端"""
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=60.0,
                follow_redirects=True,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
            self._owns_client = True

    async def close(self):
        if self._owns_client and self.client:
            await self.client.aclose()

    @abstractmethod
    async def scrape(self) -> list[UnifiedDocument]:
        """采集数据, 返回文档列表. 子类必须实现."""
        ...

    async def safe_get(self, url: str, retries: int = 2, **kwargs) -> httpx.Response:
        """带限速和重试的安全 GET 请求"""
        await self._ensure_client()
        last_error = None
        for attempt in range(retries + 1):
            await asyncio.sleep(settings.SCRAPE_DELAY + random.uniform(0, 0.5))
            try:
                resp = await self.client.get(url, **kwargs)
                resp.raise_for_status()
                return resp
            except httpx.HTTPError as e:
                last_error = e
                if attempt < retries:
                    logger.debug(f"Retry {attempt+1}/{retries} for {url[:60]}: {e}")
                    await asyncio.sleep(3 * (attempt + 1))  # 递增等待
        logger.warning(f"HTTP error fetching {url}: {last_error}")
        raise last_error

    def _save_raw(self, docs: list[UnifiedDocument], suffix: str = ""):
        """保存原始采集结果到 data/raw/"""
        name = self.source_name + suffix
        path = settings.RAW_DIR / f"{name}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for doc in docs:
                f.write(doc.model_dump_json() + "\n")
        logger.info(f"Saved {len(docs)} raw docs to {path}")

    def _load_mock(self, suffix: str = "") -> list[UnifiedDocument]:
        """Mock 模式: 从预置文件加载数据"""
        name = self.source_name + suffix
        path = settings.RAW_DIR / f"{name}.jsonl"
        if not path.exists():
            logger.warning(f"Mock file not found: {path}")
            return []
        docs = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    docs.append(UnifiedDocument.model_validate_json(line))
        logger.info(f"Loaded {len(docs)} mock docs from {path}")
        return docs

    @abstractmethod
    async def scrape(self) -> list[UnifiedDocument]:
        ...
