"""
RAG Chain — 检索增强生成链路

支持 (按优先级):
  - Qwen / Tongyi (DashScope, 默认)
  - DeepSeek API
  - OpenAI API

检索策略: 语义搜索 + 可选来源/日期过滤 → 组装 context → LLM 生成
"""

import logging
import os
import time
from typing import Optional

from langchain_core.prompts import PromptTemplate

from config import settings
from models import SourceType
from pipeline.vectordb.store import VectorStoreManager
from serve.prompts import RAG_QA_PROMPT, RAG_SHORT_PROMPT

logger = logging.getLogger(__name__)


class RAGChain:
    """检索增强生成链路"""

    def __init__(self):
        # 初始化向量库
        self.vector_store = VectorStoreManager()

        # 初始化 LLM (根据 provider 选择)
        if settings.LLM_PROVIDER == "qwen":
            from langchain_community.chat_models.tongyi import ChatTongyi
            api_key = settings.DASHSCOPE_API_KEY or os.getenv("DASHSCOPE_API_KEY", "")
            self.llm = ChatTongyi(
                model=settings.LLM_MODEL,
                dashscope_api_key=api_key,
                temperature=settings.LLM_TEMPERATURE,
            )
        elif settings.LLM_PROVIDER == "deepseek":
            from langchain_openai import ChatOpenAI
            self.llm = ChatOpenAI(
                model=settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL or "https://api.deepseek.com",
                temperature=settings.LLM_TEMPERATURE,
            )
        elif settings.LLM_PROVIDER == "openai":
            from langchain_openai import ChatOpenAI
            self.llm = ChatOpenAI(
                model=settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY,
                temperature=settings.LLM_TEMPERATURE,
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {settings.LLM_PROVIDER}")

        self.qa_prompt = PromptTemplate.from_template(RAG_QA_PROMPT)
        self.short_prompt = PromptTemplate.from_template(RAG_SHORT_PROMPT)

    def query(
        self,
        question: str,
        top_k: int = 5,
        source_filter: Optional[SourceType] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict:
        """
        执行 RAG 查询

        Returns:
            {
                "answer": str,
                "sources": [...],
                "query_time_ms": float,
                "total_docs_searched": int
            }
        """
        t0 = time.time()

        # Step 1: 检索
        results = self.vector_store.search(
            query=question,
            top_k=top_k,
            source_filter=source_filter,
            date_from=date_from,
            date_to=date_to,
        )

        if not results:
            return {
                "answer": "抱歉，未找到与您问题相关的信息。请尝试扩大搜索范围或更换关键词。",
                "sources": [],
                "query_time_ms": (time.time() - t0) * 1000,
                "total_docs_searched": 0,
            }

        # Step 2: 组装 context
        context_parts = []
        for i, r in enumerate(results):
            meta = r["metadata"]
            part = (
                f"[来源 {i+1}] 标题: {meta.get('title', 'N/A')}\n"
                f"来源: {meta.get('source_name', 'N/A')}\n"
                f"日期: {meta.get('published_at', 'N/A')[:10]}\n"
                f"URL: {meta.get('url', 'N/A')}\n"
                f"内容: {r['content']}\n"
            )
            context_parts.append(part)

        context = "\n---\n".join(context_parts)

        # Step 3: 生成
        is_short = len(question) < 20 or any(
            kw in question.lower() for kw in ["价格", "price", "多少钱", "报价"]
        )
        prompt = self.short_prompt if is_short else self.qa_prompt
        formatted_prompt = prompt.format(context=context, question=question)

        try:
            response = self.llm.invoke(formatted_prompt)
            answer = response.content
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            # 降级: 直接返回检索结果
            answer = "（LLM 生成失败，以下为检索到的原始信息）\n\n"
            answer += "\n\n".join(
                f"📰 {r['metadata'].get('title', 'N/A')} ({r['metadata'].get('published_at', 'N/A')[:10]})\n{r['content'][:300]}..."
                for r in results
            )

        # Step 4: 组装结果
        sources = []
        for r in results:
            meta = r["metadata"]
            sources.append({
                "title": meta.get("title", ""),
                "url": meta.get("url", ""),
                "source_name": meta.get("source_name", ""),
                "source_type": meta.get("source_type", ""),
                "published_at": meta.get("published_at", ""),
                "relevance_score": round(1.0 / (1.0 + r["score"]), 4),  # 转换为 0-1 相似度
                "chunk_preview": r["content"][:200] + "..." if len(r["content"]) > 200 else r["content"],
            })

        # 获取总数
        stats = self.vector_store.get_stats()

        return {
            "answer": answer,
            "sources": sources,
            "query_time_ms": round((time.time() - t0) * 1000, 1),
            "total_docs_searched": stats.get("total_chunks", 0),
        }
