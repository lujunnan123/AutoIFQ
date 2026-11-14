"""Playwright 只负责获取易盾 ydToken，登录请求由协议客户端发起。

纯协议请求登录接口会返回「易盾token为空」，因此浏览器只用于通过验证码并
截取页面即将提交的请求参数中的 ydToken；该请求会被中止，真正的登录由
Pxb7Client.login_with_password 发送。
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from urllib.parse import quote

from ..settings import LoginSettings, Pxb7Settings
from .phone_parser import mask_phone
from .pxb7_client import Pxb7Error

try:
    from playwright.sync_api import (
        Error as PlaywrightError,
        TimeoutError as PlaywrightTimeoutError,
        sync_playwright,
    )
except ImportError:  # Playwright 未安装时优雅降级
    sync_playwright = None
    PlaywrightError = Exception  # type: ignore[assignment,misc]
    PlaywrightTimeoutError = Exception  # type: ignore[assignment,misc]

LogCallback = Callable[[str, str], None]

_TOKEN_LOCK = threading.Lock()


class Pxb7BrowserYdTokenProvider:
    def __init__(
        self,
        pxb7: Pxb7Settings,
        login: LoginSettings,
        log: LogCallback | None = None,
    ) -> None:
        self._pxb7 = pxb7
        self._login = login
        self._log = log or (lambda _message, _level: None)
        redirect = quote(f"{pxb7.website}/", safe="")
        self._login_url = f"{pxb7.website}/login?redirect={redirect}"

    def capture(
        self,
        phone: str,
        password: str,
        cancel: threading.Event | None = None,
    ) -> tuple[str, list[dict]]:
        """返回 (ydToken, browser_cookies)。"""
        cancel = cancel or threading.Event()
        if sync_playwright is None:
            raise Pxb7Error(
                "未安装 Playwright，无法获取易盾 token。"
                "请执行 pip install playwright 后重试。"
            )
        if not self._acquire_lock(cancel):
            raise Pxb7Error("已取消")
        try:
            return self._capture_locked(phone, password, cancel)
        finally:
            _TOKEN_LOCK.release()

    def _acquire_lock(self, cancel: threading.Event) -> bool:
        while not _TOKEN_LOCK.acquire(timeout=0.5):
            if cancel.is_set():
                return False
        return True

    def _capture_locked(
        self, phone: str, password: str, cancel: threading.Event
    ) -> tuple[str, list[dict]]:
        masked = mask_phone(phone)
        if self._login.browser_headless:
            self._log(
                f"{masked} 正在通过无头浏览器获取易盾 token…", "info"
            )
        else:
            self._log(
                f"{masked} 正在通过浏览器获取易盾 token…"
                "（如出现滑块，请在浏览器中手动完成）",
                "info",
            )

        try:
            with sync_playwright() as playwright:
                browser = self._launch(playwright)
                try:
                    context = browser.new_context(
                        locale="zh-CN",
                        viewport={"width": 1360, "height": 900},
                    )
                    page = context.new_page()
                    page.set_default_timeout(15000)
                    state: dict = {}

                    def handle_route(route) -> None:
                        try:
                            try:
                                payload = route.request.post_data_json
                            except Exception:
                                raw = route.request.post_data or "{}"
                                payload = json.loads(raw)
                            if isinstance(payload, dict):
                                state["payload"] = payload
                        finally:
                            route.abort()

                    page.route(
                        re.compile(r".*user/web/login/twiceLogin.*"),
                        handle_route,
                    )
                    page.goto(
                        self._login_url,
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )
                    page.wait_for_timeout(1500)
                    page.get_by_text("密码登录", exact=True).first.click()
                    page.wait_for_timeout(500)
                    page.get_by_placeholder("请输入账号").first.fill(phone)
                    page.get_by_placeholder("请输入密码").first.fill(password)
                    agree = page.get_by_text("阅读并同意", exact=False).first
                    agree.locator("xpath=..").click()
                    page.wait_for_timeout(300)
                    page.get_by_text("登录", exact=True).first.click()

                    if self._login.browser_headless:
                        self._log(
                            f"{masked} 已触发登录请求，等待易盾无感知验证…",
                            "warn",
                        )
                    else:
                        self._log(
                            f"{masked} 已触发登录请求；"
                            "如出现滑块，请手动完成，工具只截取易盾 token。",
                            "warn",
                        )

                    deadline = time.monotonic() + self._login.browser_timeout
                    while time.monotonic() < deadline:
                        if cancel.is_set():
                            raise Pxb7Error("已取消")
                        page.wait_for_timeout(500)
                        if "payload" in state:
                            break

                    payload = state.get("payload")
                    if not payload:
                        hint = (
                            "若页面出现滑块，请将 config.json 中 "
                            "login.browser_headless 设为 false 后重试。"
                            if self._login.browser_headless
                            else "滑块可能未完成或登录请求未提交。"
                        )
                        raise Pxb7Error(f"{masked} 未获取到易盾 token。{hint}")

                    token = str(payload.get("ydToken") or "").strip()
                    if not token:
                        raise Pxb7Error(f"{masked} 登录请求中没有易盾 token。")

                    self._log(
                        f"{masked} 已获取易盾 token，准备协议登录。", "success"
                    )
                    return token, context.cookies()
                finally:
                    try:
                        if browser.is_connected():
                            browser.close()
                    except Exception:
                        pass
        except PlaywrightTimeoutError as exc:
            raise Pxb7Error(f"浏览器操作超时：{exc}") from exc
        except PlaywrightError as exc:
            raise Pxb7Error(f"浏览器操作失败：{exc}") from exc

    def _launch(self, playwright):
        channel = self._login.browser_channel or None
        try:
            return playwright.chromium.launch(
                headless=self._login.browser_headless,
                channel=channel,
            )
        except PlaywrightError as exc:
            if not channel:
                raise
            self._log(
                f"启动浏览器通道 {channel} 失败（{exc}），尝试 Playwright Chromium…",
                "warn",
            )
            return playwright.chromium.launch(
                headless=self._login.browser_headless
            )
