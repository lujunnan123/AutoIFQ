"""从短信内容中提取验证码。"""

from __future__ import annotations

import re

_KEYWORD_PATTERNS = (
    re.compile(
        r"(?:验证码|校验码|动态码|登录码|verification\s*code|code)"
        r"[^\d]{0,16}(\d{4,8})",
        re.IGNORECASE,
    ),
    re.compile(r"(\d{4,8})[^\d]{0,8}(?:为|是)?[^\d]{0,8}(?:验证码|校验码)"),
)

_FALLBACK_PATTERN = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")


def extract_code(content: str) -> str | None:
    """优先匹配「验证码」附近的数字；匹配不到时回退到首个 4-8 位数字。"""
    if not content:
        return None

    text = content.strip()
    for pattern in _KEYWORD_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)

    for match in _FALLBACK_PATTERN.finditer(text):
        code = match.group(1)
        if len(code) in (4, 5, 6):
            return code
    return None
