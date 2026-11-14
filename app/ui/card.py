"""带标题栏的卡片容器。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class Card(QFrame):
    """统一样式的卡片：标题 + 可选副标题 + 右侧操作区 + 内容区。"""

    def __init__(
        self,
        title: str,
        subtitle: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")

        self._body = QVBoxLayout(self)
        self._body.setContentsMargins(18, 15, 18, 16)
        self._body.setSpacing(11)

        self._header = QHBoxLayout()
        self._header.setSpacing(8)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        text_col.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("CardSub")
            text_col.addWidget(subtitle_label)

        self._header.addLayout(text_col)
        self._header.addStretch(1)
        self._body.addLayout(self._header)

    @property
    def body(self) -> QVBoxLayout:
        """卡片内容布局。"""
        return self._body

    def add_header_widget(self, widget: QWidget) -> None:
        """在标题栏右侧追加控件。"""
        self._header.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
