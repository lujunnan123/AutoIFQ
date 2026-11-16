"""主窗口：组合各个面板并驱动螃蟹上号任务。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ..constants import (
    APP_VERSION,
    DEFAULT_WINDOW_SIZE,
    MIN_WINDOW_SIZE,
    SIDE_PANEL_WIDTH,
    StepStatus,
    WINDOW_TITLE,
)
from ..feishu_login import FeishuLoginRunner
from ..models import RunParams, RunState
from ..runner import LoginRunner
from ..services.accounts import AccountParseError, read_accounts
from ..services.feishu_common import feishu_logged_in
from ..services.parameter_store import ParameterStore, ParameterStoreError
from ..services.phrase_store import PhraseStore, PhraseStoreError
from ..settings import SettingsError, load_settings
from ..utils import fmt_size
from .action_panel import ActionPanel
from .header_bar import HeaderBar
from .log_panel import LogPanel
from .manual_test_window import ManualTestWindow
from .parameter_panel import ParameterPanel
from .phrase_panel import PhrasePanel
from .progress_panel import ProgressPanel
from .upload_panel import UploadPanel


class MainWindow(QMainWindow):
    def __init__(
        self,
        phrase_store: PhraseStore | None = None,
        parameter_store: ParameterStore | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*DEFAULT_WINDOW_SIZE)
        self.setMinimumSize(*MIN_WINDOW_SIZE)

        # 面板
        self.header = HeaderBar()
        self.upload_panel = UploadPanel()
        self.progress_panel = ProgressPanel()
        self.log_panel = LogPanel()
        self.parameter_panel = ParameterPanel()
        self.phrase_panel = PhrasePanel()
        self.action_panel = ActionPanel()
        self._manual_test_window: ManualTestWindow | None = None
        self._feishu_login_runner: FeishuLoginRunner | None = None

        self._phrase_store = phrase_store or PhraseStore()
        self._phrase_store_error: str | None = None
        self._phrase_save_error_logged = False
        self._loaded_phrase_count = 0
        self._load_phrases()

        self._parameter_store = parameter_store or ParameterStore()
        self._parameter_store_error: str | None = None
        self._parameter_save_error_logged = False
        self._loaded_parameter_count = 0
        self._load_parameters()

        self.runner: LoginRunner | None = None
        self._run_state = RunState.IDLE
        self._login_summary_received = False
        self._build_result: tuple[bool, str] | None = None

        self._build_ui()
        self._connect_signals()

        self.action_panel.set_state(RunState.IDLE)
        self._refresh_feishu_chip()
        self.set_status("就绪 · 等待导入账号清单")
        self.log(
            "AutoIFQ 界面已加载，请导入账号清单（.txt），"
            "并确认右上角飞书登录状态后开始。",
            "accent",
        )
        if self._loaded_phrase_count:
            self.log(
                f"已加载 {self._loaded_phrase_count} 条询问话术。", "muted"
            )
        if self._phrase_store_error:
            self.log(
                f"询问话术读取失败：{self._phrase_store_error}", "warn"
            )
        if self._loaded_parameter_count:
            self.log(
                f"已加载 {self._loaded_parameter_count} 项运行参数。", "muted"
            )
        if self._parameter_store_error:
            self.log(
                f"运行参数读取失败：{self._parameter_store_error}", "warn"
            )

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 18, 24, 16)
        outer.setSpacing(16)

        outer.addWidget(self.header)

        content = QHBoxLayout()
        content.setSpacing(16)
        content.addLayout(self._build_left_column(), 1)
        content.addWidget(self._build_right_column())
        outer.addLayout(content, 1)

        self._build_status_bar()

    def _build_left_column(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(16)
        column.addWidget(self.upload_panel)
        column.addWidget(self.progress_panel)
        column.addWidget(self.log_panel, 1)
        return column

    def _build_right_column(self) -> QWidget:
        container = QWidget()
        container.setObjectName("SidePanel")
        container.setFixedWidth(SIDE_PANEL_WIDTH)

        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(16)
        column.addWidget(self.parameter_panel)
        column.addWidget(self.phrase_panel)
        column.addWidget(self.action_panel)
        column.addStretch(1)
        return container

    def _build_status_bar(self) -> None:
        status = self.statusBar()
        self._status_label = QLabel()
        self._status_label.setObjectName("StatusText")
        status.addWidget(self._status_label, 1)

        version = QLabel(APP_VERSION)
        version.setObjectName("StatusVersion")
        status.addPermanentWidget(version)
        status.setSizeGripEnabled(False)

    # ------------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.upload_panel.fileLoaded.connect(self._on_file_loaded)
        self.upload_panel.fileRejected.connect(self._on_file_rejected)
        self.upload_panel.fileCleared.connect(self._on_file_cleared)
        self.upload_panel.manualTestRequested.connect(
            self._open_manual_test
        )
        self.header.feishu_clicked.connect(self._start_feishu_login)

        self.action_panel.start_requested.connect(self._start)
        self.action_panel.pause_requested.connect(self._toggle_pause)
        self.action_panel.stop_requested.connect(self._stop)

        self.phrase_panel.phrasesChanged.connect(self._save_phrases)
        self.parameter_panel.valuesChanged.connect(self._save_parameters)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def update_thread_step(
        self,
        thread_id: int,
        step_index: int,
        *,
        progress: float = 0.0,
        status: str = StepStatus.RUNNING,
        detail: str = "",
    ) -> None:
        """供后端调用：更新某个线程的指定步骤。"""
        self.progress_panel.update_thread_step(
            thread_id,
            step_index,
            progress=progress,
            status=status,
            detail=detail,
        )

    def collect_params(self) -> RunParams:
        """读取当前界面的全部运行参数。"""
        return self.parameter_panel.build_params(self.phrase_panel.phrases())

    def set_status(self, text: str) -> None:
        self._status_label.setText(text)

    def log(self, message: str, level: str = "info") -> None:
        self.log_panel.append(message, level)

    # ------------------------------------------------------------------
    # 文件事件
    # ------------------------------------------------------------------

    def _on_file_loaded(self, path: str, size: int) -> None:
        self.log(
            f"已导入账号清单：{Path(path).name}（{fmt_size(size)}）", "success"
        )
        try:
            accounts = read_accounts(path)
            default_count = sum(
                account.password_is_default for account in accounts
            )
            self.log(
                f"清单中识别到 {len(accounts)} 个账号"
                f"（{default_count} 个仅手机号，将使用默认密码）",
                "info",
            )
            if self._feishu_state_present():
                self.set_status("文件已就绪 · 可以开始")
            else:
                self.set_status(
                    f"账号清单已就绪 · 共 {len(accounts)} 个账号 · "
                    "请先点击右上角登录飞书"
                )
        except AccountParseError as exc:
            self.log(str(exc), "warn")
            self.set_status("账号清单已导入 · 未识别到账号")

    def _on_file_rejected(self, message: str, level: str) -> None:
        self.log(message, level)
        QMessageBox.warning(self, "无法导入文件", message)

    def _on_file_cleared(self) -> None:
        self.log("已移除账号清单。", "info")
        self.set_status("就绪 · 等待导入账号清单")

    # ------------------------------------------------------------------
    # 手动测试
    # ------------------------------------------------------------------

    def _open_manual_test(self) -> None:
        if self._manual_test_window is not None:
            self._manual_test_window.raise_()
            self._manual_test_window.activateWindow()
            return

        window = ManualTestWindow(self)
        window.destroyed.connect(
            lambda: setattr(self, "_manual_test_window", None)
        )
        self._manual_test_window = window
        window.show()
        self.log("已打开手动测试界面。", "info")

    # ------------------------------------------------------------------
    # 飞书登录
    # ------------------------------------------------------------------

    def _feishu_state_present(self) -> bool:
        try:
            settings = load_settings()
        except SettingsError:
            return False
        return feishu_logged_in(settings.feishu)

    def _refresh_feishu_chip(self) -> None:
        if self._feishu_state_present():
            self.header.set_feishu_status("飞书已登录", "online")
        else:
            self.header.set_feishu_status("飞书未登录", "offline")

    def _start_feishu_login(self) -> None:
        if (
            self._feishu_login_runner is not None
            and self._feishu_login_runner.isRunning()
        ):
            self.log("飞书登录正在进行中，请在浏览器中扫码。", "warn")
            return
        if self.runner is not None and self.runner.isRunning():
            self.log("询价任务运行中，请先停止任务再登录飞书。", "warn")
            return

        try:
            settings = load_settings()
        except SettingsError as exc:
            self.log(str(exc), "error")
            QMessageBox.warning(self, "配置缺失", str(exc))
            return

        self.header.set_feishu_status("登录中…", "logging")
        self.log(
            "正在启动飞书二维码登录，稍后请在浏览器中扫码…", "accent"
        )
        self.set_status("飞书登录中 · 请在浏览器中扫码")

        runner = FeishuLoginRunner(settings, self)
        runner.log_message.connect(self.log)
        runner.status_changed.connect(self._on_feishu_status)
        runner.completed.connect(self._on_feishu_completed)
        runner.finished.connect(self._on_feishu_runner_finished)
        self._feishu_login_runner = runner
        runner.start()

    def _on_feishu_status(self, state: str) -> None:
        if state == "logging":
            self.header.set_feishu_status("登录中…", "logging")
        elif state == "logged_in":
            self.header.set_feishu_status("飞书已登录", "online")
        elif state == "error":
            self.header.set_feishu_status("飞书未登录", "offline")

    def _on_feishu_completed(self, success: bool, detail: str) -> None:
        if success:
            self.header.set_feishu_status("飞书已登录", "online")
            self.log(f"执行结果：{detail}", "success")
            self.set_status(f"飞书已登录 · {detail}")
        else:
            self.header.set_feishu_status("飞书未登录", "offline")
            self.set_status("飞书登录失败 · 查看运行日志")

    def _on_feishu_runner_finished(self) -> None:
        runner = self._feishu_login_runner
        self._feishu_login_runner = None
        if runner is not None:
            runner.deleteLater()

    # ------------------------------------------------------------------
    # 询问话术持久化
    # ------------------------------------------------------------------

    def _load_phrases(self) -> None:
        phrases: list[str] = []
        try:
            phrases = self._phrase_store.load()
        except PhraseStoreError as exc:
            self._phrase_store_error = str(exc)
        self._loaded_phrase_count = len(phrases)
        self.phrase_panel.set_phrases(phrases)

    def _save_phrases(self) -> None:
        try:
            self._phrase_store.save(self.phrase_panel.phrases())
            self._phrase_save_error_logged = False
        except PhraseStoreError as exc:
            if not self._phrase_save_error_logged:
                self.log(f"询问话术保存失败：{exc}", "error")
                self._phrase_save_error_logged = True

    # ------------------------------------------------------------------
    # 运行参数持久化
    # ------------------------------------------------------------------

    def _load_parameters(self) -> None:
        values: dict[str, float] = {}
        try:
            values = self._parameter_store.load()
        except ParameterStoreError as exc:
            self._parameter_store_error = str(exc)
        self._loaded_parameter_count = len(values)
        self.parameter_panel.apply_values(values)

    def _save_parameters(self) -> None:
        try:
            self._parameter_store.save(self.parameter_panel.values())
            self._parameter_save_error_logged = False
        except ParameterStoreError as exc:
            if not self._parameter_save_error_logged:
                self.log(f"运行参数保存失败：{exc}", "error")
                self._parameter_save_error_logged = True

    # ------------------------------------------------------------------
    # 运行控制
    # ------------------------------------------------------------------

    def _start(self) -> None:
        if self.runner is not None and self.runner.isRunning():
            return
        if (
            self._feishu_login_runner is not None
            and self._feishu_login_runner.isRunning()
        ):
            self.log("请先在浏览器中完成飞书扫码登录。", "warn")
            return

        file_path = self.upload_panel.current_file()
        if not file_path:
            self.upload_panel.flash()
            self.log("请先导入账号清单（TXT）后再开始。", "warn")
            self.set_status("缺少文件 · 请导入账号清单")
            return

        try:
            settings = load_settings()
        except SettingsError as exc:
            self.log(str(exc), "error")
            QMessageBox.warning(self, "配置缺失", str(exc))
            return

        if not feishu_logged_in(settings.feishu):
            self.header.set_feishu_status("飞书未登录", "offline")
            self.log(
                "请先点击右上角「飞书未登录」完成二维码登录，"
                "再开始构建表格。",
                "warn",
            )
            self.set_status("缺少飞书登录 · 请点击右上角登录")
            return

        try:
            accounts = read_accounts(
                file_path, settings.login.default_password
            )
        except AccountParseError as exc:
            self.log(str(exc), "error")
            QMessageBox.warning(self, "账号解析失败", str(exc))
            self.set_status("清单中没有可用账号")
            return

        params = self.collect_params()
        threads = max(1, min(params.threads, len(accounts)))

        self.progress_panel.reset()
        self.progress_panel.set_build_status(
            "running", "正在读取飞书多维表格…"
        )
        self.progress_panel.set_chip("构建中", "running")
        self._set_run_state(RunState.RUNNING)

        self.set_status("运行中 · 正在读取飞书表格并构建")

        self._login_summary_received = False
        self._build_result = None
        self.runner = LoginRunner(accounts, threads, settings, self)
        self.runner.log_message.connect(self.log)
        self.runner.build_status.connect(self._on_build_status)
        self.runner.build_result.connect(self._on_build_result)
        self.runner.thread_added.connect(self._on_thread_added)
        self.runner.thread_step.connect(self._on_thread_step)
        self.runner.thread_finished.connect(self._on_thread_finished)
        self.runner.summary.connect(self._on_login_summary)
        self.runner.finished.connect(self._on_runner_finished)
        self.runner.start()

    def _toggle_pause(self) -> None:
        if self.runner is None or not self.runner.isRunning():
            return
        if self._run_state is RunState.RUNNING:
            self.runner.pause()
            self._set_run_state(RunState.PAUSED)
            self.progress_panel.set_chip("已暂停", "paused")
            self.log("已请求暂停；正在进行的请求会先完成。", "warn")
            self.set_status("已暂停 · 可继续或停止")
        elif self._run_state is RunState.PAUSED:
            self.runner.resume()
            self._set_run_state(RunState.RUNNING)
            self.progress_panel.set_chip("运行中", "running")
            self.log("继续执行。", "info")
            self.set_status("运行中 · 正在执行线程任务")

    def _stop(self) -> None:
        if self.runner is None or not self.runner.isRunning():
            return
        if self._run_state not in (RunState.RUNNING, RunState.PAUSED):
            return
        self.runner.cancel()
        self.action_panel.pause_btn.setEnabled(False)
        self.action_panel.stop_btn.setEnabled(False)
        self.log("正在停止…（等待当前请求结束）", "warn")
        self.set_status("正在停止…")

    def _set_run_state(self, state: RunState) -> None:
        self._run_state = state
        self.action_panel.set_state(state)

    # ------------------------------------------------------------------
    # 任务事件
    # ------------------------------------------------------------------

    def _on_build_status(self, state: str, detail: str) -> None:
        self.progress_panel.set_build_status(state, detail)
        if state == "running":
            self.progress_panel.set_chip("构建中", "running")
            self.set_status("正在构建表格…")
        elif state == "done":
            self.progress_panel.set_chip("运行中", "running")
            self.set_status("构建表格完成 · 正在展开线程…")
        elif state == "error":
            self.progress_panel.set_chip("构建表格失败", "error")
            self.set_status("构建表格失败 · 查看日志")

    def _on_build_result(self, success: bool, detail: str) -> None:
        self._build_result = (success, detail)
        if success:
            self.set_status(f"构建表格完成 · {Path(detail).name}")
            return

        if "飞书" in detail and "登录" in detail:
            self.header.set_feishu_status("飞书未登录", "offline")
            self.log(
                "飞书登录状态不可用，请点击右上角重新扫码登录。",
                "warn",
            )
        self.set_status("构建表格失败 · 查看日志")

    def _on_thread_added(self, thread_id: int, label: str) -> None:
        self.progress_panel.add_thread(thread_id, label)
        self.set_status("运行中 · 正在执行线程任务")

    def _on_thread_step(
        self,
        thread_id: int,
        step_index: int,
        progress: float,
        status: str,
        detail: str,
    ) -> None:
        self.progress_panel.update_thread_step(
            thread_id,
            step_index,
            progress=progress,
            status=status,
            detail=detail,
        )
        self.set_status("运行中 · 正在执行线程任务")

    def _on_thread_finished(
        self, thread_id: int, success: bool, detail: str
    ) -> None:
        self.progress_panel.remove_thread(thread_id)
        outcome = "完成" if success else "失败"
        self.set_status(f"线程 {thread_id} {outcome} · 继续后续任务")

    def _on_login_summary(self, success: int, total: int, cancelled: bool) -> None:
        self._login_summary_received = True

        if cancelled:
            self.progress_panel.reset()
            self.progress_panel.set_chip("已停止", "idle")
            self._set_run_state(RunState.IDLE)
            self.set_status("已停止 · 等待重新开始")
            return

        self._set_run_state(RunState.DONE)
        build_ok = (
            self._build_result is not None and self._build_result[0]
        )
        self.progress_panel.clear_threads()
        if self._build_result is not None and not build_ok:
            self.progress_panel.set_chip("构建表格失败", "error")
            self.progress_panel.set_thread_message(
                "构建表格失败，线程未执行", final=True
            )
            self.set_status("构建表格失败 · 线程未执行")
            return

        if success > 0:
            self.progress_panel.set_chip("上号完成", "done")
            self.progress_panel.set_thread_message(
                f"所有线程已完成 · 成功 {success}/{total} 个账号",
                final=True,
            )
            if build_ok:
                self.set_status(
                    f"完成 · 成功 {success}/{total} 个账号 · 表格已生成"
                )
            else:
                self.set_status(f"上号完成 · 成功 {success}/{total}")
        else:
            self.progress_panel.set_chip("上号失败", "error")
            self.progress_panel.set_thread_message(
                f"所有线程已结束 · 成功 0/{total}", final=True
            )
            if build_ok:
                self.set_status("表格已生成 · 上号失败")
            else:
                self.set_status(f"上号结束 · 0/{total} 登录成功")

    def _on_runner_finished(self) -> None:
        runner = self.runner
        self.runner = None
        if runner is not None:
            runner.deleteLater()

        if not self._login_summary_received:
            self.log("任务异常结束，未收到结果。", "error")
            self.progress_panel.reset()
            self.progress_panel.set_chip("已停止", "idle")
            self._set_run_state(RunState.IDLE)
            self.set_status("任务已结束")

    # ------------------------------------------------------------------
    # 关闭窗口
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_phrases()
        self._save_parameters()
        if self.runner is not None and self.runner.isRunning():
            self.runner.cancel()
            self.runner.wait(35000)
        if (
            self._feishu_login_runner is not None
            and self._feishu_login_runner.isRunning()
        ):
            self._feishu_login_runner.cancel()
            self._feishu_login_runner.wait(7000)
        super().closeEvent(event)
