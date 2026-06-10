"""Main application entry point for RaceCraft Desktop"""

import sys
import asyncio
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop
from racecraft.ui.main_window import MainWindow
from racecraft.ui.tray import RaceCraftTray
from racecraft.auth import AuthenticationService
from racecraft.collector import TelemetryCollector


class RaceCraftApp:
    """Main application coordinator"""

    def __init__(self):
        self.qt_app = QApplication(sys.argv)

        # Use qasync for asyncio/Qt integration
        self.loop = QEventLoop(self.qt_app)
        asyncio.set_event_loop(self.loop)

        # Create services
        # TODO: Replace with actual API URL from config
        self.auth = AuthenticationService("https://api.racecraft.example.com")
        self.collector = TelemetryCollector()

        # Create UI
        self.main_window = MainWindow()

        # Get icon path (use placeholder for now)
        icon_path = self._get_icon_path()
        self.tray = RaceCraftTray(icon_path)

        # Connect signals - UI
        self.tray.show_window_signal.connect(self.main_window.show)
        self.tray.exit_signal.connect(self._on_exit)

        # Connect signals - Telemetry collector
        self.collector.stats_updated.connect(self.main_window.update_telemetry_stats)
        self.collector.game_connected.connect(self._on_game_connected)
        self.collector.game_disconnected.connect(self._on_game_disconnected)
        self.collector.error_occurred.connect(self._on_collector_error)

    def _get_icon_path(self) -> str:
        """Get path to tray icon"""
        # Check if icon exists, otherwise use default
        icon_path = Path("assets/icon.png")
        if icon_path.exists():
            return str(icon_path)

        # Fall back to creating a simple icon or using system default
        # For now, return empty string (Qt will use default)
        return ""

    async def start(self):
        """Start the application"""
        print("RaceCraft Desktop starting...")

        # Authenticate on startup (skip if network unavailable - dev mode)
        try:
            credentials = await self.auth.validate_on_startup()

            if credentials:
                self.main_window.update_auth_status({
                    "user_id": credentials.user_id,
                    "license_tier": credentials.license_tier,
                    "authorized": True
                })
                self.tray.update_status("Authenticated")
                print(f"Authenticated as user: {credentials.user_id}")
            else:
                self.main_window.update_auth_status({"authorized": False})
                self.tray.update_status("Not authenticated")
                # Show window to prompt login
                self.main_window.show()
                print("Authentication required")

        except Exception as e:
            # Network error - skip authentication for development
            print(f"Authentication error: {e}")
            print("Continuing in offline mode (development)")
            self.main_window.update_auth_status({
                "user_id": "dev-mode",
                "license_tier": "development",
                "authorized": False
            })
            self.tray.update_status("Offline mode")
            self.main_window.show()

        # Start telemetry collector
        print("Starting telemetry collector...")
        await self.collector.start()

        # TODO: Start background services
        # asyncio.create_task(self.upload.retry_failed_uploads())

        # Show tray icon
        self.tray.show()

        # Start with window hidden if authenticated, shown otherwise
        if self.auth.is_authenticated:
            self.main_window.hide()
            self.tray.show_notification(
                "RaceCraft Desktop",
                "Running in background. Click tray icon to show window."
            )
        else:
            self.main_window.show()

    def _on_game_connected(self, game_name: str):
        """Called when game is detected and connected"""
        print(f"Game connected: {game_name}")
        self.tray.update_status(f"Connected: {game_name}")
        self.tray.show_notification(
            "RaceCraft Desktop",
            f"Connected to {game_name}!"
        )

    def _on_game_disconnected(self):
        """Called when game disconnects"""
        print("Game disconnected")
        self.tray.update_status("Waiting for game")

    def _on_collector_error(self, error_msg: str):
        """Called when telemetry collector has an error"""
        print(f"Collector error: {error_msg}")
        self.tray.update_status(f"Error: {error_msg}")

    def _on_exit(self):
        """Clean shutdown"""
        print("Shutting down RaceCraft Desktop...")
        # Stop collector
        asyncio.create_task(self.collector.stop())
        # TODO: Stop other services
        self.qt_app.quit()


def main():
    """Main entry point"""
    app = RaceCraftApp()

    with app.loop:
        app.loop.run_until_complete(app.start())
        app.loop.run_forever()


if __name__ == "__main__":
    main()
