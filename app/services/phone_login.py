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

_PROXY_ERROR_MARKERS = (
    "err_tunnel_connection_failed",
    "err_proxy_connection_failed",
    "err_proxy_auth_required",
    "err_no_supported_proxies",
    "err_connection_reset",
    "err_connection_closed",
    "err_connection_timed_out",
    "err_timed_out",
    "err_name_not_resolved",
    "timeout",
    "超时",
    "行为验证失败",
    "代理网络下登录页未加载",
    "代理连接失败",
    "代理不可达",
)


def is_proxy_login_error(exc: BaseException) -> bool:
    """判断登录异常是否更像代理线路问题。"""
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in _PROXY_ERROR_MARKERS)


def proxy_error_hint(exc: BaseException) -> str:
    text = str(exc)
    if "ERR_TUNNEL_CONNECTION_FAILED" in text:
        return (
            "代理 HTTPS 隧道建立失败，常见原因是代理已失效、"
            "未加入白名单、鉴权失败或线路不可用"
        )
    if "ERR_PROXY_AUTH_REQUIRED" in text:
        return "代理要求鉴权，请检查代理账号密码或白名单配置"
    if "行为验证失败" in text:
        return "当前代理 IP 被易盾判定为风险，请更换代理线路"
    if (
        "ERR_TIMED_OUT" in text
        or "Timeout" in text
        or "超时" in text
    ):
        return "代理线路超时，请更换更快的代理"
    if "ERR_CONNECTION_RESET" in text or "ERR_CONNECTION_CLOSED" in text:
        return "代理连接被重置，请更换代理线路"
    return "代理线路异常，请检查代理接口、白名单或有效期"


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
