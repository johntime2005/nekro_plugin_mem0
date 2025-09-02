"""
test_plugin_mock.py - 使用模拟对象测试插件
"""

import sys
import types

# 模拟 nekro_agent 模块
nekro_agent = types.ModuleType('nekro_agent')
nekro_agent.core = types.ModuleType('nekro_agent.core')
nekro_agent.services = types.ModuleType('nekro_agent.services')
nekro_agent.models = types.ModuleType('nekro_agent.models')
nekro_agent.schemas = types.ModuleType('nekro_agent.schemas')
nekro_agent.api = types.ModuleType('nekro_agent.api')

# 模拟必要的类和函数
class MockConfig:
    pass

class MockLogger:
    @staticmethod
    def info(msg): pass
    @staticmethod
    def error(msg): pass
    @staticmethod
    def success(msg): pass

class MockBase:
    pass

class MockNekroPlugin:
    def __init__(self, **kwargs):
        self.name = kwargs.get('name', 'Mock Plugin')
        self.module_name = kwargs.get('module_name', 'mock')
        self.version = kwargs.get('version', '1.0.0')
        self.author = kwargs.get('author', 'mock')

    def mount_init_method(self, func):
        return func

    def mount_sandbox_method(self, method_type, **kwargs):
        def decorator(func):
            return func
        return decorator

# 添加到 sys.modules
sys.modules['nekro_agent'] = nekro_agent
sys.modules['nekro_agent.core'] = nekro_agent.core
sys.modules['nekro_agent.core.config'] = nekro_agent.core
sys.modules['nekro_agent.core.logger'] = nekro_agent.core
sys.modules['nekro_agent.services'] = nekro_agent.services
sys.modules['nekro_agent.services.plugin'] = nekro_agent.services
sys.modules['nekro_agent.services.plugin.base'] = nekro_agent.services
sys.modules['nekro_agent.models'] = nekro_agent.models
sys.modules['nekro_agent.models.db_chat_channel'] = nekro_agent.models
sys.modules['nekro_agent.models.db_chat_message'] = nekro_agent.models
sys.modules['nekro_agent.schemas'] = nekro_agent.schemas
sys.modules['nekro_agent.schemas.chat_message'] = nekro_agent.schemas
sys.modules['nekro_agent.schemas.signal'] = nekro_agent.schemas
sys.modules['nekro_agent.api'] = nekro_agent.api
sys.modules['nekro_agent.api.schemas'] = nekro_agent.api

# 设置模拟对象
nekro_agent.core.config = MockConfig()
nekro_agent.core.logger = MockLogger()
nekro_agent.services.base = MockBase()
nekro_agent.services.plugin.base.ConfigBase = MockBase
nekro_agent.services.plugin.base.NekroPlugin = MockNekroPlugin
nekro_agent.services.plugin.base.SandboxMethodType = type('SandboxMethodType', (), {'AGENT': 'agent'})()
nekro_agent.models.db_chat_channel.DBChatChannel = MockBase
nekro_agent.models.db_chat_message.DBChatMessage = MockBase
nekro_agent.schemas.chat_message.ChatMessage = MockBase
nekro_agent.schemas.signal.MsgSignal = MockBase
nekro_agent.api.schemas.AgentCtx = MockBase

# 现在测试插件导入
try:
    from __init__ import plugin
    print('✅ 插件导入成功!')
    print(f'插件名称: {plugin.name}')
    print(f'模块名称: {plugin.module_name}')
    print(f'版本: {plugin.version}')
    print(f'作者: {plugin.author}')
except Exception as e:
    print(f'❌ 插件导入失败: {e}')
    import traceback
    traceback.print_exc()
