"""运行参数卡片。"""

from __future__ import annotations

from collections.abc import Mapping

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QWidget,
)

from ..constants import PARAMETER_FIELDS, SpinFieldSpec
from ..models import RunParams
from .card import Card
from .click_outside import ClickOutsideFilter


class ParameterPanel(Card):
    valuesChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("运行参数", "线程、间隔与询价范围", parent)

        self._spins: dict[str, QSpinBox | QDoubleSpinBox] = {}
        self._saved_labels: dict[str, QLabel] = {}
        self._saved_timers: dict[str, QTimer] = {}
        self._committed_values: dict[str, float] = {}

        form = QFormLayout()
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)

        for spec in PARAMETER_FIELDS:
            spin = self._create_spin(spec)
            self._spins[spec.key] = spin

            saved_label = QLabel("")
            saved_label.setObjectName("FieldSaved")
            saved_label.setFixedWidth(16)
            saved_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            saved_label.setToolTip("已保存")
            self._saved_labels[spec.key] = saved_label

            field = QWidget()
            field_layout = QHBoxLayout(field)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(6)
            field_layout.addWidget(spin, 1)
            field_layout.addWidget(
                saved_label, 0, Qt.AlignmentFlag.AlignVCenter
            )

            field_label = QLabel(spec.label)
            field_label.setObjectName("FieldLabel")
            form.addRow(field_label, field)

            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(1200)
            timer.timeout.connect(lambda label=saved_label: label.setText(""))
            self._saved_timers[spec.key] = timer

            spin.editingFinished.connect(
                lambda key=spec.key: self._confirm_field(key)
            )
            self._committed_values[spec.key] = float(spin.value())

        self.body.addLayout(form)

        hint = QLabel("线程数用于螃蟹上号；其余参数将在后续步骤接入后生效。")
        hint.setObjectName("HintLabel")
        self.body.addWidget(hint)

        for spin in self._spins.values():
            spin.valueChanged.connect(self._on_value_changed)

        # 点击界面除当前数值输入框外的任意位置时确认内容
        self._click_filter = ClickOutsideFilter(self._on_outside_click, self)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def build_params(self, phrases: tuple[str, ...]) -> RunParams:
        """把界面上的参数收集为不可变的 RunParams。"""
        values = self.values()
        return RunParams(
            threads=int(values["threads"]),
            interval_sec=float(values["interval_sec"]),
            merchant_count=int(values["merchant_count"]),
            timeout_sec=int(values["timeout_sec"]),
            retries=int(values["retries"]),
            phrases=phrases,
        )

    def values(self) -> dict[str, int | float]:
        """读取当前参数，并先确认输入框内未提交的文本。"""
        result: dict[str, int | float] = {}
        for key, spin in self._spins.items():
            blocked = spin.blockSignals(True)
            try:
                spin.interpretText()
            finally:
                spin.blockSignals(blocked)
            result[key] = spin.value()
        return result

    def apply_values(self, values: Mapping[str, float]) -> None:
        """恢复持久化参数；越界值会被控件自动钳制。"""
        for key, spin in self._spins.items():
            if key not in values:
                continue
            try:
                value = float(values[key])
            except (TypeError, ValueError):
                continue
            blocked = spin.blockSignals(True)
            try:
                if isinstance(spin, QDoubleSpinBox):
                    spin.setValue(value)
                else:
                    spin.setValue(int(round(value)))
            finally:
                spin.blockSignals(blocked)
            self._committed_values[key] = float(spin.value())

    def _on_value_changed(self, _value) -> None:
        self.valuesChanged.emit()

    # ------------------------------------------------------------------
    # 失焦确认
    # ------------------------------------------------------------------

    def _on_outside_click(self, clicked: object) -> None:
        for key, spin in self._spins.items():
            line_edit = spin.lineEdit()
            editing = spin.hasFocus() or (
                line_edit is not None and line_edit.hasFocus()
            )
            if editing:
                if not self._is_inside(clicked, spin):
                    self._confirm_field(key)
                break

    @staticmethod
    def _is_inside(clicked: object, spin: QWidget) -> bool:
        return isinstance(clicked, QWidget) and (
            clicked is spin or spin.isAncestorOf(clicked)
        )

    def _confirm_field(self, key: str) -> None:
        spin = self._spins[key]
        spin.interpretText()

        value = float(spin.value())
        if value == self._committed_values[key]:
            return

        self._committed_values[key] = value
        saved_label = self._saved_labels[key]
        saved_label.setToolTip(f"已保存：{spin.text()}")
        saved_label.setText("✓")
        self._saved_timers[key].start()

    # ------------------------------------------------------------------
    # 控件工厂
    # ------------------------------------------------------------------

    @staticmethod
    def _create_spin(spec: SpinFieldSpec) -> QSpinBox | QDoubleSpinBox:
        if spec.decimals:
            spin: QSpinBox | QDoubleSpinBox = QDoubleSpinBox()
            spin.setDecimals(spec.decimals)
            spin.setSingleStep(spec.step)
        else:
            spin = QSpinBox()

        spin.setRange(spec.minimum, spec.maximum)
        spin.setValue(spec.default)
        spin.setSuffix(spec.suffix)
        spin.setToolTip(spec.tip)
        spin.setMinimumHeight(32)
        spin.setKeyboardTracking(False)
        return spin
