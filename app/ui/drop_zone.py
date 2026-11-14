"""支持点击选择与拖拽导入的 TXT 文件区域。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ..constants import FILE_DIALOG_FILTER, FILE_SIZE_HINT
from ..utils import fmt_size, repolish
from .elided_label import ElidedLabel


class DropZone(QFrame):
    fileSelected = pyqtSignal(str)
    fileCleared = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(108)
        self._file_path: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(0)

        self._pages = QStackedLayout()
        self._pages.setContentsMargins(0, 0, 0, 0)
        self._pages.addWidget(self._build_empty_page())
        self._pages.addWidget(self._build_file_page())
        root.addLayout(self._pages)

    # ---- 页面 ------------------------------------------------------------

    def _build_empty_page(self) -> QWidget:
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(14)

        icon = QLabel("↑")
        icon.setObjectName("DropIcon")
        icon.setFixedSize(42, 42)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        title = QLabel("点击选择或拖拽 TXT 文件到此处")
        title.setObjectName("DropTitle")
        hint = QLabel(FILE_SIZE_HINT)
        hint.setObjectName("FileMeta")
        text_col.addWidget(title)
        text_col.addWidget(hint)
        text_col.addStretch(1)

        browse = QPushButton("浏览文件")
        browse.setObjectName("GhostStrong")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self._browse)

        row.addWidget(icon)
        row.addLayout(text_col, 1)
        row.addWidget(browse)
        return page

    def _build_file_page(self) -> QWidget:
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(14)

        badge = QLabel("TXT")
        badge.setObjectName("FileBadge")
        badge.setFixedSize(42, 42)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        self.file_name = ElidedLabel()
        self.file_name.setObjectName("FileName")
        self.file_meta = QLabel()
        self.file_meta.setObjectName("FileMeta")
        text_col.addWidget(self.file_name)
        text_col.addWidget(self.file_meta)
        text_col.addStretch(1)

        replace = QPushButton("更换")
        replace.setObjectName("Ghost")
        replace.setCursor(Qt.CursorShape.PointingHandCursor)
        replace.clicked.connect(self._browse)

        remove = QPushButton("移除")
        remove.setObjectName("Ghost")
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.clicked.connect(self.clear_file)

        row.addWidget(badge)
        row.addLayout(text_col, 1)
        row.addWidget(replace)
        row.addWidget(remove)
        return page

    # ---- 交互 ------------------------------------------------------------

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择询价清单", "", FILE_DIALOG_FILTER
        )
        if path:
            self.fileSelected.emit(path)

    def set_file(self, path: str) -> None:
        self._file_path = path
        file_path = Path(path)
        try:
            size = file_path.stat().st_size
        except OSError:
            size = 0
        self.file_name.set_full_text(file_path.name)
        self.file_meta.setText(f"{fmt_size(size)} · 已就绪")
        self.setToolTip(path)
        self._pages.setCurrentIndex(1)

    def clear_file(self) -> None:
        had_file = self._file_path is not None
        self._file_path = None
        self.setToolTip("")
        self._pages.setCurrentIndex(0)
        if had_file:
            self.fileCleared.emit()

    def current_file(self) -> str | None:
        return self._file_path

    def flash(self) -> None:
        self._set_drag_active(True)
        QTimer.singleShot(420, lambda: self._set_drag_active(False))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._pages.currentIndex() == 0:
            self._browse()
        super().mousePressEvent(event)

    # ---- 拖放 ------------------------------------------------------------

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        repolish(self)

    @staticmethod
    def _first_txt(event) -> str | None:
        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            local = url.toLocalFile()
            if local.lower().endswith(".txt"):
                return local
        return None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._first_txt(event):
            event.acceptProposedAction()
            self._set_drag_active(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._set_drag_active(False)
        path = self._first_txt(event)
        if path:
            event.acceptProposedAction()
            self.fileSelected.emit(path)
        else:
            event.ignore()
