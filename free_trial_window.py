"""
Free Trial Window - Allows users to activate a 1-hour free trial membership
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QMessageBox, QWidget, QHBoxLayout
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QIcon
from styled_widget import StyledWidget
from loading_widget import LoadingOverlay
from firebase_client import FirebaseClient
from utils import debug_log
from thread_workers import FreeTrialActivationWorker
from datetime import datetime, timedelta
import os
from pathlib import Path


class FreeTrialWindow(QDialog):
    """Window for activating free trial membership"""
    
    trial_activated = Signal()  # Signal emitted when trial is activated
    
    def __init__(self, id_token: str, local_id: str, parent=None):
        super().__init__(parent)
        self._id_token = id_token
        self._local_id = local_id
        self.loading_overlay = None
        self.activation_worker = None
        
        self.setWindowTitle("Free Trial Activation")
        self.setMinimumSize(500, 400)
        self.setModal(True)
        
        # Set window icon
        icon_path = os.path.join(Path(__file__).parent.parent.parent, 'autonix.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        self.init_ui()
        self.setup_loading_overlay()
        self.apply_styles()
        
        # Center the window
        self.center_window()
    
    def init_ui(self):
        """Initialize the UI components"""
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # Header section
        header = QLabel("🎁 Free Trial Activation")
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("""
            QLabel {
                font-size: 28px;
                font-weight: bold;
                color: #2196F3;
                margin-bottom: 10px;
            }
        """)
        layout.addWidget(header)
        
        # Description
        description = QLabel(
            "Activate your free trial to get 1 hour of full membership access!\n\n"
            "This includes access to all premium features and applications.\n"
            "The trial will automatically expire after 1 hour."
        )
        description.setAlignment(Qt.AlignCenter)
        description.setWordWrap(True)
        description.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #CCCCCC;
                margin: 20px 0;
                padding: 15px;
                background-color: #3E3E42;
                border-radius: 8px;
            }
        """)
        layout.addWidget(description)
        
        # Trial details card
        details_card = self.create_details_card()
        layout.addWidget(details_card)
        
        layout.addStretch()
        
        # Buttons layout
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)
        
        # Activate button
        self.activate_btn = QPushButton("✨ Activate Free Trial")
        self.activate_btn.setMinimumHeight(50)
        self.activate_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #4CAF50, stop:1 #45A049);
                color: white;
                font-size: 16px;
                font-weight: bold;
                border: none;
                border-radius: 8px;
                padding: 10px;
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
        
        # Close button
        self.close_btn = QPushButton("Close")
        self.close_btn.setMinimumHeight(50)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: #555555;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border: none;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #666666;
            }
            QPushButton:pressed {
                background-color: #444444;
            }
        """)
        self.close_btn.clicked.connect(self.close)
        buttons_layout.addWidget(self.close_btn)
        
        layout.addLayout(buttons_layout)
        
        self.setLayout(layout)
    
    def create_details_card(self):
        """Create a card showing trial details"""
        card = QWidget()
        card.setStyleSheet("""
            QWidget {
                background-color: #3E3E42;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(10)
        
        title = QLabel("Trial Details:")
        title.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #2196F3;
                margin-bottom: 10px;
            }
        """)
        card_layout.addWidget(title)
        
        details = [
            "⏱️ Duration: 1 Hour",
            "🎯 Access: All Premium Features",
            "🔄 Auto-Expires: After 1 Hour",
            "💳 Cost: Completely Free",
            "⚡ Activation: Instant"
        ]
        
        for detail in details:
            label = QLabel(detail)
            label.setStyleSheet("""
                QLabel {
                    font-size: 13px;
                    color: #CCCCCC;
                    padding: 5px 0;
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
    
    def apply_styles(self):
        """Apply dark theme styles"""
        self.setStyleSheet("""
            QDialog {
                background-color: #2D2D30;
            }
        """)
    
    def center_window(self):
        """Center the window on screen"""
        if self.parent():
            parent_geometry = self.parent().geometry()
            x = parent_geometry.x() + (parent_geometry.width() - self.width()) // 2
            y = parent_geometry.y() + (parent_geometry.height() - self.height()) // 2
            self.move(x, y)
        else:
            from PySide6.QtWidgets import QApplication
            screen = QApplication.primaryScreen().geometry()
            x = (screen.width() - self.width()) // 2
            y = (screen.height() - self.height()) // 2
            self.move(x, y)
    
    def on_activate_trial(self):
        """Handle free trial activation using threading"""
        try:
            # Show loading
            self.set_loading_state(True)
            
            # Calculate activation and expiration times
            now = datetime.utcnow()
            activated_at = now.isoformat() + "Z"
            expires_at = (now + timedelta(hours=1)).isoformat() + "Z"
            
            debug_log(f"Activating free trial for user {self._local_id}")
            debug_log(f"Activated at: {activated_at}")
            debug_log(f"Expires at: {expires_at}")
            
            # Prepare membership data
            membership_data = {
                "membership": True,
                "membership_type": "hourly",
                "membership_activated_at": activated_at,
                "membership_expires": expires_at,
                "membership_activated_by": "system",
                "free_trial_used": True  # Mark free trial as used
            }
            
            # Create and start worker thread
            self.activation_worker = FreeTrialActivationWorker(
                self._id_token,
                self._local_id,
                membership_data
            )
            self.activation_worker.progress.connect(self.on_activation_progress)
            self.activation_worker.finished.connect(self.on_activation_finished)
            self.activation_worker.start()
            
        except Exception as e:
            self.set_loading_state(False)
            debug_log(f"Exception starting free trial activation: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Error",
                f"An error occurred while starting activation:\n{str(e)}"
            )
    
    def on_activation_progress(self, message: str):
        """Handle activation progress updates"""
        if self.loading_overlay:
            self.loading_overlay.show_loading(message)
    
    def on_activation_finished(self, success: bool, result: dict):
        """Handle activation completion"""
        self.set_loading_state(False)
        
        if not success:
            error_msg = result.get("error", "Unknown error")
            debug_log(f"Failed to activate free trial: {error_msg}")
            QMessageBox.critical(
                self,
                "Activation Failed",
                f"Failed to activate free trial:\n{error_msg}"
            )
            return
        
        # Success
        now = datetime.utcnow()
        debug_log(f"Free trial activated successfully for user {self._local_id}")
        
        # Show success message
        QMessageBox.information(
            self,
            "Free Trial Activated! 🎉",
            "Your free trial has been activated successfully!\n\n"
            f"Activated at: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Expires at: {(now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "Please log in again to access your premium features."
        )
        
        # Emit signal to notify parent (will navigate to login)
        self.trial_activated.emit()
        
        # Close the window
        self.accept()
    
    def set_loading_state(self, loading):
        """Set loading state"""
        if loading:
            self.activate_btn.setEnabled(False)
            self.close_btn.setEnabled(False)
            if self.loading_overlay:
                self.loading_overlay.show_loading("Activating free trial...")
        else:
            self.activate_btn.setEnabled(True)
            self.close_btn.setEnabled(True)
            if self.loading_overlay:
                self.loading_overlay.hide_loading()

