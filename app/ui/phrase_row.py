"""询问话术列表中的单行输入组件。"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from ..utils import repolish


class PhraseRow(QFrame):
    """一行话术：序号 + 输入框，失焦或点击外部时确认并规范化内容。"""

    activated = pyqtSignal(object)  # PhraseRow
    committed = pyqtSignal(object)  # PhraseRow

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PhraseRow")
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)
        self._committed_text = text.strip()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 10, 4)
        layout.setSpacing(8)

        self.index_label = QLabel("1")
        self.index_label.setObjectName("PhraseIndex")
        self.index_label.setFixedSize(20, 20)
        self.index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.input = QLineEdit(text)
        self.input.setObjectName("PhraseInput")
        self.input.setPlaceholderText("输入一条询问话术…")
        self.input.setClearButtonEnabled(False)
        self._set_placeholder_color()

        self.saved_label = QLabel("✓ 已保存")
        self.saved_label.setObjectName("PhraseSaved")
        self.saved_label.setVisible(False)

        layout.addWidget(self.index_label)
        layout.addWidget(self.input, 1)
        layout.addWidget(self.saved_label)

        self._saved_timer = QTimer(self)
        self._saved_timer.setSingleShot(True)
        self._saved_timer.setInterval(1400)
        self._saved_timer.timeout.connect(lambda: self.saved_label.setVisible(False))

        self.input.editingFinished.connect(self.commit)
        self.input.textEdited.connect(lambda: self.saved_label.setVisible(False))
        self.input.installEventFilter(self)

    def text(self) -> str:
        return self.input.text().strip()

    def set_number(self, number: int) -> None:
        self.index_label.setText(str(number))

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        repolish(self)

    def _set_placeholder_color(self) -> None:
        palette = self.input.palette()
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#55677d"))
        self.input.setPalette(palette)

    def commit(self) -> None:
        """确认输入框内容；仅在内容发生变化时提示「已保存」。"""
        raw = self.input.text()
        normalized = raw.strip()
        if normalized != raw:
            self.input.setText(normalized)

        if normalized != self._committed_text:
            self._committed_text = normalized
            if normalized:
                self.saved_label.setVisible(True)
                self._saved_timer.start()
            else:
                self._saved_timer.stop()
                self.saved_label.setVisible(False)
        # 内容未变化：保持现状。此前变更留下的提示由其定时器自然消失，
        # 这样点击外部触发的提交与随后的失焦提交不会把提示立刻抹掉。

        self.committed.emit(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self)
            self.input.setFocus()
        super().mousePressEvent(event)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.input and event.type() == QEvent.Type.FocusIn:
            self.activated.emit(self)
        return super().eventFilter(obj, event)
