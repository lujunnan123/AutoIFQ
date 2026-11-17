"""TXT 手机号登录：易盾 token + 协议登录 + 代理聊天会话。"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..settings import AppSettings
from .accounts import Account
from .proxy_provider import ProxyEndpoint
from .pxb7_chat import PhoneSession
from .pxb7_client import Pxb7Client
from .pxb7_yd_token import Pxb7BrowserYdTokenProvider

StepCallback = Callable[[float, str], None]


@dataclass(frozen=True)
class PhoneLoginResult:
    session: PhoneSession | None
    username: str
    user_id: str
    warning: str | None = None


def login_phone(
    settings: AppSettings,
    account: Account,
    proxy: ProxyEndpoint | None,
    cancel: threading.Event,
    provider: Pxb7BrowserYdTokenProvider,
    on_step: StepCallback | None = None,
) -> PhoneLoginResult:
    """执行与主流程相同的手机号协议登录，并生成聊天会话。"""
    step = on_step or (lambda progress, detail: None)
    step(5.0, "正在获取易盾 token…")
    token, browser_cookies = provider.capture(
        account.phone,
        account.password,
        cancel,
        proxy=proxy,
    )
    step(55.0, "正在协议密码登录…")
    client = Pxb7Client(
        settings.pxb7,
        account.phone,
        proxy=proxy,
    )
    client.load_cookies(browser_cookies)
    result = client.login_with_password(
        account.phone, account.password, token
    )

    username = result.username.strip()
    if not username:
        username = (
            f"用户{result.user_id}" if result.user_id else "未知用户"
        )

    session = _build_phone_session(
        account.phone,
        result.token,
        result.user_id,
        browser_cookies,
        client,
        proxy,
    )
    step(100.0, f"用户名：{username}")
    return PhoneLoginResult(
        session=session,
        username=username,
        user_id=result.user_id,
        warning=result.warning,
    )


def _build_phone_session(
    phone: str,
    token: str,
    user_id: str,
    browser_cookies: list[dict[str, Any]],
    client: Pxb7Client,
    proxy: ProxyEndpoint | None,
) -> PhoneSession | None:
    if not token:
        return None
    cookies: list[dict[str, str]] = []
    for cookie in browser_cookies:
        domain = str(cookie.get("domain") or "")
        name = str(cookie.get("name") or "")
        if "pxb7.com" not in domain or not name:
            continue
        cookies.append(
            {
                "name": name,
                "value": str(cookie.get("value") or ""),
                "domain": domain,
                "path": str(cookie.get("path") or "/"),
            }
        )
    cookies.extend(client.session_cookies())
    return PhoneSession(
        phone=phone,
        token=token,
        user_id=user_id,
        cookies=tuple(cookies),
        proxy=proxy,
    )
