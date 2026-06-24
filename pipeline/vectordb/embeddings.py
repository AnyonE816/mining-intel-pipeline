"""
DashScope Embeddings — 阿里云云端 Embedding，无需下载模型

实现 LangChain Embeddings 接口, 可直接用于 ChromaDB。
支持 text-embedding-v4 (1024维, 推荐) / v3 / v2。
"""

import logging
import os
from typing import List

from langchain_core.embeddings import Embeddings
from dashscope import TextEmbedding

from config import settings

logger = logging.getLogger(__name__)


class DashScopeEmbeddings(Embeddings):
    """阿里云 DashScope 文本 Embedding — LangChain 兼容封装"""

    def __init__(self, model: str = "text-embedding-v4", api_key: str = "", batch_size: int = 10):
        self.model = model
        self.api_key = api_key or settings.DASHSCOPE_API_KEY or os.getenv("DASHSCOPE_API_KEY", "")
        self.batch_size = min(batch_size, 10)  # DashScope 单次最多 10 条

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量 Embedding — 用于文档入库"""
        if not texts:
            return []

        all_embeddings = []
        # 分批调用 (DashScope 单次最多 25 条)
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            try:
                resp = TextEmbedding.call(
                    model=self.model,
                    input=batch,
                    api_key=self.api_key,
                )
                if resp.status_code == 200:
                    batch_embs = resp.output.get("embeddings", [])
                    # Keep original order (DashScope returns in order)
                    for emb_item in batch_embs:
                        all_embeddings.append(emb_item["embedding"])
                else:
                    logger.error(
                        f"Embedding API error: code={resp.code}, msg={resp.message}"
                    )
                    # Fallback: zero vectors to avoid crashing
                    dim = 1024 if "v4" in self.model or "v3" in self.model else 1536
                    for _ in batch:
                        all_embeddings.append([0.0] * dim)
            except Exception as e:
                logger.error(f"Embedding call failed: {e}")
                dim = 1024
                for _ in batch:
                    all_embeddings.append([0.0] * dim)

        return all_embeddings

    def embed_query(self, text: str) -> List[float]:
        """单个查询 Embedding — 用于用户问题"""
        result = self.embed_documents([text])
        return result[0] if result else [0.0] * 1024
