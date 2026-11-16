"""读取飞书多维表格：解析页面接口返回的字段与记录（不依赖剪贴板）。"""

from __future__ import annotations

import base64
import gzip
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import parse_qs, urlparse

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

from ..settings import FeishuSettings
from .excel_table import REQUIRED_COLUMNS, _normalize
from .feishu_common import feishu_logged_in, resolve_state_path

LogFn = Callable[[str, str], None]

_CLIENT_VARS_TIMEOUT = 30.0
_REQUIRED_NORMALIZED = {_normalize(name) for name in REQUIRED_COLUMNS}
_TIMEZONE_OFFSETS = {
    "Asia/Shanghai": 8,
    "Asia/Chongqing": 8,
    "Asia/Harbin": 8,
    "Asia/Hong_Kong": 8,
    "Asia/Macau": 8,
    "Asia/Taipei": 8,
    "Asia/Singapore": 8,
}


class FeishuTableError(Exception):
    """飞书表格读取失败。"""


class FeishuLoginRequired(FeishuTableError):
    """飞书登录状态缺失或已失效。"""


@dataclass(frozen=True)
class FeishuTableData:
    rows: list[tuple[object, ...]]
    total_records: int
    source_name: str
    page_url: str
    headers: tuple[str, ...] = REQUIRED_COLUMNS


