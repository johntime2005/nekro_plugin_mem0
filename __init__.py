"""
Nekro Agent 长期记忆插件
===========================
为 Agent 提供基于 mem0 的长期记忆能力，使其能够存储、检索和管理信息。
"""

from typing import List, Dict, Any, Optional
from nekro_agent.api.schemas import AgentCtx
from nekro_agent.core import logger
from nekro_agent.services.plugin.base import (
    ConfigBase,
    NekroPlugin,
    SandboxMethodType,
)
from pydantic import Field
from mem0 import Mem0

# 1. 定义插件实例
plugin = NekroPlugin(
    name="长期记忆插件",
    module_name="nekro-plugin-memory",
    description="为 Agent 提供基于 mem0 的长期记忆能力，使其能够存储、检索和管理信息。",
    version="1.1.0",
    author="johntime2005 & Copilot",
    url="https://github.com/johntime2005/nekro-plugin-memory",
)

# 2. 定义插件配置
@plugin.mount_config()
class MemoryConfig(ConfigBase):
    """长期记忆插件配置"""

    agent_id: str = Field(
        default="nekro-agent",
        title="Agent ID",
        description="用于隔离不同 Agent 记忆的唯一标识符。",
    )
    llm_model: str = Field(
        default="gpt-4o",
        title="LLM 模型",
        description="用于记忆处理和摘要的语言模型。",
    )
    embedding_model: str = Field(
        default="text-embedding-3-large",
        title="Embedding 模型",
        description="用于将文本向量化的嵌入模型。",
    )
    embedding_dims: int = Field(
        default=1536,
        title="Embedding 维度",
        description="指定嵌入模型的输出维度。例如，对于 text-embedding-004 使用 768，对于 text-embedding-3-large 使用 1536 或 3072。",
    )
    vector_store_provider: str = Field(
        default="qdrant",
        title="向量数据库提供商",
        description="支持 'qdrant', 'chroma' 等。",
    )
    qdrant_host: str = Field(
        default="localhost",
        title="Qdrant 主机地址",
        description="如果使用 Qdrant，请指定其主机地址。",
    )
    qdrant_port: int = Field(
        default=6333,
        title="Qdrant 端口",
        description="如果使用 Qdrant，请指定其端口。",
    )

# 3. 初始化 mem0 客户端
# 将客户端实例和配置存储在模块级别，以便在所有方法中访问
mem0_client: Optional[Mem0] = None
config: Optional[MemoryConfig] = None

@plugin.mount_init_method()
async def init_memory_client():
    """
    初始化 mem0 客户端。
    该函数会在 Nekro Agent 加载插件时自动执行。
    """
    global mem0_client, config
    config = plugin.get_config(MemoryConfig)
    
    logger.info("正在初始化长期记忆插件...")
    try:
        mem0_client = Mem0(
            agent_id=config.agent_id,
            llm_config={
                "model": config.llm_model,
            },
            embed_config={
                "model": config.embedding_model,
                "dims": config.embedding_dims,
            },
            vector_store_config={
                "provider": config.vector_store_provider,
                "config": {
                    "host": config.qdrant_host,
                    "port": config.qdrant_port,
                },
            },
        )
        logger.success("长期记忆插件初始化成功！")
    except Exception as e:
        logger.error(f"长期记忆插件初始化失败: {e}")
        mem0_client = None # 初始化失败时，确保客户端为 None

# 4. 挂载沙盒方法
@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="add_memory",
    description="【核心功能】向记忆库中添加一条新的信息。当需要记录关键事实、用户偏好或对话要点以备将来使用时调用此方法。",
)
async def add_memory(_ctx: AgentCtx, data: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Args:
        data (str): 需要记忆的核心信息内容。
        metadata (Optional[Dict[str, Any]], optional): 与该记忆相关的元数据，如来源、时间等。默认为 None。

    Returns:
        str: 记忆添加成功的确认信息或失败的错误提示。
    """
    if not mem0_client:
        return "错误：记忆客户端未初始化。"
    try:
        mem0_client.add(data, metadata=metadata)
        logger.info(f"成功添加记忆: {data}")
        return f"记忆已添加: {data}"
    except Exception as e:
        logger.error(f"添加记忆失败: {e}")
        return f"添加记忆时出错: {e}"

@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="search_memory",
    description="【核心功能】根据问题或关键词在记忆库中进行智能搜索。当需要从过去的记忆中寻找相关信息以回答问题或进行联想时调用。",
)
async def search_memory(_ctx: AgentCtx, query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Args:
        query (str): 用于搜索的查询语句或关键词。
        limit (int, optional): 返回最相关记忆的最大数量。默认为 5。

    Returns:
        List[Dict[str, Any]]: 搜索到的相关记忆列表，按相关性排序。
    """
    if not mem0_client:
        logger.error("记忆客户端未初始化，无法执行搜索。")
        return [{"error": "记忆客户端未初始化。"}]
    try:
        results = mem0_client.search(query, limit=limit)
        logger.info(f"为查询 '{query}' 找到 {len(results)} 条相关记忆。")
        return results
    except Exception as e:
        logger.error(f"搜索记忆失败: {e}")
        return [{"error": f"搜索记忆时出错: {e}"}]

@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="get_all_memories",
    description="【辅助功能】获取所有存储的记忆。用于调试或需要完整回顾所有记忆的场景。请注意，数据量可能很大。",
)
async def get_all_memories(_ctx: AgentCtx) -> List[Dict[str, Any]]:
    """
    Returns:
        List[Dict[str, Any]]: 包含所有记忆的列表。
    """
    if not mem0_client:
        logger.error("记忆客户端未初始化，无法获取所有记忆。")
        return [{"error": "记忆客户端未初始化。"}]
    try:
        memories = mem0_client.get_all()
        logger.info(f"成功获取 {len(memories)} 条记忆。")
        return memories
    except Exception as e:
        logger.error(f"获取所有记忆失败: {e}")
        return [{"error": f"获取所有记忆时出错: {e}"}]

