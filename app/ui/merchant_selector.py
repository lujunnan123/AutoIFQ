"""咨询商家多选控件。"""

from __future__ import annotations

from collections.abc import Iterable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class MerchantSelector(QWidget):
    selectionChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._merchants: list[str] = []
        self._checks: list[QCheckBox] = []
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)

        title = QLabel("咨询商家")
        title.setObjectName("FieldLabel")

        self.summary_label = QLabel("尚未获取商家")
        self.summary_label.setObjectName("MerchantSummary")

        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.setObjectName("Ghost")
        self.select_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.select_all_btn.setFixedHeight(24)
        self.select_all_btn.setEnabled(False)
        self.select_all_btn.clicked.connect(self._select_all)

        self.clear_btn = QPushButton("清空")
        self.clear_btn.setObjectName("Ghost")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setFixedHeight(24)
        self.clear_btn.setEnabled(False)
        self.clear_btn.clicked.connect(self._clear_selection)

        header.addWidget(title)
        header.addWidget(self.summary_label)
        header.addStretch(1)
        header.addWidget(self.select_all_btn)
        header.addWidget(self.clear_btn)
        layout.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("MerchantScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFixedHeight(118)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.viewport().setObjectName("MerchantViewport")

        self._list_host = QWidget()
        self._list_host.setObjectName("MerchantList")
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(2, 2, 4, 2)
        self._list_layout.setSpacing(2)

        self.empty_label = QLabel(
            "尚未获取商家，请点击右上角「螃蟹未登录」登录"
        )
        self.empty_label.setObjectName("MerchantEmpty")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setMinimumHeight(104)
        self._list_layout.addWidget(self.empty_label)
        self._list_layout.addStretch(1)

        self.scroll.setWidget(self._list_host)
        layout.addWidget(self.scroll)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def set_merchants(
        self,
        merchants: Iterable[str],
        selected: Iterable[str] = (),
    ) -> None:
        values: list[str] = []
        seen: set[str] = set()
        for merchant in merchants:
            if not isinstance(merchant, str):
                continue
            name = merchant.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            values.append(name)

        selected_set = {
            name.strip()
            for name in selected
            if isinstance(name, str) and name.strip()
        }

        self._updating = True
        try:
            self._clear_checks()
            self._merchants = values
            for name in values:
                check = QCheckBox(name)
                check.setObjectName("MerchantCheck")
                check.setCursor(Qt.CursorShape.PointingHandCursor)
                check.setToolTip(name)
                check.setChecked(name in selected_set)
                check.toggled.connect(self._on_toggled)
                self._checks.append(check)
                self._list_layout.insertWidget(
                    self._list_layout.count() - 1, check
                )
        finally:
            self._updating = False

        has_merchants = bool(values)
        self.empty_label.setVisible(not has_merchants)
        self.select_all_btn.setEnabled(has_merchants)
        self.clear_btn.setEnabled(has_merchants)
        self._refresh_summary()
        self.selectionChanged.emit()

    def merchants(self) -> tuple[str, ...]:
        return tuple(self._merchants)

    def selected_merchants(self) -> tuple[str, ...]:
        return tuple(
            check.text() for check in self._checks if check.isChecked()
        )

    # ------------------------------------------------------------------
    # 内部操作
    # ------------------------------------------------------------------

    def _clear_checks(self) -> None:
        for check in self._checks:
            self._list_layout.removeWidget(check)
            check.hide()
            check.deleteLater()
        self._checks.clear()
        self._merchants = []

    def _on_toggled(self, _checked: bool) -> None:
        if self._updating:
            return
        self._refresh_summary()
        self.selectionChanged.emit()

    def _select_all(self) -> None:
        self._apply_checked(True)

    def _clear_selection(self) -> None:
        self._apply_checked(False)

    def _apply_checked(self, checked: bool) -> None:
        if not self._checks:
            return
        self._updating = True
        try:
            for check in self._checks:
                check.setChecked(checked)
        finally:
            self._updating = False
        self._refresh_summary()
        self.selectionChanged.emit()

    def _refresh_summary(self) -> None:
        total = len(self._merchants)
        if not total:
            self.summary_label.setText("尚未获取商家")
            return
        selected = len(self.selected_merchants())
        self.summary_label.setText(f"已选 {selected} / {total} 家")
