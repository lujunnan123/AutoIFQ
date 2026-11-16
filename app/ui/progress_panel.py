"""询价进度卡片：先构建表格，再以列表展示活动线程。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..constants import StepStatus
from ..utils import repolish
from .card import Card
from .elided_label import ElidedLabel
from .thread_progress_row import ThreadProgressRow


class ProgressPanel(Card):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "询价进度", "先构建表格，再按线程数展开执行", parent
        )
        self._rows: dict[int, ThreadProgressRow] = {}
        self._build_state = "pending"
        self._message = "点击开始后先构建表格，再展开线程"
        self._final_message: str | None = None

        self.chip = QLabel("待开始")
        self.chip.setObjectName("StatusChip")
        self.chip.setProperty("state", "idle")
        self.add_header_widget(self.chip)

        self._build_row = QFrame()
        self._build_row.setObjectName("BuildRow")
        build_layout = QHBoxLayout(self._build_row)
        build_layout.setContentsMargins(10, 6, 10, 6)
        build_layout.setSpacing(8)

        self._build_dot = QLabel("●")
        self._build_dot.setObjectName("StepDot")
        self._build_dot.setProperty("state", StepStatus.PENDING)
        self._build_dot.setFixedWidth(12)
        self._build_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)

        build_title = QLabel("构建表格")
        build_title.setObjectName("BuildTitle")
        self._build_detail = ElidedLabel("等待开始")
        self._build_detail.setObjectName("BuildDetail")
        self._build_status = QLabel("等待中")
        self._build_status.setObjectName("MiniChip")
        self._build_status.setProperty("state", "idle")

        build_layout.addWidget(self._build_dot)
        build_layout.addWidget(build_title)
        build_layout.addWidget(self._build_detail, 1)
        build_layout.addWidget(
            self._build_status, 0, Qt.AlignmentFlag.AlignVCenter
        )
        self.body.addWidget(self._build_row)

        section_row = QHBoxLayout()
        section_row.setSpacing(8)
        section_title = QLabel("线程进度")
        section_title.setObjectName("SectionTitle")
        self._thread_count = QLabel("0 个线程")
        self._thread_count.setObjectName("MetaLabel")
        section_row.addWidget(section_title)
        section_row.addWidget(self._thread_count)
        section_row.addStretch(1)
        self.body.addLayout(section_row)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("ThreadScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFixedHeight(200)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.viewport().setObjectName("ThreadViewport")

        self._list_host = QWidget()
        self._list_host.setObjectName("ThreadList")
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)

        self._empty = QLabel(self._message)
        self._empty.setObjectName("ThreadEmpty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setMinimumHeight(180)
        self._relayout_rows()

        self.scroll.setWidget(self._list_host)
        self.body.addWidget(self.scroll)

        self.set_build_status("pending", "等待开始")

    # ------------------------------------------------------------------
    # 构建表格状态
    # ------------------------------------------------------------------

    def set_build_status(self, state: str, detail: str) -> None:
        self._build_state = state
        mapping = {
            "pending": ("等待中", "idle", StepStatus.PENDING),
            "running": ("构建中", "running", StepStatus.RUNNING),
            "done": ("已完成", "done", StepStatus.DONE),
            "error": ("失败", "error", StepStatus.ERROR),
        }
        text, chip_state, dot_state = mapping.get(
            state, mapping["pending"]
        )
        self._build_status.setText(text)
        self._build_status.setProperty("state", chip_state)
        repolish(self._build_status)

        self._build_dot.setProperty("state", dot_state)
        repolish(self._build_dot)

        self._build_detail.set_full_text(detail or "等待开始")
        self._build_detail.setToolTip(detail)

        if not self._rows:
            self._message = {
                "pending": "点击开始后先构建表格，再展开线程",
                "running": "正在构建表格…",
                "done": "构建表格完成，正在展开线程…",
                "error": "构建表格失败，线程未执行",
            }.get(state, "点击开始后先构建表格，再展开线程")
            self._empty.setText(self._message)
            self._empty.setVisible(True)

    # ------------------------------------------------------------------
    # 线程列表行
    # ------------------------------------------------------------------

    def add_thread(self, thread_id: int, label: str) -> None:
        row = self._rows.get(thread_id)
        if row is not None:
            row.set_label(label)
            return

        row = ThreadProgressRow(thread_id, label)
        self._rows[thread_id] = row
        self._relayout_rows()
        self._thread_count.setText(f"{len(self._rows)} 个线程")

    def remove_thread(self, thread_id: int) -> None:
        row = self._rows.pop(thread_id, None)
        if row is not None:
            row.hide()
            row.deleteLater()
        self._thread_count.setText(f"{len(self._rows)} 个线程")
        if not self._rows and self._final_message is None:
            self._message = "正在等待下一条数据…"
        self._relayout_rows()

    def clear_threads(self) -> None:
        for row in self._rows.values():
            row.hide()
            row.deleteLater()
        self._rows.clear()
        self._thread_count.setText("0 个线程")
        self._relayout_rows()

    def update_thread_step(
        self,
        thread_id: int,
        step_index: int,
        *,
        progress: float,
        status: str,
        detail: str = "",
    ) -> None:
        self._ensure_row(thread_id)
        self._rows[thread_id].update_step(
            step_index, progress=progress, status=status, detail=detail
        )

    def set_thread_message(self, message: str, *, final: bool = False) -> None:
        self._message = message
        if final:
            self._final_message = message
        if not self._rows:
            self._empty.setText(message)
            self._empty.setVisible(True)

    def _ensure_row(self, thread_id: int) -> None:
        if thread_id not in self._rows:
            self.add_thread(thread_id, f"线程 {thread_id}")

    # ------------------------------------------------------------------
    # 布局
    # ------------------------------------------------------------------

    def _relayout_rows(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self._list_host)

        if not self._rows:
            self._empty.setText(self._message)
            self._empty.setVisible(True)
            self._list_layout.addWidget(self._empty)
            self._list_layout.addStretch(1)
            return

        self._empty.setVisible(False)
        for thread_id in sorted(self._rows):
            self._list_layout.addWidget(self._rows[thread_id])
        self._list_layout.addStretch(1)

    # ------------------------------------------------------------------
    # 公共状态
    # ------------------------------------------------------------------

    def reset(self) -> None:
        for row in self._rows.values():
            row.hide()
            row.deleteLater()
        self._rows.clear()
        self._thread_count.setText("0 个线程")
        self._message = "点击开始后先构建表格，再展开线程"
        self._final_message = None
        self._build_state = "pending"
        self._relayout_rows()
        self.set_build_status("pending", "等待开始")

    def set_chip(self, text: str, state: str) -> None:
        self.chip.setText(text)
        self.chip.setProperty("state", state)
        repolish(self.chip)
