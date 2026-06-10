"""System tray icon with menu for RaceCraft Desktop"""

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor
from PyQt6.QtCore import QObject, pyqtSignal, Qt


class RaceCraftTray(QObject):
    """System tray icon with context menu"""

    show_window_signal = pyqtSignal()
    exit_signal = pyqtSignal()

    def __init__(self, icon_path: str):
        super().__init__()

        # Create icon (use provided or generate simple one)
        icon = self._load_or_create_icon(icon_path)
        self.tray = QSystemTrayIcon(icon)

        # Create context menu
        menu = QMenu()

        show_action = QAction("Show RaceCraft", menu)
        show_action.triggered.connect(self.show_window_signal.emit)
        menu.addAction(show_action)

        menu.addSeparator()

        settings_action = QAction("Settings", menu)
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)

        menu.addSeparator()

        exit_action = QAction("Exit", menu)
        exit_action.triggered.connect(self.exit_signal.emit)
        menu.addAction(exit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)

    def show(self):
        """Show tray icon"""
        self.tray.show()

    def update_status(self, status: str):
        """Update tooltip with current status"""
        self.tray.setToolTip(f"RaceCraft - {status}")

    def show_notification(self, title: str, message: str):
        """Show system notification"""
        self.tray.showMessage(
            title,
            message,
            QSystemTrayIcon.MessageIcon.Information,
            3000
        )

    def _on_tray_activated(self, reason):
        """Handle tray icon click"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_window_signal.emit()

    def _open_settings(self):
        """Open settings dialog (TODO)"""
        # TODO: Implement settings dialog
        pass

    def _load_or_create_icon(self, icon_path: str) -> QIcon:
        """Load icon from path or create a simple fallback icon"""
        if icon_path:
            icon = QIcon(icon_path)
            if not icon.isNull():
                return icon

        # Create a simple colored square as fallback
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw a blue circle (racing theme)
        painter.setBrush(QColor(41, 128, 185))  # Nice blue color
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(4, 4, 56, 56)

        # Draw white "RC" text
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(painter.font())
        font = painter.font()
        font.setPixelSize(24)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "RC")

        painter.end()

        return QIcon(pixmap)
