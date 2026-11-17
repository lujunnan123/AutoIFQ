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

from ..settings import PROJECT_ROOT, LoginSettings, Pxb7Settings
from .phone_parser import mask_phone
from .proxy_provider import ProxyEndpoint
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
        proxy: ProxyEndpoint | None = None,
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
            return self._capture_locked(phone, password, cancel, proxy)
        finally:
            _TOKEN_LOCK.release()

    def _acquire_lock(self, cancel: threading.Event) -> bool:
        while not _TOKEN_LOCK.acquire(timeout=0.5):
            if cancel.is_set():
                return False
        return True

    def _capture_locked(
        self,
        phone: str,
        password: str,
        cancel: threading.Event,
        proxy: ProxyEndpoint | None = None,
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
                browser = self._launch(playwright, proxy)
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
                    self._open_password_login(page, masked)
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

                    browser_timeout = self._login.browser_timeout
                    if proxy is not None:
                        browser_timeout = max(
                            browser_timeout, 300.0
                        )
                        self._log(
                            f"{masked} 使用代理时易盾验证较慢，"
                            f"等待上限延长到 {int(browser_timeout)} 秒。",
                            "muted",
                        )
                    deadline = time.monotonic() + browser_timeout
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

    def _open_password_login(self, page, masked: str) -> None:
        page.wait_for_timeout(1500)
        for attempt in range(2):
            if self._click_password_tab(page):
                return
            if attempt == 0:
                self._log(
                    f"{masked} 登录页暂未加载，刷新页面后重试…",
                    "warn",
                )
                try:
                    page.reload(
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )
                    page.wait_for_timeout(2500)
                except PlaywrightError as exc:
                    self._log(
                        f"{masked} 刷新登录页失败：{exc}", "warn"
                    )

        self._log(
            f"{masked} 未找到「密码登录」入口，"
            f"当前页面：{page.url}",
            "error",
        )
        try:
            body = page.locator("body").inner_text(timeout=3000)
            preview = " ".join(body.split())[:300]
            self._log(f"登录页文本：{preview}", "muted")
        except Exception:
            pass
        self._save_login_failure_screenshot(page, masked)
        raise Pxb7Error(
            "代理网络下登录页未加载出「密码登录」入口，"
            "可能是代理较慢、代理不可达或触发了页面验证。"
            "请更换代理后重试；失败截图已保存到 output 目录。"
        )

    def _click_password_tab(self, page) -> bool:
        try:
            locator = page.get_by_text("密码登录", exact=True)
            locator.first.wait_for(
                state="visible", timeout=30000
            )
        except PlaywrightError:
            locator = page.get_by_text("密码登录", exact=False)
        try:
            count = min(locator.count(), 5)
        except PlaywrightError:
            return False
        for index in range(count):
            element = locator.nth(index)
            try:
                if not element.is_visible():
                    continue
                element.click(timeout=5000)
                return True
            except Exception:
                continue
        return False

    def _save_login_failure_screenshot(self, page, masked: str) -> None:
        try:
            output_dir = PROJECT_ROOT / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            safe_masked = masked.replace("*", "x")
            path = output_dir / f"proxy_login_failure_{safe_masked}.png"
            page.screenshot(path=str(path), full_page=False)
            self._log(f"登录失败截图：{path}", "warn")
        except Exception as exc:
            self._log(f"保存登录失败截图失败：{exc}", "warn")

    def _launch(self, playwright, proxy: ProxyEndpoint | None = None):
        channel = self._login.browser_channel or None
        kwargs = {
            "headless": self._login.browser_headless,
            "channel": channel,
        }
        if proxy is not None:
            kwargs["proxy"] = proxy.as_playwright()
        try:
            return playwright.chromium.launch(**kwargs)
        except PlaywrightError as exc:
            if not channel:
                raise
            self._log(
                f"启动浏览器通道 {channel} 失败（{exc}），尝试 Playwright Chromium…",
                "warn",
            )
            kwargs.pop("channel", None)
            return playwright.chromium.launch(**kwargs)
