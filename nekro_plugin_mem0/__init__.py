"""
导出插件实例
"""

from .plugin import plugin
# 导入插件方法以确保沙盒方法被注册
from . import plugin_method  # noqa: F401

__all__ = ["plugin"]
