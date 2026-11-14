"""询价清单上传卡片。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget

from ..constants import MAX_FILE_SIZE
from .card import Card
from .drop_zone import DropZone


class UploadPanel(Card):
    """负责文件选择、拖放与基础校验，验证通过后发出 fileLoaded。"""

    fileLoaded = pyqtSignal(str, int)  # path, size
    fileRejected = pyqtSignal(str, str)  # message, level
    fileCleared = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("上传账号清单", "格式：手机号----密码（仅手机号使用默认密码）", parent)
        self._file_path: str | None = None

        self.drop_zone = DropZone()
        self.drop_zone.fileSelected.connect(self._on_file_selected)
        self.drop_zone.fileCleared.connect(self._on_file_cleared)
        self.body.addWidget(self.drop_zone)

    def current_file(self) -> str | None:
        return self._file_path

    def flash(self) -> None:
        self.drop_zone.flash()

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
