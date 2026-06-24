"""
mining.com 新闻采集器 (WordPress REST API)

发现: mining.com 运行在 WordPress 上, REST API 完全开放 (/wp-json/wp/v2/posts)
数据源:
  - mining.com WP REST API (主要, 56K+ posts)
  - S&P Global RSS (备选, 403 被墙)

WP API 参数:
  - per_page: 最大 100
  - after: ISO 日期过滤
  - page: 分页

预期产出: ≥200 条新闻 (WP API 30天内预估 >500 条)
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from config import settings
from models import UnifiedDocument, SourceType, Language
from pipeline.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

WP_API = "https://www.mining.com/wp-json/wp/v2/posts"
# Fallback RSS
RSS_FEED = "https://www.mining.com/feed/"


class MiningNewsScraper(BaseScraper):
    source_name = "mining_com"
    source_type = SourceType.NEWS

    async def scrape(self) -> list[UnifiedDocument]:
        if settings.MOCK_MODE:
            return self._load_mock()

        docs = []

        # Primary: WordPress REST API (full content included, no need separate fetch)
        wp_docs = await self._scrape_wp_api()
        docs.extend(wp_docs)
        logger.info(f"WP API: {len(wp_docs)} docs")

        # Fallback: RSS (if WP API doesn't give enough)
        if len(docs) < settings.SCRAPE_MIN_PER_SOURCE:
            rss_docs = await self._scrape_rss()
            docs.extend(rss_docs)
            logger.info(f"RSS supplement: {len(rss_docs)} docs")

        self._save_raw(docs)
        return docs

    async def _scrape_wp_api(self) -> list[UnifiedDocument]:
        """
        WordPress REST API — 获取近N天的文章 (含全文)

        WP API 返回的 content.rendered 已包含完整的 HTML 正文,
        不需要二次爬取页面, 大幅提升速度.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.SCRAPE_DAYS_BACK)
        after_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%S")

        docs = []
        page = 1
        max_pages = 10  # 安全上限: 10页 × 100条 = 最多1000条

        semaphore = asyncio.Semaphore(settings.SCRAPE_MAX_CONCURRENT)

        while page <= max_pages:
            url = f"{WP_API}?per_page=100&page={page}&after={after_iso}&_fields=id,title,content,excerpt,link,date,author_info,categories,yoast_head"
            try:
                resp = await self.safe_get(url)
                posts = resp.json()

                if not posts or not isinstance(posts, list):
                    break

                logger.info(f"  Page {page}: {len(posts)} posts")

                for post in posts:
                    doc = await self._parse_wp_post(post)
                    if doc:
                        docs.append(doc)

                # 如果返回不足一页, 说明没有更多了
                if len(posts) < 100:
                    break

                page += 1

            except Exception as e:
                logger.warning(f"WP API page {page} failed: {e}")
                break

        return docs

    async def _parse_wp_post(self, post: dict) -> UnifiedDocument | None:
        """解析 WP API 返回的单条文章"""
        try:
            title = BeautifulSoup(post.get("title", {}).get("rendered", ""), "html.parser").get_text(strip=True)
            if not title:
                return None

            url = post.get("link", "")
            date_str = post.get("date", "")
            published = datetime.fromisoformat(date_str.replace("Z", "+00:00"))

            # 全文: WP API 的 content.rendered 包含完整 HTML 正文
            html_content = post.get("content", {}).get("rendered", "")
            content = BeautifulSoup(html_content, "html.parser").get_text(separator="\n", strip=True)
            content = re.sub(r"\n{3,}", "\n\n", content)[:5000]

            if not content:
                content = title

            # 摘要
            excerpt_html = post.get("excerpt", {}).get("rendered", "")
            summary = BeautifulSoup(excerpt_html, "html.parser").get_text()[:500] if excerpt_html else ""

            # 作者
            author = ""
            author_info = post.get("author_info", {})
            if author_info:
                author = author_info.get("display_name", "")

            doc_id = UnifiedDocument.generate_id(title, url, published)

            return UnifiedDocument(
                id=doc_id,
                source_type=SourceType.NEWS,
                source_name="mining_com",
                language=Language.EN,
                title=title,
                content=content,
                summary=summary,
                url=url,
                published_at=published,
                metadata={
                    "author": author,
                    "wp_id": post.get("id", ""),
                },
            )
        except Exception as e:
            logger.debug(f"Failed to parse WP post: {e}")
            return None

    async def _scrape_rss(self) -> list[UnifiedDocument]:
        """RSS 备份方案"""
        import feedparser
        docs = []
        try:
            resp = await self.safe_get(RSS_FEED)
            feed = feedparser.parse(resp.text)

            cutoff = datetime.now(timezone.utc) - timedelta(days=settings.SCRAPE_DAYS_BACK)

            for entry in feed.entries:
                try:
                    title = entry.get("title", "").strip()
                    url = entry.get("link", "")
                    summary = entry.get("summary", "")

                    published = None
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    if not published:
                        continue
                    if published < cutoff:
                        continue

                    content = BeautifulSoup(summary, "html.parser").get_text() if summary else title
                    doc_id = UnifiedDocument.generate_id(title, url, published)

                    docs.append(UnifiedDocument(
                        id=doc_id,
                        source_type=SourceType.NEWS,
                        source_name="mining_com",
                        language=Language.EN,
                        title=title,
                        content=content,
                        summary=BeautifulSoup(summary, "html.parser").get_text()[:500] if summary else "",
                        url=url,
                        published_at=published,
                    ))
                except Exception:
                    continue

        except Exception as e:
            logger.warning(f"RSS fallback failed: {e}")

        return docs
