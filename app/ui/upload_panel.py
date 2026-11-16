"""账号清单 + 源表格上传卡片。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from ..constants import MAX_FILE_SIZE
from .card import Card
from .drop_zone import DropZone

EXCEL_EXTENSIONS = (".xlsx", ".xls", ".xlsm")


class UploadPanel(Card):
    """两个并排的上传区：账号 TXT 与源表格 Excel。"""

    fileLoaded = pyqtSignal(str, int)  # account txt path, size
    fileRejected = pyqtSignal(str, str)
    fileCleared = pyqtSignal()

    excelLoaded = pyqtSignal(str, int)
    excelRejected = pyqtSignal(str, str)
    excelCleared = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "上传文件", "账号清单（TXT）+ 源表格（Excel），两项都需导入", parent
        )
        self._file_path: str | None = None
        self._excel_path: str | None = None

        row = QHBoxLayout()
        row.setSpacing(12)

        self.drop_zone = DropZone(
            title="账号清单 TXT",
            hint=".txt · 手机号----密码",
            browse_text="选择",
            file_filter="文本文件 (*.txt);;所有文件 (*)",
            extensions=(".txt",),
            badge_text="TXT",
            dialog_title="选择账号清单",
            compact=True,
        )
        self.drop_zone.fileSelected.connect(self._on_file_selected)
        self.drop_zone.fileCleared.connect(self._on_file_cleared)

        self.excel_drop_zone = DropZone(
            title="源表格 Excel",
            hint=".xlsx / .xls",
            browse_text="选择",
            file_filter="Excel 文件 (*.xlsx *.xls *.xlsm);;所有文件 (*)",
            extensions=EXCEL_EXTENSIONS,
            badge_text="XLSX",
            dialog_title="选择源表格",
            compact=True,
        )
        self.excel_drop_zone.fileSelected.connect(self._on_excel_selected)
        self.excel_drop_zone.fileCleared.connect(self._on_excel_cleared)

        row.addWidget(self.drop_zone, 1)
        row.addWidget(self.excel_drop_zone, 1)
        self.body.addLayout(row)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def current_file(self) -> str | None:
        return self._file_path

    def excel_file(self) -> str | None:
        return self._excel_path

    def flash(self) -> None:
        self.drop_zone.flash()

    def flash_excel(self) -> None:
        self.excel_drop_zone.flash()

    # ------------------------------------------------------------------
    # 账号 TXT
    # ------------------------------------------------------------------

    def _on_file_selected(self, path: str) -> None:
        file_path = Path(path)
        if not file_path.is_file():
            self.fileRejected.emit(f"文件不存在：{path}", "error")
            return
        if file_path.suffix.lower() != ".txt":
            self.fileRejected.emit("仅支持导入 .txt 文本文件。", "warn")
            return

        try:
            size = file_path.stat().st_size
        except OSError as exc:
            self.fileRejected.emit(f"无法读取文件：{exc}", "error")
            return

        if size > MAX_FILE_SIZE:
            self.fileRejected.emit("文件超过 20 MB，请拆分后再导入。", "warn")
            return

        self._file_path = str(file_path)
        self.drop_zone.set_file(self._file_path)
        self.fileLoaded.emit(self._file_path, size)

    def _on_file_cleared(self) -> None:
        self._file_path = None
        self.fileCleared.emit()

    # ------------------------------------------------------------------
    # 源表格 Excel
    # ------------------------------------------------------------------

    def _on_excel_selected(self, path: str) -> None:
        file_path = Path(path)
        if not file_path.is_file():
            self.excelRejected.emit(f"文件不存在：{path}", "error")
            return
        if file_path.suffix.lower() not in EXCEL_EXTENSIONS:
            self.excelRejected.emit(
                "仅支持导入 .xlsx / .xls / .xlsm 表格文件。", "warn"
            )
            return

        try:
            size = file_path.stat().st_size
        except OSError as exc:
            self.excelRejected.emit(f"无法读取文件：{exc}", "error")
            return

        if size > MAX_FILE_SIZE:
            self.excelRejected.emit("表格文件超过 20 MB，请拆分后再导入。", "warn")
            return

        self._excel_path = str(file_path)
        self.excel_drop_zone.set_file(self._excel_path)
        self.excelLoaded.emit(self._excel_path, size)

    def _on_excel_cleared(self) -> None:
        self._excel_path = None
        self.excelCleared.emit()
