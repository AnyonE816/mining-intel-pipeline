"""
矿产政策采集器 (v3 — 正确的 URL + Safari 伪装)

数据源 (全部已验证可访问):
  1. 中国稀土集团官网 (regcc.cn) — 集团新闻/行业动态
  2. 澳洲 Critical Minerals Office (industry.gov.au)
  3. 澳洲 Critical Minerals Strategy 2023-2030
  4. IEA Critical Minerals (iea.org) — 作为补充
  5. EU Critical Raw Materials — 作为补充

反爬经验:
  - 澳洲政府网站需要 Safari 级别 User-Agent + Accept 头
  - 中国稀土集团是传统 CMS, 页面渲染在服务端
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from config import settings
from models import UnifiedDocument, SourceType, Language
from pipeline.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# 政策页面配置
POLICY_PAGES = [
    # (URL, source_name, country, page_type, max_pages)
    # regcc.cn list pages with pagination
    ("https://www.regcc.cn/zgxtjt/jtnew/list.shtml", "regcc_cn", "china", "list", 2),
    ("https://www.regcc.cn/zgxtjt/cydt/list.shtml", "regcc_cn", "china", "list", 1),
    # Australian government pages
    ("https://www.industry.gov.au/mining-oil-and-gas/minerals/critical-minerals/critical-minerals-office", "disr_au", "australia", "content", 1),
    ("https://www.industry.gov.au/publications/critical-minerals-strategy-2023-2030", "disr_au", "australia", "content", 1),
    # International policy pages
    ("https://www.iea.org/topics/critical-minerals", "iea_org", "global", "content", 1),
    ("https://single-market-economy.ec.europa.eu/sectors/raw-materials/areas-specific-interest/critical-raw-materials_en", "eu_commission", "europe", "content", 1),
]


SAFARI_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15"


class PolicyScraper(BaseScraper):
    source_name = "policy"
    source_type = SourceType.POLICY

    async def safe_get_au(self, url: str) -> httpx.Response:
        """澳洲政府站专用: 强制 Safari UA，避免被拒"""
        import httpx as _httpx
        await self._ensure_client()
        await asyncio.sleep(settings.SCRAPE_DELAY)
        for attempt in range(3):
            try:
                resp = await self.client.get(url, headers={
                    "User-Agent": SAFARI_UA,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                })
                resp.raise_for_status()
                return resp
            except Exception as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(5 * (attempt + 1))
        raise RuntimeError("unreachable")

    async def scrape(self) -> list[UnifiedDocument]:
        if settings.MOCK_MODE:
            return self._load_mock()

        docs = []

        for url, source_name, country, page_type, max_pages in POLICY_PAGES:
            try:
                if page_type == "list":
                    page_docs = await self._scrape_list_page(url, source_name, country, max_pages)
                else:
                    # 澳洲政府站用 Safari UA + 重试
                    if "industry.gov.au" in url:
                        page_docs = await self._scrape_content_page_au(url, source_name, country)
                    else:
                        page_docs = await self._scrape_content_page(url, source_name, country)
                docs.extend(page_docs)
                logger.info(f"{source_name} ({url.split('/')[-1][:30]}): {len(page_docs)} items")
            except Exception as e:
                logger.warning(f"{source_name} ({url[:60]}) failed: {e}")

        # Unique IDs
        for i, doc in enumerate(docs):
            doc.id = UnifiedDocument.generate_id(doc.title, doc.url + str(i), doc.published_at)

        self._save_raw(docs)
        return docs

    async def _scrape_list_page(self, url: str, source_name: str, country: str, max_pages: int = 1) -> list[UnifiedDocument]:
        """
        爬取列表页 (如 regcc.cn 的新闻列表)

        regcc.cn 结构: 每个新闻项是 <a href="...shtml"> 包含标题和日期
        链接格式: /zgxtjt/jtnew/202606/42211...shtml
        """
        docs = []
        now = datetime.now(timezone.utc)
        seen = set()
        cutoff = now - timedelta(days=settings.SCRAPE_DAYS_BACK)

        # Paginate through list pages
        for page_num in range(1, max_pages + 1):
            if page_num == 1:
                page_url = url
            else:
                # regcc.cn pattern: list.shtml → list_2.shtml → list_3.shtml
                base = url.rsplit(".", 1)[0] if "." in url else url
                ext = url.rsplit(".", 1)[1] if "." in url else "shtml"
                page_url = f"{base}_{page_num}.{ext}"

            try:
                resp = await self.safe_get(page_url)
            except Exception:
                continue  # Skip failed pages, try next

            soup = BeautifulSoup(resp.text, "lxml")

            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                title = a_tag.get_text(strip=True)

                if not re.search(r"(jtnew|cydt|gzdt|qydt)/\d{6}/", href):
                    continue
                if len(title) < 10:
                    continue

                full_url = urljoin(page_url, href)
                if full_url in seen:
                    continue
                seen.add(full_url)

                # Extract date from href: .../202606/...
                date_match = re.search(r"/(\d{4})(\d{2})/", href)
                pub_date = now
                if date_match:
                    try:
                        pub_date = datetime(int(date_match.group(1)), int(date_match.group(2)), 1, tzinfo=timezone.utc)
                    except ValueError:
                        pass

                # Filter: only within SCRAPE_DAYS_BACK
                if pub_date < cutoff:
                    continue

                content = await self._fetch_article_text(full_url) if "regcc" in source_name else title

                docs.append(UnifiedDocument(
                    id="",
                    source_type=SourceType.POLICY,
                    source_name=source_name,
                    language=Language.ZH if "cn" in source_name else Language.EN,
                    title=title,
                    content=content or title,
                    url=full_url,
                    published_at=pub_date,
                    metadata={"country": country},
                ))

        # 如果列表页拿不到足够条目，用页面可见文本补充
        if len(docs) < 5:
            main_text = soup.get_text(separator="\n", strip=True)
            main_text = re.sub(r"\n{3,}", "\n\n", main_text)
            paragraphs = [p.strip() for p in main_text.split("\n\n") if len(p.strip()) > 60]
            for i, para in enumerate(paragraphs):
                docs.append(UnifiedDocument(
                    id="",
                    source_type=SourceType.POLICY,
                    source_name=source_name,
                    language=Language.ZH if "cn" in source_name else Language.EN,
                    title=f"[{source_name}] {para.split('。')[0][:100]}",
                    content=para[:3000],
                    url=f"{url}#p{i}",
                    published_at=now,
                    metadata={"country": country},
                ))

        return docs

    async def _scrape_content_page_au(self, url: str, source_name: str, country: str) -> list[UnifiedDocument]:
        """澳洲政府站专用 — Safari UA + 3次重试"""
        resp = await self.safe_get_au(url)
        return self._parse_content_html(resp.text, url, source_name, country)

    async def _scrape_content_page(self, url: str, source_name: str, country: str) -> list[UnifiedDocument]:
        resp = await self.safe_get(url)
        return self._parse_content_html(resp.text, url, source_name, country)

    def _parse_content_html(self, html: str, url: str, source_name: str, country: str) -> list[UnifiedDocument]:
        """
        解析内容页 HTML — 针对 Drupal CMS 结构优化
        """
        soup = BeautifulSoup(html, "lxml")
        docs = []
        now = datetime.now(timezone.utc)
        seen = set()

        for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # 多种选择器, 覆盖不同 CMS 结构
        selectors = [
            ".field__item", ".field-item", "[class*=field__item]",
            "[class*=text--content]", "[class*=text-long]", "[class*=body]",
            "[class*=card]", "[class*=callout]", "[class*=panel]",
        ]

        for selector in selectors:
            for el in soup.select(selector):
                if el.name in ("script", "style"):
                    continue
                text = el.get_text(separator=" ", strip=True)
                if len(text) < 100:
                    continue
                # 去重
                key = text[:80]
                if key in seen:
                    continue
                seen.add(key)

                # 用前 150 字符作标题
                title = text.split(".")[0][:150].strip()
                if len(title) < 10:
                    title = text[:150].strip()

                docs.append(UnifiedDocument(
                    id="",
                    source_type=SourceType.POLICY,
                    source_name=source_name,
                    language=Language.EN,
                    title=f"[{source_name}] {title}",
                    content=text[:3000],
                    url=f"{url}#{len(docs)}",
                    published_at=now,
                    metadata={"country": country},
                ))

        # 兜底: 按段落切分
        if len(docs) < 10:
            main = soup.find("main") or soup.find("article") or soup.find("body") or soup
            text = main.get_text(separator="\n", strip=True)
            text = re.sub(r"\n{3,}", "\n\n", text)
            paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 80]
            for i, para in enumerate(paragraphs):
                title = para.split(".")[0][:150].strip()
                if len(title) < 10:
                    title = para[:150].strip()
                key = title[:80]
                if key in seen:
                    continue
                seen.add(key)
                docs.append(UnifiedDocument(
                    id="",
                    source_type=SourceType.POLICY,
                    source_name=source_name,
                    language=Language.EN,
                    title=f"[{source_name}] {title}",
                    content=para[:3000],
                    url=f"{url}#p{i}",
                    published_at=now,
                    metadata={"country": country},
                ))

        return docs

    async def _fetch_article_text(self, url: str) -> str:
        """爬取 regcc.cn 文章详情页正文"""
        try:
            resp = await self.safe_get(url)
            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup.find_all(["script", "style", "nav"]):
                tag.decompose()
            main = soup.find("main") or soup.find("article") or soup.find("body") or soup
            text = main.get_text(separator="\n", strip=True)
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text[:3000]
        except Exception:
            return ""
