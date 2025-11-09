from PySide6.QtWidgets import QVBoxLayout, QLabel, QPushButton, QWidget, QMessageBox, QLineEdit, QComboBox, QHBoxLayout, QFrame, QScrollArea
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPalette, QColor
from styled_widget import StyledWidget
from loading_widget import LoadingOverlay
from firebase_client import FirebaseClient
from thread_workers import TransactionRecordingWorker
from utils import debug_log

class MembershipPage(StyledWidget):
    logout = Signal()
    go_back = Signal()  # Signal emitted when user clicks back button
    
    def __init__(self):
        super().__init__()
        self.loading_overlay = None
        self.info_label = QLabel("Your membership is not active.")

        # Initialize input widgets
        self.txid_input = QLineEdit()
        self.membership_dropdown = QComboBox()
        self.membership_dropdown.addItem("Weekly", "weekly")
        self.membership_dropdown.addItem("Monthly", "monthly")
        self.whatsapp_input = QLineEdit()

        # Ensure no pre-filled text
        self.txid_input.clear()
        self.whatsapp_input.clear()

        self.init_ui()
        self.setup_loading_overlay()

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(40, 40, 40, 40)

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
        self.back_btn.clicked.connect(self.on_back_clicked)
        back_layout.addWidget(self.back_btn)
        back_layout.addStretch()
        main_layout.addLayout(back_layout)

        header_frame = self.create_header_section()
        main_layout.addWidget(header_frame)

        # Membership status
        status_card = self.create_membership_status_card()
        main_layout.addWidget(status_card)

        # Create pricing + transaction layout side by side
        side_by_side = QHBoxLayout()
        side_by_side.setSpacing(10)

        pricing_card = self.create_pricing_card()
        transaction_card = self.create_transaction_card()

        side_by_side.addWidget(pricing_card, 1)
        side_by_side.addWidget(transaction_card, 1)

        main_layout.addLayout(side_by_side)

        # Buttons row (Record + Logout)
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        buttons_layout.setAlignment(Qt.AlignCenter)
        self.record_transaction_btn = QPushButton("💳 Record Membership Transaction")
        self.logout_btn = QPushButton("🚪 Logout")

        self.record_transaction_btn.setMinimumHeight(45)
        self.logout_btn.setMinimumHeight(45)

        self.record_transaction_btn.clicked.connect(self.on_record_transaction)
        self.logout_btn.clicked.connect(lambda: self.logout.emit())

        self.apply_button_styles()

        buttons_layout.addWidget(self.record_transaction_btn)
        buttons_layout.addWidget(self.logout_btn)
        main_layout.addLayout(buttons_layout)

        main_layout.addStretch()
        self.setLayout(main_layout)

        self._id_token = None
        self._local_id = None
        self._user_profile = {}
        self.transaction_worker = None

    def apply_button_styles(self):
        self.record_transaction_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #66d9ff, stop:1 #33cc99);
                color: white;
                font-size: 14px;
                font-weight: bold;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #33ccff, stop:1 #29b67d);
            }
        ''')

        self.logout_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ff8a80, stop:1 #ff5252);
                color: white;
                font-size: 14px;
                font-weight: bold;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ff6e6e, stop:1 #ff1744);
            }
        ''')

    def create_header_section(self):
        header_frame = QFrame()
        header_frame.setStyleSheet('''
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #74ebd5, stop:1 #ACB6E5);
                border-radius: 6px;
                padding: 6px;
            }
        ''')

        header_layout = QVBoxLayout(header_frame)
        title = QLabel("Membership Dashboard")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet('''
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
        ''')

        subtitle = QLabel("Manage your membership and payment records")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet('''
            QLabel {
                font-size: 13px;
                color: white;
            }
        ''')

        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        return header_frame

    def create_membership_status_card(self):
        card = QFrame()
        card.setStyleSheet('''
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #fbc2eb, stop:1 #a6c1ee);
                border-radius: 6px;
                padding: 8px;
            }
        ''')

        layout = QVBoxLayout(card)
        label = QLabel("Current Status")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet('''
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
        ''')

        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setStyleSheet('''
            QLabel {
                font-size: 13px;
                color: #2C3E50;
                background: rgba(255,255,255,0.3);
                border-radius: 4px;
                padding: 4px;
            }
        ''')

        layout.addWidget(label)
        layout.addWidget(self.info_label)
        return card

    def create_pricing_card(self):
        card = QFrame()
        card.setStyleSheet('''
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #a1c4fd, stop:1 #c2e9fb);
                border-radius: 6px;
                padding: 10px;
            }
        ''')

        layout = QVBoxLayout(card)
        label = QLabel("Membership Pricing")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet('''
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: #2C3E50;
            }
        ''')

        content = QLabel('''<div style="text-align:center; color:#2C3E50;">
            <b>💰 Membership Plans</b><br>
            📅 Monthly Membership - <b>300 PKR</b><br>
            📅 Weekly Membership - <b>100 PKR</b><br><br>
            💳 EasyPaisa: <b>03144573695</b><br>
            Account: <b>Ahmad Hassan</b><br>
            📞 WhatsApp: <b>03144573695</b><br>
            ✉️ Email: <b>rbpk.order.bot@gmail.com</b>
        </div>''')
        content.setAlignment(Qt.AlignCenter)
        content.setWordWrap(True)

        layout.addWidget(label)
        layout.addWidget(content)
        return card

    def create_transaction_card(self):
        card = QFrame()
        card.setStyleSheet('''
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #fddb92, stop:1 #d1fdff);
                border-radius: 6px;
                padding: 10px;
            }
        ''')

        layout = QVBoxLayout(card)
        label = QLabel("Record Your Payment")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet('''
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: #2C3E50;
            }
        ''')

        layout.addWidget(label)
        form_layout = QVBoxLayout()
        form_layout.addWidget(self.create_input_field("Transaction ID (TXID)", "Enter TXID", self.txid_input))
        form_layout.addWidget(self.create_dropdown_field("Membership Type", self.membership_dropdown))
        form_layout.addWidget(self.create_input_field("WhatsApp Number", "Enter your WhatsApp", self.whatsapp_input))

        layout.addLayout(form_layout)
        return card

    def create_input_field(self, label_text, placeholder, input_widget):
        frame = QFrame()
        vbox = QVBoxLayout(frame)
        label = QLabel(label_text)
        label.setStyleSheet('''
            QLabel {
                color: #2C3E50;
                font-weight: bold;
                font-size: 13px;
            }
        ''')
        input_widget.setPlaceholderText(placeholder)
        input_widget.setMinimumHeight(40)
        input_widget.setStyleSheet('''
            QLineEdit {
                background: white;
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 6px;
                color: #000000;
            }
            QLineEdit:focus {
                border: 1px solid #66afe9;
            }
            QLineEdit[placeholderText="true"] {
                color: #888888;
            }
        ''')
        vbox.addWidget(label)
        vbox.addWidget(input_widget)
        return frame

    def create_dropdown_field(self, label_text, dropdown_widget):
        frame = QFrame()
        vbox = QVBoxLayout(frame)
        label = QLabel(label_text)
        label.setStyleSheet('''
            QLabel {
                color: #2C3E50;
                font-weight: bold;
                font-size: 13px;
            }
        ''')
        dropdown_widget.setMinimumHeight(40)
        dropdown_widget.setStyleSheet('''
            QComboBox {
                background: white;
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 6px;
                color: #000000;
            }
            QComboBox:focus {
                border: 1px solid #66afe9;
            }
        ''')
        vbox.addWidget(label)
        vbox.addWidget(dropdown_widget)
        return frame

    def setup_loading_overlay(self):
        self.loading_overlay = LoadingOverlay(self, "Processing transaction...")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.loading_overlay:
            self.loading_overlay.resize(self.size())

    def set_loading_state(self, loading, message="Processing..."):
        form_elements = [
            self.txid_input, self.membership_dropdown, self.whatsapp_input,
            self.record_transaction_btn, self.logout_btn, self.back_btn
        ]

        if loading:
            for e in form_elements:
                e.setEnabled(False)
            if self.loading_overlay:
                self.loading_overlay.show_loading(message)
        else:
            for e in form_elements:
                e.setEnabled(True)
            if self.loading_overlay:
                self.loading_overlay.hide_loading()
    
    def on_back_clicked(self):
        """Handle back button click - navigate based on free_trial_used status"""
        # Check if free trial was used
        free_trial_used = self._user_profile.get("free_trial_used", False)
        
        # Emit signal to navigate - main window will handle the logic
        self.go_back.emit()

    def set_user(self, id_token: str, local_id: str, user_profile: dict):
        self._id_token = id_token
        self._local_id = local_id
        self._user_profile = user_profile or {}
        membership = user_profile.get("membership", False)
        email = user_profile.get("email", "")
        whatsapp = user_profile.get("whatsapp", "")

        status_text = f"Email: {email}\nMembership active: {'Yes' if membership else 'No'}"
        if membership:
            self.info_label.setStyleSheet('''
                QLabel {
                    font-size: 13px;
                    color: #2C3E50;
                    background: rgba(200,255,200,0.4);
                    border-radius: 4px;
                    padding: 4px;
                    border-left: 4px solid #27AE60;
                }
            ''')
        else:
            self.info_label.setStyleSheet('''
                QLabel {
                    font-size: 13px;
                    color: #2C3E50;
                    background: rgba(255,200,200,0.4);
                    border-radius: 4px;
                    padding: 4px;
                    border-left: 4px solid #E74C3C;
                }
            ''')

        self.info_label.setText(status_text)


    def on_record_transaction(self):
        """Handle transaction recording using threading"""
        txid = self.txid_input.text().strip()
        if not txid:
            QMessageBox.warning(self, "Input Required", "Please enter TXID.")
            return
        if len(txid) < 5:
            QMessageBox.warning(self, "Invalid TXID", "Please enter a valid Transaction ID.")
            return

        whatsapp = self.whatsapp_input.text().strip()
        if not whatsapp:
            QMessageBox.warning(self, "Input Required", "Please enter WhatsApp number.")
            return
        if len(whatsapp) < 10:
            QMessageBox.warning(self, "Invalid WhatsApp", "Please enter a valid WhatsApp number.")
            return

        membership_type = self.membership_dropdown.currentData()
        membership_text = self.membership_dropdown.currentText()

        if not self._id_token or not self._local_id:
            QMessageBox.critical(self, "Error", "User session not found. Please log in again.")
            return

        # Show loading
        self.set_loading_state(True, "Recording transaction...")
        
        try:
            from datetime import datetime
            import uuid

            transaction_data = {
                "user_id": self._local_id,
                "user_email": self._user_profile.get("email", ""),
                "txid": txid,
                "membership_type": membership_type,
                "membership_text": membership_text,
                "whatsapp": whatsapp,
                "timestamp": datetime.now().isoformat(),
                "status": "pending",
                "amount": 500 if membership_type == "monthly" else 150
            }

            transaction_id = f"{self._local_id}_{int(datetime.now().timestamp())}_{str(uuid.uuid4())[:8]}"

            # Create and start worker thread
            self.transaction_worker = TransactionRecordingWorker(
                self._id_token,
                self._local_id,
                transaction_data,
                transaction_id,
                whatsapp
            )
            self.transaction_worker.progress.connect(self.on_transaction_progress)
            self.transaction_worker.finished.connect(self.on_transaction_finished)
            self.transaction_worker.start()
            
        except Exception as e:
            self.set_loading_state(False)
            debug_log(f"Exception starting transaction recording: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Failed to start recording: {str(e)}")
    
    def on_transaction_progress(self, message: str):
        """Handle transaction recording progress"""
        if self.loading_overlay:
            self.loading_overlay.show_loading(message)
    
    def on_transaction_finished(self, success: bool, result: dict):
        """Handle transaction recording completion"""
        self.set_loading_state(False)
        
        if not success:
            error_msg = result.get("error", "Unknown error")
            QMessageBox.critical(self, "Error", f"Failed to record transaction: {error_msg}")
            return
        
        # Success
        transaction_id = result.get("transaction_id", "Unknown")
        transaction_data = result.get("transaction_data", {})
        membership_text = transaction_data.get("membership_text", "membership")
        txid = transaction_data.get("txid", "")
        whatsapp = transaction_data.get("whatsapp", "")
        
        success_msg = (
            f"Your {membership_text.lower()} membership transaction has been recorded.\n\n"
            f"Transaction ID: {transaction_id}\nTXID: {txid}\nWhatsApp: {whatsapp}\n"
            f"⚠️ Membership is NOT yet active. Wait for admin verification."
        )

        QMessageBox.information(self, "Transaction Recorded", success_msg)
        self.info_label.setText(
            f"Email: {self._user_profile.get('email', '')}\nMembership active: No\nTransaction recorded - awaiting activation"
        )

        self.txid_input.clear()
        self.membership_dropdown.setCurrentIndex(0)
    
    def extract_profile_from_fields(self, fields: dict) -> dict:
        """Extract profile data from Firestore fields"""
        from firebase_client import FirebaseClient
        return {
            "email": FirebaseClient._extract_field_value(fields.get("email"), "string", ""),
            "username": FirebaseClient._extract_field_value(fields.get("username"), "string", ""),
            "whatsapp": FirebaseClient._extract_field_value(fields.get("whatsapp"), "string", ""),
            "membership": FirebaseClient._extract_field_value(fields.get("membership"), "boolean", False),
            "email_verified": FirebaseClient._extract_field_value(fields.get("email_verified"), "boolean", False),
            "membership_expires": FirebaseClient._extract_field_value(fields.get("membership_expires"), "string", ""),
            "membership_type": FirebaseClient._extract_field_value(fields.get("membership_type"), "string", "none"),
            "membership_activated_at": FirebaseClient._extract_field_value(fields.get("membership_activated_at"), "string", ""),
            "membership_activated_by": FirebaseClient._extract_field_value(fields.get("membership_activated_by"), "string", ""),
            "free_trial_used": FirebaseClient._extract_field_value(fields.get("free_trial_used"), "boolean", False),
        }