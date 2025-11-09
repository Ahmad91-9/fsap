from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, 
    QWidget, QFrame, QGridLayout, QMessageBox, QLineEdit, QComboBox, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from styled_widget import StyledWidget
from firebase_client import FirebaseClient
from config import monthly_reward_on_a_successful_referral, weekly_reward_on_a_successful_referral
from utils import debug_log
from loading_widget import LoadingOverlay
from datetime import datetime


class AutoRewardsCalculationWorker(QThread):
    """Worker thread to automatically calculate both monthly and weekly rewards"""
    finished = Signal(bool, dict)
    progress = Signal(str)
    
    def __init__(self, id_token: str, user_id: str):
        super().__init__()
        self.id_token = id_token
        self.user_id = user_id
    
    def run(self):
        try:
            self.progress.emit("Loading referral data...")
            # Get comprehensive referral data
            referral_data = FirebaseClient.get_comprehensive_referral_data(self.id_token, self.user_id)
            if "error" in referral_data:
                self.finished.emit(False, referral_data)
                return
            
            self.progress.emit("Analyzing referred users...")
            data = referral_data.get("data", {})
            referred_user_details = data.get("referred_user_details", [])
            
            # Get current rewards to check used membership codes
            current_rewards = FirebaseClient.get_user_rewards(self.id_token, self.user_id)
            if "error" in current_rewards:
                self.finished.emit(False, current_rewards)
                return
            
            rewards_info = current_rewards.get("data", {})
            used_membership_codes = set(rewards_info.get("used_membership_codes", []))
            
            # Count monthly and weekly referrals separately, only for new/unused membership codes
            monthly_referrals_count = 0
            weekly_referrals_count = 0
            new_membership_codes = []  # Track new codes to add to used list
            
            for user_detail in referred_user_details:
                if isinstance(user_detail, dict):
                    # Check if user has active membership
                    membership_status = user_detail.get("membership_status", False)
                    if isinstance(membership_status, str):
                        membership_status = membership_status.lower() == "true"
                    
                    if bool(membership_status):
                        # Get membership code
                        membership_code = user_detail.get("membership_code")
                        if not membership_code:
                            # If no membership code, try to get it from user data
                            user_id = user_detail.get("user_id")
                            if user_id:
                                try:
                                    user_data = FirebaseClient.get_user_data(self.id_token, user_id)
                                    if "error" not in user_data:
                                        user_fields = user_data.get("fields", {})
                                        membership_code = FirebaseClient._extract_field_value(user_fields.get("membership_code"), "string", None)
                                except:
                                    pass
                        
                        # Only count if membership code is not in used list
                        if membership_code and membership_code not in used_membership_codes:
                            # Get membership type
                            membership_type = user_detail.get("membership_type", "none")
                            if isinstance(membership_type, str):
                                membership_type = membership_type.lower()
                            
                            # Count based on membership type
                            if membership_type == "monthly":
                                monthly_referrals_count += 1
                                new_membership_codes.append(membership_code)
                            elif membership_type == "weekly":
                                weekly_referrals_count += 1
                                new_membership_codes.append(membership_code)
            
            self.progress.emit("Calculating monthly rewards...")
            
            current_monthly = rewards_info.get("monthly_rewards", 0)
            current_weekly = rewards_info.get("weekly_rewards", 0)
            withdrawn = rewards_info.get("withdrawn_amount", 0)
            
            # Calculate monthly rewards - only for users with monthly membership
            monthly_reward_per_referral = monthly_reward_on_a_successful_referral()
            monthly_new_rewards = monthly_reward_per_referral * monthly_referrals_count
            total_monthly = monthly_new_rewards + current_monthly  # Add to existing
            
            self.progress.emit("Calculating weekly rewards...")
            
            # Calculate weekly rewards - only for users with weekly membership
            weekly_reward_per_referral = weekly_reward_on_a_successful_referral()
            weekly_new_rewards = weekly_reward_per_referral * weekly_referrals_count
            total_weekly = weekly_new_rewards + current_weekly  # Add to existing
            
            total_rewards = total_monthly + total_weekly
            available_balance = total_rewards - withdrawn
            
            # Update rewards in Firebase
            self.progress.emit("Saving rewards...")
            # Add new membership codes to used list
            updated_used_codes = list(used_membership_codes) + new_membership_codes
            
            rewards_data = {
                "user_id": self.user_id,
                "monthly_rewards": total_monthly,
                "weekly_rewards": total_weekly,
                "total_rewards": total_rewards,
                "withdrawn_amount": withdrawn,
                "available_balance": available_balance,
                "last_calculated": datetime.now().isoformat() + "Z",
                "used_membership_codes": updated_used_codes
            }
            
            update_result = FirebaseClient.update_user_rewards(self.id_token, self.user_id, rewards_data)
            if "error" in update_result:
                self.finished.emit(False, update_result)
                return
            
            self.finished.emit(True, {
                "success": True,
                "monthly_referrals_count": monthly_referrals_count,
                "weekly_referrals_count": weekly_referrals_count,
                "total_active_referrals": monthly_referrals_count + weekly_referrals_count,
                "monthly_new_rewards": monthly_new_rewards,
                "weekly_new_rewards": weekly_new_rewards,
                "rewards_data": rewards_data,
                "referral_data": data
            })
            
        except Exception as e:
            debug_log(f"Exception in AutoRewardsCalculationWorker: {e}")
            self.finished.emit(False, {"error": f"Exception calculating rewards: {str(e)}"})


