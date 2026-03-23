import re
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None


def parse_extracted_memories(response: str) -> list[dict[str, Any]]:
    if yaml is None:
        return []
    yaml_match = re.search(r"```(?:yaml)?\s*\n(.*?)\n```", response, re.DOTALL)
    if not yaml_match:
        return []

    try:
        data = yaml.safe_load(yaml_match.group(1))
    except yaml.YAMLError:
        return []

    if not isinstance(data, dict) or "memories" not in data:
        return []

    memories = data["memories"]
    if not isinstance(memories, list):
        return []

    result = []
    for memory in memories:
        if (
            not isinstance(memory, dict)
            or "content" not in memory
            or not memory["content"]
        ):
            continue

        importance = memory.get("importance", 5)
        try:
            importance = int(importance)
            if not (1 <= importance <= 10):
                importance = 5
        except (ValueError, TypeError):
            importance = 5

        result.append(
            {
                "content": memory["content"],
                "type": memory.get("type", "contextual"),
                "importance": importance,
            }
        )

    return result
