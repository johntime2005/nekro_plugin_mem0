"""
输出格式化
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _coerce_result_item(item: Any) -> Optional[Dict[str, Any]]:
    if isinstance(item, dict):
        return item
    if isinstance(item, str):
        text = item.strip()
        if text:
            return {"memory": text}
    return None


def format_add_output(result: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(result, dict) and "results" in result:
        return {
            "ok": True,
            "results": result.get("results", []),
            "relations": result.get("relations"),
        }
    return result


def _filter_expired(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    valid = []
    for item in results:
        metadata = item.get("metadata") or {}
        expiry = metadata.get("expiration_date")
        if expiry:
            try:
                if isinstance(expiry, str):
                    exp_dt = datetime.fromisoformat(expiry)
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                    if exp_dt < now:
                        continue
            except (ValueError, TypeError):
                pass
        valid.append(item)
    return valid


def _normalize_results(results: Any) -> List[Dict[str, Any]]:
    raw_items: Any
    if isinstance(results, dict):
        raw_items = results.get("results", [])
    else:
        raw_items = results or []

    if not isinstance(raw_items, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for item in raw_items:
        coerced = _coerce_result_item(item)
        if coerced is not None:
            normalized.append(coerced)
    return normalized


def normalize_results(results: Any) -> List[Dict[str, Any]]:
    """公开的结果归一化，供外部复用。"""
    return _normalize_results(results)


def _filter_by_tags(
    results: List[Dict[str, Any]], tags: List[str]
) -> List[Dict[str, Any]]:
    if not tags:
        return results
    wanted = set(tags)
    filtered = []
    for item in results:
        metadata = item.get("metadata") or {}
        if isinstance(metadata, dict):
            tag_value = metadata.get("TYPE")
            if isinstance(tag_value, list):
                if wanted.intersection(set(tag_value)):
                    filtered.append(item)
            elif isinstance(tag_value, str):
                if tag_value in wanted:
                    filtered.append(item)
            else:
                filtered.append(item)
        else:
            filtered.append(item)
    return filtered


def _format_memory_line(item: Dict[str, Any]) -> str:
    memory_id = item.get("id") or item.get("memory_id") or "未知ID"
    text = item.get("memory") or item.get("data") or item.get("content") or ""
    score = item.get("score")
    metadata = item.get("metadata") or {}
    layer = item.get("layer") or item.get("scope_level")
    tag = metadata.get("TYPE")
    importance = metadata.get("importance")
    expiration_date = metadata.get("expiration_date")
    tag_part = f"[{tag}]" if tag else ""
    layer_part = f"[{layer}]" if layer else ""
    importance_part = f"[importance={importance}]" if importance is not None else ""
    expires_part = f"[expires={expiration_date}]" if expiration_date else ""
    score_part = f"(score={score:.3f})" if isinstance(score, (int, float)) else ""
    return f"- {memory_id} {tag_part}{layer_part}{importance_part}{expires_part}{score_part} {text}".strip()


def _format_memory_list(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "(无结果)"
    lines = [_format_memory_line(item) for item in results]
    return "\n".join(lines)


def _build_memory_operations(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    operations: List[Dict[str, Any]] = []
    for item in results:
        memory_id = item.get("id") or item.get("memory_id")
        if not memory_id:
            continue
        metadata = item.get("metadata") or {}
        memory_text = (
            item.get("memory") or item.get("data") or item.get("content") or ""
        )
        operations.append(
            {
                "memory_id": str(memory_id),
                "update": {
                    "tool": "update_memory",
                    "payload": {
                        "memory_id": str(memory_id),
                        "new_memory": str(memory_text),
                    },
                },
                "delete": {
                    "tool": "delete_memory",
                    "payload": {"memory_id": str(memory_id)},
                },
                "update_metadata": {
                    "tool": "update_memory_metadata",
                    "payload": {
                        "memory_id": str(memory_id),
                        "metadata_patch": {},
                        "expiration_date": metadata.get("expiration_date"),
                        "clear_expiration": False,
                    },
                },
            }
        )
    return operations


def _get_combined_score(item: Dict[str, Any], importance_weight: float = 0.3) -> float:
    """计算组合分数：(1-weight)*score + weight*(importance/10)

    Args:
        item: 记忆条目
        importance_weight: importance 权重 (0.0-1.0)，剩余为 score 权重
    """
    score = item.get("score") or 0.0
    if not isinstance(score, (int, float)):
        score = 0.0

    metadata = item.get("metadata") or {}
    importance = metadata.get("importance", 5)
    try:
        importance = max(1, min(10, int(importance)))
    except (ValueError, TypeError):
        importance = 5

    w = max(0.0, min(1.0, float(importance_weight)))
    return (1.0 - w) * float(score) + w * (importance / 10.0)


def format_search_output(
    results: List[Dict[str, Any]],
    tags: Optional[List[str]] = None,
    threshold: Optional[float] = None,
    importance_weight: float = 0.3,
) -> Dict[str, Any]:
    normalized = _normalize_results(results)
    filtered = _filter_by_tags(normalized, tags or [])
    filtered = _filter_expired(filtered)
    if threshold is not None:
        filtered = [
            item
            for item in filtered
            if _get_combined_score(item, importance_weight=importance_weight)
            >= threshold
        ]
    return {
        "results": filtered,
        "text": _format_memory_list(filtered),
        "memory_operations": _build_memory_operations(filtered),
    }


def format_get_all_output(
    results: List[Dict[str, Any]], tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    normalized = _normalize_results(results)
    filtered = _filter_by_tags(normalized, tags or [])
    filtered = _filter_expired(filtered)
    return {
        "results": filtered,
        "text": _format_memory_list(filtered),
        "memory_operations": _build_memory_operations(filtered),
    }


def format_history_output(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return _normalize_results(results)


def format_history_text(results: List[Dict[str, Any]]) -> str:
    history = format_history_output(results)
    if not history:
        return "(无结果)"
    lines = []
    for item in history:
        memory_id = item.get("memory_id") or item.get("id") or ""
        version = item.get("version") or item.get("seq") or ""
        text = item.get("memory") or item.get("data") or item.get("content") or ""
        lines.append(f"- [{version}] {memory_id} {text}".strip())
    return "\n".join(lines)
