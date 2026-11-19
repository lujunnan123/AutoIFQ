"""手动询价窗口：独立商户与参数，共用主界面询问话术库。"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..constants import PARAMETER_FIELDS, SpinFieldSpec
from ..manual_inquiry import ManualInquiryRunner, ManualMerchantQuote
from ..settings import SettingsError, load_settings
from .card import Card
from .image_upload import ImageUploader
from .log_panel import LogPanel
from .merchant_selector import MerchantSelector

_QUOTE_COLORS = {
    "waiting": "#77899f",
    "running": "#79b4ff",
    "quoted": "#45e0a8",
    "no_quote": "#f5c35a",
    "error": "#ff8b9c",
}
_MANUAL_PARAMETER_KEYS = ("timeout_sec", "interval_sec")


class ManualInquiryWindow(QDialog):
    """一个独立的手动询价窗口，拥有自己的商户、参数和询价线程。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        merchants: Iterable[str] = (),
        phrase_provider: Callable[[], Iterable[str]] | None = None,
        account_file_provider: Callable[[], str | None] | None = None,
        window_number: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ManualInquiryWindow")
        self._window_number = window_number
        title = (
            f"手动询价 #{window_number}"
            if window_number is not None
            else "手动询价"
        )
        self.setWindowTitle(title)
        self._apply_screen_size()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._paste_dir = Path(
            tempfile.mkdtemp(prefix="autoifq_manual_")
        )

        merchant_values = tuple(merchants)
        self._phrase_provider = phrase_provider or (lambda: ())
        self._account_file_provider = account_file_provider or (lambda: None)

        self._runner: ManualInquiryRunner | None = None
        self._log_path: Path | None = None
        self._param_spins: dict[str, QSpinBox | QDoubleSpinBox] = {}
        self._pending_merchants: tuple[str, ...] | None = None
        self._syncing_merchants = False
        self._closing = False
        self._temp_cleaned = False

        self._build_ui(title)
        self._paste_shortcut = QShortcut(
            QKeySequence.StandardKey.Paste, self
        )
        self._paste_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self._paste_shortcut.activated.connect(self._paste_images)

        # 商户和参数完全由本窗口维护；打开时默认不勾选商户。
        self._syncing_merchants = True
        try:
            self.merchant_selector.set_merchants(
                merchant_values, ()
            )
        finally:
            self._syncing_merchants = False
        self._refresh_quote_rows()
        self._update_actions()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _apply_screen_size(self) -> None:
        """初始高度不超过当前屏幕可用区域。"""
        screen = QApplication.primaryScreen()
        if screen is None:
            self.setMinimumHeight(420)
            self.resize(1200, 700)
            return
        available = screen.availableGeometry()
        width = min(1200, max(960, available.width() - 60))
        height = min(600, max(420, available.height() - 70))
        self.setMinimumHeight(420)
        self.resize(width, height)

    def _build_ui(self, title_text: str) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("ManualBodyScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.viewport().setObjectName("ManualBodyViewport")

        host = QWidget()
        host.setObjectName("ManualBodyContent")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel(title_text)
        title.setObjectName("AppTitle")
        subtitle = QLabel("独立参数 · 话术共用 · TXT 领取手机号")
        subtitle.setObjectName("CardSub")
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("Ghost")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        header.addWidget(title)
        header.addWidget(
            subtitle, 0, Qt.AlignmentFlag.AlignBottom
        )
        header.addStretch(1)
        header.addWidget(
            close_btn, 0, Qt.AlignmentFlag.AlignVCenter
        )
        layout.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(10)
        content.addWidget(self._build_config_card(), 1)

        right_column = QWidget()
        right_column.setFixedWidth(380)
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        right_layout.addWidget(self._build_quote_card(), 0)
        self.log_panel = LogPanel(
            self,
            title="询价日志",
            subtitle="发送进度与商家回复",
            view_min_height=80,
        )
        right_layout.addWidget(self.log_panel, 1)
        content.addWidget(right_column, 0)
        layout.addLayout(content, 1)

        scroll.setWidget(host)
        outer.addWidget(scroll)

    def _build_config_card(self) -> Card:
        config_card = Card(
            "测试配置", "本窗口独立参数 · 询问话术共用", self
        )
        config_card.body.setContentsMargins(12, 10, 12, 10)
        config_card.body.setSpacing(6)

        self.merchant_selector = MerchantSelector(
            title="本次咨询商家",
            list_height=88,
        )
        self.merchant_selector.selectionChanged.connect(
            self._on_manual_selection_changed
        )
        config_card.body.addWidget(self.merchant_selector)

        config_card.body.addLayout(self._build_parameter_row())

        compact_hint = QLabel(
            "商户和参数仅本窗口生效；开始后从 TXT 领取 1 个手机号"
            "并删除该行。同级窗口领取其他号码，话术共用主界面。"
        )
        compact_hint.setObjectName("HintLabel")
        compact_hint.setWordWrap(True)
        config_card.body.addWidget(compact_hint)

        self.image_uploader = ImageUploader(
            self._paste_dir, self, compact=True
        )
        self.image_uploader.imagesChanged.connect(
            self._update_actions
        )
        self.image_uploader.message.connect(self._log)
        config_card.body.addWidget(self.image_uploader)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.start_btn = QPushButton("开始询价")
        self.start_btn.setObjectName("Primary")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setFixedHeight(34)
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._start_inquiry)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setFixedHeight(30)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_inquiry)

        self.status_label = QLabel("请选择截图与商户")
        self.status_label.setObjectName("HintLabel")
        self.status_label.setWordWrap(True)

        action_row.addWidget(self.start_btn)
        action_row.addWidget(self.stop_btn)
        action_row.addWidget(self.status_label, 1)
        config_card.body.addLayout(action_row)
        config_card.body.addStretch(1)
        return config_card

    def _build_parameter_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        specs = {spec.key: spec for spec in PARAMETER_FIELDS}
        for key in _MANUAL_PARAMETER_KEYS:
            spec = specs[key]
            field = QWidget()
            field_layout = QVBoxLayout(field)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(4)

            label = QLabel(spec.label)
            label.setObjectName("FieldLabel")

            spin = self._create_parameter_spin(spec)
            spin.setValue(spec.default)
            self._param_spins[key] = spin

            field_layout.addWidget(label)
            field_layout.addWidget(spin)
            row.addWidget(field, 1)
        return row

    @staticmethod
    def _create_parameter_spin(
        spec: SpinFieldSpec,
    ) -> QSpinBox | QDoubleSpinBox:
        if spec.decimals:
            spin: QSpinBox | QDoubleSpinBox = QDoubleSpinBox()
            spin.setDecimals(spec.decimals)
            spin.setSingleStep(spec.step)
            spin.setRange(float(spec.minimum), float(spec.maximum))
        else:
            spin = QSpinBox()
            spin.setRange(int(spec.minimum), int(spec.maximum))
        spin.setSuffix(spec.suffix)
        spin.setToolTip(spec.tip)
        spin.setMinimumHeight(28)
        spin.setKeyboardTracking(False)
        return spin

    def _build_quote_card(self) -> Card:
        quote_card = Card(
            "实时报价", "本窗口商户与商家评估报价", self
        )
        quote_card.setFixedWidth(380)
        self.quote_table = QTableWidget(0, 2)
        self.quote_table.setObjectName("ManualQuoteTable")
        self.quote_table.setHorizontalHeaderLabels(["商户", "实时报价"])
        self.quote_table.verticalHeader().setVisible(False)
        self.quote_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.quote_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.quote_table.setShowGrid(False)
        self.quote_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self.quote_table.horizontalHeader()
        header.setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        header.setSectionResizeMode(
            1, QHeaderView.ResizeMode.Fixed
        )
        self.quote_table.setColumnWidth(1, 130)
        self.quote_table.setMinimumHeight(140)
        quote_card.body.addWidget(self.quote_table, 1)
        return quote_card

    # ------------------------------------------------------------------
    # 商户选择（仅本窗口）
    # ------------------------------------------------------------------

    def set_available_merchants(
        self, merchants: Iterable[str]
    ) -> None:
        """同步主界面获取到的商家名称，但保留本窗口的勾选状态。"""
        values = tuple(
            dict.fromkeys(
                name.strip()
                for name in merchants
                if isinstance(name, str) and name.strip()
            )
        )
        if self.is_busy():
            self._pending_merchants = values
            return
        if values == self.merchant_selector.merchants():
            return

        selected = self.merchant_selector.selected_merchants()
        self._syncing_merchants = True
        try:
            self.merchant_selector.set_merchants(values, selected)
        finally:
            self._syncing_merchants = False
        self._refresh_quote_rows()
        self._update_actions()

    def _on_manual_selection_changed(self) -> None:
        if self._syncing_merchants:
            return
        self._refresh_quote_rows()
        self._update_actions()

    def selected_merchants(self) -> tuple[str, ...]:
        return self.merchant_selector.selected_merchants()

    # ------------------------------------------------------------------
    # 实时报价表
    # ------------------------------------------------------------------

    def _refresh_quote_rows(self) -> None:
        selected = self.merchant_selector.selected_merchants()
        if not selected:
            self.quote_table.setRowCount(1)
            name_item = QTableWidgetItem("请选择商户")
            value_item = QTableWidgetItem("--")
            value_item.setForeground(
                QBrush(QColor(_QUOTE_COLORS["waiting"]))
            )
            self.quote_table.setItem(0, 0, name_item)
            self.quote_table.setItem(0, 1, value_item)
            return

        self.quote_table.setRowCount(len(selected))
        for row, merchant in enumerate(selected):
            name_item = QTableWidgetItem(merchant)
            name_item.setToolTip(merchant)
            value_item = QTableWidgetItem("待询价")
            value_item.setForeground(
                QBrush(QColor(_QUOTE_COLORS["waiting"]))
            )
            value_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter
            )
            self.quote_table.setItem(row, 0, name_item)
            self.quote_table.setItem(row, 1, value_item)

    def _set_quote_status(
        self, merchant: str, text: str, color_key: str
    ) -> None:
        for row in range(self.quote_table.rowCount()):
            item = self.quote_table.item(row, 0)
            if item is None or item.text() != merchant:
                continue
            value_item = self.quote_table.item(row, 1)
            if value_item is None:
                value_item = QTableWidgetItem()
                self.quote_table.setItem(row, 1, value_item)
            value_item.setText(text)
            value_item.setForeground(
                QBrush(QColor(_QUOTE_COLORS[color_key]))
            )
            return

    def _mark_unfinished_quotes(self, text: str) -> None:
        for row in range(self.quote_table.rowCount()):
            value_item = self.quote_table.item(row, 1)
            if value_item is None:
                continue
            if value_item.text() in (
                "待询价",
                "询价中…",
                "发送中…",
                "已发送 · 等回复",
            ):
                value_item.setText(text)
                value_item.setForeground(
                    QBrush(QColor(_QUOTE_COLORS["waiting"]))
                )

    # ------------------------------------------------------------------
    # 截图
    # ------------------------------------------------------------------

    def _paste_images(self) -> None:
        if self.is_busy():
            return
        self.image_uploader.paste_from_clipboard()

    # ------------------------------------------------------------------
    # 询价
    # ------------------------------------------------------------------

    def _update_actions(self) -> None:
        running = self.is_busy()
        has_merchants = bool(
            self.merchant_selector.selected_merchants()
        )
        self.start_btn.setEnabled(
            not running
            and self.image_uploader.count() > 0
            and has_merchants
        )
        self.stop_btn.setEnabled(running)
        self.merchant_selector.setEnabled(not running)
        self.image_uploader.setEnabled(not running)
        for spin in self._param_spins.values():
            spin.setEnabled(not running)

    def _start_inquiry(self) -> None:
        if self.is_busy():
            return
        merchants = list(self.merchant_selector.selected_merchants())
        if not merchants:
            self._log("请先勾选至少一个商户。", "warn")
            return
        image_paths = [
            Path(path) for path in self.image_uploader.image_paths()
        ]
        if not image_paths:
            self._log("请先添加至少一张账号截图。", "warn")
            return
        account_file = self._account_file_provider()
        if not account_file or not Path(account_file).is_file():
            self._log(
                "请先在主界面上传账号 TXT 清单。", "warn"
            )
            self._set_status("缺少账号 TXT")
            return

        try:
            settings = load_settings()
        except SettingsError as exc:
            self._log(str(exc), "error")
            self._set_status("配置缺失")
            return

        try:
            phrases = tuple(
                phrase.strip()
                for phrase in self._phrase_provider()
                if isinstance(phrase, str) and phrase.strip()
            )
        except Exception as exc:
            self._log(f"读取共用询问话术失败：{exc}", "error")
            self._set_status("询问话术读取失败")
            return
        if not phrases:
            self._log(
                "主界面询问话术库为空，本次使用默认话术。", "warn"
            )

        timeout = float(self._param_spins["timeout_sec"].value())
        interval = float(self._param_spins["interval_sec"].value())

        self._refresh_quote_rows()
        self._log(
            f"账号清单：{Path(account_file).name}；"
            "本窗口开始后领取 1 个手机号并从清单中删除。",
            "info",
        )
        self._log(
            f"本窗口独立参数：单次超时 {timeout:g} 秒 · "
            f"操作间隔 {interval:g} 秒；商户 {len(merchants)} 个；"
            f"截图 {len(image_paths)} 张；询问话术与主界面共用"
            f"（{len(phrases)} 条）。",
            "info",
        )

        runner = ManualInquiryRunner(
            settings,
            account_file,
            merchants,
            image_paths,
            phrases,
            timeout,
            interval,
            self._log_path,
            self,
        )
        runner.log_message.connect(self._log)
        runner.merchant_started.connect(self._on_merchant_started)
        runner.merchant_sent.connect(self._on_merchant_sent)
        runner.merchant_quote.connect(self._on_merchant_quote)
        runner.status_message.connect(self._set_status)
        runner.completed.connect(self._on_completed)
        runner.finished.connect(self._on_runner_finished)
        self._runner = runner
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.merchant_selector.setEnabled(False)
        self.image_uploader.setEnabled(False)
        for spin in self._param_spins.values():
            spin.setEnabled(False)
        self._set_status("询价中 · 正在从 TXT 领取手机号…")
        runner.start()

    def _on_merchant_started(self, merchant: str) -> None:
        self._set_quote_status(merchant, "发送中…", "running")

    def _on_merchant_sent(self, merchant: str) -> None:
        self._set_quote_status(
            merchant, "已发送 · 等回复", "running"
        )

    def _on_merchant_quote(self, quote: object) -> None:
        if not isinstance(quote, ManualMerchantQuote):
            return
        if quote.log_path is not None:
            self._log_path = quote.log_path
        if quote.price is not None:
            self._set_quote_status(
                quote.merchant, f"¥{quote.price:g}", "quoted"
            )
            self._log(
                f"商户「{quote.merchant}」报价：{quote.price:g}",
                "success",
            )
        elif quote.status == "已取消":
            self._set_quote_status(
                quote.merchant, "已取消", "waiting"
            )
        elif quote.status == "已咨询过":
            self._set_quote_status(
                quote.merchant, "已咨询过", "no_quote"
            )
        elif quote.error:
            self._set_quote_status(
                quote.merchant, "失败", "error"
            )
        else:
            self._set_quote_status(
                quote.merchant, "未报价", "no_quote"
            )
            self._log(
                f"商户「{quote.merchant}」未识别到报价。", "warn"
            )

    def _on_completed(self, success: bool, summary: str) -> None:
        self._set_status(summary)
        if "停止" in summary:
            self._mark_unfinished_quotes("已取消")
        else:
            self._mark_unfinished_quotes("未执行")

    def _on_runner_finished(self) -> None:
        runner = self._runner
        self._runner = None
        if runner is not None:
            runner.deleteLater()
        pending = self._pending_merchants
        self._pending_merchants = None
        self._mark_unfinished_quotes("已结束")
        self._update_actions()
        if pending is not None:
            self.set_available_merchants(pending)
        if self._closing:
            QTimer.singleShot(0, self.close)

    def _stop_inquiry(self) -> None:
        if self._runner is None or not self._runner.isRunning():
            return
        self._runner.cancel()
        self.stop_btn.setEnabled(False)
        self._set_status("正在停止…")
        self._log("已请求停止手动询价。", "warn")

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _log(self, message: str, level: str = "info") -> None:
        self.log_panel.append(message, level)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def is_busy(self) -> bool:
        return self._runner is not None

    def cleanup(self) -> None:
        if self._temp_cleaned:
            return
        self._temp_cleaned = True
        shutil.rmtree(self._paste_dir, ignore_errors=True)

    def shutdown(self) -> None:
        self._closing = True
        runner = self._runner
        if runner is not None:
            runner.cancel()
            if runner.wait(120000):
                self._runner = None
                runner.deleteLater()
        self.cleanup()
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.is_busy():
            self._closing = True
            self._runner.cancel()
            self._set_status("正在停止询价，完成后窗口关闭…")
            self._log("正在停止询价并关闭窗口…", "warn")
            event.ignore()
            return
        self.cleanup()
        super().closeEvent(event)
