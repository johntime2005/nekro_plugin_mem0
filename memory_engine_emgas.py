from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
import threading
from typing import cast
from typing_extensions import override

from .emgas_ppmi import build_cooccurrence_matrix, compute_ppmi
from .emgas_spreading import EMGASGraph, SpreadingActivationOptions
from .hippo_entity_extraction import extract_entities
from .memory_engine_base import MemoryEngineBase, register_engine


@register_engine("emgas")
class EMGASEngine(MemoryEngineBase):
    def __init__(self, config: object) -> None:
        self.config: object = config

        self.memory_id: str = str(getattr(config, "MEMORY_ID", "default") or "default")
        self.decay_rate: float = float(getattr(config, "EMGAS_DECAY_RATE", 0.01))
        self.prune_threshold: float = float(getattr(config, "EMGAS_PRUNE_THRESHOLD", 0.05))
        self.firing_threshold: float = float(getattr(config, "EMGAS_FIRING_THRESHOLD", 0.1))
        self.propagation_decay: float = float(getattr(config, "EMGAS_PROPAGATION_DECAY", 0.85))

        self.graph_path: Path = (
            Path("data")
            / "chatluna"
            / "long-memory"
            / "emgas"
            / f"{self.memory_id}.json"
        )

        self.graph: EMGASGraph = EMGASGraph()
        self.passage_store: dict[str, dict[str, object]] = {}

        self._lock: threading.RLock = threading.RLock()
        self._stop_event: threading.Event = threading.Event()
        self._maintenance_interval_seconds: int = 10 * 60
        self._maintenance_thread: threading.Thread = threading.Thread(
            target=self._maintenance_loop,
            name=f"emgas-maintenance-{self.memory_id}",
            daemon=True,
        )

        self._load_graph()
        self._maintenance_thread.start()

    def initialize(self) -> None:
        return None

    @override
    def add_memory(self, key: str, value: object) -> None:
        passage_id, content, concepts, payload = self._normalize_add_payload(key, value)
        if not passage_id:
            return

        with self._lock:
            self.graph.add_memory(content=content, passage_id=passage_id, concepts=concepts)
            self.passage_store[passage_id] = payload
            self._apply_ppmi()
            self._save_graph()

    @override
    def search_memory(self, query: str, **kwargs) -> list[dict[str, object]]:
        if not query:
            return []

        seed_concepts = extract_entities(query)
        if not seed_concepts:
            return []

        opts = SpreadingActivationOptions(
            firing_threshold=self.firing_threshold,
            propagation_decay=self.propagation_decay,
        )

        with self._lock:
            passage_ids = self.graph.retrieve_context(seed_concepts=seed_concepts, options=opts)
            if not passage_ids:
                return []

            results: list[dict[str, object]] = []
            for passage_id in passage_ids:
                payload = self.passage_store.get(passage_id)
                if payload:
                    result = dict(payload)
                    _ = result.setdefault("id", passage_id)
                    results.append(result)
                else:
                    results.append({"id": passage_id, "memory": passage_id})
            return results

    @override
    def remove_memory(self, key: str) -> bool:
        passage_id = str(key or "").strip()
        if not passage_id:
            return False

        with self._lock:
            existed = passage_id in self.passage_store or f"passage::{passage_id}" in self.graph.nodes
            self.graph.remove_memory(passage_id)
            _ = self.passage_store.pop(passage_id, None)
            self._apply_ppmi()
            self._save_graph()
            return existed

    def close(self) -> None:
        self._stop_event.set()
        if self._maintenance_thread.is_alive():
            self._maintenance_thread.join(timeout=1.0)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            return

    def _maintenance_loop(self) -> None:
        while not self._stop_event.wait(self._maintenance_interval_seconds):
            with self._lock:
                self.graph.apply_decay(lambda_rate=self.decay_rate)
                self.graph.prune(threshold=self.prune_threshold)
                self._sync_passage_store_after_prune()
                self._save_graph()

    def _sync_passage_store_after_prune(self) -> None:
        remained_passages: set[str] = {
            node_id.split("::", 1)[1]
            for node_id, node in self.graph.nodes.items()
            if node.node_type == "passage" and "::" in node_id
        }
        for passage_id in list(self.passage_store.keys()):
            if passage_id not in remained_passages:
                del self.passage_store[passage_id]

    def _normalize_add_payload(
        self, key: str, value: object
    ) -> tuple[str, str, list[str], dict[str, object]]:
        if isinstance(value, Mapping):
            payload: dict[str, object] = {}
            value_map = cast(Mapping[object, object], value)
            for raw_key, raw_value in value_map.items():
                if isinstance(raw_key, str):
                    payload[raw_key] = raw_value
            passage_id = str(payload.get("id") or payload.get("passage_id") or key or "").strip()
            content = str(payload.get("memory") or payload.get("content") or "").strip()
            raw_concepts = payload.get("concepts")
            concepts = self._normalize_concepts(raw_concepts)
            if not concepts:
                concepts = extract_entities(content)
        else:
            passage_id = str(key or "").strip()
            content = str(value or "").strip()
            payload = {"id": passage_id, "memory": content}
            concepts = extract_entities(content)

        dedup_concepts = [c for c in dict.fromkeys(concepts) if c]
        _ = payload.setdefault("id", passage_id)
        _ = payload.setdefault("memory", content)
        payload["concepts"] = dedup_concepts
        return passage_id, content, dedup_concepts, payload

    def _apply_ppmi(self) -> None:
        typed_documents: list[list[str]] = []
        for record in self.passage_store.values():
            raw_concepts = record.get("concepts")
            doc = self._normalize_concepts(raw_concepts)
            if doc:
                typed_documents.append(doc)
        if not typed_documents:
            return

        cooccurrence = build_cooccurrence_matrix(typed_documents)
        total_pairs = sum(cooccurrence.values())
        if total_pairs <= 0:
            return

        concept_counts = Counter(token for doc in typed_documents for token in doc)
        ppmi_scores = compute_ppmi(cooccurrence, concept_counts, total_pairs)

        for (from_id, to_id), score in ppmi_scores.items():
            if score <= 0:
                continue
            from_node = self.graph.nodes.get(from_id)
            to_node = self.graph.nodes.get(to_id)
            if not from_node or not to_node:
                continue
            if from_node.node_type != "concept" or to_node.node_type != "concept":
                continue

            edge = self.graph.edges.get(from_id, {}).get(to_id)
            if edge is None:
                self.graph.add_edge(from_id, to_id, weight=score)
            else:
                edge.weight = max(0.01, float(score))

    def _load_graph(self) -> None:
        if not self.graph_path.exists():
            return
        self.graph = EMGASGraph.load(str(self.graph_path))

    def _save_graph(self) -> None:
        self.graph_path.parent.mkdir(parents=True, exist_ok=True)
        self.graph.save(str(self.graph_path))

    def _normalize_concepts(self, raw_concepts: object) -> list[str]:
        if not isinstance(raw_concepts, list):
            return []
        concepts: list[str] = []
        raw_items = cast(list[object], raw_concepts)
        for raw_item in raw_items:
            token = str(raw_item).strip()
            if token:
                concepts.append(token)
        return concepts
