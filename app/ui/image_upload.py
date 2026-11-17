"""多图上传控件：文件选择、拖拽、粘贴与缩略图列表。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
_IMAGE_FILTER = (
    "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*)"
)
_MAX_IMAGES = 20


class ImageUploader(QWidget):
    imagesChanged = pyqtSignal()
    message = pyqtSignal(str, str)

    def __init__(
        self,
        paste_dir: str | Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._paste_dir = Path(paste_dir)
        self._paste_dir.mkdir(parents=True, exist_ok=True)
        self._paths: list[str] = []
        self._paste_counter = 0
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        title = QLabel("账号截图")
        title.setObjectName("FieldLabel")
        self.count_label = QLabel("0 张")
        self.count_label.setObjectName("HintLabel")

        self.add_btn = QPushButton("添加图片")
        self.add_btn.setObjectName("GhostStrong")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.clicked.connect(self.open_files)

        self.paste_btn = QPushButton("粘贴图片")
        self.paste_btn.setObjectName("Ghost")
        self.paste_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.paste_btn.clicked.connect(self.paste_from_clipboard)

        self.remove_btn = QPushButton("移除选中")
        self.remove_btn.setObjectName("Ghost")
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.setEnabled(False)
        self.remove_btn.clicked.connect(self.remove_selected)

        self.clear_btn = QPushButton("清空")
        self.clear_btn.setObjectName("Ghost")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setEnabled(False)
        self.clear_btn.clicked.connect(self.clear)

        toolbar.addWidget(title)
        toolbar.addWidget(self.count_label)
        toolbar.addStretch(1)
        toolbar.addWidget(self.add_btn)
        toolbar.addWidget(self.paste_btn)
        toolbar.addWidget(self.remove_btn)
        toolbar.addWidget(self.clear_btn)
        layout.addLayout(toolbar)

        self.drop_area = _ImageDropArea(self)
        self.drop_area.openRequested.connect(self.open_files)
        self.drop_area.filesDropped.connect(self.add_paths)
        layout.addWidget(self.drop_area)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("ManualImageList")
        self.list_widget.setViewMode(QListView.ViewMode.IconMode)
        self.list_widget.setIconSize(QSize(96, 64))
        self.list_widget.setGridSize(QSize(126, 96))
        self.list_widget.setMovement(QListView.Movement.Static)
        self.list_widget.setResizeMode(QListView.ResizeMode.Adjust)
        self.list_widget.setSelectionMode(
            QListView.SelectionMode.ExtendedSelection
        )
        self.list_widget.setSpacing(4)
        self.list_widget.setWordWrap(True)
        self.list_widget.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.list_widget.setFixedHeight(138)
        self.list_widget.itemSelectionChanged.connect(
            self._update_buttons
        )
        self.list_widget.setToolTip(
            "支持多张图片，Ctrl+V 可从剪贴板粘贴"
        )
        layout.addWidget(self.list_widget)

    # ------------------------------------------------------------------
    # 添加 / 粘贴
    # ------------------------------------------------------------------

    def open_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择账号截图", "", _IMAGE_FILTER
        )
        if paths:
            self.add_paths(paths)

    def add_paths(self, paths: list[str] | tuple[str, ...]) -> int:
        added = 0
        for raw_path in paths:
            if len(self._paths) >= _MAX_IMAGES:
                self.message.emit(
                    f"最多支持 {_MAX_IMAGES} 张图片，其余图片已忽略。",
                    "warn",
                )
                break
            path = Path(raw_path)
            if not path.is_file():
                self.message.emit(f"图片不存在：{path}", "warn")
                continue
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                self.message.emit(
                    f"不支持的图片格式：{path.name}", "warn"
                )
                continue
            resolved = str(path.resolve())
            if resolved in self._paths:
                continue
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                self.message.emit(
                    f"无法加载图片：{path.name}", "warn"
                )
                continue
            icon_pixmap = pixmap.scaled(
                96,
                64,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            item = QListWidgetItem(QIcon(icon_pixmap), path.name)
            item.setData(Qt.ItemDataRole.UserRole, resolved)
            item.setToolTip(str(path))
            self.list_widget.addItem(item)
            self._paths.append(resolved)
            added += 1

        if added:
            self.message.emit(
                f"已添加 {added} 张图片，共 {len(self._paths)} 张。",
                "info",
            )
        self._update_buttons()
        if added:
            self.imagesChanged.emit()
        return added

    def paste_from_clipboard(self) -> None:
        mime = QApplication.clipboard().mimeData()
        if mime is None:
            self.message.emit("剪贴板中没有图片。", "warn")
            return

        paths: list[str] = []
        if mime.hasUrls():
            for url in mime.urls():
                local = url.toLocalFile()
                if not local:
                    continue
                if Path(local).suffix.lower() in IMAGE_EXTENSIONS:
                    paths.append(local)
        if paths:
            self.add_paths(paths)
            return

        if mime.hasImage():
            image = QApplication.clipboard().image()
            if image is not None and not image.isNull():
                self._paste_counter += 1
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = (
                    self._paste_dir
                    / f"粘贴截图_{stamp}_{self._paste_counter}.png"
                )
                if image.save(str(path), "PNG"):
                    self.add_paths([str(path)])
                    return
                self.message.emit("粘贴图片保存失败。", "error")
                return

        self.message.emit("剪贴板中没有可用的图片。", "warn")

    # ------------------------------------------------------------------
    # 移除
    # ------------------------------------------------------------------

    def remove_selected(self) -> None:
        selected = self.list_widget.selectedItems()
        if not selected:
            return
        for item in selected:
            index = self.list_widget.row(item)
            self.list_widget.takeItem(index)
        self._sync_paths()
        self._update_buttons()
        self.imagesChanged.emit()

    def clear(self) -> None:
        if not self._paths:
            return
        self.list_widget.clear()
        self._paths.clear()
        self._update_buttons()
        self.imagesChanged.emit()

    def _sync_paths(self) -> None:
        self._paths = [
            str(
                self.list_widget.item(index).data(
                    Qt.ItemDataRole.UserRole
                )
            )
            for index in range(self.list_widget.count())
        ]

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def image_paths(self) -> tuple[str, ...]:
        return tuple(self._paths)

    def count(self) -> int:
        return len(self._paths)

    def _update_buttons(self) -> None:
        count = len(self._paths)
        self.count_label.setText(f"{count} 张")
        self.remove_btn.setEnabled(
            bool(self.list_widget.selectedItems())
        )
        self.clear_btn.setEnabled(count > 0)
        self.add_btn.setEnabled(count < _MAX_IMAGES)
        self.paste_btn.setEnabled(count < _MAX_IMAGES)


class _ImageDropArea(QFrame):
    openRequested = pyqtSignal()
    filesDropped = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ImageDropArea")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(72)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title = QLabel("点击选择 / 拖拽 / Ctrl+V 粘贴图片")
        title.setObjectName("DropTitle")
        hint = QLabel(
            "支持多张 PNG / JPG / JPEG / WEBP / BMP，最多 20 张"
        )
        hint.setObjectName("FileMeta")
        text_col.addWidget(title)
        text_col.addWidget(hint)
        text_col.addStretch(1)

        add_hint = QLabel("添加图片")
        add_hint.setObjectName("GhostStrongText")

        layout.addLayout(text_col, 1)
        layout.addWidget(add_hint)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.openRequested.emit()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._image_paths(event):
            event.acceptProposedAction()
            self.setProperty("dragActive", True)
            self.style().unpolish(self)
            self.style().polish(self)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._set_drag_active(False)
        paths = self._image_paths(event)
        if paths:
            event.acceptProposedAction()
            self.filesDropped.emit(paths)
        else:
            event.ignore()

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)

    @staticmethod
    def _image_paths(event) -> list[str]:
        mime = event.mimeData()
        if not mime.hasUrls():
            return []
        paths: list[str] = []
        for url in mime.urls():
            local = url.toLocalFile()
            if (
                local
                and Path(local).suffix.lower() in IMAGE_EXTENSIONS
            ):
                paths.append(local)
        return paths
