"""手动询价：TXT 领取一个手机号，先批量发送，再轮询商家回复。"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from .services.account_claim import (
    AccountClaimError,
    claim_account,
    release_account,
)
from .services.accounts import Account
from .services.consult_history import (
    HISTORY_LOCK,
    ConsultHistoryStore,
    ConsultHistoryStoreError,
)
from .services.manual_log import (
    ManualLogError,
    append_manual_inquiry_log,
)
from .services.phone_login import (
    is_proxy_login_error,
    login_phone,
    proxy_error_hint,
)
from .services.phone_parser import mask_phone
from .services.proxy_provider import (
    ProxyPool,
    ProxySettings,
    ProxyStore,
    ProxyStoreError,
)
from .services.pxb7_chat import (
    PendingChatInquiry,
    PhoneSession,
    Pxb7ChatCancelled,
    Pxb7ChatService,
)
from .services.pxb7_yd_token import Pxb7BrowserYdTokenProvider
from .settings import AppSettings

_REPLY_POLL_INTERVAL = 2.0
_PROXY_LOGIN_ATTEMPTS = 3


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
    """一个手动窗口使用一个从 TXT 领取的手机号，窗口内严格串行。"""

    log_message = pyqtSignal(str, str)
    merchant_started = pyqtSignal(str)
    merchant_sent = pyqtSignal(str)
    merchant_quote = pyqtSignal(object)
    status_message = pyqtSignal(str)
    completed = pyqtSignal(bool, str)

    def __init__(
        self,
        settings: AppSettings,
        account_file: str | Path,
        merchants: list[str],
        image_paths: list[Path],
        phrases: tuple[str, ...],
        timeout: float,
        interval: float,
        log_path: str | Path | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._account_file = Path(account_file)
        self._merchants = list(merchants)
        self._image_paths = [Path(path) for path in image_paths]
        self._phrases = tuple(phrases)
        self._timeout = max(1.0, float(timeout))
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
        if not self._merchants:
            self._log("缺少商户，无法执行手动询价。", "error")
            self.completed.emit(False, "缺少商户")
            return
        if not self._image_paths:
            self._log("缺少账号截图，无法执行手动询价。", "error")
            self.completed.emit(False, "缺少账号截图")
            return

        self._log(
            f"开始手动询价：{len(self._merchants)} 个商户，"
            f"{len(self._image_paths)} 张截图；"
            "本窗口从 TXT 领取 1 个手机号。",
            "accent",
        )
        self.status_message.emit("正在从 TXT 领取手机号…")

        login = self._login_from_txt()
        if self._cancel.is_set():
            error = "手动询价已停止"
            self._log(error, "warn")
            self._record_remaining(
                self._merchants, set(), "已取消", error, ""
            )
            self.completed.emit(False, error)
            return
        if login is None:
            self._finish_without_login()
            return

        session, account = login
        masked_phone = mask_phone(account.phone)
        self._log(
            f"本窗口使用手机号 {masked_phone}；"
            "该手机号已从 TXT 删除，同级窗口不会重复领取。",
            "success",
        )
        self.status_message.emit(
            f"手机号 {masked_phone} 登录完成，准备发送询价…"
        )

        to_send, skipped = self._assign_history(account.phone)
        recorded: set[str] = set()
        for merchant in skipped:
            error = "该手机号已咨询过此商户，跳过"
            self._log(f"跳过商户「{merchant}」：{error}", "warn")
            self._record_quote(
                ManualMerchantQuote(
                    merchant=merchant,
                    phone=masked_phone,
                    phrase="",
                    price=None,
                    replies=(),
                    status="已咨询过",
                    elapsed=0.0,
                    log_path=self._log_path,
                    error=error,
                )
            )
            recorded.add(merchant)

        if not to_send:
            summary = "手动询价完成 · 所有商户均已咨询过"
            self._log(summary, "warn")
            self.completed.emit(True, summary)
            return

        pendings: list[PendingChatInquiry] = []
        quoted = 0
        fatal_error = ""
        service = Pxb7ChatService(
            self._settings,
            self._log,
            session=session,
        )
        try:
            service.__enter__()
        except Pxb7ChatCancelled:
            error = "手动询价已停止"
            self._record_remaining(
                to_send, recorded, "已取消", error, masked_phone
            )
            self._log(error, "warn")
            self.completed.emit(False, error)
            return
        except Exception as exc:
            error = f"聊天会话启动失败：{exc}"
            self._record_remaining(
                to_send, recorded, "失败", error, masked_phone
            )
            self._log(error, "error")
            self.completed.emit(False, error)
            return

        try:
            # 第一阶段：先给每个商户发送询价信息，聊天窗口保持打开。
            for merchant in to_send:
                if self._cancel.is_set():
                    break
                self.merchant_started.emit(merchant)
                phrase = (
                    random.choice(self._phrases) if self._phrases else ""
                )
                self._log(
                    f"商户「{merchant}」使用手机号 {masked_phone} "
                    "发送询价…",
                    "info",
                )
                if phrase:
                    self._log(f"本次话术：{phrase}", "muted")
                sent_count = len(pendings) + 1
                self.status_message.emit(
                    f"正在发送 {sent_count}/{len(to_send)} · {merchant}"
                )

                try:
                    pending = service.start_inquiry(
                        merchant,
                        self._image_paths,
                        phrase,
                        self._cancel,
                    )
                except Pxb7ChatCancelled:
                    raise
                except Exception as exc:
                    error = str(exc)
                    self._log(
                        f"商户「{merchant}」发送失败：{error}", "error"
                    )
                    self._record_quote(
                        ManualMerchantQuote(
                            merchant=merchant,
                            phone=masked_phone,
                            phrase=phrase,
                            price=None,
                            replies=(),
                            status="失败",
                            elapsed=0.0,
                            log_path=self._log_path,
                            error=error,
                        )
                    )
                    recorded.add(merchant)
                    continue

                pendings.append(pending)
                self.merchant_sent.emit(merchant)
                self._log(
                    f"已向商户「{merchant}」发送，继续处理下一家。",
                    "info",
                )
                if not self._sleep_interval():
                    break

            # 第二阶段：所有发送完成后，轮流检查各聊天窗口的新回复。
            if pendings and not self._cancel.is_set():
                self._log(
                    f"已向 {len(pendings)} 家商户发送完成，"
                    f"开始轮询回复；单家最多等待 {int(self._timeout)} 秒。",
                    "accent",
                )
                self.status_message.emit(
                    f"已发送 {len(pendings)} 家，正在监测回复…"
                )
                quoted += self._monitor(
                    service, pendings, masked_phone, recorded
                )
        except Pxb7ChatCancelled:
            self._log("手动询价已停止。", "warn")
        except Exception as exc:
            fatal_error = str(exc)
            self._log(f"手动询价异常：{fatal_error}", "error")
        finally:
            for pending in pendings:
                service.close_pending(pending)
            try:
                service.__exit__(None, None, None)
            except Exception:
                pass

        if self._cancel.is_set():
            self._record_remaining(
                to_send,
                recorded,
                "已取消",
                "手动询价已停止",
                masked_phone,
            )
            summary = "手动询价已停止"
            self._log(summary, "warn")
            self.completed.emit(False, summary)
        elif fatal_error:
            self._record_remaining(
                to_send, recorded, "失败", fatal_error, masked_phone
            )
            summary = f"手动询价异常：{fatal_error}"
            self.completed.emit(False, summary)
        else:
            self._record_remaining(
                to_send,
                recorded,
                "失败",
                "未执行完成",
                masked_phone,
            )
            summary = (
                f"手动询价完成 · {quoted}/{len(self._merchants)}"
                " 个商户有报价"
            )
            level = "success" if quoted else "warn"
            self._log(summary, level)
            self.completed.emit(True, summary)

    # ------------------------------------------------------------------
    # 手机号领取 / 登录
    # ------------------------------------------------------------------

    def _login_from_txt(
        self,
    ) -> tuple[PhoneSession, Account] | None:
        proxy_settings = ProxySettings()
        try:
            proxy_settings = ProxyStore().load()
        except ProxyStoreError as exc:
            self._log(
                f"代理设置读取失败：{exc}；为避免直连，将停止登录。",
                "error",
            )
            return None

        proxy_pool: ProxyPool | None = None
        if proxy_settings.enabled:
            proxy_pool = ProxyPool(proxy_settings, self._log)
            self._log("本窗口手机号登录已启用随机代理。", "warn")
        else:
            self._log("代理未启用，本窗口手机号将直连登录。", "warn")

        provider = Pxb7BrowserYdTokenProvider(
            self._settings.pxb7, self._settings.login, self._log
        )

        def acquire_proxy():
            if not proxy_settings.enabled:
                return None
            if proxy_pool is None:
                raise RuntimeError("代理池未初始化")
            self._log("正在获取随机代理…", "info")
            try:
                proxy = proxy_pool.acquire()
            except Exception as exc:
                raise RuntimeError(
                    f"代理获取失败：{exc}"
                ) from exc
            self._log(f"使用代理：{proxy.display()}", "info")
            return proxy

        while not self._cancel.is_set():
            # 先获取代理再领取手机号；代理接口失败不消耗 TXT 账号。
            try:
                proxy = acquire_proxy()
            except RuntimeError as exc:
                self._log(
                    f"{exc}；为避免直连，已停止领取手机号。",
                    "error",
                )
                return None

            try:
                account = claim_account(
                    self._account_file,
                    self._settings.login.default_password,
                )
            except AccountClaimError as exc:
                self._log(str(exc), "error")
                return None
            if account is None:
                self._log(
                    "TXT 中没有可领取的手机号：可能已被其他窗口领取或清单为空。",
                    "error",
                )
                return None

            masked = mask_phone(account.phone)
            self._log(
                f"已从 TXT 领取手机号 {masked}，并从清单中删除。",
                "info",
            )

            attempts = 0
            max_attempts = (
                _PROXY_LOGIN_ATTEMPTS if proxy is not None else 1
            )
            while not self._cancel.is_set():
                attempts += 1
                self._log(
                    f"手机号 {masked} 正在登录螃蟹平台"
                    f"（第 {attempts}/{max_attempts} 次尝试）…",
                    "info",
                )

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
                    message = str(exc)
                    self._log(
                        f"手机号 {masked} 登录失败：{message}",
                        "error",
                    )
                    if self._cancel.is_set():
                        self._release_account(account, masked)
                        return None

                    if is_proxy_login_error(exc):
                        hint = proxy_error_hint(exc)
                        if proxy is None:
                            self._log(
                                f"直连网络异常：{hint}；"
                                "手机号已放回 TXT。",
                                "error",
                            )
                            self._release_account(account, masked)
                            return None
                        if attempts < max_attempts:
                            self._log(
                                f"代理线路异常：{hint}；"
                                "更换代理后重试同一手机号…",
                                "warn",
                            )
                            try:
                                proxy = acquire_proxy()
                            except RuntimeError as proxy_exc:
                                self._log(
                                    f"{proxy_exc}；手机号已放回 TXT，"
                                    "停止本窗口登录。",
                                    "error",
                                )
                                self._release_account(
                                    account, masked
                                )
                                return None
                            continue

                        self._log(
                            f"手机号 {masked} 连续 {attempts} 次"
                            f"代理登录失败：{hint}；"
                            "手机号已放回 TXT。请检查代理白名单、"
                            "有效期或更换代理接口。",
                            "error",
                        )
                        self._release_account(account, masked)
                        return None

                    # 非代理问题（例如账号密码错误）：跳过该手机号，
                    # 继续领取下一个。
                    break

                if login.session is None:
                    self._log(
                        f"手机号 {masked} 未取得聊天会话，"
                        "继续领取下一个。",
                        "warn",
                    )
                    break

                self._log(
                    f"手机号 {masked} 登录成功 · 用户名："
                    f"{login.username}",
                    "success",
                )
                return login.session, account

        return None

    def _release_account(self, account: Account, masked: str) -> None:
        try:
            restored = release_account(self._account_file, account)
        except AccountClaimError as exc:
            self._log(
                f"手机号 {masked} 放回 TXT 失败：{exc}", "warn"
            )
            return
        if restored:
            self._log(
                f"已将手机号 {masked} 放回 TXT，未消耗该账号。",
                "warn",
            )
        else:
            self._log(
                f"手机号 {masked} 已存在于 TXT，无需重复放回。",
                "muted",
            )

    # ------------------------------------------------------------------
    # 咨询历史
    # ------------------------------------------------------------------

    def _assign_history(
        self, phone: str
    ) -> tuple[list[str], list[str]]:
        with HISTORY_LOCK:
            try:
                history = self._history_store.load()
            except ConsultHistoryStoreError as exc:
                self._log(
                    f"咨询历史读取失败：{exc}；本次按空历史执行。",
                    "warn",
                )
                history = {}

            to_send: list[str] = []
            skipped: list[str] = []
            for merchant in self._merchants:
                if merchant in history.get(phone, set()):
                    skipped.append(merchant)
                else:
                    to_send.append(merchant)
            if to_send:
                history.setdefault(phone, set()).update(to_send)
                self._save_history(history)
            return to_send, skipped

    def _save_history(self, history: dict[str, set[str]]) -> None:
        try:
            self._history_store.save(history)
        except ConsultHistoryStoreError as exc:
            self._log(
                f"咨询历史保存失败：{exc}；本次运行仍会避免重复。",
                "warn",
            )

    # ------------------------------------------------------------------
    # 回复监测
    # ------------------------------------------------------------------

    def _monitor(
        self,
        service: Pxb7ChatService,
        pendings: list[PendingChatInquiry],
        masked_phone: str,
        recorded: set[str],
    ) -> int:
        quoted = 0
        remaining = list(pendings)

        while remaining and not self._cancel.is_set():
            now = time.monotonic()
            for pending in list(remaining):
                if self._cancel.is_set():
                    break
                merchant = pending.merchant_name
                try:
                    price = service.poll_pending(
                        pending, self._cancel
                    )
                except Pxb7ChatCancelled:
                    raise
                except Exception as exc:
                    error = str(exc)
                    self._log(
                        f"商户「{merchant}」读取回复失败：{error}",
                        "error",
                    )
                    self._record_pending(
                        pending,
                        masked_phone,
                        "失败",
                        error,
                        recorded,
                    )
                    remaining.remove(pending)
                    continue

                if price is not None:
                    self._record_pending(
                        pending,
                        masked_phone,
                        "有报价",
                        "",
                        recorded,
                        price=price,
                    )
                    quoted += 1
                    remaining.remove(pending)
                    self._log(
                        f"商户「{merchant}」报价：{price:g}",
                        "success",
                    )
                elif now >= pending.sent_at + self._timeout:
                    self._record_pending(
                        pending,
                        masked_phone,
                        "未报价",
                        "",
                        recorded,
                    )
                    remaining.remove(pending)
                    self._log(
                        f"商户「{merchant}」在 {int(self._timeout)} "
                        "秒内未给出可识别报价。",
                        "warn",
                    )

            if remaining and not self._sleep_poll(
                _REPLY_POLL_INTERVAL
            ):
                break

        if remaining and self._cancel.is_set():
            for pending in remaining:
                self._record_pending(
                    pending,
                    masked_phone,
                    "已取消",
                    "手动询价已停止",
                    recorded,
                )
        return quoted

    def _record_pending(
        self,
        pending: PendingChatInquiry,
        masked_phone: str,
        status: str,
        error: str,
        recorded: set[str],
        *,
        price: float | int | None = None,
    ) -> None:
        if pending.merchant_name in recorded:
            return
        self._record_quote(
            ManualMerchantQuote(
                merchant=pending.merchant_name,
                phone=masked_phone,
                phrase=pending.phrase,
                price=price,
                replies=tuple(pending.replies),
                status=status,
                elapsed=time.monotonic() - pending.started_at,
                log_path=self._log_path,
                error=error,
            )
        )
        recorded.add(pending.merchant_name)

    # ------------------------------------------------------------------
    # 完成 / 日志
    # ------------------------------------------------------------------

    def _finish_without_login(self) -> None:
        error = (
            "TXT 中没有可领取手机号，或领取的手机号均登录失败"
        )
        self._log(error, "error")
        self._record_remaining(
            self._merchants, set(), "失败", error, ""
        )
        self.completed.emit(False, error)

    def _record_remaining(
        self,
        merchants: list[str],
        recorded: set[str],
        status: str,
        error: str,
        phone: str,
    ) -> None:
        for merchant in merchants:
            if merchant in recorded:
                continue
            self._record_quote(
                ManualMerchantQuote(
                    merchant=merchant,
                    phone=phone,
                    phrase="",
                    price=None,
                    replies=(),
                    status=status,
                    elapsed=0.0,
                    log_path=self._log_path,
                    error=error,
                )
            )
            recorded.add(merchant)

    def _record_quote(self, quote: ManualMerchantQuote) -> None:
        first_write = self._log_path is None
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
            if first_write:
                self._log(
                    f"询价日志表格：{self._log_path}", "info"
                )
        except ManualLogError as exc:
            self._log(
                f"询价日志表格保存失败：{exc}", "error"
            )
        self.merchant_quote.emit(quote)

    def _sleep_interval(self) -> bool:
        return self._sleep_poll(self._interval)

    def _sleep_poll(self, seconds: float) -> bool:
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end:
            if self._cancel.is_set():
                return False
            time.sleep(min(0.2, end - time.monotonic()))
        return not self._cancel.is_set()

    def _log(self, message: str, level: str = "info") -> None:
        self.log_message.emit(message, level)
