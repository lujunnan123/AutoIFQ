"""手动询价窗口：多图上传，TXT 手机号 + 代理登录并展示实时报价。"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..manual_inquiry import ManualInquiryRunner, ManualMerchantQuote
from ..models import RunParams
from ..services.accounts import AccountParseError, read_accounts
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


class ManualInquiryWindow(QDialog):
    merchantSelectionChanged = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        merchant_provider: Callable[[], tuple[str, ...]] | None = None,
        selected_merchant_provider: (
            Callable[[], tuple[str, ...]] | None
        ) = None,
        params_provider: Callable[[], RunParams] | None = None,
        account_file_provider: Callable[[], str | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ManualInquiryWindow")
        self.setWindowTitle("手动询价")
        self.resize(1200, 900)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._paste_dir = Path(
            tempfile.mkdtemp(prefix="autoifq_manual_")
        )

        self._merchant_provider = merchant_provider or (lambda: ())
        self._selected_merchant_provider = (
            selected_merchant_provider or (lambda: ())
        )
        self._params_provider = params_provider or (
            lambda: RunParams(
                threads=1,
                interval_sec=3.0,
                timeout_sec=90,
                retries=0,
                merchants=(),
                phrases=(),
            )
        )
        self._account_file_provider = account_file_provider or (lambda: None)

        self._runner: ManualInquiryRunner | None = None
        self._log_path: Path | None = None
        self._syncing_merchants = False
        self._closing = False
        self._temp_cleaned = False

        self._build_ui()
        self._paste_shortcut = QShortcut(
            QKeySequence.StandardKey.Paste, self
        )
        self._paste_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self._paste_shortcut.activated.connect(self._paste_images)
        self.sync_merchants_from_main()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        title = QLabel("手动询价")
        title.setObjectName("AppTitle")
        subtitle = QLabel(
            "上传账号截图，选择商户；使用 TXT 手机号和随机代理登录，"
            "复用主界面的超时与询问话术执行询价。"
        )
        subtitle.setObjectName("CardSub")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        top_row.addWidget(self._build_config_card(), 1)
        top_row.addWidget(self._build_quote_card(), 0)
        layout.addLayout(top_row)

        self.log_panel = LogPanel(
            self,
            title="询价日志",
            subtitle="手机号登录、商家回复与截图评估报价",
        )
        layout.addWidget(self.log_panel, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("Ghost")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

    def _build_config_card(self) -> Card:
        config_card = Card(
            "测试配置", "指定商户、账号截图与账号清单", self
        )
        config_card.body.setSpacing(10)

        self.merchant_selector = MerchantSelector(
            title="指定商户"
        )
        self.merchant_selector.selectionChanged.connect(
            self._on_manual_selection_changed
        )
        config_card.body.addWidget(self.merchant_selector)

        self.image_uploader = ImageUploader(self._paste_dir, self)
        self.image_uploader.imagesChanged.connect(
            self._update_actions
        )
        self.image_uploader.message.connect(self._log)
        config_card.body.addWidget(self.image_uploader)

        account_hint = QLabel(
            "手机号来自主界面已导入的 TXT 账号清单；"
            "右上角螃蟹账号仅用于获取商户名称。"
        )
        account_hint.setObjectName("HintLabel")
        account_hint.setWordWrap(True)
        config_card.body.addWidget(account_hint)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.start_btn = QPushButton("开始询价")
        self.start_btn.setObjectName("Primary")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setFixedHeight(42)
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._start_inquiry)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setFixedHeight(38)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_inquiry)

        self.status_label = QLabel("请选择截图与商户")
        self.status_label.setObjectName("HintLabel")
        self.status_label.setWordWrap(True)

        action_row.addWidget(self.start_btn)
        action_row.addWidget(self.stop_btn)
        action_row.addWidget(self.status_label, 1)
        config_card.body.addLayout(action_row)
        return config_card

    def _build_quote_card(self) -> Card:
        quote_card = Card(
            "实时报价", "商户与商家评估报价", self
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
        self.quote_table.setMinimumHeight(220)
        quote_card.body.addWidget(self.quote_table, 1)
        return quote_card

    # ------------------------------------------------------------------
    # 商户选择同步
    # ------------------------------------------------------------------

    def sync_merchants_from_main(self) -> None:
        if self._syncing_merchants or self.is_busy():
            return
        try:
            merchants = self._merchant_provider()
            selected = self._selected_merchant_provider()
        except Exception as exc:
            self._log(f"同步主界面商户失败：{exc}", "error")
            return
        self._syncing_merchants = True
        try:
            self.merchant_selector.set_merchants(merchants, selected)
        finally:
            self._syncing_merchants = False
        self._refresh_quote_rows()
        self._update_actions()

    def _on_manual_selection_changed(self) -> None:
        if self._syncing_merchants:
            return
        self._refresh_quote_rows()
        self._update_actions()
        self.merchantSelectionChanged.emit()

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
            if value_item.text() in ("待询价", "询价中…"):
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
        if not account_file:
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
            accounts = read_accounts(
                account_file, settings.login.default_password
            )
        except AccountParseError as exc:
            self._log(str(exc), "error")
            self._set_status("账号清单解析失败")
            return
        if not accounts:
            self._log("账号 TXT 中没有可用手机号。", "error")
            self._set_status("账号清单为空")
            return

        try:
            params = self._params_provider()
        except Exception as exc:
            self._log(f"读取主界面运行参数失败：{exc}", "error")
            return
        phrases = tuple(params.phrases)
        if not phrases:
            self._log(
                "主界面询问话术为空，本次使用默认话术。", "warn"
            )

        self._refresh_quote_rows()
        self._log(
            f"账号清单：{Path(account_file).name}，"
            f"{len(accounts)} 个手机号；"
            f"商户 {len(merchants)} 个；截图 {len(image_paths)} 张。",
            "info",
        )

        runner = ManualInquiryRunner(
            settings,
            accounts,
            merchants,
            image_paths,
            phrases,
            float(params.timeout_sec),
            int(params.threads),
            float(params.interval_sec),
            self._log_path,
            self,
        )
        runner.log_message.connect(self._log)
        runner.merchant_started.connect(self._on_merchant_started)
        runner.merchant_quote.connect(self._on_merchant_quote)
        runner.status_message.connect(self._set_status)
        runner.completed.connect(self._on_completed)
        runner.finished.connect(self._on_runner_finished)
        self._runner = runner
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.merchant_selector.setEnabled(False)
        self.image_uploader.setEnabled(False)
        self._set_status("询价中 · 正在登录 TXT 手机号…")
        runner.start()

    def _on_merchant_started(self, merchant: str) -> None:
        self._set_quote_status(merchant, "询价中…", "running")

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
        self._update_actions()
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
