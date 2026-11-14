"""通过 Playwright 打开螃蟹登录页，触发登录验证码短信。

说明：
- 工具只负责填写手机号并点击「获取验证码」；
- 如果易盾弹出滑块，需要在可见浏览器窗口中人工完成，工具不会破解验证码；
- 捕获 sendSms 接口成功响应后自动关闭浏览器，随后由协议流程读取短信并登录。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from urllib.parse import quote

from ..settings import LoginSettings, Pxb7Settings
from .phone_parser import mask_phone

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

# 浏览器触发涉及人工滑块，多个线程必须串行。
_TRIGGER_LOCK = threading.Lock()


class Pxb7BrowserSmsTrigger:
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

    def trigger(
        self, phone: str, cancel: threading.Event | None = None
    ) -> bool:
        cancel = cancel or threading.Event()
        if sync_playwright is None:
            self._log(
                "未安装 Playwright，无法自动触发验证码短信。"
                "请执行 pip install playwright 后重试。",
                "error",
            )
            return False
        if not self._acquire_lock(cancel):
            return False
        try:
            return self._trigger_locked(phone, cancel)
        finally:
            _TRIGGER_LOCK.release()

    def _acquire_lock(self, cancel: threading.Event) -> bool:
        while not _TRIGGER_LOCK.acquire(timeout=0.5):
            if cancel.is_set():
                return False
        return True

    def _trigger_locked(self, phone: str, cancel: threading.Event) -> bool:
        masked = mask_phone(phone)
        self._log(
            f"{masked} 正在打开浏览器触发验证码短信…"
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

                    def handle_response(response) -> None:
                        if (
                            "/user/web/login/sms/sendSms" in response.url
                            and response.request.method == "POST"
                        ):
                            state["response"] = response

                    page.on("response", handle_response)
                    page.goto(
                        self._login_url,
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )
                    page.get_by_placeholder("请输入手机号").first.fill(phone)
                    page.wait_for_timeout(500)
                    page.get_by_text("获取验证码", exact=True).first.click()

                    self._log(
                        f"{masked} 已点击「获取验证码」；"
                        "如浏览器弹出滑块，请手动完成验证。",
                        "warn",
                    )

                    deadline = time.monotonic() + self._login.browser_timeout
                    while time.monotonic() < deadline:
                        if cancel.is_set():
                            self._log(f"{masked} 已取消浏览器触发。", "warn")
                            return False
                        page.wait_for_timeout(500)
                        if "response" in state:
                            break

                    response = state.get("response")
                    if response is None:
                        hint = (
                            "若页面出现滑块，请将 config.json 中 "
                            "login.browser_headless 设为 false 后重试。"
                            if self._login.browser_headless
                            else "滑块可能未完成或页面未提交成功。"
                        )
                        self._log(
                            f"{masked} 未检测到短信发送成功。{hint}", "warn"
                        )
                        return False

                    try:
                        body = response.json()
                    except Exception:
                        body = {}

                    if isinstance(body, dict) and body.get("success"):
                        self._log(
                            f"{masked} 验证码短信发送成功，等待短信后台接收…",
                            "success",
                        )
                        return True

                    message = (
                        (body.get("errMessage") if isinstance(body, dict) else "")
                        or (body.get("msg") if isinstance(body, dict) else "")
                        or f"HTTP {response.status}"
                    )
                    self._log(f"{masked} 短信发送失败：{message}", "error")
                    return False
                finally:
                    try:
                        if browser.is_connected():
                            browser.close()
                    except Exception:
                        pass
        except PlaywrightTimeoutError as exc:
            self._log(f"{masked} 浏览器操作超时：{exc}", "warn")
        except PlaywrightError as exc:
            self._log(f"{masked} 浏览器操作失败：{exc}", "error")
        except Exception as exc:
            self._log(f"{masked} 浏览器触发异常：{exc}", "error")
        return False

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
