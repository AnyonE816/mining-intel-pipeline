"""
评测指标计算

指标 1: Recall@K — 检索结果中是否包含 ground truth 标注的相关文档
指标 2: Faithfulness — LLM as Judge 评估生成回答是否忠实于检索到的上下文
"""

import logging
import os
import re
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)


def _init_eval_llm():
    """初始化评测用 LLM (与 RAG 共享 provider 配置)"""
    if settings.LLM_PROVIDER == "qwen":
        from langchain_community.chat_models.tongyi import ChatTongyi
        api_key = settings.DASHSCOPE_API_KEY or os.getenv("DASHSCOPE_API_KEY", "")
        return ChatTongyi(
            model=settings.LLM_MODEL,
            dashscope_api_key=api_key,
            temperature=0.0,
        )
    elif settings.LLM_PROVIDER == "deepseek":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL or "https://api.deepseek.com",
            temperature=0.0,
        )
    elif settings.LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            temperature=0.0,
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {settings.LLM_PROVIDER}")


def recall_at_k(
    retrieved_doc_ids: list[str],
    relevant_doc_ids: list[str],
    k: int = 5,
) -> float:
    """
    计算 recall@k

    如果 top-k 检索结果中包含至少一个 ground truth 的相关文档 → 1.0
    否则 → 0.0

    Args:
        retrieved_doc_ids: 检索返回的文档 ID (按排名顺序, 取前k个)
        relevant_doc_ids: ground truth 标注的相关文档 ID
        k: 截断值

    Returns:
        0.0 或 1.0
    """
    if not relevant_doc_ids:
        return 1.0  # 没有标注相关文档的, 默认通过

    retrieved_k = set(retrieved_doc_ids[:k])
    relevant = set(relevant_doc_ids)
    hits = len(retrieved_k & relevant)
    return 1.0 if hits > 0 else 0.0


def evaluate_faithfulness(
    answer: str,
    contexts: list[str],
    llm,
) -> float:
    """
    用 LLM 评估回答忠实度

    调用另一个 LLM (或同一个) 判断 answer 是否忠实于 context.
    返回 1-5 的归一化分数 (除以5转为 0-1)。

    Args:
        answer: RAG 生成的回答
        contexts: 检索到的文本片段
        llm: LangChain ChatLLM 实例

    Returns:
        归一化忠实度分数 (0.0 - 1.0)
    """
    from serve.prompts import FAITHFULNESS_PROMPT

    context_text = "\n---\n".join(contexts[:5])  # 最多 5 个 context
    prompt = FAITHFULNESS_PROMPT.format(context=context_text, answer=answer)

    try:
        response = llm.invoke(prompt)
        # 提取数字
        match = re.search(r"[1-5]", response.content)
        if match:
            score = int(match.group())
            return score / 5.0
        else:
            logger.warning(f"Could not parse faithfulness score from: {response.content[:100]}")
            return 0.5  # 默认中等
    except Exception as e:
        logger.error(f"Faithfulness eval failed: {e}")
        return 0.5


def run_batch_eval(ground_truths: list[dict], rag_chain) -> dict:
    """
    批量运行评测

    Args:
        ground_truths: GroundTruthItem 字典列表
        rag_chain: RAGChain 实例

    Returns:
        {
            "recall_at_5": float,       # 平均 recall@5
            "avg_faithfulness": float,   # 平均忠实度
            "per_question": [...],       # 每题详情
            "summary": str              # 总结文本
        }
    """
    # 初始化评估用 LLM (与 RAG 使用相同的 provider)
    eval_llm = _init_eval_llm()

    total_recall = 0.0
    total_faithfulness = 0.0
    n = 0
    details = []

    for gt in ground_truths:
        question = gt["question"]
        relevant_ids = gt.get("relevant_doc_ids", [])
        source_filter = gt.get("source_type_filter")
        date_from = gt.get("date_from")
        date_to = gt.get("date_to")

        # 执行查询
        result = rag_chain.query(
            question=question,
            top_k=5,
            source_filter=source_filter,
            date_from=date_from,
            date_to=date_to,
        )

        # Recall@5
        retrieved_ids = [s["metadata"]["doc_id"] for s in result.get("_raw_results", [])]
        # 从 sources 获取 doc_id (如果 _raw_results 不可用)
        if not retrieved_ids:
            retrieved_ids = []
        rec = recall_at_k(retrieved_ids, relevant_ids, k=5)

        # Faithfulness
        contexts = [s["chunk_preview"] for s in result.get("sources", [])]
        faith = evaluate_faithfulness(result["answer"], contexts, eval_llm)

        total_recall += rec
        total_faithfulness += faith
        n += 1

        details.append({
            "id": gt["id"],
            "question": question,
            "recall@5": rec,
            "faithfulness": round(faith, 3),
            "answer_preview": result["answer"][:200],
            "sources_count": len(result["sources"]),
        })

    avg_recall = total_recall / n if n > 0 else 0.0
    avg_faith = total_faithfulness / n if n > 0 else 0.0

    return {
        "recall_at_5": round(avg_recall, 3),
        "avg_faithfulness": round(avg_faith, 3),
        "per_question": details,
        "summary": f"Recall@5: {avg_recall:.1%} ({int(total_recall)}/{n}), "
                   f"Faithfulness: {avg_faith:.2f}/1.0",
    }
