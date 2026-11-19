"""手动询价日志表格生成。"""

from __future__ import annotations

import functools
import os
import threading
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..settings import PROJECT_ROOT

# 多个手动询价窗口可能同时写入日志；串行化文件创建与保存，
# 既避免同名日志冲突，也避免 openpyxl 同时写同一个文件。
_LOG_LOCK = threading.Lock()

_HEADERS = (
    "时间",
    "商户",
    "手机号",
    "截图文件",
    "询问话术",
    "商家回复",
    "识别报价",
    "状态",
    "耗时(秒)",
    "错误",
)
_WIDTHS = {
    "时间": 20,
    "商户": 22,
    "手机号": 16,
    "截图文件": 24,
    "询问话术": 30,
    "商家回复": 60,
    "识别报价": 14,
    "状态": 12,
    "耗时(秒)": 10,
    "错误": 40,
}
_SHEET = "手动询价日志"


class ManualLogError(Exception):
    """手动询价日志保存失败。"""


def _synchronized(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _LOG_LOCK:
            return func(*args, **kwargs)

    return wrapper


@_synchronized
def append_manual_inquiry_log(
    path: str | Path | None,
    *,
    merchant: str,
    phone: str = "",
    image_paths: Iterable[str | Path],
    phrase: str,
    replies: tuple[str, ...],
    price: object | None,
    status: str,
    elapsed: float,
    error: str = "",
    output_dir: str | Path | None = None,
) -> Path:
    """创建或追加手动询价日志；返回日志文件路径。"""
    log_path = Path(path) if path else _new_log_path(output_dir)
    exists = log_path.exists()
    if exists:
        try:
            workbook = load_workbook(log_path)
        except Exception as exc:
            raise ManualLogError(f"无法打开日志表格：{exc}") from exc
        worksheet = workbook.active
    else:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = _SHEET
        _write_headers(worksheet)

    image_names = "; ".join(
        Path(image_path).name for image_path in image_paths
    )
    replies_text = "\n".join(
        reply for reply in replies if reply
    )
    price_value = price if price not in (None, "") else ""
    row = [
        datetime.now(),
        merchant,
        phone,
        image_names,
        phrase,
        replies_text,
        price_value,
        status,
        round(max(0.0, float(elapsed)), 1),
        error,
    ]
    worksheet.append(row)

    row_index = worksheet.max_row
    for column_index, header in enumerate(_HEADERS, start=1):
        cell = worksheet.cell(row_index, column_index)
        cell.border = _border()
        cell.alignment = Alignment(
            vertical="top",
            wrap_text=header in (
                "询问话术",
                "商家回复",
                "错误",
                "截图文件",
            ),
        )
        if header == "时间":
            cell.number_format = "yyyy-mm-dd hh:mm:ss"
        elif header == "识别报价" and isinstance(price_value, (int, float)):
            cell.number_format = "#,##0.##"
    worksheet.auto_filter.ref = worksheet.dimensions

    _save_atomic(workbook, log_path)
    return log_path


def _new_log_path(output_dir: str | Path | None) -> Path:
    if output_dir:
        root = Path(output_dir)
        if not root.is_absolute():
            root = PROJECT_ROOT / root
    else:
        root = PROJECT_ROOT / "output"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = root / f"手动询价日志_{stamp}.xlsx"
    counter = 2
    while candidate.exists():
        candidate = (
            root / f"手动询价日志_{stamp}_{counter}.xlsx"
        )
        counter += 1
    return candidate


def _write_headers(worksheet) -> None:
    header_font = Font(
        name="微软雅黑", bold=True, color="FFFFFF", size=11
    )
    header_fill = PatternFill("solid", fgColor="2F5597")
    header_alignment = Alignment(
        horizontal="center", vertical="center"
    )
    border = _border()
    for column_index, header in enumerate(_HEADERS, start=1):
        cell = worksheet.cell(1, column_index, header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = border
        worksheet.column_dimensions[
            get_column_letter(column_index)
        ].width = _WIDTHS[header]
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions


def _border() -> Border:
    thin = Side(style="thin", color="D9E1F2")
    return Border(left=thin, right=thin, top=thin, bottom=thin)


def _save_atomic(workbook, path: Path) -> None:
    temp_path = path.with_name(f"{path.stem}.tmp{path.suffix}")
    try:
        workbook.save(temp_path)
        os.replace(temp_path, path)
    except OSError as exc:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise ManualLogError(f"无法保存日志表格：{exc}") from exc
