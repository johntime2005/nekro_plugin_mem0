"""
独立测试脚本 - 测试预搜索工具函数
"""

import re
from typing import Any


def clean_message_content(content: str) -> str:
    """清洗消息内容"""
    if not content:
        return ""

    # 去除代码块
    content = re.sub(r"```[\s\S]*?```", "", content)
    content = re.sub(r"`[^`]+`", "", content)
    content = re.sub(r"<[^>]+>", "", content)
    content = re.sub(r"\s+", " ", content)
    content = re.sub(r"<!--.*?-->", "", content)

    return content.strip()


def build_pre_search_query(
    messages: list[dict[str, Any]], query_message_count: int, max_length: int
) -> str | None:
    """从历史消息生成查询"""
    if not messages:
        return None

    user_messages = [
        msg for msg in messages if isinstance(msg, dict) and msg.get("role") == "user"
    ]

    if not user_messages:
        return None

    recent_user_messages = user_messages[-query_message_count:]
    last_message = recent_user_messages[-1].get("content", "")
    cleaned = clean_message_content(last_message)

    if cleaned:
        return cleaned[:max_length]

    all_content = " ".join(
        clean_message_content(msg.get("content", "")) for msg in recent_user_messages
    )

    return all_content[:max_length] if all_content else None


# 测试
if __name__ == "__main__":
    print("=" * 60)
    print("预搜索工具函数测试")
    print("=" * 60)

    # 测试1: 消息清洗
    print("\n[测试1] 消息清洗")
    test_content = """这是一段测试文本
```python
print('code block')
```
还有一些`inline code`内容
<html>标签</html>"""

    cleaned = clean_message_content(test_content)
    print(f"  原始长度: {len(test_content)} 字符")
    print(f"  清洗后: {len(cleaned)} 字符")
    print(f"  内容: '{cleaned}'")
    assert "code block" not in cleaned, "代码块应被移除"
    assert "inline code" not in cleaned, "行内代码应被移除"
    assert "<html>" not in cleaned, "HTML标签应被移除"
    print("  ✓ 通过")

    # 测试2: 查询生成 - 单条消息
    print("\n[测试2] 查询生成 - 单条消息")
    messages = [{"role": "user", "content": "我喜欢猫"}]
    query = build_pre_search_query(messages, 10, 500)
    print(f"  生成的查询: '{query}'")
    assert query == "我喜欢猫", "应返回清洗后的消息"
    print("  ✓ 通过")

    # 测试3: 查询生成 - 多条消息
    print("\n[测试3] 查询生成 - 多条消息")
    messages = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！"},
        {"role": "user", "content": "我喜欢猫"},
        {"role": "assistant", "content": "好的"},
        {"role": "user", "content": "特别是橘猫"},
    ]
    query = build_pre_search_query(messages, 10, 500)
    print(f"  生成的查询: '{query}'")
    assert query == "特别是橘猫", "应返回最后一条用户消息"
    print("  ✓ 通过")

    # 测试4: 查询生成 - 长度截断
    print("\n[测试4] 查询生成 - 长度截断")
    messages = [{"role": "user", "content": "A" * 1000}]
    query = build_pre_search_query(messages, 10, 100)
    assert query is not None, "查询不应为 None"
    print(f"  生成的查询长度: {len(query)} 字符")
    assert len(query) == 100, "应截断到最大长度"
    print("  ✓ 通过")

    # 测试5: 空消息处理
    print("\n[测试5] 空消息处理")
    query = build_pre_search_query([], 10, 500)
    assert query is None, "空消息列表应返回 None"
    print("  ✓ 通过")

    # 测试6: 只有 assistant 消息
    print("\n[测试6] 只有 assistant 消息")
    messages = [{"role": "assistant", "content": "你好！"}]
    query = build_pre_search_query(messages, 10, 500)
    assert query is None, "没有用户消息应返回 None"
    print("  ✓ 通过")

    print("\n" + "=" * 60)
    print("✅ 所有测试通过！")
    print("=" * 60)
