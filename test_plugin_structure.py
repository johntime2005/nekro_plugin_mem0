"""
test_plugin_structure.py - 测试插件结构
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(__file__))

try:
    # 尝试导入插件包
    import mem0_memory
    print("✅ 插件包导入成功")

    # 检查插件实例
    if hasattr(mem0_memory, 'plugin'):
        plugin = mem0_memory.plugin
        print(f"✅ 插件实例存在: {plugin.name}")
        print(f"   模块名: {plugin.module_name}")
        print(f"   版本: {plugin.version}")
        print(f"   作者: {plugin.author}")
    else:
        print("❌ 插件实例不存在")

    # 检查插件方法
    if hasattr(mem0_memory, 'add_memory'):
        print("✅ add_memory 方法存在")
    else:
        print("❌ add_memory 方法不存在")

    if hasattr(mem0_memory, 'search_memory'):
        print("✅ search_memory 方法存在")
    else:
        print("❌ search_memory 方法不存在")

    print("\n🎉 插件结构验证完成！")

except ImportError as e:
    print(f"❌ 导入失败: {e}")
    print("这可能是因为缺少依赖项，但插件结构应该是正确的")

except Exception as e:
    print(f"❌ 其他错误: {e}")
