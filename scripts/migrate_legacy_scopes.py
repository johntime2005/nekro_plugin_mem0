from __future__ import annotations

import argparse
import asyncio
import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LAYER_KEY_MAP = {
    "global": "user_id",
    "persona": "agent_id",
    "conversation": "run_id",
}


@dataclass
class ScopeStats:
    layer: str
    value: str
    target_existing: int = 0
    legacy_sources_checked: int = 0
    legacy_records_seen: int = 0
    candidate_records: int = 0
    skipped_duplicate: int = 0
    migrated: int = 0
    errors: List[str] = field(default_factory=list)


def _normalize_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _get_preset_id(chat_key: Optional[str]) -> str:
    if not chat_key:
        return "default"
    return base64.urlsafe_b64encode(chat_key.encode()).decode()


def _decode_id(encoded: str) -> str:
    return base64.urlsafe_b64decode(encoded.encode()).decode()


def _memory_identifier(item: Dict[str, Any]) -> Optional[str]:
    for key in ("id", "memory_id"):
        value = item.get(key)
        if value:
            return str(value)
    return None


def _build_legacy_value_candidates(layer: str, value: Optional[str]) -> List[str]:
    normalized = _normalize_value(value)
    if not normalized:
        return []

    candidates: List[str] = [normalized]

    if layer == "global":
        if normalized.startswith("private_") and normalized[8:].isdigit():
            candidates.append(normalized[8:])
        elif normalized.isdigit():
            candidates.append(f"private_{normalized}")

    if layer == "persona":
        if normalized.startswith("preset:"):
            raw = normalized.split(":", 1)[1]
            if raw:
                candidates.append(raw)
        else:
            candidates.append(f"preset:{normalized}")

    if layer == "conversation":
        try:
            decoded = _decode_id(normalized)
            if decoded:
                candidates.append(decoded)
                candidates.append(_get_preset_id(decoded))
        except Exception:
            pass

    deduped: List[str] = []
    for item in candidates:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _build_layer_ids(layer: str, value: str) -> Dict[str, Optional[str]]:
    key = LAYER_KEY_MAP[layer]
    ids: Dict[str, Optional[str]] = {
        "layer": layer,
        "user_id": None,
        "agent_id": None,
        "run_id": None,
    }
    ids[key] = value
    return ids


def _build_legacy_layer_variants(
    layer: str, value: str
) -> List[Dict[str, Optional[str]]]:
    variants: List[Dict[str, Optional[str]]] = []
    for candidate in _build_legacy_value_candidates(layer, value):
        variants.append(_build_layer_ids(layer, candidate))

    deduped: List[Dict[str, Optional[str]]] = []
    seen: Set[Tuple[Optional[str], Optional[str], Optional[str]]] = set()
    for item in variants:
        fp = (item.get("user_id"), item.get("agent_id"), item.get("run_id"))
        if fp in seen:
            continue
        seen.add(fp)
        deduped.append(item)
    return deduped


def _query_kwargs(layer_ids: Dict[str, Optional[str]]) -> Dict[str, str]:
    query: Dict[str, str] = {}
    for key in ("user_id", "agent_id", "run_id"):
        value = layer_ids.get(key)
        if value is not None:
            query[key] = value
    return query


def _iter_values(single_values: List[str], values_file: Optional[str]) -> List[str]:
    values: List[str] = []
    values.extend([v.strip() for v in single_values if v.strip()])

    if values_file:
        file_path = Path(values_file)
        if not file_path.exists():
            raise FileNotFoundError(f"values file not found: {values_file}")
        for line in file_path.read_text(encoding="utf-8").splitlines():
            normalized = line.strip()
            if normalized and not normalized.startswith("#"):
                values.append(normalized)

    deduped: List[str] = []
    for item in values:
        if item not in deduped:
            deduped.append(item)
    return deduped


