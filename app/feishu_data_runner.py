"""自动询价前置：先读取飞书数据，交给筛选窗口确认。"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from .services.feishu_table import (
    FeishuLoginRequired,
    FeishuTableClient,
    FeishuTableError,
)
from .settings import AppSettings


class FeishuDataRunner(QThread):
    """读取当前视图的全部可用记录，不直接构建询价表。"""

    log_message = pyqtSignal(str, str)
    data_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            data = FeishuTableClient(
                self._settings.feishu, self._log
            ).fetch_records(
                limit=0,
                download_images=False,
                fetch_all=True,
            )
        except FeishuLoginRequired as exc:
            self.failed.emit(str(exc))
            return
        except FeishuTableError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # 防御性兜底
            self.failed.emit(f"读取飞书数据异常：{exc}")
            return

        if self._cancel.is_set():
            self._cleanup(data.temp_dir)
            return
        self.data_ready.emit(data)

    def _cleanup(self, temp_dir: Path | None) -> None:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _log(self, message: str, level: str = "info") -> None:
        self.log_message.emit(message, level)
