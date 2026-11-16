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
from ..models import RunParams, RunState
from ..runner import LoginRunner
from ..services.accounts import AccountParseError, read_accounts
from ..settings import SettingsError, load_settings
from ..utils import fmt_size
from .action_panel import ActionPanel
from .header_bar import HeaderBar
from .log_panel import LogPanel
from .parameter_panel import ParameterPanel
from .phrase_panel import PhrasePanel
from .progress_panel import ProgressPanel
from .upload_panel import UploadPanel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*DEFAULT_WINDOW_SIZE)
        self.setMinimumSize(*MIN_WINDOW_SIZE)

        # 面板
        self.upload_panel = UploadPanel()
        self.progress_panel = ProgressPanel()
        self.log_panel = LogPanel()
        self.parameter_panel = ParameterPanel()
        self.phrase_panel = PhrasePanel()
        self.action_panel = ActionPanel()

        self.runner: LoginRunner | None = None
        self._run_state = RunState.IDLE
        self._login_summary_received = False
        self._table_result: tuple[bool, str] | None = None

        self._build_ui()
        self._connect_signals()

        self.action_panel.set_state(RunState.IDLE)
        self.set_status("就绪 · 等待导入账号清单和源表格")
        self.log(
            "AutoIFQ 界面已加载，请导入账号清单（.txt）和源表格（Excel）后开始。",
            "accent",
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

        outer.addWidget(HeaderBar())

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
        self.upload_panel.excelLoaded.connect(self._on_excel_loaded)
        self.upload_panel.excelRejected.connect(self._on_excel_rejected)
        self.upload_panel.excelCleared.connect(self._on_excel_cleared)

        self.action_panel.start_requested.connect(self._start)
        self.action_panel.pause_requested.connect(self._toggle_pause)
        self.action_panel.stop_requested.connect(self._stop)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def update_step(
        self,
        index: int,
        *,
        progress: float | None = None,
        status: str | None = None,
        detail: str | None = None,
    ) -> None:
        """更新指定步骤：status 取 pending / running / done / error。"""
        self.progress_panel.set_step(
            index, progress=progress, status=status, detail=detail
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
            if self.upload_panel.excel_file():
                self.set_status("文件已就绪 · 可以开始")
            else:
                self.set_status(
                    f"账号清单已就绪 · 共 {len(accounts)} 个账号 · 等待源表格"
                )
        except AccountParseError as exc:
            self.log(str(exc), "warn")
            self.set_status("账号清单已导入 · 未识别到账号")

    def _on_file_rejected(self, message: str, level: str) -> None:
        self.log(message, level)
        QMessageBox.warning(self, "无法导入文件", message)

    def _on_file_cleared(self) -> None:
        self.log("已移除账号清单。", "info")
        if self.upload_panel.excel_file():
            self.set_status("源表格已就绪 · 等待账号清单")
        else:
            self.set_status("就绪 · 等待导入账号清单和源表格")

    def _on_excel_loaded(self, path: str, size: int) -> None:
        self.log(
            f"已导入源表格：{Path(path).name}（{fmt_size(size)}）", "success"
        )
        if self.upload_panel.current_file():
            self.set_status("文件已就绪 · 可以开始")
        else:
            self.set_status("源表格已就绪 · 等待账号清单")

    def _on_excel_rejected(self, message: str, level: str) -> None:
        self.log(message, level)
        QMessageBox.warning(self, "无法导入源表格", message)

    def _on_excel_cleared(self) -> None:
        self.log("已移除源表格。", "info")
        if self.upload_panel.current_file():
            self.set_status("账号清单已就绪 · 等待源表格")
        else:
            self.set_status("就绪 · 等待导入账号清单和源表格")

    # ------------------------------------------------------------------
    # 运行控制
    # ------------------------------------------------------------------

    def _start(self) -> None:
        if self.runner is not None and self.runner.isRunning():
            return

        file_path = self.upload_panel.current_file()
        excel_path = self.upload_panel.excel_file()
        if not file_path or not excel_path:
            missing: list[str] = []
            if not file_path:
                self.upload_panel.flash()
                missing.append("账号清单（TXT）")
            if not excel_path:
                self.upload_panel.flash_excel()
                missing.append("源表格（Excel）")
            self.log(f"请先导入{'、'.join(missing)}后再开始。", "warn")
            self.set_status("缺少文件 · 请同时导入账号清单和源表格")
            return

        try:
            settings = load_settings()
        except SettingsError as exc:
            self.log(str(exc), "error")
            QMessageBox.warning(self, "配置缺失", str(exc))
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
        self.progress_panel.set_step(
            0,
            status=StepStatus.RUNNING,
            progress=0.0,
            detail=f"准备登录 {len(accounts)} 个账号",
        )
        self.progress_panel.set_chip("上号中", "running")
        self._set_run_state(RunState.RUNNING)

        self.set_status("运行中 · 正在登录螃蟹平台")

        self._login_summary_received = False
        self._table_result = None
        self.runner = LoginRunner(
            accounts, threads, settings, excel_path, self
        )
        self.runner.log_message.connect(self.log)
        self.runner.step_progress.connect(self._on_login_progress)
        self.runner.step_done.connect(self._on_login_step_done)
        self.runner.table_result.connect(self._on_table_result)
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
            self.progress_panel.set_chip("上号中", "running")
            self.log("继续执行。", "info")
            self.set_status("运行中 · 正在登录螃蟹平台")

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

    def _on_login_progress(self, index: int, progress: float, detail: str) -> None:
        self.progress_panel.set_step(
            index,
            progress=progress,
            status=StepStatus.RUNNING,
            detail=detail,
        )

    def _on_login_step_done(self, index: int, success: bool, detail: str) -> None:
        self.progress_panel.set_step(
            index,
            progress=100.0,
            status=StepStatus.DONE if success else StepStatus.ERROR,
            detail=detail,
        )

    def _on_table_result(self, success: bool, detail: str) -> None:
        self._table_result = (success, detail)
        if success:
            self.set_status(f"表格已生成 · {Path(detail).name}")
        else:
            self.set_status("构建表格失败 · 查看日志")

    def _on_login_summary(self, success: int, total: int, cancelled: bool) -> None:
        self._login_summary_received = True

        if cancelled:
            self.progress_panel.reset()
            self.progress_panel.set_chip("已停止", "idle")
            self._set_run_state(RunState.IDLE)
            self.set_status("已停止 · 等待重新开始")
            return

        self._set_run_state(RunState.DONE)
        if success > 0:
            if self._table_result is not None:
                table_ok, detail = self._table_result
                if table_ok:
                    self.progress_panel.set_chip("表格已生成", "done")
                    self.set_status(
                        f"上号完成 · 表格已生成（{Path(detail).name}）"
                    )
                else:
                    self.progress_panel.set_chip("构建表格失败", "error")
                    self.set_status("上号完成 · 构建表格失败")
            else:
                self.progress_panel.set_chip("上号完成", "done")
                self.set_status(f"上号完成 · 成功 {success}/{total}")
        else:
            self.progress_panel.set_chip("上号失败", "error")
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
        if self.runner is not None and self.runner.isRunning():
            self.runner.cancel()
            self.runner.wait(35000)
        super().closeEvent(event)
