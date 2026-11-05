"""
Modern Dark Theme Stylesheet for PySide6 Data Recovery Suite
=============================================================
Provides a sleek, polished dark mode UI inspired by modern developer & forensic tools.
All font sizes are declared in explicit points (pt) to prevent QFont pointSize <= 0 warnings.
"""
from pathlib import Path

_CHECK_ICON_PATH = str(Path(__file__).parent / "icons" / "check.svg").replace("\\", "/")

DARK_THEME_QSS = """
/* ===== Global Application Styles ===== */
QWidget {
    background-color: #0a0e17;
    color: #c8ccd4;
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 10pt;
    selection-background-color: #1a2a3e;
    selection-color: #e0e4ec;
}

QMainWindow {
    background-color: #0a0e17;
}

/* ===== Frame Containers ===== */
QFrame[class="card"] {
    background-color: #0f1520;
    border: 1px solid #1a2230;
    border-radius: 8px;
    padding: 12px;
}

QFrame[class="card-highlight"] {
    background-color: #111927;
    border: 1px solid #1e2d40;
    border-radius: 8px;
    padding: 12px;
}

QFrame[class="metric-card"] {
    background-color: #0c1119;
    border: 1px solid #1a2230;
    border-radius: 8px;
    padding: 10px 14px;
}

QFrame[class="ticker-bar"] {
    background-color: #0c1119;
    border: 1px solid #1a2230;
    border-radius: 6px;
    padding: 6px 12px;
}

QFrame[class="device-info-box"] {
    background-color: #0c1119;
    border: 1px solid #1a2230;
    border-radius: 6px;
    padding: 8px;
}

/* ===== Headers & Labels ===== */
QLabel[class="header-title"] {
    font-size: 15pt;
    font-weight: 700;
    color: #e0e4ec;
    letter-spacing: 1px;
}

QLabel[class="header-subtitle"] {
    font-size: 9pt;
    color: #5a6578;
}

QLabel[class="version-badge"] {
    background-color: #0d3b2e;
    color: #2dd4a8;
    border: 1px solid #156b52;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 8pt;
    font-weight: 700;
}

QLabel[class="section-title"] {
    font-size: 10pt;
    font-weight: 700;
    color: #89b4fa;
    margin-bottom: 4px;
}

QLabel[class="section-number"] {
    font-size: 10pt;
    font-weight: 700;
    color: #5a6578;
}

QLabel[class="online-dot"] {
    color: #2dd4a8;
    font-size: 9pt;
    font-weight: 600;
}

QLabel[class="metric-value"] {
    font-size: 18pt;
    font-weight: 700;
    color: #e0e4ec;
}

QLabel[class="metric-value-accent"] {
    font-size: 18pt;
    font-weight: 700;
    color: #2dd4a8;
}

QLabel[class="metric-unit"] {
    font-size: 10pt;
    font-weight: 400;
    color: #5a6578;
}

QLabel[class="metric-label"] {
    font-size: 9pt;
    font-weight: 500;
    color: #5a6578;
    text-transform: uppercase;
}

QLabel[class="metric-sub"] {
    font-size: 8pt;
    color: #3d4a5c;
}

QLabel[class="peak-badge"] {
    background-color: #0d3b2e;
    color: #2dd4a8;
    border: 1px solid #156b52;
    border-radius: 3px;
    padding: 1px 6px;
    font-size: 8pt;
    font-weight: 600;
}

QLabel[class="scanning-badge"] {
    background-color: #1a2a3e;
    color: #4d9cf0;
    border: 1px solid #2a4a6e;
    border-radius: 3px;
    padding: 1px 6px;
    font-size: 8pt;
    font-weight: 600;
}

QLabel[class="ticker-text"] {
    font-size: 9pt;
    color: #5a6578;
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
}

QLabel[class="ticker-sector"] {
    font-size: 9pt;
    color: #2dd4a8;
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
}

QLabel[class="safety-ok"] {
    font-size: 9pt;
    color: #2dd4a8;
    font-weight: 500;
}

QLabel[class="safety-warn"] {
    font-size: 9pt;
    color: #f38ba8;
    font-weight: 700;
}

QLabel[class="info-label"] {
    font-size: 9pt;
    color: #5a6578;
}

QLabel[class="info-value"] {
    font-size: 9pt;
    color: #8892a4;
}

QLabel[class="info-badge-ro"] {
    background-color: #0d3b2e;
    color: #2dd4a8;
    border: 1px solid #156b52;
    border-radius: 3px;
    padding: 1px 6px;
    font-size: 8pt;
    font-weight: 600;
}

/* ===== Badges ===== */
QLabel[class="badge-admin"] {
    background-color: #0d3b2e;
    color: #2dd4a8;
    border: 1px solid #156b52;
    border-radius: 6px;
    padding: 5px 14px;
    font-size: 9pt;
    font-weight: 600;
}

QLabel[class="badge-user"] {
    background-color: #3b3022;
    color: #f9e2af;
    border: 1px solid #6b5536;
    border-radius: 6px;
    padding: 5px 14px;
    font-size: 9pt;
    font-weight: 600;
}

/* ===== Buttons ===== */
QPushButton {
    background-color: #141c28;
    color: #c8ccd4;
    border: 1px solid #1e2d40;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 500;
    font-size: 10pt;
}

QPushButton:hover {
    background-color: #1a2a3e;
    border-color: #2a4a6e;
}

QPushButton:pressed {
    background-color: #223550;
}

QPushButton:disabled {
    background-color: #0c1119;
    color: #3d4a5c;
    border-color: #141c28;
}

QPushButton[class="btn-primary"] {
    background-color: #2dd4a8;
    color: #0a0e17;
    border: none;
    font-weight: 700;
    padding: 14px 18px;
    font-size: 11pt;
    border-radius: 6px;
}

QPushButton[class="btn-primary"]:hover {
    background-color: #3de8ba;
}

QPushButton[class="btn-primary"]:pressed {
    background-color: #1fb88e;
}

QPushButton[class="btn-primary"]:disabled {
    background-color: #141c28;
    color: #3d4a5c;
}

QPushButton[class="btn-success"] {
    background-color: #2dd4a8;
    color: #0a0e17;
    border: none;
    font-weight: 600;
    font-size: 10pt;
}

QPushButton[class="btn-success"]:hover {
    background-color: #3de8ba;
}

QPushButton[class="btn-danger"] {
    background-color: #e05575;
    color: #ffffff;
    border: none;
    font-weight: 600;
    font-size: 10pt;
}

QPushButton[class="btn-danger"]:hover {
    background-color: #ea6b88;
}

QPushButton[class="btn-danger"]:disabled {
    background-color: #0c1119;
    color: #3d4a5c;
    border: 1px solid #1a2230;
}

QPushButton[class="btn-pause"] {
    background-color: #141c28;
    color: #c8ccd4;
    border: 1px solid #1e2d40;
    font-weight: 600;
    font-size: 10pt;
    border-radius: 6px;
    padding: 10px 16px;
}

QPushButton[class="btn-pause"]:hover {
    background-color: #1a2a3e;
}

QPushButton[class="btn-pause"]:disabled {
    background-color: #0c1119;
    color: #3d4a5c;
}

QPushButton[class="btn-filter"] {
    background-color: #141c28;
    color: #5a6578;
    border: 1px solid #1e2d40;
    border-radius: 4px;
    padding: 3px 10px;
    font-size: 9pt;
    font-weight: 500;
}

QPushButton[class="btn-filter"]:hover {
    color: #c8ccd4;
    border-color: #2a4a6e;
}

QPushButton[class="btn-filter-active"] {
    background-color: #1a2a3e;
    color: #4d9cf0;
    border: 1px solid #2a4a6e;
    border-radius: 4px;
    padding: 3px 10px;
    font-size: 9pt;
    font-weight: 600;
}

QPushButton[class="btn-table-action"] {
    background-color: #141c28;
    color: #5a6578;
    border: 1px solid #1e2d40;
    border-radius: 4px;
    padding: 3px 8px;
    font-size: 9pt;
}

QPushButton[class="btn-table-action"]:hover {
    color: #c8ccd4;
    border-color: #2a4a6e;
}

QPushButton[class="btn-tab-all"] {
    background-color: #1a2a3e;
    color: #4d9cf0;
    border: 1px solid #2a4a6e;
    border-radius: 4px;
    padding: 4px 12px;
    font-size: 9pt;
    font-weight: 600;
}

QPushButton[class="btn-tab"] {
    background-color: transparent;
    color: #5a6578;
    border: none;
    padding: 4px 12px;
    font-size: 9pt;
    font-weight: 500;
}

QPushButton[class="btn-tab"]:hover {
    color: #c8ccd4;
}

/* ===== Form Controls ===== */
QComboBox {
    background-color: #0f1520;
    color: #c8ccd4;
    border: 1px solid #1a2230;
    border-radius: 6px;
    padding: 6px 12px;
    min-height: 24px;
    font-size: 10pt;
}

QComboBox:hover {
    border-color: #2a4a6e;
}

QComboBox:disabled {
    background-color: #0c1119;
    color: #3d4a5c;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid #1a2230;
}

QComboBox QAbstractItemView {
    background-color: #0f1520;
    border: 1px solid #1e2d40;
    selection-background-color: #1a2a3e;
    selection-color: #4d9cf0;
    padding: 4px;
    font-size: 10pt;
}

QLineEdit {
    background-color: #0f1520;
    color: #c8ccd4;
    border: 1px solid #1a2230;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 10pt;
}

QLineEdit:focus {
    border-color: #2a4a6e;
}

QLineEdit:disabled {
    background-color: #0c1119;
    color: #3d4a5c;
}

/* ===== Checkboxes ===== */
QCheckBox {
    spacing: 8px;
    font-weight: 500;
    font-size: 8.5pt;
    color: #c8ccd4;
}

QCheckBox:disabled {
    color: #3d4a5c;
}

QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #2a3a50;
    border-radius: 3px;
    background-color: #0c1119;
}

QCheckBox::indicator:hover {
    border-color: #2dd4a8;
}

QCheckBox::indicator:checked {
    background-color: #2dd4a8;
    border-color: #2dd4a8;
    image: url("__CHECK_ICON__");
}

/* ===== Progress Bar ===== */
QProgressBar {
    background-color: #0c1119;
    border: 1px solid #1a2230;
    border-radius: 6px;
    text-align: center;
    color: #c8ccd4;
    font-weight: 600;
    font-size: 9pt;
    height: 20px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1b8a6e, stop:0.5 #2dd4a8, stop:1 #4d9cf0);
    border-radius: 5px;
}

/* ===== Table View ===== */
QTableWidget {
    background-color: #0c1119;
    border: 1px solid #1a2230;
    border-radius: 8px;
    gridline-color: #111927;
    color: #c8ccd4;
    font-size: 10pt;
}

QTableWidget::item {
    padding: 6px 10px;
    border-bottom: 1px solid #111927;
}

QTableWidget::item:selected {
    background-color: #1a2a3e;
    color: #e0e4ec;
}

QHeaderView::section {
    background-color: #0f1520;
    color: #5a6578;
    padding: 8px 10px;
    border: none;
    border-right: 1px solid #1a2230;
    border-bottom: 1px solid #1a2230;
    font-weight: 600;
    font-size: 9pt;
    text-transform: uppercase;
}

/* ===== Log Console ===== */
QTextEdit[class="log-console"] {
    background-color: #080c14;
    border: 1px solid #1a2230;
    border-radius: 6px;
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
    font-size: 9pt;
    color: #5a6578;
    padding: 8px;
}

/* ===== Scrollbars ===== */
QScrollBar:vertical {
    border: none;
    background: #0a0e17;
    width: 8px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #1a2230;
    min-height: 20px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #1e2d40;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    border: none;
    background: #0a0e17;
    height: 8px;
    margin: 0px;
}

QScrollBar::handle:horizontal {
    background: #1a2230;
    min-width: 20px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal:hover {
    background: #1e2d40;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ===== Splitter ===== */
QSplitter::handle {
    background-color: #1a2230;
    width: 1px;
}

QSplitter::handle:hover {
    background-color: #2a4a6e;
}

/* ===== Tooltip ===== */
QToolTip {
    background-color: #141c28;
    color: #c8ccd4;
    border: 1px solid #1e2d40;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 9pt;
}
"""

DARK_THEME_QSS = DARK_THEME_QSS.replace("__CHECK_ICON__", _CHECK_ICON_PATH)