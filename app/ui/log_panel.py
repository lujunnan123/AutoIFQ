"""运行日志卡片。"""

from __future__ import annotations

import html
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPlainTextEdit, QPushButton, QWidget

from ..constants import LOG_LEVEL_COLORS
from .card import Card


class LogPanel(Card):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str = "运行日志",
        subtitle: str = "实时输出每一步的执行信息",
    ) -> None:
        super().__init__(title, subtitle, parent)

        clear_button = QPushButton("清空")
        clear_button.setObjectName("Ghost")
        clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_button.clicked.connect(self.clear)
        self.add_header_widget(clear_button)

        self.view = QPlainTextEdit()
        self.view.setObjectName("LogView")
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(2000)
        self.view.setPlaceholderText("等待运行…")
        self.view.setMinimumHeight(120)
        self.body.addWidget(self.view, 1)

    def append(self, message: str, level: str = "info") -> None:
        color = LOG_LEVEL_COLORS.get(level, LOG_LEVEL_COLORS["info"])
        stamp = datetime.now().strftime("%H:%M:%S")
        self.view.appendHtml(
            f'<span style="color:#4d6076;">[{stamp}]</span> '
            f'<span style="color:{color};">{html.escape(message)}</span>'
        )
        scrollbar = self.view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear(self) -> None:
        self.view.clear()
