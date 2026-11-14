"""通用小工具。"""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget


def fmt_size(size: int) -> str:
    """把字节数格式化为易读的文件大小。"""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.2f} MB"


def repolish(widget: QWidget) -> None:
    """动态属性变化后刷新 QSS 样式。"""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
