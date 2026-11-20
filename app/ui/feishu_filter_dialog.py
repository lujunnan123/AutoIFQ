"""飞书多维表格筛选与结果确认窗口。"""

from __future__ import annotations

from datetime import date, datetime

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..services.excel_table import REQUIRED_COLUMNS
from ..services.feishu_filter import (
    FIELD_TYPES,
    OPERATOR_LABELS,
    FilterCondition,
    FilterGroup,
    field_operators,
    filter_records,
    is_empty_operator,
)
from ..services.feishu_table import FeishuRecord, FeishuTableData

_FIELDS = tuple(REQUIRED_COLUMNS) + ("上架情况", "账号内容图片")


class _ConditionRow(QFrame):
    changed = pyqtSignal()
    remove_requested = pyqtSignal(object)

    def __init__(
        self,
        choice_values: dict[str, list[str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FilterConditionRow")
        self._choice_values = choice_values
        self._editors: list[QWidget] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        self.field_combo = QComboBox()
        for field in _FIELDS:
            self.field_combo.addItem(field, field)
        self.field_combo.setMinimumWidth(120)

        self.operator_combo = QComboBox()
        self.operator_combo.setMinimumWidth(110)

        self.value_host = QWidget()
        self.value_layout = QHBoxLayout(self.value_host)
        self.value_layout.setContentsMargins(0, 0, 0, 0)
        self.value_layout.setSpacing(6)

        remove_btn = QPushButton("删除")
        remove_btn.setObjectName("GhostDanger")
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.clicked.connect(
            lambda: self.remove_requested.emit(self)
        )

        layout.addWidget(self.field_combo)
        layout.addWidget(self.operator_combo)
        layout.addWidget(self.value_host, 1)
        layout.addWidget(remove_btn)

        self.field_combo.currentIndexChanged.connect(
            self._on_field_changed
        )
        self.operator_combo.currentIndexChanged.connect(
            self._on_operator_changed
        )
        self._rebuild_operators()
        self._rebuild_value_editors()

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def field(self) -> str:
        return str(self.field_combo.currentData() or "")

    def operator(self) -> str:
        return str(self.operator_combo.currentData() or "")

    def condition(self) -> FilterCondition | None:
        field = self.field()
        operator = self.operator()
        field_type = FIELD_TYPES.get(field, "text")

        if is_empty_operator(operator):
            return FilterCondition(field, operator)

        if field_type == "date":
            values = [self._editor_date(editor) for editor in self._editors]
            values = [value for value in values if value is not None]
            if not values:
                return None
            if operator == "between":
                if len(values) < 2:
                    return None
                return FilterCondition(
                    field, operator, values[0], values[1]
                )
            return FilterCondition(field, operator, values[0])

        texts = [self._editor_text(editor) for editor in self._editors]
        if operator == "between":
            if len(texts) < 2:
                return None
            if not texts[0].strip() or not texts[1].strip():
                return None
            return FilterCondition(
                field, operator, texts[0], texts[1]
            )
        text = texts[0] if texts else ""
        if field_type in ("number", "choice") and not text.strip():
            return None
        return FilterCondition(field, operator, text)

    def set_changed_connections(self) -> None:
        self.field_combo.currentIndexChanged.connect(
            lambda: self.changed.emit()
        )
        self.operator_combo.currentIndexChanged.connect(
            lambda: self.changed.emit()
        )

    # ------------------------------------------------------------------
    # 控件重建
    # ------------------------------------------------------------------

    def _on_field_changed(self) -> None:
        self._rebuild_operators()
        self._rebuild_value_editors()
        self.changed.emit()

    def _on_operator_changed(self) -> None:
        self._rebuild_value_editors()
        self.changed.emit()

    def _rebuild_operators(self) -> None:
        previous = self.operator_combo.currentData()
        operators = field_operators(self.field())
        self.operator_combo.blockSignals(True)
        try:
            self.operator_combo.clear()
            for operator in operators:
                self.operator_combo.addItem(
                    OPERATOR_LABELS.get(operator, operator),
                    operator,
                )
            if previous in operators:
                self.operator_combo.setCurrentIndex(
                    operators.index(previous)
                )
        finally:
            self.operator_combo.blockSignals(False)

    def _rebuild_value_editors(self) -> None:
        while self.value_layout.count():
            item = self.value_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._editors.clear()

        field_type = FIELD_TYPES.get(self.field(), "text")
        operator = self.operator()
        if is_empty_operator(operator):
            hint = QLabel("无需填写")
            hint.setObjectName("HintLabel")
            self.value_layout.addWidget(hint)
            self.value_layout.addStretch(1)
            return

        count = (
            2
            if operator == "between"
            and field_type in ("number", "date")
            else 1
        )
        for index in range(count):
            if index == 1:
                separator = QLabel("~")
                separator.setObjectName("HintLabel")
                self.value_layout.addWidget(separator)
            editor = self._create_editor(field_type)
            self._editors.append(editor)
            self.value_layout.addWidget(editor, 1)

    def _create_editor(self, field_type: str) -> QWidget:
        if field_type == "date":
            editor = QDateEdit()
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("yyyy-MM-dd")
            editor.setDate(QDate.currentDate())
            return editor
        if field_type == "choice":
            editor = QComboBox()
            editor.setEditable(True)
            options = self._choice_values.get(self.field(), [])
            for value in options:
                editor.addItem(value)
            if editor.count():
                editor.setCurrentIndex(0)
            return editor
        editor = QLineEdit()
        editor.setPlaceholderText(
            "输入数字" if field_type == "number" else "输入文本"
        )
        return editor

    @staticmethod
    def _editor_text(editor: QWidget) -> str:
        if isinstance(editor, QLineEdit):
            return editor.text()
        if isinstance(editor, QComboBox):
            return editor.currentText()
        return ""

    @staticmethod
    def _editor_date(editor: QWidget) -> date | None:
        if isinstance(editor, QDateEdit):
            value = editor.date()
            if value.isValid():
                return value.toPyDate()
        return None


class FeishuFilterDialog(QDialog):
    """筛选飞书记录，显示结果并返回用户确认的记录。"""

    def __init__(
        self,
        data: FeishuTableData,
        parent: QWidget | None = None,
        *,
        merchant_count: int = 0,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FeishuFilterDialog")
        self.setWindowTitle("筛选飞书数据")
        self._data = data
        self._merchant_count = merchant_count
        self._records = list(data.records)
        self._rows = list(data.rows)
        self._filtered_indices: list[int] = []
        self._condition_rows: list[_ConditionRow] = []
        self._rebuilding = False
        self._selected_data: FeishuTableData | None = None
        self._choice_values = self._collect_choice_values()

        self._apply_screen_size()
        self._build_ui()
        self._add_condition_row()
        self._apply_filter()

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def selected_data(self) -> FeishuTableData | None:
        return self._selected_data

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _apply_screen_size(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1120, 760)
            return
        available = screen.availableGeometry()
        width = min(1200, max(960, available.width() - 60))
        height = min(800, max(620, available.height() - 70))
        self.resize(width, height)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        title = QLabel("筛选飞书数据")
        title.setObjectName("AppTitle")
        subtitle = QLabel(
            f"数据源：{self._data.source_name} · "
            f"当前视图 {self._data.total_records} 条 · "
            f"本次已读取 {len(self._records)} 条 · "
            f"咨询商家 {self._merchant_count} 个"
        )
        subtitle.setObjectName("CardSub")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        if self._data.total_records > len(self._records):
            warning = QLabel(
                "当前接口只加载了部分记录，筛选仅针对已读取的记录。"
            )
            warning.setObjectName("FilterWarning")
            warning.setWordWrap(True)
            layout.addWidget(warning)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(QLabel("条件组合"))
        self.joiner_combo = QComboBox()
        self.joiner_combo.addItem("满足全部条件（且）", "AND")
        self.joiner_combo.addItem("满足任一条件（或）", "OR")
        toolbar.addWidget(self.joiner_combo)
        toolbar.addStretch(1)

        add_btn = QPushButton("添加条件")
        add_btn.setObjectName("GhostStrong")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self._add_condition_row)

        reset_btn = QPushButton("重置")
        reset_btn.setObjectName("Ghost")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_conditions)

        apply_btn = QPushButton("应用筛选")
        apply_btn.setObjectName("Primary")
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.clicked.connect(self._apply_filter)

        toolbar.addWidget(add_btn)
        toolbar.addWidget(reset_btn)
        toolbar.addWidget(apply_btn)
        layout.addLayout(toolbar)

        scroll = QScrollArea()
        scroll.setObjectName("FilterConditionScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setMinimumHeight(92)
        scroll.setMaximumHeight(190)
        scroll.viewport().setObjectName("FilterConditionViewport")

        host = QWidget()
        host.setObjectName("FilterConditionHost")
        self._conditions_layout = QVBoxLayout(host)
        self._conditions_layout.setContentsMargins(0, 0, 0, 0)
        self._conditions_layout.setSpacing(6)
        self._conditions_layout.addStretch(1)
        scroll.setWidget(host)
        layout.addWidget(scroll)

        self.filter_status = QLabel("")
        self.filter_status.setObjectName("FilterStatus")
        layout.addWidget(self.filter_status)

        self.table = QTableWidget(0, 9)
        self.table.setObjectName("FilterPreviewTable")
        self.table.setHorizontalHeaderLabels(
            [
                "选择",
                "账号",
                "账号内容",
                "收购日期",
                "可不可二次",
                "成本",
                "拉群前报价",
                "上架情况",
                "图片",
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed
        )
        self.table.setColumnWidth(0, 48)
        for column in (1, 3, 4, 5, 6, 7, 8):
            header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        header.setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.select_all_btn = QPushButton("全选")
        self.select_none_btn = QPushButton("取消全选")
        self.select_images_btn = QPushButton("仅选有图片")
        for button in (
            self.select_all_btn,
            self.select_none_btn,
            self.select_images_btn,
        ):
            button.setObjectName("Ghost")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            bottom.addWidget(button)
        self.select_all_btn.clicked.connect(
            lambda: self._set_all_checked(True)
        )
        self.select_none_btn.clicked.connect(
            lambda: self._set_all_checked(False)
        )
        self.select_images_btn.clicked.connect(
            self._select_with_images
        )
        bottom.addStretch(1)
        self.counts_label = QLabel("")
        self.counts_label.setObjectName("FilterCounts")
        bottom.addWidget(self.counts_label)

        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("Ghost")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        self.confirm_btn = QPushButton("确认并开始询价")
        self.confirm_btn.setObjectName("Primary")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.clicked.connect(self._confirm)
        bottom.addWidget(cancel_btn)
        bottom.addWidget(self.confirm_btn)
        layout.addLayout(bottom)

    # ------------------------------------------------------------------
    # 条件
    # ------------------------------------------------------------------

    def _add_condition_row(self) -> None:
        row = _ConditionRow(self._choice_values)
        row.remove_requested.connect(self._remove_condition_row)
        row.set_changed_connections()
        self._condition_rows.append(row)
        self._conditions_layout.insertWidget(
            self._conditions_layout.count() - 1, row
        )

    def _remove_condition_row(self, row: _ConditionRow) -> None:
        if row not in self._condition_rows:
            return
        self._condition_rows.remove(row)
        self._conditions_layout.removeWidget(row)
        row.deleteLater()
        self._apply_filter()

    def _reset_conditions(self) -> None:
        for row in list(self._condition_rows):
            self._conditions_layout.removeWidget(row)
            row.deleteLater()
        self._condition_rows.clear()
        self._add_condition_row()
        self._apply_filter()

    def _current_group(self) -> tuple[FilterGroup, int]:
        conditions: list[FilterCondition] = []
        invalid = 0
        for row in self._condition_rows:
            condition = row.condition()
            if condition is None:
                invalid += 1
                continue
            conditions.append(condition)
        return (
            FilterGroup(
                str(self.joiner_combo.currentData() or "AND"),
                tuple(conditions),
            ),
            invalid,
        )

    # ------------------------------------------------------------------
    # 筛选与预览
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        group, invalid = self._current_group()
        self._filtered_indices = filter_records(
            self._records, group
        )
        self._rebuild_preview()
        if invalid:
            self.filter_status.setText(
                f"{invalid} 条条件未填写完整，已忽略；"
                f"当前结果 {len(self._filtered_indices)} 条；"
                "默认仅勾选有账号内容图片的记录。"
            )
        else:
            self.filter_status.setText(
                f"应用条件后共 {len(self._filtered_indices)} 条记录；"
                "默认仅勾选有账号内容图片的记录。"
            )

    def _rebuild_preview(self) -> None:
        self._rebuilding = True
        try:
            self.table.setRowCount(len(self._filtered_indices))
            for row_index, original_index in enumerate(
                self._filtered_indices
            ):
                record = self._records[original_index]
                values = (
                    self._rows[original_index]
                    if original_index < len(self._rows)
                    else record.values
                )
                check_item = QTableWidgetItem("")
                check_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                has_images = record.has_images or bool(
                    record.screenshots
                )
                check_item.setCheckState(
                    Qt.CheckState.Checked
                    if has_images
                    else Qt.CheckState.Unchecked
                )
                check_item.setData(
                    Qt.ItemDataRole.UserRole, original_index
                )
                self.table.setItem(row_index, 0, check_item)

                for column, value in enumerate(
                    list(values)[: len(REQUIRED_COLUMNS)],
                    start=1,
                ):
                    text = self._display_value(value)
                    item = QTableWidgetItem(text)
                    item.setToolTip(text)
                    if column in (3, 4, 5, 6):
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight
                            | Qt.AlignmentFlag.AlignVCenter
                        )
                    self.table.setItem(row_index, column, item)

                status_text = record.listing_status or ""
                status_item = QTableWidgetItem(status_text)
                status_item.setToolTip(status_text)
                self.table.setItem(row_index, 7, status_item)

                image_count = len(record.image_items) or len(
                    record.screenshots
                )
                image_text = (
                    f"有 {image_count} 张" if has_images else "无"
                )
                image_item = QTableWidgetItem(image_text)
                image_item.setForeground(
                    QBrush(
                        QColor(
                            "#45e0a8" if has_images else "#f5c35a"
                        )
                    )
                )
                self.table.setItem(row_index, 8, image_item)
                self.table.setRowHeight(row_index, 28)
        finally:
            self._rebuilding = False
        self._update_counts()

    def _display_value(self, value: object) -> str:
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d")
        if isinstance(value, date):
            return value.strftime("%Y-%m-%d")
        if value is None:
            return ""
        return str(value)

    # ------------------------------------------------------------------
    # 选择
    # ------------------------------------------------------------------

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._rebuilding or item.column() != 0:
            return
        self._update_counts()

    def _set_all_checked(self, checked: bool) -> None:
        state = (
            Qt.CheckState.Checked
            if checked
            else Qt.CheckState.Unchecked
        )
        self._rebuilding = True
        try:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item is not None:
                    item.setCheckState(state)
        finally:
            self._rebuilding = False
        self._update_counts()

    def _select_with_images(self) -> None:
        self._rebuilding = True
        try:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item is None:
                    continue
                original_index = int(
                    item.data(Qt.ItemDataRole.UserRole)
                )
                record = self._records[original_index]
                has_images = record.has_images or bool(
                    record.screenshots
                )
                item.setCheckState(
                    Qt.CheckState.Checked
                    if has_images
                    else Qt.CheckState.Unchecked
                )
        finally:
            self._rebuilding = False
        self._update_counts()

    def _selected_indices(self) -> list[int]:
        selected: list[int] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            if item.checkState() != Qt.CheckState.Checked:
                continue
            selected.append(
                int(item.data(Qt.ItemDataRole.UserRole))
            )
        return selected

    def _update_counts(self) -> None:
        selected = self._selected_indices()
        with_images = sum(
            1
            for index in selected
            if (
                self._records[index].has_images
                or self._records[index].screenshots
            )
        )
        self.counts_label.setText(
            f"筛选结果 {len(self._filtered_indices)} · "
            f"已选 {len(selected)} · "
            f"有图片 {with_images} · "
            f"无图片 {len(selected) - with_images}"
        )
        self.confirm_btn.setEnabled(bool(selected))

    # ------------------------------------------------------------------
    # 确认
    # ------------------------------------------------------------------

    def _confirm(self) -> None:
        selected = self._selected_indices()
        if not selected:
            QMessageBox.warning(
                self, "没有选中记录", "请至少勾选一条记录。"
            )
            return
        selected = sorted(set(selected))
        rows = [
            self._rows[index]
            for index in selected
            if index < len(self._rows)
        ]
        records = [
            self._records[index]
            for index in selected
            if index < len(self._records)
        ]
        self._selected_data = FeishuTableData(
            rows=list(rows),
            total_records=self._data.total_records,
            source_name=self._data.source_name,
            page_url=self._data.page_url,
            headers=self._data.headers,
            records=tuple(records),
            temp_dir=self._data.temp_dir,
        )
        self.accept()

    def _collect_choice_values(self) -> dict[str, list[str]]:
        values: dict[str, list[str]] = {}
        for field, field_type in FIELD_TYPES.items():
            if field_type != "choice":
                continue
            seen: list[str] = []
            if field == "上架情况":
                for record in self._records:
                    text = (record.listing_status or "").strip()
                    if text and text not in seen:
                        seen.append(text)
            else:
                try:
                    index = REQUIRED_COLUMNS.index(field)
                except ValueError:
                    continue
                for record in self._records:
                    if index >= len(record.values):
                        continue
                    text = str(record.values[index] or "").strip()
                    if text and text not in seen:
                        seen.append(text)
            if field == "可不可二次":
                for value in ("是", "否"):
                    if value not in seen:
                        seen.append(value)
            values[field] = seen
        return values
