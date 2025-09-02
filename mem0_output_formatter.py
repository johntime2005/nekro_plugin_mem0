"""
mem0_output_formatter.py - 记忆输出格式化器
"""

from typing import Any, Dict, List


def format_add_output(result: Any) -> str:
    """格式化添加记忆的结果"""
    if hasattr(result, 'id'):
        return f"记忆已添加，ID: {result.id}"
    return "记忆已添加"


def format_search_output(results: List[Dict[str, Any]]) -> str:
    """格式化搜索结果"""
    if not results:
        return "(无结果)"

    formatted = []
    for i, result in enumerate(results, 1):
        memory = result.get('memory', '')
        score = result.get('score', 0)
        metadata = result.get('metadata', {})

        formatted.append(f"{i}. {memory}")
        if metadata:
            tags = metadata.get('TYPE', [])
            if tags:
                formatted.append(f"   标签: {', '.join(tags)}")
        if score > 0:
            formatted.append(f"   相关度: {score:.2f}")

    return "\n".join(formatted)


def format_get_all_output(results: List[Dict[str, Any]]) -> str:
    """格式化获取所有记忆的结果"""
    if not results:
        return "(无结果)"

    formatted = []
    for i, result in enumerate(results, 1):
        memory = result.get('memory', '')
        metadata = result.get('metadata', {})
        created_at = result.get('created_at', '')

        formatted.append(f"{i}. {memory}")
        if metadata:
            tags = metadata.get('TYPE', [])
            if tags:
                formatted.append(f"   标签: {', '.join(tags)}")
        if created_at:
            formatted.append(f"   创建时间: {created_at}")

    return "\n".join(formatted)


def format_history_output(history: List[Dict[str, Any]]) -> str:
    """格式化记忆历史"""
    if not history:
        return "无历史记录"

    formatted = []
    for i, entry in enumerate(history, 1):
        memory = entry.get('memory', '')
        timestamp = entry.get('timestamp', '')

        formatted.append(f"{i}. {memory}")
        if timestamp:
            formatted.append(f"   时间: {timestamp}")

    return "\n".join(formatted)
