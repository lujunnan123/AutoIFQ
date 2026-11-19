"""深色主题：全局样式表与数字输入框箭头资源。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap


def _ensure_arrow_assets() -> tuple[str, str]:
    """生成数字输入框使用的上下箭头图标，返回图标文件路径。"""
    cache_dir = Path(tempfile.gettempdir()) / "autoifq_ui_assets"
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []

    for name, pointing_up in (("up", True), ("down", False)):
        icon_path = cache_dir / f"spin_{name}.png"
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#93a8c1"), 3.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        arrow = QPainterPath()
        if pointing_up:
            arrow.moveTo(9, 20)
            arrow.lineTo(16, 13)
            arrow.lineTo(23, 20)
        else:
            arrow.moveTo(9, 13)
            arrow.lineTo(16, 20)
            arrow.lineTo(23, 13)
        painter.drawPath(arrow)
        painter.end()

        pixmap.save(str(icon_path), "PNG")
        paths.append(icon_path.as_posix())

    return paths[0], paths[1]


STYLE_SHEET = """
* {
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    outline: none;
}
QMainWindow, QWidget#Root, QWidget#SidePanel {
    background-color: #0b1017;
}
QLabel {
    color: #dce6f3;
    background: transparent;
}
QFrame#Card {
    background-color: #111823;
    border: 1px solid #1d2836;
    border-radius: 14px;
}

/* ---------- 顶部 ---------- */
QLabel#AppLogo {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #3f84ff, stop:1 #22b8a2);
    border-radius: 13px;
    color: #ffffff;
    font-size: 21px;
    font-weight: 800;
}
QLabel#AppTitle {
    color: #f3f8ff;
    font-size: 23px;
    font-weight: 800;
    letter-spacing: 0.5px;
}
QLabel#TitleSep {
    color: #3c4d63;
    font-size: 18px;
}
QLabel#AppSubTitle {
    color: #c0cedf;
    font-size: 15px;
    font-weight: 600;
}
QLabel#AppSub {
    color: #687b91;
    font-size: 11px;
}
QPushButton#FeishuChip, QPushButton#Pxb7Chip {
    border-radius: 10px;
    padding: 6px 14px;
    font-size: 11px;
    font-weight: 700;
}
QPushButton#FeishuChip[state="offline"], QPushButton#Pxb7Chip[state="offline"] {
    color: #93a4ba;
    background-color: rgba(147, 164, 186, 18);
    border: 1px solid rgba(147, 164, 186, 55);
}
QPushButton#FeishuChip[state="offline"]:hover,
QPushButton#Pxb7Chip[state="offline"]:hover {
    color: #c7d5e6;
    background-color: rgba(147, 164, 186, 32);
    border-color: rgba(147, 164, 186, 90);
}
QPushButton#FeishuChip[state="logging"], QPushButton#Pxb7Chip[state="logging"] {
    color: #79b4ff;
    background-color: rgba(63, 132, 255, 28);
    border: 1px solid rgba(63, 132, 255, 90);
}
QPushButton#FeishuChip[state="online"], QPushButton#Pxb7Chip[state="online"] {
    color: #45e0a8;
    background-color: rgba(46, 204, 143, 24);
    border: 1px solid rgba(46, 204, 143, 72);
}
QPushButton#FeishuChip[state="online"]:hover,
QPushButton#Pxb7Chip[state="online"]:hover {
    color: #7cf0c4;
    background-color: rgba(46, 204, 143, 36);
    border-color: rgba(46, 204, 143, 105);
}
QPushButton#FeishuChip[state="error"], QPushButton#Pxb7Chip[state="error"] {
    color: #ff8b9c;
    background-color: rgba(255, 93, 115, 24);
    border: 1px solid rgba(255, 93, 115, 72);
}
QLabel#CardTitle {
    color: #edf4fd;
    font-size: 14px;
    font-weight: 700;
}
QLabel#CardSub {
    color: #64778e;
    font-size: 11px;
}
QLabel#FieldLabel {
    color: #91a3b9;
    font-size: 12px;
}
QLabel#FieldSaved {
    color: #3fe0a4;
    font-size: 11px;
    font-weight: 700;
}
QLabel#MetaLabel {
    color: #77899f;
    font-size: 11px;
}
QLabel#HintLabel {
    color: #5b6d82;
    font-size: 11px;
}
QLabel#OverallPercent {
    color: #a9c8ff;
    font-size: 12px;
    font-weight: 700;
}

