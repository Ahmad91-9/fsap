from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QScrollArea, QMessageBox
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from ui.styled_widget import StyledWidget
from ui.loading_widget import LoadingOverlay
from config import GITHUB_APPS, LOCAL_APPS, get_app_icon


class AppCard(QWidget):
    """Modern app card widget"""
    launch_clicked = Signal(str, str, str, bool)  # name, description, path, is_local
    
    def __init__(self, name, description, icon_data, path, is_local=False, parent=None):
        super().__init__(parent)
        self.name = name
        self.description = description
        self.path = path
        self.is_local = is_local
        self.setup_ui(icon_data)
    
    def setup_ui(self, icon_data):
        """Set up the app card UI"""
        self.setFixedHeight(120)
        self.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #2D2D30, stop:1 #3E3E42);
                border-radius: 12px;
                padding: 10px;
            }
            QWidget:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #3E3E42, stop:1 #4E4E52);
                border: 2px solid #0078D7;
            }
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(15)
        
        # Icon
        icon_label = QLabel()
        icon_label.setFixedSize(80, 80)
        pix = get_app_icon(icon_data)
        if not pix.isNull():
            icon_label.setPixmap(pix.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            icon_label.setText("📱")
            icon_label.setStyleSheet("font-size: 48px;")
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)
        
        # Info section
        info_layout = QVBoxLayout()
        info_layout.setSpacing(5)
        
        # App name
        name_label = QLabel(self.name)
        name_label.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: white;
        """)
        info_layout.addWidget(name_label)
        
        # Description
        desc_label = QLabel(self.description)
        desc_label.setStyleSheet("""
            font-size: 12px;
            color: #CCCCCC;
        """)
        desc_label.setWordWrap(True)
        info_layout.addWidget(desc_label)
        
        info_layout.addStretch()
        layout.addLayout(info_layout, 1)
        
        # Launch button
        launch_btn = QPushButton("Launch")
        launch_btn.setFixedSize(100, 40)
        launch_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0078D7, stop:1 #00BCF2);
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1084DD, stop:1 #10C8F8);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #006CB7, stop:1 #00A8D2);
            }
        """)
        launch_btn.clicked.connect(self.on_launch)
        layout.addWidget(launch_btn)
    
    def on_launch(self):
        """Emit launch signal"""
        self.launch_clicked.emit(self.name, self.description, self.path, self.is_local)


class DashboardPage(StyledWidget):
    """Main dashboard page showing all apps"""
    logout = Signal()
    launch_app = Signal(str, str, bool)  # name, path, is_local
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.loading_overlay = None
        self.current_user = None
        self.init_ui()
        self.setup_loading_overlay()
    
    def set_user(self, user: dict):
        """Set the current user"""
        self.current_user = user
    
    def init_ui(self):
        """Initialize the dashboard UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # Header with logout
        header_layout = QHBoxLayout()
        header = QLabel("Available Applications")
        header.setStyleSheet("""
            font-size: 28px;
            font-weight: bold;
            color: white;
        """)
        header_layout.addWidget(header)
        header_layout.addStretch()
        
        logout_btn = QPushButton("Logout")
        logout_btn.setFixedSize(100, 40)
        logout_btn.clicked.connect(self.logout)
        header_layout.addWidget(logout_btn)
        
        layout.addLayout(header_layout)
        
        # Scroll area for apps
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background-color: #2D2D30;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #0078D7;
                border-radius: 6px;
                min-height: 20px;
            }
        """)
        
        # Container for app cards
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(15)
        
        # GitHub Apps Section
        if GITHUB_APPS:
            github_header = QLabel("🌐 GitHub Apps")
            github_header.setStyleSheet("""
                font-size: 20px;
                font-weight: bold;
                color: #00BCF2;
                margin-top: 10px;
            """)
            container_layout.addWidget(github_header)
            
            for name, desc, icon, url in GITHUB_APPS:
                card = AppCard(name, desc, icon, url, is_local=False)
                card.launch_clicked.connect(self.on_app_launch)
                container_layout.addWidget(card)
        
        # Local Apps Section
        if LOCAL_APPS:
            local_header = QLabel("💻 Local Apps")
            local_header.setStyleSheet("""
                font-size: 20px;
                font-weight: bold;
                color: #7FBA00;
                margin-top: 20px;
            """)
            container_layout.addWidget(local_header)
            
            for name, desc, icon, path in LOCAL_APPS:
                card = AppCard(name, desc, icon, path, is_local=True)
                card.launch_clicked.connect(self.on_app_launch)
                container_layout.addWidget(card)
        
        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)
    
    def setup_loading_overlay(self):
        """Set up loading overlay"""
        self.loading_overlay = LoadingOverlay(self, "Launching application...")
    
    def resizeEvent(self, event):
        """Handle resize events"""
        super().resizeEvent(event)
        if self.loading_overlay:
            self.loading_overlay.resize(self.size())
    
    def on_app_launch(self, name, description, path, is_local):
        """Handle app launch request - emit signal for main window to handle"""
        self.launch_app.emit(name, path, is_local)
