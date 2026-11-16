"""线程进度列表中的单行（一个活动线程）。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ..constants import STEPS, StepStatus
from ..utils import repolish
from .elided_label import ElidedLabel


class ThreadProgressRow(QFrame):
    def __init__(
        self,
        thread_id: int,
        label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ThreadRow")
        self.setFixedHeight(78)
        self._thread_id = thread_id
        self._steps = [
            {"progress": 0.0, "status": StepStatus.PENDING, "detail": ""}
            for _ in STEPS
        ]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel(f"线程 {thread_id}")
        title.setObjectName("ThreadTitle")
        self.phone_label = ElidedLabel(label)
        self.phone_label.setObjectName("ThreadPhone")
        self.chip = QLabel("运行中")
        self.chip.setObjectName("MiniChip")
        self.chip.setProperty("state", "running")
        header.addWidget(title)
        header.addWidget(self.phone_label, 1)
        header.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(header)

        steps_row = QHBoxLayout()
        steps_row.setSpacing(10)
        self._dots: list[QLabel] = []
        for step in STEPS:
            dot = QLabel("●")
            dot.setObjectName("StepDot")
            dot.setProperty("state", StepStatus.PENDING)
            dot.setFixedWidth(12)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name = QLabel(step.name)
            name.setObjectName("ThreadStepName")
            steps_row.addWidget(dot)
            steps_row.addWidget(name)
            self._dots.append(dot)
        steps_row.addStretch(1)
        layout.addLayout(steps_row)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        meta = QLabel("线程进度")
        meta.setObjectName("ThreadMeta")
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("ThreadPercent")
        self.percent_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        bottom.addWidget(meta)
        bottom.addStretch(1)
        bottom.addWidget(self.percent_label)
        layout.addLayout(bottom)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("ThreadBar")
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        layout.addWidget(self.progress_bar)

        self._refresh()

    def set_label(self, label: str) -> None:
        self.phone_label.set_full_text(label)

    def update_step(
        self,
        index: int,
        *,
        progress: float,
        status: str,
        detail: str = "",
    ) -> None:
        if not 0 <= index < len(self._steps):
            return
        step = self._steps[index]
        step["progress"] = max(0.0, min(100.0, float(progress)))
        step["status"] = status
        step["detail"] = detail

        dot = self._dots[index]
        dot.setProperty("state", status)
        repolish(dot)
        dot.setToolTip(
            f"{STEPS[index].name} · {status} · {progress:.0f}%"
            + (f"\n{detail}" if detail else "")
        )
        self._refresh()

    def _refresh(self) -> None:
        overall = sum(step["progress"] for step in self._steps) / len(self._steps)
        self.progress_bar.setValue(int(round(overall * 10)))
        self.percent_label.setText(f"{overall:.0f}%")

        any_error = any(
            step["status"] == StepStatus.ERROR for step in self._steps
        )
        any_running = any(
            step["status"] == StepStatus.RUNNING for step in self._steps
        )
        all_done = all(
            step["status"] == StepStatus.DONE for step in self._steps
        )

        if any_error:
            bar_state = "error"
            chip_text, chip_state = "失败", "error"
        elif all_done:
            bar_state = "done"
            chip_text, chip_state = "已完成", "done"
        elif any_running:
            bar_state = "running"
            chip_text, chip_state = "运行中", "running"
        elif overall > 0:
            bar_state = "running"
            chip_text, chip_state = "运行中", "running"
        else:
            bar_state = "idle"
            chip_text, chip_state = "等待中", "idle"

        self.progress_bar.setProperty("status", bar_state)
        repolish(self.progress_bar)
        self.chip.setText(chip_text)
        self.chip.setProperty("state", chip_state)
        repolish(self.chip)
