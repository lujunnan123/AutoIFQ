"""代理设置对话框：接口地址、获取数量与连通性测试。"""

from __future__ import annotations

from urllib.parse import urlsplit

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..services.proxy_provider import (
    ProxyEndpoint,
    ProxySettings,
    ProxyStore,
    ProxyStoreError,
    fetch_proxies,
)


class ProxyTestThread(QThread):
    finished_result = pyqtSignal(bool, object, str)

    def __init__(
        self,
        settings: ProxySettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings

    def run(self) -> None:
        try:
            proxies = fetch_proxies(self._settings)
            self.finished_result.emit(True, proxies, "")
        except Exception as exc:
            self.finished_result.emit(False, [], str(exc))


class ProxySettingsDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        store: ProxyStore | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ProxySettingsDialog")
        self.setWindowTitle("代理设置")
        self.resize(760, 580)
        self._store = store or ProxyStore()
        self._test_thread: ProxyTestThread | None = None
        self._close_pending = False
        self.saved_settings: ProxySettings | None = None
        self._load_error: str | None = None

        self._settings = ProxySettings()
        try:
            self._settings = self._store.load()
        except ProxyStoreError as exc:
            self._load_error = str(exc)

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        title = QLabel("代理设置")
        title.setObjectName("AppTitle")
        subtitle = QLabel(
            "子线程登录螃蟹账号和聊天时使用随机代理；"
            "飞书登录与右上角螃蟹商家登录保持直连。"
        )
        subtitle.setObjectName("CardSub")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.enable_check = QCheckBox("启用子线程代理")
        self.enable_check.setObjectName("ProxyCheck")
        self.enable_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.enable_check.setChecked(self._settings.enabled)
        layout.addWidget(self.enable_check)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.url_edit = QLineEdit(self._settings.api_url)
        self.url_edit.setObjectName("ProxyUrlEdit")
        self.url_edit.setPlaceholderText(
            "http://代理接口地址?num=5&time=30..."
        )
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.setMinimumHeight(34)

        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 50)
        self.count_spin.setValue(self._settings.fetch_count)
        self.count_spin.setSuffix(" 个")
        self.count_spin.setMinimumHeight(32)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(3, 120)
        self.timeout_spin.setValue(int(self._settings.timeout_sec))
        self.timeout_spin.setSuffix(" 秒")
        self.timeout_spin.setMinimumHeight(32)

        form.addRow(self._label("代理接口地址"), self.url_edit)

        count_row = QWidget()
        count_layout = QHBoxLayout(count_row)
        count_layout.setContentsMargins(0, 0, 0, 0)
        count_layout.setSpacing(10)
        count_layout.addWidget(self.count_spin)
        count_layout.addWidget(self._label("请求超时"))
        count_layout.addWidget(self.timeout_spin)
        count_layout.addStretch(1)
        form.addRow(self._label("每次获取数量"), count_row)
        layout.addLayout(form)

        test_row = QHBoxLayout()
        test_row.setSpacing(10)
        self.test_btn = QPushButton("测试获取")
        self.test_btn.setObjectName("GhostStrong")
        self.test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.test_btn.clicked.connect(self._test_fetch)
        self.status_label = QLabel("")
        self.status_label.setObjectName("ProxyStatus")
        self.status_label.setWordWrap(True)
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.status_label, 1)
        layout.addLayout(test_row)

        self.result_edit = QPlainTextEdit()
        self.result_edit.setObjectName("ProxyResult")
        self.result_edit.setReadOnly(True)
        self.result_edit.setPlaceholderText(
            "测试成功后在这里显示获取到的代理 IP"
        )
        self.result_edit.setFixedHeight(150)
        layout.addWidget(self.result_edit)

        hint = QLabel(
            "提示：代理接口请求本身为直连。若接口返回“请先添加白名单”，"
            "请把运行程序的公网 IP 加入代理服务商白名单。"
            "子线程的易盾验证、协议登录和聊天会使用同一代理。"
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        if self._load_error:
            self.status_label.setText(
                f"代理设置读取失败：{self._load_error}"
            )

        layout.addStretch(1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.close_btn = QPushButton("关闭")
        self.close_btn.setObjectName("Ghost")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.close)
        self.save_btn = QPushButton("保存")
        self.save_btn.setObjectName("Primary")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.clicked.connect(self._save)
        button_row.addWidget(self.close_btn)
        button_row.addWidget(self.save_btn)
        layout.addLayout(button_row)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    # ------------------------------------------------------------------
    # 测试 / 保存
    # ------------------------------------------------------------------

    def _current_settings(self) -> ProxySettings:
        return ProxySettings(
            enabled=self.enable_check.isChecked(),
            api_url=self.url_edit.text().strip(),
            fetch_count=self.count_spin.value(),
            timeout_sec=float(self.timeout_spin.value()),
        )

    def _test_fetch(self) -> None:
        if self._test_thread is not None and self._test_thread.isRunning():
            return
        settings = self._current_settings()
        if not settings.api_url:
            self.status_label.setText("请先填写代理接口地址。")
            return

        self.test_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.status_label.setText("正在请求代理接口…")
        self.result_edit.clear()

        thread = ProxyTestThread(settings, self)
        thread.finished_result.connect(self._on_test_result)
        thread.finished.connect(self._on_test_thread_finished)
        self._test_thread = thread
        thread.start()

    def _on_test_result(
        self,
        success: bool,
        proxies: object,
        error: str,
    ) -> None:
        items = proxies if isinstance(proxies, list) else []
        if success:
            self.status_label.setText(
                f"获取成功：{len(items)} 个代理 IP"
            )
            lines = []
            for index, proxy in enumerate(items, start=1):
                if isinstance(proxy, ProxyEndpoint):
                    lines.append(
                        f"{index}. {proxy.server}"
                        + (" · 需要认证" if proxy.username else "")
                    )
            self.result_edit.setPlainText("\n".join(lines))
        else:
            self.status_label.setText(f"获取失败：{error}")
            self.result_edit.setPlainText(error)

    def _on_test_thread_finished(self) -> None:
        self.test_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        thread = self._test_thread
        self._test_thread = None
        if thread is not None:
            thread.deleteLater()
        if self._close_pending:
            self._close_pending = False
            QTimer.singleShot(0, self.close)

    def _save(self) -> None:
        if self._test_thread is not None and self._test_thread.isRunning():
            self.status_label.setText("正在获取代理，请稍候…")
            return
        settings = self._current_settings()
        if settings.enabled:
            if not settings.api_url:
                self.status_label.setText(
                    "启用代理时必须填写代理接口地址。"
                )
                return
            try:
                parts = urlsplit(settings.api_url)
            except ValueError:
                self.status_label.setText("代理接口地址格式不正确。")
                return
            if parts.scheme not in ("http", "https") or not parts.netloc:
                self.status_label.setText(
                    "代理接口地址必须是合法的 http(s) 地址。"
                )
                return

        try:
            self._store.save(settings)
        except ProxyStoreError as exc:
            self.status_label.setText(f"保存失败：{exc}")
            return

        self.saved_settings = settings
        self.accept()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._test_thread is not None and self._test_thread.isRunning():
            self._close_pending = True
            self.status_label.setText(
                "正在获取代理，完成后窗口会自动关闭…"
            )
            event.ignore()
            return
        super().closeEvent(event)
