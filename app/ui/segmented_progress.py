"""分块流程进度可视化组件。"""

from __future__ import annotations

import math
from collections.abc import Sequence

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..constants import StepSpec, StepStatus

_BACKGROUNDS = {
    StepStatus.PENDING: (QColor("#0e151e"), QColor("#1d2836")),
    StepStatus.RUNNING: (QColor("#0e1929"), QColor("#2d4d7a")),
    StepStatus.DONE: (QColor("#0d1a17"), QColor("#1e3b32")),
    StepStatus.ERROR: (QColor("#1c1217"), QColor("#4a2631")),
}

_PERCENT_COLORS = {
    StepStatus.PENDING: "#5d6f84",
    StepStatus.RUNNING: "#79b4ff",
    StepStatus.DONE: "#3fe0a4",
    StepStatus.ERROR: "#ff7b8f",
}


class SegmentedProgress(QWidget):
    """每个步骤独立显示状态、百分比与细节的流程进度条。"""

    def __init__(
        self, steps: Sequence[StepSpec], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._steps = [
            {
                "name": step.name,
                "hint": step.hint,
                "progress": 0.0,
                "status": StepStatus.PENDING,
                "detail": "",
            }
            for step in steps
        ]
        self._phase = 0.0
        self.setFixedHeight(108)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._anim = QTimer(self)
        self._anim.setInterval(40)
        self._anim.timeout.connect(self._on_anim)

    # ---- API -------------------------------------------------------------

    def set_step(
        self,
        index: int,
        *,
        progress: float | None = None,
        status: str | None = None,
        detail: str | None = None,
    ) -> None:
        if not 0 <= index < len(self._steps):
            return
        step = self._steps[index]
        if progress is not None:
            step["progress"] = max(0.0, min(100.0, float(progress)))
        if status is not None:
            step["status"] = status
        if detail is not None:
            step["detail"] = detail
        self._sync_anim()
        self.update()

    def reset(self) -> None:
        for step in self._steps:
            step.update(progress=0.0, status=StepStatus.PENDING, detail="")
        self._anim.stop()
        self.update()

    def step(self, index: int) -> dict:
        return self._steps[index]

    def overall(self) -> float:
        return sum(step["progress"] for step in self._steps) / len(self._steps)

    # ---- 动画 ------------------------------------------------------------

    def _sync_anim(self) -> None:
        running = any(step["status"] == StepStatus.RUNNING for step in self._steps)
        if running and not self._anim.isActive():
            self._anim.start()
        elif not running and self._anim.isActive():
            self._anim.stop()

    def _on_anim(self) -> None:
        self._phase = (self._phase + 0.09) % (2 * math.pi)
        self.update()

    # ---- 绘制 ------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        count = len(self._steps)
        gap = 8
        card_w = (self.width() - gap * (count - 1)) / count

        for index, step in enumerate(self._steps):
            x = index * (card_w + gap)
            self._draw_card(painter, QRectF(x, 0, card_w, self.height()), step)

    def _draw_card(self, painter: QPainter, rect: QRectF, step: dict) -> None:
        status = step["status"]
        background, border = _BACKGROUNDS.get(status, _BACKGROUNDS[StepStatus.PENDING])

        painter.setPen(QPen(border, 1))
        painter.setBrush(background)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)

        x = rect.x() + 14
        y = rect.y()
        w = rect.width() - 28
        cx, cy = rect.x() + 17, y + 20

        self._draw_status_dot(painter, cx, cy, status)

        name_font = QFont(self.font())
        name_font.setPixelSize(13)
        name_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(name_font)
        painter.setPen(
            QColor("#e7eef8") if status != StepStatus.PENDING else QColor("#a9b8ca")
        )

        name_rect = QRectF(x + 17, y + 12, w - 17, 17)
        metrics = QFontMetrics(name_font)
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(
                step["name"], Qt.TextElideMode.ElideRight, int(name_rect.width())
            ),
        )

        detail = step["detail"] or step["hint"]
        if status == StepStatus.DONE and not step["detail"]:
            detail = "已完成"
        elif status == StepStatus.ERROR:
            detail = detail or "执行失败"

        detail_font = QFont(self.font())
        detail_font.setPixelSize(10)
        painter.setFont(detail_font)
        painter.setPen(
            QColor("#566a80")
            if status == StepStatus.PENDING
            else QColor("#7e92a9")
        )
        detail_rect = QRectF(x, y + 36, w, 14)
        metrics = QFontMetrics(detail_font)
        painter.drawText(
            detail_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(detail, Qt.TextElideMode.ElideRight, int(detail_rect.width())),
        )

        # 进度轨道 + 百分比
        bar_rect = QRectF(x, rect.bottom() - 20, w - 44, 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#182230"))
        painter.drawRoundedRect(bar_rect, 3, 3)

        pct_font = QFont(self.font())
        pct_font.setPixelSize(10)
        pct_font.setWeight(QFont.Weight.DemiBold)
        percent_text = (
            "100%" if status == StepStatus.DONE else f"{step['progress']:.0f}%"
        )
        painter.setFont(pct_font)
        painter.setPen(
            QColor(_PERCENT_COLORS.get(status, _PERCENT_COLORS[StepStatus.PENDING]))
        )
        painter.drawText(
            QRectF(rect.right() - 50, rect.bottom() - 29, 36, 15),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            percent_text,
        )

        self._draw_fill(painter, bar_rect, step, status)

    def _draw_fill(
        self, painter: QPainter, bar_rect: QRectF, step: dict, status: str
    ) -> None:
        fraction = max(0.0, min(1.0, step["progress"] / 100.0))
        if fraction <= 0:
            return

        fill_rect = QRectF(
            bar_rect.x(),
            bar_rect.y(),
            max(6.0, bar_rect.width() * fraction),
            bar_rect.height(),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        gradient = QLinearGradient(fill_rect.left(), 0, fill_rect.right(), 0)
        if status == StepStatus.ERROR:
            gradient.setColorAt(0.0, QColor("#ff5d73"))
            gradient.setColorAt(1.0, QColor("#ff8b9c"))
        elif status == StepStatus.DONE:
            gradient.setColorAt(0.0, QColor("#22c98f"))
            gradient.setColorAt(1.0, QColor("#3fe0a4"))
        else:
            gradient.setColorAt(0.0, QColor("#3f84ff"))
            gradient.setColorAt(1.0, QColor("#35d6c0"))
        painter.setBrush(gradient)
        painter.drawRoundedRect(fill_rect, 3, 3)

    def _draw_status_dot(
        self, painter: QPainter, cx: float, cy: float, status: str
    ) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        if status == StepStatus.DONE:
            painter.setBrush(QColor("#2ecc8f"))
            painter.drawEllipse(QRectF(cx - 7, cy - 7, 14, 14))
            pen = QPen(QColor("#ffffff"), 1.7)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            path.moveTo(cx - 3.6, cy)
            path.lineTo(cx - 1.0, cy + 2.8)
            path.lineTo(cx + 4.2, cy - 3.0)
            painter.drawPath(path)
        elif status == StepStatus.RUNNING:
            glow_alpha = int(55 + 45 * (0.5 + 0.5 * math.sin(self._phase)))
            painter.setBrush(QColor(79, 140, 255, glow_alpha))
            painter.drawEllipse(QRectF(cx - 9, cy - 9, 18, 18))
            painter.setBrush(QColor("#4f8cff"))
            painter.drawEllipse(QRectF(cx - 4.5, cy - 4.5, 9, 9))
        elif status == StepStatus.ERROR:
            painter.setBrush(QColor("#ff5d73"))
            painter.drawEllipse(QRectF(cx - 7, cy - 7, 14, 14))
            font = QFont(self.font())
            font.setPixelSize(11)
            font.setWeight(QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(
                QRectF(cx - 7, cy - 8, 14, 15), Qt.AlignmentFlag.AlignCenter, "!"
            )
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#3b4c61"), 1.6))
            painter.drawEllipse(QRectF(cx - 5.5, cy - 5.5, 11, 11))
