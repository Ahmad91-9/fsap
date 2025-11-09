from PySide6.QtWidgets import QVBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QWidget, QHBoxLayout, QMessageBox
from PySide6.QtCore import Qt, Signal, QThread
from styled_widget import StyledWidget
from loading_widget import LoadingOverlay, LoadingSpinner
from config import _TEMP_SIGNUPS
from firebase_client import FirebaseClient
from thread_workers import RegistrationCompletionWorker
from utils import validate_referral_code, debug_log, generate_referral_code

class RegisterPage(StyledWidget):
    start_signup = Signal(str, str)  # email, password
    verify_email = Signal(str, str)  # idToken, localId
    cancel_signup = Signal(str, str)  # idToken, localId
    go_login = Signal()
    registration_complete = Signal(str, str)  # idToken, localId
    
    def __init__(self, main_window=None):
        super().__init__()
        self.main_window = main_window
        self.loading_overlay = None
        self.init_ui()
        self.setup_loading_overlay()
    
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(40, 40, 40, 40)
        
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
        self.back_btn.clicked.connect(lambda: self.go_login.emit())
        back_layout.addWidget(self.back_btn)
        back_layout.addStretch()
        layout.addLayout(back_layout)
        
        # Title
        title = QLabel("Create Account")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 20px;")
        layout.addWidget(title)
        
        # Form container
        form_container = QWidget()
        form_layout = QVBoxLayout(form_container)
        form_layout.setSpacing(15)
        
        # Username input
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")
        self.username_input.setMinimumHeight(40)
        form_layout.addWidget(self.username_input)
        
        # Email input
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("Email")
        self.email_input.setMinimumHeight(40)
        form_layout.addWidget(self.email_input)
        
        # Password input
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setMinimumHeight(40)
        form_layout.addWidget(self.password_input)
        
        # Confirm password input
        self.confirm_input = QLineEdit()
        self.confirm_input.setPlaceholderText("Confirm Password")
        self.confirm_input.setEchoMode(QLineEdit.Password)
        self.confirm_input.setMinimumHeight(40)
        form_layout.addWidget(self.confirm_input)

        # Referral code input (optional) - FIXED REFERRAL SYSTEM
        self.referral_input = QLineEdit()
        self.referral_input.setPlaceholderText("Enter Referral Code (Optional)")
        self.referral_input.setMinimumHeight(40)
        form_layout.addWidget(self.referral_input)

        # RBPK-Accenture username input (optional)
        self.rbpk_accenture_input = QLineEdit()
        self.rbpk_accenture_input.setPlaceholderText("RBPK-Accenture Username (Optional)")
        self.rbpk_accenture_input.setMinimumHeight(40)
        form_layout.addWidget(self.rbpk_accenture_input)
        
        
        # Show password checkbox
        self.show_pass = QCheckBox("Show password")
        self.show_pass.toggled.connect(self.toggle_passwords)
        form_layout.addWidget(self.show_pass)
        
        # Send verification email button
        self.get_code_btn = QPushButton("Send Verification Email")
        self.get_code_btn.setMinimumHeight(40)
        self.get_code_btn.clicked.connect(self.on_get_code)
        form_layout.addWidget(self.get_code_btn)
        
        # Verification status label
        self.verification_status_label = QLabel("")
        self.verification_status_label.setAlignment(Qt.AlignCenter)
        self.verification_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        self.verification_status_label.setWordWrap(True)
        form_layout.addWidget(self.verification_status_label)
        
        # Check verification button  
        self.verify_btn = QPushButton("Check Email Verification")
        self.verify_btn.setMinimumHeight(40)
        self.verify_btn.setEnabled(False)
        self.verify_btn.clicked.connect(self.on_verify_clicked)
        form_layout.addWidget(self.verify_btn)
        
        # Register button
        self.register_btn = QPushButton("Complete Registration")
        self.register_btn.setMinimumHeight(45)
        self.register_btn.setEnabled(False)
        self.register_btn.clicked.connect(self.on_register_clicked)
        form_layout.addWidget(self.register_btn)
        
        layout.addWidget(form_container)
        
        # Links
        links_layout = QHBoxLayout()
        links_layout.addStretch()
        self.login_link = QPushButton("Already have an account? Login")
        self.login_link.setFlat(True)
        self.login_link.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #007ACC;
                font-weight: bold;
                text-decoration: underline;
                border: none;
            }
        """)
        self.login_link.clicked.connect(self.go_to_login_with_cleanup)
        links_layout.addWidget(self.login_link)
        links_layout.addStretch()
        layout.addLayout(links_layout)
        
        layout.addStretch()
        self.setLayout(layout)
        
        # internal state
        self._id_token = None
        self._local_id = None
        self.referral_validation_worker = None
        self.registration_worker = None
        self._signup_completed = False

    def setup_loading_overlay(self):
        """Set up the loading overlay for this page"""
        self.loading_overlay = LoadingOverlay(self, "Processing registration...")
        
    def resizeEvent(self, event):
        """Handle resize events to properly position loading overlay"""
        super().resizeEvent(event)
        if self.loading_overlay:
            self.loading_overlay.resize(self.size())
    
    def set_loading_state(self, loading, message="Processing..."):
        """Set the loading state of the registration form"""
        form_elements = [
            self.username_input, self.email_input, self.password_input,
            self.confirm_input, self.referral_input, self.rbpk_accenture_input,
            self.show_pass, self.get_code_btn, self.verify_btn, self.register_btn, self.login_link
        ]
        
        if loading:
            # Disable form elements
            for element in form_elements:
                element.setEnabled(False)
            
            # Show loading overlay
            if self.loading_overlay:
                self.loading_overlay.show_loading(message)
        else:
            # Re-enable appropriate form elements based on state
            self.username_input.setEnabled(True)
            self.email_input.setEnabled(True)
            self.password_input.setEnabled(True)
            self.confirm_input.setEnabled(True)
            self.referral_input.setEnabled(True)
            self.rbpk_accenture_input.setEnabled(True)
            self.show_pass.setEnabled(True)
            self.login_link.setEnabled(True)
            
            # Enable buttons based on verification state
            if self._id_token and self._local_id:
                self.verify_btn.setEnabled(True)
                if hasattr(self, '_email_verified') and self._email_verified:
                    self.register_btn.setEnabled(True)
                else:
                    self.get_code_btn.setEnabled(True)
            else:
                self.get_code_btn.setEnabled(True)
            
            # Hide loading overlay
            if self.loading_overlay:
                self.loading_overlay.hide_loading()

    def toggle_passwords(self, checked):
        mode = QLineEdit.Normal if checked else QLineEdit.Password
        self.password_input.setEchoMode(mode)
        self.confirm_input.setEchoMode(mode)

    def on_get_code(self):
        email = self.email_input.text().strip()
        password = self.password_input.text().strip()
        username = self.username_input.text().strip()
        confirm = self.confirm_input.text().strip()
        
        # Validate inputs
        if not email or not password or not username or not confirm:
            QMessageBox.warning(self, "Input Required", "Please fill in all fields.")
            return
        
        # Check password match
        if password != confirm:
            QMessageBox.warning(self, "Password Mismatch", "Passwords do not match.")
            return
        
        # Show loading state
        self.set_loading_state(True, "Sending verification email...")
        self.verification_status_label.setText("Sending verification email...")
        self.start_signup.emit(email, password)

    def on_verify_clicked(self):
        if not (self._id_token and self._local_id):
            QMessageBox.warning(self, "No signup", "No signup in progress.")
            return
        
        # Show loading state
        self.set_loading_state(True, "Checking email verification...")
        self.verify_btn.setText("Checking verification...")
        self.verify_email.emit(self._id_token, self._local_id)
    

    def on_register_clicked(self):
        """FIXED REGISTRATION WITH COMPREHENSIVE REFERRAL PROCESSING"""
        if not self._id_token or not self._local_id:
            QMessageBox.warning(self, "Not Verified", "Please verify your email first.")
            return

        # Validate referral code if provided
        referral_code = self.referral_input.text().strip().upper()
        if referral_code:
            # Validate referral code format first
            if not validate_referral_code(referral_code):
                QMessageBox.warning(self, "Invalid Referral Code",
                    "Referral code must be 6-12 alphanumeric characters and start with a letter.")
                return
            
            # Validate referral code exists in database
            self.set_loading_state(True, "Validating referral code...")
            self.referral_validation_worker = ReferralValidationWorker(None, referral_code)
            self.referral_validation_worker.finished.connect(self.on_referral_validation_for_registration)
            self.referral_validation_worker.start()
            return  # Exit here, will continue in callback

        # If no referral code, proceed with registration
        self._proceed_with_registration("")

    def _proceed_with_registration(self, referral_code):
        """Continue with registration after referral code validation using threading"""
        # Show loading state for registration
        self.set_loading_state(True, "Completing registration...")

        # Generate unique referral code for new user
        user_referral_code = generate_referral_code(user_id=self._local_id)
        username = self.username_input.text().strip()
        email = self.email_input.text().strip()
        rbpk_accenture_username = self.rbpk_accenture_input.text().strip()

        try:
            import time
            
            user_data = {
                "username": username,
                "email": email,
                "email_verified": True,
                "referral_code": user_referral_code,
                "referral_count": 0,
                "referred_user_ids": [],
                "referred_by": "",
                "registration_date": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "membership": False,
                "free_trial_used": False,  # New users haven't used free trial yet
                "rbpk_accenture_username": rbpk_accenture_username if rbpk_accenture_username else ""
            }

            # Create and start worker thread
            self.registration_worker = RegistrationCompletionWorker(
                self._id_token,
                self._local_id,
                user_data,
                referral_code
            )
            self.registration_worker.progress.connect(self.on_registration_progress)
            self.registration_worker.finished.connect(self.on_registration_finished)
            self.registration_worker.start()

        except Exception as e:
            self.set_loading_state(False)  # Hide loading on error
            debug_log(f"Exception starting registration: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Failed to start registration: {str(e)}")
    
    def on_registration_progress(self, message: str):
        """Handle registration progress updates"""
        if self.loading_overlay:
            self.loading_overlay.show_loading(message)
    
    def on_registration_finished(self, success: bool, result: dict):
        """Handle registration completion"""
        self.set_loading_state(False)
        
        if not success:
            error_msg = result.get("error", "Unknown error")
            QMessageBox.critical(self, "Error", f"Failed to complete registration: {error_msg}")
            return
        
        # Success
        referrer_id = result.get("referrer_id", "")
        user_referral_code = result.get("referral_code", "")
        
        # Mark signup as completed and remove from temp signup tracking
        self._signup_completed = True
        try:
            _TEMP_SIGNUPS.remove((self._id_token, self._local_id))
        except ValueError:
            pass

        success_message = "Registration completed successfully!"
        if referrer_id:
            success_message += f"\n\nYou were referred by user ID: {referrer_id}"
            success_message += "\nYour referrer will receive credit when you activate membership."
        success_message += f"\nYour referral code: {user_referral_code}"

        QMessageBox.information(self, "Registered", success_message)

        # Complete registration
        self.register_btn.setEnabled(False)
        if self.main_window:
            # Navigate to free trial page after registration
            self.main_window.go_to_free_trial(self._id_token, self._local_id)
        else:
            self.registration_complete.emit(self._id_token, self._local_id)

    def handle_signup_result(self, success: bool, payload: dict):
        """Handle the result of the signup operation"""
        # Stop loading state
        self.set_loading_state(False)
        
        if success:
            self._id_token = payload.get("idToken")
            self._local_id = payload.get("localId")
            self.verification_status_label.setText("Verification email sent! Check your inbox or spam folder(must).")
            self.verify_btn.setEnabled(True)
        else:
            error_msg = "Signup failed"
            if isinstance(payload, dict):
                if "error" in payload:
                    error_detail = payload["error"]
                    if isinstance(error_detail, dict):
                        error_msg = error_detail.get("message", "Unknown error")
                    else:
                        error_msg = str(error_detail)
                elif "exception" in payload:
                    error_msg = f"Exception: {payload['exception']}"
            
            self.verification_status_label.setText(f"Error: {error_msg}")
            self.get_code_btn.setEnabled(True)

    def handle_verify_result(self, ok: bool, msg: str):
        """Handle the result of email verification check"""
        # Stop loading state
        self.set_loading_state(False)
        
        self.verify_btn.setEnabled(True)
        self.verify_btn.setText("Check Email Verification")
        
        if ok:
            self._email_verified = True
            self.verification_status_label.setText("Email verified successfully!")
            self.register_btn.setEnabled(True)
        else:
            self.verification_status_label.setText(f"Verification: {msg}")
    
    def cleanup_incomplete_signup(self):
        """Clean up incomplete signup if user navigates away without completing registration"""
        if not self._signup_completed and self._id_token and self._local_id:
            try:
                debug_log(f"Cleaning up incomplete signup for user: {self._local_id}")
                # Remove from temp signups list
                from config import _TEMP_SIGNUPS
                try:
                    _TEMP_SIGNUPS.remove((self._id_token, self._local_id))
                except ValueError:
                    pass
                
                # Delete the Firebase account
                from firebase_client import FirebaseClient
                FirebaseClient.delete_account(self._id_token)
                debug_log(f"Deleted incomplete signup account: {self._local_id}")
                
            except Exception as e:
                debug_log(f"Error cleaning up incomplete signup: {e}")
    
    def go_to_login_with_cleanup(self):
        """Navigate to login page and clean up incomplete signup"""
        self.cleanup_incomplete_signup()
        self.go_login.emit()
    
    def on_referral_validation_for_registration(self, success: bool, result: dict):
        """Handle referral code validation during registration"""
        if success:
            # Referral code is valid, proceed with registration
            referral_code = self.referral_input.text().strip().upper()
            self._proceed_with_registration(referral_code)
        else:
            # Referral code is invalid, show error and return to registration page
            self.set_loading_state(False)
            error_msg = result.get("error", "Unknown error")
            QMessageBox.warning(self, "Invalid Referral Code", 
                f"Referral code validation failed:\n{error_msg}\n\nPlease enter a correct referral code or leave it empty.")
            # Focus back on the referral input field
            self.referral_input.setFocus()
            self.referral_input.selectAll()


class ReferralValidationWorker(QThread):
    """Worker thread to validate referral codes without blocking the UI"""
    finished = Signal(bool, dict)
    
    def __init__(self, id_token: str, referral_code: str):
        super().__init__()
        self.id_token = id_token
        self.referral_code = referral_code
    
    def run(self):
        try:
            # Validate the referral code
            result = FirebaseClient.validate_referral_code(self.id_token, self.referral_code)
            
            if "success" in result:
                self.finished.emit(True, result)
            else:
                self.finished.emit(False, result)
                
        except Exception as e:
            debug_log(f"Exception in ReferralValidationWorker: {e}")
            self.finished.emit(False, {"error": f"Exception: {str(e)}"})