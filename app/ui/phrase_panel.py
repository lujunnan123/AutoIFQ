"""询问话术卡片：自定义列表，支持新建、删除与点击确认。"""

from __future__ import annotations

from collections.abc import Iterable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .card import Card
from .click_outside import ClickOutsideFilter
from .phrase_row import PhraseRow


class PhrasePanel(Card):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "询问话术", "添加回复话术，系统将随机挑选话术中咨询坑位", parent
        )

        self._rows: list[PhraseRow] = []
        self._selected: PhraseRow | None = None

        self.new_btn = QPushButton("新建")
        self.new_btn.setObjectName("Ghost")
        self.new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_btn.setToolTip("添加一条询问话术")
        self.new_btn.clicked.connect(self._add_new)

        self.delete_btn = QPushButton("删除")
        self.delete_btn.setObjectName("GhostDanger")
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.setToolTip("删除选中的话术")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._delete_selected)

        self.add_header_widget(self.new_btn)
        self.add_header_widget(self.delete_btn)

        self._build_list()

        # 点击界面除当前输入框外的任意位置时确认内容
        self._click_filter = ClickOutsideFilter(self._on_outside_click, self)

    # ------------------------------------------------------------------
    # 构建列表
    # ------------------------------------------------------------------

    def _build_list(self) -> None:
        self.scroll = QScrollArea()
        self.scroll.setObjectName("PhraseScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFixedHeight(150)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.viewport().setObjectName("PhraseViewport")

        self._list_host = QWidget()
        self._list_host.setObjectName("PhraseList")
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)

        self._empty_label = QLabel("暂无询问话术，点击「新建」添加")
        self._empty_label.setObjectName("PhraseEmpty")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setMinimumHeight(126)
        self._list_layout.addWidget(self._empty_label)
        self._list_layout.addStretch(1)

        self.scroll.setWidget(self._list_host)
        self.body.addWidget(self.scroll)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def phrases(self) -> tuple[str, ...]:
        """返回所有非空话术。"""
        return tuple(row.text() for row in self._rows if row.text())

    def set_phrases(self, phrases: Iterable[str]) -> None:
        """清空并重建话术列表。"""
        self._clear_rows()
        for phrase in phrases:
            self.add_phrase(phrase)

    def add_phrase(self, text: str = "") -> PhraseRow:
        row = PhraseRow(text)
        row.activated.connect(self._select_row)
        self._rows.append(row)
        self._list_layout.insertWidget(self._list_layout.count() - 1, row)
        self._renumber()
        self._select_row(row)
        self._refresh_empty_state()
        return row

    # ------------------------------------------------------------------
    # 点击确认
    # ------------------------------------------------------------------

    def _on_outside_click(self, clicked: object) -> None:
        """点击界面中除当前输入框外的任意位置时，立即确认其内容。"""
        focused = QApplication.focusWidget()
        for row in self._rows:
            if row.input is focused:
                if clicked is not row.input:
                    row.commit()
                break

    # ------------------------------------------------------------------
    # 内部操作
    # ------------------------------------------------------------------

    def _add_new(self) -> None:
        row = self.add_phrase()
        row.input.setFocus()
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _delete_selected(self) -> None:
        row = self._selected
        if row is None or row not in self._rows:
            return

        index = self._rows.index(row)
        self._rows.pop(index)
        self._list_layout.removeWidget(row)
        row.hide()
        row.deleteLater()
        self._renumber()

        self._selected = None
        if self._rows:
            self._select_row(self._rows[min(index, len(self._rows) - 1)])
        else:
            self.delete_btn.setEnabled(False)
        self._refresh_empty_state()

    def _select_row(self, row: PhraseRow) -> None:
        self._selected = row
        for candidate in self._rows:
            candidate.set_selected(candidate is row)
        self.delete_btn.setEnabled(row is not None)

    def _clear_rows(self) -> None:
        for row in self._rows:
            self._list_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._rows.clear()
        self._selected = None
        self.delete_btn.setEnabled(False)
        self._refresh_empty_state()

    def _renumber(self) -> None:
        for index, row in enumerate(self._rows, start=1):
            row.set_number(index)

    def _refresh_empty_state(self) -> None:
        self._empty_label.setVisible(not self._rows)

    def _scroll_to_bottom(self) -> None:
        scrollbar = self.scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
