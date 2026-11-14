"""窗口顶部标题栏。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget


class HeaderBar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        logo = QLabel("A")
        logo.setObjectName("AppLogo")
        logo.setFixedSize(46, 46)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titles = QVBoxLayout()
        titles.setSpacing(1)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        app_title = QLabel("AutoIFQ")
        app_title.setObjectName("AppTitle")
        separator = QLabel("·")
        separator.setObjectName("TitleSep")
        subtitle = QLabel("自动询价助手")
        subtitle.setObjectName("AppSubTitle")
        title_row.addWidget(app_title)
        title_row.addWidget(separator)
        title_row.addWidget(subtitle)
        title_row.addStretch(1)

        description = QLabel("批量导入清单 · 自动询价 · 结果回填")
        description.setObjectName("AppSub")
        titles.addLayout(title_row)
        titles.addWidget(description)

        preview_chip = QLabel("螃蟹上号已接入 · 后续步骤开发中")
        preview_chip.setObjectName("PreviewChip")

        layout.addWidget(logo)
        layout.addLayout(titles, 1)
        layout.addWidget(preview_chip, 0, Qt.AlignmentFlag.AlignVCenter)
