"""读取源表指定列（飞书多维表格或本地 Excel），生成新的询价表格。"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..settings import PROJECT_ROOT

REQUIRED_COLUMNS: tuple[str, ...] = (
    "账号",
    "账号内容",
    "收购日期",
    "可不可二次",
    "成本",
    "拉群前报价",
)

_OUTPUT_SHEET = "自动询价"
_ILLEGAL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_HEADER_SCAN_ROWS = 50


class ExcelTableError(Exception):
    """Excel 无法读取、列缺失或没有数据。"""


@dataclass(frozen=True)
class ExcelCopyResult:
    output_path: Path
    source_sheet: str
    output_sheet: str
    total_records: int
    copied_records: int
    columns: tuple[str, ...]


@dataclass
class _SheetData:
    name: str
    rows: list[list[object]]


def _normalize(value: object) -> str:
    if value is None:
        return ""
    text = (
        str(value)
        .replace("\n", "")
        .replace("\r", "")
        .replace("　", "")
        .replace("【", "")
        .replace("】", "")
        .replace("[", "")
        .replace("]", "")
    )
    return "".join(text.split())


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    return isinstance(value, str) and not value.strip()


def _load_sheets(source: Path) -> list[_SheetData]:
    suffix = source.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        try:
            workbook = load_workbook(
                source, data_only=True, read_only=True
            )
        except Exception as exc:
            raise ExcelTableError(f"无法打开 Excel 文件：{exc}") from exc

        sheets: list[_SheetData] = []
        try:
            for worksheet in workbook.worksheets:
                if worksheet.sheet_state != "visible":
                    continue
                rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
                sheets.append(_SheetData(worksheet.title, rows))
        finally:
            workbook.close()
        return sheets

    if suffix == ".xls":
        try:
            import xlrd
        except ImportError as exc:  # pragma: no cover
            raise ExcelTableError(
                "读取 .xls 需要安装 xlrd，或将文件另存为 .xlsx。"
            ) from exc

        try:
            book = xlrd.open_workbook(str(source), on_demand=True)
        except Exception as exc:
            raise ExcelTableError(f"无法打开 Excel 文件：{exc}") from exc

        sheets = []
        try:
            for sheet in book.sheets():
                if sheet.visibility != 0:
                    continue
                rows: list[list[object]] = []
                for row_index in range(sheet.nrows):
                    values: list[object] = []
                    for col_index in range(sheet.ncols):
                        cell = sheet.cell(row_index, col_index)
                        if cell.ctype == xlrd.XL_CELL_DATE:
                            try:
                                value = xlrd.xldate_as_datetime(
                                    cell.value, book.datemode
                                )
                            except Exception:
                                value = cell.value
                        elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                            value = bool(cell.value)
                        elif cell.ctype == xlrd.XL_CELL_ERROR:
                            value = None
                        else:
                            value = cell.value
                        values.append(value)
                    rows.append(values)
                sheets.append(_SheetData(sheet.name, rows))
        finally:
            book.release_resources()
        return sheets

    raise ExcelTableError("仅支持 .xlsx / .xlsm / .xls 格式的表格文件。")


def _find_header(
    sheets: list[_SheetData],
) -> tuple[_SheetData, int, dict[str, int], list[str]]:
    required = {_normalize(name): name for name in REQUIRED_COLUMNS}
    best_row: list[str] = []
    best_matches = -1

    for sheet in sheets:
        for row_index, row in enumerate(sheet.rows[:_HEADER_SCAN_ROWS]):
            mapping: dict[str, int] = {}
            for col_index, value in enumerate(row):
                normalized = _normalize(value)
                if normalized in required:
                    mapping.setdefault(required[normalized], col_index)

            if len(mapping) == len(REQUIRED_COLUMNS):
                headers = [str(value) for value in row if not _is_empty(value)]
                return sheet, row_index, mapping, headers

            if len(mapping) > best_matches:
                best_matches = len(mapping)
                best_row = [str(value) for value in row if not _is_empty(value)]

    best_values = {_normalize(value) for value in best_row}
    missing = [
        name for name in REQUIRED_COLUMNS if _normalize(name) not in best_values
    ]
    example = "、".join(best_row[:20]) or "空"
    missing_text = "、".join(missing) or "无"
    raise ExcelTableError(
        f"源表缺少必要列：{missing_text}。"
        f"需要包含：{'、'.join(REQUIRED_COLUMNS)}。"
        f"当前最接近的表头：{example}"
    )


def _safe_value(value: object) -> object:
    if isinstance(value, str):
        return _ILLEGAL_CHARACTERS.sub("", value)
    return value


def _unique_output_path(output_root: Path) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = output_root / f"自动询价表格_{stamp}.xlsx"
    counter = 2
    while candidate.exists():
        candidate = output_root / f"自动询价表格_{stamp}_{counter}.xlsx"
        counter += 1
    return candidate


def copy_source_table(
    source_path: str | Path,
    *,
    limit: int = 5,
    output_dir: str | Path | None = None,
) -> ExcelCopyResult:
    """读取源表指定列，生成新表格；limit=0 表示复制全部记录。"""
    source = Path(source_path)
    if not source.is_file():
        raise ExcelTableError(f"源表格不存在：{source}")

    sheets = _load_sheets(source)
    if not sheets:
        raise ExcelTableError("Excel 中没有可见的工作表。")

    sheet, header_index, mapping, _headers = _find_header(sheets)

    records: list[tuple[object, ...]] = []
    for row in sheet.rows[header_index + 1:]:
        values = tuple(
            row[mapping[name]] if mapping[name] < len(row) else None
            for name in REQUIRED_COLUMNS
        )
        if all(_is_empty(value) for value in values):
            continue
        records.append(values)

    if not records:
        raise ExcelTableError("源表表头下没有数据记录。")

    return _write_output(
        records,
        source_name=sheet.name,
        limit=limit,
        output_dir=output_dir,
    )


def build_result_table(
    records: Sequence[Sequence[object]],
    source_name: str,
    *,
    limit: int = 5,
    output_dir: str | Path | None = None,
) -> ExcelCopyResult:
    """根据飞书等数据源的行记录，生成新的询价表格。"""
    cleaned: list[tuple[object, ...]] = []
    for record in records:
        values = list(record[: len(REQUIRED_COLUMNS)])
        if len(values) < len(REQUIRED_COLUMNS):
            values.extend([None] * (len(REQUIRED_COLUMNS) - len(values)))
        row = tuple(values)
        if all(_is_empty(value) for value in row):
            continue
        cleaned.append(row)

    if not cleaned:
        raise ExcelTableError("数据源中没有可写入的记录。")

    return _write_output(
        cleaned,
        source_name=source_name,
        limit=limit,
        output_dir=output_dir,
    )


def _write_output(
    records: Sequence[Sequence[object]],
    *,
    source_name: str,
    limit: int,
    output_dir: str | Path | None,
) -> ExcelCopyResult:
    copy_count = len(records) if limit <= 0 else min(limit, len(records))

    if output_dir:
        output_root = Path(output_dir)
        if not output_root.is_absolute():
            output_root = PROJECT_ROOT / output_root
    else:
        output_root = PROJECT_ROOT / "output"
    try:
        output_path = _unique_output_path(output_root)
    except OSError as exc:
        raise ExcelTableError(f"无法创建输出目录：{exc}") from exc

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = _OUTPUT_SHEET

    header_font = Font(name="微软雅黑", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill("solid", fgColor="2F5597")
    header_alignment = Alignment(horizontal="center", vertical="center")
    thin = Side(style="thin", color="D9E1F2")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for column_index, name in enumerate(REQUIRED_COLUMNS, start=1):
        cell = worksheet.cell(1, column_index, name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = border

    for row_index, record in enumerate(records[:copy_count], start=2):
        for column_index, (name, value) in enumerate(
            zip(REQUIRED_COLUMNS, record), start=1
        ):
            cell = worksheet.cell(row_index, column_index, _safe_value(value))
            cell.border = border
            cell.alignment = Alignment(
                vertical="top", wrap_text=(name == "账号内容")
            )
            if isinstance(value, datetime):
                cell.number_format = "yyyy-mm-dd"
            elif name == "成本" and isinstance(value, (int, float)):
                cell.number_format = "#,##0.00"

    widths = {
        "账号": 20,
        "账号内容": 52,
        "可不可二次": 14,
        "收购日期": 16,
        "成本": 12,
        "拉群前报价": 18,
    }
    for index, name in enumerate(REQUIRED_COLUMNS, start=1):
        worksheet.column_dimensions[get_column_letter(index)].width = widths[name]

    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions

    try:
        workbook.save(output_path)
    except OSError as exc:
        raise ExcelTableError(f"无法保存新表格：{exc}") from exc

    return ExcelCopyResult(
        output_path=output_path,
        source_sheet=source_name,
        output_sheet=worksheet.title,
        total_records=len(records),
        copied_records=copy_count,
        columns=REQUIRED_COLUMNS,
    )
