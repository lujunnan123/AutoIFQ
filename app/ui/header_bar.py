"""窗口顶部标题栏与飞书登录状态。"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..utils import repolish


class HeaderBar(QWidget):
    feishu_clicked = pyqtSignal()
    pxb7_clicked = pyqtSignal()

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

        self.pxb7_chip = QPushButton("螃蟹未登录")
        self.pxb7_chip.setObjectName("Pxb7Chip")
        self.pxb7_chip.setProperty("state", "offline")
        self.pxb7_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pxb7_chip.setToolTip("点击登录螃蟹账号并获取咨询商家")
        self.pxb7_chip.clicked.connect(
            lambda: self.pxb7_clicked.emit()
        )

        self.feishu_chip = QPushButton("飞书未登录")
        self.feishu_chip.setObjectName("FeishuChip")
        self.feishu_chip.setProperty("state", "offline")
        self.feishu_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.feishu_chip.setToolTip("点击使用二维码登录飞书，或刷新登录状态")
        self.feishu_chip.clicked.connect(
            lambda: self.feishu_clicked.emit()
        )

        layout.addWidget(logo)
        layout.addLayout(titles, 1)
        layout.addWidget(self.pxb7_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.feishu_chip, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_feishu_status(self, text: str, state: str) -> None:
        self.feishu_chip.setText(text)
        self.feishu_chip.setProperty("state", state)
        repolish(self.feishu_chip)

    def set_pxb7_status(self, text: str, state: str) -> None:
        self.pxb7_chip.setText(text)
        self.pxb7_chip.setProperty("state", state)
        repolish(self.pxb7_chip)
