"""应用启动入口：创建 QApplication 与主窗口。"""

from __future__ import annotations

import sys

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from .constants import APP_NAME
from .theme import build_stylesheet
from .ui.main_window import MainWindow


def create_application(argv: list[str] | None = None) -> QApplication:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(build_stylesheet())
    app.setFont(QFont("Microsoft YaHei UI", 9))
    return app


def run(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    app = create_application(args)

    if "--smoke-test" in args:
        # 打包后的无界面冒烟测试：验证界面组件、表格依赖与 Playwright 驱动
        try:
            import xlrd  # noqa: F401
            from playwright.sync_api import sync_playwright

            window = MainWindow()  # noqa: F841
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True, channel="msedge"
                )
                browser.close()
        except Exception as exc:
            print(f"SMOKE FAILED: {exc}", file=sys.stderr)
            return 1
        print("SMOKE OK")
        return 0

    window = MainWindow()
    window.show()
    return app.exec()
