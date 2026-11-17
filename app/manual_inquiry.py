"""手动询价后台任务：TXT 手机号 + 代理登录，再执行商户聊天询价。"""

from __future__ import annotations

import queue
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from .services.accounts import Account
from .services.consult_history import (
    ConsultHistoryStore,
    ConsultHistoryStoreError,
)
from .services.manual_log import (
    ManualLogError,
    append_manual_inquiry_log,
)
from .services.phone_login import login_phone
from .services.phone_parser import mask_phone
from .services.proxy_provider import (
    ProxyPool,
    ProxySettings,
    ProxyStore,
    ProxyStoreError,
)
from .services.pxb7_chat import (
    PhoneSession,
    Pxb7ChatCancelled,
    Pxb7ChatService,
)
from .services.pxb7_yd_token import Pxb7BrowserYdTokenProvider
from .settings import AppSettings


@dataclass(frozen=True)
class ManualMerchantQuote:
    merchant: str
    phone: str
    phrase: str
    price: float | int | None
    replies: tuple[str, ...]
    status: str
    elapsed: float
    log_path: Path | None
    error: str


class ManualInquiryRunner(QThread):
    log_message = pyqtSignal(str, str)
    merchant_started = pyqtSignal(str)
    merchant_quote = pyqtSignal(object)
    status_message = pyqtSignal(str)
    completed = pyqtSignal(bool, str)

    def __init__(
        self,
        settings: AppSettings,
        accounts: list[Account],
        merchants: list[str],
        image_paths: list[Path],
        phrases: tuple[str, ...],
        timeout: float,
        threads: int,
        interval: float,
        log_path: str | Path | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._accounts = list(accounts)
        self._merchants = list(merchants)
        self._image_paths = [Path(path) for path in image_paths]
        self._phrases = tuple(phrases)
        self._timeout = max(1.0, float(timeout))
        self._threads = max(1, min(int(threads), max(1, len(self._accounts))))
        self._interval = max(0.0, float(interval))
        self._log_path = Path(log_path) if log_path else None
        self._cancel = threading.Event()
        self._history_store = ConsultHistoryStore()

    def cancel(self) -> None:
        self._cancel.set()

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    def run(self) -> None:
        if not self._accounts or not self._merchants:
            self._log("缺少手机号或商户，无法执行手动询价。", "error")
            self.completed.emit(False, "缺少手机号或商户")
            return
        if not self._image_paths:
            self._log("缺少账号截图，无法执行手动询价。", "error")
            self.completed.emit(False, "缺少账号截图")
            return

        self._log(
            f"开始手动询价：{len(self._accounts)} 个 TXT 手机号，"
            f"{len(self._merchants)} 个商户，{len(self._image_paths)} 张截图。",
            "accent",
        )
        self.status_message.emit("正在登录 TXT 手机号…")

        sessions = self._login_accounts()
        if self._cancel.is_set():
            self._log("手动询价已停止。", "warn")
            self.completed.emit(False, "已停止")
            return
        if not sessions:
            self._log("没有成功的手机号登录会话，无法询价。", "error")
            self._finish_without_sessions()
            return

        self._log(
            f"手机号登录完成：{len(sessions)} 个会话可用，开始商户询价。",
            "success",
        )
        self.status_message.emit("手机号登录完成，正在询价…")

        try:
            history = self._history_store.load()
        except ConsultHistoryStoreError as exc:
            self._log(
                f"咨询历史读取失败：{exc}；本次按空历史执行。", "warn"
            )
            history = {}

        phone_order = [
            account.phone
            for account in self._accounts
            if account.phone in sessions
        ]

        # 与主流程一致：先按手机号分配商户，再复用同一聊天会话逐条询价。
        assignments: dict[str, list[str]] = {
            phone: [] for phone in phone_order
        }
        skipped: list[str] = []
        for merchant in self._merchants:
            phone = self._choose_phone(merchant, phone_order, history)
            if phone is None:
                skipped.append(merchant)
                continue
            history.setdefault(phone, set()).add(merchant)
            assignments[phone].append(merchant)
        self._save_history(history)

        for merchant in skipped:
            error = "没有可用于该商户的手机号（均已咨询过或登录失败）"
            self._log(f"跳过商户「{merchant}」：{error}", "warn")
            self._record_quote(
                ManualMerchantQuote(
                    merchant=merchant,
                    phone="",
                    phrase="",
                    price=None,
                    replies=(),
                    status="失败",
                    elapsed=0.0,
                    log_path=self._log_path,
                    error=error,
                )
            )

        quoted = 0
        for phone in phone_order:
            tasks = assignments.get(phone) or []
            if not tasks:
                continue
            if self._cancel.is_set():
                break
            masked_phone = mask_phone(phone)
            self._log(
                f"手机号 {masked_phone}：分配 {len(tasks)} 个商户询价任务。",
                "info",
            )
            service = Pxb7ChatService(
                self._settings,
                self._log,
                session=sessions[phone],
            )
            try:
                service.__enter__()
            except Pxb7ChatCancelled:
                break
            except Exception as exc:
                error = f"聊天会话启动失败：{exc}"
                self._log(
                    f"手机号 {masked_phone} {error}；"
                    "该手机号任务全部跳过。",
                    "warn",
                )
                for merchant in tasks:
                    self._record_quote(
                        ManualMerchantQuote(
                            merchant=merchant,
                            phone=masked_phone,
                            phrase="",
                            price=None,
                            replies=(),
                            status="失败",
                            elapsed=0.0,
                            log_path=self._log_path,
                            error=error,
                        )
                    )
                continue

            try:
                for merchant in tasks:
                    if self._cancel.is_set():
                        break
                    quote = self._inquire_merchant(
                        service, merchant, phone, masked_phone
                    )
                    self._record_quote(quote)
                    if quote.price is not None:
                        quoted += 1
                    if self._cancel.is_set():
                        break
                    if not self._sleep_interval():
                        break
            except Pxb7ChatCancelled:
                self._log("手动询价已停止。", "warn")
                break
            finally:
                try:
                    service.__exit__(None, None, None)
                except Exception:
                    pass

            if self._cancel.is_set():
                break

        cancelled = self._cancel.is_set()
        if cancelled:
            summary = "手动询价已停止"
            self._log(summary, "warn")
            self.completed.emit(False, summary)
        else:
            summary = (
                f"手动询价完成 · {quoted}/{len(self._merchants)} 个商户有报价"
            )
            level = "success" if quoted else "warn"
            self._log(summary, level)
            self.completed.emit(True, summary)

    def _inquire_merchant(
        self,
        service: Pxb7ChatService,
        merchant: str,
        phone: str,
        masked_phone: str,
    ) -> ManualMerchantQuote:
        phrase = random.choice(self._phrases) if self._phrases else ""
        self.merchant_started.emit(merchant)
        self._log(
            f"商户「{merchant}」使用手机号 {masked_phone} 询价…",
            "info",
        )
        if phrase:
            self._log(f"本次话术：{phrase}", "muted")
        self.status_message.emit(
            f"商户「{merchant}」询价中 · {masked_phone}"
        )

        started = time.monotonic()
        result = None
        error = ""
        try:
            result = service.inquire(
                merchant,
                self._image_paths,
                phrase,
                self._timeout,
                self._cancel,
            )
        except Pxb7ChatCancelled:
            raise
        except Exception as exc:
            error = str(exc)
            self._log(
                f"商户「{merchant}」询价失败：{error}", "error"
            )

        elapsed = time.monotonic() - started
        price = result.price if result is not None else None
        replies = result.replies if result is not None else ()
        if self._cancel.is_set():
            status = "已取消"
        elif error:
            status = "失败"
        elif price is not None:
            status = "有报价"
        else:
            status = "未报价"
        return ManualMerchantQuote(
            merchant=merchant,
            phone=masked_phone,
            phrase=phrase,
            price=price,
            replies=tuple(replies),
            status=status,
            elapsed=elapsed,
            log_path=self._log_path,
            error=error,
        )

    # ------------------------------------------------------------------
    # 手机号登录
    # ------------------------------------------------------------------

    def _login_accounts(self) -> dict[str, PhoneSession]:
        proxy_settings = ProxySettings()
        try:
            proxy_settings = ProxyStore().load()
        except ProxyStoreError as exc:
            self._log(
                f"代理设置读取失败：{exc}；为避免直连，将跳过手机号登录。",
                "error",
            )
            proxy_settings = ProxySettings(
                enabled=True, api_url="", fetch_count=5, timeout_sec=20.0
            )

        proxy_pool: ProxyPool | None = None
        if proxy_settings.enabled:
            proxy_pool = ProxyPool(proxy_settings, self._log)
            self._log(
                "手动询价手机号登录已启用随机代理。", "warn"
            )
        else:
            self._log(
                "代理未启用，手动询价手机号将直连登录。", "warn"
            )

        provider = Pxb7BrowserYdTokenProvider(
            self._settings.pxb7, self._settings.login, self._log
        )
        sessions: dict[str, PhoneSession] = {}
        sessions_lock = threading.Lock()
        work_queue: queue.Queue = queue.Queue()
        for account in self._accounts:
            work_queue.put(account)

        def worker() -> None:
            while not self._cancel.is_set():
                try:
                    account = work_queue.get_nowait()
                except queue.Empty:
                    return
                masked = mask_phone(account.phone)
                proxy = None
                if proxy_settings.enabled:
                    self._log(
                        f"手机号 {masked} 正在获取随机代理…", "info"
                    )
                    try:
                        if proxy_pool is None:
                            raise RuntimeError("代理池未初始化")
                        proxy = proxy_pool.acquire()
                    except Exception as exc:
                        self._log(
                            f"手机号 {masked} 代理获取失败：{exc}；"
                            "跳过该手机号，不使用直连。",
                            "error",
                        )
                        continue
                    self._log(
                        f"手机号 {masked} 使用代理：{proxy.display()}",
                        "info",
                    )
                self._log(f"手机号 {masked} 正在登录螃蟹平台…", "info")

                def on_step(progress: float, detail: str) -> None:
                    if progress in (5.0, 55.0):
                        self._log(
                            f"手机号 {masked}：{detail}", "muted"
                        )

                try:
                    login = login_phone(
                        self._settings,
                        account,
                        proxy,
                        self._cancel,
                        provider,
                        on_step,
                    )
                except Exception as exc:
                    self._log(
                        f"手机号 {masked} 登录失败：{exc}", "error"
                    )
                    continue
                if login.session is None:
                    self._log(
                        f"手机号 {masked} 未取得聊天会话，已跳过。",
                        "warn",
                    )
                    continue
                with sessions_lock:
                    sessions[account.phone] = login.session
                self._log(
                    f"手机号 {masked} 登录成功 · 用户名："
                    f"{login.username}",
                    "success",
                )

        workers = [
            threading.Thread(target=worker, daemon=True)
            for _ in range(min(self._threads, len(self._accounts)))
        ]
        for thread in workers:
            thread.start()
        for thread in workers:
            thread.join()
        return sessions

    def _finish_without_sessions(self) -> None:
        for merchant in self._merchants:
            quote = ManualMerchantQuote(
                merchant=merchant,
                phone="",
                phrase="",
                price=None,
                replies=(),
                status="失败",
                elapsed=0.0,
                log_path=self._log_path,
                error="没有可用的手机号登录会话",
            )
            self._record_quote(quote)
        self.completed.emit(False, "没有可用的手机号登录会话")

    # ------------------------------------------------------------------
    # 历史 / 日志
    # ------------------------------------------------------------------

    @staticmethod
    def _choose_phone(
        merchant: str,
        phone_order: list[str],
        history: dict[str, set[str]],
    ) -> str | None:
        for phone in phone_order:
            if merchant not in history.get(phone, set()):
                return phone
        return None

    def _save_history(self, history: dict[str, set[str]]) -> None:
        try:
            self._history_store.save(history)
        except ConsultHistoryStoreError as exc:
            self._log(
                f"咨询历史保存失败：{exc}；本次运行仍会避免重复。",
                "warn",
            )

    def _record_quote(self, quote: ManualMerchantQuote) -> None:
        try:
            self._log_path = append_manual_inquiry_log(
                self._log_path,
                merchant=quote.merchant,
                phone=quote.phone,
                image_paths=self._image_paths,
                phrase=quote.phrase,
                replies=quote.replies,
                price=quote.price,
                status=quote.status,
                elapsed=quote.elapsed,
                error=quote.error,
                output_dir=self._settings.excel.output_dir or None,
            )
            quote = ManualMerchantQuote(
                merchant=quote.merchant,
                phone=quote.phone,
                phrase=quote.phrase,
                price=quote.price,
                replies=quote.replies,
                status=quote.status,
                elapsed=quote.elapsed,
                log_path=self._log_path,
                error=quote.error,
            )
            self._log(f"询价日志表格：{self._log_path}", "info")
        except ManualLogError as exc:
            self._log(
                f"询价日志表格保存失败：{exc}", "error"
            )
        self.merchant_quote.emit(quote)

    def _sleep_interval(self) -> bool:
        end = time.monotonic() + self._interval
        while time.monotonic() < end:
            if self._cancel.is_set():
                return False
            time.sleep(min(0.2, end - time.monotonic()))
        return not self._cancel.is_set()

    def _log(self, message: str, level: str = "info") -> None:
        self.log_message.emit(message, level)