/* ---------- 状态胶囊 ---------- */
QLabel#StatusChip {
    font-size: 11px;
    font-weight: 700;
    padding: 4px 12px;
    border-radius: 10px;
}
QLabel#StatusChip[state="idle"] {
    color: #93a4ba;
    background-color: rgba(147, 164, 186, 20);
    border: 1px solid rgba(147, 164, 186, 55);
}
QLabel#StatusChip[state="running"] {
    color: #79b4ff;
    background-color: rgba(63, 132, 255, 32);
    border: 1px solid rgba(63, 132, 255, 90);
}
QLabel#StatusChip[state="paused"] {
    color: #f5c35a;
    background-color: rgba(245, 195, 90, 26);
    border: 1px solid rgba(245, 195, 90, 72);
}
QLabel#StatusChip[state="done"] {
    color: #45e0a8;
    background-color: rgba(46, 204, 143, 26);
    border: 1px solid rgba(46, 204, 143, 72);
}
QLabel#StatusChip[state="error"] {
    color: #ff8b9c;
    background-color: rgba(255, 93, 115, 26);
    border: 1px solid rgba(255, 93, 115, 72);
}

/* ---------- 询价进度 / 线程 ---------- */
QFrame#BuildRow {
    background-color: #0d141d;
    border: 1px solid #223043;
    border-radius: 9px;
}
QLabel#BuildTitle {
    color: #dfe9f5;
    font-size: 12px;
    font-weight: 600;
}
QLabel#BuildDetail {
    color: #77899f;
    font-size: 11px;
}
QLabel#SectionTitle {
    color: #c9d8e8;
    font-size: 12px;
    font-weight: 600;
}
QLabel#ThreadEmpty {
    color: #5b6d82;
    font-size: 11px;
}
QScrollArea#ThreadScroll,
QWidget#ThreadViewport,
QWidget#ThreadList {
    background: transparent;
    border: none;
}
QFrame#ThreadRow {
    background: transparent;
    border: none;
    border-bottom: 1px solid #1d2836;
}
QFrame#ThreadRow:hover {
    background-color: #0f1723;
}
QLabel#ThreadTitle {
    color: #e7eef8;
    font-size: 12px;
    font-weight: 700;
}
QLabel#ThreadPhone {
    color: #77899f;
    font-size: 11px;
}
QLabel#ThreadStepName {
    color: #a9b8ca;
    font-size: 11px;
}
QLabel#ThreadStepStatus {
    color: #77899f;
    font-size: 10px;
}
QLabel#ThreadMeta {
    color: #5f7186;
    font-size: 10px;
}
QLabel#ThreadPercent {
    color: #a9c8ff;
    font-size: 10px;
    font-weight: 700;
}
QLabel#StepDot {
    font-size: 10px;
}
QLabel#StepDot[state="pending"] {
    color: #3b4c61;
}
QLabel#StepDot[state="running"] {
    color: #4f8cff;
}
QLabel#StepDot[state="done"] {
    color: #2ecc8f;
}
QLabel#StepDot[state="error"] {
    color: #ff5d73;
}
QLabel#MiniChip {
    font-size: 10px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 8px;
}
QLabel#MiniChip[state="idle"] {
    color: #93a4ba;
    background-color: rgba(147, 164, 186, 18);
    border: 1px solid rgba(147, 164, 186, 45);
}
QLabel#MiniChip[state="running"] {
    color: #79b4ff;
    background-color: rgba(63, 132, 255, 26);
    border: 1px solid rgba(63, 132, 255, 70);
}
QLabel#MiniChip[state="done"] {
    color: #45e0a8;
    background-color: rgba(46, 204, 143, 22);
    border: 1px solid rgba(46, 204, 143, 60);
}
QLabel#MiniChip[state="error"] {
    color: #ff8b9c;
    background-color: rgba(255, 93, 115, 22);
    border: 1px solid rgba(255, 93, 115, 60);
}
QProgressBar#ThreadBar {
    background-color: #121924;
    border: 1px solid #1d2836;
    border-radius: 3px;
}
QProgressBar#ThreadBar::chunk {
    border-radius: 2px;
    background-color: #3f84ff;
}
QProgressBar#ThreadBar[status="done"]::chunk {
    background-color: #2ecc8f;
}
QProgressBar#ThreadBar[status="error"]::chunk {
    background-color: #ff5d73;
}
QProgressBar#ThreadBar[status="running"]::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #3f84ff, stop:1 #35d6c0);
}
QProgressBar#ThreadBar[status="idle"]::chunk {
    background-color: #2b3a4d;
}