async def _migrate_one_scope(
    *,
    client: Any,
    layer: str,
    value: str,
    dry_run: bool,
) -> ScopeStats:
    stats = ScopeStats(layer=layer, value=value)
    target_ids = _build_layer_ids(layer, value)
    target_kwargs = _query_kwargs(target_ids)
    target_fp = (
        target_ids.get("user_id"),
        target_ids.get("agent_id"),
        target_ids.get("run_id"),
    )

    target_records = await asyncio.to_thread(client.get_all, **target_kwargs)
    target_records = list(target_records or [])
    stats.target_existing = len(target_records)

    existing_ids: Set[str] = set()
    existing_source_ids: Set[str] = set()
    existing_texts: Set[str] = set()
    for item in target_records:
        memory_id = _memory_identifier(item)
        if memory_id:
            existing_ids.add(memory_id)
        metadata = item.get("metadata") or {}
        source_memory_id = metadata.get("_source_memory_id")
        if source_memory_id:
            existing_source_ids.add(str(source_memory_id))
        text = item.get("memory") or item.get("text") or item.get("content") or ""
        normalized_text = str(text).strip()
        if normalized_text:
            existing_texts.add(normalized_text)

    candidates: List[Dict[str, Any]] = []
    seen_candidate_keys: Set[str] = set()

    for variant in _build_legacy_layer_variants(layer, value):
        fp = (
            variant.get("user_id"),
            variant.get("agent_id"),
            variant.get("run_id"),
        )
        if fp == target_fp:
            continue

        stats.legacy_sources_checked += 1
        legacy_kwargs = _query_kwargs(variant)
        legacy_records = await asyncio.to_thread(client.get_all, **legacy_kwargs)
        for item in list(legacy_records or []):
            stats.legacy_records_seen += 1
            source_id = _memory_identifier(item)
            text = item.get("memory") or item.get("text") or item.get("content") or ""
            normalized_text = str(text).strip()
            if not normalized_text:
                stats.skipped_duplicate += 1
                continue

            dedup_key = (
                f"source:{source_id}" if source_id else f"text:{normalized_text}"
            )
            if dedup_key in seen_candidate_keys:
                stats.skipped_duplicate += 1
                continue

            if source_id and source_id in existing_source_ids:
                stats.skipped_duplicate += 1
                continue
            if source_id and source_id in existing_ids:
                stats.skipped_duplicate += 1
                continue
            if normalized_text in existing_texts:
                stats.skipped_duplicate += 1
                continue

            seen_candidate_keys.add(dedup_key)
            copied = dict(item)
            copied["_migration_source_scope"] = variant
            copied["_migration_source_id"] = source_id
            copied["_migration_text"] = normalized_text
            candidates.append(copied)

    stats.candidate_records = len(candidates)

    if dry_run:
        return stats

    for item in candidates:
        metadata = dict(item.get("metadata") or {})
        metadata.setdefault("_migrated_from_legacy_scope", True)
        source_id = item.get("_migration_source_id")
        if source_id:
            metadata.setdefault("_source_memory_id", str(source_id))
        metadata.setdefault(
            "_migration_from_scope",
            json.dumps(item.get("_migration_source_scope"), ensure_ascii=False),
        )
        metadata.setdefault("_migration_at", datetime.now(timezone.utc).isoformat())

        add_kwargs: Dict[str, Any] = {"metadata": metadata, "infer": False}
        add_kwargs.update(target_kwargs)

        try:
            migrated_text = str(item.get("_migration_text") or "").strip()
            if not migrated_text:
                continue
            await asyncio.to_thread(client.add, migrated_text, **add_kwargs)
            stats.migrated += 1
            existing_texts.add(migrated_text)
            if source_id:
                existing_source_ids.add(str(source_id))
        except Exception as exc:
            stats.errors.append(str(exc))

    return stats


def _print_report(all_stats: Iterable[ScopeStats], dry_run: bool) -> None:
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"\n=== Legacy Scope Migration Report ({mode}) ===")

    total_scopes = 0
    total_candidates = 0
    total_migrated = 0
    total_skipped = 0
    total_errors = 0

    for item in all_stats:
        total_scopes += 1
        total_candidates += item.candidate_records
        total_migrated += item.migrated
        total_skipped += item.skipped_duplicate
        total_errors += len(item.errors)
        print(
            "- "
            f"{item.layer}:{item.value} | "
            f"target_existing={item.target_existing}, "
            f"legacy_sources={item.legacy_sources_checked}, "
            f"legacy_seen={item.legacy_records_seen}, "
            f"candidates={item.candidate_records}, "
            f"skipped={item.skipped_duplicate}, "
            f"migrated={item.migrated}, "
            f"errors={len(item.errors)}"
        )
        for err in item.errors[:3]:
            print(f"    error: {err}")

    print("---")
    print(
        f"summary: scopes={total_scopes}, candidates={total_candidates}, "
        f"migrated={total_migrated}, skipped={total_skipped}, errors={total_errors}"
    )


async def _amain(args: argparse.Namespace) -> int:
    from mem0_utils import get_mem0_client

    values = _iter_values(args.value, args.values_file)
    if not values:
        raise ValueError("no scope values provided; use --value or --values-file")

    client = await get_mem0_client()
    if client is None:
        raise RuntimeError(
            "mem0 client init failed; check plugin model/vector settings"
        )

    all_stats: List[ScopeStats] = []
    for value in values:
        stats = await _migrate_one_scope(
            client=client,
            layer=args.layer,
            value=value,
            dry_run=(not args.apply),
        )
        all_stats.append(stats)

    _print_report(all_stats, dry_run=(not args.apply))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate legacy-scoped memories into current scope ids"
    )
    parser.add_argument(
        "--layer",
        required=True,
        choices=["global", "persona", "conversation"],
        help="Target scope layer to migrate into",
    )
    parser.add_argument(
        "--value",
        action="append",
        default=[],
        help="Target scope value (repeatable)",
    )
    parser.add_argument(
        "--values-file",
        default=None,
        help="Path of text file containing scope values (one per line)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write migrated records (default is dry-run)",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
