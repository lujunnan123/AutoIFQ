"""螃蟹上号业务：读取短信后台验证码并完成协议登录。"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from ..settings import AppSettings, LoginSettings
from .phone_parser import mask_phone
from .pxb7_client import Pxb7Client, Pxb7LoginError
from .sms_admin_client import SmsAdminClient, SmsMessage
from .sms_code import extract_code

LogCallback = Callable[[str, str], None]


class LoginCancelled(Exception):
    """用户主动停止。"""


class SmsCodeTimeout(Exception):
    """在限定时间内没有拿到可用验证码。"""


@dataclass(frozen=True)
class LoginOutcome:
    phone: str
    username: str
    user_id: str
    sms: SmsMessage
    warning: str | None = None


def sms_rejection_reason(
    message: SmsMessage,
    config: LoginSettings,
    *,
    now: float | None = None,
    attempted: bool = False,
    min_timestamp: float | None = None,
) -> str | None:
    """返回该短信不符合条件的原因；符合条件时返回 None。"""
    if attempted:
        return "已尝试过"
    if config.sms_keyword not in message.content:
        return f"内容不含「{config.sms_keyword}」"

    server_timestamp = message.server_timestamp
    if server_timestamp <= 0:
        return "服务器时间无法解析"
    if min_timestamp is not None and server_timestamp < min_timestamp:
        return "早于本次触发时间"

    current = time.time() if now is None else now
    age = current - server_timestamp
    # 允许 60s 的服务器/本机时钟偏差。
    if age < -60 or age > config.sms_max_age_seconds:
        return (
            f"服务器时间超出 {config.sms_max_age_seconds / 60:.0f} 分钟窗口"
        )

    if not extract_code(message.content):
        return "短信未包含可提取的验证码"
    return None


class LoginService:
    def __init__(
        self,
        settings: AppSettings,
        admin: SmsAdminClient,
        log: LogCallback | None = None,
        sms_trigger: Callable[[str, threading.Event], bool] | None = None,
    ) -> None:
        self._settings = settings
        self._admin = admin
        self._log = log or (lambda _message, _level: None)
        self._sms_trigger = sms_trigger

    def login(
        self,
        phone: str,
        cancel: threading.Event | None = None,
        pause: threading.Event | None = None,
    ) -> LoginOutcome:
        cancel = cancel or threading.Event()
        pause = pause or threading.Event()

        masked = mask_phone(phone)
        config = self._settings.login
        client = Pxb7Client(self._settings.pxb7, phone)

        fresh_after: float | None = None
        if self._sms_trigger is not None:
            self._check_cancelled(cancel)
            try:
                triggered = self._sms_trigger(phone, cancel)
            except Exception as exc:
                triggered = False
                self._log(f"{masked} 触发短信异常：{exc}", "error")
            self._check_cancelled(cancel)
            if triggered:
                # 只接受本次触发之后到达的短信，避免复用旧验证码。
                fresh_after = time.time() - 30
                self._log(f"{masked} 短信已触发，开始刷新短信后台…", "info")
            else:
                self._log(
                    f"{masked} 浏览器触发未确认成功，继续刷新短信后台…",
                    "warn",
                )

        started = time.monotonic()
        deadline = started + config.sms_wait_timeout
        last_notice = started
        first_refresh = True
        attempted: set[str] = set()
        attempts = 0

        while True:
            self._check_cancelled(cancel)
            self._wait_if_paused(cancel, pause)

            now = time.monotonic()
            if now >= deadline:
                raise SmsCodeTimeout(
                    f"{config.sms_wait_timeout:.0f}s 内未找到符合条件的验证码短信"
                    f"（内容含「{config.sms_keyword}」，且服务器收到时间在 "
                    f"{config.sms_max_age_seconds / 60:.0f} 分钟内），"
                    "判定该手机号无法收到验证码。"
                    "若已通过浏览器触发仍未收到，请检查短信后台设备或稍后重试。"
                )

            messages = self._admin.latest_messages(
                phone, page_size=max(20, config.sms_latest_count)
            )
            latest = messages[: config.sms_latest_count]
            candidate = self._pick_candidate(latest, attempted, fresh_after)

            if candidate is not None:
                message, code = candidate
                attempted.add(message.identity())
                attempts += 1

                delay = message.delay_seconds()
                delay_text = f"，延迟约 {delay}s" if delay is not None else ""
                server_time = message.created_at or message.received_at or "未知"
                self._log(
                    f"{masked} 找到螃蟹账号验证码短信"
                    f"（服务器收到：{server_time}{delay_text}）",
                    "info",
                )

                try:
                    result = client.login_with_code(phone, code)
                    return LoginOutcome(
                        phone=phone,
                        username=result.username,
                        user_id=result.user_id,
                        sms=message,
                        warning=result.warning,
                    )
                except Pxb7LoginError as exc:
                    if exc.retryable and attempts < config.max_code_attempts:
                        self._log(
                            f"{masked} 验证码无效或已过期，继续刷新短信", "warn"
                        )
                        continue
                    raise

            now = time.monotonic()
            if first_refresh or now - last_notice >= config.status_log_interval:
                waited = int(now - started)
                self._log_refresh_summary(
                    masked, latest, attempted, waited, fresh_after
                )
                last_notice = now
                first_refresh = False

            self._sleep(config.sms_poll_interval, cancel, pause)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _pick_candidate(
        self,
        messages: list[SmsMessage],
        attempted: set[str],
        min_timestamp: float | None = None,
    ) -> tuple[SmsMessage, str] | None:
        """只接受：关键字、时间窗口、本次触发之后到达的短信。"""
        config = self._settings.login
        now = time.time()
        for message in messages:
            if message.identity() in attempted:
                continue
            if (
                sms_rejection_reason(
                    message, config, now=now, min_timestamp=min_timestamp
                )
                is not None
            ):
                continue
            code = extract_code(message.content)
            if code:
                return message, code
        return None

    def _log_refresh_summary(
        self,
        masked_phone: str,
        latest: list[SmsMessage],
        attempted: set[str],
        waited: int,
        min_timestamp: float | None = None,
    ) -> None:
        """在没有候选短信时，说明每条短信被过滤的原因，便于排查。"""
        hint = ""
        if not latest:
            detail = "接口未返回该号码的收件短信（短信可能没有进入短信后台设备）"
        else:
            config = self._settings.login
            now = time.time()
            counts: dict[str, int] = {}
            stale_pxb7 = False
            for message in latest:
                reason = sms_rejection_reason(
                    message,
                    config,
                    now=now,
                    attempted=message.identity() in attempted,
                    min_timestamp=min_timestamp,
                )
                key = reason or "符合条件"
                counts[key] = counts.get(key, 0) + 1
                if (
                    config.sms_keyword in message.content
                    and message.server_timestamp > 0
                    and now - message.server_timestamp
                    > config.sms_max_age_seconds
                ):
                    stale_pxb7 = True
            detail = "、".join(
                f"{count} 条{reason}" for reason, count in counts.items()
            )
            if stale_pxb7:
                hint = "；检测到螃蟹账号旧短信，请重新触发登录验证码"
        self._log(
            f"{masked_phone} 刷新短信（最新 {len(latest)} 条）："
            f"{detail}{hint}（已等待 {waited}s）",
            "info",
        )

    @staticmethod
    def _check_cancelled(cancel: threading.Event) -> None:
        if cancel.is_set():
            raise LoginCancelled()

    def _wait_if_paused(
        self, cancel: threading.Event, pause: threading.Event
    ) -> None:
        while pause.is_set():
            self._check_cancelled(cancel)
            time.sleep(0.2)

    def _sleep(
        self, seconds: float, cancel: threading.Event, pause: threading.Event
    ) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self._check_cancelled(cancel)
            if pause.is_set():
                self._wait_if_paused(cancel, pause)
                end = time.monotonic() + seconds
                continue
            time.sleep(min(0.2, max(0.0, end - time.monotonic())))
