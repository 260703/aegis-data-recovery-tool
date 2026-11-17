import os
import sys
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from core.device_manager import DeviceManager
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Aegis Recovery")
    app.setOrganizationName("AegisForensics")

    # Set application icon (works both in development and when bundled by PyInstaller)
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    icon_path = os.path.join(base_dir, "aegis.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    device_mgr = DeviceManager()
    is_admin = device_mgr.is_admin()

    window = MainWindow(is_admin=is_admin)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()