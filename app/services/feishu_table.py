"""读取飞书多维表格：解析页面接口返回的字段与记录（不依赖剪贴板）。"""

from __future__ import annotations

import base64
import gzip
import json
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import (
    parse_qs,
    urlencode,
    urlparse,
    urlsplit,
    urlunsplit,
)

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
_RECORDS_API_WAIT = 20.0
_RECORDS_PAGE_SIZE = 3000
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
_SCREENSHOT_FIELD_ALIASES = ("账号内容图片",)
_MAX_SCREENSHOTS_PER_RECORD = 10


@dataclass(frozen=True)
class FeishuAttachment:
    token: str
    name: str = ""
    mime: str = ""


@dataclass(frozen=True)
class FeishuRecord:
    record_id: str
    values: tuple[object, ...]
    account: str
    screenshots: tuple[Path, ...] = ()
    has_images: bool = False
    image_items: tuple[FeishuAttachment, ...] = ()
    listing_status: str = ""


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
    records: tuple[FeishuRecord, ...] = ()
    temp_dir: Path | None = None


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

    def fetch_records(
        self,
        limit: int = 0,
        *,
        download_images: bool = True,
        fetch_all: bool = False,
    ) -> FeishuTableData:
        """读取当前视图记录；download_images=False 时只读取图片元信息。"""
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
            return self._fetch(
                headless=headless,
                limit=limit,
                download_images=download_images,
                fetch_all=fetch_all,
            )
        except FeishuLoginRequired:
            raise
        except FeishuTableError as exc:
            if not headless:
                raise
            self._log(
                f"无头模式读取飞书表格失败：{exc}；改用可见浏览器重试…",
                "warn",
            )
            return self._fetch(
                headless=False,
                limit=limit,
                download_images=download_images,
                fetch_all=fetch_all,
            )

    # ------------------------------------------------------------------
    # 浏览器读取
    # ------------------------------------------------------------------

    def _fetch(
        self,
        *,
        headless: bool,
        limit: int,
        download_images: bool = True,
        fetch_all: bool = False,
    ) -> FeishuTableData:
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

                def on_records_response(response) -> None:
                    if captured.get("records_request") is not None:
                        return
                    url = response.url
                    if "/bitable/" not in url or "/records" not in url:
                        return
                    if self._table_id and self._table_id not in url:
                        return
                    try:
                        captured["records_request"] = {
                            "url": url,
                            "headers": response.request.all_headers(),
                        }
                    except Exception:
                        pass

                page.on("response", on_response)
                page.on("response", on_records_response)
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

                if fetch_all:
                    initial_total = table.get("recordCount")
                    initial_loaded = len(
                        table.get("recordMap") or {}
                    )
                    if (
                        isinstance(initial_total, int)
                        and initial_total > initial_loaded
                    ):
                        self._log(
                            f"飞书初次加载 {initial_loaded}/"
                            f"{initial_total} 条，正在补全剩余记录…",
                            "info",
                        )
                        records_deadline = (
                            time.monotonic() + _RECORDS_API_WAIT
                        )
                        while (
                            time.monotonic() < records_deadline
                            and captured.get("records_request") is None
                        ):
                            page.wait_for_timeout(300)
                        request_info = captured.get("records_request")
                        if isinstance(request_info, dict):
                            try:
                                table = self._fetch_all_records(
                                    context, table, request_info
                                )
                                self._log(
                                    "飞书记录补全成功："
                                    f"{len(table.get('recordMap') or {})}/"
                                    f"{table.get('recordCount')} 条。",
                                    "success",
                                )
                            except Exception as exc:
                                self._log(
                                    f"飞书记录补全失败：{exc}；"
                                    f"将使用初次加载的 "
                                    f"{initial_loaded}/{initial_total} 条。",
                                    "warn",
                                )
                        else:
                            self._log(
                                "未捕获到飞书记录分页接口，"
                                "将使用初次加载的部分记录。",
                                "warn",
                            )

                timezone_name = captured.get("timezone")
                rows, total, selected_ids = self._extract_rows(
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

                if download_images:
                    records, temp_dir = self._download_records(
                        context, table, selected_ids, rows
                    )
                else:
                    records, temp_dir = self._prepare_records(
                        table, selected_ids, rows
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
                    records=tuple(records),
                    temp_dir=temp_dir,
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

    def _fetch_all_records(
        self,
        context,
        table: dict,
        request_info: dict,
    ) -> dict:
        base_url = str(request_info.get("url") or "")
        raw_headers = request_info.get("headers") or {}
        headers = {
            str(key): str(value)
            for key, value in raw_headers.items()
            if str(key).lower()
            not in (
                "cookie",
                ":authority",
                ":method",
                ":path",
                ":scheme",
                "accept-encoding",
                "content-length",
            )
        }
        if not base_url:
            raise FeishuTableError("记录分页接口地址为空。")

        all_records: dict[str, object] = {}
        ordered_ids: list[str] = []
        resource_map: dict[str, object] = {}
        total = table.get("recordCount")
        offset = 0
        page_size = _RECORDS_PAGE_SIZE

        for _page in range(50):
            url = self._records_api_url(base_url, offset, page_size)
            try:
                response = context.request.get(
                    url, headers=headers, timeout=60000
                )
            except Exception as exc:
                raise FeishuTableError(
                    f"请求飞书记录分页接口失败：{exc}"
                ) from exc
            if response.status != 200:
                raise FeishuTableError(
                    f"飞书记录分页接口返回 HTTP {response.status}"
                )
            try:
                data = response.json()
            except Exception as exc:
                raise FeishuTableError(
                    f"飞书记录分页接口返回格式异常：{exc}"
                ) from exc
            if (
                isinstance(data, dict)
                and data.get("code") not in (0, None)
            ):
                raise FeishuTableError(
                    "飞书记录分页接口错误："
                    f"{data.get('msg') or data.get('code')}"
                )
            payload = (
                data.get("data") if isinstance(data, dict) else None
            )
            if not isinstance(payload, dict):
                raise FeishuTableError(
                    "飞书记录分页接口缺少 data。"
                )
            raw_records = payload.get("records")
            page_data = self._decode_records_payload(raw_records)
            if not isinstance(page_data, dict):
                raise FeishuTableError(
                    "无法解析飞书记录分页接口数据。"
                )

            page_records = page_data.get("recordMap") or {}
            if not isinstance(page_records, dict) or not page_records:
                break
            new_count = 0
            for record_id, record in page_records.items():
                if record_id not in all_records:
                    all_records[record_id] = record
                    new_count += 1

            for group in page_data.get("groupList") or []:
                if not isinstance(group, dict):
                    continue
                for record_id in group.get("recordIDList") or []:
                    if (
                        isinstance(record_id, str)
                        and record_id not in ordered_ids
                        and record_id in all_records
                    ):
                        ordered_ids.append(record_id)

            self._merge_resource_map(
                resource_map, page_data.get("resourceMap")
            )
            page_total = page_data.get("tableRecordNum")
            if isinstance(page_total, int) and page_total > 0:
                total = page_total

            if not new_count:
                break
            if isinstance(total, int) and len(all_records) >= total:
                break
            if len(page_records) < page_size:
                break
            offset += len(page_records)

        if not all_records:
            raise FeishuTableError("记录分页接口没有返回记录。")

        for record_id in all_records:
            if record_id not in ordered_ids:
                ordered_ids.append(record_id)

        merged = dict(table)
        merged["recordMap"] = all_records
        merged["groupList"] = [{"recordIDList": ordered_ids}]
        if resource_map:
            merged["resourceMap"] = resource_map
        merged["recordCount"] = (
            total if isinstance(total, int) else len(all_records)
        )
        return merged

    @staticmethod
    def _records_api_url(
        base_url: str, offset: int, limit: int
    ) -> str:
        parts = urlsplit(base_url)
        query = parse_qs(parts.query, keep_blank_values=True)
        query["offset"] = [str(offset)]
        query["limit"] = [str(limit)]
        return urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urlencode(query, doseq=True),
                parts.fragment,
            )
        )

    @staticmethod
    def _decode_records_payload(raw: object) -> dict | None:
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str) or not raw.strip():
            return None
        try:
            content = base64.b64decode(raw)
            try:
                content = gzip.decompress(content)
            except OSError:
                pass
            data = json.loads(content.decode("utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            try:
                data = json.loads(raw)
                return data if isinstance(data, dict) else None
            except Exception:
                return None

    @classmethod
    def _merge_resource_map(
        cls,
        target: dict,
        source: object,
    ) -> None:
        if not isinstance(source, dict):
            return
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(
                target.get(key), dict
            ):
                cls._merge_resource_map(target[key], value)
            else:
                target[key] = value

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
    ) -> tuple[list[tuple[object, ...]], int, list[str]]:
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
        return rows, total, selected

    def _prepare_records(
        self,
        table: dict,
        selected_ids: list[str],
        rows: list[tuple[object, ...]],
    ) -> tuple[list[FeishuRecord], None]:
        field_map = table.get("fieldMap") or {}
        field_ids = self._screenshot_field_ids(field_map)
        resource_map = (
            (table.get("resourceMap") or {}).get("attachments") or {}
        ).get("data") or {}
        record_map = table.get("recordMap") or {}
        status_field = self._find_field(table, "上架情况")
        if status_field is None:
            self._log(
                "飞书表格未找到「上架情况」字段，"
                "筛选页面该列将为空。",
                "warn",
            )

        records: list[FeishuRecord] = []
        for index, record_id in enumerate(selected_ids):
            values = tuple(rows[index]) if index < len(rows) else ()
            account = str(values[0]) if values else ""
            listing_status = ""
            if status_field is not None:
                status_id, status_meta = status_field
                entry = (record_map.get(record_id) or {}).get(
                    status_id
                )
                listing_status = str(
                    self._field_value(entry, status_meta) or ""
                ).strip()
            attachments: list[FeishuAttachment] = []

            for alias in _SCREENSHOT_FIELD_ALIASES:
                field_id = field_ids.get(_normalize(alias))
                if not field_id:
                    continue
                record_entry = (record_map.get(record_id) or {}).get(
                    field_id
                )
                record_items = None
                if isinstance(record_entry, dict):
                    record_items = record_entry.get("value")
                resource_items = (
                    (resource_map.get(field_id) or {}).get(record_id)
                )
                items = self._attachment_items(
                    record_items, resource_items
                )
                if not items:
                    continue
                for item in items[:_MAX_SCREENSHOTS_PER_RECORD]:
                    attachment = self._attachment_from_item(item)
                    if attachment is not None:
                        attachments.append(attachment)
                if attachments:
                    break

            records.append(
                FeishuRecord(
                    record_id=record_id,
                    values=values,
                    account=account,
                    has_images=bool(attachments),
                    image_items=tuple(attachments),
                    listing_status=listing_status,
                )
            )

        with_images = sum(1 for record in records if record.has_images)
        self._log(
            f"记录准备完成：{len(records)} 条，其中 {with_images} 条"
            "有账号内容图片，将在筛选确认后下载。",
            "info",
        )
        return records, None

    def _download_records(
        self,
        context,
        table: dict,
        selected_ids: list[str],
        rows: list[tuple[object, ...]],
    ) -> tuple[list[FeishuRecord], Path]:
        records, _ = self._prepare_records(table, selected_ids, rows)
        temp_dir = Path(tempfile.mkdtemp(prefix="autoifq_feishu_"))
        return (
            self._download_prepared_records(context, records, temp_dir),
            temp_dir,
        )

    def _download_prepared_records(
        self,
        context,
        records: list[FeishuRecord],
        temp_dir: Path,
        cancel: threading.Event | None = None,
    ) -> list[FeishuRecord]:
        downloaded_records: list[FeishuRecord] = []
        downloaded = 0
        for index, record in enumerate(records):
            if cancel is not None and cancel.is_set():
                raise FeishuTableError("已取消下载账号内容图片。")
            if record.screenshots:
                downloaded_records.append(record)
                continue

            shots: list[Path] = []
            for shot_index, attachment in enumerate(record.image_items):
                if cancel is not None and cancel.is_set():
                    raise FeishuTableError(
                        "已取消下载账号内容图片。"
                    )
                path = self._download_attachment(
                    context, attachment, temp_dir, index, shot_index
                )
                if path is not None:
                    shots.append(path)

            if shots:
                downloaded += len(shots)
                self._log(
                    f"账号 {self._mask(record.account)} 已下载 "
                    f"{len(shots)} 张账号内容图片。",
                    "muted",
                )
            elif record.has_images:
                self._log(
                    f"账号 {self._mask(record.account)} 的账号内容图片"
                    "下载失败，该行询价将被跳过。",
                    "warn",
                )
            downloaded_records.append(
                replace(record, screenshots=tuple(shots))
            )

        if downloaded:
            self._log(
                f"账号内容图片准备完成：共下载 {downloaded} 张。",
                "info",
            )
        return downloaded_records

    def download_images(
        self,
        data: FeishuTableData,
        cancel: threading.Event | None = None,
    ) -> FeishuTableData:
        """为筛选后的记录下载账号内容图片，返回带本地路径的新数据。"""
        targets = [
            record
            for record in data.records
            if record.image_items and not record.screenshots
        ]
        if not targets:
            return data
        if sync_playwright is None:
            raise FeishuTableError(
                "未安装 Playwright，无法下载账号内容图片。"
            )
        if not feishu_logged_in(self._config):
            raise FeishuLoginRequired(
                "飞书登录状态已失效，无法下载账号内容图片；"
                "请重新登录飞书后再试。"
            )

        self._log(
            f"开始下载选中记录的账号内容图片：{len(targets)} 条记录。",
            "info",
        )
        temp_dir = Path(tempfile.mkdtemp(prefix="autoifq_feishu_"))
        browser = None
        try:
            with sync_playwright() as playwright:
                browser = self._launch(playwright, headless=True)
                context = browser.new_context(
                    storage_state=str(self._state_path),
                    locale="zh-CN",
                    viewport={"width": 1600, "height": 1000},
                )
                try:
                    records = self._download_prepared_records(
                        context,
                        list(data.records),
                        temp_dir,
                        cancel,
                    )
                finally:
                    try:
                        context.close()
                    except Exception:
                        pass
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        finally:
            if browser is not None:
                try:
                    if browser.is_connected():
                        browser.close()
                except Exception:
                    pass

        return FeishuTableData(
            rows=list(data.rows),
            total_records=data.total_records,
            source_name=data.source_name,
            page_url=data.page_url,
            headers=data.headers,
            records=tuple(records),
            temp_dir=temp_dir,
        )

    @staticmethod
    def _find_field(
        table: dict,
        name: str,
    ) -> tuple[str, dict] | None:
        normalized = _normalize(name)
        field_map = table.get("fieldMap") or {}
        for field_id, meta in field_map.items():
            if not isinstance(meta, dict):
                continue
            if _normalize(meta.get("name")) == normalized:
                return field_id, meta
        return None

    @staticmethod
    def _screenshot_field_ids(field_map: dict) -> dict[str, str]:
        field_ids: dict[str, str] = {}
        for alias in _SCREENSHOT_FIELD_ALIASES:
            normalized = _normalize(alias)
            for field_id, meta in field_map.items():
                if not isinstance(meta, dict):
                    continue
                if _normalize(meta.get("name")) == normalized:
                    field_ids[normalized] = field_id
                    break
        return field_ids

    @staticmethod
    def _attachment_from_item(item: dict) -> FeishuAttachment | None:
        token = str(
            item.get("attachmentToken") or item.get("id") or ""
        ).strip()
        if not token:
            return None
        return FeishuAttachment(
            token=token,
            name=str(item.get("name") or ""),
            mime=str(item.get("mimeType") or ""),
        )

    @staticmethod
    def _attachment_items(
        record_items: object,
        resource_items: object,
    ) -> list[dict]:
        if isinstance(record_items, list) and record_items:
            return [
                item for item in record_items if isinstance(item, dict)
            ]
        if isinstance(resource_items, list) and resource_items:
            return [
                item for item in resource_items if isinstance(item, dict)
            ]
        return []

    def _download_attachment(
        self,
        context,
        item: FeishuAttachment,
        temp_dir: Path,
        record_index: int,
        shot_index: int,
    ) -> Path | None:
        token = item.token.strip()
        if not token:
            return None

        parsed = urlparse(self._config.table_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        url = (
            f"{base_url}/space/api/box/stream/download/all/{token}"
        )
        try:
            response = context.request.get(
                url,
                headers={"Referer": self._config.table_url},
                timeout=60000,
            )
            if response.status != 200:
                self._log(
                    f"账号内容图片下载失败：HTTP {response.status}",
                    "warn",
                )
                return None
            content = response.body()
            if not content:
                return None
            content_type = str(
                response.headers.get("content-type") or ""
            ).lower()
            if "text/html" in content_type:
                self._log(
                    "账号内容图片下载失败：返回了登录页，"
                    "飞书登录状态可能已失效。",
                    "warn",
                )
                return None
            mime = str(item.mime or content_type).lower()
            if "png" in mime:
                suffix = ".png"
            elif "jpeg" in mime or "jpg" in mime:
                suffix = ".jpg"
            else:
                suffix = Path(item.name).suffix or ".img"
            path = (
                temp_dir
                / f"record_{record_index}"
                / f"shot_{shot_index + 1}{suffix}"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return path
        except Exception as exc:
            self._log(f"账号内容图片下载异常：{exc}", "warn")
            return None

    @staticmethod
    def _mask(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return "未知账号"
        if len(text) <= 4:
            return "*" * len(text)
        if len(text) <= 8:
            return text[:2] + "*" * (len(text) - 4) + text[-2:]
        return text[:3] + "*" * (len(text) - 6) + text[-3:]

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
        ui_type = str(meta.get("fieldUIType") or "").lower()
        if field_type in (3, 4) or "select" in ui_type:
            return cls._select_value(raw, meta)
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
    def _select_value(raw: object, meta: dict) -> str:
        options: dict[str, str] = {}
        prop = meta.get("property")
        if isinstance(prop, dict):
            for option in prop.get("options") or []:
                if not isinstance(option, dict):
                    continue
                option_id = str(option.get("id") or "").strip()
                name = str(option.get("name") or "").strip()
                if option_id and name:
                    options[option_id] = name

        def one(item: object) -> str:
            if isinstance(item, list):
                return ", ".join(
                    value
                    for value in (one(child) for child in item)
                    if value
                )
            if isinstance(item, dict):
                option_id = str(item.get("id") or "").strip()
                if option_id in options:
                    return options[option_id]
                if "value" in item:
                    return one(item.get("value"))
                for key in ("name", "text"):
                    value = item.get(key)
                    if value is not None:
                        text = str(value).strip()
                        if text:
                            return options.get(text, text)
                return ""
            text = str(item or "").strip()
            if not text:
                return ""
            return options.get(text, text)

        return one(raw)

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
