from PySide6.QtCore import QThread, Signal
from firebase_client import FirebaseClient
from config import _TEMP_SIGNUPS

class SignupWorker(QThread):
    finished = Signal(bool, dict)  # success, payload
    progress = Signal(str)
    
    def __init__(self, email: str, password: str):
        super().__init__()
        self.email = email
        self.password = password
    
    def run(self):
        try:
            self.progress.emit("Starting signup...")
            sent, payload = FirebaseClient.generate_and_send_verification(self.email, self.password)
            if isinstance(payload, dict) and "error" in payload and not sent:
                self.finished.emit(False, payload)
                return
            if not sent:
                self.finished.emit(False, {"message": "Email send failed", "payload": payload})
                return
            _TEMP_SIGNUPS.append((payload.get("idToken"), payload.get("localId")))
            self.finished.emit(True, payload)
        except Exception as e:
            self.finished.emit(False, {"exception": str(e)})

class VerifyWorker(QThread):
    finished = Signal(bool, str)
    
    def __init__(self, id_token: str, local_id: str):
        super().__init__()
        self.id_token = id_token
        self.local_id = local_id
    
    def run(self):
        try:
            ok, msg = FirebaseClient.check_email_verification_status(self.id_token, self.local_id)
            if ok:
                try:
                    _TEMP_SIGNUPS.remove((self.id_token, self.local_id))
                except Exception:
                    pass
            self.finished.emit(ok, msg)
        except Exception as e:
            self.finished.emit(False, str(e))

class LoginWorker(QThread):
    finished = Signal(bool, dict)
    
    def __init__(self, email: str, password: str):
        super().__init__()
        self.email = email
        self.password = password
    
    def run(self):
        try:
            data = FirebaseClient.login(self.email, self.password)
            if "idToken" in data:
                id_token = data.get("idToken")
                local_id = data.get("localId")
                
                # FIXED: Properly fetch complete user profile from Firestore
                profile = FirebaseClient.get_user_data(id_token, local_id)
                fields = profile.get("fields", {}) if isinstance(profile, dict) and "error" not in profile else {}
                
                # Use helper method to extract field values properly
                user = {
                    "localId": local_id,
                    "idToken": id_token,
                    "email": data.get("email", self.email),
                    "username": FirebaseClient._extract_field_value(fields.get("username"), "string", self.email.split("@")[0]),
                    "membership": FirebaseClient._extract_field_value(fields.get("membership"), "boolean", False),
                    "email_verified": FirebaseClient._extract_field_value(fields.get("email_verified"), "boolean", False),
                    "membership_expires": FirebaseClient._extract_field_value(fields.get("membership_expires"), "string", ""),
                    "membership_type": FirebaseClient._extract_field_value(fields.get("membership_type"), "string", "none"),
                    "referral_code": FirebaseClient._extract_field_value(fields.get("referral_code"), "string", ""),
                    "referral_count": FirebaseClient._extract_field_value(fields.get("referral_count"), "integer", 0),
                    "total_referred_count": FirebaseClient._extract_field_value(fields.get("total_referred_count"), "integer", 0),
                    "active_referred_count": FirebaseClient._extract_field_value(fields.get("active_referred_count"), "integer", 0),
                    "referred_by": FirebaseClient._extract_field_value(fields.get("referred_by"), "string", ""),
                    "whatsapp": FirebaseClient._extract_field_value(fields.get("whatsapp"), "string", ""),
                    "raw_profile": profile
                }
                
                # Handle alternative data formats for referral fields
                if not user["referral_code"]:
                    if isinstance(fields.get("referral_code"), str):
                        user["referral_code"] = fields["referral_code"]
                    elif isinstance(fields.get("referral_code"), dict) and "stringValue" in fields["referral_code"]:
                        user["referral_code"] = fields["referral_code"]["stringValue"]

                if user["referral_count"] == 0:
                    if isinstance(fields.get("referral_count"), int):
                        user["referral_count"] = fields["referral_count"]
                    elif isinstance(fields.get("referral_count"), str):
                        try:
                            user["referral_count"] = int(fields["referral_count"])
                        except ValueError:
                            user["referral_count"] = 0
                    elif isinstance(fields.get("referral_count"), dict) and "integerValue" in fields["referral_count"]:
                        try:
                            user["referral_count"] = int(fields["referral_count"]["integerValue"])
                        except ValueError:
                            user["referral_count"] = 0

                if not user["referred_by"]:
                    if isinstance(fields.get("referred_by"), str):
                        user["referred_by"] = fields["referred_by"]
                    elif isinstance(fields.get("referred_by"), dict) and "stringValue" in fields["referred_by"]:
                        user["referred_by"] = fields["referred_by"]["stringValue"]
                
                # Extract free_trial_used field
                user["free_trial_used"] = FirebaseClient._extract_field_value(fields.get("free_trial_used"), "boolean", False)
                if isinstance(user["free_trial_used"], str):
                    user["free_trial_used"] = user["free_trial_used"].lower() == "true"
                
                # Ensure referral_count is always an integer
                if isinstance(user["referral_count"], str):
                    try:
                        user["referral_count"] = int(user["referral_count"])
                    except ValueError:
                        user["referral_count"] = 0
                if isinstance(user["membership"], str):
                    user["membership"] = user["membership"].lower() == "true"
                if isinstance(user["email_verified"], str):
                    user["email_verified"] = user["email_verified"].lower() == "true"
                self.finished.emit(True, user)
            else:
                self.finished.emit(False, data)
        except Exception as e:
            self.finished.emit(False, {"exception": str(e)})

class DeleteTempWorker(QThread):
    finished = Signal(bool, dict)
    
    def __init__(self, id_token: str, local_id: str):
        super().__init__()
        self.id_token = id_token
        self.local_id = local_id
    
    def run(self):
        info = {}
        try:
            try:
                FirebaseClient.delete_account(self.id_token)
            except Exception as e:
                info["delete_account_err"] = str(e)
            self.finished.emit(True, info)
        except Exception as e:
            self.finished.emit(False, {"exception": str(e)})


class ReferralSyncWorker(QThread):
    """
    Worker to run FirebaseClient.sync_referral_data_on_login in a background thread
    and emit the result back to the main thread.
    Emits:
        finished(bool, dict) - success flag and result or error dict
        progress(str) - optional progress messages
    """
    finished = Signal(bool, dict)
    progress = Signal(str)

    def __init__(self, id_token: str, local_id: str):
        super().__init__()
        self.id_token = id_token
        self.local_id = local_id

    def run(self):
        try:
            # Emit initial progress if UI wants it
            try:
                self.progress.emit("Starting referral synchronization...")
            except Exception:
                pass

            result = FirebaseClient.sync_referral_data_on_login(self.id_token, self.local_id)

            if isinstance(result, dict):
                self.finished.emit(True, result)
            else:
                # normalize to dict
                self.finished.emit(True, {"results": result})
        except Exception as e:
            self.finished.emit(False, {"exception": str(e)})
