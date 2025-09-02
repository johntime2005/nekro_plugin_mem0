"""
辅助函数
"""

import base64
from typing import Optional


def get_preset_id(chat_key: Optional[str]) -> str:
    if not chat_key:
        return "default"
    return base64.urlsafe_b64encode(chat_key.encode()).decode()


def decode_id(encoded: str) -> str:
    return base64.urlsafe_b64decode(encoded.encode()).decode()
