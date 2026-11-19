"""手动询价窗口从 TXT 中原子领取手机号，并从清单中删除。"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from .accounts import Account
from .phone_parser import PHONE_PATTERN, decode_text

# 同一进程内的多个手动询价窗口共享该锁，保证领取过程不会拿到同一行。
CLAIM_LOCK = threading.RLock()


class AccountClaimError(Exception):
    """账号清单领取失败。"""


def claim_account(
    path: str | Path,
    default_password: str,
) -> Account | None:
    """领取清单中的第一个手机号并从文件删除；没有可用账号时返回 None。"""
    file_path = Path(path)
    with CLAIM_LOCK:
        try:
            raw = file_path.read_bytes()
        except OSError as exc:
            raise AccountClaimError(
                f"无法读取账号清单：{exc}"
            ) from exc

        lines = decode_text(raw).splitlines(keepends=True)
        accounts: list[Account] = []
        positions: dict[str, int] = {}

        for line in lines:
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
                existing = accounts[index]
                # 同一号码先出现仅手机号、后出现显式密码时，以后者为准。
                if (
                    existing.password_is_default
                    and not account.password_is_default
                ):
                    accounts[index] = account
                continue

            positions[phone] = len(accounts)
            accounts.append(account)

        if not accounts:
            return None

        chosen = accounts[0]
        kept_lines = []
        for line in lines:
            match = PHONE_PATTERN.search(line)
            if match and match.group(1) == chosen.phone:
                continue
            kept_lines.append(line)

        _write_atomic(file_path, "".join(kept_lines))
        return chosen


def release_account(
    path: str | Path,
    account: Account,
) -> bool:
    """把登录前领取但未使用的手机号放回清单；已存在时返回 False。"""
    file_path = Path(path)
    with CLAIM_LOCK:
        try:
            raw = file_path.read_bytes()
        except FileNotFoundError:
            raw = b""
        except OSError as exc:
            raise AccountClaimError(
                f"无法读取账号清单：{exc}"
            ) from exc

        text = decode_text(raw)
        for line in text.splitlines():
            match = PHONE_PATTERN.search(line)
            if match and match.group(1) == account.phone:
                return False

        newline = "\r\n" if "\r\n" in text else "\n"
        if text and not text.endswith(("\n", "\r")):
            text += newline
        if account.password_is_default:
            text += account.phone + newline
        else:
            text += (
                f"{account.phone}----{account.password}{newline}"
            )
        _write_atomic(file_path, text)
        return True


def _write_atomic(path: Path, text: str) -> None:
    temp_path = path.with_name(path.name + ".tmp")
    try:
        # 用二进制写入，避免 Windows 把已有的 \r\n 再次转换成 \r\r\n。
        temp_path.write_bytes(text.encode("utf-8"))
        os.replace(temp_path, path)
    except OSError as exc:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise AccountClaimError(
            f"更新账号清单失败：{exc}"
        ) from exc
