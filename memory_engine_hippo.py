from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .hippo_alias_merge import apply_alias_mapping, consolidate_entity_aliases
from .hippo_entity_extraction import extract_entities
from .hippo_pagerank import HippoGraphIndex
from .mem0_utils import get_mem0_client
from .memory_engine_base import MemoryEngineBase, register_engine


@register_engine("hippo")
class HippoEngine(MemoryEngineBase):
    def __init__(self, config: Any, memory_id: str | None = None) -> None:
        self.config: Any = config
        self.client: Any = None

        cfg_memory_id = getattr(config, "MEMORY_ID", None) if config is not None else None
        self.memory_id: str = (memory_id or cfg_memory_id or "default").strip() or "default"

        self.graph = HippoGraphIndex()
        self.alias_map: dict[str, str] = {}
        self.memory_store: dict[str, dict[str, Any]] = {}

        self.ppr_alpha: float = float(getattr(config, "HIPPO_PPR_ALPHA", 0.15))
        self.hybrid_weight: float = float(getattr(config, "HIPPO_HYBRID_WEIGHT", 0.8))
        self.top_entities: int = int(getattr(config, "HIPPO_TOP_ENTITIES", 10))
        self.max_candidates: int = int(getattr(config, "HIPPO_MAX_CANDIDATES", 200))

        self._persist_path = Path("data") / "chatluna" / "long-memory" / "hippo" / f"{self.memory_id}.json"

    async def initialize(self) -> None:
        self.client = await get_mem0_client()
        self._load_state()

    def add_memory(self, key: str, value: object) -> None:
        passage_id = self._normalize_passage_id(key)
        content = self._extract_content(value)
        if not content:
            return

        entities = extract_entities(content)
        normalized_entities = self._normalize_entities(entities)

        self.memory_store[passage_id] = {
            "content": content,
            "entities": normalized_entities,
        }
        self.graph.add_memory(content, passage_id=passage_id, entities=normalized_entities)

        if self.client is not None:
            try:
                self.client.add(
                    content,
                    user_id=key,
                    metadata={
                        "hippo_passage_id": passage_id,
                        "hippo_entities": normalized_entities,
                    },
                )
            except Exception:
                pass

        self._save_state()

    def search_memory(self, query: str, **kwargs) -> list[dict[str, object]]:
        query_text = (query or "").strip()
        if not query_text:
            return []

        query_entities = self._normalize_entities(extract_entities(query_text))
        ppr_scores = self.graph.ppr(query_entities, alpha=self._clamp(self.ppr_alpha), max_iter=20)
        ppr_candidates = self.graph.get_candidates_by_ppr(
            ppr_scores,
            top_entities=max(1, self.top_entities),
            max_candidates=max(1, self.max_candidates),
        )

        semantic_results: list[dict[str, Any]] = []
        if self.client is not None:
            try:
                raw = self.client.search(query_text, limit=max(1, self.max_candidates), **kwargs)
                if isinstance(raw, list):
                    semantic_results = [item for item in raw if isinstance(item, dict)]
            except Exception:
                semantic_results = []

        merged: dict[str, dict[str, Any]] = {}

        for item in semantic_results:
            pid = self._extract_passage_id(item)
            if not pid:
                continue

            content = self._extract_result_content(item)
            if not content and pid in self.memory_store:
                content = str(self.memory_store[pid].get("content", ""))

            entities = self._extract_result_entities(item)
            if not entities and pid in self.memory_store:
                entities = [str(e) for e in self.memory_store[pid].get("entities", [])]
            entities = self._normalize_entities(entities)

            semantic_score = self._normalize_semantic_score(item)
            ppr_score = self.graph.score_content_by_ppr(entities, ppr_scores)
            hybrid_score = self._hybrid_score(semantic_score, ppr_score)

            merged[pid] = {
                **item,
                "id": pid,
                "memory": content,
                "entities": entities,
                "semantic_score": semantic_score,
                "ppr_score": ppr_score,
                "score": hybrid_score,
                "hybrid_score": hybrid_score,
            }

        for pid in ppr_candidates:
            if pid in merged:
                continue
            record = self.memory_store.get(pid)
            if not record:
                continue
            entities = [str(e) for e in record.get("entities", [])]
            ppr_score = self.graph.score_content_by_ppr(entities, ppr_scores)
            hybrid_score = self._hybrid_score(0.0, ppr_score)
            merged[pid] = {
                "id": pid,
                "memory": str(record.get("content", "")),
                "entities": entities,
                "semantic_score": 0.0,
                "ppr_score": ppr_score,
                "score": hybrid_score,
                "hybrid_score": hybrid_score,
            }

        ranked = sorted(merged.values(), key=lambda x: float(x.get("hybrid_score", 0.0)), reverse=True)
        return ranked[: max(1, self.max_candidates)]

    def remove_memory(self, key: str) -> bool:
        pid = self._normalize_passage_id(key)
        removed = False

        if pid in self.memory_store:
            self.memory_store.pop(pid, None)
            self.graph.remove_memory(pid)
            removed = True

        if self.client is not None:
            try:
                self.client.delete(key)
                removed = True
            except Exception:
                pass

        if removed:
            self._save_state()
        return removed

    def _normalize_passage_id(self, key: str) -> str:
        value = (key or "").strip()
        return value or f"hippo-{uuid4().hex}"

    def _extract_content(self, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for k in ("content", "memory", "text", "value"):
                if k in value and value[k] is not None:
                    return str(value[k]).strip()
            return str(value).strip()
        if hasattr(value, "content"):
            return str(getattr(value, "content", "")).strip()
        return str(value).strip()

    def _normalize_entities(self, entities: list[str]) -> list[str]:
        clean_entities = [str(entity).strip() for entity in entities if str(entity).strip()]
        if not clean_entities:
            return []

        vocabulary = set(self.alias_map.keys())
        vocabulary.update(self.alias_map.values())
        vocabulary.update(clean_entities)

        self.alias_map = consolidate_entity_aliases(list(vocabulary), threshold=0.85)
        return apply_alias_mapping(clean_entities, self.alias_map)

    def _extract_passage_id(self, item: dict[str, Any]) -> str:
        for key in ("id", "memory_id"):
            value = item.get(key)
            if value:
                return str(value)

        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            pid = metadata.get("hippo_passage_id")
            if pid:
                return str(pid)
        return ""

    def _extract_result_content(self, item: dict[str, Any]) -> str:
        for key in ("memory", "content", "text", "value"):
            value = item.get(key)
            if value is not None:
                text = str(value).strip()
                if text:
                    return text
        return ""

    def _extract_result_entities(self, item: dict[str, Any]) -> list[str]:
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            values = metadata.get("hippo_entities")
            if isinstance(values, list):
                return [str(v).strip() for v in values if str(v).strip()]

        content = self._extract_result_content(item)
        return extract_entities(content) if content else []

    def _normalize_semantic_score(self, item: dict[str, Any]) -> float:
        raw = item.get("score")
        if raw is None:
            raw = item.get("similarity")
        if raw is None:
            raw = item.get("relevance")
        if raw is None:
            return 0.0

        try:
            score = float(raw)
        except Exception:
            return 0.0

        if score < 0:
            return 0.0
        if score > 1.0:
            return 1.0 / (1.0 + score)
        return score

    def _hybrid_score(self, semantic_score: float, ppr_score: float) -> float:
        w = self._clamp(self.hybrid_weight)
        return (w * max(0.0, semantic_score)) + ((1.0 - w) * max(0.0, ppr_score))

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    def _load_state(self) -> None:
        path = self._persist_path
        if not path.exists():
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return

            graph_payload = data.get("graph")
            if isinstance(graph_payload, dict):
                temp = HippoGraphIndex()
                adj = graph_payload.get("adj", {})
                postings = graph_payload.get("postings", {})
                passage_entities = graph_payload.get("passage_entities", {})

                if isinstance(adj, dict):
                    for src, neighbors in adj.items():
                        if not isinstance(neighbors, dict):
                            continue
                        temp.adj[str(src)] = {
                            str(dst): float(weight)
                            for dst, weight in neighbors.items()
                            if isinstance(weight, (int, float, str))
                        }

                if isinstance(postings, dict):
                    for entity, pids in postings.items():
                        if isinstance(pids, list):
                            temp.postings[str(entity)] = {str(pid) for pid in pids}

                if isinstance(passage_entities, dict):
                    for pid, entities in passage_entities.items():
                        if isinstance(entities, list):
                            temp.passage_entities[str(pid)] = [str(e) for e in entities]

                self.graph = temp

            alias_map = data.get("alias_map", {})
            if isinstance(alias_map, dict):
                self.alias_map = {str(k): str(v) for k, v in alias_map.items()}

            memory_store = data.get("memory_store", {})
            if isinstance(memory_store, dict):
                normalized_store: dict[str, dict[str, Any]] = {}
                for pid, record in memory_store.items():
                    if not isinstance(record, dict):
                        continue
                    normalized_store[str(pid)] = {
                        "content": str(record.get("content", "")),
                        "entities": [str(e) for e in record.get("entities", []) if str(e).strip()],
                    }
                self.memory_store = normalized_store
        except Exception:
            return

    def _save_state(self) -> None:
        payload = {
            "graph": {
                "adj": {src: dict(neighbors) for src, neighbors in self.graph.adj.items()},
                "postings": {entity: sorted(list(pids)) for entity, pids in self.graph.postings.items()},
                "passage_entities": {
                    pid: list(entities) for pid, entities in self.graph.passage_entities.items()
                },
            },
            "alias_map": dict(self.alias_map),
            "memory_store": self.memory_store,
        }

        path = self._persist_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
