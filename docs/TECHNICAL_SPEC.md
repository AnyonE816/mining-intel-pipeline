# 矿业智能情报聚合管线 — 技术规格文档

> **项目名称:** mining-intel-pipeline  
> **面试公司:** 凌天智矿（杭州）科技有限公司  
> **面试题目:** 题 #1 — 24h 搭一个矿业新闻 + 政策 + 价格三源聚合管线  
> **创建日期:** 2026-06-23  
> **目标时间:** 3 小时内完成基本雏形 → 可运行全链路  
>
> **阅读指南:** 本文档旨在让任何一个 AI 编程助手（或新加入的开发者）在不依赖对话上下文的情况下，完整理解本项目要做什么、怎么做、以及当前进展。每次重大变更后应更新本文档。

---

## 目录

1. [项目概述](#1-项目概述)
2. [需求原文](#2-需求原文)
3. [系统架构](#3-系统架构)
4. [数据源与爬取策略](#4-数据源与爬取策略)
5. [数据 Schema 设计](#5-数据-schema-设计)
6. [组件详解](#6-组件详解)
7. [API 接口设计](#7-api-接口设计)
8. [评测框架设计](#8-评测框架设计)
9. [技术栈与依赖](#9-技术栈与依赖)
10. [文件结构地图](#10-文件结构地图)
11. [分步实施计划](#11-分步实施计划)
12. [环境搭建指南](#12-环境搭建指南)
13. [运行指南](#13-运行指南)
14. [风险与退路](#14-风险与退路)
15. [关键决策记录](#15-关键决策记录)

---

## 1. 项目概述

### 1.1 一句话描述

构建一个从采集→清洗→向量化→RAG查询的**矿业信息聚合管线**，用户可以用自然语言提问（如"近7天澳洲锂出口政策有何变化？"），系统从向量数据库中检索最相关的矿业新闻/政策/价格信息并生成回答。

### 1.2 核心目标

| 目标 | 指标 |
|------|------|
| 三源数据采集 | 每个源 ≥30天、≥200条，合计 ≥600条 |
| 向量库入库 | 全量数据 embedding + ChromaDB 持久化 |
| 自然语言查询 | `/query` REST 接口，支持中文自然语言 |
| 自动化评测 | 20条 ground truth Q&A，自动计算 recall@5 + faithfulness |

### 1.3 业务价值（为什么矿业公司需要这个）

- 矿业决策依赖分散在新闻、政策文件、价格行情中的信息
- 传统方式需要人工跨多个平台搜索，效率低、易遗漏
- RAG 方案可以将异构信息统一检索，用自然语言直接提问
- 这是"AI + 矿业"最基础的落地场景，验证候选人的全栈AI工程能力

---

## 2. 需求原文

```
题 #1 · 主题 24h 搭一个矿业新闻 + 政策 + 价格三源聚合管线

你将从下列 3 个数据源采集数据，每个源至少近 30 天 200 条 (合计 ≥600 条)，
入向量库，提供一个 /query REST 接口可自然语言提问:

#1 矿业新闻 — mining.com / S&P Global Mining (RSS 都给)
    难点: 全文需爬 + 结构化抽取
#2 关键矿产政策 — 中国稀土集团官网 / 澳洲 DISR Critical Minerals Strategy
    难点: 反爬中等 + HTML 结构不规整
#3 价格 — LME 铜锌镍 + SHFE 锂 + 上海钢联铁矿石
    难点: 登录墙 / 接口频控

交付清单:
  • pipeline/    — 采集 + 清洗 + 去重 + 入库
  • serve/       — FastAPI /query 接口, 支持自然语言
  • eval/        — 20 条 ground truth Q&A, 自动跑 recall@5 + answer faithfulness
  • DATA_NOTES.md — 描述 schema, 字段, 主键, 去重策略
```

---

## 3. 系统架构

### 3.1 架构全景图 (ASCII)

```
┌─────────────────────────────────────────────────────────────┐
│                    数据采集层 (Scrapers)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ mining.com   │  │ 中国稀土集团  │  │ LME / SHFE   │       │
│  │ S&P Global   │  │ 澳洲 DISR    │  │ 上海钢联     │       │
│  │ (RSS + 爬虫) │  │ (HTML 爬虫)  │  │ (API + 爬虫) │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                 │                 │                │
│         └─────────────────┼─────────────────┘                │
│                           ▼                                  │
├─────────────────────────────────────────────────────────────┤
│                    清洗与标准化层 (Cleaners)                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  • HTML 标签清洗  • 文本截断规范化  • 日期统一格式    │   │
│  │  • 空字段填充      • 来源标记          • 语言检测     │   │
│  └──────────────────────────┬───────────────────────────┘   │
│                             ▼                                │
├─────────────────────────────────────────────────────────────┤
│                    去重层 (Dedup)                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  • URL 精确去重    • 标题相似度去重 (difflib >0.85)   │   │
│  │  • 内容 MD5 去重   • 同源同日期去重                    │   │
│  └──────────────────────────┬───────────────────────────┘   │
│                             ▼                                │
├─────────────────────────────────────────────────────────────┤
│                    向量化与存储层 (VectorDB)                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  • text → embedding (sentence-transformers)           │   │
│  │  • ChromaDB 持久化 (chunk_size=500, overlap=50)       │   │
│  │  • metadata: source, date, category, url, title       │   │
│  └──────────────────────────┬───────────────────────────┘   │
│                             ▼                                │
├─────────────────────────────────────────────────────────────┤
│                    服务层 (Serve)                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  FastAPI + LangChain RAG Chain                         │   │
│  │  POST /query  {"question": "...", "top_k": 5}          │   │
│  │  → Retrieve → Rerank → Generate (with citations)      │   │
│  └──────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                    评测层 (Eval)                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  20 ground truth Q&A → 自动跑 recall@5                │   │
│  │  faithfulness 评分 (LLM as judge)                      │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 数据流向

```
原始网页/API → Scraper → raw JSONL → Cleaner → clean JSONL → Dedup → deduped JSONL
                                                                              ↓
用户提问 → /query API → Embedding → ChromaDB 检索 ←────────────── VectorStore.add()
                                ↓
                         LangChain RAG Chain
                                ↓
                         生成的回答 + 引用来源
```

---

## 4. 数据源与爬取策略

### 4.1 数据源详细分析

#### 源 1: 矿业新闻 (目标 ≥200条)

| 属性 | 说明 |
|------|------|
| **主源** | mining.com — 有 RSS 源，英文内容 |
| **备用源** | S&P Global Mining — RSS 可用，部分付费 |
| **爬取方式** | RSS 解析 + 全文爬取 |
| **难点** | 全文需要在文章页面二次爬取；部分内容可能付费墙 |
| **RSS 地址** | `https://www.mining.com/feed/` |
| **数据结构** | 标题、发布时间、作者、分类、正文全文、URL |

**爬取策略:**
1. 先用 `feedparser` 解析 RSS，拿到最近 30 天的文章列表（标题 + 摘要 + URL + 日期）
2. 对每篇文章 URL，用 `httpx` + `BeautifulSoup` 爬取全文
3. 目标 200 条 → RSS 通常每天 20-30 条，30 天足够
4. 备选：如果 mining.com 不够，补充 miningweekly.com 或 spglobal.com

#### 源 2: 关键矿产政策 (目标 ≥200条)

| 属性 | 说明 |
|------|------|
| **主源** | 澳洲 DISR Critical Minerals Strategy 页面 |
| **备用源** | 中国稀土集团官网新闻 |
| **爬取方式** | HTML 页面爬取 + 结构化解析 |
| **难点** | HTML 结构不规整，反爬中等 |
| **URL** | `https://www.industry.gov.au/publications/australias-critical-minerals-list-and-strategic-materials-list` |
| **备用URL** | 中国稀土集团 `http://www.creg.com.cn/` |

**爬取策略:**
1. DISR 是澳洲政府网站，反爬较弱，优先攻克
2. 中国稀土集团官网可能有反爬，需要 User-Agent 伪装 + 请求间隔
3. 政策类内容通常更新频率低，可扩展到相关政府公告、行业报告
4. 备选：USGS Critical Minerals、IEA Critical Minerals 报告

#### 源 3: 价格行情 (目标 ≥200条)

| 属性 | 说明 |
|------|------|
| **主源** | LME (London Metal Exchange) 铜/锌/镍 |
| **第二源** | SHFE (上海期货交易所) 锂 |
| **第三源** | 上海钢联 铁矿石 |
| **爬取方式** | API 优先，爬虫兜底 |
| **难点** | LME 有登录墙，SHFE 有频控，上海钢联可能需付费 |

**爬取策略:**
1. **LME:** 尝试公开的延迟数据 API / 第三方聚合站点 (investing.com, tradingeconomics.com)
2. **SHFE:** 尝试公开行情接口或第三方数据
3. **上海钢联:** 最难攻克，可能需要模拟登录。**退路方案：** 使用 Yahoo Finance 或 investing.com 的 commodity prices 作为替代
4. 价格数据每天一条即可，30天 3-5 个品种 = 90-150 条。需补充历史价格使每条成为一个独立记录，凑满 200 条
5. **重要退路:** 如果所有价格源都有登录墙，使用 `yfinance` 库获取相关期货 ETF 价格作为代理指标，并明确标注在 DATA_NOTES.md 中

### 4.2 反爬应对工具箱

```
优先级从高到低:
1. User-Agent 轮换 (模拟正常浏览器)
2. 请求间隔 1-3 秒 (asyncio.sleep)
3. Referer 头设置
4. Cookie 持久化 (requests.Session)
5. 如果被封 → 切换为静态 HTML 文件开发 (mock 模式)，管线代码照写
```

---

## 5. 数据 Schema 设计

### 5.1 统一文档模型 (UnifiedDocument)

```python
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

class SourceType(str, Enum):
    NEWS = "news"           # 矿业新闻
    POLICY = "policy"       # 政策文件
    PRICE = "price"         # 价格行情

class Language(str, Enum):
    ZH = "zh"
    EN = "en"

class UnifiedDocument(BaseModel):
    """所有数据源清洗后的统一 Schema"""
    id: str                          # 主键: md5(url + title + date)
    source_type: SourceType          # news | policy | price
    source_name: str                 # "mining.com" | "disr_au" | "lme" | "shfe" 等
    language: Language               # zh | en
    title: str                       # 标题
    content: str                     # 正文/内容 (用于 embedding 的主文本)
    summary: str = ""                # 摘要 (RSS 有则填)
    url: str                         # 原始 URL
    published_at: datetime           # 发布时间
    ingested_at: datetime            # 入库时间
    metadata: dict = {}              # 扩展字段 (价格数据: commodity/price/unit; 政策: country/region)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
```

### 5.2 价格数据扩展 Schema

```python
class PriceMetadata(BaseModel):
    commodity: str        # "copper" | "zinc" | "nickel" | "lithium" | "iron_ore"
    price: float          # 价格数值
    unit: str             # "USD/tonne" | "CNY/tonne" | "USD/lb"
    change_pct: float = 0 # 涨跌幅百分比
    exchange: str         # "LME" | "SHFE" | "SHANGHAI_STEEL"
```

### 5.3 去重主键策略

```python
# 主键生成逻辑
import hashlib

def generate_doc_id(title: str, url: str, published_at: str) -> str:
    """组合键: URL + 标题前50字符 + 日期 → MD5"""
    raw = f"{url}|{title[:50]}|{published_at}"
    return hashlib.md5(raw.encode()).hexdigest()
```

去重判断优先级:
1. **URL 精确匹配** → 直接去重 (最强)
2. **标题相似度 > 0.85** (difflib.SequenceMatcher) + 同日期 → 去重
3. **内容 MD5** → 完全一致的正文去重

### 5.4 ChromaDB Chunk 设计

```
原始文档 → text splitters:
  - chunk_size: 500 字符
  - chunk_overlap: 50 字符
  - separator: "\n\n" | "\n" | " " | ""

每个 chunk 的 metadata:
  - doc_id: 关联到原始文档
  - source_type: news/policy/price
  - source_name: 具体来源
  - published_at: 发布日期 (用于时间范围过滤)
  - title: 原始标题
  - url: 原始链接 (用于引用)
  - chunk_index: 第几个 chunk
```

---

## 6. 组件详解

### 6.1 Scrapers (pipeline/scrapers/)

每个 scraper 实现统一接口:

```python
from abc import ABC, abstractmethod
from typing import List, AsyncIterator
from models import UnifiedDocument

class BaseScraper(ABC):
    source_name: str
    source_type: SourceType
    
    @abstractmethod
    async def scrape(self) -> List[UnifiedDocument]:
        """采集数据, 返回未清洗的文档列表"""
        ...
```

#### 6.1.1 MiningDotComScraper (源1: 矿业新闻)
- **技术:** `feedparser` + `httpx` + `BeautifulSoup`
- **流程:** RSS 列表 → 过滤近30天 → 逐篇爬全文 → 结构化提取
- **速率:** 每次请求间隔 1s，并发 3
- **输出:** `data/raw/news_mining_com.jsonl`

#### 6.1.2 PolicyScraper (源2: 矿产政策)
- **技术:** `httpx` + `BeautifulSoup` + CSS Selector
- **主攻:** 澳洲 DISR 页面 → 解析政策列表 → 逐篇爬取
- **备份:** 中国稀土集团 → requests + BeautifulSoup
- **输出:** `data/raw/policy_*.jsonl`

#### 6.1.3 PriceScraper (源3: 价格行情)
- **技术:** `httpx` (公开API) / `yfinance` (备选) / `akshare` (中国数据备选)
- **流程:** 尝试 LME 公开数据 → 尝试 SHFE → 降级到第三方
- **输出:** `data/raw/price_*.jsonl`

### 6.2 Cleaners (pipeline/cleaners/)

```python
class DocumentCleaner:
    @staticmethod
    def clean_html(html: str) -> str:
        """去除 HTML 标签, 保留段落结构"""
        ...
    
    @staticmethod
    def normalize_date(date_str: str) -> datetime:
        """统一日期格式 → ISO 8601"""
        ...
    
    @staticmethod
    def detect_language(text: str) -> str:
        """检测文本语言 zh/en"""
        ...
    
    @staticmethod
    def clean(doc: UnifiedDocument) -> UnifiedDocument:
        """主清洗入口"""
        ...
```

### 6.3 Dedup (pipeline/dedup/)

```python
class Deduplicator:
    def __init__(self, title_threshold: float = 0.85):
        self.seen_urls: set = set()
        self.seen_content_md5: set = set()
        self.title_threshold = title_threshold
    
    def is_duplicate(self, doc: UnifiedDocument, existing: list[UnifiedDocument]) -> bool:
        """三重去重: URL / 标题相似度 / 内容MD5"""
        ...
```

### 6.4 VectorDB (pipeline/vectordb/)

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings

class VectorStoreManager:
    def __init__(self, persist_dir: str = "data/chroma_db"):
        self.embeddings = HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-zh-v1.5"  # 中英双语 embedding
        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
        )
        self.vectorstore = Chroma(
            persist_directory=persist_dir,
            embedding_function=self.embeddings,
        )
    
    def add_documents(self, docs: list[UnifiedDocument]):
        ...
    
    def search(self, query: str, top_k: int = 5, filters: dict = None):
        ...
```

**Embedding 模型选择:**
- 默认: `BAAI/bge-small-zh-v1.5` (中英双语，轻量快速)
- 备选: `sentence-transformers/all-MiniLM-L6-v2` (纯英文场景)
- 生产备选: OpenAI `text-embedding-3-small` (需要 API key)

### 6.5 RAG Chain (serve/)

```python
from langchain.chains import RetrievalQA
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate

# 提示词模板 (中英双语支持)
PROMPT_TEMPLATE = """你是一个矿业情报分析助手。根据以下检索到的信息回答用户问题。

检索到的相关信息:
{context}

用户问题: {question}

回答要求:
1. 基于检索到的信息回答，不要编造
2. 如果信息不足以回答，明确说明
3. 引用信息来源 (标注 source 和 date)
4. 使用中文回答

回答:"""
```

### 6.6 FastAPI 服务

```python
# POST /query
# Request: {"question": "近7天澳洲锂出口政策有何变化?", "top_k": 5}
# Response: {
#   "answer": "根据检索到的信息...",
#   "sources": [{"title": "...", "url": "...", "date": "...", "relevance": 0.92}],
#   "query_time_ms": 234
# }
```

---

## 7. API 接口设计

### 7.1 `/query` — 自然语言查询

```
POST /query
Content-Type: application/json

Request:
{
    "question": "近7天澳洲锂出口政策有何变化?",
    "top_k": 5,
    "source_filter": null,        // 可选: "news" | "policy" | "price"
    "date_from": null,             // 可选: "2026-06-01"
    "date_to": null                // 可选: "2026-06-23"
}

Response 200:
{
    "answer": "根据澳洲DISR 6月15日发布的公告，澳洲政府正在审查锂矿出口许可框架...",
    "sources": [
        {
            "title": "Australia reviews lithium export framework",
            "url": "https://www.industry.gov.au/...",
            "source_name": "disr_au",
            "published_at": "2026-06-15T10:30:00Z",
            "relevance_score": 0.92,
            "chunk_preview": "..."
        }
    ],
    "query_time_ms": 234,
    "total_docs_searched": 650
}

Response 400:
{
    "error": "question is required and must be non-empty"
}
```

### 7.2 `/stats` — 数据统计

```
GET /stats

Response 200:
{
    "total_documents": 650,
    "by_source": {
        "news": 220,
        "policy": 210,
        "price": 220
    },
    "by_source_name": {
        "mining_com": 200,
        "sp_global": 20,
        "disr_au": 150,
        "creg_cn": 60,
        "lme": 90,
        "shfe": 80,
        "shanghai_steel": 50
    },
    "date_range": {
        "earliest": "2026-05-24",
        "latest": "2026-06-23"
    },
    "last_updated": "2026-06-23T18:00:00Z"
}
```

### 7.3 `/health` — 健康检查

```
GET /health
Response 200: {"status": "ok", "vectorstore": "connected"}
```

---

## 8. 评测框架设计

### 8.1 Ground Truth 格式

```json
{
    "id": "gt_001",
    "question": "近7天铜价走势如何？",
    "expected_answer_keywords": ["铜", "LME", "上涨", "下跌", "美元"],
    "relevant_doc_ids": ["abc123", "def456"],
    "source_type_filter": "price",
    "date_range_days": 7
}
```

### 8.2 评测指标

**recall@5:** 在 top-5 检索结果中，是否包含至少一个 `relevant_doc_ids` 中的文档。

```python
def recall_at_k(retrieved_doc_ids: list[str], relevant_doc_ids: list[str], k: int = 5) -> float:
    retrieved_k = set(retrieved_doc_ids[:k])
    relevant = set(relevant_doc_ids)
    hits = len(retrieved_k & relevant)
    return 1.0 if hits > 0 else 0.0
# 对 20 条 ground truth 取平均
```

**Answer Faithfulness (LLM as Judge):**
```python
# 用另一个 LLM 调用判断生成的 answer 是否忠实于检索到的 context
# 评分 1-5: 1=完全编造, 5=完全基于context
def evaluate_faithfulness(answer: str, contexts: list[str]) -> float:
    prompt = f"""判断以下 answer 是否忠实于提供的 context。

Context:
{chr(10).join(contexts)}

Answer:
{answer}

请给出 1-5 的评分，1=完全编造，5=完全基于context。只输出数字。"""
    # 调用 LLM 获取评分
    ...
```

### 8.3 评测运行方式

```bash
python eval/run_eval.py
# 输出:
# recall@5: 0.85 (17/20)
# avg_faithfulness: 4.2/5.0
# per_question_detail: eval/results.json
```

---

## 9. 技术栈与依赖

### 9.1 核心依赖

| 包名 | 版本 | 用途 |
|------|------|------|
| `python` | ≥3.11 | 运行时 |
| `fastapi` | ≥0.110 | Web 框架 |
| `uvicorn` | ≥0.27 | ASGI 服务器 |
| `langchain` | ≥0.2 | RAG 编排 |
| `langchain-community` | ≥0.2 | Chroma 集成 |
| `chromadb` | ≥0.5 | 向量数据库 |
| `sentence-transformers` | ≥2.7 | 本地 embedding |
| `httpx` | ≥0.27 | 异步 HTTP 客户端 |
| `beautifulsoup4` | ≥4.12 | HTML 解析 |
| `lxml` | ≥5.0 | HTML 解析加速 |
| `feedparser` | ≥6.0 | RSS 解析 |
| `pydantic` | ≥2.0 | 数据校验 |
| `pydantic-settings` | ≥2.0 | 配置管理 |

### 9.2 可选依赖

| 包名 | 用途 | 何时安装 |
|------|------|----------|
| `langchain-openai` | OpenAI LLM | 有 API key 时 |
| `yfinance` | 期货价格备选 | 价格源主方案失败时 |
| `akshare` | 中国金融数据 | 上海钢联数据备选 |
| `openai` | embedding/text-gen | 有 API key 时 |
| `pytest` | 测试 | 开发时 |

### 9.3 LLM 配置

```
默认方案:
  - Embedding: BAAI/bge-small-zh-v1.5 (本地, 免费)
  - Text Generation: DeepSeek API (用户已有) 或本地模型

备选方案:
  - Embedding: OpenAI text-embedding-3-small
  - Text Generation: OpenAI GPT-4o-mini
```

---

## 10. 文件结构地图

```
mining-intel-pipeline/
│
├── docs/
│   └── TECHNICAL_SPEC.md          # ← 本文档 (需求+架构+计划)
│
├── pipeline/                       # 数据管线
│   ├── __init__.py
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── base.py                # BaseScraper 抽象类
│   │   ├── mining_news.py         # mining.com RSS + 全文爬取
│   │   ├── policy.py              # DISR + 中国稀土集团
│   │   └── price.py              # LME + SHFE + 上海钢联
│   ├── cleaners/
│   │   ├── __init__.py
│   │   └── cleaner.py             # HTML清洗 + 日期标准化 + 语言检测
│   ├── dedup/
│   │   ├── __init__.py
│   │   └── deduplicator.py        # URL/相似度/MD5 三重去重
│   ├── vectordb/
│   │   ├── __init__.py
│   │   └── store.py               # ChromaDB 管理 + embedding
│   └── runner.py                  # 一键运行全管线
│
├── serve/                          # API 服务
│   ├── __init__.py
│   ├── main.py                    # FastAPI app + /query /stats /health
│   ├── rag_chain.py               # LangChain RAG chain
│   └── prompts.py                 # 提示词模板
│
├── eval/                           # 评测
│   ├── __init__.py
│   ├── ground_truth.json          # 20 条 ground truth Q&A
│   ├── metrics.py                 # recall@k + faithfulness 计算
│   └── run_eval.py                # 评测入口
│
├── data/                           # 数据目录 (gitignore)
│   ├── raw/                        # 原始采集数据 (JSONL)
│   ├── processed/                  # 清洗去重后数据 (JSONL)
│   └── chroma_db/                  # ChromaDB 持久化目录
│
├── config.py                       # 全局配置 (Pydantic Settings)
├── models.py                       # 数据模型 (Pydantic)
├── requirements.txt                # Python 依赖
├── DATA_NOTES.md                   # Schema + 字段 + 主键 + 去重策略说明
├── README.md                       # 项目 README (快速开始)
└── .env.example                    # 环境变量模板
```

---

## 11. 分步实施计划

### 总时间预算: 3小时

### Phase 1: 基础设施 (15 min) ⬜
```
□ 创建项目结构, requirements.txt
□ 配置 Pydantic Settings (config.py)
□ 实现数据模型 (models.py)
□ 安装依赖 (pip install -r requirements.txt)
```

### Phase 2: 数据采集 (45 min) ⬜
```
□ MiningNewsScraper — mining.com RSS + 全文 (20 min)
□ PolicyScraper — 澳洲 DISR + 中国稀土集团 (15 min)
□ PriceScraper — LME + SHFE + 上海钢联 (10 min)
□ 三个 scraper 测试运行，确认能拿到数据
```

### Phase 3: 清洗+去重 (20 min) ⬜
```
□ DocumentCleaner 实现
□ Deduplicator 实现
□ 全量数据走通清洗→去重→输出 JSONL
```

### Phase 4: 向量库入库 (20 min) ⬜
```
□ VectorStoreManager 实现
□ embedding 模型下载 & 加载
□ 全量数据 chunk → embedding → ChromaDB
□ 验证: 手动测试 search 返回结果
```

### Phase 5: API 服务 (30 min) ⬜
```
□ LangChain RAG Chain 实现
□ FastAPI /query /stats /health 路由
□ uvicorn 启动测试
□ 手动测试 3-5 个自然语言问题
```

### Phase 6: 评测框架 (30 min) ⬜
```
□ 编写 20 条 ground truth (覆盖三源 + 混合问题)
□ recall@5 自动计算
□ faithfulness 评分实现
□ 跑通评测并输出报告
```

### Phase 7: 文档 + 收尾 (20 min) ⬜
```
□ DATA_NOTES.md 编写
□ README.md 编写
□ 整体联调，修复发现的问题
□ 最终评测跑分记录
```

---

## 12. 环境搭建指南

### 12.1 快速开始 (5 步)

```bash
# 1. 进入项目目录
cd /Users/zoom/PycharmProjects/mining-intel-pipeline

# 2. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量 (复制模板后编辑)
cp .env.example .env
# 编辑 .env, 填入 LLM API key

# 5. 运行管线
python pipeline/runner.py          # 采集+清洗+入库
python serve/main.py               # 启动 API 服务
python eval/run_eval.py            # 运行评测
```

### 12.2 环境变量 (.env)

```bash
# LLM 配置
LLM_PROVIDER=deepseek              # deepseek | openai | local
LLM_API_KEY=sk-xxxxxxxxxxxx
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com

# Embedding 配置
EMBEDDING_PROVIDER=local           # local | openai
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5

# 数据库
CHROMA_PERSIST_DIR=data/chroma_db

# 采集
SCRAPE_DELAY=1.5                   # 请求间隔(秒)
SCRAPE_MAX_CONCURRENT=3            # 最大并发数
```

---

## 13. 运行指南

### 13.1 分步运行

```bash
# 仅采集数据
python pipeline/runner.py --step scrape

# 仅清洗+去重
python pipeline/runner.py --step clean

# 仅入库
python pipeline/runner.py --step ingest

# 一键全流程
python pipeline/runner.py --all

# 启动 API
uvicorn serve.main:app --host 0.0.0.0 --port 8000 --reload

# API 文档
open http://localhost:8000/docs   # Swagger UI

# 测试查询
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "近7天铜价走势如何？", "top_k": 5}'

# 运行评测
python eval/run_eval.py
```

### 13.2 Mock 模式 (爬虫被墙时的退路)

```bash
# 如果某个数据源爬不下来，使用预置模拟数据:
MOCK_MODE=true python pipeline/runner.py --all
# Mock 数据从 data/mock/ 目录读取
```

---

## 14. 风险与退路

| 风险 | 概率 | 影响 | 退路方案 |
|------|------|------|----------|
| mining.com 反爬加强 | 低 | 中 | 使用 S&P Global RSS 替代；或预先手工采集 |
| LME 登录墙无法突破 | 中 | 中 | 用 yfinance 获取铜/锌/镍 ETF 价格；或 investing.com 爬取 |
| 上海钢联完全需要付费 | 高 | 低 | 用 akshare 获取国内铁矿石期货数据 |
| 中国稀土集团反爬严格 | 中 | 中 | 改用澳洲 DISR + USGS + IEA 公开报告 |
| ChromaDB 初始化慢 | 低 | 低 | 减少 chunk 数量，先用前 300 条 demo |
| embedding 模型下载慢 | 中 | 中 | 预下载模型到本地，或使用 OpenAI embedding API |
| 3 小时内完不成全部 | 中 | — | **核心链路优先**: scrape→clean→ingest→query 通了就算成功，eval 和文档可以后续补充 |

**最重要的底线:** API 能跑通、query 能返回结果，就是成功。评测和文档是加分项。

---

## 15. 关键决策记录

| # | 决策 | 理由 | 日期 |
|---|------|------|------|
| 1 | 选题 #1 | 技术栈与候选人经验最匹配，风险可控，展示面最全面 | 2026-06-23 |
| 2 | 使用本地 embedding (BGE) | 免费、中英双语、无需 API key | 2026-06-23 |
| 3 | ChromaDB 而非 Pinecone/Weaviate | 轻量、本地运行、LangChain 原生集成、无需注册 | 2026-06-23 |
| 4 | DeepSeek 作为默认 LLM | 用户已有 API key，中文能力强，性价比高 | 2026-06-23 |
| 5 | 爬虫失败时使用 MOCK_MODE | 保障管线架构可展示，不因外部因素阻塞 | 2026-06-23 |
| 6 | pipeline/ 文件夹结构 - scrapers/cleaners/dedup/vectordb | 模块职责单一，符合面试展示要求 | 2026-06-23 |

---

> **文档维护:** 每次对架构、数据模型、依赖的变更必须同步更新本文档。  
> **最后更新:** 2026-06-23  
> **项目 Git:** 待初始化
