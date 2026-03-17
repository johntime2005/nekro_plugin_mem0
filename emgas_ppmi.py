import math
from collections import Counter, defaultdict


def build_cooccurrence_matrix(documents: list[list[str]], window_size: int = 5) -> dict[tuple[str, str], int]:
    if window_size < 1:
        raise ValueError("window_size 必须 >= 1")

    matrix: dict[tuple[str, str], int] = defaultdict(int)

    for concepts in documents:
        tokens = [token for token in concepts if token]
        for i, center in enumerate(tokens):
            start = max(0, i - window_size)
            end = min(len(tokens), i + window_size + 1)
            for j in range(start, end):
                if i == j:
                    continue
                context = tokens[j]
                pair = (center, context)
                matrix[pair] += 1

    return dict(matrix)


def compute_ppmi(
    cooccurrence: dict[tuple[str, str], int], concept_counts: Counter[str], total_pairs: int
) -> dict[tuple[str, str], float]:
    if total_pairs <= 0:
        return {}

    ppmi_scores: dict[tuple[str, str], float] = {}

    for (concept_a, concept_b), pair_count in cooccurrence.items():
        if pair_count <= 0:
            continue

        count_a = concept_counts.get(concept_a, 0)
        count_b = concept_counts.get(concept_b, 0)
        if count_a <= 0 or count_b <= 0:
            continue

        p_xy = pair_count / total_pairs
        p_x = count_a / total_pairs
        p_y = count_b / total_pairs
        ratio = p_xy / (p_x * p_y)
        if ratio <= 0:
            continue

        pmi = math.log2(ratio)
        ppmi_scores[(concept_a, concept_b)] = max(0.0, pmi)

    return ppmi_scores


def update_edge_weights(edges: dict[str, dict[str, float]], ppmi_scores: dict[tuple[str, str], float]) -> None:
    for from_id, to_map in edges.items():
        for to_id in list(to_map.keys()):
            if (from_id, to_id) in ppmi_scores:
                to_map[to_id] = ppmi_scores[(from_id, to_id)]
