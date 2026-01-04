"""
输出格式化
"""

from typing import Any, Dict, List, Optional


def format_add_output(result: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(result, dict) and "results" in result:
        return {"ok": True, "results": result.get("results", []), "relations": result.get("relations")}
    return result


def _normalize_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if isinstance(results, dict):
        return results.get("results", [])
    return results or []


def _filter_by_tags(results: List[Dict[str, Any]], tags: List[str]) -> List[Dict[str, Any]]:
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
    tag = metadata.get("TYPE")
    tag_part = f"[{tag}]" if tag else ""
    score_part = f"(score={score:.3f})" if isinstance(score, (int, float)) else ""
    return f"- {memory_id} {tag_part}{score_part} {text}".strip()


def _format_memory_list(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "(无结果)"
    lines = [_format_memory_line(item) for item in results]
    return "\n".join(lines)


def format_search_output(results: List[Dict[str, Any]], tags: Optional[List[str]] = None, threshold: Optional[float] = None) -> Dict[str, Any]:
    normalized = _normalize_results(results)
    filtered = _filter_by_tags(normalized, tags or [])
    if threshold is not None:
        filtered = [item for item in filtered if item.get("score") is None or item.get("score") >= threshold]
    return {"results": filtered, "text": _format_memory_list(filtered)}


def format_get_all_output(results: List[Dict[str, Any]], tags: Optional[List[str]] = None) -> Dict[str, Any]:
    normalized = _normalize_results(results)
    filtered = _filter_by_tags(normalized, tags or [])
    return {"results": filtered, "text": _format_memory_list(filtered)}


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
