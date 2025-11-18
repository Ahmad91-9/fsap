from PySide6.QtWidgets import (
    QVBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox,
    QWidget, QHBoxLayout, QMessageBox, QApplication, QMainWindow, QFrame
)
from PySide6.QtCore import Qt, Signal, QRect
from PySide6.QtGui import QIcon, QPixmap, QPainter
from styled_widget import StyledWidget
from loading_widget import LoadingOverlay
import sys
import os
from pathlib import Path


class LoginPage(StyledWidget):
    request_login = Signal(str, str)
    go_register = Signal()

    def __init__(self):
        super().__init__()
        self.loading_overlay = None
        self.init_ui()
        self.setup_loading_overlay()

    def paintEvent(self, event):
        """Draw background image scaled to widget size"""
        painter = QPainter(self)
        bg_path = Path(__file__).parent / "autonix_bg.png"

        if bg_path.exists():
            pix = QPixmap(str(bg_path))
            if not pix.isNull():
                scaled = pix.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                painter.drawPixmap(0, 0, scaled)

    def init_ui(self):
        """Initialize all UI elements"""
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(40, 40, 40, 40)

        # -------------------------------------------------------------------
        # Top image section
        # -------------------------------------------------------------------
        base_dir = Path(__file__).parent
        image_path = next(
            (p for p in base_dir.glob("*.ico") if p.name.lower() == "autonix.ico"),
            None
        )

        image_frame = QFrame()
        image_frame.setFixedSize(150, 150)
        image_frame.setStyleSheet("""
            QFrame {
                background-color: #f8f8f8;
                border: 0px solid #ccc;
                border-radius: 5px;
            }
        """)

        image_label = QLabel(alignment=Qt.AlignCenter)
        image_label.setScaledContents(True)
        if image_path and image_path.exists():
            pixmap = QPixmap(str(image_path))
            if pixmap.isNull():
                image_label.setText("Invalid image")
            else:
                scaled = pixmap.scaled(150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                image_label.setPixmap(scaled)
        else:
            image_label.setText("Image not found")

        frame_layout = QVBoxLayout(image_frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.addWidget(image_label)

        # Center image horizontally
        top_layout = QHBoxLayout()
        top_layout.addStretch()
        top_layout.addWidget(image_frame, alignment=Qt.AlignCenter)
        top_layout.addStretch()
        layout.addLayout(top_layout)

        # -------------------------------------------------------------------
        # Title and subtitle
        # -------------------------------------------------------------------
        title = QLabel("Welcome to Autonix")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        subtitle = QLabel("Please login to your Autonix account")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 16px; color: #CCCCCC; margin-bottom: 20px;")
        layout.addWidget(subtitle)

        # -------------------------------------------------------------------
        # Login form
        # -------------------------------------------------------------------
        form_container = QWidget()
        form_layout = QVBoxLayout(form_container)
        form_layout.setSpacing(15)

        # Email input
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Email")
        self.user_input.setMinimumHeight(40)
        form_layout.addWidget(self.user_input)

        # Password input
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setMinimumHeight(40)
        form_layout.addWidget(self.password_input)

        # Show password checkbox
        self.show_pass = QCheckBox("Show password")
        self.show_pass.toggled.connect(self.toggle_password)
        form_layout.addWidget(self.show_pass)

        layout.addWidget(form_container)

        # -------------------------------------------------------------------
        # Login button
        # -------------------------------------------------------------------
        self.login_btn = QPushButton("Login")
        self.login_btn.setMinimumHeight(45)
        self.login_btn.clicked.connect(self.on_login_clicked)
        layout.addWidget(self.login_btn)

        # -------------------------------------------------------------------
        # Register link
        # -------------------------------------------------------------------
        register_link_layout = QHBoxLayout()
        register_link_layout.addStretch()
        self.register_link = QPushButton("Create an Autonix account")
        self.register_link.setFlat(True)
        self.register_link.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #007ACC;
                font-weight: bold;
                text-decoration: underline;
                border: none;
            }
        """)
        self.register_link.clicked.connect(lambda: self.go_register.emit())
        register_link_layout.addWidget(self.register_link)
        register_link_layout.addStretch()
        layout.addLayout(register_link_layout)

        layout.addStretch()
        self.setLayout(layout)

    # -----------------------------------------------------------------------
    # Utility methods
    # -----------------------------------------------------------------------
    def setup_loading_overlay(self):
        """Set up the loading overlay for this page"""
        self.loading_overlay = LoadingOverlay(self, "Logging in to Autonix...")

    def resizeEvent(self, event):
        """Resize overlay when widget resizes"""
        super().resizeEvent(event)
        if self.loading_overlay:
            self.loading_overlay.resize(self.size())

    def toggle_password(self, checked):
        self.password_input.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    def on_login_clicked(self):
        """Handle login button click"""
        email = self.user_input.text().strip()
        password = self.password_input.text().strip()

        if not email or not password:
            QMessageBox.warning(self, "Input Required", "Please enter email and password.")
            return

        self.set_loading_state(True)
        self.request_login.emit(email, password)

    def set_loading_state(self, loading):
        """Enable/disable form during login"""
        self.user_input.setEnabled(not loading)
        self.password_input.setEnabled(not loading)
        self.login_btn.setEnabled(not loading)
        self.register_link.setEnabled(not loading)
        self.show_pass.setEnabled(not loading)

        if self.loading_overlay:
            if loading:
                self.loading_overlay.show_loading("Authenticating with Autonix...")
            else:
                self.loading_overlay.hide_loading()

    def login_completed(self, success=True):
        """Call after login finishes"""
        self.set_loading_state(False)


# ---------------------------------------------------------------------------
# Main launcher
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)

    icon_path = Path(__file__).parent / 'autonix.ico'
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = QMainWindow()
    window.setWindowTitle("Autonix Login")
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.setFixedSize(420, 520)

    # Center window
    screen = app.primaryScreen().availableGeometry()
    x = (screen.width() - window.width()) // 2
    y = (screen.height() - window.height()) // 2
    window.setGeometry(QRect(x, y, window.width(), window.height()))

    login_page = LoginPage()
    window.setCentralWidget(login_page)
    window.show()

    sys.exit(app.exec())