/* ---------- 拖放区 ---------- */
QFrame#DropZone {
    background-color: #0d141d;
    border: 1px dashed #27364a;
    border-radius: 12px;
}
QFrame#DropZone:hover {
    border-color: #365072;
    background-color: #0f1723;
}
QFrame#DropZone[dragActive="true"] {
    border: 1px solid #3f84ff;
    background-color: rgba(63, 132, 255, 26);
}
QLabel#DropIcon {
    background-color: rgba(63, 132, 255, 28);
    border: 1px solid rgba(63, 132, 255, 66);
    border-radius: 21px;
    color: #6ea8ff;
    font-size: 21px;
    font-weight: 700;
    padding-bottom: 2px;
}
QLabel#DropTitle {
    color: #dfe9f5;
    font-size: 13px;
    font-weight: 600;
}
QLabel#FileBadge {
    background-color: rgba(63, 132, 255, 30);
    border: 1px solid rgba(63, 132, 255, 70);
    border-radius: 10px;
    color: #7db4ff;
    font-size: 10px;
    font-weight: 800;
}
QLabel#FileName {
    color: #e9f1fb;
    font-size: 13px;
    font-weight: 700;
}
QLabel#FileMeta {
    color: #77899f;
    font-size: 11px;
}

/* ---------- 输入控件 ---------- */
QSpinBox, QDoubleSpinBox {
    background-color: #0b121b;
    border: 1px solid #223043;
    border-radius: 8px;
    padding: 5px 32px 5px 10px;
    color: #dbe6f3;
    font-size: 12px;
    selection-background-color: #2f6fd0;
    selection-color: #ffffff;
}
QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: #2d4058;
}
QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #3f84ff;
    background-color: #0c141f;
}
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 24px;
    height: 16px;
    background: transparent;
    border-left: 1px solid #1d2a3a;
    border-top-right-radius: 7px;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 24px;
    height: 16px;
    background: transparent;
    border-left: 1px solid #1d2a3a;
    border-bottom-right-radius: 7px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: rgba(63, 132, 255, 28);
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url("@ARROW_UP@");
    width: 9px;
    height: 9px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url("@ARROW_DOWN@");
    width: 9px;
    height: 9px;
}
QPlainTextEdit#TemplateEdit {
    background-color: #0b121b;
    border: 1px solid #223043;
    border-radius: 9px;
    padding: 8px;
    color: #c6d5e6;
    font-size: 12px;
    selection-background-color: #2f6fd0;
    selection-color: #ffffff;
}
QPlainTextEdit#TemplateEdit:focus {
    border-color: #3f84ff;
}
QPlainTextEdit#LogView {
    background-color: #0a1018;
    border: 1px solid #1b2634;
    border-radius: 10px;
    padding: 8px;
    color: #93a7bd;
    font-family: "Cascadia Mono", "Consolas", "Microsoft YaHei UI";
    font-size: 11px;
    selection-background-color: #264a78;
    selection-color: #ffffff;
}

