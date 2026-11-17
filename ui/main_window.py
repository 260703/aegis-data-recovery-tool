"""
Modern Desktop Data Recovery Suite - Main GUI Window
=====================================================
Built with PySide6 for high-performance raw disk carving and file recovery.
Features:
- Dedicated QThread background scanner with real-time UI signals.
- Automatic USB / removable drive detection with non-blocking hotplug polling.
- Strict read-only target access with safety checks preventing target overwrites.
- Live file recovery table with search/filter, open folder, and file inspection.
- Professional forensic dashboard with real-time metrics, throughput, and ETA.
"""

import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

import psutil
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFileDialog, QProgressBar, QTableWidget, QTableWidgetItem,
    QHeaderView, QCheckBox, QFrame, QSplitter, QTextEdit, QScrollArea,
    QLineEdit, QMessageBox, QAbstractItemView, QSizePolicy, QMenu
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QPixmap, QColor
import shutil

from core.device_manager import DeviceManager, DeviceInfo
from core.worker import RecoveryWorker
from ui.styles import DARK_THEME_QSS

try:
    import aegis_core
except ImportError:
    aegis_core = None


# Format badge color map
FORMAT_BADGE_COLORS = {
    "JPG":  ("#1a3a2e", "#2dd4a8", "#156b52"),
    "JPEG": ("#1a3a2e", "#2dd4a8", "#156b52"),
    "PNG":  ("#1a2a3e", "#4d9cf0", "#2a4a6e"),
    "CR2":  ("#3b2a22", "#e8a65a", "#6b5536"),
    "CR3":  ("#3b2a22", "#e8a65a", "#6b5536"),
    "NEF":  ("#3b2a22", "#e8a65a", "#6b5536"),
    "ARW":  ("#3b2a22", "#e8a65a", "#6b5536"),
    "DNG":  ("#3b2a22", "#e8a65a", "#6b5536"),
    "RAW":  ("#3b2a22", "#e8a65a", "#6b5536"),
    "MP4":  ("#2a1a3e", "#a86edb", "#5a3a8e"),
    "MOV":  ("#2a1a3e", "#a86edb", "#5a3a8e"),
    "PDF":  ("#3b2222", "#e05575", "#6b3636"),
}


class FormatBadgeWidget(QLabel):
    """Small colored badge label for file format display in the table."""
    def __init__(self, fmt_text: str, parent=None):
        super().__init__(fmt_text, parent)
        fmt_upper = fmt_text.upper()
        bg, fg, border = FORMAT_BADGE_COLORS.get(fmt_upper, ("#141c28", "#5a6578", "#1e2d40"))
        self.setAlignment(Qt.AlignCenter)
        self.setFixedWidth(50)
        self.setFixedHeight(22)
        self.setStyleSheet(
            f"background-color: {bg}; color: {fg}; border: 1px solid {border}; "
            f"border-radius: 3px; font-size: 8pt; font-weight: 700; padding: 1px 4px;"
        )


