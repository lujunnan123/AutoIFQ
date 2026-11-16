"""飞书配置路径等公共工具。"""

from __future__ import annotations

import json
from pathlib import Path

from ..settings import PROJECT_ROOT, FeishuSettings


def resolve_state_path(config: FeishuSettings) -> Path:
    state_path = Path(config.state_path)
    if not state_path.is_absolute():
        state_path = PROJECT_ROOT / state_path
    return state_path


def feishu_logged_in(config: FeishuSettings) -> bool:
    """检查是否保存过可用的登录状态；会话是否过期需在实际访问时验证。"""
    state_path = resolve_state_path(config)
    if not state_path.exists():
        return False
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    return bool(data.get("cookies") or data.get("origins"))
