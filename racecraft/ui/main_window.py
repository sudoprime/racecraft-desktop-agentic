"""Main application window for RaceCraft Desktop - Premium Edition"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QStatusBar, QCheckBox,
    QScrollArea, QSizeGrip, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, pyqtSlot, QPoint, QPropertyAnimation, QEasingCurve, QTimer, pyqtProperty
from PyQt6.QtGui import QPalette, QColor, QMouseEvent, QPainter, QLinearGradient, QBrush


class PulsingWidget(QWidget):
    """Widget with pulsing opacity animation"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._opacity = 1.0

        # Setup pulsing animation
        self.animation = QPropertyAnimation(self, b"opacity")
        self.animation.setDuration(2000)
        self.animation.setStartValue(0.6)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.animation.setLoopCount(-1)  # Infinite loop

    def get_opacity(self):
        return self._opacity

    def set_opacity(self, opacity):
        self._opacity = opacity
        self.update()

    opacity = pyqtProperty(float, get_opacity, set_opacity)

    def start_pulsing(self):
        self.animation.start()

    def stop_pulsing(self):
        self.animation.stop()
        self._opacity = 1.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setOpacity(self._opacity)
        super().paintEvent(event)


class PremiumCard(QFrame):
    """Premium card with gradient background, shadow, and glow effects"""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("premiumCard")

        # Add drop shadow effect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(32)
        shadow.setXOffset(0)
        shadow.setYOffset(8)
        shadow.setColor(QColor(0, 0, 0, 128))
        self.setGraphicsEffect(shadow)

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        if title:
            # Title label
            title_label = QLabel(title)
            title_label.setObjectName("cardTitle")
            layout.addWidget(title_label)


