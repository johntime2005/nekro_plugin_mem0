"""实体别名合并：Jaccard 相似度 + Union-Find"""

from typing import final


def char_shingle_set(text: str, k: int = 3) -> set[str]:
    """生成字符 k-shingle 集合"""
    value = (text or "").strip()
    if not value:
        return set()

    if k <= 1:
        return set(value)

    if len(value) < k:
        return {value}

    return {value[i : i + k] for i in range(len(value) - k + 1)}


def jaccard_similarity(set1: set[str], set2: set[str]) -> float:
    """Jaccard 相似度"""
    if not set1 and not set2:
        return 1.0
    if not set1 or not set2:
        return 0.0

    inter = len(set1 & set2)
    union = len(set1 | set2)
    if union == 0:
        return 0.0
    return inter / union


@final
class UnionFind:
    """并查集"""

    def __init__(self, n: int):
        self.parent: list[int] = list(range(n))
        self.rank: list[int] = [0] * n

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int):
        rx = self.find(x)
        ry = self.find(y)
        if rx == ry:
            return

        if self.rank[rx] < self.rank[ry]:
            self.parent[rx] = ry
        elif self.rank[rx] > self.rank[ry]:
            self.parent[ry] = rx
        else:
            self.parent[ry] = rx
            self.rank[rx] += 1


def consolidate_entity_aliases(entities: list[str], threshold: float = 0.85) -> dict[str, str]:
    """合并相似实体
    - 计算所有实体对的 Jaccard 相似度（char 3-shingles）
    - 相似度 >= threshold 的用 UnionFind 合并
    - 返回 {原实体: 代表实体} 映射
    """
    clean_entities = [e.strip() for e in entities if e.strip()]
    n = len(clean_entities)
    if n == 0:
        return {}

    uf = UnionFind(n)
    shingles = [char_shingle_set(entity, k=3) for entity in clean_entities]

    threshold = float(threshold)
    if threshold < 0:
        threshold = 0.0
    if threshold > 1:
        threshold = 1.0

    for i in range(n):
        for j in range(i + 1, n):
            sim = jaccard_similarity(shingles[i], shingles[j])
            if sim >= threshold:
                uf.union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = uf.find(i)
        groups.setdefault(root, []).append(i)

    rep_by_root: dict[int, str] = {}
    for root, indices in groups.items():
        members = [clean_entities[idx] for idx in indices]
        members_sorted = sorted(members, key=lambda s: (-len(s), s))
        rep_by_root[root] = members_sorted[0]

    alias_map: dict[str, str] = {}
    for i, ent in enumerate(clean_entities):
        root = uf.find(i)
        alias_map[ent] = rep_by_root[root]
    return alias_map


def apply_alias_mapping(entities: list[str], alias_map: dict[str, str]) -> list[str]:
    """应用别名映射，返回规范化后的实体列表（去重）"""
    normalized: list[str] = []
    seen: set[str] = set()

    for entity in entities:
        clean = entity.strip()
        if not clean:
            continue

        mapped = alias_map.get(clean, clean)
        if mapped not in seen:
            seen.add(mapped)
            normalized.append(mapped)

    return normalized
