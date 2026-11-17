"""通过螃蟹官网获取三角洲行动回收坑位的咨询商家。"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from ..settings import AppSettings, PROJECT_ROOT, Pxb7AccountSettings

LogFn = Callable[[str, str], None]

_MERCHANT_API_KEYWORD = "queryRecycleMerchant"
_MERCHANT_WAIT_SECONDS = 25.0
_STATE_WAIT_SECONDS = 15.0


class Pxb7MerchantError(Exception):
    """获取螃蟹咨询商家失败。"""


class Pxb7MerchantCancelled(Pxb7MerchantError):
    """用户取消了螃蟹登录 / 商家获取。"""


@dataclass(frozen=True)
class MerchantFetchResult:
    merchants: tuple[str, ...]
    used_saved_state: bool


def resolve_state_path(config: Pxb7AccountSettings) -> Path:
    state_path = Path(config.state_path)
    if not state_path.is_absolute():
        state_path = PROJECT_ROOT / state_path
    return state_path


def state_available(config: Pxb7AccountSettings) -> bool:
    """检查保存的 Playwright 登录状态是否至少包含会话数据。"""
    path = resolve_state_path(config)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and bool(
        data.get("cookies") or data.get("origins")
    )


class Pxb7MerchantService:
    """登录螃蟹账号并读取指定游戏的回收坑位商家。"""

    def __init__(
        self,
        settings: AppSettings,
        log: LogFn | None = None,
    ) -> None:
        self._settings = settings
        self._account = settings.pxb7_account
        self._log = log or (lambda message, level: None)
        self._state_path = resolve_state_path(self._account)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def fetch(
        self, cancel: threading.Event | None = None
    ) -> MerchantFetchResult:
        cancel = cancel or threading.Event()
        if sync_playwright is None:
            raise Pxb7MerchantError(
                "未安装 Playwright，无法登录螃蟹账号。"
                "请执行 pip install -r requirements.txt。"
            )

        if not state_available(self._account) and not (
            self._account.phone and self._account.password
        ):
            raise Pxb7MerchantError(
                "未配置螃蟹登录账号。请在 config.json 的 "
                "pxb7_account 中填写 phone 和 password。"
            )

        attempts = [self._account.headless]
        if self._account.headless:
            attempts.append(False)

        last_error: Exception | None = None
        for index, headless in enumerate(attempts):
            self._check_cancel(cancel)
            try:
                return self._fetch_once(headless, cancel)
            except Pxb7MerchantCancelled:
                raise
            except Pxb7MerchantError as exc:
                last_error = exc
                self._log(f"获取咨询商家失败：{exc}", "warn")
            except PlaywrightTimeoutError as exc:
                last_error = exc
                self._log(f"螃蟹页面操作超时：{exc}", "warn")
            except PlaywrightError as exc:
                last_error = exc
                self._log(f"螃蟹浏览器操作失败：{exc}", "warn")
            except Exception as exc:  # 防御性兜底
                last_error = exc
                self._log(f"获取咨询商家异常：{exc}", "error")

            if index + 1 < len(attempts):
                self._log(
                    "改用可见浏览器重试；如出现滑块或验证，"
                    "请在浏览器中手动完成。",
                    "warn",
                )

        raise Pxb7MerchantError(
            f"未能获取三角洲行动咨询商家：{last_error}"
        )

    # ------------------------------------------------------------------
    # 单次尝试
    # ------------------------------------------------------------------

    def _fetch_once(
        self, headless: bool, cancel: threading.Event
    ) -> MerchantFetchResult:
        with sync_playwright() as playwright:
            browser = self._launch(playwright, headless=headless)
            try:
                if state_available(self._account):
                    self._log(
                        "正在使用已保存的螃蟹登录状态刷新咨询商家…",
                        "info",
                    )
                    try:
                        merchants = self._load_with_saved_state(
                            browser, cancel
                        )
                        if merchants:
                            self._log(
                                f"使用已保存状态获取到 "
                                f"{len(merchants)} 个咨询商家。",
                                "success",
                            )
                            return MerchantFetchResult(
                                tuple(merchants), True
                            )
                    except Pxb7MerchantCancelled:
                        raise
                    except Exception as exc:
                        self._log(
                            f"已保存的螃蟹登录状态不可用：{exc}；"
                            "开始重新登录…",
                            "warn",
                        )

                merchants = self._login_and_fetch(
                    browser, headless=headless, cancel=cancel
                )
                return MerchantFetchResult(tuple(merchants), False)
            finally:
                try:
                    if browser.is_connected():
                        browser.close()
                except Exception:
                    pass

    def _load_with_saved_state(
        self, browser, cancel: threading.Event
    ) -> list[str]:
        context = browser.new_context(
            storage_state=str(self._state_path),
            locale="zh-CN",
            viewport={"width": 1600, "height": 1000},
        )
        try:
            page = context.new_page()
            page.set_default_timeout(15000)
            captured = self._attach_merchant_capture(page)
            page.goto(
                self._account.recovery_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            if "/login" in page.url:
                return []
            merchants = self._wait_for_merchants(
                page, captured, cancel, _STATE_WAIT_SECONDS
            )
            if merchants:
                self._save_state(context)
            return merchants
        finally:
            try:
                context.close()
            except Exception:
                pass

    def _login_and_fetch(
        self, browser, *, headless: bool, cancel: threading.Event
    ) -> list[str]:
        if not (self._account.phone and self._account.password):
            raise Pxb7MerchantError(
                "螃蟹登录状态已失效，且未配置 pxb7_account 账号密码。"
            )

        website = self._settings.pxb7.website
        login_url = (
            f"{website}/login?redirect="
            + quote(self._account.recovery_url, safe="")
        )

        context = browser.new_context(
            locale="zh-CN",
            viewport={"width": 1600, "height": 1000},
        )
        try:
            page = context.new_page()
            page.set_default_timeout(15000)
            captured = self._attach_merchant_capture(page)

            if not headless:
                self._log(
                    "正在打开螃蟹登录页；如出现滑块或验证，"
                    "请在浏览器中手动完成。",
                    "warn",
                )
            else:
                self._log("正在通过无头浏览器登录螃蟹账号…", "info")

            page.goto(
                login_url, wait_until="domcontentloaded", timeout=60000
            )
            self._submit_password_login(page, cancel)
            self._wait_for_login(page, cancel)

            if "/sell/recovery" not in page.url:
                page.goto(
                    self._account.recovery_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

            self._log(
                "螃蟹登录成功，正在读取三角洲行动回收坑位商家…",
                "info",
            )
            merchants = self._wait_for_merchants(
                page, captured, cancel, _MERCHANT_WAIT_SECONDS
            )
            if not merchants:
                raise Pxb7MerchantError(
                    "登录成功，但未获取到三角洲行动的回收坑位商家。"
                )

            self._save_state(context)
            return merchants
        finally:
            try:
                context.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 登录流程
    # ------------------------------------------------------------------

    def _submit_password_login(self, page, cancel: threading.Event) -> None:
        self._check_cancel(cancel)
        page.get_by_text("密码登录", exact=True).first.click()
        page.wait_for_timeout(500)
        page.get_by_placeholder("请输入账号").first.fill(
            self._account.phone
        )
        page.get_by_placeholder("请输入密码").first.fill(
            self._account.password
        )

        try:
            agreement = page.get_by_text(
                "阅读并同意", exact=False
            ).first
            agreement.locator("xpath=..").click()
        except Exception:
            pass

        page.wait_for_timeout(300)
        page.get_by_text("登录", exact=True).first.click()

    def _wait_for_login(self, page, cancel: threading.Event) -> None:
        deadline = time.monotonic() + self._account.login_timeout
        identity_clicked = False
        last_hint = time.monotonic()

        while time.monotonic() < deadline:
            self._check_cancel(cancel)

            if not identity_clicked:
                try:
                    identity = page.get_by_text(
                        "以普通用户身份登录", exact=True
                    )
                    if identity.count() and identity.first.is_visible():
                        identity.first.click(timeout=3000)
                        identity_clicked = True
                        self._log(
                            "已选择以普通用户身份登录螃蟹账号。",
                            "info",
                        )
                        page.wait_for_timeout(1000)
                        continue
                except Exception:
                    pass

            if "/login" not in page.url:
                self._log("螃蟹账号登录成功。", "success")
                return

            try:
                body = page.locator("body").inner_text(timeout=2000)
            except Exception:
                body = ""
            for cue in (
                "账号或密码错误",
                "密码错误",
                "账号不存在",
                "验证码错误",
                "操作过于频繁",
            ):
                if cue in body:
                    raise Pxb7MerchantError(f"螃蟹登录失败：{cue}")

            now = time.monotonic()
            if now - last_hint >= 20.0:
                self._log("仍在等待螃蟹账号登录…", "muted")
                last_hint = now
            page.wait_for_timeout(500)

        raise Pxb7MerchantError(
            "等待螃蟹账号登录超时；如出现滑块，请将 "
            "pxb7_account.headless 设为 false 后重试。"
        )

    # ------------------------------------------------------------------
    # 商家接口
    # ------------------------------------------------------------------

    def _attach_merchant_capture(self, page) -> dict:
        captured: dict[str, object] = {}

        def on_response(response) -> None:
            if captured.get("merchants"):
                return
            if _MERCHANT_API_KEYWORD not in response.url:
                return
            try:
                data = response.json()
            except Exception:
                return
            names = self._extract_merchant_names(data)
            if names:
                captured["merchants"] = names

        page.on("response", on_response)
        return captured

    def _wait_for_merchants(
        self,
        page,
        captured: dict,
        cancel: threading.Event,
        timeout: float,
    ) -> list[str]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._check_cancel(cancel)
            names = captured.get("merchants")
            if names:
                return list(names)
            try:
                if "/login" in page.url:
                    page.wait_for_timeout(500)
                else:
                    page.wait_for_timeout(300)
            except PlaywrightError:
                break
        names = captured.get("merchants")
        return list(names) if names else []

    @staticmethod
    def _extract_merchant_names(data: object) -> list[str]:
        payload = data.get("data") if isinstance(data, dict) else data
        if isinstance(payload, dict):
            for key in (
                "list",
                "records",
                "items",
                "merchantList",
                "recycleMerchantList",
            ):
                value = payload.get(key)
                if isinstance(value, list):
                    payload = value
                    break

        if not isinstance(payload, list):
            return []

        names: list[str] = []
        seen: set[str] = set()
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = (
                item.get("recycleName")
                or item.get("merchantName")
                or item.get("name")
            )
            if not isinstance(name, str):
                continue
            value = name.strip()
            if not value or value in seen:
                continue
            seen.add(value)
            names.append(value)
        return names

    # ------------------------------------------------------------------
    # 浏览器 / 状态
    # ------------------------------------------------------------------

    def _launch(self, playwright, *, headless: bool):
        channel = self._account.browser_channel or None
        try:
            return playwright.chromium.launch(
                headless=headless, channel=channel
            )
        except PlaywrightError:
            if not channel:
                raise
            self._log(
                f"启动浏览器通道 {channel} 失败，"
                "尝试 Playwright Chromium…",
                "warn",
            )
            return playwright.chromium.launch(headless=headless)

    def _save_state(self, context) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(self._state_path))
        except Exception as exc:
            self._log(f"保存螃蟹登录状态失败：{exc}", "warn")

    @staticmethod
    def _check_cancel(cancel: threading.Event) -> None:
        if cancel.is_set():
            raise Pxb7MerchantCancelled("已取消螃蟹登录 / 商家获取。")