/* ---------- 按钮 ---------- */
QPushButton {
    background-color: #182230;
    border: 1px solid #26344a;
    border-radius: 9px;
    padding: 7px 14px;
    color: #d7e3f2;
    font-size: 12px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #1f2c3e;
    border-color: #33455e;
}
QPushButton:pressed {
    background-color: #141d29;
}
QPushButton:disabled {
    color: #55657a;
    background-color: #141b25;
    border-color: #1e2836;
}
QPushButton#Primary {
    background-color: #3f84ff;
    border: 1px solid #3f84ff;
    border-radius: 10px;
    color: #ffffff;
    font-size: 13px;
    font-weight: 700;
    padding: 10px 16px;
}
QPushButton#Primary:hover {
    background-color: #5595ff;
    border-color: #5595ff;
}
QPushButton#Primary:pressed {
    background-color: #306fe0;
    border-color: #306fe0;
}
QPushButton#Primary:disabled {
    background-color: #1b2b45;
    border-color: #1b2b45;
    color: #5d769b;
}
QPushButton#Secondary {
    background-color: #16202c;
    border-color: #28374d;
}
QPushButton#Danger {
    background-color: #1d151a;
    border-color: #46242e;
    color: #ff8b9c;
}
QPushButton#Danger:hover {
    background-color: #291920;
    border-color: #63313e;
}
QPushButton#Danger:disabled {
    color: #6b4650;
    background-color: #171114;
    border-color: #2c1a20;
}
QPushButton#Ghost {
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 500;
    color: #8fa2b8;
    background-color: transparent;
    border: 1px solid #243043;
    border-radius: 7px;
}
QPushButton#Ghost:hover {
    color: #cfe0f2;
    border-color: #34465d;
    background-color: #16202c;
}
QPushButton#GhostStrong {
    padding: 7px 16px;
    font-size: 12px;
    font-weight: 600;
    color: #9dc5ff;
    background-color: rgba(63, 132, 255, 22);
    border: 1px solid rgba(63, 132, 255, 70);
    border-radius: 8px;
}
QPushButton#GhostStrong:hover {
    color: #cfe3ff;
    background-color: rgba(63, 132, 255, 38);
    border-color: rgba(63, 132, 255, 110);
}
QPushButton#GhostDanger {
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 500;
    color: #ff8b9c;
    background-color: transparent;
    border: 1px solid #3a2229;
    border-radius: 7px;
}
QPushButton#GhostDanger:hover {
    color: #ffb1bd;
    background-color: #24161b;
    border-color: #5a2b36;
}
QPushButton#GhostDanger:disabled {
    color: #5a3a42;
    background-color: transparent;
    border-color: #2a1c21;
}
QPushButton#ManualInquiryButton {
    background-color: #0d141d;
    border: 1px dashed #2c4058;
    border-radius: 12px;
    color: #9dc5ff;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#ManualInquiryButton:hover {
    background-color: #0f1723;
    border-color: #3f84ff;
    color: #cfe3ff;
}
QPushButton#ManualInquiryButton:pressed {
    background-color: #0b121a;
}