class WithdrawalWorker(QThread):
    """Worker thread to process withdrawal"""
    finished = Signal(bool, dict)
    progress = Signal(str)
    
    def __init__(self, id_token: str, user_id: str, withdrawal_amount: int, 
                 account_number: str, account_name: str, account_type: str, whatsapp: str):
        super().__init__()
        self.id_token = id_token
        self.user_id = user_id
        self.withdrawal_amount = withdrawal_amount
        self.account_number = account_number
        self.account_name = account_name
        self.account_type = account_type
        self.whatsapp = whatsapp
    
    def run(self):
        try:
            self.progress.emit("Processing withdrawal...")
            
            # Get current rewards
            current_rewards = FirebaseClient.get_user_rewards(self.id_token, self.user_id)
            if "error" in current_rewards:
                self.finished.emit(False, current_rewards)
                return
            
            rewards_info = current_rewards.get("data", {})
            available_balance = rewards_info.get("available_balance", 0)
            
            if self.withdrawal_amount > available_balance:
                self.finished.emit(False, {"error": "Insufficient balance"})
                return
            
            # Record withdrawal
            self.progress.emit("Recording withdrawal request...")
            withdrawal_data = {
                "user_id": self.user_id,
                "amount": self.withdrawal_amount,
                "account_number": self.account_number,
                "account_name": self.account_name,
                "account_type": self.account_type,
                "whatsapp": self.whatsapp,
                "status": "pending"
            }
            
            withdrawal_result = FirebaseClient.record_withdrawal(
                self.id_token, self.user_id, withdrawal_data
            )
            if "error" in withdrawal_result:
                self.finished.emit(False, withdrawal_result)
                return
            
            # Update user rewards - deduct withdrawn amount
            self.progress.emit("Updating balance...")
            new_withdrawn = rewards_info.get("withdrawn_amount", 0) + self.withdrawal_amount
            new_available = available_balance - self.withdrawal_amount
            
            updated_rewards = {
                "user_id": self.user_id,
                "monthly_rewards": rewards_info.get("monthly_rewards", 0),
                "weekly_rewards": rewards_info.get("weekly_rewards", 0),
                "total_rewards": rewards_info.get("total_rewards", 0),
                "withdrawn_amount": new_withdrawn,
                "available_balance": new_available,
                "last_updated": datetime.now().isoformat() + "Z"
            }
            
            update_result = FirebaseClient.update_user_rewards(self.id_token, self.user_id, updated_rewards)
            if "error" in update_result:
                self.finished.emit(False, update_result)
                return
            
            self.finished.emit(True, {
                "success": True,
                "withdrawal_id": withdrawal_result.get("withdrawal_id"),
                "updated_rewards": updated_rewards
            })
            
        except Exception as e:
            debug_log(f"Exception in WithdrawalWorker: {e}")
            self.finished.emit(False, {"error": f"Exception processing withdrawal: {str(e)}"})


