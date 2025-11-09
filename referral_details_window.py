from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, 
    QWidget, QFrame, QGridLayout, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from styled_widget import StyledWidget
from firebase_client import FirebaseClient
from utils import debug_log
import time


class ReferralDetailsWorker(QThread):
    """Worker thread to load referral data without blocking the UI"""
    data_loaded = Signal(dict)
    error_occurred = Signal(str)
    
    def __init__(self, id_token, user_id):
        super().__init__()
        self.id_token = id_token
        self.user_id = user_id
    
    def run(self):
        try:
            # Get comprehensive referral data using the FIXED methods
            data = FirebaseClient.get_comprehensive_referral_data(self.id_token, self.user_id)
            if "error" in data:
                self.error_occurred.emit(data["error"])
            else:
                self.data_loaded.emit(data)
        except Exception as e:
            debug_log(f"Exception in ReferralDetailsWorker.run: {e}")
            self.error_occurred.emit(str(e))


class ReferralDetailsWindow(QDialog):
    """FIXED: Comprehensive referral details window with proper data handling"""
    def __init__(self, id_token, user_id, username, parent=None):
        super().__init__(parent)
        
        self.id_token = id_token
        self.user_id = user_id
        self.username = username
        self.referral_data = {}
        
        self.setWindowTitle(f"Referral Details - {username}")
        self.setModal(True)
        self.resize(800, 600)
        
        # Apply styling
        self.apply_styling()
        self.init_ui()
        self.load_referral_data()
    
    def apply_styling(self):
        """Apply comprehensive dark theme styling"""
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 2px solid #333333;
                border-radius: 10px;
            }
            QLabel {
                color: #ffffff;
                font-size: 14px;
            }
            .title-label {
                font-size: 18px;
                font-weight: bold;
                color: #4CAF50;
                margin: 10px 0;
            }
            .section-title {
                font-size: 16px;
                font-weight: bold;
                color: #2196F3;
                margin: 15px 0 5px 0;
                padding: 5px 0;
                border-bottom: 1px solid #333333;
            }
            .stat-value {
                font-size: 20px;
                font-weight: bold;
                color: #4CAF50;
            }
            .user-card {
                background-color: #2a2a2a;
                border: 1px solid #444444;
                border-radius: 8px;
                padding: 10px;
                margin: 5px 0;
            }
            .membership-active {
                color: #4CAF50;
                font-weight: bold;
            }
            .membership-inactive {
                color: #FF9800;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QScrollArea {
                border: 1px solid #333333;
                border-radius: 5px;
                background-color: #1a1a1a;
            }
        """)
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title_label = QLabel(f"Referral System Details")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #4CAF50; margin: 10px 0;")
        layout.addWidget(title_label)
        
        # User info
        user_info_label = QLabel(f"User: {self.username} (ID: {self.user_id})")
        user_info_label.setFont(QFont("Arial", 12))
        layout.addWidget(user_info_label)
        
        # Stats section - FIXED WITH PROPER DATA MAPPING
        stats_frame = QFrame()
        stats_layout = QGridLayout(stats_frame)
        
        self.referral_code_label = QLabel("Referral Code: Loading...")
        self.active_count_label = QLabel("Active Referrals: Loading...")
        self.total_count_label = QLabel("Total Referrals: Loading...")
        self.referred_by_label = QLabel("Referred By: Loading...")
        
        stats_layout.addWidget(QLabel("Your Referral Code:"), 0, 0)
        stats_layout.addWidget(self.referral_code_label, 0, 1)
        stats_layout.addWidget(QLabel("Active Referrals:"), 1, 0)
        stats_layout.addWidget(self.active_count_label, 1, 1)
        stats_layout.addWidget(QLabel("Total Referrals:"), 2, 0)
        stats_layout.addWidget(self.total_count_label, 2, 1)
        stats_layout.addWidget(QLabel("You Were Referred By:"), 3, 0)
        stats_layout.addWidget(self.referred_by_label, 3, 1)
        
        layout.addWidget(stats_frame)
        
        # Referred users section
        referred_section_label = QLabel("Users You Have Referred")
        referred_section_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2196F3; margin: 15px 0 5px 0; padding: 5px 0; border-bottom: 1px solid #333333;")
        layout.addWidget(referred_section_label)
        
        # Scrollable area for referred users
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMaximumHeight(300)
        
        self.referred_users_widget = QWidget()
        self.referred_users_layout = QVBoxLayout(self.referred_users_widget)
        scroll_area.setWidget(self.referred_users_widget)
        layout.addWidget(scroll_area)
        
        # Status label
        self.status_label = QLabel("Loading referral data...")
        layout.addWidget(self.status_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("Refresh Data")
        refresh_btn.clicked.connect(self.load_referral_data)
        button_layout.addWidget(refresh_btn)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
    
    def load_referral_data(self):
        """Load referral data using worker thread"""
        try:
            self.status_label.setText("Loading referral data...")
            
            # Disable refresh button during loading
            for btn in self.findChildren(QPushButton):
                if btn.text() == "Refresh Data":
                    btn.setEnabled(False)
            
            # Start worker thread
            self.worker = ReferralDetailsWorker(self.id_token, self.user_id)
            self.worker.data_loaded.connect(self.on_data_loaded)
            self.worker.error_occurred.connect(self.on_error)
            self.worker.start()
        except Exception as e:
            debug_log(f"Exception in load_referral_data: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load referral data: {e}")
    
    def on_data_loaded(self, data):
        """FIXED: Handle loaded referral data with proper field mapping"""
        try:
            self.referral_data = data
            self.update_display()
            self.status_label.setText("Data loaded successfully")
        except Exception as e:
            debug_log(f"Exception in on_data_loaded: {e}")
            QMessageBox.critical(self, "Error", f"Failed to process referral data: {e}")
            self.status_label.setText("Error processing data")
        
        # Re-enable refresh button
        for btn in self.findChildren(QPushButton):
            if btn.text() == "Refresh Data":
                btn.setEnabled(True)
    
    def on_error(self, error_msg):
        """Handle error loading referral data"""
        self.status_label.setText(f"Error: {error_msg}")
        QMessageBox.warning(self, "Error", f"Failed to load referral data: {error_msg}")
        
        # Re-enable refresh button
        for btn in self.findChildren(QPushButton):
            if btn.text() == "Refresh Data":
                btn.setEnabled(True)
    
    def update_display(self):
        """FIXED: Update display with comprehensive referral data"""
        try:
            # Update stats with proper data extraction
            data = self.referral_data.get("data", {}) if "data" in self.referral_data else self.referral_data
            
            referral_code = data.get("referral_code", "Not set")
            self.referral_code_label.setText(referral_code)
            self.referral_code_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #4CAF50;")
            
            active_count = data.get("active_referred_count", 0)
            total_count = data.get("total_referred_count", 0)

            # Recompute counts from referred_user_details to ensure accuracy and handle type coercion
            referred_details = data.get("referred_user_details", [])
            if isinstance(referred_details, list) and referred_details:
                computed_total = 0
                computed_active = 0
                for detail in referred_details:
                    if isinstance(detail, dict):
                        computed_total += 1
                        status = detail.get("membership_status", False)
                        if isinstance(status, str):
                            status = status.lower() == "true"
                        if bool(status):
                            computed_active += 1
                # If computed values differ or stored counts look suspicious, prefer computed
                if computed_total > 0:
                    total_count = computed_total
                    active_count = computed_active
            
            self.active_count_label.setText(str(active_count))
            self.active_count_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #4CAF50;")
            
            self.total_count_label.setText(str(total_count))
            self.total_count_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #4CAF50;")
            
            referred_by = data.get("referred_by", "")
            if referred_by:
                self.referred_by_label.setText(f"User ID: {referred_by}")
            else:
                self.referred_by_label.setText("Not referred by anyone")
            
            # Update referred users list
            self.update_referred_users_list()
        except Exception as e:
            debug_log(f"Exception in update_display: {e}")
            QMessageBox.critical(self, "Error", f"Failed to update referral display: {e}")
    
    def update_referred_users_list(self):
        """FIXED: Update the referred users list with comprehensive data"""
        try:
            # Clear existing widgets
            for i in reversed(range(self.referred_users_layout.count())):
                child = self.referred_users_layout.itemAt(i).widget()
                if child:
                    child.setParent(None)
            
            data = self.referral_data.get("data", {}) if "data" in self.referral_data else self.referral_data
            referred_details = data.get("referred_user_details", [])
            
            if not referred_details:
                no_users_label = QLabel("No users referred yet")
                no_users_label.setAlignment(Qt.AlignCenter)
                no_users_label.setStyleSheet("color: #888888; font-style: italic; margin: 20px;")
                self.referred_users_layout.addWidget(no_users_label)
                return
            
            for user_detail in referred_details:
                user_card = self.create_user_card(user_detail)
                self.referred_users_layout.addWidget(user_card)
            
            # Add stretch to push cards to top
            self.referred_users_layout.addStretch()
        except Exception as e:
            debug_log(f"Exception in update_referred_users_list: {e}")
            QMessageBox.critical(self, "Error", f"Failed to update referred users list: {e}")
    
    def create_user_card(self, user_detail):
        """FIXED: Create user card with comprehensive membership information"""
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border: 1px solid #444444;
                border-radius: 8px;
                padding: 10px;
                margin: 5px 0;
            }
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Handle both dict and direct value formats - FIXED DATA HANDLING
        if isinstance(user_detail, dict):
            username = user_detail.get("username", "Unknown")
            user_id = user_detail.get("user_id", "Unknown")
            referred_at = user_detail.get("referred_at", "Unknown")
            membership_status = user_detail.get("membership_status", False)
            membership_type = user_detail.get("membership_type", "None")
        else:
            # Fallback for unexpected format
            username = str(user_detail)
            user_id = "Unknown"
            referred_at = "Unknown"
            membership_status = False
            membership_type = "None"
        
        # Username and ID
        username_label = QLabel(f"👤 {username}")
        username_label.setStyleSheet("font-weight: bold; font-size: 16px; margin-bottom: 5px;")
        layout.addWidget(username_label)
        
        user_id_label = QLabel(f"ID: {user_id}")
        user_id_label.setStyleSheet("font-size: 12px; color: #CCCCCC;")
        layout.addWidget(user_id_label)
        
        # Referral date
        if referred_at != "Unknown":
            try:
                from datetime import datetime
                ref_date = datetime.fromisoformat(referred_at.replace('Z', '+00:00'))
                date_str = ref_date.strftime("%Y-%m-%d %H:%M")
                date_label = QLabel(f"📅 Referred: {date_str}")
            except:
                date_label = QLabel(f"📅 Referred: {referred_at}")
        else:
            date_label = QLabel("📅 Referred: Unknown")
        
        date_label.setStyleSheet("font-size: 12px; color: #AAAAAA; margin: 2px 0;")
        layout.addWidget(date_label)
        
        # Membership status - FIXED DISPLAY
        if membership_status:
            membership_label = QLabel(f"💎 Membership: Active ({membership_type})")
            membership_label.setStyleSheet("color: #4CAF50; font-weight: bold; margin: 2px 0;")
        else:
            membership_label = QLabel("💎 Membership: Inactive")
            membership_label.setStyleSheet("color: #FF9800; margin: 2px 0;")
        
        layout.addWidget(membership_label)
        
        return card