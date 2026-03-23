"""
查询改写模块 - 基于 ChatLuna 的 LLM 查询改写
"""

import re
from typing import Any

from nekro_agent.core import logger

QUERY_REWRITE_PROMPT = """你是一个查询优化专家。用户可能会提出模糊、冗长或包含闲聊的问题。你的任务是将其改写为清晰、简洁的语义查询，用于记忆库检索。

改写规则：
1. 提取核心语义，去除冗余词汇
2. 保留关键实体和时间信息
3. 转换为陈述句或名词短语
4. 保持原意，避免过度解释

用户问题：{question}

改写后的查询（仅输出查询文本，不要解释）："""


def should_skip_retrieval(question: str) -> bool:
    """
    检测是否应跳过记忆检索。

    检测条件：
    1. 包含 [skip] token
    2. 常见问候语（你好、嗨、早上好等）
    3. 纯表情或无意义内容

    Args:
        question: 用户问题

    Returns:
        True 表示应跳过检索，False 表示应进行检索
    """
    if not question or not isinstance(question, str):
        return True

    question_lower = question.lower().strip()

    # 检查 [skip] token
    if "[skip]" in question_lower:
        return True

    # 常见问候语（仅完全匹配，不匹配前缀）
    greetings = [
        "你好",
        "嗨",
        "hi",
        "hello",
        "hey",
        "早上好",
        "晚上好",
        "下午好",
        "good morning",
        "good evening",
        "good afternoon",
        "怎么样",
        "最近怎么样",
        "你好吗",
        "how are you",
        "谢谢",
        "谢了",
        "thanks",
        "thank you",
        "再见",
        "拜拜",
        "bye",
        "goodbye",
    ]

    # 改为仅完全匹配（去掉 startswith 检查）
    if question_lower in greetings:
        return True

    # 纯表情或极短内容（少于3个字符）
    if len(question_lower) < 3:
        return True

    return False


async def rewrite_query(
    llm_client: Any,
    chat_history: list[dict[str, str]],
    question: str,
) -> str | None:
    """
    使用 LLM 改写查询以优化记忆检索。

    Args:
        llm_client: ChatLuna LLM 客户端
        chat_history: 聊天历史（最近20条消息）
        question: 用户问题

    Returns:
        改写后的查询，如果失败返回 None
    """
    if not llm_client or not question:
        return None

    try:
        # 构建改写 prompt
        prompt = QUERY_REWRITE_PROMPT.format(question=question)

        # 构建消息列表（仅使用最近20条历史）
        messages = chat_history[-20:] if chat_history else []
        messages.append({"role": "user", "content": prompt})

        # 调用 LLM
        response = await llm_client.chat(messages=messages)

        # 提取改写后的查询
        if response and hasattr(response, "content"):
            rewritten = response.content.strip()
        elif isinstance(response, dict) and "content" in response:
            rewritten = response["content"].strip()
        elif isinstance(response, str):
            rewritten = response.strip()
        else:
            return None

        # 清理改写结果
        rewritten = re.sub(r"^[\"']|[\"']$", "", rewritten)  # 去除首尾引号
        rewritten = re.sub(r"^改写后的查询[:：]\s*", "", rewritten)  # 去除前缀
        rewritten = rewritten.strip()

        return rewritten if rewritten else None

    except Exception as exc:
        logger.debug(f"[QueryRewrite] 查询改写失败: {exc}")
        return None