class RewardsWindow(QDialog):
    """Rewards management window with calculation and withdrawal functionality"""
    
    def __init__(self, id_token: str, user_id: str, username: str, parent=None):
        super().__init__(parent)
        
        self.id_token = id_token
        self.user_id = user_id
        self.username = username
        self.rewards_data = {}
        self.referral_data = {}
        
        self.calculation_worker = None
        self.withdrawal_worker = None
        self.loading_overlay = None
        
        self.setWindowTitle(f"Rewards - {username}")
        self.setModal(True)
        # Make window full screen
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        self.showMaximized()
        
        self.apply_styling()
        self.init_ui()
        self.setup_loading_overlay()
        # Automatically calculate both monthly and weekly rewards when window opens
        self.auto_calculate_rewards()
    
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
                font-size: 11px;
            }
            QLineEdit, QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 5px;
                font-size: 11px;
                min-height: 25px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 2px solid #4CAF50;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 6px 15px;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
                min-height: 28px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #555555;
                color: #888888;
            }
            .stat-value {
                font-size: 14px;
                font-weight: bold;
                color: #4CAF50;
            }
            .section-title {
                font-size: 12px;
                font-weight: bold;
                color: #2196F3;
                margin: 10px 0 3px 0;
                padding: 3px 0;
                border-bottom: 1px solid #333333;
            }
        """)
    
    def setup_loading_overlay(self):
        """Setup loading overlay"""
        try:
            self.loading_overlay = LoadingOverlay(self)
        except Exception as e:
            debug_log(f"Error setting up loading overlay: {e}")
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Title
        title_label = QLabel("Rewards System")
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #4CAF50; margin: 5px 0;")
        layout.addWidget(title_label)
        
        # User info
        user_info_label = QLabel(f"User: {self.username} (ID: {self.user_id})")
        user_info_label.setFont(QFont("Arial", 10))
        layout.addWidget(user_info_label)
        
        # Rewards display section
        rewards_frame = QFrame()
        rewards_layout = QGridLayout(rewards_frame)
        
        self.active_referrals_label = QLabel("Active Referrals: Loading...")
        self.monthly_rewards_label = QLabel("Monthly Rewards: 0 PKR")
        self.weekly_rewards_label = QLabel("Weekly Rewards: 0 PKR")
        self.total_rewards_label = QLabel("Total Rewards: 0 PKR")
        self.withdrawn_label = QLabel("Withdrawn: 0 PKR")
        self.available_balance_label = QLabel("Available Balance: 0 PKR")
        self.available_balance_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #4CAF50;")
        
        rewards_layout.addWidget(QLabel("Active Referrals:"), 0, 0)
        rewards_layout.addWidget(self.active_referrals_label, 0, 1)
        rewards_layout.addWidget(QLabel("Monthly Rewards:"), 1, 0)
        rewards_layout.addWidget(self.monthly_rewards_label, 1, 1)
        rewards_layout.addWidget(QLabel("Weekly Rewards:"), 2, 0)
        rewards_layout.addWidget(self.weekly_rewards_label, 2, 1)
        rewards_layout.addWidget(QLabel("Total Rewards:"), 3, 0)
        rewards_layout.addWidget(self.total_rewards_label, 3, 1)
        rewards_layout.addWidget(QLabel("Withdrawn:"), 4, 0)
        rewards_layout.addWidget(self.withdrawn_label, 4, 1)
        rewards_layout.addWidget(QLabel("Available Balance:"), 5, 0)
        rewards_layout.addWidget(self.available_balance_label, 5, 1)
        
        layout.addWidget(rewards_frame)
        
        # Withdrawal section
        withdraw_section_label = QLabel("Withdraw Rewards")
        withdraw_section_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #2196F3; margin: 10px 0 3px 0; padding: 3px 0; border-bottom: 1px solid #333333;")
        layout.addWidget(withdraw_section_label)
        
        # Withdrawal form
        withdraw_form = QFrame()
        withdraw_form_layout = QGridLayout(withdraw_form)
        
        self.withdraw_amount_input = QLineEdit()
        self.withdraw_amount_input.setPlaceholderText("Enter amount (PKR)")
        withdraw_form_layout.addWidget(QLabel("Withdraw Amount (PKR):"), 0, 0)
        withdraw_form_layout.addWidget(self.withdraw_amount_input, 0, 1)
        
        self.account_type_combo = QComboBox()
        self.account_type_combo.addItems(["Easypaisa", "Jazzcash"])
        withdraw_form_layout.addWidget(QLabel("Account Type:"), 1, 0)
        withdraw_form_layout.addWidget(self.account_type_combo, 1, 1)
        
        self.account_number_input = QLineEdit()
        self.account_number_input.setPlaceholderText("Enter account number")
        withdraw_form_layout.addWidget(QLabel("Account Number:"), 2, 0)
        withdraw_form_layout.addWidget(self.account_number_input, 2, 1)
        
        self.account_name_input = QLineEdit()
        self.account_name_input.setPlaceholderText("Enter account name")
        withdraw_form_layout.addWidget(QLabel("Account Name:"), 3, 0)
        withdraw_form_layout.addWidget(self.account_name_input, 3, 1)
        
        self.whatsapp_input = QLineEdit()
        self.whatsapp_input.setPlaceholderText("Enter WhatsApp number")
        withdraw_form_layout.addWidget(QLabel("WhatsApp Number:"), 4, 0)
        withdraw_form_layout.addWidget(self.whatsapp_input, 4, 1)
        
        layout.addWidget(withdraw_form)
        
        # Withdraw button
        button_layout = QHBoxLayout()
        
        self.withdraw_btn = QPushButton("Withdraw")
        self.withdraw_btn.clicked.connect(self.on_withdraw_clicked)
        button_layout.addWidget(self.withdraw_btn)
        
        self.record_withdraw_btn = QPushButton("Record Withdrawal")
        self.record_withdraw_btn.clicked.connect(self.on_record_withdrawal)
        self.record_withdraw_btn.setEnabled(False)
        button_layout.addWidget(self.record_withdraw_btn)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        # Status label
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
    
    def auto_calculate_rewards(self):
        """Automatically calculate both monthly and weekly rewards"""
        try:
            self.set_loading_state(True)
            self.status_label.setText("Calculating rewards...")
            
            # Create worker to calculate both rewards
            self.calculation_worker = AutoRewardsCalculationWorker(
                self.id_token, self.user_id
            )
            self.calculation_worker.progress.connect(self.on_calculation_progress)
            self.calculation_worker.finished.connect(self.on_calculation_finished)
            self.calculation_worker.start()
            
        except Exception as e:
            self.set_loading_state(False)
            debug_log(f"Exception in auto_calculate_rewards: {e}")
            QMessageBox.critical(self, "Error", f"Failed to calculate rewards: {str(e)}")
    
    def update_display(self):
        """Update the display with current rewards data"""
        try:
            # Calculate total active referrals from referral data
            referred_user_details = self.referral_data.get("referred_user_details", [])
            total_active = 0
            monthly_count = 0
            weekly_count = 0
            
            for user_detail in referred_user_details:
                if isinstance(user_detail, dict):
                    membership_status = user_detail.get("membership_status", False)
                    if isinstance(membership_status, str):
                        membership_status = membership_status.lower() == "true"
                    
                    if bool(membership_status):
                        total_active += 1
                        membership_type = user_detail.get("membership_type", "none")
                        if isinstance(membership_type, str):
                            membership_type = membership_type.lower()
                        if membership_type == "monthly":
                            monthly_count += 1
                        elif membership_type == "weekly":
                            weekly_count += 1
            
            # Display total active referrals with breakdown
            if monthly_count > 0 or weekly_count > 0:
                self.active_referrals_label.setText(
                    f"{total_active} (Monthly: {monthly_count}, Weekly: {weekly_count})"
                )
            else:
                self.active_referrals_label.setText(str(total_active))
            
            monthly = self.rewards_data.get("monthly_rewards", 0)
            weekly = self.rewards_data.get("weekly_rewards", 0)
            total = self.rewards_data.get("total_rewards", 0)
            withdrawn = self.rewards_data.get("withdrawn_amount", 0)
            available = self.rewards_data.get("available_balance", 0)
            
            self.monthly_rewards_label.setText(f"{monthly} PKR")
            self.weekly_rewards_label.setText(f"{weekly} PKR")
            self.total_rewards_label.setText(f"{total} PKR")
            self.withdrawn_label.setText(f"{withdrawn} PKR")
            self.available_balance_label.setText(f"{available} PKR")
        except Exception as e:
            debug_log(f"Exception in update_display: {e}")
    
    
    def on_calculation_progress(self, message: str):
        """Handle calculation progress updates"""
        if self.loading_overlay:
            self.loading_overlay.show_loading(message)
        self.status_label.setText(message)
    
    def on_calculation_finished(self, success: bool, result: dict):
        """Handle calculation completion"""
        self.set_loading_state(False)
        
        if not success:
            error_msg = result.get("error", "Unknown error")
            self.status_label.setText(f"Error: {error_msg}")
            QMessageBox.critical(self, "Error", f"Failed to calculate rewards: {error_msg}")
            return
        
        # Update rewards data
        self.rewards_data = result.get("rewards_data", {})
        self.referral_data = result.get("referral_data", {})
        self.update_display()
        
        monthly_new = result.get("monthly_new_rewards", 0)
        weekly_new = result.get("weekly_new_rewards", 0)
        monthly_count = result.get("monthly_referrals_count", 0)
        weekly_count = result.get("weekly_referrals_count", 0)
        total_active = result.get("total_active_referrals", 0)
        total_new = monthly_new + weekly_new
        
        self.status_label.setText(
            f"Rewards calculated successfully! "
            f"Monthly: {monthly_new} PKR ({monthly_count} referrals), "
            f"Weekly: {weekly_new} PKR ({weekly_count} referrals) "
            f"({total_new} PKR total for {total_active} active referrals)."
        )
    
    def on_withdraw_clicked(self):
        """Handle withdraw button click"""
        try:
            # Get available balance
            available = self.rewards_data.get("available_balance", 0)
            
            if available < 100:
                QMessageBox.warning(
                    self,
                    "Minimum Withdrawal",
                    "Minimum withdrawal amount is 100 PKR.\n"
                    f"Your available balance: {available} PKR"
                )
                return
            
            # Get withdrawal amount
            amount_text = self.withdraw_amount_input.text().strip()
            if not amount_text:
                QMessageBox.warning(self, "Error", "Please enter withdrawal amount")
                return
            
            try:
                amount = int(amount_text)
            except ValueError:
                QMessageBox.warning(self, "Error", "Invalid withdrawal amount. Please enter a number.")
                return
            
            if amount < 100:
                QMessageBox.warning(self, "Error", "Minimum withdrawal amount is 100 PKR")
                return
            
            if amount > available:
                QMessageBox.warning(self, "Error", f"Insufficient balance. Available: {available} PKR")
                return
            
            # Validate other fields
            account_type = self.account_type_combo.currentText()
            account_number = self.account_number_input.text().strip()
            account_name = self.account_name_input.text().strip()
            whatsapp = self.whatsapp_input.text().strip()
            
            if not account_number:
                QMessageBox.warning(self, "Error", "Please enter account number")
                return
            
            if not account_name:
                QMessageBox.warning(self, "Error", "Please enter account name")
                return
            
            if not whatsapp:
                QMessageBox.warning(self, "Error", "Please enter WhatsApp number")
                return
            
            # Enable record withdrawal button
            self.record_withdraw_btn.setEnabled(True)
            self.status_label.setText(f"Withdrawal details entered. Click 'Record Withdrawal' to process.")
            
        except Exception as e:
            debug_log(f"Exception in on_withdraw_clicked: {e}")
            QMessageBox.critical(self, "Error", f"Error: {str(e)}")
    
    def on_record_withdrawal(self):
        """Handle record withdrawal button click"""
        try:
            amount_text = self.withdraw_amount_input.text().strip()
            if not amount_text:
                QMessageBox.warning(self, "Error", "Please enter withdrawal amount")
                return
            
            try:
                amount = int(amount_text)
            except ValueError:
                QMessageBox.warning(self, "Error", "Invalid withdrawal amount")
                return
            
            account_type = self.account_type_combo.currentText()
            account_number = self.account_number_input.text().strip()
            account_name = self.account_name_input.text().strip()
            whatsapp = self.whatsapp_input.text().strip()
            
            if not all([account_number, account_name, whatsapp]):
                QMessageBox.warning(self, "Error", "Please fill all fields")
                return
            
            # Process withdrawal
            self.set_loading_state(True)
            self.status_label.setText("Processing withdrawal...")
            
            self.withdrawal_worker = WithdrawalWorker(
                self.id_token, self.user_id, amount,
                account_number, account_name, account_type, whatsapp
            )
            self.withdrawal_worker.progress.connect(self.on_withdrawal_progress)
            self.withdrawal_worker.finished.connect(self.on_withdrawal_finished)
            self.withdrawal_worker.start()
            
        except Exception as e:
            self.set_loading_state(False)
            debug_log(f"Exception in on_record_withdrawal: {e}")
            QMessageBox.critical(self, "Error", f"Error processing withdrawal: {str(e)}")
    
    def on_withdrawal_progress(self, message: str):
        """Handle withdrawal progress updates"""
        if self.loading_overlay:
            self.loading_overlay.show_loading(message)
        self.status_label.setText(message)
    
    def on_withdrawal_finished(self, success: bool, result: dict):
        """Handle withdrawal completion"""
        self.set_loading_state(False)
        
        if not success:
            error_msg = result.get("error", "Unknown error")
            self.status_label.setText(f"Error: {error_msg}")
            QMessageBox.critical(self, "Error", f"Failed to process withdrawal: {error_msg}")
            return
        
        # Update rewards data
        self.rewards_data = result.get("updated_rewards", {})
        
        # Get the withdrawal amount from the input field before clearing
        withdrawal_id = result.get("withdrawal_id", "Unknown")
        try:
            amount = int(self.withdraw_amount_input.text().strip())
        except:
            amount = 0
        
        # Clear form
        self.withdraw_amount_input.clear()
        self.account_number_input.clear()
        self.account_name_input.clear()
        self.whatsapp_input.clear()
        self.record_withdraw_btn.setEnabled(False)
        
        # Update display after clearing form
        self.update_display()
        
        self.status_label.setText("Withdrawal processed successfully!")
        QMessageBox.information(
            self,
            "Withdrawal Processed",
            f"Your withdrawal has been processed successfully!\n\n"
            f"Withdrawal ID: {withdrawal_id}\n"
            f"Amount: {amount} PKR\n"
            f"Remaining Balance: {self.rewards_data.get('available_balance', 0)} PKR"
        )
    
    def set_loading_state(self, loading: bool):
        """Set loading state for UI"""
        if loading:
            self.withdraw_btn.setEnabled(False)
            self.record_withdraw_btn.setEnabled(False)
            if self.loading_overlay:
                self.loading_overlay.show_loading("Processing...")
        else:
            self.withdraw_btn.setEnabled(True)
            if self.loading_overlay:
                self.loading_overlay.hide_loading()
    
    def closeEvent(self, event):
        """Cleanup on close"""
        if self.calculation_worker and self.calculation_worker.isRunning():
            self.calculation_worker.terminate()
            self.calculation_worker.wait()
        if self.withdrawal_worker and self.withdrawal_worker.isRunning():
            self.withdrawal_worker.terminate()
            self.withdrawal_worker.wait()
        if self.loading_overlay:
            self.loading_overlay.hide_loading()
        super().closeEvent(event)

