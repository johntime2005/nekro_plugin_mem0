"""
插件方法
"""

from typing import Any, Dict, List, Optional
from nekro_agent.api.schemas import AgentCtx
from nekro_agent.core import logger
from nekro_agent.services.plugin.base import SandboxMethodType
from nekro_agent.schemas.chat_message import ChatMessage
from nekro_agent.schemas.signal import MsgSignal
from .mem0_output_formatter import (
    format_add_output,
    format_get_all_output,
    format_history_output,
    format_history_text,
    format_search_output,
    _format_memory_list,
)
from .mem0_utils import get_mem0_client
from .plugin import get_memory_config, plugin
from .utils import resolve_memory_scope


@plugin.mount_init_method()
async def init_plugin() -> None:
    logger.info("记忆插件初始化中...")


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="添加记忆",
    description="为用户的个人资料添加一条新记忆，添加的记忆与该用户相关",
)
async def add_memory(
    _ctx: AgentCtx,
    memory: Any,
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    scope = resolve_memory_scope(_ctx, user_id=user_id, agent_id=agent_id, run_id=run_id)
    if not scope.has_scope():
        return {"ok": False, "error": "缺少 user_id/agent_id/run_id，无法写入记忆"}

    result = client.add(
        memory,
        user_id=scope.user_id,
        agent_id=scope.persona_id if plugin_config.ENABLE_AGENT_SCOPE else None,
        run_id=scope.run_id,
        metadata=metadata or {},
    )
    return format_add_output(result)


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="搜索记忆",
    description="根据查询语句搜索用户记忆",
)
async def search_memory(
    _ctx: AgentCtx,
    query: str,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = 5,
) -> Dict[str, Any]:
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    scope = resolve_memory_scope(_ctx, user_id=user_id, agent_id=agent_id, run_id=run_id)
    if not scope.has_scope():
        return {"ok": False, "error": "缺少 user_id/agent_id/run_id，无法搜索记忆"}

    search_run_id = scope.run_id if plugin_config.SESSION_ISOLATION or not (scope.user_id or scope.agent_id) else None
    search_agent_id = scope.persona_id if plugin_config.ENABLE_AGENT_SCOPE else None

    if not any([scope.user_id, search_agent_id, search_run_id]):
        return {"ok": False, "error": "缺少可用的 user_id/agent_id/run_id"}

    raw_results = client.search(
        query,
        user_id=scope.user_id,
        agent_id=search_agent_id,
        run_id=search_run_id,
        limit=limit,
        threshold=plugin_config.MEMORY_SEARCH_SCORE_THRESHOLD,
    )
    formatted = format_search_output(raw_results, threshold=plugin_config.MEMORY_SEARCH_SCORE_THRESHOLD)
    return {"ok": True, **formatted}


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="获取记忆列表",
    description="获取指定作用域（user/agent/run）的全部记忆，可按标签过滤",
)
async def get_all_memory(
    _ctx: AgentCtx,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    scope = resolve_memory_scope(_ctx, user_id=user_id, agent_id=agent_id, run_id=run_id)
    if not scope.has_scope():
        return {"ok": False, "error": "缺少 user_id/agent_id/run_id，无法获取记忆"}

    results = client.get_all(
        user_id=scope.user_id,
        agent_id=scope.persona_id if plugin_config.ENABLE_AGENT_SCOPE else None,
        run_id=scope.run_id if plugin_config.SESSION_ISOLATION else None,
    )
    formatted = format_get_all_output(results, tags=tags)
    return {"ok": True, **formatted}


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="更新记忆",
    description="根据记忆ID更新记忆内容",
)
async def update_memory(
    _ctx: AgentCtx,
    memory_id: str,
    new_memory: str,
) -> Dict[str, Any]:
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    try:
        result = client.update(memory_id, new_memory)
    except Exception as exc:  # pragma: no cover - mem0内部异常透出
        logger.error(f"更新记忆失败: {exc}")
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "result": result}


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="删除记忆",
    description="根据记忆ID删除单条记忆",
)
async def delete_memory(
    _ctx: AgentCtx,
    memory_id: str,
) -> Dict[str, Any]:
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    try:
        result = client.delete(memory_id)
    except Exception as exc:  # pragma: no cover
        logger.error(f"删除记忆失败: {exc}")
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "result": result}


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="删除作用域记忆",
    description="删除指定 user/agent/run 对应的全部记忆",
)
async def delete_all_memory(
    _ctx: AgentCtx,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    plugin_config = get_memory_config()
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    scope = resolve_memory_scope(_ctx, user_id=user_id, agent_id=agent_id, run_id=run_id)
    if not scope.has_scope():
        return {"ok": False, "error": "缺少 user_id/agent_id/run_id，无法删除记忆"}

    try:
        client.delete_all(
            user_id=scope.user_id,
            agent_id=scope.persona_id if plugin_config.ENABLE_AGENT_SCOPE else None,
            run_id=scope.run_id if plugin_config.SESSION_ISOLATION else None,
        )
    except Exception as exc:  # pragma: no cover
        logger.error(f"删除全部记忆失败: {exc}")
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "message": "已删除指定作用域记忆"}


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="获取记忆历史",
    description="查看指定记忆的历史版本",
)
async def get_memory_history(
    _ctx: AgentCtx,
    memory_id: str,
) -> Dict[str, Any]:
    client = await get_mem0_client()
    if client is None:
        return {"ok": False, "error": "mem0 client init failed"}

    try:
        results = client.history(memory_id)
    except Exception as exc:  # pragma: no cover
        logger.error(f"获取记忆历史失败: {exc}")
        return {"ok": False, "error": str(exc)}

    history_list = format_history_output(results)
    return {"ok": True, "results": history_list, "text": format_history_text(history_list)}


