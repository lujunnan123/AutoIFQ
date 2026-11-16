"""手动测试窗口（内容暂定）。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget


class ManualTestWindow(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ManualTestWindow")
        self.setWindowTitle("手动测试")
        self.resize(760, 520)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        title = QLabel("手动测试")
        title.setObjectName("AppTitle")
        hint = QLabel("手动测试界面 · 内容暂定")
        hint.setObjectName("CardSub")

        placeholder = QLabel("功能开发中")
        placeholder.setObjectName("ManualTestPlaceholder")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)

        close_btn = QPushButton("关闭")
        close_btn.setObjectName("Ghost")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.close)

        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addStretch(1)
        layout.addWidget(placeholder, 2)
        layout.addStretch(1)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)
