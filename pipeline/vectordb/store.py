"""
向量数据库管理器 — ChromaDB + DashScope Embedding

功能:
  - 文本分块 (RecursiveCharacterTextSplitter)
  - Embedding 生成 (阿里云 DashScope, 默认 text-embedding-v4)
  - ChromaDB 持久化
  - 语义检索 (带 metadata 过滤)
"""

import logging
import os
from datetime import datetime
from typing import Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_core.documents import Document as LangchainDocument

from config import settings
from models import UnifiedDocument, SourceType

logger = logging.getLogger(__name__)


def _init_embeddings():
    """根据配置初始化 embedding 引擎"""
    provider = settings.EMBEDDING_PROVIDER
    model = settings.EMBEDDING_MODEL

    if provider == "dashscope":
        from pipeline.vectordb.embeddings import DashScopeEmbeddings
        api_key = settings.DASHSCOPE_API_KEY or os.getenv("DASHSCOPE_API_KEY", "")
        logger.info(f"Using DashScope embedding: {model}")
        return DashScopeEmbeddings(model=model, api_key=api_key)

    elif provider == "local":
        from langchain_community.embeddings import HuggingFaceEmbeddings
        logger.info(f"Using local embedding: {model}")
        return HuggingFaceEmbeddings(
            model_name=model,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )

    elif provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        logger.info(f"Using OpenAI embedding: {model}")
        return OpenAIEmbeddings(model=model)

    else:
        raise ValueError(f"Unsupported embedding provider: {provider}")


class VectorStoreManager:
    """ChromaDB 向量存储管理器"""

    def __init__(self):
        self.embeddings = _init_embeddings()

        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            separators=["\n\n", "\n", "。", ".", " ", ""],
            length_function=len,
        )

        self.vectorstore: Optional[Chroma] = None

    def _get_store(self) -> Chroma:
        """懒加载 ChromaDB"""
        if self.vectorstore is None:
            self.vectorstore = Chroma(
                persist_directory=str(settings.CHROMA_DIR),
                embedding_function=self.embeddings,
                collection_name="mining_intel",
            )
        return self.vectorstore

    def add_documents(self, docs: list[UnifiedDocument]) -> int:
        """
        将统一文档分块后加入向量库

        Returns:
            实际入库的 chunk 数量
        """
        store = self._get_store()

        lc_docs = []
        for doc in docs:
            # 组装 embedding 文本
            text = doc.to_chunk_text()

            # 分块
            chunks = self.text_splitter.split_text(text)

            for i, chunk in enumerate(chunks):
                lc_doc = LangchainDocument(
                    page_content=chunk,
                    metadata={
                        "doc_id": doc.id,
                        "source_type": doc.source_type.value,
                        "source_name": doc.source_name,
                        "title": doc.title,
                        "url": doc.url,
                        "published_at": doc.published_at.isoformat() if doc.published_at else "",
                        "language": doc.language.value,
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                    },
                )
                lc_docs.append(lc_doc)

        if lc_docs:
            store.add_documents(lc_docs)

        logger.info(f"Ingested {len(docs)} docs → {len(lc_docs)} chunks into ChromaDB")
        return len(lc_docs)

    def search(
        self,
        query: str,
        top_k: int = 5,
        source_filter: Optional[SourceType] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[dict]:
        """
        语义检索

        Args:
            query: 搜索查询文本
            top_k: 返回结果数
            source_filter: 可选, 按来源类型过滤
            date_from: 可选, 起始日期 YYYY-MM-DD
            date_to: 可选, 结束日期 YYYY-MM-DD

        Returns:
            [{content, metadata, score}, ...] 按相似度降序
        """
        store = self._get_store()

        # 构建过滤器
        filter_dict = {}
        if source_filter:
            filter_dict["source_type"] = source_filter.value if hasattr(source_filter, 'value') else source_filter

        # 执行检索 (先取更多, 再手动过滤日期)
        k = top_k * 3 if (date_from or date_to) else top_k
        results = store.similarity_search_with_score(query, k=k, filter=filter_dict or None)

        # 后处理: 日期过滤 + 去重 doc_id + 排序
        seen_doc_ids = set()
        filtered = []
        for doc, score in results:
            # 日期过滤
            if date_from or date_to:
                pub_date = doc.metadata.get("published_at", "")[:10]
                if date_from and pub_date < date_from:
                    continue
                if date_to and pub_date > date_to:
                    continue

            # 去重: 同一个 doc 只保留最相关的 chunk
            doc_id = doc.metadata.get("doc_id", "")
            if doc_id in seen_doc_ids:
                continue
            seen_doc_ids.add(doc_id)

            filtered.append({
                "content": doc.page_content,
                "metadata": doc.metadata,
                "score": float(score),
            })

            if len(filtered) >= top_k:
                break

        return filtered

    def get_stats(self) -> dict:
        """获取向量库统计信息"""
        store = self._get_store()
        collection = store.get()
        total = len(collection["ids"]) if collection["ids"] else 0

        # 按来源统计
        by_source = {"news": 0, "policy": 0, "price": 0}
        by_source_name = {}
        dates = []

        for meta in collection.get("metadatas", []):
            if meta:
                st = meta.get("source_type", "unknown")
                by_source[st] = by_source.get(st, 0) + 1
                sn = meta.get("source_name", "unknown")
                by_source_name[sn] = by_source_name.get(sn, 0) + 1
                pub = meta.get("published_at", "")[:10]
                if pub:
                    dates.append(pub)

        return {
            "total_chunks": total,
            "by_source": by_source,
            "by_source_name": by_source_name,
            "date_range": {
                "earliest": min(dates) if dates else "",
                "latest": max(dates) if dates else "",
            },
        }
