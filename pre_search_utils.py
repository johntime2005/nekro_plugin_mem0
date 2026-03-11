"""
预搜索辅助函数
"""

import re
from typing import List, Dict, Any, Optional
from nekro_agent.core import logger


def build_pre_search_query(
    messages: List[Dict[str, Any]], query_message_count: int, max_length: int
) -> Optional[str]:
    """
    从历史消息生成预搜索查询。

    策略：
    1. 筛选用户消息（排除 assistant/system）
    2. 取最近 N 条用户消息
    3. 清洗：去除代码块、过长内容
    4. 优先使用最后一条用户消息
    5. 截断到最大长度

    Args:
        messages: 历史消息列表，格式 [{"role": "user", "content": "..."}]
        query_message_count: 用于生成查询的消息数量
        max_length: 查询字符串最大长度

    Returns:
        生成的查询字符串，如果无法生成则返回 None
    """
    if not messages:
        return None

    # 筛选用户消息
    user_messages = [
        msg for msg in messages if isinstance(msg, dict) and msg.get("role") == "user"
    ]

    if not user_messages:
        return None

    # 取最近 N 条
    recent_user_messages = user_messages[-query_message_count:]

    # 优先使用最后一条消息
    last_message = recent_user_messages[-1].get("content", "")
    cleaned = clean_message_content(last_message)

    if cleaned:
        # 截断到最大长度
        return cleaned[:max_length]

    # 如果最后一条消息为空，尝试拼接多条
    all_content = " ".join(
        clean_message_content(msg.get("content", "")) for msg in recent_user_messages
    )

    return all_content[:max_length] if all_content else None


def clean_message_content(content: str) -> str:
    """
    清洗消息内容，去除代码块、特殊字符等。

    Args:
        content: 原始消息内容

    Returns:
        清洗后的内容
    """
    if not content:
        return ""

    # 去除代码块（```...```）
    content = re.sub(r"```[\s\S]*?```", "", content)

    # 去除行内代码（`...`）
    content = re.sub(r"`[^`]+`", "", content)

    # 去除 HTML 标签
    content = re.sub(r"<[^>]+>", "", content)

    # 去除多余空白
    content = re.sub(r"\s+", " ", content)

    # 去除特殊标记（如 OMO_INTERNAL_INITIATOR）
    content = re.sub(r"<!--.*?-->", "", content)

    return content.strip()


def convert_db_messages_to_dict(db_messages: List[Any]) -> List[Dict[str, Any]]:
    """
    将数据库消息对象转换为标准字典格式。

    Args:
        db_messages: 数据库消息对象列表（DBChatMessage）

    Returns:
        标准格式的消息列表 [{"role": "user", "content": "..."}]
    """
    result = []
    for msg in db_messages:
        try:
            # 判断消息角色
            sender_id = getattr(msg, "sender_id", None)
            is_bot = sender_id == "-1"
            role = "assistant" if is_bot else "user"

            # 提取内容
            content = getattr(msg, "content_text", None) or getattr(msg, "content", "")

            if content:
                result.append({"role": role, "content": str(content)})
        except Exception as exc:
            logger.debug(f"[PreSearch] 跳过无效消息: {exc}")
            continue

    return result