class MainWindow(QMainWindow):
    """Main application window with premium design"""

    # Premium color palette
    COLORS = {
        'bg_main': '#0A0A0B',
        'bg_card': '#14141A',
        'bg_card_hover': '#1A1A22',
        'border': 'rgba(255, 255, 255, 0.06)',
        'border_active': 'rgba(0, 217, 255, 0.4)',
        'text_primary': '#FFFFFF',
        'text_secondary': '#9CA3AF',
        'text_muted': '#6B7280',
        'accent_cyan': '#00D9FF',
        'accent_cyan_glow': 'rgba(0, 217, 255, 0.4)',
        'gradient_start': '#00D9FF',
        'gradient_end': '#0891B2',
        'success': '#10B981',
        'warning': '#EA580C',
        'warning_bg_start': '#7C2D12',
        'warning_bg_end': '#991B1B',
        'error': '#EF4444',
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RaceCraft Desktop")
        self.setMinimumSize(600, 700)
        self.resize(650, 750)

        # Frameless window
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)

        # Window dragging
        self.dragging = False
        self.drag_position = QPoint()

        # Debug mode
        self.debug_mode = False
        self.last_telemetry = None

        # Apply premium styling
        self._apply_premium_stylesheet()

        # Central widget
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Custom title bar
        title_bar = self._create_premium_title_bar()
        main_layout.addWidget(title_bar)

        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("scrollArea")
        scroll_widget = QWidget()
        scroll_widget.setObjectName("scrollContent")

        content_layout = QVBoxLayout(scroll_widget)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(16)

        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)

        # Authentication card
        auth_card = self._create_auth_card()
        content_layout.addWidget(auth_card)

        # Telemetry card
        telemetry_card = self._create_telemetry_card()
        content_layout.addWidget(telemetry_card)

        # Debug toggle
        self.debug_checkbox = QCheckBox("Show All Telemetry Channels")
        self.debug_checkbox.setObjectName("debugToggle")
        self.debug_checkbox.stateChanged.connect(self._on_debug_toggled)
        content_layout.addWidget(self.debug_checkbox)

        # Debug card (hidden by default)
        self.debug_card = self._create_debug_card()
        self.debug_card.setVisible(False)
        content_layout.addWidget(self.debug_card)

        # Upload card
        upload_card = self._create_upload_card()
        content_layout.addWidget(upload_card)

        content_layout.addStretch()

        # Premium status bar
        status_bar = self._create_status_bar()
        main_layout.addWidget(status_bar)

    def _create_premium_title_bar(self) -> QWidget:
        """Create premium title bar with gradient"""
        title_bar = QWidget()
        title_bar.setFixedHeight(48)
        title_bar.setObjectName("titleBar")

        layout = QHBoxLayout(title_bar)
        layout.setContentsMargins(16, 0, 8, 0)

        # Logo/title with glow effect
        title = QLabel("racecraft.ai")
        title.setObjectName("appTitle")
        layout.addWidget(title)

        # Connection status indicator
        self.connection_indicator = QLabel("●")
        self.connection_indicator.setObjectName("connectionDot")
        self.connection_indicator.setStyleSheet(f"""
            color: {self.COLORS['error']};
            font-size: 20px;
            padding: 0 8px;
        """)
        layout.addWidget(self.connection_indicator)

        layout.addStretch()

        # Window controls
        min_btn = QPushButton("−")
        min_btn.setObjectName("titleBarBtn")
        min_btn.setFixedSize(32, 32)
        min_btn.clicked.connect(self.showMinimized)
        layout.addWidget(min_btn)

        close_btn = QPushButton("×")
        close_btn.setObjectName("titleBarBtnClose")
        close_btn.setFixedSize(32, 32)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        # Enable dragging
        title_bar.mousePressEvent = self._title_bar_mouse_press
        title_bar.mouseMoveEvent = self._title_bar_mouse_move
        title_bar.mouseReleaseEvent = self._title_bar_mouse_release

        return title_bar

    def _create_auth_card(self) -> QWidget:
        """Create premium authentication card"""
        card = PremiumCard()
        layout = card.layout()

        # Header
        header = QLabel("🔐 AUTHENTICATION")
        header.setObjectName("cardTitle")
        layout.addWidget(header)

        # Info grid
        info_grid = QGridLayout()
        info_grid.setSpacing(12)
        info_grid.setContentsMargins(0, 8, 0, 8)

        # User ID
        user_label = QLabel("USER ID")
        user_label.setObjectName("dataLabel")
        info_grid.addWidget(user_label, 0, 0)

        self.user_id_value = QLabel("Not authenticated")
        self.user_id_value.setObjectName("dataValue")
        info_grid.addWidget(self.user_id_value, 0, 1)

        # License
        license_label = QLabel("LICENSE")
        license_label.setObjectName("dataLabel")
        info_grid.addWidget(license_label, 1, 0)

        self.license_value = QLabel("None")
        self.license_value.setObjectName("dataValue")
        info_grid.addWidget(self.license_value, 1, 1)

        layout.addLayout(info_grid)

        # Status badge with pulsing animation
        badge_container = QWidget()
        badge_container.setObjectName("badgeContainer")
        badge_layout = QHBoxLayout(badge_container)
        badge_layout.setContentsMargins(0, 12, 0, 12)

        self.auth_badge = PulsingWidget()
        self.auth_badge.setObjectName("statusBadgeWarning")
        badge_inner_layout = QHBoxLayout(self.auth_badge)
        badge_inner_layout.setContentsMargins(16, 8, 16, 8)

        self.auth_badge_label = QLabel("⚠ NOT AUTHENTICATED")
        self.auth_badge_label.setObjectName("badgeText")
        badge_inner_layout.addWidget(self.auth_badge_label)

        self.auth_badge.start_pulsing()
        badge_layout.addWidget(self.auth_badge)
        badge_layout.addStretch()

        layout.addWidget(badge_container)

        # Premium login button
        self.login_button = QPushButton("LOGIN TO RACECRAFT")
        self.login_button.setObjectName("loginBtn")
        self.login_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_button.clicked.connect(self._on_login_clicked)
        layout.addWidget(self.login_button)

        return card

    def _create_telemetry_card(self) -> QWidget:
        """Create premium telemetry data grid"""
        card = PremiumCard()
        layout = card.layout()

        # Header
        header = QLabel("⚡ TELEMETRY")
        header.setObjectName("cardTitle")
        layout.addWidget(header)

        # Data grid with borders
        grid_frame = QFrame()
        grid_frame.setObjectName("dataGrid")
        grid_layout = QGridLayout(grid_frame)
        grid_layout.setSpacing(0)
        grid_layout.setContentsMargins(0, 0, 0, 0)

        # Row data
        rows = [
            ("GAME", "game"),
            ("FPS", "fps"),
            ("FRAMES", "frames"),
            ("SPEED", "speed"),
            ("RPM", "rpm"),
            ("GEAR", "gear"),
            ("LAP", "lap"),
            ("DURATION", "duration"),
        ]

        self.telemetry_values = {}

        for idx, (label, key) in enumerate(rows):
            # Label cell
            label_widget = QLabel(label)
            label_widget.setObjectName("gridLabel")
            label_widget.setStyleSheet(f"""
                background-color: rgba(255, 255, 255, 0.02);
                border-right: 1px solid {self.COLORS['border']};
                border-bottom: 1px solid {self.COLORS['border']};
                padding: 12px 16px;
            """)
            grid_layout.addWidget(label_widget, idx, 0)

            # Value cell
            value_widget = QLabel("—")
            value_widget.setObjectName("gridValue")
            value_widget.setStyleSheet(f"""
                background-color: rgba(0, 0, 0, 0.2);
                border-bottom: 1px solid {self.COLORS['border']};
                padding: 12px 16px;
            """)
            grid_layout.addWidget(value_widget, idx, 1)

            # Indicator cell (for sparklines/status)
            indicator = QLabel("●")
            indicator.setObjectName("gridIndicator")
            indicator.setStyleSheet(f"""
                background-color: rgba(0, 0, 0, 0.2);
                border-bottom: 1px solid {self.COLORS['border']};
                padding: 12px 16px;
                color: {self.COLORS['error']};
                text-align: center;
            """)
            grid_layout.addWidget(indicator, idx, 2)

            self.telemetry_values[key] = {
                'value': value_widget,
                'indicator': indicator
            }

        # Set column stretch
        grid_layout.setColumnStretch(0, 1)  # Label
        grid_layout.setColumnStretch(1, 3)  # Value
        grid_layout.setColumnStretch(2, 1)  # Indicator

        layout.addWidget(grid_frame)

        return card

    def _create_debug_card(self) -> QWidget:
        """Create debug telemetry card"""
        card = PremiumCard()
        layout = card.layout()

        header = QLabel("🔍 ALL TELEMETRY CHANNELS")
        header.setObjectName("cardTitle")
        layout.addWidget(header)

        # Debug grid
        debug_grid = QGridLayout()
        debug_grid.setSpacing(8)

        self.debug_labels = {}

        # Driver inputs section
        debug_grid.addWidget(self._create_section_label("DRIVER INPUTS"), 0, 0, 1, 2)

        inputs = ['throttle', 'brake', 'clutch', 'steering']
        for idx, key in enumerate(inputs):
            label = QLabel(key.upper() + ":")
            label.setObjectName("debugLabel")
            debug_grid.addWidget(label, idx + 1, 0)

            value = QLabel("—")
            value.setObjectName("debugValue")
            debug_grid.addWidget(value, idx + 1, 1)

            self.debug_labels[key] = value

        # G-Forces
        row = 5
        debug_grid.addWidget(self._create_section_label("G-FORCES"), row, 0, 1, 2)
        row += 1

        gforces = ['g_lat', 'g_long', 'g_vert']
        for idx, key in enumerate(gforces):
            label = QLabel(key.upper() + ":")
            label.setObjectName("debugLabel")
            debug_grid.addWidget(label, row + idx, 0)

            value = QLabel("—")
            value.setObjectName("debugValue")
            debug_grid.addWidget(value, row + idx, 1)

            self.debug_labels[key] = value

        layout.addLayout(debug_grid)

        return card

    def _create_upload_card(self) -> QWidget:
        """Create upload status card"""
        card = PremiumCard()
        layout = card.layout()

        header = QLabel("📤 UPLOAD STATUS")
        header.setObjectName("cardTitle")
        layout.addWidget(header)

        # Status badge
        badge_container = QWidget()
        badge_layout = QHBoxLayout(badge_container)
        badge_layout.setContentsMargins(0, 8, 0, 8)

        self.upload_badge = QLabel("— NO PENDING SESSIONS")
        self.upload_badge.setObjectName("statusBadgeIdle")
        badge_layout.addWidget(self.upload_badge)
        badge_layout.addStretch()

        layout.addWidget(badge_container)

        # Info grid
        info_grid = QGridLayout()
        info_grid.setSpacing(12)

        last_label = QLabel("LAST UPLOAD")
        last_label.setObjectName("dataLabel")
        info_grid.addWidget(last_label, 0, 0)

        self.last_upload_value = QLabel("Never")
        self.last_upload_value.setObjectName("dataValue")
        info_grid.addWidget(self.last_upload_value, 0, 1)

        pending_label = QLabel("PENDING")
        pending_label.setObjectName("dataLabel")
        info_grid.addWidget(pending_label, 1, 0)

        self.pending_count_value = QLabel("0")
        self.pending_count_value.setObjectName("dataValue")
        info_grid.addWidget(self.pending_count_value, 1, 1)

        layout.addLayout(info_grid)

        return card

    def _create_status_bar(self) -> QWidget:
        """Create premium status bar"""
        status_widget = QWidget()
        status_widget.setObjectName("statusBar")
        status_widget.setFixedHeight(28)

        layout = QHBoxLayout(status_widget)
        layout.setContentsMargins(12, 4, 12, 4)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("statusText")
        layout.addWidget(self.status_label)

        layout.addStretch()

        # Resize grip
        grip = QSizeGrip(status_widget)
        grip.setFixedSize(16, 16)
        layout.addWidget(grip)

        return status_widget

    def _create_section_label(self, text: str) -> QLabel:
        """Create section header label"""
        label = QLabel(text)
        label.setObjectName("sectionHeader")
        return label

    # Mouse event handlers for window dragging
    def _title_bar_mouse_press(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _title_bar_mouse_move(self, event: QMouseEvent):
        if self.dragging:
            self.move(event.globalPosition().toPoint() - self.drag_position)

    def _title_bar_mouse_release(self, event: QMouseEvent):
        self.dragging = False

    # Update methods
    @pyqtSlot(dict)
    def update_auth_status(self, auth_data: dict):
        """Update authentication UI"""
        self.user_id_value.setText(auth_data.get('user_id', 'Unknown'))
        self.license_value.setText(auth_data.get('license_tier', 'Free'))

        if auth_data.get('authorized'):
            self.auth_badge.stop_pulsing()
            self.auth_badge.setObjectName("statusBadgeSuccess")
            self.auth_badge.setStyle(self.auth_badge.style())  # Force style refresh
            self.auth_badge_label.setText("✓ AUTHENTICATED")
            self.login_button.setEnabled(False)
            self.connection_indicator.setStyleSheet(f"color: {self.COLORS['success']}; font-size: 20px; padding: 0 8px;")
        else:
            self.auth_badge.start_pulsing()
            self.auth_badge.setObjectName("statusBadgeWarning")
            self.auth_badge.setStyle(self.auth_badge.style())
            self.auth_badge_label.setText("⚠ NOT AUTHENTICATED")
            self.login_button.setEnabled(True)
            self.connection_indicator.setStyleSheet(f"color: {self.COLORS['error']}; font-size: 20px; padding: 0 8px;")

    @pyqtSlot(dict)
    def update_session_info(self, session_data: dict):
        """Update session UI (compatibility)"""
        self.update_telemetry_stats(session_data)

    @pyqtSlot(dict)
    def update_telemetry_stats(self, stats: dict):
        """Update telemetry grid"""
        self.last_telemetry = stats

        # Update game
        game_name = stats.get('game_name', 'None')
        self.telemetry_values['game']['value'].setText(game_name)
        if game_name != 'None':
            self.telemetry_values['game']['indicator'].setStyleSheet(f"color: {self.COLORS['success']};")
            self.telemetry_values['game']['indicator'].setText("🟢")
        else:
            self.telemetry_values['game']['indicator'].setStyleSheet(f"color: {self.COLORS['error']};")
            self.telemetry_values['game']['indicator'].setText("🔴")

        # Update FPS
        fps = stats.get('frames_per_second', 0.0)
        self.telemetry_values['fps']['value'].setText(f"{fps:.1f} Hz")

        # Color code FPS
        if fps >= 50:
            color = self.COLORS['success']
        elif fps >= 30:
            color = self.COLORS['warning']
        else:
            color = self.COLORS['error']
        self.telemetry_values['fps']['value'].setStyleSheet(f"color: {color};")

        # Update frames
        frames = stats.get('frames_collected', 0)
        self.telemetry_values['frames']['value'].setText(f"{frames:,}")

        # Update speed
        speed = stats.get('last_speed', 0.0)
        self.telemetry_values['speed']['value'].setText(f"{speed:.1f} mph")

        # Update RPM
        rpm = stats.get('last_rpm', 0)
        self.telemetry_values['rpm']['value'].setText(f"{rpm:,}")

        # Update gear
        gear = stats.get('last_gear', 0)
        gear_str = "R" if gear == -1 else "N" if gear == 0 else str(gear)
        self.telemetry_values['gear']['value'].setText(gear_str)

        # Update lap
        lap = stats.get('current_lap', 0)
        self.telemetry_values['lap']['value'].setText(str(lap))

        # Update duration
        duration = stats.get('session_duration', 0)
        hours, remainder = divmod(duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.telemetry_values['duration']['value'].setText(
            f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"
        )

        # Update debug if enabled
        if self.debug_mode:
            self._update_debug_telemetry(stats)

    @pyqtSlot(dict)
    def update_upload_status(self, upload_data: dict):
        """Update upload status"""
        status = upload_data.get('status', 'idle')

        if status == 'uploading':
            self.upload_badge.setObjectName("statusBadgeActive")
            self.upload_badge.setText("⏳ UPLOADING...")
        elif status == 'complete':
            self.upload_badge.setObjectName("statusBadgeSuccess")
            self.upload_badge.setText("✓ UPLOAD COMPLETE")
        elif status == 'failed':
            self.upload_badge.setObjectName("statusBadgeError")
            self.upload_badge.setText("✗ UPLOAD FAILED")
        else:
            self.upload_badge.setObjectName("statusBadgeIdle")
            self.upload_badge.setText("— NO PENDING SESSIONS")

        self.upload_badge.setStyle(self.upload_badge.style())  # Force refresh

        if upload_data.get('last_upload_time'):
            self.last_upload_value.setText(upload_data['last_upload_time'])

        self.pending_count_value.setText(str(upload_data.get('pending_count', 0)))

    def _on_debug_toggled(self, state):
        """Handle debug toggle"""
        self.debug_mode = (state == Qt.CheckState.Checked.value)
        self.debug_card.setVisible(self.debug_mode)

        if self.debug_mode and self.last_telemetry:
            self._update_debug_telemetry(self.last_telemetry)

    def _update_debug_telemetry(self, stats: dict):
        """Update debug view"""
        import math
        raw = stats.get('raw_telemetry', {})

        # Driver inputs
        if 'throttle' in self.debug_labels:
            throttle = raw.get('Throttle', 0.0)
            brake = raw.get('Brake', 0.0)
            clutch = raw.get('Clutch', 0.0)
            steering = raw.get('SteeringWheelAngle', 0.0)

            self.debug_labels['throttle'].setText(f"{throttle*100:.1f}%")
            self.debug_labels['brake'].setText(f"{brake*100:.1f}%")
            self.debug_labels['clutch'].setText(f"{clutch*100:.1f}%")
            self.debug_labels['steering'].setText(f"{steering:.2f}°")

        # G-Forces
        if 'g_lat' in self.debug_labels:
            g_lat = raw.get('LatAccel', 0.0)
            g_long = raw.get('LongAccel', 0.0)
            g_vert = raw.get('VertAccel', 0.0)

            self.debug_labels['g_lat'].setText(f"{g_lat:.2f}G")
            self.debug_labels['g_long'].setText(f"{g_long:.2f}G")
            self.debug_labels['g_vert'].setText(f"{g_vert:.2f}G")

    def closeEvent(self, event):
        """Minimize to tray instead of close"""
        event.ignore()
        self.hide()

    def _on_login_clicked(self):
        """Handle login button"""
        pass

    def _apply_premium_stylesheet(self):
        """Apply premium stylesheet with gradients, shadows, and effects"""
        c = self.COLORS

        stylesheet = f"""
            /* Main window - deep black with subtle grid pattern */
            QMainWindow {{
                background-color: {c['bg_main']};
            }}

            QWidget {{
                background-color: transparent;
                color: {c['text_primary']};
                font-family: 'Inter', 'Segoe UI', sans-serif;
            }}

            #centralWidget {{
                background-color: {c['bg_main']};
                background-image:
                    linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px);
                background-size: 20px 20px;
            }}

            /* Premium cards with gradient and glow */
            #premiumCard {{
                background: qlineargradient(
                    spread:pad, x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(31, 31, 35, 255),
                    stop:0.5 rgba(25, 25, 29, 255),
                    stop:1 rgba(20, 20, 24, 255)
                );
                border: 1px solid {c['border']};
                border-radius: 12px;
                margin: 0px;
            }}

            #premiumCard:hover {{
                border: 1px solid {c['border_active']};
            }}

            /* Title bar */
            #titleBar {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(20, 20, 24, 255),
                    stop:1 rgba(14, 14, 18, 255)
                );
                border-bottom: 1px solid {c['border']};
            }}

            #appTitle {{
                color: {c['text_primary']};
                font-size: 18px;
                font-weight: 700;
                letter-spacing: 0.5px;
                text-shadow: 0 0 20px {c['accent_cyan_glow']};
            }}

            #titleBarBtn {{
                background-color: transparent;
                color: {c['text_secondary']};
                border: none;
                border-radius: 4px;
                font-size: 20px;
                font-weight: bold;
            }}

            #titleBarBtn:hover {{
                background-color: {c['bg_card_hover']};
                color: {c['text_primary']};
            }}

            #titleBarBtnClose:hover {{
                background-color: {c['error']};
                color: {c['text_primary']};
            }}

            /* Card titles */
            #cardTitle {{
                color: {c['text_secondary']};
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 1.5px;
                text-transform: uppercase;
                margin-bottom: 8px;
            }}

            /* Data labels and values */
            #dataLabel {{
                color: {c['text_muted']};
                font-size: 11px;
                font-weight: 500;
                letter-spacing: 0.5px;
                text-transform: uppercase;
            }}

            #dataValue {{
                color: {c['text_primary']};
                font-family: 'JetBrains Mono', 'Consolas', monospace;
                font-size: 14px;
                font-weight: 600;
            }}

            /* Data grid */
            #dataGrid {{
                border: 1px solid {c['border']};
                border-radius: 8px;
                overflow: hidden;
            }}

            #gridLabel {{
                color: {c['text_muted']};
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 0.5px;
                text-transform: uppercase;
            }}

            #gridValue {{
                color: {c['text_primary']};
                font-family: 'JetBrains Mono', 'Consolas', monospace;
                font-size: 16px;
                font-weight: 600;
                text-shadow: 0 0 8px {c['accent_cyan_glow']};
            }}

            #gridIndicator {{
                font-size: 16px;
            }}

            /* Status badges */
            #statusBadgeWarning {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {c['warning_bg_start']},
                    stop:1 {c['warning_bg_end']}
                );
                border: 1px solid rgba(239, 68, 68, 0.3);
                border-radius: 12px;
                padding: 8px 16px;
            }}

            #statusBadgeSuccess {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(16, 185, 129, 0.2),
                    stop:1 rgba(16, 185, 129, 0.3)
                );
                border: 1px solid {c['success']};
                border-radius: 12px;
                padding: 8px 16px;
            }}

            #statusBadgeActive {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(0, 217, 255, 0.2),
                    stop:1 rgba(8, 145, 178, 0.3)
                );
                border: 1px solid {c['accent_cyan']};
                border-radius: 12px;
                padding: 8px 16px;
            }}

            #statusBadgeError {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(239, 68, 68, 0.2),
                    stop:1 rgba(239, 68, 68, 0.3)
                );
                border: 1px solid {c['error']};
                border-radius: 12px;
                padding: 8px 16px;
            }}

            #statusBadgeIdle {{
                color: {c['text_muted']};
                font-size: 13px;
                font-weight: 500;
            }}

            #badgeText {{
                color: {c['text_primary']};
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 1px;
            }}

            /* Premium login button */
            #loginBtn {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {c['gradient_start']},
                    stop:1 {c['gradient_end']}
                );
                color: #000000;
                font-weight: 700;
                font-size: 14px;
                padding: 14px 32px;
                border: none;
                border-radius: 8px;
                min-height: 48px;
                letter-spacing: 1px;
            }}

            #loginBtn:hover {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #33E0FF,
                    stop:1 #0EA5E9
                );
            }}

            #loginBtn:pressed {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00B8D4,
                    stop:1 #0891B2
                );
            }}

            #loginBtn:disabled {{
                background-color: {c['bg_card_hover']};
                color: {c['text_muted']};
            }}

            /* Checkbox */
            #debugToggle {{
                color: {c['text_primary']};
                font-size: 13px;
                font-weight: 500;
                padding: 8px;
            }}

            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid {c['text_muted']};
                border-radius: 4px;
                background-color: rgba(0, 0, 0, 0.3);
            }}

            QCheckBox::indicator:checked {{
                background-color: {c['accent_cyan']};
                border-color: {c['accent_cyan']};
            }}

            QCheckBox::indicator:hover {{
                border-color: {c['accent_cyan']};
            }}

            /* Scroll area */
            #scrollArea {{
                border: none;
                background-color: transparent;
            }}

            #scrollContent {{
                background-color: transparent;
            }}

            QScrollBar:vertical {{
                background-color: transparent;
                width: 8px;
                margin: 0px;
            }}

            QScrollBar::handle:vertical {{
                background-color: rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                min-height: 30px;
            }}

            QScrollBar::handle:vertical:hover {{
                background-color: rgba(255, 255, 255, 0.2);
            }}

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}

            /* Status bar */
            #statusBar {{
                background-color: {c['bg_card']};
                border-top: 1px solid {c['border']};
            }}

            #statusText {{
                color: {c['text_muted']};
                font-size: 11px;
            }}

            /* Debug sections */
            #sectionHeader {{
                color: {c['accent_cyan']};
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1px;
                margin-top: 12px;
                margin-bottom: 6px;
            }}

            #debugLabel {{
                color: {c['text_muted']};
                font-size: 12px;
            }}

            #debugValue {{
                color: {c['text_primary']};
                font-family: 'Consolas', monospace;
                font-size: 13px;
                font-weight: 600;
            }}
        """

        self.setStyleSheet(stylesheet)
