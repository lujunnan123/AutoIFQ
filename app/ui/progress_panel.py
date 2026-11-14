"""询价流程进度卡片。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget

from ..constants import STEPS
from ..utils import repolish
from .card import Card
from .segmented_progress import SegmentedProgress


class ProgressPanel(Card):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("询价进度", "五步流程 · 实时可视化监听", parent)

        self.chip = QLabel("待开始")
        self.chip.setObjectName("StatusChip")
        self.chip.setProperty("state", "idle")
        self.add_header_widget(self.chip)

        self.segmented = SegmentedProgress(STEPS)
        self.body.addWidget(self.segmented)

        overall_row = QHBoxLayout()
        overall_row.setSpacing(8)
        overall_title = QLabel("总进度")
        overall_title.setObjectName("MetaLabel")
        self.overall_label = QLabel("0%")
        self.overall_label.setObjectName("OverallPercent")
        self.overall_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        overall_row.addWidget(overall_title)
        overall_row.addStretch(1)
        overall_row.addWidget(self.overall_label)
        self.body.addLayout(overall_row)

        self.overall_bar = QProgressBar()
        self.overall_bar.setObjectName("OverallBar")
        self.overall_bar.setRange(0, 1000)
        self.overall_bar.setTextVisible(False)
        self.overall_bar.setFixedHeight(8)
        self.body.addWidget(self.overall_bar)

    def set_step(
        self,
        index: int,
        *,
        progress: float | None = None,
        status: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.segmented.set_step(
            index, progress=progress, status=status, detail=detail
        )
        self.refresh_overall()

    def reset(self) -> None:
        self.segmented.reset()
        self.refresh_overall()

    def set_chip(self, text: str, state: str) -> None:
        self.chip.setText(text)
        self.chip.setProperty("state", state)
        repolish(self.chip)

    def refresh_overall(self) -> None:
        overall = self.segmented.overall()
        self.overall_bar.setValue(int(round(overall * 10)))
        self.overall_label.setText(f"{overall:.0f}%")