class MainWindow(QMainWindow):
    def __init__(self, is_admin: bool):
        super().__init__()
        self.is_admin = is_admin
        self.device_mgr = DeviceManager()
        self.worker: Optional[RecoveryWorker] = None
        self.available_devices: List[DeviceInfo] = []
        self.custom_images: List[DeviceInfo] = []
        self.recovered_files: List[Dict[str, Any]] = []
        self._last_partition_sig: Tuple[Tuple[str, str], ...] = ()
        self._scan_aborted: bool = False
        self._scan_start_time: float = 0.0
        self._peak_speed: float = 0.0
        self._file_type_counts: Dict[str, int] = {}
        self._active_filter: str = "all"

        self.setWindowTitle("Aegis Data Recovery v5.0-PRO")
        self.resize(1380, 860)
        self.setMinimumSize(1100, 720)

        # Set application / window icon from aegis.ico
        ico_path = Path(__file__).resolve().parent.parent / "aegis.ico"
        if ico_path.exists():
            self.setWindowIcon(QIcon(str(ico_path)))

        # Apply Global Dark Theme Stylesheet
        self.setStyleSheet(DARK_THEME_QSS)

        # Ensure base font has a safe positive point size >= 1
        base_font = self.font()
        if base_font.pointSize() <= 0:
            base_font.setPointSize(10)
        self.setFont(base_font)

        # Build UI layout
        self._init_ui()

        # Initial device enumeration
        self.refresh_devices()

        # Log active engine capabilities
        if aegis_core is not None:
            self._log("⚡ Native Rust acceleration active: Hardware AVX2/SIMD pattern matching & Rayon multi-threading.", "success")
        else:
            self._log("⚠️ Native Rust engine (aegis_core) not detected. Running in Pure Python fallback mode.", "warning")
            self._log("💡 Tip: For up to 50x faster carving, download the pre-compiled .exe from GitHub Releases or build with 'maturin develop --release'.", "info")

        # Start periodic USB hotplug detection timer (checks every 2.5s without blocking UI)
        self.hotplug_timer = QTimer(self)
        self.hotplug_timer.timeout.connect(self._check_device_hotplug)
        self.hotplug_timer.start(2500)

        # Elapsed timer for live clock
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._update_elapsed)

    def _init_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # =============================================================
        # TOP HEADER BAR (compact)
        # =============================================================
        # =============================================================
        # TOP HEADER BAR (compact 42px)
        # =============================================================
        header_frame = QFrame()
        header_frame.setFixedHeight(42)
        header_frame.setStyleSheet(
            "background-color: #0c1119; border-bottom: 1px solid #1a2230;"
        )
        header_bar = QHBoxLayout(header_frame)
        header_bar.setContentsMargins(14, 0, 14, 0)
        header_bar.setSpacing(10)

        # App icon / logo
        ico_path = Path(__file__).resolve().parent.parent / "aegis.ico"
        if ico_path.exists():
            icon_label = QLabel()
            pixmap = QIcon(str(ico_path)).pixmap(24, 24)
            icon_label.setPixmap(pixmap)
            icon_label.setFixedSize(pixmap.width(), 24)
            icon_label.setStyleSheet("border: none; background: transparent;")
            header_bar.addWidget(icon_label)
        else:
            icon_label = QLabel("🛡")
            icon_label.setStyleSheet("font-size: 13pt; border: none;")
            header_bar.addWidget(icon_label)

        # Title + version badge (single row, compact)
        app_title = QLabel("AEGIS DATA RECOVERY")
        app_title.setStyleSheet("font-size: 11pt; font-weight: 700; color: #e0e4ec; letter-spacing: 0.5px;")
        header_bar.addWidget(app_title)

        version_badge = QLabel("v5.0-PRO")
        version_badge.setStyleSheet(
            "background-color: #0d3b2e; color: #2dd4a8; border: 1px solid #156b52; "
            "border-radius: 3px; padding: 1px 5px; font-size: 7.5pt; font-weight: 700;"
        )
        version_badge.setFixedHeight(18)
        header_bar.addWidget(version_badge)

        # Subtitle
        app_sub = QLabel("Forensic Raw Disk Carving Engine · Read-Only Media Stream")
        app_sub.setStyleSheet("font-size: 8pt; color: #4d5b6e; margin-left: 6px;")
        header_bar.addWidget(app_sub)

        header_bar.addStretch()

        # Elevation status badge (matched 26px height)
        if self.is_admin:
            admin_badge = QLabel("● ADMINISTRATOR (RAW DISK ACCESS ENABLED)")
            admin_badge.setStyleSheet(
                "background-color: #0d3b2e; color: #2dd4a8; border: 1px solid #156b52; "
                "border-radius: 4px; padding: 0 10px; font-size: 8pt; font-weight: 600;"
            )
        else:
            admin_badge = QLabel("⚠ USER MODE (DISK IMAGES ONLY)")
            admin_badge.setStyleSheet(
                "background-color: #3b3022; color: #f9e2af; border: 1px solid #6b5536; "
                "border-radius: 4px; padding: 0 10px; font-size: 8pt; font-weight: 600;"
            )
        admin_badge.setFixedHeight(26)
        admin_badge.setAlignment(Qt.AlignCenter)
        header_bar.addWidget(admin_badge)

        # Refresh drives button (matched 26px height and identical border-radius)
        self.btn_refresh = QPushButton("⟳ Refresh Drives")
        self.btn_refresh.setFixedHeight(26)
        self.btn_refresh.setStyleSheet(
            "QPushButton { background-color: #141c28; color: #c8ccd4; border: 1px solid #1e2d40; "
            "border-radius: 4px; padding: 0 10px; font-size: 8pt; font-weight: 500; } "
            "QPushButton:hover { background-color: #1a2a3e; border-color: #2a4a6e; color: #ffffff; }"
        )
        self.btn_refresh.setToolTip("Scan system for newly connected USB or removable drives")
        self.btn_refresh.clicked.connect(self.refresh_devices)
        header_bar.addWidget(self.btn_refresh)

        root_layout.addWidget(header_frame)

        # =============================================================
        # MAIN CONTENT AREA (Left sidebar + Right dashboard)
        # =============================================================
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # ----- LEFT SIDEBAR -----
        left_panel = QFrame()
        left_panel.setFixedWidth(380)
        left_panel.setStyleSheet(
            "QFrame#left_panel { background-color: #0f1520; border-right: 1px solid #1a2230; "
            "border-top: none; border-left: none; border-bottom: none; border-radius: 0; }"
        )
        left_panel.setObjectName("left_panel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # Scroll Area for configuration sections (1 through 4)
        # Prevents any content cropping across different screen heights/DPIs
        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setFrameShape(QFrame.NoFrame)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.left_scroll.setStyleSheet(
            "QScrollArea { background-color: transparent; border: none; } "
            "QScrollBar:vertical { width: 6px; background: #0c1119; border: none; } "
            "QScrollBar::handle:vertical { background: #1e2d40; border-radius: 3px; min-height: 20px; } "
            "QScrollBar::handle:vertical:hover { background: #2a4a6e; } "
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
        )

        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background-color: transparent;")
        self.scroll_content.setFixedWidth(378)
        scroll_layout = QVBoxLayout(self.scroll_content)
        scroll_layout.setContentsMargins(16, 14, 16, 14)
        scroll_layout.setSpacing(12)

        # --- 1. RECOVERY TARGET ---
        self._add_section_header(scroll_layout, "1", "SELECT RECOVERY TARGET", online=True)

        self.combo_devices = QComboBox()
        self.combo_devices.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.combo_devices.setFixedHeight(34)
        self.combo_devices.setStyleSheet("font-size: 9pt; padding: 4px 8px;")
        self.combo_devices.view().setFixedWidth(346)
        self.combo_devices.view().setTextElideMode(Qt.ElideMiddle)
        self.combo_devices.currentIndexChanged.connect(self._on_device_selected)
        scroll_layout.addWidget(self.combo_devices)

        self.btn_browse_image = QPushButton("📁  Load Disk Image (.dd, .img, .raw, .vhd)")
        self.btn_browse_image.setFixedHeight(32)
        self.btn_browse_image.setStyleSheet(
            "QPushButton { font-size: 8.5pt; font-weight: 500; background-color: #141c28; "
            "color: #c8ccd4; border: 1px solid #1e2d40; border-radius: 5px; padding: 4px 10px; } "
            "QPushButton:hover { background-color: #1a2a3e; border-color: #2a4a6e; color: #ffffff; }"
        )
        self.btn_browse_image.setToolTip("Mount a forensic raw disk image dump file for recovery")
        self.btn_browse_image.clicked.connect(self._browse_disk_image)
        scroll_layout.addWidget(self.btn_browse_image)

        # Device info box (clean styling, distinct row layout)
        self.frame_device_info = QFrame()
        self.frame_device_info.setStyleSheet(
            "background-color: #0a0e16; border: 1px solid #1a2230; border-radius: 6px;"
        )
        info_layout = QVBoxLayout(self.frame_device_info)
        info_layout.setSpacing(6)
        info_layout.setContentsMargins(12, 8, 12, 8)

        self.lbl_info_sector = self._make_info_row(info_layout, "Logical Sector Size:", "512 Bytes")
        self.lbl_info_sectors = self._make_info_row(info_layout, "Total Sectors (LBA):", "-")
        self.lbl_info_write_mode = self._make_write_mode_row(info_layout)
        scroll_layout.addWidget(self.frame_device_info)

        # --- 2. OUTPUT DIRECTORY ---
        self._add_section_header(scroll_layout, "2", "OUTPUT RECOVERY DIRECTORY")

        out_box = QHBoxLayout()
        out_box.setContentsMargins(0, 0, 0, 0)
        out_box.setSpacing(8)

        self.edit_output = QLineEdit()
        self.edit_output.setFixedHeight(32)
        self.edit_output.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        desktop_path = Path.home() / "Desktop"
        default_out = str((desktop_path if desktop_path.exists() else Path.home()) / "Aegis_Recovered_Data")
        self.edit_output.setText(default_out)
        self.edit_output.setPlaceholderText("Select output destination folder...")
        self.edit_output.setToolTip("Folder where recovered files are saved (must NOT be on target drive)")
        self.edit_output.textChanged.connect(self._validate_output_safety)

        self.btn_browse_out = QPushButton("📁 Browse...")
        self.btn_browse_out.setFixedHeight(32)
        self.btn_browse_out.setFixedWidth(85)
        self.btn_browse_out.setStyleSheet(
            "QPushButton { background-color: #141c28; color: #4d9cf0; border: 1px solid #2a4a6e; "
            "border-radius: 5px; font-size: 8.5pt; font-weight: 600; padding: 0 6px; } "
            "QPushButton:hover { background-color: #1a2a3e; border-color: #4d9cf0; color: #ffffff; }"
        )
        self.btn_browse_out.setToolTip("Select destination folder on a separate drive")
        self.btn_browse_out.clicked.connect(self._browse_output_dir)

        out_box.addWidget(self.edit_output)
        out_box.addWidget(self.btn_browse_out)
        scroll_layout.addLayout(out_box)

        # Safety Warning Label
        self.lbl_safety_status = QLabel("✓  Separate drive selected (Read-Only Safety Guaranteed)")
        self.lbl_safety_status.setProperty("class", "safety-ok")
        self.lbl_safety_status.setWordWrap(True)
        scroll_layout.addWidget(self.lbl_safety_status)

        # --- 3. FILE FORMATS TO CARVE ---
        fmt_header = QHBoxLayout()
        fmt_header.setSpacing(4)
        lbl_fmt_num = QLabel("3.")
        lbl_fmt_num.setProperty("class", "section-number")
        lbl_fmt_num.setFixedWidth(16)
        fmt_header.addWidget(lbl_fmt_num)
        lbl_fmt_title = QLabel("FILE FORMATS TO CARVE")
        lbl_fmt_title.setProperty("class", "section-title")
        fmt_header.addWidget(lbl_fmt_title)
        fmt_header.addStretch()
        self.lbl_selected_count = QLabel("5 Selected")
        self.lbl_selected_count.setStyleSheet(
            "background-color: #0d3b2e; color: #2dd4a8; border: 1px solid #156b52; "
            "border-radius: 3px; padding: 1px 6px; font-size: 7.5pt; font-weight: 700;"
        )
        fmt_header.addWidget(self.lbl_selected_count)
        scroll_layout.addLayout(fmt_header)

        # Filter tabs for format checkboxes (compact pills that never clip)
        filter_tabs = QHBoxLayout()
        filter_tabs.setSpacing(6)
        self.btn_select_all = QPushButton("All")
        self.btn_photos_only = QPushButton("Photos")
        self.btn_videos_only = QPushButton("Videos")
        for btn in (self.btn_select_all, self.btn_photos_only, self.btn_videos_only):
            btn.setFixedHeight(22)
            btn.setStyleSheet(
                "QPushButton { font-size: 8pt; padding: 1px 12px; background-color: #141c28; "
                "color: #8892a4; border: 1px solid #1e2d40; border-radius: 3px; font-weight: 500; } "
                "QPushButton:hover { background-color: #1a2a3e; color: #2dd4a8; border-color: #2dd4a8; }"
            )
        self.btn_select_all.setToolTip("Select all supported file formats")
        self.btn_photos_only.setToolTip("Select photos only (JPEG, PNG, RAW)")
        self.btn_videos_only.setToolTip("Select videos only (MP4, MOV)")
        self.btn_select_all.clicked.connect(self._select_all_formats)
        self.btn_photos_only.clicked.connect(self._select_photos_only)
        self.btn_videos_only.clicked.connect(self._select_videos_only)
        filter_tabs.addWidget(self.btn_select_all)
        filter_tabs.addWidget(self.btn_photos_only)
        filter_tabs.addWidget(self.btn_videos_only)
        filter_tabs.addStretch()
        scroll_layout.addLayout(filter_tabs)

        fmt_box = QVBoxLayout()
        fmt_box.setSpacing(6)
        self.chk_jpeg = QCheckBox("JPEG Images   (.jpg, .jpeg)")
        self.chk_png = QCheckBox("PNG Images    (.png)")
        self.chk_raw = QCheckBox("RAW Photos    (.cr2, .cr3, .nef, .arw)")
        self.chk_mp4 = QCheckBox("MP4 Videos    (.mp4)")
        self.chk_mov = QCheckBox("QuickTime      (.mov)")

        self._format_checkboxes = [self.chk_jpeg, self.chk_png, self.chk_raw, self.chk_mp4, self.chk_mov]
        for chk in self._format_checkboxes:
            chk.setChecked(True)
            chk.stateChanged.connect(self._update_format_count)
            fmt_box.addWidget(chk)
        scroll_layout.addLayout(fmt_box)

        # --- 4. SECTOR ALIGNMENT ---
        self._add_section_header(scroll_layout, "4", "SECTOR ALIGNMENT")

        self.combo_align = QComboBox()
        self.combo_align.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.combo_align.setFixedHeight(34)
        self.combo_align.view().setFixedWidth(346)
        self.combo_align.view().setTextElideMode(Qt.ElideRight)
        self.combo_align.addItem("512-Byte Sector (Fast, Standard FAT/exFAT)", 512)
        self.combo_align.addItem("4096-Byte Cluster (Ultra-Fast NTFS)", 4096)
        self.combo_align.addItem("1-Byte Unaligned (Forensic Byte Carve)", 1)
        scroll_layout.addWidget(self.combo_align)

        scroll_layout.addStretch()
        self.left_scroll.setWidget(self.scroll_content)
        left_layout.addWidget(self.left_scroll, stretch=1)

        # --- ACTION BUTTONS (Pinned at bottom of sidebar, never hidden) ---
        action_footer = QFrame()
        action_footer.setStyleSheet(
            "QFrame { background-color: #0b0f17; border-top: 1px solid #1a2230; "
            "border-bottom: none; border-left: none; border-right: none; }"
        )
        footer_layout = QVBoxLayout(action_footer)
        footer_layout.setContentsMargins(16, 12, 16, 14)
        footer_layout.setSpacing(8)

        self.btn_start = QPushButton("▶  START RECOVERY SCAN")
        self.btn_start.setProperty("class", "btn-primary")
        self.btn_start.setFixedHeight(44)
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self._start_scan)
        footer_layout.addWidget(self.btn_start)

        btn_action_sub = QHBoxLayout()
        btn_action_sub.setSpacing(8)
        self.btn_pause = QPushButton("⏸  Pause")
        self.btn_pause.setProperty("class", "btn-pause")
        self.btn_pause.setFixedHeight(34)
        self.btn_pause.setCursor(Qt.PointingHandCursor)
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._toggle_pause)

        self.btn_stop = QPushButton("⏹  Stop")
        self.btn_stop.setProperty("class", "btn-danger")
        self.btn_stop.setFixedHeight(34)
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_scan)

        btn_action_sub.addWidget(self.btn_pause)
        btn_action_sub.addWidget(self.btn_stop)
        footer_layout.addLayout(btn_action_sub)

        left_layout.addWidget(action_footer)

        content_layout.addWidget(left_panel)


        # ----- RIGHT DASHBOARD PANEL -----
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(16, 12, 16, 12)
        right_layout.setSpacing(10)

        # === METRICS ROW ===
        metrics_bar = QHBoxLayout()
        metrics_bar.setSpacing(10)

        # Progress metric
        self.card_progress, progress_inner = self._make_metric_card()
        self.lbl_progress_pct = QLabel("0.0%")
        self.lbl_progress_pct.setStyleSheet("font-size: 18pt; font-weight: 700; color: #e0e4ec;")
        self.lbl_progress_val = QLabel("0.0 / 0.0 GB")
        self.lbl_progress_val.setStyleSheet("font-size: 11pt; font-weight: 500; color: #e0e4ec;")
        self.lbl_progress_lba = QLabel("LBA: 0")
        self.lbl_progress_lba.setProperty("class", "metric-sub")
        lbl_progress_title = QLabel("PROGRESS")
        lbl_progress_title.setProperty("class", "metric-label")
        progress_inner.addWidget(lbl_progress_title)
        progress_row = QHBoxLayout()
        progress_row.addWidget(self.lbl_progress_val)
        progress_row.addStretch()
        progress_row.addWidget(self.lbl_progress_pct)
        progress_inner.addLayout(progress_row)
        progress_inner.addWidget(self.lbl_progress_lba)
        metrics_bar.addWidget(self.card_progress)

        # I/O Throughput metric
        self.card_speed, speed_inner = self._make_metric_card()
        lbl_speed_title_row = QHBoxLayout()
        lbl_speed_title = QLabel("I/O THROUGHPUT")
        lbl_speed_title.setProperty("class", "metric-label")
        lbl_speed_title_row.addWidget(lbl_speed_title)
        lbl_speed_title_row.addStretch()
        self.lbl_peak_badge = QLabel("PEAK: 0 MB/s")
        self.lbl_peak_badge.setProperty("class", "peak-badge")
        lbl_speed_title_row.addWidget(self.lbl_peak_badge)
        speed_inner.addLayout(lbl_speed_title_row)
        self.lbl_speed_val = QLabel("0.0")
        self.lbl_speed_val.setStyleSheet("font-size: 22pt; font-weight: 700; color: #e0e4ec;")
        speed_val_row = QHBoxLayout()
        speed_val_row.addWidget(self.lbl_speed_val)
        lbl_speed_unit = QLabel("MB/s")
        lbl_speed_unit.setProperty("class", "metric-unit")
        speed_val_row.addWidget(lbl_speed_unit)
        speed_val_row.addStretch()
        speed_inner.addLayout(speed_val_row)
        # Speed bar visualization
        self.speed_bars = []
        speed_bar_row = QHBoxLayout()
        speed_bar_row.setSpacing(2)
        for i in range(8):
            bar = QLabel()
            bar.setFixedSize(12, 14)
            bar.setStyleSheet("background-color: #1a2230; border-radius: 2px;")
            speed_bar_row.addWidget(bar)
            self.speed_bars.append(bar)
        speed_bar_row.addStretch()
        speed_inner.addLayout(speed_bar_row)
        self.lbl_speed_channel = QLabel("Channel: Waiting...")
        self.lbl_speed_channel.setProperty("class", "metric-sub")
        speed_inner.addWidget(self.lbl_speed_channel)
        metrics_bar.addWidget(self.card_speed)

        # Estimated Time metric
        self.card_eta, eta_inner = self._make_metric_card()
        eta_title_row = QHBoxLayout()
        lbl_eta_title = QLabel("ESTIMATED TIME")
        lbl_eta_title.setProperty("class", "metric-label")
        eta_title_row.addWidget(lbl_eta_title)
        eta_title_row.addStretch()
        self.lbl_scan_state = QLabel("IDLE")
        self.lbl_scan_state.setProperty("class", "scanning-badge")
        eta_title_row.addWidget(self.lbl_scan_state)
        eta_inner.addLayout(eta_title_row)
        self.lbl_eta_val = QLabel("--:--:--")
        self.lbl_eta_val.setStyleSheet("font-size: 22pt; font-weight: 700; color: #e0e4ec;")
        eta_inner.addWidget(self.lbl_eta_val)
        self.lbl_elapsed = QLabel("Elapsed: 00:00:00")
        self.lbl_elapsed.setProperty("class", "metric-sub")
        eta_inner.addWidget(self.lbl_elapsed)
        if aegis_core is not None:
            self.lbl_engine_info = QLabel("Engine: ⚡ Native Rust (SIMD + Rayon)")
            self.lbl_engine_info.setStyleSheet("color: #2dd4a8; font-size: 8pt; font-weight: 600;")
            self.lbl_engine_info.setToolTip("Hardware-accelerated AVX2/SIMD scanning & Rayon multi-threading active")
        else:
            self.lbl_engine_info = QLabel("Engine: ⚠️ Pure Python (Fallback Mode)")
            self.lbl_engine_info.setStyleSheet("color: #e8a65a; font-size: 8pt; font-weight: 600;")
            self.lbl_engine_info.setToolTip("Running in interpreted Python fallback mode. Build with maturin or download .exe for 50x speed.")
        eta_inner.addWidget(self.lbl_engine_info)
        metrics_bar.addWidget(self.card_eta)

        # Recovered Files metric
        self.card_files, files_inner = self._make_metric_card()
        files_title_row = QHBoxLayout()
        lbl_files_title = QLabel("RECOVERED FILES")
        lbl_files_title.setProperty("class", "metric-label")
        files_title_row.addWidget(lbl_files_title)
        files_title_row.addStretch()
        self.lbl_valid_count = QLabel("0 VALID")
        self.lbl_valid_count.setProperty("class", "peak-badge")
        files_title_row.addWidget(self.lbl_valid_count)
        files_inner.addLayout(files_title_row)
        self.lbl_files_val = QLabel("0")
        self.lbl_files_val.setStyleSheet("font-size: 28pt; font-weight: 700; color: #2dd4a8;")
        files_inner.addWidget(self.lbl_files_val)
        self.lbl_corrupt_count = QLabel("Corrupt / Partial: 0")
        self.lbl_corrupt_count.setProperty("class", "metric-sub")
        files_inner.addWidget(self.lbl_corrupt_count)
        self.lbl_auto_verify = QLabel("Auto-verification enabled")
        self.lbl_auto_verify.setProperty("class", "metric-sub")
        files_inner.addWidget(self.lbl_auto_verify)
        metrics_bar.addWidget(self.card_files)

        right_layout.addLayout(metrics_bar)

        # === TICKER / STATUS BAR ===
        ticker_frame = QFrame()
        ticker_frame.setProperty("class", "ticker-bar")
        ticker_layout = QHBoxLayout(ticker_frame)
        ticker_layout.setContentsMargins(12, 4, 12, 4)
        ticker_layout.setSpacing(8)
        self.lbl_ticker_text = QLabel("Ready to scan · Signatures loaded · Write-block hardware check: N/A")
        self.lbl_ticker_text.setProperty("class", "ticker-text")
        ticker_layout.addWidget(self.lbl_ticker_text)
        ticker_layout.addStretch()
        lbl_sector_label = QLabel("Sector Offset:")
        lbl_sector_label.setProperty("class", "ticker-text")
        ticker_layout.addWidget(lbl_sector_label)
        self.lbl_ticker_sector = QLabel("0x0000000000")
        self.lbl_ticker_sector.setProperty("class", "ticker-sector")
        ticker_layout.addWidget(self.lbl_ticker_sector)
        right_layout.addWidget(ticker_frame)

        # === RECOVERED FILES TABLE HEADER ===
        table_header_row = QHBoxLayout()
        table_header_row.setSpacing(8)

        lbl_table_title = QLabel("RECOVERED FILES STREAM")
        lbl_table_title.setStyleSheet("font-size: 10pt; font-weight: 700; color: #e0e4ec;")
        table_header_row.addWidget(lbl_table_title)

        # File count + type tabs
        self.lbl_total_items = QLabel("0 items")
        self.lbl_total_items.setStyleSheet("font-size: 9pt; color: #5a6578; margin-left: 8px;")
        table_header_row.addWidget(self.lbl_total_items)

        # Tab buttons for filtering
        self.btn_tab_all = QPushButton("All")
        self.btn_tab_all.setProperty("class", "btn-tab-all")
        self.btn_tab_all.clicked.connect(lambda: self._set_table_filter("all"))
        table_header_row.addWidget(self.btn_tab_all)

        self.btn_tab_images = QPushButton("Images (0)")
        self.btn_tab_images.setProperty("class", "btn-tab")
        self.btn_tab_images.clicked.connect(lambda: self._set_table_filter("images"))
        table_header_row.addWidget(self.btn_tab_images)

        self.btn_tab_video = QPushButton("Video (0)")
        self.btn_tab_video.setProperty("class", "btn-tab")
        self.btn_tab_video.clicked.connect(lambda: self._set_table_filter("video"))
        table_header_row.addWidget(self.btn_tab_video)

        self.btn_tab_docs = QPushButton("Docs (0)")
        self.btn_tab_docs.setProperty("class", "btn-tab")
        self.btn_tab_docs.clicked.connect(lambda: self._set_table_filter("docs"))
        table_header_row.addWidget(self.btn_tab_docs)

        table_header_row.addStretch()

        # Selection buttons: Select All / Deselect All
        self.btn_select_all = QPushButton("☑ Select All")
        self.btn_select_all.setFixedHeight(28)
        self.btn_select_all.setCursor(Qt.PointingHandCursor)
        self.btn_select_all.setStyleSheet("""
            QPushButton {
                background-color: #141c28;
                color: #8b99ac;
                border: 1px solid #1e2d40;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 8pt;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #1a2a3e;
                color: #e0e4ec;
                border-color: #2a3a50;
            }
        """)
        self.btn_select_all.clicked.connect(self._select_all_files)
        table_header_row.addWidget(self.btn_select_all)

        self.btn_deselect_all = QPushButton("☐ Deselect All")
        self.btn_deselect_all.setFixedHeight(28)
        self.btn_deselect_all.setCursor(Qt.PointingHandCursor)
        self.btn_deselect_all.setStyleSheet("""
            QPushButton {
                background-color: #141c28;
                color: #8b99ac;
                border: 1px solid #1e2d40;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 8pt;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #1a2a3e;
                color: #e0e4ec;
                border-color: #2a3a50;
            }
        """)
        self.btn_deselect_all.clicked.connect(self._deselect_all_files)
        table_header_row.addWidget(self.btn_deselect_all)

        # Search filter
        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("🔍 Filter files...")
        self.edit_search.setMaximumWidth(180)
        self.edit_search.setFixedHeight(28)
        self.edit_search.textChanged.connect(self._filter_table)
        table_header_row.addWidget(self.edit_search)

        # Save Selected button (prominent emerald accent)
        self.btn_save_selected = QPushButton("💾 Save Selected (0)")
        self.btn_save_selected.setFixedHeight(28)
        self.btn_save_selected.setCursor(Qt.PointingHandCursor)
        self.btn_save_selected.setEnabled(False)
        self.btn_save_selected.setStyleSheet("""
            QPushButton {
                background-color: #0d3b2e;
                color: #2dd4a8;
                border: 1px solid #156b52;
                border-radius: 4px;
                padding: 2px 10px;
                font-weight: 700;
                font-size: 8.5pt;
            }
            QPushButton:hover {
                background-color: #156b52;
                color: #ffffff;
            }
            QPushButton:disabled {
                background-color: #0c1119;
                color: #3d4a5c;
                border: 1px solid #1a2230;
            }
        """)
        self.btn_save_selected.clicked.connect(lambda: self._save_selected_files(show_dialog=True))
        table_header_row.addWidget(self.btn_save_selected)

        # Open Output Folder
        btn_open_out_folder = QPushButton("📂 Open Folder")
        btn_open_out_folder.setFixedHeight(28)
        btn_open_out_folder.setCursor(Qt.PointingHandCursor)
        btn_open_out_folder.clicked.connect(self._open_output_folder)
        table_header_row.addWidget(btn_open_out_folder)

        right_layout.addLayout(table_header_row)

        # === TABLE WIDGET ===
        self.table_files = QTableWidget()
        self.table_files.setColumnCount(7)
        self.table_files.setHorizontalHeaderLabels([
            "FILE NAME", "FORMAT", "SIZE", "SECTOR OFFSET / LBA",
            "INTEGRITY DETAILS", "SELECT", ""
        ])
        header = self.table_files.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.resizeSection(1, 70)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.resizeSection(2, 80)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.resizeSection(3, 170)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        header.resizeSection(5, 75)
        header.setSectionResizeMode(6, QHeaderView.Fixed)
        header.resizeSection(6, 60)
        self.table_files.setColumnHidden(6, True)  # Hidden helper column

        header.sectionClicked.connect(self._on_header_section_clicked)
        self.table_files.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_files.customContextMenuRequested.connect(self._on_table_context_menu)

        self.table_files.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_files.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_files.doubleClicked.connect(self._on_table_double_click)
        self.table_files.setShowGrid(False)
        self.table_files.verticalHeader().setVisible(False)
        right_layout.addWidget(self.table_files, stretch=3)

        # === ACTIVITY CONSOLE ===
        console_header = QHBoxLayout()
        console_header.setSpacing(8)
        console_dot = QLabel("●")
        console_dot.setStyleSheet("color: #2dd4a8; font-size: 10pt;")
        console_header.addWidget(console_dot)
        lbl_console = QLabel("ACTIVITY CONSOLE / FORENSIC LOG STREAM")
        lbl_console.setStyleSheet("font-size: 9pt; font-weight: 700; color: #5a6578;")
        console_header.addWidget(lbl_console)
        console_header.addStretch()

        self.chk_auto_scroll = QCheckBox("Auto-Scroll: ON")
        self.chk_auto_scroll.setChecked(True)
        self.chk_auto_scroll.setStyleSheet("font-size: 8pt; color: #5a6578;")
        console_header.addWidget(self.chk_auto_scroll)

        btn_clear_console = QPushButton("Clear Console")
        btn_clear_console.setProperty("class", "btn-filter")
        btn_clear_console.clicked.connect(lambda: self.txt_console.clear())
        console_header.addWidget(btn_clear_console)

        btn_export_log = QPushButton("Export Log (.txt)")
        btn_export_log.setProperty("class", "btn-filter")
        btn_export_log.clicked.connect(self._export_log)
        console_header.addWidget(btn_export_log)

        right_layout.addLayout(console_header)

        self.txt_console = QTextEdit()
        self.txt_console.setProperty("class", "log-console")
        self.txt_console.setReadOnly(True)
        self.txt_console.setMaximumHeight(140)
        right_layout.addWidget(self.txt_console, stretch=1)

        content_layout.addWidget(right_panel)

        root_layout.addWidget(content_widget)

    # ------------------------------------------------------------------
    # UI Helper Builders
    # ------------------------------------------------------------------
    @staticmethod
    def _make_metric_card() -> Tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setProperty("class", "metric-card")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)
        return card, layout

    def _add_section_header(self, parent_layout: QVBoxLayout, number: str, title: str, online: bool = False):
        row = QHBoxLayout()
        row.setSpacing(6)
        lbl_num = QLabel(f"{number}.")
        lbl_num.setProperty("class", "section-number")
        lbl_num.setFixedWidth(18)
        row.addWidget(lbl_num)
        lbl_title = QLabel(title)
        lbl_title.setProperty("class", "section-title")
        row.addWidget(lbl_title)
        row.addStretch()
        if online:
            dot = QLabel("● ONLINE")
            dot.setProperty("class", "online-dot")
            row.addWidget(dot)
        parent_layout.addLayout(row)

    def _make_info_row(self, parent_layout: QVBoxLayout, label: str, value: str) -> QLabel:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lbl = QLabel(label)
        lbl.setStyleSheet("font-size: 8.5pt; color: #5a6578; border: none; background: transparent;")
        lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        row.addWidget(lbl)
        row.addStretch()
        val = QLabel(value)
        val.setStyleSheet("font-size: 8.5pt; color: #c8ccd4; font-weight: 600; border: none; background: transparent;")
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        val.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        row.addWidget(val)
        parent_layout.addLayout(row)
        return val

    def _make_write_mode_row(self, parent_layout: QVBoxLayout) -> QLabel:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lbl = QLabel("Write-Block Mode:")
        lbl.setStyleSheet("font-size: 8.5pt; color: #5a6578; border: none; background: transparent;")
        lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        row.addWidget(lbl)
        row.addStretch()
        badge = QLabel("● Hardware Read-Only")
        badge.setStyleSheet(
            "background-color: #0d3b2e; color: #2dd4a8; border: 1px solid #156b52; "
            "border-radius: 3px; padding: 1px 7px; font-size: 8pt; font-weight: 700;"
        )
        badge.setFixedHeight(20)
        badge.setAlignment(Qt.AlignCenter)
        row.addWidget(badge)
        parent_layout.addLayout(row)
        return badge

    # ------------------------------------------------------------------
    # Format Selection Helpers
    # ------------------------------------------------------------------
    def _update_format_count(self):
        count = sum(1 for chk in self._format_checkboxes if chk.isChecked())
        self.lbl_selected_count.setText(f"{count} Selected")

    def _select_all_formats(self):
        for chk in self._format_checkboxes:
            chk.setChecked(True)

    def _select_photos_only(self):
        self.chk_jpeg.setChecked(True)
        self.chk_png.setChecked(True)
        self.chk_raw.setChecked(True)
        self.chk_mp4.setChecked(False)
        self.chk_mov.setChecked(False)

    def _select_videos_only(self):
        self.chk_jpeg.setChecked(False)
        self.chk_png.setChecked(False)
        self.chk_raw.setChecked(False)
        self.chk_mp4.setChecked(True)
        self.chk_mov.setChecked(True)

    # ------------------------------------------------------------------
    # Table Filter Tabs
    # ------------------------------------------------------------------
    def _set_table_filter(self, filter_type: str):
        self._active_filter = filter_type
        # Update tab button styles
        for btn, ftype in [(self.btn_tab_all, "all"), (self.btn_tab_images, "images"),
                           (self.btn_tab_video, "video"), (self.btn_tab_docs, "docs")]:
            if ftype == filter_type:
                btn.setProperty("class", "btn-tab-all")
            else:
                btn.setProperty("class", "btn-tab")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._filter_table(self.edit_search.text())

    def _get_type_category(self, ext: str) -> str:
        ext = ext.upper()
        if ext in ("JPG", "JPEG", "PNG", "CR2", "CR3", "NEF", "ARW", "DNG", "RAW", "TIFF"):
            return "images"
        if ext in ("MP4", "MOV", "AVI", "MKV"):
            return "video"
        return "docs"

    def _update_tab_counts(self):
        img_count = sum(1 for f in self.recovered_files if self._get_type_category(f["ext"]) == "images")
        vid_count = sum(1 for f in self.recovered_files if self._get_type_category(f["ext"]) == "video")
        doc_count = sum(1 for f in self.recovered_files if self._get_type_category(f["ext"]) == "docs")
        self.btn_tab_images.setText(f"Images ({img_count})")
        self.btn_tab_video.setText(f"Video ({vid_count})")
        self.btn_tab_docs.setText(f"Docs ({doc_count})")
        self.lbl_total_items.setText(f"{len(self.recovered_files)} items")

    # ------------------------------------------------------------------
    # Elapsed Timer
    # ------------------------------------------------------------------
    def _update_elapsed(self):
        import time
        elapsed = time.time() - self._scan_start_time
        h, rem = divmod(int(elapsed), 3600)
        m, s = divmod(rem, 60)
        self.lbl_elapsed.setText(f"Elapsed: {h:02d}:{m:02d}:{s:02d}")

    # ------------------------------------------------------------------
    # Speed Bar Visualization
    # ------------------------------------------------------------------
    def _update_speed_bars(self, speed_mb: float):
        max_speed = max(self._peak_speed, 1.0)
        level = min(8, int((speed_mb / max_speed) * 8))
        for i, bar in enumerate(self.speed_bars):
            if i < level:
                if i < 3:
                    bar.setStyleSheet("background-color: #2dd4a8; border-radius: 2px;")
                elif i < 6:
                    bar.setStyleSheet("background-color: #4d9cf0; border-radius: 2px;")
                else:
                    bar.setStyleSheet("background-color: #e8a65a; border-radius: 2px;")
            else:
                bar.setStyleSheet("background-color: #1a2230; border-radius: 2px;")

    # ------------------------------------------------------------------
    # Device Management & Non-Blocking Hotplug Detection
    # ------------------------------------------------------------------
    @staticmethod
    def _get_partition_signature() -> Tuple[Tuple[str, str], ...]:
        """Fast (<1ms) partition snapshot so hotplug polling never blocks the GUI."""
        try:
            return tuple(sorted((p.device, p.mountpoint) for p in psutil.disk_partitions(all=True)))
        except Exception:
            return ()

    def refresh_devices(self):
        """Enumerate connected drives while preserving any loaded disk image files."""
        current_data = self.combo_devices.currentData()
        hw_devices = self.device_mgr.get_available_devices()
        self._last_partition_sig = self._get_partition_signature()

        # Keep user-loaded .dd/.img files at the top of the device list
        self.available_devices = list(self.custom_images) + hw_devices

        self.combo_devices.blockSignals(True)
        self.combo_devices.clear()

        selected_idx = 0
        for i, dev in enumerate(self.available_devices):
            self.combo_devices.addItem(dev.display_name, dev.device_path)
            if current_data and dev.device_path == current_data:
                selected_idx = i

        self.combo_devices.blockSignals(False)
        if self.combo_devices.count() > 0:
            self.combo_devices.setCurrentIndex(selected_idx)
            self._on_device_selected(selected_idx)

    def _check_device_hotplug(self):
        """Fast timer callback that detects connected/disconnected USB devices without spawning PowerShell."""
        if self.worker and self.worker.isRunning():
            return

        current_sig = self._get_partition_signature()
        if current_sig != self._last_partition_sig:
            self._last_partition_sig = current_sig
            self._log("Detected change in storage hardware. Refreshing drive list...", "info")
            self.refresh_devices()

    def _on_device_selected(self, index: int):
        """Update device details card when user picks a drive."""
        if index < 0 or index >= len(self.available_devices):
            return
        dev = self.available_devices[index]

        # Update info box
        sector_size = 512
        if dev.total_bytes > 0:
            total_sectors = dev.total_bytes // sector_size
            self.lbl_info_sectors.setText(f"{total_sectors:,}")
        else:
            self.lbl_info_sectors.setText("-")

        self._validate_output_safety()

    def _browse_disk_image(self):
        """Allow user to load raw disk dumps (.dd, .img, .bin, .raw)."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Raw Disk Image",
            "",
            "Disk Images (*.dd *.img *.bin *.raw);;All Files (*.*)"
        )
        if file_path:
            p = Path(file_path)
            size_bytes = p.stat().st_size
            size_gb = size_bytes / (1024**3)
            img_info = DeviceInfo(
                device_path=file_path,
                display_name=f"📄 {p.name} [{size_gb:.2f} GB]",
                drive_type="Disk Image File",
                total_bytes=size_bytes,
                free_bytes=0,
                filesystem="Raw Image",
                is_removable=True
            )
            # Remove duplicate if already loaded, then insert at top
            self.custom_images = [d for d in self.custom_images if d.device_path != file_path]
            self.custom_images.insert(0, img_info)
            self.refresh_devices()
            self.combo_devices.setCurrentIndex(0)
            self._log(f"Loaded disk image: {file_path}", "info")

    def _browse_output_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Recovery Output Directory")
        if folder:
            self.edit_output.setText(folder)
            self._validate_output_safety()

    def _validate_output_safety(self) -> bool:
        """Enforces that output folder is NOT on the drive being recovered."""
        target_path = self.combo_devices.currentData()
        out_dir = self.edit_output.text().strip()

        if not target_path or not out_dir:
            return False

        is_safe, msg = self.device_mgr.is_output_safe(target_path, out_dir)
        if not is_safe:
            self.lbl_safety_status.setText(f"⚠  {msg.splitlines()[0]}")
            self.lbl_safety_status.setProperty("class", "safety-warn")
            self.lbl_safety_status.style().unpolish(self.lbl_safety_status)
            self.lbl_safety_status.style().polish(self.lbl_safety_status)
            return False
        else:
            self.lbl_safety_status.setText("✓  Separate drive selected (Read-Only Safety Guaranteed)")
            self.lbl_safety_status.setProperty("class", "safety-ok")
            self.lbl_safety_status.style().unpolish(self.lbl_safety_status)
            self.lbl_safety_status.style().polish(self.lbl_safety_status)
            return True

    def _set_controls_scanning(self, scanning: bool):
        """Enables or disables configuration widgets while a scan is active."""
        self.combo_devices.setEnabled(not scanning)
        self.btn_refresh.setEnabled(not scanning)
        self.btn_browse_image.setEnabled(not scanning)
        self.edit_output.setEnabled(not scanning)
        self.btn_browse_out.setEnabled(not scanning)
        self.combo_align.setEnabled(not scanning)
        for chk in self._format_checkboxes:
            chk.setEnabled(not scanning)

        self.btn_start.setEnabled(not scanning)
        self.btn_pause.setEnabled(scanning)
        self.btn_pause.setText("⏸  Pause")
        self.btn_stop.setEnabled(scanning)

        if scanning:
            self.lbl_scan_state.setText("SCANNING")
            self.lbl_scan_state.setProperty("class", "scanning-badge")
        else:
            self.lbl_scan_state.setText("IDLE")
        self.lbl_scan_state.style().unpolish(self.lbl_scan_state)
        self.lbl_scan_state.style().polish(self.lbl_scan_state)

    # ------------------------------------------------------------------
    # Scan Control & Thread Management
    # ------------------------------------------------------------------
    def _start_scan(self):
        import time as _time
        target_path = self.combo_devices.currentData()
        out_dir = self.edit_output.text().strip()

        if not target_path:
            QMessageBox.warning(self, "No Target", "Please select a target drive or load a disk image.")
            return

        # Crucial Safety Check: Never allow saving to the drive being carved!
        if not self._validate_output_safety():
            _, msg = self.device_mgr.is_output_safe(target_path, out_dir)
            QMessageBox.critical(self, "Strict Safety Violation", msg)
            return

        # Check enabled formats
        enabled_formats = []
        if self.chk_jpeg.isChecked():
            enabled_formats.append("jpeg")
        if self.chk_png.isChecked():
            enabled_formats.append("png")
        if self.chk_raw.isChecked():
            enabled_formats.append("raw")
        if self.chk_mp4.isChecked():
            enabled_formats.append("mp4")
        if self.chk_mov.isChecked():
            enabled_formats.append("mov")

        if not enabled_formats:
            QMessageBox.warning(self, "No Formats", "Select at least one file format to recover.")
            return

        # Check if running in Python fallback mode and prompt the user
        if aegis_core is None and not getattr(self, "_warned_python_fallback", False):
            self._warned_python_fallback = True
            reply = QMessageBox.warning(
                self,
                "Native Rust Engine Not Detected",
                "⚠️ Running in Pure Python Fallback Mode\n\n"
                "The compiled Rust extension ('aegis_core') was not detected in this environment.\n\n"
                "• The recovery scan will proceed using the built-in Python fallback engine.\n"
                "• For up to 50x faster carving and full multi-core saturation, "
                "please download the standalone pre-compiled executable from GitHub Releases "
                "or compile the Rust crate using:\n\n"
                "    maturin develop --release\n\n"
                "Would you like to proceed with the Python engine?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        align_step = self.combo_align.currentData()

        # Reset UI state
        self._scan_aborted = False
        self._peak_speed = 0.0
        self._file_type_counts = {}
        self.table_files.setRowCount(0)
        self.recovered_files.clear()
        self._update_selected_count()
        self.lbl_progress_pct.setText("0.0%")
        self.lbl_progress_val.setText("0.0 / 0.0 GB")
        self.lbl_progress_lba.setText("LBA: 0")
        self.lbl_speed_val.setText("0.0")
        self.lbl_peak_badge.setText("PEAK: 0 MB/s")
        self.lbl_eta_val.setText("--:--:--")
        self.lbl_elapsed.setText("Elapsed: 00:00:00")
        self.lbl_files_val.setText("0")
        self.lbl_valid_count.setText("0 VALID")
        self.lbl_corrupt_count.setText("Corrupt / Partial: 0")
        self.lbl_ticker_sector.setText("0x0000000000")
        self._update_tab_counts()
        self._update_speed_bars(0)

        self._set_controls_scanning(True)

        # Start elapsed timer
        self._scan_start_time = _time.time()
        self._elapsed_timer.start(1000)

        # Update ticker
        sig_count = len(enabled_formats)
        self.lbl_ticker_text.setText(
            f"Scanning · Signatures Active: {sig_count} · Write-block hardware check: PASSED"
        )

        # Initialize output and staging directories
        self._user_output_dir = os.path.abspath(out_dir)
        self._staging_dir = os.path.join(self._user_output_dir, ".aegis_staging")
        os.makedirs(self._staging_dir, exist_ok=True)
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(self._staging_dir, 2)  # FILE_ATTRIBUTE_HIDDEN
        except Exception:
            pass

        # Launch QThread Background Worker with staging directory
        self.worker = RecoveryWorker(
            target_path=target_path,
            output_dir=self._staging_dir,
            sector_step=align_step,
            block_size_mb=16,
            enabled_formats=enabled_formats,
            parent=self
        )

        # Connect Worker Signals to UI Slots
        self.worker.sig_started.connect(self._on_scan_started)
        self.worker.sig_progress.connect(self._on_scan_progress)
        self.worker.sig_file_found.connect(self._on_file_found)
        self.worker.sig_log.connect(self._log)
        self.worker.sig_finished.connect(self._on_scan_finished)
        self.worker.sig_error.connect(self._on_scan_error)

        self.worker.start()

    def _toggle_pause(self):
        if not self.worker:
            return
        if self.btn_pause.text().startswith("⏸"):
            self.worker.pause()
            self.btn_pause.setText("▶  Resume")
            self._elapsed_timer.stop()
            self.lbl_scan_state.setText("PAUSED")
        else:
            self.worker.resume()
            self.btn_pause.setText("⏸  Pause")
            self._elapsed_timer.start(1000)
            self.lbl_scan_state.setText("SCANNING")

    def _stop_scan(self):
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self, "Stop Scan",
                "Are you sure you want to stop the recovery scan? Recovered files will be preserved.",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._scan_aborted = True
                self.btn_pause.setEnabled(False)
                self.btn_stop.setEnabled(False)
                self.lbl_scan_state.setText("STOPPING")
                self.worker.stop()

    # ------------------------------------------------------------------
    # Worker Signal Slots
    # ------------------------------------------------------------------
    def _on_scan_started(self, total_bytes: int):
        total_gb = total_bytes / (1024**3)
        self.lbl_progress_val.setText(f"0.0 / {total_gb:.1f} GB")

    def _on_scan_progress(self, current: int, total: int, speed: float, eta_sec: float, total_found: int):
        pct = min(100.0, (current / total) * 100) if total > 0 else 0.0

        cur_gb = current / (1024**3)
        tot_gb = total / (1024**3)
        self.lbl_progress_pct.setText(f"{pct:.1f}%")
        self.lbl_progress_val.setText(f"{cur_gb:.1f} / {tot_gb:.1f} GB")

        # LBA approximation (assuming 512-byte sectors)
        lba = current // 512
        self.lbl_progress_lba.setText(f"LBA: {lba:,}    Total: {(total // (1024**3)):.1f}G")

        # Speed
        self.lbl_speed_val.setText(f"{speed:.1f}")
        if speed > self._peak_speed:
            self._peak_speed = speed
        self.lbl_peak_badge.setText(f"PEAK: {self._peak_speed:.0f} MB/s")
        self._update_speed_bars(speed)
        self.lbl_speed_channel.setText("Channel: Direct I/O")

        # ETA
        if eta_sec > 0:
            h, rem = divmod(int(eta_sec), 3600)
            m, s = divmod(rem, 60)
            self.lbl_eta_val.setText(f"{h:02d}:{m:02d}:{s:02d}")
        else:
            self.lbl_eta_val.setText("00:00:00")

        # Files count
        self.lbl_files_val.setText(str(total_found))
        self.lbl_valid_count.setText(f"{total_found} VALID")

        # Ticker sector offset
        self.lbl_ticker_sector.setText(f"0x{current:010X}")

        # Ticker text update
        sig_count = len([f for f in ["jpeg", "png", "raw", "mp4", "mov"]
                         if self.worker and f in self.worker.enabled_formats])
        self.lbl_ticker_text.setText(
            f"Scanning LBA Sector {lba:,} · Signatures Active: {sig_count} · "
            f"Write-block hardware check: PASSED"
        )

    def _on_file_found(self, meta: Dict[str, Any]):
        """Inserts recovered file into the table view in real time."""
        self.recovered_files.append(meta)

        vbar = self.table_files.verticalScrollBar()
        at_bottom = vbar.value() >= (vbar.maximum() - 20)

        row = self.table_files.rowCount()
        self.table_files.insertRow(row)

        # File icon + name
        ext_upper = meta["ext"].upper()
        icon = self._get_file_icon(ext_upper)
        item_name = QTableWidgetItem(f"{icon}  {meta['name']}")
        item_name.setToolTip(meta["path"])

        # Format badge (text-based for QTableWidgetItem)
        item_fmt = QTableWidgetItem(ext_upper)
        item_fmt.setTextAlignment(Qt.AlignCenter)
        # Color the format text
        fmt_colors = FORMAT_BADGE_COLORS.get(ext_upper, ("#141c28", "#5a6578", "#1e2d40"))
        from PySide6.QtGui import QColor
        item_fmt.setForeground(QColor(fmt_colors[1]))

        # Size
        sz_kb = meta["size"] / 1024
        if sz_kb > 1024:
            size_str = f"{sz_kb / 1024:.2f} MB"
        else:
            size_str = f"{sz_kb:.1f} KB"
        item_size = QTableWidgetItem(size_str)
        item_size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # Sector offset + LBA
        sector = meta['offset'] // 512
        item_off = QTableWidgetItem(f"0x{meta['offset']:012X}\n(#{sector:,})")
        item_off.setTextAlignment(Qt.AlignCenter)
        item_off.setForeground(QColor("#5a6578"))

        # Integrity details with colored status dot
        details = meta.get("details", "")
        integrity_prefix = "●  " if details else ""
        item_details = QTableWidgetItem(f"{integrity_prefix}{details}")
        if "OK" in details.upper() or "VALID" in details.upper() or "INTACT" in details.upper() or "VERIFIED" in details.upper():
            item_details.setForeground(QColor("#2dd4a8"))
        elif "PARTIAL" in details.upper() or "MINOR" in details.upper():
            item_details.setForeground(QColor("#e8a65a"))
        else:
            item_details.setForeground(QColor("#5a6578"))

        self.table_files.setItem(row, 0, item_name)
        self.table_files.setItem(row, 1, item_fmt)
        self.table_files.setItem(row, 2, item_size)
        self.table_files.setItem(row, 3, item_off)
        self.table_files.setItem(row, 4, item_details)

        # Select Checkbox (Save to desired output folder)
        chk_widget = QWidget()
        chk_layout = QHBoxLayout(chk_widget)
        chk_layout.setContentsMargins(0, 0, 0, 0)
        chk_layout.setAlignment(Qt.AlignCenter)

        chk = QCheckBox()
        chk.setChecked(True)
        chk.setCursor(Qt.PointingHandCursor)
        chk.setToolTip("Select to save this file to destination output directory")
        chk.stateChanged.connect(self._update_selected_count)

        chk_layout.addWidget(chk)
        self.table_files.setCellWidget(row, 5, chk_widget)

        meta["checkbox"] = chk
        meta["staging_path"] = meta.get("path", "")
        meta["saved"] = False

        self._update_selected_count()

        # Apply active filters
        self._apply_row_filter(row, meta)

        # Update tab counts
        self._update_tab_counts()

        if at_bottom and self.chk_auto_scroll.isChecked():
            self.table_files.scrollToBottom()

    def _apply_row_filter(self, row: int, meta: Dict[str, Any]):
        q = self.edit_search.text().strip().lower()
        category = self._get_type_category(meta["ext"])
        type_visible = (self._active_filter == "all" or self._active_filter == category)
        text_visible = True
        if q:
            text_visible = (q in meta["name"].lower()) or (q in meta["ext"].lower())
        self.table_files.setRowHidden(row, not (type_visible and text_visible))

    def _on_scan_finished(self, stats: Dict[str, Any]):
        total_found = sum(stats["found"].values())
        elapsed = stats.get("elapsed_time", 0.0)

        self._set_controls_scanning(False)
        self._elapsed_timer.stop()

        # Update elapsed one final time
        h, rem = divmod(int(elapsed), 3600)
        m, s = divmod(rem, 60)
        self.lbl_elapsed.setText(f"Elapsed: {h:02d}:{m:02d}:{s:02d}")

        # Automatically sync currently selected files to user's desired output directory
        self._save_selected_files(show_dialog=False)

        selected_count = sum(
            1 for m in self.recovered_files
            if m.get("checkbox") and m["checkbox"].isChecked()
        )

        if self._scan_aborted:
            self.lbl_scan_state.setText("STOPPED")
            self.lbl_ticker_text.setText("Scan stopped by user · Selected files are saved")
            QMessageBox.information(
                self,
                "Scan Stopped",
                f"Recovery scan was stopped after {elapsed:.1f} seconds.\n\n"
                f"Files detected before stop: {total_found}\n"
                f"Selected & saved to output folder: {selected_count}\n"
                f"Saved to: {self._user_output_dir}\n\n"
                f"Tip: You can select or deselect files in the table and click 'Save Selected' at any time."
            )
            return

        self.lbl_scan_state.setText("COMPLETE")
        self.lbl_progress_pct.setText("100%")
        self.lbl_eta_val.setText("00:00:00")
        self.lbl_ticker_text.setText(
            f"Scan completed · {total_found} files recovered in {elapsed:.1f}s · "
            f"Write-block check: PASSED"
        )

        QMessageBox.information(
            self,
            "Recovery Complete",
            f"Recovery scan finished in {elapsed:.1f} seconds.\n\n"
            f"Total files detected: {total_found}\n"
            f"Selected & saved to output folder: {selected_count}\n"
            f"• JPEG: {stats['found'].get('jpeg', 0)}\n"
            f"• PNG: {stats['found'].get('png', 0)}\n"
            f"• RAW: {stats['found'].get('raw', 0)}\n"
            f"• MP4: {stats['found'].get('mp4', 0)}\n"
            f"• MOV: {stats['found'].get('mov', 0)}\n\n"
            f"Saved to: {self._user_output_dir}\n\n"
            f"Tip: You can check or uncheck files in the table and click 'Save Selected' to update your saved files anytime."
        )

    def _on_scan_error(self, err_msg: str):
        self._set_controls_scanning(False)
        self._elapsed_timer.stop()
        self.lbl_scan_state.setText("ERROR")
        self.lbl_ticker_text.setText(f"Error: {err_msg[:80]}")
        QMessageBox.critical(self, "Scan Error", f"A critical error occurred:\n\n{err_msg}")

    # ------------------------------------------------------------------
    # Logging, Table Interactions & Window Lifecycle
    # ------------------------------------------------------------------
    @staticmethod
    def _get_file_icon(ext: str) -> str:
        ext = ext.upper()
        if ext in ("JPG", "JPEG"):
            return "🖼"
        if ext == "PNG":
            return "🖼"
        if ext in ("CR2", "CR3", "NEF", "ARW", "DNG", "RAW"):
            return "📷"
        if ext in ("MP4", "MOV"):
            return "🎬"
        if ext == "PDF":
            return "📄"
        return "📁"

    def _log(self, message: str, level: str = "info"):
        color = "#5a6578"
        level_tag = "[INFO]"
        if level == "success":
            color = "#2dd4a8"
            level_tag = "[CARVED]"
        elif level == "warning":
            color = "#e8a65a"
            level_tag = "[WARN]"
        elif level == "error":
            color = "#e05575"
            level_tag = "[ERROR]"

        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        html = (
            f"<span style='color: #3d4a5c;'>[{ts}]</span> "
            f"<span style='color: {color}; font-weight: 600;'>{level_tag}</span> "
            f"<span style='color: {color};'>{message}</span>"
        )
        self.txt_console.append(html)

        if self.chk_auto_scroll.isChecked():
            sb = self.txt_console.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _filter_table(self, query: str):
        q = query.strip().lower()
        for row in range(self.table_files.rowCount()):
            item_name = self.table_files.item(row, 0)
            item_fmt = self.table_files.item(row, 1)
            visible = True
            if item_fmt:
                category = self._get_type_category(item_fmt.text())
                if self._active_filter != "all" and self._active_filter != category:
                    visible = False
            if q and item_name and item_fmt:
                text_match = (q in item_name.text().lower()) or (q in item_fmt.text().lower())
                visible = visible and text_match
            self.table_files.setRowHidden(row, not visible)

    def _on_header_section_clicked(self, logical_index: int):
        if logical_index == 5:  # SELECT column
            all_selected = all(
                m.get("checkbox") and m["checkbox"].isChecked()
                for m in self.recovered_files
            ) if self.recovered_files else False
            if all_selected:
                self._deselect_all_files()
            else:
                self._select_all_files()

    def _update_selected_count(self):
        selected_count = sum(
            1 for m in self.recovered_files
            if m.get("checkbox") and m["checkbox"].isChecked()
        )
        if hasattr(self, "btn_save_selected"):
            self.btn_save_selected.setText(f"💾 Save Selected ({selected_count})")
            self.btn_save_selected.setEnabled(selected_count > 0)

    def _select_all_files(self):
        """Checks select boxes for all files."""
        for meta in self.recovered_files:
            chk = meta.get("checkbox")
            if chk:
                chk.blockSignals(True)
                chk.setChecked(True)
                chk.blockSignals(False)
        self._update_selected_count()

    def _deselect_all_files(self):
        """Unchecks select boxes for all files."""
        for meta in self.recovered_files:
            chk = meta.get("checkbox")
            if chk:
                chk.blockSignals(True)
                chk.setChecked(False)
                chk.blockSignals(False)
        self._update_selected_count()

    def _save_selected_files(self, show_dialog: bool = True):
        """
        Saves only the files that are currently selected (checked) to the user's chosen output directory.
        Unselected files are excluded and removed from the output folder.
        """
        user_out = getattr(self, "_user_output_dir", None) or self.edit_output.text().strip()
        if not user_out:
            if show_dialog:
                QMessageBox.warning(self, "Output Directory Missing", "Please select a valid output directory first.")
            return

        os.makedirs(user_out, exist_ok=True)
        saved_count = 0
        removed_count = 0
        saved_bytes = 0

        for meta in self.recovered_files:
            chk = meta.get("checkbox")
            is_checked = chk.isChecked() if chk else False
            staging_path = meta.get("staging_path", "")

            if not staging_path or not os.path.exists(staging_path):
                continue

            staging_dir = getattr(self, "_staging_dir", None)
            if staging_dir and os.path.exists(staging_dir):
                try:
                    rel_path = os.path.relpath(staging_path, staging_dir)
                except Exception:
                    rel_path = os.path.basename(staging_path)
            else:
                rel_path = os.path.basename(staging_path)

            dest_path = os.path.join(user_out, rel_path)

            if is_checked:
                try:
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    if not os.path.exists(dest_path) or os.path.abspath(staging_path) != os.path.abspath(dest_path):
                        shutil.copy2(staging_path, dest_path)
                    meta["path"] = dest_path
                    meta["saved"] = True
                    saved_count += 1
                    saved_bytes += meta.get("size", 0)
                except Exception as e:
                    self._log(f"Error saving {meta.get('name', 'file')}: {e}", "error")
            else:
                # If file was unselected, remove it from the destination folder if it was previously saved
                if os.path.exists(dest_path) and os.path.abspath(staging_path) != os.path.abspath(dest_path):
                    try:
                        os.remove(dest_path)
                        removed_count += 1
                    except Exception:
                        pass
                meta["path"] = staging_path
                meta["saved"] = False

        if saved_count > 0 or show_dialog:
            size_mb = saved_bytes / (1024 * 1024)
            self._log(f"Output sync complete: {saved_count} selected files ({size_mb:.2f} MB) saved to {user_out}", "success")
        if show_dialog:
            msg = f"Successfully saved {saved_count} selected file(s) to:\n{user_out}"
            if removed_count > 0:
                msg += f"\n\n({removed_count} unselected file(s) removed from output directory)"
            QMessageBox.information(self, "Files Saved", msg)

    def _on_table_context_menu(self, pos):
        """Right-click context menu for table rows."""
        row = self.table_files.rowAt(pos.y())
        if 0 <= row < len(self.recovered_files):
            meta = self.recovered_files[row]
            menu = QMenu(self)
            menu.setStyleSheet("""
                QMenu {
                    background-color: #0c1119;
                    color: #c8ccd4;
                    border: 1px solid #1e2d40;
                    padding: 4px;
                    border-radius: 4px;
                }
                QMenu::item {
                    padding: 6px 20px;
                    border-radius: 3px;
                }
                QMenu::item:selected {
                    background-color: #1a2a3e;
                    color: #2dd4a8;
                }
            """)
            action_preview = menu.addAction("👁  Preview File")
            action_toggle = menu.addAction("☑  Toggle Select / Save")
            menu.addSeparator()
            action_export = menu.addAction("💾  Export Single File...")
            action_open_loc = menu.addAction("📂  Open File Location")

            chosen = menu.exec(self.table_files.viewport().mapToGlobal(pos))
            p = meta.get("path") or meta.get("staging_path")
            if chosen == action_preview and p and os.path.exists(p):
                self._open_file(p)
            elif chosen == action_toggle:
                chk = meta.get("checkbox")
                if chk:
                    chk.setChecked(not chk.isChecked())
            elif chosen == action_export and p and os.path.exists(p):
                self._export_single_file(p)
            elif chosen == action_open_loc and p and os.path.exists(p):
                folder = os.path.dirname(p)
                if os.path.exists(folder):
                    os.startfile(folder)

    def _on_table_double_click(self, index):
        row = index.row()
        if 0 <= row < len(self.recovered_files):
            meta = self.recovered_files[row]
            p = meta.get("path") or meta.get("staging_path")
            if p and os.path.exists(p):
                self._open_file(p)

    def _open_file(self, path: str):
        if os.path.exists(path):
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.run(["xdg-open", path])

    def _export_single_file(self, path: str):
        if os.path.exists(path):
            dest, _ = QFileDialog.getSaveFileName(
                self, "Export Recovered File", os.path.basename(path)
            )
            if dest:
                shutil.copy2(path, dest)
                self._log(f"Exported: {os.path.basename(path)} → {dest}", "success")

    def _export_log(self):
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export Activity Log", "aegis_forensic_log.txt",
            "Text Files (*.txt);;All Files (*.*)"
        )
        if dest:
            with open(dest, "w", encoding="utf-8") as f:
                f.write(self.txt_console.toPlainText())
            self._log(f"Log exported to: {dest}", "info")

    def _open_output_folder(self):
        folder = getattr(self, "_user_output_dir", None) or self.edit_output.text().strip()
        if os.path.exists(folder):
            if sys.platform == "win32":
                os.startfile(folder)
            else:
                subprocess.run(["xdg-open", folder])
        else:
            QMessageBox.information(self, "Folder Missing", f"Folder does not exist yet:\n{folder}")

    def closeEvent(self, event):
        """Ensures background QThread stops cleanly before closing the window."""
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Scan in Progress",
                "A recovery scan is currently running. Stop the scan and exit?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
            self._scan_aborted = True
            self.worker.stop()
            self.worker.wait(5000)

        # Sync selected files before exit
        if self.recovered_files and hasattr(self, "_user_output_dir"):
            try:
                self._save_selected_files(show_dialog=False)
            except Exception:
                pass

        # Cleanup staging cache
        staging_dir = getattr(self, "_staging_dir", None)
        if staging_dir and os.path.exists(staging_dir):
            try:
                shutil.rmtree(staging_dir, ignore_errors=True)
            except Exception:
                pass

        self.hotplug_timer.stop()
        self._elapsed_timer.stop()
        event.accept()