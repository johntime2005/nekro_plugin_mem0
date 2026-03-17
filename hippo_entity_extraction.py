"""HippoRAG 实体提取模块"""

from collections.abc import Awaitable, Callable
import json
import re
from typing import cast, final


def normalize_text(text: str) -> str:
    """文本标准化：小写、去除特殊字符，保留中日韩字符"""
    normalized = text.lower()
    normalized = re.sub(r"[^a-z0-9\s\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7a3]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def extract_entities(text: str, max_entities: int = 50) -> list[str]:
    """基于规则的实体提取
    - 中文：连续2+个汉字 ([\u4e00-\u9fff]{2,})
    - 英文：3+字符非纯数字 token
    - 返回去重后的实体列表，最多 max_entities 个
    """
    if not text or max_entities <= 0:
        return []

    normalized = normalize_text(text)
    if not normalized:
        return []

    entities: list[str] = []
    seen: set[str] = set()

    def _push(entity: str) -> None:
        if entity and entity not in seen and len(entities) < max_entities:
            seen.add(entity)
            entities.append(entity)

    for match in re.finditer(r"[\u4e00-\u9fff]{2,}", normalized):
        _push(match.group(0))

    for token_match in re.finditer(r"[a-z0-9]+", normalized):
        token = token_match.group(0)
        if len(token) >= 3 and not token.isdigit():
            _push(token)

    return entities


@final
class Triple:
    """三元组：subject, predicate, object"""

    def __init__(self, subject: str, predicate: str, obj: str):
        self.subject: str = subject
        self.predicate: str = predicate
        self.obj: str = obj

    def _repr_text(self) -> str:
        return f"Triple(subject={self.subject!r}, predicate={self.predicate!r}, obj={self.obj!r})"

    __repr__ = _repr_text


def _extract_json_text(raw: str) -> str | None:
    code_block = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
    if code_block:
        return code_block.group(1).strip()

    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1 and end > start:
        return raw[start : end + 1]

    return None


async def extract_triples_with_llm(llm_invoke_fn: Callable[[str], Awaitable[str]], text: str) -> list[Triple]:
    """用 LLM 提取三元组
    - llm_invoke_fn: async callable，接受 str prompt，返回 str response
    - prompt 要求 LLM 返回 JSON array: [{"subject": "...", "predicate": "...", "object": "..."}]
    - 解析 JSON（支持 ```json 代码块）
    - 异常时返回空列表
    """
    if not text:
        return []

    prompt = (
        "请从以下文本中抽取关系三元组，并仅返回 JSON 数组，不要输出任何额外说明。\\n"
        "格式必须是：[{\"subject\": \"...\", \"predicate\": \"...\", \"object\": \"...\"}]\\n"
        f"文本：{text}"
    )

    try:
        response = await llm_invoke_fn(prompt)

        json_text = _extract_json_text(response)
        if not json_text:
            return []

        payload_obj = cast(object, json.loads(json_text))
        if not isinstance(payload_obj, list):
            return []
        payload_list = cast(list[object], payload_obj)

        triples: list[Triple] = []
        for item_obj in payload_list:
            if not isinstance(item_obj, dict):
                continue
            item = cast(dict[str, object], item_obj)

            subject = str(item.get("subject", "")).strip()
            predicate = str(item.get("predicate", "")).strip()
            obj = str(item.get("object", "")).strip()
            if subject and predicate and obj:
                triples.append(Triple(subject=subject, predicate=predicate, obj=obj))
        return triples
    except Exception:
        return []
