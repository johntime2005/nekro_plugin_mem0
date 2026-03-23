"""
导出插件实例
"""

import sys
import subprocess
import importlib.util


def _check_and_install_dependencies():
    try:
        required_modules = ("mem0ai", "pydantic_settings", "loguru")
        missing = [
            name for name in required_modules if importlib.util.find_spec(name) is None
        ]
        if not missing:
            return
        print(
            "nekro_plugin_mem0: 缺少必要依赖，正在自动下载安装 mem0ai 及相关依赖...",
            file=sys.stderr,
        )
        try:
            subprocess.check_call(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "mem0ai>=1.0.1",
                    "pydantic-settings>=2.3.4",
                    "loguru>=0.7.2",
                ]
            )
            print("nekro_plugin_mem0: 依赖自动安装完成！", file=sys.stderr)
        except subprocess.CalledProcessError as e:
            print(
                "nekro_plugin_mem0: 自动安装依赖失败，请手动在终端运行：pip install mem0ai>=1.0.1 pydantic-settings>=2.3.4 loguru>=0.7.2",
                file=sys.stderr,
            )
            print(
                f"nekro_plugin_mem0: 将以降级模式继续加载（记忆功能可能不可用）: {e}",
                file=sys.stderr,
            )
    except Exception as e:
        print(f"nekro_plugin_mem0: 依赖检查异常，降级继续加载: {e}", file=sys.stderr)


_check_and_install_dependencies()

from .plugin import plugin

# 导入插件方法以确保沙盒方法被注册
from . import plugin_method  # noqa: F401

# 导入引擎以触发注册
from . import memory_engine_basic  # noqa: F401
from . import memory_engine_hippo  # noqa: F401
from . import memory_engine_emgas  # noqa: F401

__all__ = ["plugin"]
