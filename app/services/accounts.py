"""从 TXT 清单解析「手机号----密码」账号。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .phone_parser import PHONE_PATTERN, decode_text

DEFAULT_PASSWORD = "Aa123456"


class AccountParseError(Exception):
    """清单中没有可用账号，或文件无法读取。"""


@dataclass(frozen=True)
class Account:
    phone: str
    password: str
    password_is_default: bool = False


def read_accounts(
    path: str | Path, default_password: str = DEFAULT_PASSWORD
) -> list[Account]:
    """解析格式：手机号----密码；只有手机号时使用默认密码。"""
    file_path = Path(path)
    try:
        raw = file_path.read_bytes()
    except OSError as exc:
        raise AccountParseError(f"无法读取清单文件：{exc}") from exc

    accounts: list[Account] = []
    positions: dict[str, int] = {}

    for line in decode_text(raw).splitlines():
        match = PHONE_PATTERN.search(line)
        if not match:
            continue

        phone = match.group(1)
        rest = line[match.end():]
        password = ""
        if "----" in rest:
            password = rest.split("----", 1)[1].strip()

        if password:
            account = Account(phone=phone, password=password)
        else:
            account = Account(
                phone=phone,
                password=default_password,
                password_is_default=True,
            )

        if phone in positions:
            index = positions[phone]
            # 同一号码先出现“仅手机号”，后出现显式密码时，以后者为准。
            if accounts[index].password_is_default and not account.password_is_default:
                accounts[index] = account
            continue

        positions[phone] = len(accounts)
        accounts.append(account)

    if not accounts:
        raise AccountParseError(
            "未找到可用账号。请使用格式：手机号----密码（仅手机号时使用默认密码 "
            f"{default_password}）。"
        )
    return accounts
