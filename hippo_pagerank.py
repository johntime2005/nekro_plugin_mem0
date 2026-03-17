"""纯 Python Personalized PageRank 实现"""

import json
import importlib
from collections.abc import Iterable
from collections import defaultdict
from typing import cast


class HippoGraphIndex:
    """知识图谱索引，支持 PPR 检索"""

    def __init__(self):
        self.adj: dict[str, dict[str, float]] = defaultdict(dict)
        self.postings: dict[str, set[str]] = defaultdict(set)
        self.passage_entities: dict[str, list[str]] = {}

    @staticmethod
    def _extract_entities(content: str) -> list[str]:
        module_names = ("hippo_entity_extraction", "nekro_plugin_mem0.hippo_entity_extraction")
        for module_name in module_names:
            try:
                module = importlib.import_module(module_name)
                extractor = getattr(module, "extract_entities", None)
                if callable(extractor):
                    result_obj = extractor(content)
                    if isinstance(result_obj, list):
                        result_list = cast(list[object], result_obj)
                        return [str(item).strip() for item in result_list if str(item).strip()]
            except Exception:
                continue
        return []

    def add_edge(self, entity_a: str, entity_b: str, weight: float = 1.0):
        """添加无向边（双向）"""
        a = (entity_a or "").strip()
        b = (entity_b or "").strip()
        if not a or not b or a == b:
            return

        w = float(weight)
        if w <= 0:
            return

        self.adj[a][b] = self.adj[a].get(b, 0.0) + w
        self.adj[b][a] = self.adj[b].get(a, 0.0) + w

    def add_memory(self, content: str, passage_id: str, entities: list[str] | None = None):
        """添加记忆到图
        - 提取实体（或使用传入的 entities）
        - 更新 postings 倒排索引
        - 添加共现边（所有实体对之间）
        """
        pid = (passage_id or "").strip()
        if not pid:
            return

        if pid in self.passage_entities:
            self.remove_memory(pid)

        raw_entities = entities if entities is not None else self._extract_entities(content)
        unique_entities = list(dict.fromkeys(e.strip() for e in raw_entities if e.strip()))
        self.passage_entities[pid] = unique_entities

        for entity in unique_entities:
            self.postings[entity].add(pid)

        n = len(unique_entities)
        for i in range(n):
            for j in range(i + 1, n):
                self.add_edge(unique_entities[i], unique_entities[j], weight=1.0)

    def remove_memory(self, passage_id: str):
        """移除记忆：清理 postings 和 passage_entities"""
        pid = (passage_id or "").strip()
        if not pid:
            return

        entities = self.passage_entities.pop(pid, [])
        for entity in entities:
            posting = self.postings.get(entity)
            if posting is None:
                continue
            posting.discard(pid)
            if not posting:
                _ = self.postings.pop(entity, None)

    def ppr(self, seed_entities: list[str], alpha: float = 0.15, max_iter: int = 20) -> dict[str, float]:
        """Personalized PageRank
        - 收集所有节点
        - teleport 均匀分布在种子上
        - power iteration
        - dangling node 处理
        - 归一化
        """
        nodes: set[str] = set(self.adj.keys())
        for src, neighbors in self.adj.items():
            nodes.add(src)
            nodes.update(neighbors.keys())

        clean_seeds = [s.strip() for s in seed_entities if s.strip()]
        for seed in clean_seeds:
            nodes.add(seed)

        if not nodes:
            return {}

        node_list = list(nodes)
        n_nodes = len(node_list)

        if clean_seeds:
            seed_set = set(clean_seeds)
            teleport = {node: (1.0 / len(seed_set) if node in seed_set else 0.0) for node in node_list}
        else:
            teleport = {node: 1.0 / n_nodes for node in node_list}

        rank = dict(teleport)

        alpha = float(alpha)
        if alpha < 0:
            alpha = 0.0
        if alpha > 1:
            alpha = 1.0

        max_iter = max(1, int(max_iter))

        for _ in range(max_iter):
            next_rank = {node: alpha * teleport[node] for node in node_list}
            dangling_mass = 0.0

            for node in node_list:
                neighbors = self.adj.get(node, {})
                total_weight = sum(neighbors.values())
                if total_weight <= 0:
                    dangling_mass += rank.get(node, 0.0)
                    continue

                distribute = (1.0 - alpha) * rank.get(node, 0.0)
                for nbr, w in neighbors.items():
                    next_rank[nbr] = next_rank.get(nbr, 0.0) + distribute * (w / total_weight)

            if dangling_mass > 0:
                for node in node_list:
                    next_rank[node] = next_rank.get(node, 0.0) + (1.0 - alpha) * dangling_mass * teleport[node]

            rank = next_rank

        total = sum(rank.values())
        if total > 0:
            rank = {k: v / total for k, v in rank.items()}
        return rank

    def get_candidates_by_ppr(self, ppr_scores: dict[str, float], top_entities: int = 10, max_candidates: int = 200) -> set[str]:
        """通过 PPR 高分实体获取候选 passage_ids"""
        if not ppr_scores or top_entities <= 0 or max_candidates <= 0:
            return set()

        ranked_entities = sorted(ppr_scores.items(), key=lambda item: item[1], reverse=True)[:top_entities]
        candidates: set[str] = set()
        for entity, _ in ranked_entities:
            for pid in self.postings.get(entity, set()):
                candidates.add(pid)
                if len(candidates) >= max_candidates:
                    return candidates
        return candidates

    def score_content_by_ppr(self, entities: list[str], ppr_scores: dict[str, float]) -> float:
        """根据 PPR 分数评估内容（实体平均分）"""
        clean_entities = [e.strip() for e in entities if e.strip()]
        if not clean_entities:
            return 0.0

        scores = [ppr_scores.get(entity, 0.0) for entity in clean_entities]
        if not scores:
            return 0.0
        return sum(scores) / len(scores)

    def save(self, filepath: str):
        """保存图到 JSON"""
        payload = {
            "adj": {src: dict(neighbors) for src, neighbors in self.adj.items()},
            "postings": {entity: sorted(list(pids)) for entity, pids in self.postings.items()},
            "passage_entities": {pid: list(entities) for pid, entities in self.passage_entities.items()},
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

    @classmethod
    def load(cls, filepath: str) -> "HippoGraphIndex":
        """从 JSON 加载图"""
        with open(filepath, "r", encoding="utf-8") as f:
            payload_obj = cast(object, json.load(f))

        if not isinstance(payload_obj, dict):
            return cls()

        payload = cast(dict[str, object], payload_obj)

        idx = cls()

        adj_obj = payload.get("adj", {})
        if isinstance(adj_obj, dict):
            adj_map = cast(dict[object, object], adj_obj)
            for src, neighbors in adj_map.items():
                if not isinstance(neighbors, dict):
                    continue
                src_key = str(src)
                if src_key not in idx.adj:
                    idx.adj[src_key] = {}
                neighbors_map = cast(dict[object, object], neighbors)
                for dst, weight in neighbors_map.items():
                    if isinstance(weight, (int, float, str)):
                        idx.adj[src_key][str(dst)] = float(weight)

        postings_obj = payload.get("postings", {})
        if isinstance(postings_obj, dict):
            postings_map = cast(dict[object, object], postings_obj)
            for entity, pids in postings_map.items():
                if not isinstance(pids, Iterable):
                    continue
                idx.postings[str(entity)] = {str(pid) for pid in pids}

        passage_entities_obj = payload.get("passage_entities", {})
        if isinstance(passage_entities_obj, dict):
            passage_entities_map = cast(dict[object, object], passage_entities_obj)
            for pid, entities in passage_entities_map.items():
                if not isinstance(entities, Iterable):
                    continue
                idx.passage_entities[str(pid)] = [str(e) for e in entities]

        return idx
