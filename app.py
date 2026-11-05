"""
Aegis Data Recovery Suite - Application Entry Point
===================================================
Handles Windows UAC elevation, high DPI initialization, and launches the PySide6 desktop GUI.
"""

import os
import sys
import platform
import ctypes

# Ensure project root is in sys.path for standalone or packaged execution
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from ui.main_window import MainWindow


def is_running_as_admin() -> bool:
    """Checks if the current Python process has Administrator rights on Windows."""
    if platform.system() != "Windows":
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def elevate_to_admin() -> bool:
    """
    Triggers Windows UAC elevation prompt to restart the application as Administrator.
    Returns True if elevation was initiated, False if elevation was declined or unavailable.
    """
    if platform.system() != "Windows" or is_running_as_admin():
        return True

    # Check if user explicitly bypassed elevation with --no-elevate
    if "--no-elevate" in sys.argv:
        return False

    try:
        # Re-launch current script with 'runas' verb
        script_path = os.path.abspath(__file__)
        args = f'"{script_path}" ' + " ".join([f'"{a}"' for a in sys.argv[1:]])

        # ShellExecuteW returns > 32 on successful elevation trigger
        ret = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            sys.executable,
            args,
            None,
            1  # SW_SHOWNORMAL
        )
        if ret > 32:
            return True
    except Exception:
        pass

    return False


def main():
    # 1. Administrator Rights & UAC Check
    admin_state = is_running_as_admin()
    if not admin_state and platform.system() == "Windows" and "--no-elevate" not in sys.argv:
        elevated = elevate_to_admin()
        if elevated:
            # Terminate unprivileged parent instance
            sys.exit(0)

    app = QApplication(sys.argv)
    app.setApplicationName("Aegis Data Recovery")
    app.setOrganizationName("AegisForensics")

    # Ensure application base font has a safe positive point size
    base_font = app.font()
    if base_font.pointSize() <= 0:
        base_font.setPointSize(10)
    app.setFont(base_font)

    # Re-evaluate admin status in elevated instance
    admin_state = is_running_as_admin()

    print("=" * 65)
    print("     AEGIS DATA RECOVERY - FORENSIC DISK CARVER")
    print("=" * 65)
    print(f"[*] Admin Privileges : {'YES (Full Raw Disk Access Enabled)' if admin_state else 'NO (Disk Images Only)'}")
    print(f"[*] Platform         : {platform.system()} {platform.release()}")
    print("=" * 65)

    # 3. Launch Main GUI Window
    window = MainWindow(is_admin=admin_state)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
