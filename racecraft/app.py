"""Main application entry point for RaceCraft Desktop"""

import argparse
import asyncio
import logging

from racecraft.log import setup_logging
import os
import sys
from pathlib import Path


DEFAULT_API_URL = os.environ.get("RACECRAFT_API_URL", "https://racecraft.ai")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="RaceCraft Desktop companion app")
    ap.add_argument("--api-url", default=DEFAULT_API_URL,
                    help="RaceCraft backend base URL (env RACECRAFT_API_URL)")
    ap.add_argument("--test", action="store_true",
                    help="generate simulated telemetry instead of attaching to a sim")
    ap.add_argument("--headless", action="store_true",
                    help="run one test session without UI and exit (implies --test)")
    ap.add_argument("--email", default=os.environ.get("RACECRAFT_EMAIL"),
                    help="login email (env RACECRAFT_EMAIL); enables headless password login")
    ap.add_argument("--password", default=os.environ.get("RACECRAFT_PASSWORD"),
                    help="login password (env RACECRAFT_PASSWORD)")
    ap.add_argument("--laps", type=int, default=int(os.environ.get("RACECRAFT_TEST_LAPS", "4")),
                    help="laps to simulate in --test mode")
    ap.add_argument("--time-scale", type=float,
                    default=float(os.environ.get("RACECRAFT_TEST_TIMESCALE", "1.0")),
                    help="simulated-time speedup factor in --test mode")
    ap.add_argument("--wait", action="store_true",
                    help="(headless) block until the analysis completes")
    return ap.parse_args(argv)


logger = logging.getLogger(__name__)


class RaceCraftApp:
    """Main application coordinator (Qt UI mode)"""

    def __init__(self, args):
        # Qt imports stay inside UI mode so --headless works without a display
        from PyQt6.QtWidgets import QApplication
        from qasync import QEventLoop
        from racecraft.ui.main_window import MainWindow
        from racecraft.ui.tray import RaceCraftTray
        from racecraft.auth import AuthenticationService
        from racecraft.collector import TelemetryCollector
        from racecraft.streaming import StreamingClient

        self.args = args
        self.qt_app = QApplication(sys.argv)

        # Use qasync for asyncio/Qt integration
        self.loop = QEventLoop(self.qt_app)
        asyncio.set_event_loop(self.loop)

        # Create services
        self.auth = AuthenticationService(args.api_url)
        self.streaming = StreamingClient(args.api_url, self.auth)
        self.collector = TelemetryCollector(streaming=self.streaming,
                                            test_mode=args.test)

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
        icon_path = Path("assets/icon.png")
        if icon_path.exists():
            return str(icon_path)
        return ""

    async def start(self):
        """Start the application"""
        logger.info(f"RaceCraft Desktop starting (API: {self.args.api_url}"
              f"{', TEST MODE' if self.args.test else ''})...")

        # Authenticate on startup
        credentials = None
        try:
            if self.args.email and self.args.password:
                credentials = await self.auth.login_with_password(
                    self.args.email, self.args.password)
            else:
                credentials = await self.auth.login_with_browser()
        except Exception as e:
            logger.info(f"Authentication error: {e}")

        if credentials:
            self.main_window.update_auth_status({
                "user_id": credentials.user_id,
                "license_tier": credentials.license_tier,
                "authorized": True,
            })
            self.tray.update_status("Authenticated")
            logger.info(f"Authenticated as user: {credentials.user_id}")
        else:
            self.main_window.update_auth_status({"authorized": False})
            self.tray.update_status("Not authenticated")
            self.main_window.show()
            logger.info("Authentication failed — telemetry will be collected locally only")
            self.collector.streaming = None  # no uploads without auth

        # Start telemetry collector
        logger.info("Starting telemetry collector...")
        await self.collector.start()

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
        logger.info(f"Game connected: {game_name}")
        self.tray.update_status(f"Connected: {game_name}")
        self.tray.show_notification(
            "RaceCraft Desktop",
            f"Connected to {game_name}!"
        )

    def _on_game_disconnected(self):
        """Called when game disconnects"""
        logger.info("Game disconnected")
        self.tray.update_status("Waiting for game")

    def _on_collector_error(self, error_msg: str):
        """Called when telemetry collector has an error"""
        logger.info(f"Collector error: {error_msg}")
        self.tray.update_status(f"Error: {error_msg}")

    def _on_exit(self):
        """Clean shutdown. quit() used to be called in the same tick as
        create_task(stop()) — the event loop died before stop() ran, so
        the final chunk flush and session end/submit were silently
        skipped on every exit (platform loop 3, T3). Quit only AFTER the
        collector has actually stopped."""
        logger.info("Shutting down RaceCraft Desktop...")
        asyncio.create_task(self._shutdown())

    async def _shutdown(self):
        try:
            await self.collector.stop()
        except Exception as e:
            logger.info(f"Shutdown error (continuing to quit): {e}")
        finally:
            self.qt_app.quit()


def main():
    """Main entry point"""
    setup_logging()
    args = parse_args()

    if args.headless:
        # No Qt at all — run one simulated session and exit
        from racecraft.headless import run_test_session
        if not (args.email and args.password):
            logger.info("--email and --password (or RACECRAFT_EMAIL/RACECRAFT_PASSWORD) "
                  "are required for --headless; hardcoded defaults were removed")
            sys.exit(2)
        rc = asyncio.run(run_test_session(
            args.api_url,
            args.email,
            args.password,
            laps=args.laps, time_scale=args.time_scale, wait=args.wait,
        ))
        sys.exit(rc)

    app = RaceCraftApp(args)
    with app.loop:
        app.loop.run_until_complete(app.start())
        app.loop.run_forever()


if __name__ == "__main__":
    main()