/* ---------- 代理设置 ---------- */
QDialog#ProxySettingsDialog {
    background-color: #0b1017;
}
QLineEdit#ProxyUrlEdit {
    background-color: #0b121b;
    border: 1px solid #223043;
    border-radius: 8px;
    padding: 6px 10px;
    color: #dbe6f3;
    font-size: 12px;
    selection-background-color: #2f6fd0;
    selection-color: #ffffff;
}
QLineEdit#ProxyUrlEdit:focus {
    border-color: #3f84ff;
    background-color: #0c141f;
}
QPlainTextEdit#ProxyResult {
    background-color: #0a1018;
    border: 1px solid #1b2634;
    border-radius: 10px;
    padding: 8px;
    color: #93a7bd;
    font-family: "Cascadia Mono", "Consolas", "Microsoft YaHei UI";
    font-size: 11px;
    selection-background-color: #264a78;
    selection-color: #ffffff;
}
QCheckBox#ProxyCheck {
    color: #c6d5e6;
    font-size: 12px;
    spacing: 8px;
    background: transparent;
}
QCheckBox#ProxyCheck::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #2d4058;
    border-radius: 4px;
    background-color: #0b121b;
}
QCheckBox#ProxyCheck::indicator:checked {
    background-color: #3f84ff;
    border-color: #3f84ff;
}
QLabel#ProxyStatus {
    color: #8fa2b8;
    font-size: 11px;
}

/* ---------- 手动询价窗口 ---------- */
QDialog#ManualInquiryWindow {
    background-color: #0b1017;
}
QScrollArea#ManualBodyScroll,
QWidget#ManualBodyViewport,
QWidget#ManualBodyContent {
    background: transparent;
    border: none;
}
QComboBox#ManualMerchant {
    background-color: #0b121b;
    border: 1px solid #223043;
    border-radius: 8px;
    padding: 5px 10px;
    color: #dbe6f3;
    font-size: 12px;
}
QComboBox#ManualMerchant:hover {
    border-color: #2d4058;
}
QComboBox#ManualMerchant:focus {
    border-color: #3f84ff;
}
QComboBox#ManualMerchant:disabled {
    color: #55657a;
    background-color: #101720;
}
QComboBox#ManualMerchant::drop-down {
    border: none;
    width: 24px;
}
QComboBox#ManualMerchant QAbstractItemView {
    background-color: #111823;
    border: 1px solid #223043;
    color: #dbe6f3;
    selection-background-color: #2f6fd0;
    selection-color: #ffffff;
    outline: 0;
    padding: 4px;
}
QLabel#ManualImagePreview {
    background-color: #0d141d;
    border: 1px dashed #27364a;
    border-radius: 10px;
    color: #5b6d82;
    font-size: 11px;
}
QFrame#ImageDropArea {
    background-color: #0d141d;
    border: 1px dashed #27364a;
    border-radius: 10px;
}
QFrame#ImageDropArea:hover {
    border-color: #365072;
    background-color: #0f1723;
}
QFrame#ImageDropArea[dragActive="true"] {
    border: 1px solid #3f84ff;
    background-color: rgba(63, 132, 255, 26);
}
QLabel#GhostStrongText {
    color: #9dc5ff;
    font-size: 12px;
    font-weight: 600;
}
QListWidget#ManualImageList {
    background-color: #0b121b;
    border: 1px solid #1b2634;
    border-radius: 9px;
    padding: 4px;
    color: #c6d5e6;
    font-size: 11px;
}
QListWidget#ManualImageList::item {
    color: #c6d5e6;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 4px;
}
QListWidget#ManualImageList::item:hover {
    background-color: #0f1723;
    border-color: #223043;
}
QListWidget#ManualImageList::item:selected {
    background-color: rgba(63, 132, 255, 34);
    border-color: #3f84ff;
    color: #ffffff;
}
QTableWidget#ManualQuoteTable {
    background-color: #0b121b;
    border: 1px solid #1b2634;
    border-radius: 9px;
    color: #dce6f3;
    font-size: 12px;
    gridline-color: #1b2634;
}
QTableWidget#ManualQuoteTable::item {
    padding: 6px 8px;
    border-bottom: 1px solid #1b2634;
}
QTableWidget#ManualQuoteTable QHeaderView::section {
    background-color: #111823;
    color: #91a3b9;
    border: none;
    border-bottom: 1px solid #223043;
    padding: 6px 8px;
    font-size: 11px;
    font-weight: 600;
}

