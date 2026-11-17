"""螃蟹商家聊天：进入坑位、发送账号内容图片/话术并识别商家报价。"""

from __future__ import annotations

import random
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from ..settings import AppSettings
from .pxb7_merchant import resolve_state_path, state_available

LogFn = Callable[[str, str], None]

_CHAT_READY_TIMEOUT = 25.0
_IMAGE_SEND_TIMEOUT = 10.0
_CHAT_MESSAGE_TIMEOUT = 5.0
_MESSAGE_GAP_MIN = 2.0
_MESSAGE_GAP_MAX = 8.0


class Pxb7ChatError(Exception):
    """螃蟹聊天询价失败。"""


class Pxb7ChatLoginRequired(Pxb7ChatError):
    """螃蟹登录状态缺失或已失效。"""


class Pxb7ChatCancelled(Pxb7ChatError):
    """询价已取消。"""


@dataclass(frozen=True)
class ChatQuoteResult:
    merchant_name: str
    price: float | None
    replies: tuple[str, ...]
    phrase: str
    timed_out: bool


@dataclass(frozen=True)
class PhoneSession:
    """协议登录手机号在官网聊天页使用的会话。"""

    phone: str
    token: str
    user_id: str
    cookies: tuple[dict[str, str], ...] = ()


class Pxb7ChatService:
    """复用已保存的螃蟹登录状态，在商家聊天坑位发送账号内容图片并等待报价。"""

    def __init__(
        self,
        settings: AppSettings,
        log: LogFn | None = None,
        session: PhoneSession | None = None,
    ) -> None:
        self._settings = settings
        self._account = settings.pxb7_account
        self._log = log or (lambda message, level: None)
        self._session = session
        self._state_path = resolve_state_path(self._account)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    # ------------------------------------------------------------------
    # 会话生命周期
    # ------------------------------------------------------------------

    def __enter__(self) -> "Pxb7ChatService":
        if self._session is None:
            if not state_available(self._account):
                raise Pxb7ChatLoginRequired(
                    "螃蟹登录状态不可用，请点击右上角「螃蟹未登录」"
                    "重新登录并获取咨询商家。"
                )
        elif not self._session.token:
            raise Pxb7ChatLoginRequired(
                "手机号会话缺少螃蟹登录 token，无法进入商家聊天。"
            )
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._launch(self._playwright)
            if self._session is None:
                self._context = self._browser.new_context(
                    storage_state=str(self._state_path),
                    locale="zh-CN",
                    viewport={"width": 1600, "height": 1200},
                )
            else:
                self._context = self._browser.new_context(
                    locale="zh-CN",
                    viewport={"width": 1600, "height": 1200},
                )
                self._context.add_cookies(
                    self._session_cookies(self._session)
                )
            self._page = self._context.new_page()
            self._page.set_default_timeout(15000)
            self._page.goto(
                self._account.recovery_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            self._page.wait_for_timeout(6000)
            self._ensure_logged_in()
            try:
                self._page.get_by_text(
                    "咨询商家", exact=True
                ).first.wait_for(state="visible", timeout=20000)
            except PlaywrightError as exc:
                raise Pxb7ChatError(
                    "未能打开三角洲行动回收商家列表。"
                ) from exc
            return self
        except Exception:
            self._close_browser()
            raise

    def __exit__(self, exc_type, exc, tb) -> None:
        self._close_browser()

    # ------------------------------------------------------------------
    # 询价
    # ------------------------------------------------------------------

    def inquire(
        self,
        merchant_name: str,
        screenshot_paths: Iterable[Path],
        phrase: str,
        timeout: float,
        cancel: threading.Event | None = None,
    ) -> ChatQuoteResult:
        cancel = cancel or threading.Event()
        self._check_cancel(cancel)
        screenshots = [Path(path) for path in screenshot_paths]
        selected_phrase = phrase.strip() or self._default_phrase()

        self._log(
            f"进入商家聊天坑位：{merchant_name}", "info"
        )
        card = self._find_merchant_card(merchant_name)
        chat = self._open_chat(card, cancel)
        try:
            self._wait_chat_ready(chat, cancel)
            baseline = self._left_texts(chat)

            if screenshots:
                self._send_screenshots(chat, screenshots, cancel)
            else:
                self._log(
                    f"{merchant_name}：该账号没有账号内容图片，"
                    "仅发送话术。",
                    "warn",
                )

            self._send_text(chat, selected_phrase, cancel, "话术")
            self._log(
                f"{merchant_name}：已发送账号内容图片和话术，"
                f"等待回复（最多 {int(timeout)} 秒）…",
                "info",
            )
            price, replies, timed_out = self._wait_for_price(
                chat, baseline, timeout, cancel, merchant_name
            )
        finally:
            try:
                if chat is not self._page:
                    chat.close()
            except Exception:
                pass

        if price is not None:
            self._log(
                f"{merchant_name} 报价：{price:g}", "success"
            )
        elif timed_out:
            self._log(
                f"{merchant_name} 在 {int(timeout)} 秒内未给出可识别报价。",
                "warn",
            )
        else:
            self._log(
                f"{merchant_name} 暂未给出可识别报价。", "warn"
            )

        return ChatQuoteResult(
            merchant_name=merchant_name,
            price=price,
            replies=tuple(replies),
            phrase=selected_phrase,
            timed_out=timed_out,
        )

    # ------------------------------------------------------------------
    # 商家 / 聊天页面
    # ------------------------------------------------------------------

    def _find_merchant_card(self, merchant_name: str):
        assert self._page is not None
        self._ensure_logged_in()
        name_locator = self._page.get_by_text(
            merchant_name, exact=True
        )
        try:
            count = name_locator.count()
        except PlaywrightError as exc:
            raise Pxb7ChatError(
                f"读取商家列表失败：{exc}"
            ) from exc
        for index in range(min(count, 5)):
            element = name_locator.nth(index)
            try:
                if not element.is_visible():
                    continue
                card = element.evaluate_handle(
                    """el => {
                        let node = el;
                        for (let i = 0; i < 6 && node; i++) {
                            const text = node.innerText || "";
                            if (text.includes("咨询商家") && text.length < 200) {
                                return node;
                            }
                            node = node.parentElement;
                        }
                        return null;
                    }"""
                ).as_element()
            except Exception:
                continue
            if card is not None:
                return card

        raise Pxb7ChatError(
            f"未在回收坑位中找到商家：{merchant_name}"
        )

    def _open_chat(self, card, cancel: threading.Event):
        assert self._page is not None
        button = card.query_selector("text=咨询商家")
        if button is None:
            raise Pxb7ChatError("商家卡片中没有「咨询商家」按钮。")

        self._check_cancel(cancel)
        pages_before = len(self._context.pages)
        try:
            with self._page.expect_popup(timeout=20000) as page_info:
                button.click()
            chat = page_info.value
        except PlaywrightTimeoutError:
            new_pages = [
                page
                for page in self._context.pages
                if page is not self._page
            ]
            if len(new_pages) > 0 and len(
                self._context.pages
            ) > pages_before:
                chat = new_pages[-1]
            else:
                raise Pxb7ChatError(
                    "点击「咨询商家」后未打开聊天页面。"
                )
        chat.set_default_timeout(15000)
        try:
            chat.wait_for_load_state(
                "domcontentloaded", timeout=20000
            )
        except PlaywrightError:
            pass
        return chat

    def _wait_chat_ready(self, chat, cancel: threading.Event) -> None:
        deadline = time.monotonic() + _CHAT_READY_TIMEOUT
        while time.monotonic() < deadline:
            self._check_cancel(cancel)
            try:
                panel = chat.locator(".px-chat")
                image_input = chat.locator(
                    "input[type=file][accept='image/*']"
                )
                body = chat.locator("body").inner_text(timeout=2000)
            except PlaywrightError:
                body = ""
                panel = None
                image_input = None
            if (
                panel is not None
                and panel.count() > 0
                and image_input is not None
                and image_input.count() > 0
                and "正在加载中" not in body
                and "没有数据哦" not in body
            ):
                return
            chat.wait_for_timeout(1000)
        raise Pxb7ChatError("螃蟹聊天页面加载超时。")

    # ------------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------------

    def _send_screenshots(
        self,
        chat,
        paths: list[Path],
        cancel: threading.Event,
    ) -> None:
        sent = 0
        for path in paths:
            self._check_cancel(cancel)
            if not path.is_file():
                self._log(
                    f"账号内容图片不存在，已跳过：{path.name}",
                    "warn",
                )
                continue
            input_locator = chat.locator(
                "input[type=file][accept='image/*']"
            ).first
            if input_locator.count() == 0:
                self._log(
                    "聊天页没有图片上传入口，停止发送账号内容图片。",
                    "warn",
                )
                break
            before = self._right_count(chat)
            try:
                input_locator.set_input_files(str(path))
            except PlaywrightError as exc:
                self._log(f"账号内容图片上传失败：{exc}", "warn")
                continue
            deadline = time.monotonic() + _IMAGE_SEND_TIMEOUT
            uploaded = False
            while time.monotonic() < deadline:
                self._check_cancel(cancel)
                chat.wait_for_timeout(500)
                if self._right_count(chat) > before:
                    uploaded = True
                    break
            if uploaded:
                sent += 1
                self._log(
                    f"已发送账号内容图片 {sent}/{len(paths)}。",
                    "muted",
                )
                self._message_gap(cancel)
            else:
                self._log(
                    f"账号内容图片 {path.name} 可能未发送成功。",
                    "warn",
                )
        if sent:
            self._log(
                f"账号内容图片发送完成：{sent} 张。", "info"
            )

    def _send_text(
        self,
        chat,
        text: str,
        cancel: threading.Event,
        label: str,
    ) -> None:
        self._check_cancel(cancel)
        editor = chat.locator(".ql-editor").first
        if editor.count() == 0:
            raise Pxb7ChatError("聊天页没有消息输入框。")
        editor.click()
        editor.fill(text)
        chat.wait_for_timeout(500)
        self._check_cancel(cancel)
        send = chat.get_by_text("发送", exact=True).first
        send.click()
        self._check_cancel(cancel)
        if label == "话术":
            self._log(f"已发送话术：{text}", "info")
        else:
            self._log(
                f"已发送{label}（{len(text)} 字）。", "info"
            )

        deadline = time.monotonic() + _CHAT_MESSAGE_TIMEOUT
        while time.monotonic() < deadline:
            try:
                body = chat.locator("body").inner_text(timeout=1000)
            except PlaywrightError:
                break
            if text in body:
                return
            chat.wait_for_timeout(500)

    # ------------------------------------------------------------------
    # 回复 / 报价
    # ------------------------------------------------------------------

    @staticmethod
    def _left_texts(chat) -> list[str]:
        locator = chat.locator(
            ".px-chat .px-pc-message.left .message-content"
        )
        values: list[str] = []
        for index in range(locator.count()):
            try:
                text = locator.nth(index).inner_text(timeout=500).strip()
            except Exception:
                text = ""
            values.append(text)
        return values

    @staticmethod
    def _right_count(chat) -> int:
        try:
            return chat.locator(
                ".px-chat .px-pc-message.right"
            ).count()
        except PlaywrightError:
            return 0

    def _wait_for_price(
        self,
        chat,
        baseline: list[str],
        timeout: float,
        cancel: threading.Event,
        merchant_name: str,
    ) -> tuple[float | None, list[str], bool]:
        last_count = len(baseline)
        replies: list[str] = []
        deadline = time.monotonic() + max(1.0, timeout)

        while time.monotonic() < deadline:
            self._check_cancel(cancel)
            try:
                current = self._left_texts(chat)
            except PlaywrightError:
                current = []
            if len(current) > last_count:
                for text in current[last_count:]:
                    if not text:
                        continue
                    replies.append(text)
                    preview = text.replace("\n", " ")
                    if len(preview) > 200:
                        preview = preview[:200] + "…"
                    self._log(
                        f"{merchant_name} 回复：{preview}", "info"
                    )
                    price = self.extract_price(text)
                    if price is not None:
                        return price, replies, False
                last_count = len(current)
            chat.wait_for_timeout(1000)

        return None, replies, True

    @staticmethod
    def extract_price(text: str) -> float | None:
        raw = (text or "").strip()
        if not raw:
            return None

        has_price_word = any(
            word in raw
            for word in (
                "报价",
                "回收价",
                "价格",
                "能收",
                "可以收",
                "出价",
                "给你",
                "收多少",
                "多少出",
                "我出",
                "最高",
                "给到",
                "收个",
                "收你",
            )
        ) or any(word in raw.lower() for word in ("rmb", "cny"))
        has_currency = any(
            symbol in raw for symbol in ("元", "块", "¥", "￥")
        )
        asset_words = (
            "总资产",
            "流动资产",
            "不动产",
            "刀皮",
            "枪械",
            "皮肤",
            "仓库",
            "等级",
        )
        if any(word in raw for word in asset_words) and not (
            has_price_word or has_currency
        ):
            return None

        patterns = (
            r"(?:报价|回收价|价格|能收|可以收|出价|给你|收多少|多少出|"
            r"我出|最高|给到|收个|收你)[^0-9]{0,8}[¥￥]?\s*"
            r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*"
            r"(万|w|W|k|K|千)?",
            r"[¥￥]\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*"
            r"(万|w|W|k|K|千)?",
            r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*"
            r"(?:元|块|rmb|RMB)",
        )
        for pattern in patterns:
            match = re.search(pattern, raw)
            if match:
                return _price_value(match.group(1), match.group(2))

        standalone = re.fullmatch(
            r"\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*"
            r"(万|w|W|k|K|千)?\s*",
            raw,
        )
        if standalone:
            return _price_value(
                standalone.group(1), standalone.group(2)
            )

        if len(raw) <= 24:
            short = re.search(
                r"(?<![\d.])([1-9][0-9]{2,6}(?:\.[0-9]+)?)"
                r"(?![\d.])",
                raw,
            )
            if short:
                return _price_value(short.group(1), "")
        return None

    # ------------------------------------------------------------------
    # 基础设施
    # ------------------------------------------------------------------

    def _ensure_logged_in(self) -> None:
        assert self._page is not None
        try:
            current_url = self._page.url
            body = self._page.locator("body").inner_text(timeout=3000)
        except PlaywrightError:
            current_url = ""
            body = ""
        if "/login" in current_url or "密码登录" in body:
            raise Pxb7ChatLoginRequired(
                "螃蟹登录状态已失效，请点击右上角「螃蟹未登录」"
                "重新登录后再开始询价。"
            )

    def _launch(self, playwright):
        channel = self._account.browser_channel or None
        try:
            return playwright.chromium.launch(
                headless=self._account.headless, channel=channel
            )
        except PlaywrightError:
            if not channel:
                raise
            self._log(
                f"启动浏览器通道 {channel} 失败，尝试 Chromium…",
                "warn",
            )
            return playwright.chromium.launch(
                headless=self._account.headless
            )

    @staticmethod
    def _session_cookies(session: PhoneSession) -> list[dict[str, str]]:
        cookies: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for cookie in session.cookies:
            name = str(cookie.get("name") or "")
            domain = str(cookie.get("domain") or "")
            if not name or "pxb7.com" not in domain:
                continue
            path = str(cookie.get("path") or "/")
            key = (name, domain, path)
            if key in seen:
                continue
            seen.add(key)
            cookies.append(
                {
                    "name": name,
                    "value": str(cookie.get("value") or ""),
                    "domain": domain,
                    "path": path,
                }
            )

        auth_cookies = (
            ("token", session.token),
            ("userId", session.user_id),
        )
        for name, value in auth_cookies:
            if not value:
                continue
            cookies = [
                cookie
                for cookie in cookies
                if not (
                    cookie["name"] == name
                    and cookie["domain"] == ".pxb7.com"
                )
            ]
            cookies.append(
                {
                    "name": name,
                    "value": value,
                    "domain": ".pxb7.com",
                    "path": "/",
                }
            )
        return cookies

    def _close_browser(self) -> None:
        if self._session is None and self._context is not None:
            try:
                self._state_path.parent.mkdir(
                    parents=True, exist_ok=True
                )
                self._context.storage_state(
                    path=str(self._state_path)
                )
            except Exception:
                pass
        self._context = None
        try:
            if self._browser is not None and self._browser.is_connected():
                self._browser.close()
        except Exception:
            pass
        self._browser = None
        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:
            pass
        self._playwright = None

    def _message_gap(self, cancel: threading.Event) -> None:
        delay = random.uniform(_MESSAGE_GAP_MIN, _MESSAGE_GAP_MAX)
        self._log(
            f"等待 {delay:.1f} 秒后发送下一条消息…", "muted"
        )
        end = time.monotonic() + delay
        while time.monotonic() < end:
            self._check_cancel(cancel)
            time.sleep(min(0.2, end - time.monotonic()))

    @staticmethod
    def _check_cancel(cancel: threading.Event) -> None:
        if cancel.is_set():
            raise Pxb7ChatCancelled("询价已取消。")

    @staticmethod
    def _default_phrase() -> str:
        return "你好，这个账号回收多少钱？"


def _price_value(number: str, suffix: str) -> float | int | None:
    try:
        value = float(number.replace(",", ""))
    except ValueError:
        return None
    factor = 1
    if suffix in ("万", "w", "W"):
        factor = 10000
    elif suffix in ("k", "K", "千"):
        factor = 1000
    value *= factor
    if value.is_integer():
        return int(value)
    return value
