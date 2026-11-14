"""螃蟹上号后台任务：账号密码登录，不阻塞界面。"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtCore import QThread, pyqtSignal

from .services.accounts import Account
from .services.phone_parser import mask_phone
from .services.pxb7_client import Pxb7Client, Pxb7Error, Pxb7LoginError
from .services.pxb7_yd_token import Pxb7BrowserYdTokenProvider
from .settings import AppSettings


class LoginRunner(QThread):
    """使用浏览器完成账号密码登录，结果通过信号回传主线程。"""

    log_message = pyqtSignal(str, str)
    step_progress = pyqtSignal(int, float, str)  # index, percent, detail
    step_done = pyqtSignal(int, bool, str)  # index, success, detail
    summary = pyqtSignal(int, int, bool)  # success, total, cancelled

    def __init__(
        self,
        accounts: list[Account],
        threads: int,
        settings: AppSettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._accounts = list(accounts)
        self._threads = max(1, min(int(threads), max(1, len(self._accounts))))
        self._settings = settings
        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._token_provider = Pxb7BrowserYdTokenProvider(
            settings.pxb7, settings.login, self._log
        )

    # ------------------------------------------------------------------
    # 控制
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        self._cancel.set()
        self._pause.clear()

    def pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    def run(self) -> None:
        total = len(self._accounts)
        if total == 0:
            self.summary.emit(0, 0, False)
            return

        default_count = sum(
            account.password_is_default for account in self._accounts
        )
        self._log(
            f"开始螃蟹上号：共 {total} 个账号 · {self._threads} 线程 · "
            f"账号密码登录（{default_count} 个使用默认密码）",
            "accent",
        )
        if self._settings.login.browser_headless:
            self._log(
                "将通过无头 Playwright 获取易盾 token，登录请求由协议发送。",
                "warn",
            )
        else:
            self._log(
                "将通过 Playwright 获取易盾 token，登录请求由协议发送；"
                "如出现滑块，请在浏览器窗口中手动完成。",
                "warn",
            )
        if self._threads > 1:
            self._log(
                "浏览器登录需要人工滑块，多线程时将串行执行登录步骤。",
                "warn",
            )

        success = 0
        done = 0
        try:
            with ThreadPoolExecutor(max_workers=self._threads) as pool:
                futures = {
                    pool.submit(self._login_one, account): account
                    for account in self._accounts
                }
                for future in as_completed(futures):
                    account = futures[future]
                    try:
                        ok = bool(future.result())
                    except Exception as exc:  # 防御性兜底
                        ok = False
                        masked = mask_phone(account.phone)
                        self._log(f"{masked} 未处理异常：{exc}", "error")

                    done += 1
                    if ok:
                        success += 1
                    self.step_progress.emit(
                        0,
                        done / total * 100,
                        f"已完成 {done}/{total} · 成功 {success}",
                    )
        finally:
            cancelled = self._cancel.is_set()
            if not cancelled:
                self.step_done.emit(0, success > 0, f"成功 {success}/{total}")
                if success:
                    self._log(
                        f"螃蟹上号完成：成功 {success}/{total} 个账号", "success"
                    )
                else:
                    self._log(
                        f"螃蟹上号结束：{total} 个账号均未登录成功", "warn"
                    )
                self._log(
                    "表格写入 / 对话聊天 / 完成询价 / 填入表格待后续接入。",
                    "muted",
                )
            else:
                self._log(
                    f"已停止螃蟹上号：完成 {done}/{total}，成功 {success}", "warn"
                )
            self.summary.emit(success, total, cancelled)

    # ------------------------------------------------------------------
    # 单账号登录
    # ------------------------------------------------------------------

    def _login_one(self, account: Account) -> bool:
        masked = mask_phone(account.phone)
        if self._cancel.is_set():
            return False

        while self._pause.is_set():
            if self._cancel.is_set():
                return False
            time.sleep(0.2)

        password_type = "默认密码" if account.password_is_default else "自定义密码"
        self._log(f"{masked} 开始登录（{password_type}）", "info")

        try:
            token, cookies = self._token_provider.capture(
                account.phone, account.password, self._cancel
            )
            self._log(
                f"{masked} 易盾 token 已获取，开始协议密码登录…", "info"
            )
            client = Pxb7Client(self._settings.pxb7, account.phone)
            client.load_cookies(cookies)
            result = client.login_with_password(
                account.phone, account.password, token
            )
        except Pxb7LoginError as exc:
            self._log(f"{masked} 登录失败：{exc}", "error")
            return False
        except Pxb7Error as exc:
            if self._cancel.is_set():
                self._log(f"{masked} 已取消", "warn")
            else:
                self._log(f"{masked} 登录异常：{exc}", "error")
            return False
        except Exception as exc:  # 防御性兜底，避免整个线程崩溃
            self._log(f"{masked} 未处理异常：{exc}", "error")
            return False

        username = result.username.strip()
        if not username:
            username = f"用户{result.user_id}" if result.user_id else "未知用户"

        detail = f"用户名：{username}"
        if result.user_id:
            detail += f" · 用户ID：{result.user_id}"
        self._log(f"{masked} 登录成功 · {detail}", "success")
        if result.warning:
            self._log(f"{masked} {result.warning}", "warn")
        return True

    def _log(self, message: str, level: str = "info") -> None:
        self.log_message.emit(message, level)
