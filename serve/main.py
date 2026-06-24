"""
FastAPI 服务 — 矿业情报查询接口

启动: uvicorn serve.main:app --host 0.0.0.0 --port 8000 --reload
文档: http://localhost:8000/docs
"""

import logging
import sys
from pathlib import Path

# 确保项目根在 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from models import QueryRequest, QueryResponse, StatsResponse, HealthResponse, SourceInfo
from serve.rag_chain import RAGChain

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("serve")

# ── FastAPI App ────────────────────────────────────────────

app = FastAPI(
    title="矿业智能情报聚合管线",
    description="Mining Intelligence Aggregation Pipeline — 自然语言查询矿业新闻/政策/价格",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局 RAG Chain (懒加载)
_rag_chain: RAGChain | None = None


def get_rag() -> RAGChain:
    global _rag_chain
    if _rag_chain is None:
        logger.info("Initializing RAG chain...")
        _rag_chain = RAGChain()
    return _rag_chain


# ── Routes ─────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
async def health():
    """健康检查"""
    try:
        rag = get_rag()
        stats = rag.vector_store.get_stats()
        return HealthResponse(
            status="ok",
            vectorstore=f"connected ({stats['total_chunks']} chunks)",
        )
    except Exception as e:
        return HealthResponse(status="degraded", vectorstore=str(e))


@app.get("/stats", response_model=StatsResponse)
async def stats():
    """数据统计"""
    rag = get_rag()
    s = rag.vector_store.get_stats()

    return StatsResponse(
        total_documents=s["total_chunks"],
        by_source=s["by_source"],
        by_source_name=s["by_source_name"],
        date_range=s["date_range"],
        last_updated=s["date_range"]["latest"],
    )


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    """
    自然语言查询矿业情报

    🟡 下方 Responses 区域是返回格式说明，不是报错

    示例请求:
    ```json
    {
        "question": "近7天澳洲锂出口政策有何变化？",
        "top_k": 5,
        "source_filter": "policy",
        "date_from": "2026-06-16",
        "date_to": "2026-06-23"
    }
    ```
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question is required")

    rag = get_rag()

    result = rag.query(
        question=req.question.strip(),
        top_k=req.top_k,
        source_filter=req.source_filter,
        date_from=req.date_from,
        date_to=req.date_to,
    )

    sources = [
        SourceInfo(
            title=s["title"],
            url=s["url"],
            source_name=s["source_name"],
            source_type=s["source_type"],
            published_at=s["published_at"],
            relevance_score=s["relevance_score"],
            chunk_preview=s["chunk_preview"],
        )
        for s in result["sources"]
    ]

    return QueryResponse(
        answer=result["answer"],
        sources=sources,
        query_time_ms=result["query_time_ms"],
        total_docs_searched=result["total_docs_searched"],
    )


# ── 启动入口 ───────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("serve.main:app", host="0.0.0.0", port=8000, reload=True)
