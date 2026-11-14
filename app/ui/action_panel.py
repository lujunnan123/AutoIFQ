"""运行控制卡片。"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ..models import RunState
from .card import Card


class ActionPanel(Card):
    start_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    stop_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("运行控制", None, parent)

        self.start_btn = QPushButton("开始询价")
        self.start_btn.setObjectName("Primary")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setFixedHeight(44)
        self.start_btn.clicked.connect(lambda: self.start_requested.emit())

        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setObjectName("Secondary")
        self.pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_btn.setFixedHeight(38)
        self.pause_btn.clicked.connect(lambda: self.pause_requested.emit())

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setFixedHeight(38)
        self.stop_btn.clicked.connect(lambda: self.stop_requested.emit())

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        button_row.addWidget(self.pause_btn, 1)
        button_row.addWidget(self.stop_btn, 1)

        self.body.addWidget(self.start_btn)
        self.body.addLayout(button_row)

    def set_state(self, state: RunState) -> None:
        running = state is RunState.RUNNING
        paused = state is RunState.PAUSED
        active = running or paused
        idle = state is RunState.IDLE
        done = state is RunState.DONE

        self.start_btn.setEnabled(idle or done)
        self.start_btn.setText("重新询价" if done else "开始询价")
        self.pause_btn.setEnabled(active)
        self.pause_btn.setText("继续" if paused else "暂停")
        self.stop_btn.setEnabled(active)
