"""记忆引擎路由调度"""
from typing import Dict, List, Any
from .memory_engine_base import get_engine
from .plugin import get_memory_config


async def route_search(query: str | None, **kwargs) -> List[Dict[str, Any]]:
    """路由搜索请求到对应引擎"""
    config = get_memory_config()
    engine_name = config.MEMORY_ENGINE

    try:
        engine_class = get_engine(engine_name)
        engine = engine_class(config)
        if hasattr(engine, 'initialize'):
            await engine.initialize()
        return engine.search_memory(query, **kwargs)
    except ValueError:
        # 引擎不存在，降级到 basic
        try:
            engine_class = get_engine("basic")
            engine = engine_class(config)
            if hasattr(engine, 'initialize'):
                await engine.initialize()
            return engine.search_memory(query, **kwargs)
        except ValueError:
            return []


async def route_add(memory: str, **kwargs) -> Dict[str, Any]:
    """路由添加请求到对应引擎"""
    config = get_memory_config()
    engine_name = config.MEMORY_ENGINE

    try:
        engine_class = get_engine(engine_name)
        engine = engine_class(config)
        if hasattr(engine, 'initialize'):
            await engine.initialize()
        return engine.add_memory(memory, **kwargs)
    except ValueError:
        try:
            engine_class = get_engine("basic")
            engine = engine_class(config)
            if hasattr(engine, 'initialize'):
                await engine.initialize()
            return engine.add_memory(memory, **kwargs)
        except ValueError:
            return {"ok": False, "error": "no engine available"}
