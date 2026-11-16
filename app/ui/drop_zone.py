"""支持点击选择与拖拽导入的文件区域（TXT / Excel）。"""

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

from ..utils import fmt_size, repolish
from .elided_label import ElidedLabel


class DropZone(QFrame):
    fileSelected = pyqtSignal(str)
    fileCleared = pyqtSignal()

    def __init__(
        self,
        *,
        title: str = "点击选择或拖拽 TXT 文件到此处",
        hint: str = "仅支持 .txt 单个文件 · 不超过 20 MB",
        browse_text: str = "浏览文件",
        file_filter: str = "文本文件 (*.txt);;所有文件 (*)",
        extensions: tuple[str, ...] = (".txt",),
        badge_text: str = "TXT",
        dialog_title: str = "选择文件",
        compact: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(100 if compact else 108)
        self._file_path: str | None = None
        self._title = title
        self._hint = hint
        self._browse_text = browse_text
        self._file_filter = file_filter
        self._extensions = tuple(ext.lower() for ext in extensions)
        self._badge_text = badge_text
        self._dialog_title = dialog_title
        self._compact = compact

        root = QVBoxLayout(self)
        margin = 10 if compact else 14
        root.setContentsMargins(margin, margin, margin, margin)
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
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(10 if self._compact else 14)
        size = 36 if self._compact else 42

        icon = QLabel("↑")
        icon.setObjectName("DropIcon")
        icon.setFixedSize(size, size)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        title = QLabel(self._title)
        title.setObjectName("DropTitle")
        hint = QLabel(self._hint)
        hint.setObjectName("FileMeta")
        text_col.addWidget(title)
        text_col.addWidget(hint)
        text_col.addStretch(1)

        browse = QPushButton(self._browse_text)
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
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(8 if self._compact else 14)
        size = 36 if self._compact else 42

        badge = QLabel(self._badge_text)
        badge.setObjectName("FileBadge")
        badge.setFixedSize(size, size)
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
            self, self._dialog_title, "", self._file_filter
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

    def _first_file(self, event) -> str | None:
        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            local = url.toLocalFile()
            suffix = Path(local).suffix.lower()
            if not self._extensions or suffix in self._extensions:
                return local
        return None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._first_file(event):
            event.acceptProposedAction()
            self._set_drag_active(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._set_drag_active(False)
        path = self._first_file(event)
        if path:
            event.acceptProposedAction()
            self.fileSelected.emit(path)
        else:
            event.ignore()