@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="记忆指令面板",
    description="提供命令式入口，便于在后台/网页操作：支持 add/search/list/update/delete/delete_all/history",
)
async def memory_command(
    _ctx: AgentCtx,
    action: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """统一命令入口，便于上层做网页/后台交互调用。"""
    payload = payload or {}
    action = (action or "").lower()

    if action == "add":
        return await add_memory(
            _ctx,
            memory=payload.get("memory"),
            user_id=payload.get("user_id"),
            metadata=payload.get("metadata"),
            agent_id=payload.get("agent_id"),
            run_id=payload.get("run_id"),
        )
    if action == "search":
        resp = await search_memory(
            _ctx,
            query=payload.get("query", ""),
            user_id=payload.get("user_id"),
            agent_id=payload.get("agent_id"),
            run_id=payload.get("run_id"),
            limit=payload.get("limit", 5),
        )
        if resp.get("ok"):
            resp["text"] = resp.get("text") or _format_memory_list(resp.get("results", []))
        return resp
    if action == "list":
        resp = await get_all_memory(
            _ctx,
            user_id=payload.get("user_id"),
            agent_id=payload.get("agent_id"),
            run_id=payload.get("run_id"),
            tags=payload.get("tags"),
        )
        return resp
    if action == "update":
        return await update_memory(
            _ctx,
            memory_id=payload.get("memory_id", ""),
            new_memory=payload.get("new_memory", ""),
        )
    if action == "delete":
        return await delete_memory(_ctx, memory_id=payload.get("memory_id", ""))
    if action == "delete_all":
        return await delete_all_memory(
            _ctx,
            user_id=payload.get("user_id"),
            agent_id=payload.get("agent_id"),
            run_id=payload.get("run_id"),
        )
    if action == "history":
        return await get_memory_history(_ctx, memory_id=payload.get("memory_id", ""))

    return {"ok": False, "error": f"未知操作: {action}"}


async def _send_feedback(_ctx: AgentCtx, text: str) -> None:
    if hasattr(_ctx, "ms") and getattr(_ctx, "chat_key", None):
        try:
            await _ctx.ms.send_text(_ctx.chat_key, text, _ctx)
        except Exception:
            logger.warning("发送命令反馈失败，但命令已处理")


def _build_help() -> str:
    return "\n".join(
        [
            "记忆命令用法（/mem 开头）：",
            "/mem add <user_id> <记忆文本>",
            "/mem search <user_id> <查询>",
            "/mem list <user_id>",
            "/mem update <memory_id> <新内容>",
            "/mem delete <memory_id>",
            "/mem delete_all <user_id>",
            "/mem history <memory_id>",
        ]
    )


@plugin.mount_on_user_message()
async def on_message(_ctx: AgentCtx, chatmessage: ChatMessage) -> MsgSignal:
    msg = (chatmessage.content_text or "").strip()
    if not msg.startswith("/mem"):
        return MsgSignal.CONTINUE

    parts = msg.split()
    if len(parts) < 2:
        await _send_feedback(_ctx, _build_help())
        return MsgSignal.BLOCK_ALL

    action = parts[1].lower()
    payload: Dict[str, Any] = {}

    if action == "add" and len(parts) >= 4:
        payload = {"user_id": parts[2], "memory": " ".join(parts[3:])}
        result = await add_memory(_ctx, **payload)
        await _send_feedback(_ctx, "添加成功" if result.get("ok") else f"添加失败：{result.get('error')}")
    elif action == "search" and len(parts) >= 4:
        payload = {"user_id": parts[2], "query": " ".join(parts[3:])}
        result = await search_memory(_ctx, **payload)
        text = result.get("text") or f"搜索失败：{result.get('error')}"
        await _send_feedback(_ctx, text)
    elif action == "list" and len(parts) >= 3:
        payload = {"user_id": parts[2]}
        result = await get_all_memory(_ctx, **payload)
        text = result.get("text") or f"查询失败：{result.get('error')}"
        await _send_feedback(_ctx, text)
    elif action == "update" and len(parts) >= 4:
        payload = {"memory_id": parts[2], "new_memory": " ".join(parts[3:])}
        result = await update_memory(_ctx, **payload)
        await _send_feedback(_ctx, "更新成功" if result.get("ok") else f"更新失败：{result.get('error')}")
    elif action == "delete" and len(parts) >= 3:
        payload = {"memory_id": parts[2]}
        result = await delete_memory(_ctx, **payload)
        await _send_feedback(_ctx, "删除成功" if result.get("ok") else f"删除失败：{result.get('error')}")
    elif action == "delete_all" and len(parts) >= 3:
        payload = {"user_id": parts[2]}
        result = await delete_all_memory(_ctx, **payload)
        await _send_feedback(_ctx, "已清空该用户记忆" if result.get("ok") else f"清空失败：{result.get('error')}")
    elif action == "history" and len(parts) >= 3:
        payload = {"memory_id": parts[2]}
        result = await get_memory_history(_ctx, **payload)
        text = result.get("text") or f"获取历史失败：{result.get('error')}"
        await _send_feedback(_ctx, text)
    else:
        await _send_feedback(_ctx, _build_help())

    return MsgSignal.BLOCK_ALL


@plugin.mount_prompt_inject_method(
    name="memory_layer_hint",
    description="为LLM注入可用的长期记忆能力提示，包含跨用户/Agent/会话的存取方式",
)
async def inject_memory_prompt(_ctx: AgentCtx) -> str:
    config = get_memory_config()
    lines = [
        "你可以使用记忆插件在多个会话间维持用户/Agent的长期记忆。",
        "写入记忆：调用 add_memory(memory, user_id, agent_id?, run_id?, metadata?)。metadata 可带标签帮助分类。",
        "检索记忆：调用 search_memory(query, user_id?, agent_id?, run_id?, limit?)，默认会结合会话隔离与相似度阈值。",
        "更新记忆：调用 update_memory(memory_id, new_memory)，用于修订已存知识。",
        "删除记忆：调用 delete_memory(memory_id) 删除单条，或 delete_all_memory(user_id?, agent_id?, run_id?) 清空作用域。",
        f"当前相似度阈值: {config.MEMORY_SEARCH_SCORE_THRESHOLD}。",
    ]

    if config.ENABLE_AGENT_SCOPE:
        lines.append("已启用人设/Agent 级记忆：同一人设在多会话间共享，未提供 user_id 时将自动落在人设层。")
    else:
        lines.append("未启用人设级记忆：记忆主要按用户/会话维度隔离。")

    if config.SESSION_ISOLATION:
        lines.append("已启用会话隔离：检索时优先限定 run_id（会话层），确保结果贴合当前对话。")
    else:
        lines.append("已关闭会话隔离：检索会聚合用户/Agent 级记忆，便于跨会话互通。")

    lines.append("run_id 会被安全编码存储，可放心跨实例迁移。")
    return "\n".join(lines)
