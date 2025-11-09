"""
Free Trial Page - Full page widget for free trial activation
This page is shown to users who haven't used their free trial yet
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from styled_widget import StyledWidget
from loading_widget import LoadingOverlay
from free_trial_window import FreeTrialWindow
from thread_workers import SkipTrialWorker
from utils import debug_log


class FreeTrialPage(StyledWidget):
    """Full page widget for free trial activation"""
    
    trial_activated = Signal()  # Signal emitted when trial is activated
    skip_trial = Signal()  # Signal emitted when user skips trial
    go_back = Signal()  # Signal emitted when user clicks back button
    
    def __init__(self):
        super().__init__()
        self.loading_overlay = None
        self._id_token = None
        self._local_id = None
        self._user_profile = {}
        self.skip_worker = None
        
        self.init_ui()
        self.setup_loading_overlay()
    
    def init_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout()
        layout.setSpacing(30)
        layout.setContentsMargins(50, 50, 50, 50)
        
        # Back button at top
        back_layout = QHBoxLayout()
        self.back_btn = QPushButton("← Back")
        self.back_btn.setMaximumWidth(100)
        self.back_btn.setMinimumHeight(35)
        self.back_btn.setStyleSheet("""
            QPushButton {
                background-color: #555555;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #666666;
            }
            QPushButton:pressed {
                background-color: #444444;
            }
        """)
        self.back_btn.clicked.connect(lambda: self.go_back.emit())
        back_layout.addWidget(self.back_btn)
        back_layout.addStretch()
        layout.addLayout(back_layout)
        
        # Header
        header = QLabel("🎁 Welcome! Activate Your Free Trial")
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("""
            QLabel {
                font-size: 32px;
                font-weight: bold;
                color: #2196F3;
                margin-bottom: 20px;
            }
        """)
        layout.addWidget(header)
        
        # Description
        description = QLabel(
            "Get started with a <b>FREE 1-hour trial</b> to explore all premium features!\n\n"
            "This includes full access to all applications and premium features.\n"
            "The trial will automatically expire after 1 hour.\n\n"
            "<i>This is a one-time offer - activate it now to get started!</i>"
        )
        description.setAlignment(Qt.AlignCenter)
        description.setWordWrap(True)
        description.setStyleSheet("""
            QLabel {
                font-size: 16px;
                color: #CCCCCC;
                margin: 30px 0;
                padding: 10px;
                background-color: #3E3E42;
                border-radius: 10px;
            }
        """)
        layout.addWidget(description)
        
        # Trial details card
        details_card = self.create_details_card()
        layout.addWidget(details_card)
        
        layout.addStretch()
        
        # Buttons layout
        buttons_layout = QVBoxLayout()
        buttons_layout.setSpacing(15)
        
        # Activate button
        self.activate_btn = QPushButton("✨ Activate Free Trial Now")
        self.activate_btn.setMinimumHeight(60)
        self.activate_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #4CAF50, stop:1 #45A049);
                color: white;
                font-size: 18px;
                font-weight: bold;
                border: none;
                border-radius: 10px;
                padding: 15px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #45A049, stop:1 #3D8B40);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #3D8B40, stop:1 #2E7D32);
            }
            QPushButton:disabled {
                background-color: #555555;
                color: #888888;
            }
        """)
        self.activate_btn.clicked.connect(self.on_activate_trial)
        buttons_layout.addWidget(self.activate_btn)
        
        # Skip button
        self.skip_btn = QPushButton("⏭️ Skip Free Trial")
        self.skip_btn.setMinimumHeight(50)
        self.skip_btn.setStyleSheet("""
            QPushButton {
                background-color: #666666;
                color: white;
                font-size: 16px;
                font-weight: bold;
                border: none;
                border-radius: 10px;
                padding: 12px;
            }
            QPushButton:hover {
                background-color: #777777;
            }
            QPushButton:pressed {
                background-color: #555555;
            }
            QPushButton:disabled {
                background-color: #444444;
                color: #888888;
            }
        """)
        self.skip_btn.clicked.connect(self.on_skip_trial)
        buttons_layout.addWidget(self.skip_btn)
        
        layout.addLayout(buttons_layout)
        
        self.setLayout(layout)
    
    def create_details_card(self):
        """Create a card showing trial details"""
        from PySide6.QtWidgets import QFrame
        
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: #3E3E42;
                border-radius: 10px;
                padding: 8px;
            }
        """)
        
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(5)
        
        title = QLabel("What You Get:")
        title.setStyleSheet("""
            QLabel {
                font-size: 20px;
                font-weight: bold;
                color: #2196F3;
                margin-bottom: 3px;
            }
        """)
        card_layout.addWidget(title)
        
        details = [
            "⏱️ 1 Hour of Full Premium Access",
            "🎯 Access to All Premium Applications",
            "🔄 Automatic Expiration After 1 Hour",
            "💳 Completely Free - No Credit Card Required",
            "⚡ Instant Activation"
        ]
        
        for detail in details:
            label = QLabel(detail)
            label.setStyleSheet("""
                QLabel {
                    font-size: 15px;
                    color: #CCCCCC;
                    padding: 8px 0;
                }
            """)
            card_layout.addWidget(label)
        
        return card
    
    def setup_loading_overlay(self):
        """Set up the loading overlay"""
        self.loading_overlay = LoadingOverlay(self, "Activating free trial...")
    
    def resizeEvent(self, event):
        """Handle resize events"""
        super().resizeEvent(event)
        if self.loading_overlay:
            self.loading_overlay.resize(self.size())
    
    def set_user(self, id_token: str, local_id: str, user_profile: dict):
        """Set user data for this page"""
        self._id_token = id_token
        self._local_id = local_id
        self._user_profile = user_profile or {}
    
    def on_activate_trial(self):
        """Handle free trial activation"""
        try:
            if not self._id_token or not self._local_id:
                QMessageBox.warning(self, "Error", "User session not found. Please log in again.")
                return
            
            # Create and show free trial window
            trial_window = FreeTrialWindow(self._id_token, self._local_id, self)
            
            # Connect to trial activated signal
            trial_window.trial_activated.connect(self.on_trial_window_activated)
            
            trial_window.exec()
            
        except Exception as e:
            debug_log(f"Exception opening free trial window: {e}")
            QMessageBox.critical(self, "Error", f"Failed to open free trial window: {str(e)}")
    
    def on_trial_window_activated(self):
        """Handle when trial window activates the trial"""
        # Emit signal to notify main window
        self.trial_activated.emit()
    
    def on_skip_trial(self):
        """Handle when user skips the free trial using threading"""
        try:
            if not self._id_token or not self._local_id:
                QMessageBox.warning(self, "Error", "User session not found. Please log in again.")
                return
            
            # Show loading
            self.set_loading_state(True)
            if self.loading_overlay:
                self.loading_overlay.show_loading("Skipping free trial...")
            
            # Create and start worker thread
            self.skip_worker = SkipTrialWorker(self._id_token, self._local_id)
            self.skip_worker.finished.connect(self.on_skip_finished)
            self.skip_worker.start()
            
        except Exception as e:
            self.set_loading_state(False)
            debug_log(f"Exception starting skip trial: {e}")
            QMessageBox.critical(self, "Error", f"Failed to skip trial: {str(e)}")
    
    def on_skip_finished(self, success: bool, result: dict):
        """Handle skip trial completion"""
        self.set_loading_state(False)
        
        if not success:
            error_msg = result.get("error", "Unknown error")
            debug_log(f"Failed to mark free trial as used: {error_msg}")
            QMessageBox.warning(self, "Warning", f"Failed to update: {error_msg}\nYou may see this page again.")
        else:
            debug_log("Free trial marked as skipped/used")
        
        # Emit signal to navigate to membership page
        self.skip_trial.emit()
    
    def set_loading_state(self, loading):
        """Set loading state"""
        if loading:
            self.activate_btn.setEnabled(False)
            self.skip_btn.setEnabled(False)
            self.back_btn.setEnabled(False)
            if self.loading_overlay:
                self.loading_overlay.show_loading("Processing...")
        else:
            self.activate_btn.setEnabled(True)
            self.skip_btn.setEnabled(True)
            self.back_btn.setEnabled(True)
            if self.loading_overlay:
                self.loading_overlay.hide_loading()