/* ---------- 询问话术列表 ---------- */
QScrollArea#PhraseScroll,
QWidget#PhraseViewport,
QWidget#PhraseList {
    background: transparent;
    border: none;
}
QFrame#PhraseRow {
    background-color: #0b121b;
    border: 1px solid #223043;
    border-radius: 9px;
}
QFrame#PhraseRow:hover {
    border-color: #2d4058;
}
QFrame#PhraseRow[selected="true"] {
    background-color: #0d1726;
    border-color: #3f84ff;
}
QLabel#PhraseIndex {
    color: #7e92a9;
    background-color: #16202c;
    border: 1px solid #223043;
    border-radius: 6px;
    font-size: 10px;
    font-weight: 700;
}
QLineEdit#PhraseInput {
    background: transparent;
    border: none;
    color: #dce6f3;
    font-size: 12px;
    padding: 0;
    selection-background-color: #2f6fd0;
    selection-color: #ffffff;
}
QLabel#PhraseSaved {
    color: #3fe0a4;
    font-size: 10px;
}
QLabel#PhraseEmpty {
    color: #5b6d82;
    font-size: 11px;
}

/* ---------- 咨询商家多选 ---------- */
QLabel#MerchantSummary {
    color: #8fa2b8;
    font-size: 11px;
}
QScrollArea#MerchantScroll,
QWidget#MerchantViewport,
QWidget#MerchantList {
    background: transparent;
    border: none;
}
QCheckBox#MerchantCheck {
    color: #c6d5e6;
    font-size: 12px;
    spacing: 8px;
    background: transparent;
    padding: 3px 2px;
}
QCheckBox#MerchantCheck:hover {
    color: #eaf3ff;
}
QCheckBox#MerchantCheck::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #2d4058;
    border-radius: 4px;
    background-color: #0b121b;
}
QCheckBox#MerchantCheck::indicator:hover {
    border-color: #3f84ff;
}
QCheckBox#MerchantCheck::indicator:checked {
    background-color: #3f84ff;
    border-color: #3f84ff;
}
QLabel#MerchantEmpty {
    color: #5b6d82;
    font-size: 11px;
}

/* ---------- 右侧滚动区 ---------- */
QScrollArea#SideScroll,
QWidget#SideScrollViewport,
QWidget#SideScrollContent {
    background: transparent;
    border: none;
}

/* ---------- 进度条 ---------- */
QProgressBar#OverallBar {
    background-color: #0b121b;
    border: 1px solid #1d2836;
    border-radius: 5px;
}
QProgressBar#OverallBar::chunk {
    border-radius: 4px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #3f84ff, stop:1 #26d3a0);
}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #263447;
    border-radius: 4px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: #33465f;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    height: 0;
}

/* ---------- 状态栏 ---------- */
QStatusBar {
    background-color: #0a0f16;
    border-top: 1px solid #18212d;
    color: #6d7f95;
}
QStatusBar::item {
    border: none;
}
QLabel#StatusText {
    color: #7f92a8;
    font-size: 11px;
    padding-left: 8px;
}
QLabel#StatusVersion {
    color: #4f6076;
    font-size: 11px;
    padding-right: 8px;
}

/* ---------- 提示 ---------- */
QToolTip {
    background-color: #16202c;
    color: #dbe6f3;
    border: 1px solid #2c3d54;
    padding: 5px 8px;
    font-size: 11px;
}

QMessageBox {
    background-color: #111823;
}
QMessageBox QLabel {
    color: #dce6f3;
    font-size: 12px;
}
"""


def build_stylesheet() -> str:
    """返回已完成资源路径替换的全局样式表。"""
    arrow_up, arrow_down = _ensure_arrow_assets()
    return STYLE_SHEET.replace("@ARROW_UP@", arrow_up).replace("@ARROW_DOWN@", arrow_down)