class FeishuTableClient:
    """使用已保存的飞书登录状态读取目标多维表格。"""

    def __init__(
        self,
        config: FeishuSettings,
        log: LogFn | None = None,
    ) -> None:
        self._config = config
        self._log = log or (lambda message, level: None)
        self._state_path = resolve_state_path(config)
        self._table_id = self._extract_table_id(config.table_url)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def fetch_records(self, limit: int = 0) -> FeishuTableData:
        """读取当前视图记录；limit>0 时只返回前 limit 条。"""
        if sync_playwright is None:
            raise FeishuTableError(
                "未安装 Playwright，无法读取飞书表格。"
                "请执行 pip install -r requirements.txt。"
            )
        if not feishu_logged_in(self._config):
            raise FeishuLoginRequired(
                "尚未登录飞书，请先点击界面右上角「飞书未登录」扫码登录。"
            )

        headless = self._config.fetch_headless
        try:
            return self._fetch(headless=headless, limit=limit)
        except FeishuLoginRequired:
            raise
        except FeishuTableError as exc:
            if not headless:
                raise
            self._log(
                f"无头模式读取飞书表格失败：{exc}；改用可见浏览器重试…",
                "warn",
            )
            return self._fetch(headless=False, limit=limit)

    # ------------------------------------------------------------------
    # 浏览器读取
    # ------------------------------------------------------------------

    def _fetch(self, *, headless: bool, limit: int) -> FeishuTableData:
        self._log("正在打开飞书多维表格并读取记录…", "info")
        browser = None
        captured: dict[str, object] = {}
        try:
            with sync_playwright() as playwright:
                browser = self._launch(playwright, headless=headless)
                context = browser.new_context(
                    storage_state=str(self._state_path),
                    locale="zh-CN",
                    viewport={"width": 1600, "height": 1000},
                )
                page = context.new_page()

                def on_response(response) -> None:
                    if captured.get("table") is not None:
                        return
                    if "/clientvars" not in response.url:
                        return
                    if (
                        self._table_id
                        and self._table_id not in response.url
                    ):
                        return
                    try:
                        data = response.json()
                    except Exception:
                        return
                    payload = (
                        data.get("data")
                        if isinstance(data, dict)
                        else None
                    )
                    if not isinstance(payload, dict):
                        return
                    table_raw = payload.get("table")
                    if not table_raw:
                        return
                    try:
                        table = self._decode_embedded(table_raw)
                    except Exception:
                        return
                    if not isinstance(table, dict):
                        return
                    meta = table.get("meta") or {}
                    table_id = meta.get("id") if isinstance(meta, dict) else None
                    if (
                        self._table_id
                        and table_id
                        and table_id != self._table_id
                    ):
                        return
                    captured["table"] = table
                    base_raw = payload.get("base")
                    if base_raw:
                        try:
                            base = self._decode_embedded(base_raw)
                            timezone_name = base.get("timezone")
                            if isinstance(timezone_name, str):
                                captured["timezone"] = timezone_name
                        except Exception:
                            pass

                page.on("response", on_response)
                page.goto(
                    self._config.table_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

                deadline = time.monotonic() + _CLIENT_VARS_TIMEOUT
                while (
                    time.monotonic() < deadline
                    and captured.get("table") is None
                ):
                    page.wait_for_timeout(300)

                table = captured.get("table")
                if not isinstance(table, dict):
                    self._raise_for_unloaded_page(page)

                timezone_name = captured.get("timezone")
                rows, total = self._extract_rows(
                    table,
                    limit,
                    timezone_name=(
                        timezone_name
                        if isinstance(timezone_name, str)
                        else ""
                    ),
                )
                if not rows:
                    raise FeishuTableError(
                        "飞书表格当前视图没有可读取的记录。"
                    )

                try:
                    context.storage_state(path=str(self._state_path))
                except Exception:
                    pass

                source_name = (
                    f"{self._config.base_name} / {self._config.table_name}"
                )
                if limit > 0:
                    self._log(
                        f"飞书表格读取成功：{source_name}，"
                        f"源表 {total} 条，已摘录前 {len(rows)} 条。",
                        "success",
                    )
                else:
                    self._log(
                        f"飞书表格读取成功：{source_name}，"
                        f"共 {total} 条，已摘录 {len(rows)} 条。",
                        "success",
                    )
                    if total > len(rows):
                        self._log(
                            f"当前页面接口仅加载了前 {len(rows)} 条记录。",
                            "warn",
                        )
                return FeishuTableData(
                    rows=rows,
                    total_records=total,
                    source_name=source_name,
                    page_url=page.url,
                    headers=REQUIRED_COLUMNS,
                )
        except PlaywrightTimeoutError as exc:
            raise FeishuTableError(
                f"访问飞书多维表格超时：{exc}"
            ) from exc
        except PlaywrightError as exc:
            raise FeishuTableError(
                f"飞书浏览器操作失败：{exc}"
            ) from exc
        finally:
            if browser is not None:
                try:
                    if browser.is_connected():
                        browser.close()
                except Exception:
                    pass

    def _raise_for_unloaded_page(self, page) -> None:
        try:
            page_url = page.url
        except Exception:
            page_url = ""
        try:
            body = page.locator("body").inner_text(timeout=3000)
        except Exception:
            body = ""

        login_cues = (
            "扫码登录",
            "使用飞书移动端扫码",
            "使用 飞书移动端 扫码",
            "使用 豆包/飞书移动端 扫码",
        )
        if "accounts.feishu.cn" in page_url or any(
            cue in body for cue in login_cues
        ):
            raise FeishuLoginRequired(
                "飞书登录状态已失效，请点击右上角重新扫码登录。"
            )

        raise FeishuTableError(
            "未能读取飞书表格接口数据，请稍后重试；"
            "若持续失败，可尝试重新登录飞书。"
        )

    def _launch(self, playwright, *, headless: bool):
        channel = self._config.browser_channel or None
        try:
            return playwright.chromium.launch(
                headless=headless, channel=channel
            )
        except PlaywrightError:
            if not channel:
                raise
            self._log(
                f"启动浏览器通道 {channel} 失败，尝试 Playwright Chromium…",
                "warn",
            )
            return playwright.chromium.launch(headless=headless)

    # ------------------------------------------------------------------
    # 数据解析
    # ------------------------------------------------------------------

    def _extract_rows(
        self,
        table: dict,
        limit: int,
        *,
        timezone_name: str = "",
    ) -> tuple[list[tuple[object, ...]], int]:
        field_map = table.get("fieldMap") or {}
        if not isinstance(field_map, dict):
            raise FeishuTableError("飞书表格字段信息格式异常。")

        by_name: dict[str, tuple[str, dict]] = {}
        available_names: list[str] = []
        for field_id, meta in field_map.items():
            if not isinstance(meta, dict):
                continue
            name = meta.get("name")
            if not isinstance(name, str):
                continue
            available_names.append(name)
            normalized = _normalize(name)
            if normalized in _REQUIRED_NORMALIZED:
                by_name.setdefault(normalized, (field_id, meta))

        missing = [
            name
            for name in REQUIRED_COLUMNS
            if _normalize(name) not in by_name
        ]
        if missing:
            example = "、".join(available_names[:30]) or "空"
            raise FeishuTableError(
                f"飞书表格缺少必要字段：{'、'.join(missing)}。"
                f"当前字段：{example}"
            )

        record_map = table.get("recordMap") or {}
        if not isinstance(record_map, dict):
            raise FeishuTableError("飞书表格记录信息格式异常。")

        record_ids: list[str] = []
        for group in table.get("groupList") or []:
            if not isinstance(group, dict):
                continue
            for record_id in group.get("recordIDList") or []:
                if isinstance(record_id, str):
                    record_ids.append(record_id)
        if not record_ids:
            record_ids = list(record_map.keys())

        seen: set[str] = set()
        selected: list[str] = []
        for record_id in record_ids:
            if record_id in seen or record_id not in record_map:
                continue
            seen.add(record_id)
            selected.append(record_id)
            if limit > 0 and len(selected) >= limit:
                break

        rows: list[tuple[object, ...]] = []
        for record_id in selected:
            record = record_map.get(record_id) or {}
            if not isinstance(record, dict):
                continue
            values: list[object] = []
            for name in REQUIRED_COLUMNS:
                field_id, meta = by_name[_normalize(name)]
                values.append(
                    self._field_value(
                        record.get(field_id), meta, timezone_name
                    )
                )
            rows.append(tuple(values))

        total_raw = table.get("recordCount")
        total = (
            total_raw
            if isinstance(total_raw, int) and total_raw >= 0
            else len(record_map)
        )
        return rows, total

    @classmethod
    def _field_value(
        cls,
        entry: object,
        meta: dict,
        timezone_name: str = "",
    ) -> object:
        raw = entry
        if isinstance(entry, dict) and "value" in entry:
            raw = entry.get("value")

        field_type = meta.get("type")
        if field_type == 5:  # 日期
            return cls._date_value(raw, timezone_name)
        if field_type == 2:  # 数字
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                return raw
            text = cls._text_of(raw)
            try:
                return float(text) if "." in text else int(text)
            except (TypeError, ValueError):
                return text
        if field_type == 7:  # 复选框
            if isinstance(raw, bool):
                return "是" if raw else "否"
            return cls._text_of(raw)
        return cls._text_of(raw)

    @staticmethod
    def _date_value(raw: object, timezone_name: str = "") -> object:
        if isinstance(raw, (int, float)) and raw:
            offset_hours = _TIMEZONE_OFFSETS.get(timezone_name)
            try:
                if offset_hours is not None:
                    moment = datetime.fromtimestamp(
                        raw / 1000,
                        tz=timezone(timedelta(hours=offset_hours)),
                    ).replace(tzinfo=None)
                else:
                    moment = datetime.fromtimestamp(raw / 1000)
                return moment.replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
            except (OverflowError, OSError, ValueError):
                pass
        return FeishuTableClient._text_of(raw)

    @staticmethod
    def _text_of(raw: object) -> str:
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw
        if isinstance(raw, bool):
            return "是" if raw else "否"
        if isinstance(raw, (int, float)):
            return str(raw)
        if isinstance(raw, list):
            return "".join(
                FeishuTableClient._text_of(item) for item in raw
            )
        if isinstance(raw, dict):
            for key in ("text", "name", "value", "en_name"):
                if key in raw:
                    return FeishuTableClient._text_of(raw[key])
            return ""
        return str(raw)

    @staticmethod
    def _decode_embedded(value: object) -> dict:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            raise FeishuTableError("飞书表格数据格式异常。")
        raw = base64.b64decode(value)
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
        table = json.loads(raw)
        if not isinstance(table, dict):
            raise FeishuTableError("飞书表格数据格式异常。")
        return table

    @staticmethod
    def _extract_table_id(table_url: str) -> str:
        try:
            query = parse_qs(urlparse(table_url).query)
        except Exception:
            return ""
        values = query.get("table") or []
        return values[0] if values else ""
