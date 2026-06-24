"""
数据清洗器 — 将原始采集数据标准化

处理内容:
  - HTML 标签清理 (残留标签/实体)
  - 日期格式统一 → ISO 8601
  - 语言检测 (zh/en)
  - 空字段填充
  - 正文截断规范化 (最大 5000 字符)
  - 标题清理 (去除多余空格/换行)
"""

import logging
import re
from datetime import datetime, timezone

from models import UnifiedDocument, Language

logger = logging.getLogger(__name__)


class DocumentCleaner:
    """文档清洗器 — 将 scraper 产出标准化"""

    HTML_RE = re.compile(r"<[^>]+>")
    ENTITY_RE = re.compile(r"&[a-z]+;|&#\d+;")
    WHITESPACE_RE = re.compile(r"\s+")
    MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

    @classmethod
    def clean(cls, doc: UnifiedDocument) -> UnifiedDocument:
        """主入口: 清洗单条文档"""
        doc.title = cls.clean_title(doc.title)
        doc.content = cls.clean_content(doc.content)
        doc.summary = cls.clean_content(doc.summary)[:500] if doc.summary else ""
        doc.language = cls.detect_language(doc.title, doc.content)

        # 确保日期有时区信息
        if doc.published_at and doc.published_at.tzinfo is None:
            doc.published_at = doc.published_at.replace(tzinfo=timezone.utc)

        return doc

    @classmethod
    def clean_title(cls, title: str) -> str:
        """清理标题"""
        if not title:
            return "(无标题)"
        title = cls.HTML_RE.sub("", title)
        title = cls.ENTITY_RE.sub("", title)
        title = cls.WHITESPACE_RE.sub(" ", title)
        return title.strip()[:300]

    @classmethod
    def clean_content(cls, content: str) -> str:
        """清理正文"""
        if not content:
            return ""

        # 去除 HTML 标签
        content = cls.HTML_RE.sub("", content)
        # 去除 HTML 实体
        content = cls.ENTITY_RE.sub("", content)
        # 规范化空白符
        content = cls.WHITESPACE_RE.sub(" ", content)
        # 规范化换行
        content = cls.MULTI_NEWLINE_RE.sub("\n\n", content)

        return content.strip()[:5000]

    @classmethod
    def detect_language(cls, title: str, content: str) -> Language:
        """检测文本语言 — 基于 Unicode 范围"""
        text = (title + " " + content[:500]).lower()

        # 统计中文字符
        zh_chars = len(re.findall(r"[一-鿿]", text))
        # 统计英文单词 (粗略)
        en_words = len(re.findall(r"[a-zA-Z]+", text))

        if zh_chars > en_words:
            return Language.ZH
        return Language.EN

    @classmethod
    def clean_batch(cls, docs: list[UnifiedDocument]) -> list[UnifiedDocument]:
        """批量清洗, 返回清洗后的文档列表"""
        cleaned = []
        for doc in docs:
            try:
                cleaned.append(cls.clean(doc))
            except Exception as e:
                logger.warning(f"Failed to clean doc {doc.id}: {e}")
        logger.info(f"Cleaned {len(cleaned)}/{len(docs)} documents")
        return cleaned
