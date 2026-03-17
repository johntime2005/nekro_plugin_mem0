import math
from datetime import datetime


def exponential_decay(base_activation: float, last_accessed: datetime, lambda_rate: float = 0.01) -> float:
    if lambda_rate < 0:
        raise ValueError("lambda_rate 必须 >= 0")

    now = datetime.now(tz=last_accessed.tzinfo) if last_accessed.tzinfo else datetime.now()
    delta_seconds = (now - last_accessed).total_seconds()
    delta_hours = max(0.0, delta_seconds / 3600.0)
    return float(base_activation * math.exp(-lambda_rate * delta_hours))


def apply_decay_to_nodes(nodes: dict[str, dict[str, object]], lambda_rate: float = 0.01) -> None:
    for node in nodes.values():
        base_activation = node.get("base_activation")
        last_accessed = node.get("last_accessed")

        if not isinstance(base_activation, (int, float)):
            continue
        if not isinstance(last_accessed, datetime):
            continue

        node["base_activation"] = exponential_decay(float(base_activation), last_accessed, lambda_rate=lambda_rate)


def prune_low_activation(nodes: dict[str, dict[str, object]], threshold: float = 0.05) -> list[str]:
    to_prune: list[str] = []
    for node_id, node in nodes.items():
        activation = node.get("base_activation", 0.0)
        if isinstance(activation, (int, float)) and float(activation) < threshold:
            to_prune.append(node_id)
    return to_prune
