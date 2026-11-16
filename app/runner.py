"""螃蟹询价后台任务：先构建表格，再按线程数展开工作线程。"""

from __future__ import annotations

import queue
import threading
import time

from PyQt6.QtCore import QThread, pyqtSignal

from .constants import StepStatus
from .services.accounts import Account
from .services.excel_table import ExcelTableError, build_result_table
from .services.feishu_table import (
    FeishuLoginRequired,
    FeishuTableClient,
    FeishuTableError,
)
from .services.phone_parser import mask_phone
from .services.pxb7_client import Pxb7Client, Pxb7Error, Pxb7LoginError
from .services.pxb7_yd_token import Pxb7BrowserYdTokenProvider
from .settings import AppSettings


class LoginRunner(QThread):
    """先构建表格，再启动固定数量的工作线程处理账号队列。"""

    log_message = pyqtSignal(str, str)
    build_status = pyqtSignal(str, str)  # running/done/error, detail
    build_result = pyqtSignal(bool, str)  # success, output path or error
    thread_added = pyqtSignal(int, str)  # slot id, masked phone label
    thread_step = pyqtSignal(int, int, float, str, str)  # slot, step, progress, status, detail
    thread_finished = pyqtSignal(int, bool, str)  # slot, success, detail
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
            f"开始任务：{total} 个账号 · 线程数 {self._threads} · "
            f"账号密码登录（{default_count} 个使用默认密码）",
            "accent",
        )
        self._log(
            "流程：先构建表格，构建成功后按线程数展开工作线程。", "info"
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

        if self._cancel.is_set():
            self.summary.emit(0, total, True)
            return

        # 第一步：构建表格（全局，先于线程执行）
        if not self._build_table():
            self.summary.emit(0, total, self._cancel.is_set())
            return

        if self._cancel.is_set():
            self._log("已停止：构建表格完成后未展开线程。", "warn")
            self.summary.emit(0, total, True)
            return

        # 第二步：按线程数启动固定工作线程，从账号队列取数据
        worker_count = min(self._threads, total)
        work_queue: queue.Queue = queue.Queue()
        for account in self._accounts:
            work_queue.put(account)

        results: list[bool] = []
        results_lock = threading.Lock()
        self._log(
            f"构建表格完成，展开 {worker_count} 个线程 "
            f"（并发 {worker_count}）处理 {total} 个账号…",
            "accent",
        )

        workers = [
            threading.Thread(
                target=self._worker,
                args=(slot, work_queue, results, results_lock),
                name=f"autoifq-worker-{slot}",
                daemon=True,
            )
            for slot in range(1, worker_count + 1)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        cancelled = self._cancel.is_set()
        success = sum(1 for ok in results if ok)
        done = len(results)
        if cancelled:
            self._log(
                f"已停止：完成 {done}/{total}，成功 {success}", "warn"
            )
        else:
            if success:
                self._log(
                    f"螃蟹上号完成：成功 {success}/{total} 个账号",
                    "success",
                )
            else:
                self._log(
                    f"螃蟹上号结束：{total} 个账号均未登录成功", "warn"
                )
            self._log(
                "对话聊天 / 完成询价 / 填入表格待后续接入。", "muted"
            )
        self.summary.emit(success, total, cancelled)

    # ------------------------------------------------------------------
    # 构建表格
    # ------------------------------------------------------------------

    def _build_table(self) -> bool:
        self.build_status.emit("running", "正在读取飞书多维表格…")
        self._log(
            "开始构建表格：从飞书多维表格读取数据…", "info"
        )
        limit = self._settings.excel.copy_limit
        if limit > 0:
            self._log(
                f"测试阶段：只摘录前 {limit} 条记录。", "warn"
            )
        try:
            source = FeishuTableClient(
                self._settings.feishu, self._log
            ).fetch_records(limit=limit)
            self._log(
                f"数据源读取完成：{source.source_name}，"
                f"源表 {source.total_records} 条，"
                f"摘录 {len(source.rows)} 条。",
                "success",
            )
            result = build_result_table(
                source.rows,
                source.source_name,
                limit=limit,
                output_dir=self._settings.excel.output_dir or None,
            )
        except FeishuLoginRequired as exc:
            message = str(exc)
            self.build_status.emit("error", message)
            self.build_result.emit(False, message)
            self._log(f"构建表格失败：{message}", "error")
            return False
        except (FeishuTableError, ExcelTableError) as exc:
            message = str(exc)
            self.build_status.emit("error", message)
            self.build_result.emit(False, message)
            self._log(f"构建表格失败：{message}", "error")
            return False
        except Exception as exc:  # 防御性兜底
            message = f"构建表格异常：{exc}"
            self.build_status.emit("error", message)
            self.build_result.emit(False, message)
            self._log(message, "error")
            return False

        detail = (
            f"飞书 · 已摘录 {result.copied_records} 条 / "
            f"源表 {source.total_records} 条 · "
            f"{result.output_path.name}"
        )
        self.build_status.emit("done", detail)
        self.build_result.emit(True, str(result.output_path))
        self._log(
            f"构建表格完成：从「{result.source_sheet}」摘录 "
            f"{result.copied_records} 条（源表 {source.total_records} 条）。",
            "success",
        )
        self._log(f"新表格已保存：{result.output_path}", "success")
        if source.total_records > result.copied_records:
            self._log(
                f"测试阶段只摘录前 {result.copied_records} 条；"
                "将 config.json 的 excel.copy_limit 设为 0 可摘录更多。",
                "muted",
            )
        return True

    # ------------------------------------------------------------------
    # 工作线程
    # ------------------------------------------------------------------

    def _worker(
        self,
        slot: int,
        work_queue: queue.Queue,
        results: list[bool],
        results_lock: threading.Lock,
    ) -> None:
        while True:
            if self._cancel.is_set():
                return
            try:
                account = work_queue.get_nowait()
            except queue.Empty:
                return

            while self._pause.is_set():
                if self._cancel.is_set():
                    return
                time.sleep(0.2)
            if self._cancel.is_set():
                return

            masked = mask_phone(account.phone)
            password_type = (
                "默认密码" if account.password_is_default else "自定义密码"
            )
            self.thread_added.emit(slot, masked)
            self._log(
                f"线程 {slot} 开始处理 {masked}（{password_type}）", "info"
            )
            ok, detail = self._login_one(slot, account)
            with results_lock:
                results.append(ok)
            self.thread_finished.emit(slot, ok, detail)

    def _login_one(self, slot: int, account: Account) -> tuple[bool, str]:
        masked = mask_phone(account.phone)

        self.thread_step.emit(
            slot, 0, 5.0, StepStatus.RUNNING, "正在获取易盾 token…"
        )
        try:
            token, cookies = self._token_provider.capture(
                account.phone, account.password, self._cancel
            )
            self.thread_step.emit(
                slot, 0, 55.0, StepStatus.RUNNING, "正在协议密码登录…"
            )
            client = Pxb7Client(self._settings.pxb7, account.phone)
            client.load_cookies(cookies)
            result = client.login_with_password(
                account.phone, account.password, token
            )
        except Pxb7LoginError as exc:
            message = str(exc)
            self.thread_step.emit(
                slot, 0, 100.0, StepStatus.ERROR, message
            )
            self._log(f"线程 {slot} · {masked} 登录失败：{message}", "error")
            return False, message
        except Pxb7Error as exc:
            message = str(exc)
            if self._cancel.is_set():
                self._log(f"线程 {slot} · {masked} 已取消", "warn")
            else:
                self._log(
                    f"线程 {slot} · {masked} 登录异常：{message}", "error"
                )
            self.thread_step.emit(
                slot, 0, 100.0, StepStatus.ERROR, message
            )
            return False, message
        except Exception as exc:  # 防御性兜底
            message = f"未处理异常：{exc}"
            self.thread_step.emit(
                slot, 0, 100.0, StepStatus.ERROR, message
            )
            self._log(f"线程 {slot} · {masked} {message}", "error")
            return False, message

        username = result.username.strip()
        if not username:
            username = (
                f"用户{result.user_id}" if result.user_id else "未知用户"
            )
        detail = f"用户名：{username}"
        if result.user_id:
            detail += f" · 用户ID：{result.user_id}"

        self.thread_step.emit(
            slot, 0, 100.0, StepStatus.DONE, detail
        )
        self._log(
            f"线程 {slot} · {masked} 登录成功 · {detail}", "success"
        )
        if result.warning:
            self._log(f"线程 {slot} · {masked} {result.warning}", "warn")
        return True, detail

    def _log(self, message: str, level: str = "info") -> None:
        self.log_message.emit(message, level)
