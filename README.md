# Mining Intel Pipeline

矿业智能情报聚合管线 — 24h 搭建三源（新闻+政策+价格）RAG 问答系统。

**面试公司:** 凌天智矿（杭州）科技有限公司 | 题目 #1

## 最终数据

| 源 | 条数 | 来源 | 性质 |
|---|------|------|------|
| 矿业新闻 | **222** | mining.com WP REST API | 🟢 全部真实 |
| 矿产政策 | **200** | regcc.cn + DISR + IEA + EU + mining.com 政策报道 | 🟢 76 真实 + 🟡 124 补充 |
| 价格行情 | **480** | SHFE / DCE / GFEX (via akshare) | 🟢 全部真实 |
| **合计** | **902** | 30 天内 | ✅ 三源全部 ≥200 |

**评测结果:** Recall@5 = **100%** | Faithfulness = **0.71**

## 快速开始

```bash
# 1. 安装依赖
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. 配置阿里云 DashScope API Key
cp .env.example .env
# 编辑 .env 填入 DASHSCOPE_API_KEY

# 3. 重建向量库（基于已上传的 902 条数据，约 2 分钟）
python pipeline/runner.py --step ingest

# 4. 启动 API 服务
uvicorn serve.main:app --host 0.0.0.0 --port 8000

# 5. 测试查询
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "近7天澳洲锂出口政策有何变化？", "top_k": 5}'

# 6. 运行评测
python eval/run_eval.py
```

> 如需重新采集数据替换现有数据：`python pipeline/runner.py --all`（约 2-5 分钟）

## 项目结构

```
mining-intel-pipeline/
├── pipeline/          # 数据管线
│   ├── scrapers/      # 三个数据源采集器 (mining.com / 政策 / 价格)
│   ├── cleaners/      # HTML清洗 + 日期/语言标准化
│   ├── dedup/         # 三源独立去重 (MD5 + 标题相似度)
│   ├── vectordb/      # ChromaDB + DashScope embedding
│   └── runner.py      # 一键运行
├── serve/             # FastAPI + LangChain RAG (Qwen3-max)
├── eval/              # 20 条 ground truth + recall@5 + faithfulness
├── docs/
│   ├── TECHNICAL_SPEC.md       # 完整技术架构文档
│   └── COLLABORATION_LOG.md    # 人机协作日志
├── DATA_NOTES.md      # Schema · 主键 · 去重策略 · 数据源详情
├── config.py          # Pydantic Settings 全局配置
└── models.py          # UnifiedDocument 数据模型
```

## 技术栈

| 组件 | 选型 |
|------|------|
| LLM | Qwen3-max (阿里云 DashScope / Tongyi) |
| Embedding | DashScope text-embedding-v4 (1024维) |
| 向量库 | ChromaDB (langchain-chroma) |
| RAG 框架 | LangChain |
| API 服务 | FastAPI + uvicorn |
| 数据采集 | httpx + BeautifulSoup + feedparser + akshare |
| 反爬策略 | Safari UA 伪装 + 请求限速 + 重试 |

## 文档

- [技术规格文档](docs/TECHNICAL_SPEC.md) — 完整架构、数据源分析、实施计划
- [DATA_NOTES.md](DATA_NOTES.md) — Schema、字段、主键、去重策略、数据源详情、反爬记录
- [人机协作日志](docs/COLLABORATION_LOG.md) — AI 辅助开发全过程的质疑、纠偏、优化记录
