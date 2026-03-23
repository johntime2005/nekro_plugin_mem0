# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

nekro-plugin-mem0 is a long-term memory plugin for Nekro Agent, providing persistent memory capabilities across conversations using mem0 v1.0. The plugin supports multiple memory engines, intelligent deduplication, and multi-layer memory architecture.

## Development Setup

```bash
# Install dependencies
poetry install

# Run tests
python test_pre_search.py
python test_memory_scope_risks.py
```

## Architecture

### Memory Engine System

The plugin uses a **router pattern** to support three different memory engines:

1. **Basic Engine** (`memory_engine_basic.py`): Vector search using embeddings (default, backward compatible)
2. **HippoRAG Engine** (`memory_engine_hippo.py`): Knowledge graph with Personalized PageRank for multi-hop reasoning
3. **EMGAS Engine** (`memory_engine_emgas.py`): Activation spreading with temporal decay modeling human memory

Engine selection is controlled by `MEMORY_ENGINE` config parameter. The router (`memory_engine_router.py`) automatically falls back to Basic engine if the selected engine fails.

**Engine Registration**: Engines register themselves using the `@register_engine(name)` decorator in `memory_engine_base.py`. All engines must implement `add_memory()` and `search_memory()` methods.

### Multi-Layer Memory Architecture

Based on mem0 v1.0's layered approach:

- **conversation**: Session-specific memories (isolated by `run_id`)
- **persona**: Agent-level memories (shared across sessions, isolated by `agent_id` + optionally `user_id`)
- **global**: Cross-agent memories (shared across all agents for a user)

Scope resolution is handled by `resolve_memory_scope()` in `utils.py`, which constructs scope identifiers from `user_id`, `agent_id`, and `run_id` combinations.

### Memory Deduplication Pipeline

Two-stage deduplication in `plugin_method.py`:

1. **SimHash pre-filter** (`dedup_simhash.py`): Fast Hamming distance check (threshold: `DEDUP_SIMHASH_THRESHOLD`, default 10)
2. **Similarity scoring** (`dedup_similarity.py`): Multi-metric scoring combining embedding cosine similarity, Jaccard similarity, and length ratio (threshold: `DEDUP_SIMILARITY_THRESHOLD`, default 0.8)

### Pre-Search System

Automatic memory retrieval before LLM processing (`pre_search_utils.py`):

- Builds queries from recent conversation history
- Optional LLM-based query rewriting (`query_rewrite.py`) with skip detection for non-semantic queries
- Timeout-aware with partial result fallback (`PRE_SEARCH_TIMEOUT`, default 0.8s)
- Can skip conversation layer to avoid redundant retrieval (`PRE_SEARCH_SKIP_CONVERSATION`)

### Passive Memory Extraction

Automatic extraction from conversation history (`plugin_method.py`):

- Triggered every N turns (`AUTO_EXTRACT_INTERVAL`, default 3)
- Uses `ENHANCED_MEMORY_PROMPT` from `extraction_prompts.py`
- Parses structured output via `extraction_parser.py`
- Extracts 7 priority types: preferences, personal, interests, habits, skills, relationships, factual

### Memory Types

13 memory types defined in `enhanced_memory.py`:
FACTS, PREFERENCES, GOALS, TRAITS, RELATIONSHIPS, EVENTS, TOPICS, CONTEXTUAL, TEMPORAL, TASK, SKILL, INTEREST, LOCATION

Each memory has:
- `content`: Text content
- `type`: MemoryType enum
- `importance`: 1-10 score
- `expiration_date`: Optional ISO8601 timestamp
- `metadata`: Arbitrary key-value pairs

## Key Configuration Parameters

**Critical settings in `plugin.py`**:

- `MEMORY_ENGINE`: "basic" | "hippo" | "emgas"
- `SESSION_ISOLATION`: Controls whether searches are scoped to current session
- `ENABLE_AGENT_SCOPE`: Enables cross-session agent-level memories
- `PERSONA_BIND_USER`: Binds persona layer to both user_id + agent_id (prevents memory leakage between users)
- `LEGACY_SCOPE_FALLBACK_ENABLED`: Backward compatibility for old scope format
- `DEDUP_ENABLED`: Toggle deduplication pipeline
- `AUTO_EXTRACT_ENABLED`: Toggle passive extraction
- `QUERY_REWRITE_ENABLED`: Toggle LLM query rewriting (adds latency)

## API Functions

All functions in `plugin_method.py` support two calling patterns:

1. **Sandbox mode** (within Nekro Agent): First parameter is `_ctx` (injected by runtime)
2. **Standalone mode**: First parameter is `None`, must provide explicit scope identifiers

Key functions:
- `add_memory()`: Non-blocking async write
- `search_memory()`: Blocking semantic search (use for specific queries, NOT for "list all")
- `get_all_memory()`: Retrieve all memories in scope (use for enumeration)
- `update_memory()`: Update memory content
- `update_memory_metadata()`: Update metadata only (importance, expiration, TYPE)
- `delete_memory()`: Delete single memory
- `delete_all_memory()`: Dangerous bulk delete

**Important**: `search_memory()` is for semantic queries only. Use `get_all_memory()` for listing all memories.

## HippoRAG Engine Details

Knowledge graph construction:
- Entity extraction via `hippo_entity_extraction.py`
- Alias merging using Jaccard similarity (`hippo_alias_merge.py`, threshold ≥ 0.85)
- PPR computation in `hippo_pagerank.py`
- Hybrid scoring: `HIPPO_HYBRID_WEIGHT × semantic_score + (1 - HIPPO_HYBRID_WEIGHT) × ppr_score`

Graph persisted to JSON for incremental updates.

## EMGAS Engine Details

Temporal decay and spreading:
- `emgas_decay.py`: Exponential decay `activation × e^(-λ × Δt_hours)`
- `emgas_spreading.py`: Energy propagation with firing threshold
- `emgas_ppmi.py`: PPMI-weighted edges based on co-occurrence
- Pruning: Removes nodes below `EMGAS_PRUNE_THRESHOLD`

## Testing Notes

- `test_pre_search.py`: Tests query building and message cleaning
- `test_memory_scope_risks.py`: Tests scope isolation and security

When adding tests, ensure they cover scope isolation to prevent memory leakage between users/agents.

## Common Pitfalls

1. **Scope confusion**: Always verify whether `PERSONA_BIND_USER` is enabled when debugging cross-user memory issues
2. **Search vs Get All**: Don't use `search_memory("all memories")` - use `get_all_memory()` instead
3. **Context parameter**: In standalone scripts, pass `None` as first parameter, not `_ctx`
4. **Engine fallback**: Router silently falls back to Basic engine on errors - check logs
5. **Deduplication timing**: Dedup happens before write, so similar memories may be rejected silently
