"""
数据模型定义 — 所有数据源清洗后的统一 Schema

所有数据结构在此文件中定义, pipeline/ 和 serve/ 均依赖此模块.
修改 Schema 时务必同步更新 docs/TECHNICAL_SPEC.md 第5节.
"""

import hashlib
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── 枚举类型 ──────────────────────────────────────────────


class SourceType(str, Enum):
    NEWS = "news"
    POLICY = "policy"
    PRICE = "price"


class Language(str, Enum):
    ZH = "zh"
    EN = "en"


# ── 统一文档模型 ──────────────────────────────────────────


class UnifiedDocument(BaseModel):
    """所有数据源清洗后的统一 Schema — 这是管线的'通用语言'"""

    id: str = Field(description="主键: md5(url + title[:50] + date)")
    source_type: SourceType = Field(description="news | policy | price")
    source_name: str = Field(description="具体来源名称, 如 mining_com / disr_au / lme")
    language: Language = Field(default=Language.EN, description="文本语言")
    title: str = Field(description="标题")
    content: str = Field(description="正文/内容 — 这是 embedding 的主输入")
    summary: str = Field(default="", description="摘要, RSS 有则填")
    url: str = Field(description="原始 URL")
    published_at: datetime = Field(description="发布时间")
    ingested_at: datetime = Field(default_factory=datetime.now, description="入库时间")
    metadata: dict = Field(default_factory=dict, description="扩展字段")

    @staticmethod
    def generate_id(title: str, url: str, published_at: str | datetime) -> str:
        """生成文档主键: md5(url + 标题前50字符 + 日期)"""
        date_str = str(published_at)[:10]  # 取日期部分
        raw = f"{url}|{title[:50]}|{date_str}"
        return hashlib.md5(raw.encode()).hexdigest()

    def to_chunk_text(self) -> str:
        """组装用于 embedding 的文本: 标题 + 来源 + 日期 + 内容"""
        date_str = self.published_at.strftime("%Y-%m-%d") if self.published_at else ""
        return f"标题: {self.title}\n来源: {self.source_name}\n日期: {date_str}\n\n{self.content}"


# ── 价格数据扩展 ──────────────────────────────────────────


class PriceMetadata(BaseModel):
    """价格类文档的 metadata 扩展字段"""
    commodity: str = Field(description="品种: copper / zinc / nickel / lithium / iron_ore")
    price: float = Field(description="价格数值")
    unit: str = Field(description="单位: USD/tonne / CNY/tonne / USD/lb")
    change_pct: float = Field(default=0.0, description="涨跌幅百分比")
    exchange: str = Field(description="交易所: LME / SHFE / SHANGHAI_STEEL")


# ── API 请求/响应模型 ─────────────────────────────────────


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500, description="自然语言问题")
    top_k: int = Field(default=5, ge=1, le=20, description="返回文档数量")
    source_filter: Optional[SourceType] = Field(default=None, description="可选来源过滤")
    date_from: Optional[str] = Field(default=None, description="起始日期 YYYY-MM-DD")
    date_to: Optional[str] = Field(default=None, description="结束日期 YYYY-MM-DD")


class SourceInfo(BaseModel):
    title: str
    url: str
    source_name: str
    source_type: SourceType
    published_at: str
    relevance_score: float
    chunk_preview: str


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceInfo]
    query_time_ms: float
    total_docs_searched: int


class StatsResponse(BaseModel):
    total_documents: int
    by_source: dict
    by_source_name: dict
    date_range: dict
    last_updated: str


class HealthResponse(BaseModel):
    status: str
    vectorstore: str


# ── Ground Truth 评测模型 ──────────────────────────────────


class GroundTruthItem(BaseModel):
    id: str = Field(description="gt_001 格式")
    question: str
    expected_answer_keywords: list[str] = Field(default_factory=list)
    relevant_doc_ids: list[str] = Field(default_factory=list)
    source_type_filter: Optional[SourceType] = None
    date_range_days: Optional[int] = None
