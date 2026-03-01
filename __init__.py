"""
导出插件实例
"""

import sys
import subprocess

def _check_and_install_dependencies():
    try:
        import mem0ai
        import pydantic_settings
        import loguru
    except ImportError:
        print("nekro_plugin_mem0: 缺少必要依赖，正在自动下载安装 mem0ai 及相关依赖...", file=sys.stderr)
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", 
                "mem0ai>=1.0.1", "pydantic-settings>=2.3.4", "loguru>=0.7.2"
            ])
            print("nekro_plugin_mem0: 依赖自动安装完成！", file=sys.stderr)
        except subprocess.CalledProcessError as e:
            print("nekro_plugin_mem0: 自动安装依赖失败，请手动在终端运行：pip install mem0ai>=1.0.1 pydantic-settings>=2.3.4 loguru>=0.7.2", file=sys.stderr)
            raise e

_check_and_install_dependencies()

from .plugin import plugin
# 导入插件方法以确保沙盒方法被注册
from . import plugin_method  # noqa: F401

__all__ = ["plugin"]
