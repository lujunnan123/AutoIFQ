"""从上传的 TXT 中解析手机号。"""

from __future__ import annotations

import re
from pathlib import Path

PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")

_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030")


class PhoneParseError(Exception):
    """清单中没有可用手机号，或文件无法读取。"""


def decode_text(raw: bytes) -> str:
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_phones(path: str | Path) -> list[str]:
    """读取文件中的手机号，按出现顺序去重。"""
    file_path = Path(path)
    try:
        raw = file_path.read_bytes()
    except OSError as exc:
        raise PhoneParseError(f"无法读取清单文件：{exc}") from exc

    phones: list[str] = []
    seen: set[str] = set()
    for match in PHONE_PATTERN.finditer(decode_text(raw)):
        phone = match.group(1)
        if phone not in seen:
            seen.add(phone)
            phones.append(phone)

    if not phones:
        raise PhoneParseError(
            "未在清单中找到手机号（需要 11 位大陆手机号，例如 13800138000）。"
        )
    return phones


def mask_phone(phone: str) -> str:
    if len(phone) == 11:
        return f"{phone[:3]}****{phone[-4:]}"
    return phone
