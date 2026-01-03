"""
输出格式化
"""

from typing import Any, Dict, List


def format_add_output(result: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(result, dict) and "results" in result:
        return {"ok": True, "results": result.get("results", []), "relations": result.get("relations")}
    return result


def format_search_output(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if isinstance(results, dict):
        return results.get("results", [])
    return results


def format_get_all_output(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if isinstance(results, dict):
        return results.get("results", [])
    return results


def format_history_output(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if isinstance(results, dict):
        return results.get("results", [])
    return results
