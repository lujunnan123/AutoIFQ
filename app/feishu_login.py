"""飞书二维码登录：打开可见浏览器、等待扫码并保存会话。"""

from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

from PyQt6.QtCore import QThread, pyqtSignal

from .services.feishu_common import feishu_logged_in, resolve_state_path
from .settings import AppSettings, FeishuSettings

try:
    from playwright.sync_api import (
        Error as PlaywrightError,
        TimeoutError as PlaywrightTimeoutError,
        sync_playwright,
    )
except ImportError:  # pragma: no cover
    sync_playwright = None

    class PlaywrightError(Exception):
        pass

    class PlaywrightTimeoutError(PlaywrightError):
        pass


class FeishuLoginError(Exception):
    """飞书扫码登录失败。"""


class FeishuLoginRunner(QThread):
    log_message = pyqtSignal(str, str)
    status_changed = pyqtSignal(str)  # logging / logged_in / error / idle
    completed = pyqtSignal(bool, str)

    def __init__(
        self,
        settings: AppSettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._feishu: FeishuSettings = settings.feishu
        self._state_path = resolve_state_path(self._feishu)
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    # ------------------------------------------------------------------

    def run(self) -> None:
        self.status_changed.emit("logging")
        self._log(
            f"目标：{self._feishu.tenant_name} / "
            f"{self._feishu.base_name} / {self._feishu.table_name}",
            "muted",
        )
        self._log("正在打开飞书登录页…", "info")
        browser = None
        try:
            if sync_playwright is None:
                raise FeishuLoginError(
                    "未安装 Playwright，无法登录飞书。"
                )
            with sync_playwright() as playwright:
                browser = self._launch(playwright)
                context_args = {
                    "locale": "zh-CN",
                    "viewport": {"width": 1440, "height": 1000},
                }
                if feishu_logged_in(self._feishu):
                    context_args["storage_state"] = str(self._state_path)
                context = browser.new_context(**context_args)
                page = context.new_page()

                page.goto(
                    self._feishu.login_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                self._log(
                    "请在打开的浏览器中使用飞书 App 扫描二维码登录…", "warn"
                )

                deadline = time.monotonic() + self._feishu.login_timeout
                logged_in = False
                last_hint = time.monotonic()
                last_tenant_try = 0.0
                while time.monotonic() < deadline:
                    if self._cancel.is_set():
                        raise FeishuLoginError("已取消飞书登录。")

                    # 扫码后飞书可能新开标签页，需要检查所有页面
                    for candidate in context.pages:
                        try:
                            candidate_url = candidate.url
                        except Exception:
                            continue
                        if self._is_base_url(candidate_url):
                            page = candidate
                            logged_in = True
                            break
                    if logged_in:
                        break

                    try:
                        page.wait_for_timeout(500)
                    except PlaywrightError:
                        if context.pages:
                            page = context.pages[-1]
                            continue
                        raise

                    now = time.monotonic()
                    if now - last_tenant_try >= 3.0:
                        self._try_select_tenant(page)
                        last_tenant_try = now
                    if now - last_hint >= 30.0:
                        self._log(
                            "仍在等待飞书扫码登录…", "muted"
                        )
                        last_hint = now

                if not logged_in:
                    raise FeishuLoginError(
                        "等待飞书扫码登录超时，请重试。"
                    )

                self._log("扫码成功，正在进入目标多维表格…", "info")
                page.goto(
                    self._feishu.table_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                page.wait_for_timeout(3000)

                if "accounts.feishu.cn" in page.url:
                    raise FeishuLoginError(
                        "登录后仍被重定向到飞书登录页，请重新登录。"
                    )

                found_table = False
                table_deadline = time.monotonic() + 15
                while time.monotonic() < table_deadline:
                    if self._cancel.is_set():
                        raise FeishuLoginError("已取消飞书登录。")
                    try:
                        body = page.locator("body").inner_text(
                            timeout=3000
                        )
                    except Exception:
                        body = ""
                    if self._feishu.table_name in body:
                        found_table = True
                        break
                    page.wait_for_timeout(1000)

                self._state_path.parent.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(self._state_path))
                if not self._state_path.exists():
                    raise FeishuLoginError(
                        "飞书登录状态保存失败，请检查 data 目录权限。"
                    )

                self._log("飞书登录成功，登录状态已保存。", "success")
                self._log(
                    f"已选择租户：{self._feishu.tenant_name}", "success"
                )
                self._log(
                    f"已进入：{self._feishu.base_name} / "
                    f"{self._feishu.table_name}",
                    "success" if found_table else "warn",
                )
                if found_table:
                    self._log(
                        "飞书登录流程完成：所有步骤执行成功。", "success"
                    )
                else:
                    self._log(
                        "飞书登录完成；目标表已通过链接打开，"
                        "但页面文本中未检测到表名，请在浏览器中确认。",
                        "warn",
                    )
                self.status_changed.emit("logged_in")
                self.completed.emit(
                    True,
                    f"{self._feishu.tenant_name} / "
                    f"{self._feishu.base_name} / "
                    f"{self._feishu.table_name}",
                )
        except PlaywrightTimeoutError as exc:
            self._log(f"飞书登录超时：{exc}", "error")
            self.status_changed.emit("error")
            self.completed.emit(False, str(exc))
        except PlaywrightError as exc:
            self._log(f"飞书浏览器操作失败：{exc}", "error")
            self.status_changed.emit("error")
            self.completed.emit(False, str(exc))
        except Exception as exc:
            self._log(f"飞书登录失败：{exc}", "error")
            self.status_changed.emit("error")
            self.completed.emit(False, str(exc))
        finally:
            if browser is not None:
                try:
                    if browser.is_connected():
                        browser.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------

    def _launch(self, playwright):
        channel = self._feishu.browser_channel or None
        try:
            return playwright.chromium.launch(
                headless=False, channel=channel
            )
        except PlaywrightError:
            if not channel:
                raise
            self._log(
                f"启动浏览器通道 {channel} 失败，尝试 Playwright Chromium…",
                "warn",
            )
            return playwright.chromium.launch(headless=False)

    @staticmethod
    def _is_base_url(url: str) -> bool:
        parsed = urlparse(url)
        return "accounts.feishu.cn" not in parsed.netloc and "/base/" in parsed.path

    def _try_select_tenant(self, page) -> None:
        try:
            page_url = page.url
        except Exception:
            return
        if "accounts.feishu.cn" not in page_url:
            return
        tenant = self._feishu.tenant_name
        aliases = {
            tenant,
            tenant.replace("维因", "维音"),
            "杭州维音信息科技有限公司",
            "杭州维因信息科技有限公司",
        }
        if tenant.endswith("公司") and "有限" not in tenant:
            aliases.add(tenant[:-2] + "有限公司")
        for name in aliases:
            locator = page.get_by_text(name, exact=False)
            try:
                count = locator.count()
            except Exception:
                continue
            for index in range(min(count, 3)):
                element = locator.nth(index)
                try:
                    if not element.is_visible():
                        continue
                except Exception:
                    continue
                try:
                    element.locator(
                        "xpath=ancestor-or-self::*[@role='button'][1]"
                    ).click(timeout=1500)
                except Exception:
                    try:
                        element.click(timeout=1500)
                    except Exception:
                        continue
                self._log(f"已选择租户：{name}", "info")
                return

    def _log(self, message: str, level: str = "info") -> None:
        self.log_message.emit(message, level)
