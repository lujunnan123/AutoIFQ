"""全局「点击外部」监听，供输入控件做失焦确认。"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QApplication


class ClickOutsideFilter(QObject):
    """鼠标在界面任意位置按下时回调，由调用方判断是否命中编辑控件外部。"""

    def __init__(
        self,
        on_click: Callable[[object], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_click = on_click
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.MouseButtonPress:
            self._on_click(obj)
        return False