@plugin.mount_sandbox_method(
    SandboxMethodType.AGENT,
    name="delete_memory",
    description="【管理功能】根据ID删除一条指定的记忆。用于修正错误的记忆或移除不再需要的信息。",
)
async def delete_memory(_ctx: AgentCtx, memory_id: str) -> str:
    """
    Args:
        memory_id (str): 要删除的记忆的唯一ID。

    Returns:
        str: 删除操作结果的确认信息。
    """
    if not mem0_client:
        return "错误：记忆客户端未初始化。"
    try:
        mem0_client.delete(memory_id)
        logger.info(f"成功删除记忆 ID: {memory_id}")
        return f"记忆 ID {memory_id} 已被删除。"
    except Exception as e:
        logger.error(f"删除记忆 ID {memory_id} 失败: {e}")
        return f"删除记忆 ID {memory_id} 时出错: {e}"
from .plugin import MemoryPlugin
from .plugin_method import MemoryPluginMethod

__all__ = ["MemoryPlugin", "MemoryPluginMethod"]
from pydantic import Field

# TODO: 插件元信息，请修改为你的插件信息
plugin = NekroPlugin(
    name="天气查询插件",  # TODO: 插件名称
    module_name="weather",  # TODO: 插件模块名 (如果要发布该插件，需要在 NekroAI 社区中唯一)
    description="提供指定城市的天气查询功能",  # TODO: 插件描述
    version="1.0.0",  # TODO: 插件版本
    author="KroMiose",  # TODO: 插件作者
    url="https://github.com/KroMiose/nekro-plugin-template",  # TODO: 插件仓库地址
)


# TODO: 插件配置，根据需要修改
@plugin.mount_config()
class WeatherConfig(ConfigBase):
    """天气查询配置"""

    API_URL: str = Field(
        default="https://wttr.in/",
        title="天气API地址",
        description="天气查询API的基础URL",
    )
    TIMEOUT: int = Field(
        default=10,
        title="请求超时时间",
        description="API请求的超时时间(秒)",
    )


# 获取配置实例
config: WeatherConfig = plugin.get_config(WeatherConfig)


@plugin.mount_sandbox_method(SandboxMethodType.AGENT, name="查询天气", description="查询指定城市的实时天气信息")
async def query_weather(_ctx: AgentCtx, city: str) -> str:
    """查询指定城市的实时天气信息。

    Args:
        city: 需要查询天气的城市名称，例如 "北京", "London"。

    Returns:
        str: 包含城市实时天气信息的字符串。查询失败时返回错误信息。

    Example:
        查询北京的天气:
        query_weather(city="北京")
        查询伦敦的天气:
        query_weather(city="London")
    """
    try:
        async with httpx.AsyncClient(timeout=config.TIMEOUT) as client:
            response = await client.get(f"{config.API_URL}{city}?format=j1")
            response.raise_for_status()
            data: Dict = response.json()

        # 提取需要的天气信息
        # wttr.in 的 JSON 结构可能包含 current_condition 列表
        if not data.get("current_condition"):
            logger.warning(f"城市 '{city}' 的天气数据格式不符合预期，缺少 'current_condition'")
            return f"未能获取到城市 '{city}' 的有效天气数据，请检查城市名称是否正确。"

        # 处理获取到的天气数据
        current_condition = data["current_condition"][0]
        temp_c = current_condition.get("temp_C")
        feels_like_c = current_condition.get("FeelsLikeC")
        humidity = current_condition.get("humidity")
        weather_desc_list = current_condition.get("weatherDesc", [])
        weather_desc = weather_desc_list[0].get("value") if weather_desc_list else "未知"
        wind_speed_kmph = current_condition.get("windspeedKmph")
        wind_dir = current_condition.get("winddir16Point")
        visibility = current_condition.get("visibility")
        pressure = current_condition.get("pressure")

        # 格式化返回结果
        result = (
            f"城市: {city}\n"
            f"天气状况: {weather_desc}\n"
            f"温度: {temp_c}°C\n"
            f"体感温度: {feels_like_c}°C\n"
            f"湿度: {humidity}%\n"
            f"风向: {wind_dir}\n"
            f"风速: {wind_speed_kmph} km/h\n"
            f"能见度: {visibility} km\n"
            f"气压: {pressure} hPa"
        )
        logger.info(f"已查询到城市 '{city}' 的天气")
    except Exception as e:
        # 捕获其他所有未知异常
        logger.exception(f"查询城市 '{city}' 天气时发生未知错误: {e}")
        return f"查询 '{city}' 天气时发生内部错误。"
    else:
        return result


@plugin.mount_cleanup_method()
async def clean_up():
    """清理插件资源"""
    # 如果有使用数据库连接、文件句柄或其他需要释放的资源，在此处添加清理逻辑
    logger.info("天气查询插件资源已清理。")
