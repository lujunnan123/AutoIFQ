"""账号清单上传卡片，以及手动询价入口。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ..constants import MAX_FILE_SIZE
from .card import Card
from .drop_zone import DropZone


class UploadPanel(Card):
    fileLoaded = pyqtSignal(str, int)
    fileRejected = pyqtSignal(str, str)
    fileCleared = pyqtSignal()
    manualInquiryRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "上传账号清单", "TXT 格式：手机号----密码（仅手机号使用默认密码）", parent
        )
        self._file_path: str | None = None

        row = QHBoxLayout()
        row.setSpacing(12)

        self.drop_zone = DropZone(
            title="点击选择或拖拽 TXT 文件到此处",
            hint="仅支持 .txt 单个文件 · 不超过 20 MB",
            browse_text="浏览文件",
            file_filter="文本文件 (*.txt);;所有文件 (*)",
            extensions=(".txt",),
            badge_text="TXT",
            dialog_title="选择账号清单",
        )
        self.drop_zone.fileSelected.connect(self._on_file_selected)
        self.drop_zone.fileCleared.connect(self._on_file_cleared)

        self.manual_inquiry_btn = QPushButton("手动询价")
        self.manual_inquiry_btn.setObjectName("ManualInquiryButton")
        self.manual_inquiry_btn.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.manual_inquiry_btn.setFixedSize(140, 108)
        self.manual_inquiry_btn.setToolTip("打开手动询价界面")
        self.manual_inquiry_btn.clicked.connect(
            lambda: self.manualInquiryRequested.emit()
        )

        row.addWidget(self.drop_zone, 1)
        row.addWidget(self.manual_inquiry_btn, 0)
        self.body.addLayout(row)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def current_file(self) -> str | None:
        return self._file_path

    def flash(self) -> None:
        self.drop_zone.flash()

    # ------------------------------------------------------------------
    # 文件校验
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
