"""螃蟹账号登录与咨询商家获取后台任务。"""

from __future__ import annotations

import threading

from PyQt6.QtCore import QThread, pyqtSignal

from .services.pxb7_merchant import (
    Pxb7MerchantCancelled,
    Pxb7MerchantService,
)
from .settings import AppSettings


class Pxb7LoginRunner(QThread):
    log_message = pyqtSignal(str, str)
    status_changed = pyqtSignal(str)  # logging / logged_in / error
    merchants_loaded = pyqtSignal(list)
    completed = pyqtSignal(bool, str)

    def __init__(
        self,
        settings: AppSettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        self.status_changed.emit("logging")
        try:
            result = Pxb7MerchantService(
                self._settings, self._log
            ).fetch(self._cancel)
            merchants = list(result.merchants)
            if not merchants:
                raise RuntimeError("未获取到咨询商家。")
            self.merchants_loaded.emit(merchants)
            source = (
                "已保存的登录状态"
                if result.used_saved_state
                else "重新登录"
            )
            message = (
                f"已获取 {len(merchants)} 个三角洲行动咨询商家"
                f"（{source}）"
            )
            self._log(f"执行结果：{message}", "success")
            self.status_changed.emit("logged_in")
            self.completed.emit(True, message)
        except Pxb7MerchantCancelled as exc:
            self._log(str(exc), "warn")
            self.status_changed.emit("error")
            self.completed.emit(False, str(exc))
        except Exception as exc:
            message = str(exc)
            self._log(f"螃蟹登录失败：{message}", "error")
            self.status_changed.emit("error")
            self.completed.emit(False, message)

    def _log(self, message: str, level: str = "info") -> None:
        self.log_message.emit(message, level)
