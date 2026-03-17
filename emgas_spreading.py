from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
import json
import math
from typing import cast


@dataclass
class EMGASNode:
    id: str
    node_type: str
    base_activation: float = 0.5
    last_accessed: datetime = field(default_factory=datetime.now)
    source_passage_ids: set[str] = field(default_factory=set)


@dataclass
class EMGASEdge:
    weight: float = 1.0


@dataclass
class SpreadingActivationOptions:
    firing_threshold: float = 0.1
    propagation_decay: float = 0.85
    max_iterations: int = 5
    top_n: int = 20


class EMGASGraph:
    def __init__(self):
        self.nodes: dict[str, EMGASNode] = {}
        self.edges: dict[str, dict[str, EMGASEdge]] = defaultdict(dict)

    def add_node(
        self,
        node_id: str,
        node_type: str = "concept",
        source_passage_ids: set[str] | None = None,
    ) -> None:
        if node_id not in self.nodes:
            self.nodes[node_id] = EMGASNode(id=node_id, node_type=node_type)
        if source_passage_ids:
            self.nodes[node_id].source_passage_ids.update(source_passage_ids)
        self.nodes[node_id].last_accessed = datetime.now()

    def add_edge(self, from_id: str, to_id: str, weight: float = 1.0) -> None:
        if from_id not in self.nodes:
            self.add_node(from_id)
        if to_id not in self.nodes:
            self.add_node(to_id)
        if to_id in self.edges[from_id]:
            self.edges[from_id][to_id].weight += weight
        else:
            self.edges[from_id][to_id] = EMGASEdge(weight=weight)

    def add_memory(self, content: str, passage_id: str, concepts: list[str]) -> None:
        _ = content
        passage_node_id = f"passage::{passage_id}"
        self.add_node(
            passage_node_id, node_type="passage", source_passage_ids={passage_id}
        )

        dedup_concepts = [c for c in dict.fromkeys(concepts) if c]
        for concept in dedup_concepts:
            self.add_node(concept, node_type="concept", source_passage_ids={passage_id})
            self.add_edge(concept, passage_node_id, weight=1.0)
            self.add_edge(passage_node_id, concept, weight=1.0)

        for i, concept_a in enumerate(dedup_concepts):
            for concept_b in dedup_concepts[i + 1 :]:
                self.add_edge(concept_a, concept_b, weight=1.0)
                self.add_edge(concept_b, concept_a, weight=1.0)

    def remove_memory(self, passage_id: str) -> None:
        passage_node_id = f"passage::{passage_id}"

        for node in self.nodes.values():
            node.source_passage_ids.discard(passage_id)

        removable = {passage_node_id}
        for node_id, node in self.nodes.items():
            if node.node_type == "concept" and not node.source_passage_ids:
                removable.add(node_id)

        for node_id in removable:
            _ = self.nodes.pop(node_id, None)
            _ = self.edges.pop(node_id, None)

        for from_id in list(self.edges.keys()):
            for to_id in list(self.edges[from_id].keys()):
                if to_id in removable:
                    del self.edges[from_id][to_id]
            if not self.edges[from_id]:
                del self.edges[from_id]

    def retrieve_context(
        self,
        seed_concepts: list[str],
        options: SpreadingActivationOptions | None = None,
    ) -> dict[str, float]:
        opts = options or SpreadingActivationOptions()
        activations: dict[str, float] = {node_id: 0.0 for node_id in self.nodes}
        for seed in seed_concepts:
            if seed in activations:
                activations[seed] = 1.0

        for _ in range(opts.max_iterations):
            firing_nodes = [
                n for n, a in activations.items() if a > opts.firing_threshold
            ]
            if not firing_nodes:
                break

            propagated: defaultdict[str, float] = defaultdict(float)
            for node_id in firing_nodes:
                current = activations[node_id]
                for neighbor_id, edge in self.edges.get(node_id, {}).items():
                    propagated[neighbor_id] += (
                        current * edge.weight * opts.propagation_decay
                    )
                activations[node_id] = current * (1.0 - opts.propagation_decay)

            for node_id, energy in propagated.items():
                activations[node_id] = activations.get(node_id, 0.0) + energy

        ranked = sorted(activations.items(), key=lambda item: item[1], reverse=True)[
            : max(0, opts.top_n)
        ]
        now = datetime.now()

        passage_scores: dict[str, float] = {}
        for node_id, act_score in ranked:
            if act_score <= 0:
                continue
            node = self.nodes[node_id]
            for pid in node.source_passage_ids:
                passage_scores[pid] = max(passage_scores.get(pid, 0.0), act_score)
            node.last_accessed = now
            node.base_activation = max(node.base_activation, act_score)

        if not passage_scores:
            return {}
        scores = list(passage_scores.values())
        min_s, max_s = min(scores), max(scores)
        if max_s == min_s:
            return {pid: 1.0 for pid in passage_scores}
        return {pid: (s - min_s) / (max_s - min_s) for pid, s in passage_scores.items()}

    def apply_decay(self, lambda_rate: float = 0.01) -> None:
        if lambda_rate < 0:
            raise ValueError("lambda_rate 必须 >= 0")
        for node in self.nodes.values():
            now = (
                datetime.now(tz=node.last_accessed.tzinfo)
                if node.last_accessed.tzinfo
                else datetime.now()
            )
            delta_seconds = (now - node.last_accessed).total_seconds()
            delta_hours = max(0.0, delta_seconds / 3600.0)
            node.base_activation = float(
                node.base_activation * math.exp(-lambda_rate * delta_hours)
            )

    def prune(self, threshold: float = 0.05) -> None:
        to_remove = {
            node_id
            for node_id, node in self.nodes.items()
            if node.base_activation < threshold
        }

        for node_id in to_remove:
            _ = self.nodes.pop(node_id, None)
            _ = self.edges.pop(node_id, None)

        for from_id in list(self.edges.keys()):
            for to_id in list(self.edges[from_id].keys()):
                if to_id in to_remove:
                    del self.edges[from_id][to_id]
            if not self.edges[from_id]:
                del self.edges[from_id]

    def save(self, filepath: str) -> None:
        payload = {
            "nodes": {
                node_id: {
                    "id": node.id,
                    "node_type": node.node_type,
                    "base_activation": node.base_activation,
                    "last_accessed": node.last_accessed.isoformat(),
                    "source_passage_ids": sorted(node.source_passage_ids),
                }
                for node_id, node in self.nodes.items()
            },
            "edges": {
                from_id: {to_id: edge.weight for to_id, edge in to_map.items()}
                for from_id, to_map in self.edges.items()
            },
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, filepath: str) -> "EMGASGraph":
        with open(filepath, "r", encoding="utf-8") as f:
            payload_obj = cast(object, json.load(f))
        payload = cast(dict[str, object], payload_obj)

        graph = cls()

        nodes_obj = payload.get("nodes", {})
        edges_obj = payload.get("edges", {})
        nodes_map = cast(dict[str, dict[str, object]], nodes_obj)
        edges_map = cast(dict[str, dict[str, float]], edges_obj)

        for node_id, raw in nodes_map.items():
            base_activation_raw = raw.get("base_activation", 0.5)
            last_accessed_raw = raw.get("last_accessed", datetime.now().isoformat())
            source_ids_raw = raw.get("source_passage_ids", [])
            if isinstance(base_activation_raw, (int, float, str)):
                base_activation = float(base_activation_raw)
            else:
                base_activation = 0.5
            graph.nodes[node_id] = EMGASNode(
                id=str(raw.get("id", node_id)),
                node_type=str(raw.get("node_type", "concept")),
                base_activation=base_activation,
                last_accessed=datetime.fromisoformat(str(last_accessed_raw)),
                source_passage_ids={str(x) for x in cast(list[object], source_ids_raw)},
            )

        for from_id, to_map in edges_map.items():
            graph.edges[from_id] = {
                to_id: EMGASEdge(weight=float(weight))
                for to_id, weight in to_map.items()
            }

        return graph
