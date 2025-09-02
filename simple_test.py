"""
simple_test.py - 简单包结构测试
"""

import sys
sys.path.insert(0, '.')

# 检查包结构
try:
    import mem0_memory
    print('✅ mem0_memory 包导入成功')

    # 检查 __init__.py 是否存在 plugin
    if hasattr(mem0_memory, '__file__'):
        print(f'包文件位置: {mem0_memory.__file__}')

    # 检查是否能访问 plugin 模块
    from mem0_memory import plugin as plugin_module
    print('✅ plugin 模块导入成功')

    print('🎉 包结构验证通过！')

except ImportError as e:
    print(f'❌ 导入失败: {e}')
except Exception as e:
    print(f'❌ 其他错误: {e}')
    import traceback
    traceback.print_exc()
