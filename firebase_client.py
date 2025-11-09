import json
import time
import requests
from pathlib import Path
try:
    # Prefer central config in src if available
    from config import FIREBASE_API_KEY, FIREBASE_PROJECT_ID, CACHE_PATH
except Exception:
    # Fallback: attempt to import from sibling src/app_config if needed
    from app_config import CACHE_PATH  # minimal fallback; API keys should be provided elsewhere
from utils import debug_log

class FirebaseClient:
    """
    Lightweight Firebase REST wrapper for Authentication and Firestore operations
    required by this application with comprehensive referral system fixes.
    """

    @staticmethod
    def _auth_url(path: str) -> str:
        return f"https://identitytoolkit.googleapis.com/v1/{path}?key={FIREBASE_API_KEY}"

    @staticmethod
    def _doc_url(collection: str, doc_id: str) -> str:
        return f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/databases/(default)/documents/{collection}/{doc_id}"

    @staticmethod
    def _to_firestore_value(val):
        """Convert a Python value into Firestore REST 'value' object."""
        if isinstance(val, bool):
            return {"booleanValue": val}
        if isinstance(val, int):
            return {"integerValue": str(val)}
        # Support nested objects
        if isinstance(val, dict):
            # Recursively convert dict to Firestore mapValue
            return {
                "mapValue": {
                    "fields": {k: FirebaseClient._to_firestore_value(v) for k, v in val.items()}
                }
            }
        if isinstance(val, list):
            # Convert list to Firestore arrayValue format
            array_values = []
            for item in val:
                array_values.append(FirebaseClient._to_firestore_value(item))
            return {"arrayValue": {"values": array_values}}
        return {"stringValue": str(val)}

    # ------------------ Authentication ------------------
    @staticmethod
    def signup(email: str, password: str) -> dict:
        """Create a new Firebase Authentication user (email/password)."""
        url = FirebaseClient._auth_url("accounts:signUp")
        payload = {"email": email, "password": password, "returnSecureToken": True}
        r = requests.post(url, json=payload, timeout=15)
        return r.json()

    @staticmethod
    def login(email: str, password: str) -> dict:
        """Sign in a user with email and password; cache idToken and expiry locally."""
        url = FirebaseClient._auth_url("accounts:signInWithPassword")
        payload = {"email": email, "password": password, "returnSecureToken": True}
        r = requests.post(url, json=payload, timeout=15)
        data = r.json()
        if "idToken" in data:
            try:
                expires_in = int(data.get("expiresIn", 3600))
                cache = {
                    "localId": data.get("localId"),
                    "idToken": data.get("idToken"),
                    "refreshToken": data.get("refreshToken"),
                    "expires_at": int(time.time()) + expires_in - 30
                }
                try:
                    CACHE_PATH.write_text(json.dumps(cache))
                except Exception:
                    pass
            except Exception:
                pass
        return data

    @staticmethod
    def refresh_id_token(refresh_token: str) -> dict:
        """Refresh an ID token using a refresh token."""
        url = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}"
        payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        r = requests.post(url, data=payload, timeout=15)
        return r.json()

    @staticmethod
    def ensure_valid_id_token() -> tuple:
        """
        If there's a cached token and it's still valid, return (idToken, localId).
        Otherwise try to refresh using stored refresh_token.
        """
        try:
            if Path(CACHE_PATH).exists():
                cache = json.loads(Path(CACHE_PATH).read_text())
            else:
                cache = None
        except Exception:
            cache = None
        if not cache:
            return None
        if cache.get("expires_at", 0) > int(time.time()):
            return cache.get("idToken"), cache.get("localId")
        resp = FirebaseClient.refresh_id_token(cache.get("refreshToken", ""))
        if "id_token" in resp:
            id_token = resp["id_token"]
            refresh = resp["refresh_token"]
            expires_in = int(resp.get("expires_in", 3600))
            local_id = resp.get("user_id", cache.get("localId"))
            new_cache = {
                "localId": local_id,
                "idToken": id_token,
                "refreshToken": refresh,
                "expires_at": int(time.time()) + expires_in - 30
            }
            try:
                Path(CACHE_PATH).write_text(json.dumps(new_cache))
            except Exception:
                pass
            return id_token, local_id
        return None

    # ------------------ Firestore helpers ------------------
    @staticmethod
    def set_document(id_token: str, collection: str, doc_id: str, data: dict, merge: bool = True) -> dict:
        """
        Write a document at /{collection}/{doc_id} using PATCH.
        The caller must provide a valid id_token to authorize.
        If merge=True, only updates the specified fields (default behavior).
        If merge=False, replaces the entire document.
        """
        url = FirebaseClient._doc_url(collection, doc_id)
        headers = {"Authorization": f"Bearer {id_token}"}
        fields = {k: FirebaseClient._to_firestore_value(v) for k, v in data.items()}
        
        payload = {"fields": fields}
        
        # Add updateMask to ensure we only update specified fields (merge behavior)
        if merge:
            field_paths = list(data.keys())
            url += f"?updateMask.fieldPaths={'&updateMask.fieldPaths='.join(field_paths)}"
        
        r = requests.patch(url, json=payload, headers=headers, timeout=15)
        return r.json()

    @staticmethod
    def get_document(id_token: str, collection: str, doc_id: str) -> dict:
        """Read a Firestore document using the REST API."""
        url = FirebaseClient._doc_url(collection, doc_id)
        headers = {"Authorization": f"Bearer {id_token}"}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 404:
            return {"error": "NOT_FOUND", "status_code": 404}
        return r.json()

    @staticmethod
    def delete_document(id_token: str, collection: str, doc_id: str) -> dict:
        """Delete a Firestore document at /{collection}/{doc_id}."""
        url = FirebaseClient._doc_url(collection, doc_id)
        headers = {"Authorization": f"Bearer {id_token}"}
        r = requests.delete(url, headers=headers, timeout=15)
        return r.json()

    @staticmethod
    def delete_account(id_token: str) -> dict:
        """Delete a Firebase Authentication account."""
        url = FirebaseClient._auth_url("accounts:delete")
        payload = {"idToken": id_token}
        r = requests.post(url, json=payload, timeout=15)
        return r.json()

    # Convenience wrappers for users collection
    @staticmethod
    def set_user_data(id_token: str, user_id: str, data: dict) -> dict:
        return FirebaseClient.set_document(id_token, "users", user_id, data)

    @staticmethod
    def get_user_data(id_token: str, user_id: str) -> dict:
        return FirebaseClient.get_document(id_token, "users", user_id)

    # Referral-specific operations
    @staticmethod
    def set_referral_code_data(id_token: str, referral_code: str, data: dict) -> dict:
        """Store referral code data in referral_codes collection."""
        return FirebaseClient.set_document(id_token, "referral_codes", referral_code, data)

    @staticmethod
    def get_referral_code_data(id_token: str, referral_code: str) -> dict:
        """Get referral code data from referral_codes collection."""
        return FirebaseClient.get_document(id_token, "referral_codes", referral_code)

    @staticmethod
    def _extract_field_value(field_data, field_type="string", default_value=None):
        """Extract value from Firestore field format or direct value."""
        if field_data is None:
            return default_value
            
        # Handle Firestore field format
        if isinstance(field_data, dict):
            # Direct Firestore mapValue to Python dict
            if field_type == "map" and "mapValue" in field_data:
                fields = field_data.get("mapValue", {}).get("fields", {})
                result = {}
                for k, v in fields.items():
                    # Try to infer type from Firestore value shape
                    if isinstance(v, dict):
                        if "stringValue" in v:
                            result[k] = v["stringValue"]
                        elif "booleanValue" in v:
                            result[k] = v["booleanValue"]
                        elif "integerValue" in v:
                            try:
                                result[k] = int(v["integerValue"])
                            except (ValueError, TypeError):
                                result[k] = v["integerValue"]
                        elif "arrayValue" in v:
                            result[k] = FirebaseClient._extract_field_value(v, "array", [])
                        elif "mapValue" in v:
                            result[k] = FirebaseClient._extract_field_value(v, "map", {})
                        else:
                            result[k] = v
                    else:
                        result[k] = v
                return result
            if field_type == "string" and "stringValue" in field_data:
                return field_data["stringValue"]
            elif field_type == "boolean" and "booleanValue" in field_data:
                return field_data["booleanValue"]
            elif field_type == "integer" and "integerValue" in field_data:
                try:
                    return int(field_data["integerValue"])
                except (ValueError, TypeError):
                    return default_value
            elif field_type == "array" and "arrayValue" in field_data:
                values = field_data["arrayValue"].get("values", [])
                # Extract values from array based on their type
                result = []
                for val in values:
                    if isinstance(val, dict):
                        if "stringValue" in val:
                            result.append(val["stringValue"])
                        elif "integerValue" in val:
                            try:
                                result.append(int(val["integerValue"]))
                            except (ValueError, TypeError):
                                result.append(val["integerValue"])
                        elif "booleanValue" in val:
                            result.append(val["booleanValue"])
                        elif "mapValue" in val:
                            # Convert mapValue to Python dict
                            result.append(FirebaseClient._extract_field_value(val, "map", {}))
                        else:
                            # Handle nested objects in array
                            result.append(val)
                    elif isinstance(val, str):
                        result.append(val)
                    else:
                        result.append(val)
                return result
            elif field_type == "map" and "fields" in field_data:
                # Some callers might pass already-unwrapped map fields
                return field_data.get("fields", {})
        
        # Handle direct value
        if field_type == "integer" and isinstance(field_data, str):
            try:
                return int(field_data)
            except (ValueError, TypeError):
                return default_value
        
        return field_data if field_data else default_value

    # ========== FIXED REFERRAL SYSTEM METHODS ==========

    @staticmethod
    def create_referral_code_entry(id_token: str, user_id: str, username: str, referral_code: str) -> dict:
        """
        Create a comprehensive referral code entry in the referral_codes collection.
        This is called when a new user registers.
        """
        try:
            referral_data = {
                "user_id": user_id,
                "username": username,
                "referral_code": referral_code,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "referral_count": 0,
                "total_referred_count": 0,
                "active_referred_count": 0,
                "referred_user_ids": [],
                "referred_user_details": []
            }
            
            result = FirebaseClient.set_referral_code_data(id_token, referral_code, referral_data)
            if "error" in result:
                return {"error": f"Failed to create referral code entry: {result.get('error', 'Unknown error')}"}
            
            debug_log(f"Created referral code entry for user {user_id} with code {referral_code}")
            return {"success": True, "referral_code": referral_code}
            
        except Exception as e:
            debug_log(f"Exception in create_referral_code_entry: {e}")
            return {"error": f"Exception creating referral code entry: {str(e)}"}

    @staticmethod
    def add_referred_user_to_code(id_token: str, referral_code: str, referred_user_id: str, referred_username: str) -> dict:
        """
        FIXED METHOD: Add a referred user to both the referral_codes collection and the referrer's user profile.
        This is the core method that was broken and causing the referral count issues.
        """
        try:
            debug_log(f"Adding referred user {referred_user_id} to referral code {referral_code}")
            
            # Get current referral code data
            referral_data = FirebaseClient.get_referral_code_data(id_token, referral_code)
            if "error" in referral_data:
                debug_log(f"Referral code {referral_code} not found")
                return {"error": f"Referral code {referral_code} not found"}
            
            fields = referral_data.get("fields", {})
            referrer_user_id = FirebaseClient._extract_field_value(fields.get("user_id"), "string", "")
            
            if not referrer_user_id:
                return {"error": "No valid referrer found for this code"}
            
            # Get current arrays
            current_user_ids = FirebaseClient._extract_field_value(fields.get("referred_user_ids"), "array", [])
            current_user_details = FirebaseClient._extract_field_value(fields.get("referred_user_details"), "array", [])
            
            # Check if user is already in the list
            if referred_user_id in current_user_ids:
                debug_log(f"User {referred_user_id} already in referral list for code {referral_code}")
                return {"success": True, "message": "User already tracked"}
            
            # Add the new user
            current_user_ids.append(referred_user_id)
            
            # Create user detail entry
            user_detail = {
                "user_id": referred_user_id,
                "username": referred_username,
                "referred_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "membership_status": False,  # Will be updated when they get membership
                "membership_type": "none"
            }
            current_user_details.append(user_detail)
            
            # Calculate new counts
            total_count = len(current_user_ids)
            active_count = 0
            
            # Count active memberships
            for detail in current_user_details:
                if isinstance(detail, dict) and detail.get("membership_status", False):
                    active_count += 1
            
            # Update referral_codes collection
            update_data = {
                "referred_user_ids": current_user_ids,
                "referred_user_details": current_user_details,
                "total_referred_count": total_count,
                "active_referred_count": active_count,
                "referral_count": active_count,  # For backward compatibility
                "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
            }
            
            result = FirebaseClient.set_referral_code_data(id_token, referral_code, update_data)
            if "error" in result:
                return {"error": f"Failed to update referral code data: {result.get('error', 'Unknown error')}"}
            
            # Also update the referrer's user profile
            referrer_profile_update = {
                "referred_user_ids": current_user_ids,
                "referral_count": active_count,
                "total_referred_count": total_count,
                "active_referred_count": active_count
            }
            
            user_result = FirebaseClient.set_user_data(id_token, referrer_user_id, referrer_profile_update)
            if "error" in user_result:
                debug_log(f"Failed to update referrer user profile: {user_result.get('error', 'Unknown error')}")
            
            debug_log(f"Successfully added user {referred_user_id} to referral code {referral_code}. Total: {total_count}, Active: {active_count}")
            return {
                "success": True,
                "total_referred_count": total_count,
                "active_referred_count": active_count,
                "referrer_user_id": referrer_user_id
            }
            
        except Exception as e:
            debug_log(f"Exception in add_referred_user_to_code: {e}")
            return {"error": f"Exception adding referred user: {str(e)}"}

    @staticmethod
    def process_referral_during_registration(id_token: str, new_user_id: str, username: str, referral_code: str) -> dict:
        """
        NEW METHOD: Comprehensive referral processing during user registration.
        This replaces the incomplete logic that was causing referral tracking failures.
        """
        try:
            debug_log(f"Processing referral during registration for user {new_user_id} with code {referral_code}")
            
            if not referral_code:
                return {"success": True, "message": "No referral code provided"}
            
            # Validate referral code exists
            referral_data = FirebaseClient.get_referral_code_data(id_token, referral_code)
            if "error" in referral_data:
                return {"error": f"Referral code {referral_code} not found"}
            
            fields = referral_data.get("fields", {})
            referrer_user_id = FirebaseClient._extract_field_value(fields.get("user_id"), "string", "")
            
            if not referrer_user_id:
                return {"error": "No valid referrer found for this code"}
            
            if referrer_user_id == new_user_id:
                return {"error": "Cannot use your own referral code"}
            
            # Add the new user to the referral tracking
            add_result = FirebaseClient.add_referred_user_to_code(id_token, referral_code, new_user_id, username)
            if "error" in add_result:
                return add_result
            
            debug_log(f"Successfully processed referral: {new_user_id} referred by {referrer_user_id} using code {referral_code}")
            return {
                "success": True,
                "referrer_user_id": referrer_user_id,
                "referral_code": referral_code,
                "message": f"Referral tracking established with {referrer_user_id}"
            }
            
        except Exception as e:
            debug_log(f"Exception in process_referral_during_registration: {e}")
            return {"error": f"Exception processing referral: {str(e)}"}

    @staticmethod
    def update_referral_membership_status(id_token: str, user_id: str, has_membership: bool, membership_type: str = "none", membership_code: str = None) -> dict:
        """
        NEW METHOD: Update membership status across all referral tracking when a user's membership changes.
        This ensures referral counts are accurate when users activate or lose membership.
        """
        try:
            debug_log(f"Updating referral membership status for user {user_id}: membership={has_membership}, type={membership_type}")
            
            # Get user's profile to find who referred them and their referral code
            user_data = FirebaseClient.get_user_data(id_token, user_id)
            if "error" in user_data:
                return {"error": "User not found"}
            
            user_fields = user_data.get("fields", {})
            referred_by = FirebaseClient._extract_field_value(user_fields.get("referred_by"), "string", "")
            user_referral_code = FirebaseClient._extract_field_value(user_fields.get("referral_code"), "string", "")
            
            results = []
            
            # Get membership_code from user data if not provided
            if membership_code is None:
                membership_code = FirebaseClient._extract_field_value(user_fields.get("membership_code"), "string", None)
            
            # Update the referrer's tracking if this user was referred by someone
            if referred_by:
                # Find the referrer's referral code
                referrer_data = FirebaseClient.get_user_data(id_token, referred_by)
                if "error" not in referrer_data:
                    referrer_fields = referrer_data.get("fields", {})
                    referrer_code = FirebaseClient._extract_field_value(referrer_fields.get("referral_code"), "string", "")
                    
                    if referrer_code:
                        update_result = FirebaseClient._update_referral_code_membership_counts(
                            id_token, referrer_code, user_id, has_membership, membership_type, membership_code
                        )
                        results.append(f"Updated referrer {referred_by} tracking: {update_result.get('message', 'Unknown')}")
            
            # Update this user's own referral code tracking for their referred users
            if user_referral_code:
                sync_result = FirebaseClient._sync_referral_code_counts(id_token, user_referral_code)
                results.append(f"Synced user's own referral code {user_referral_code}: {sync_result.get('message', 'Unknown')}")
            
            return {"success": True, "results": results}
            
        except Exception as e:
            debug_log(f"Exception in update_referral_membership_status: {e}")
            return {"error": f"Exception updating referral membership status: {str(e)}"}

    @staticmethod
    def _update_referral_code_membership_counts(id_token: str, referral_code: str, user_id: str, has_membership: bool, membership_type: str, membership_code: str = None) -> dict:
        """
        Helper method to update membership status for a specific user in a referral code's tracking.
        """
        try:
            # Get current referral code data
            referral_data = FirebaseClient.get_referral_code_data(id_token, referral_code)
            if "error" in referral_data:
                return {"error": f"Referral code {referral_code} not found"}
            
            fields = referral_data.get("fields", {})
            current_user_details = FirebaseClient._extract_field_value(fields.get("referred_user_details"), "array", [])
            referrer_user_id = FirebaseClient._extract_field_value(fields.get("user_id"), "string", "")
            
            # Update the specific user's membership status in the details array
            updated_details = []
            user_found = False
            
            for detail in current_user_details:
                if isinstance(detail, dict) and detail.get("user_id") == user_id:
                    detail["membership_status"] = has_membership
                    detail["membership_type"] = membership_type
                    if membership_code:
                        detail["membership_code"] = membership_code
                    detail["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
                    user_found = True
                updated_details.append(detail)
            
            if not user_found:
                # Backfill a missing detail entry so legacy codes that only have IDs can update counts
                try:
                    user_profile = FirebaseClient.get_user_data(id_token, user_id)
                    user_fields = user_profile.get("fields", {}) if isinstance(user_profile, dict) else {}
                    username = FirebaseClient._extract_field_value(user_fields.get("username"), "string", "Unknown")
                    if membership_code is None:
                        membership_code = FirebaseClient._extract_field_value(user_fields.get("membership_code"), "string", None)
                except Exception:
                    username = "Unknown"
                new_detail = {
                    "user_id": user_id,
                    "username": username,
                    "membership_status": has_membership,
                    "membership_type": membership_type,
                    "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
                }
                if membership_code:
                    new_detail["membership_code"] = membership_code
                updated_details.append(new_detail)
            
            # Recalculate active count
            active_count = sum(1 for detail in updated_details 
                             if isinstance(detail, dict) and detail.get("membership_status", False))
            total_count = len(updated_details)
            
            # Update referral_codes collection
            update_data = {
                "referred_user_details": updated_details,
                "active_referred_count": active_count,
                "referral_count": active_count,
                "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
            }
            
            result = FirebaseClient.set_referral_code_data(id_token, referral_code, update_data)
            if "error" in result:
                return {"error": f"Failed to update referral code: {result.get('error', 'Unknown error')}"}
            
            # Also update the referrer's user profile
            if referrer_user_id:
                referrer_update = {
                    "referral_count": active_count,
                    "active_referred_count": active_count
                }
                FirebaseClient.set_user_data(id_token, referrer_user_id, referrer_update)
            
            debug_log(f"Updated membership status for user {user_id} in referral code {referral_code}. Active count: {active_count}")
            return {"success": True, "active_count": active_count, "total_count": total_count, "message": f"Updated to {active_count} active referrals"}
            
        except Exception as e:
            debug_log(f"Exception in _update_referral_code_membership_counts: {e}")
            return {"error": f"Exception updating membership counts: {str(e)}"}

    @staticmethod
    def _sync_referral_code_counts(id_token: str, referral_code: str) -> dict:
        """
        Helper method to synchronize referral counts by checking current membership status of all referred users.
        """
        try:
            referral_data = FirebaseClient.get_referral_code_data(id_token, referral_code)
            if "error" in referral_data:
                return {"error": f"Referral code {referral_code} not found"}
            
            fields = referral_data.get("fields", {})
            user_ids = FirebaseClient._extract_field_value(fields.get("referred_user_ids"), "array", [])
            referrer_user_id = FirebaseClient._extract_field_value(fields.get("user_id"), "string", "")

            active_count = 0
            updated_details = []
            permission_error = False

            # Attempt to check each referred user's current membership status
            for user_id in user_ids:
                user_data = FirebaseClient.get_user_data(id_token, user_id)
                if isinstance(user_data, dict) and user_data.get("error"):
                    # Likely permission denied for this client; fallback to stored details
                    permission_error = True
                    break

                user_fields = user_data.get("fields", {}) if isinstance(user_data, dict) else {}
                has_membership = FirebaseClient._extract_field_value(user_fields.get("membership"), "boolean", False)
                membership_type = FirebaseClient._extract_field_value(user_fields.get("membership_type"), "string", "none")
                username = FirebaseClient._extract_field_value(user_fields.get("username"), "string", "Unknown")
                membership_code = FirebaseClient._extract_field_value(user_fields.get("membership_code"), "string", None)

                if has_membership:
                    active_count += 1

                detail = {
                    "user_id": user_id,
                    "username": username,
                    "membership_status": has_membership,
                    "membership_type": membership_type,
                    "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
                }
                if membership_code:
                    detail["membership_code"] = membership_code
                updated_details.append(detail)

            if permission_error:
                # Fallback: use existing referred_user_details to compute counts without overwriting with zeros
                existing_details = FirebaseClient._extract_field_value(fields.get("referred_user_details"), "array", [])
                active_count = 0
                computed_details = []
                for d in existing_details:
                    if isinstance(d, dict):
                        status = d.get("membership_status", False)
                        if isinstance(status, str):
                            status = status.lower() == "true"
                        if bool(status):
                            active_count += 1
                        # Preserve membership_code if it exists
                        computed_details.append(d)
                updated_details = computed_details if computed_details else existing_details

            # Prepare update data; do not reduce counts artificially
            total_count = len(user_ids)
            update_data = {
                "active_referred_count": active_count,
                "referral_count": active_count,
                "total_referred_count": total_count,
                "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
            }
            if updated_details:
                update_data["referred_user_details"] = updated_details

            result = FirebaseClient.set_referral_code_data(id_token, referral_code, update_data)
            if isinstance(result, dict) and result.get("error"):
                return {"error": f"Failed to sync referral code: {result.get('error', 'Unknown error')}"}

            # Update referrer's user profile
            if referrer_user_id:
                referrer_update = {
                    "referral_count": active_count,
                    "active_referred_count": active_count,
                    "total_referred_count": total_count
                }
                FirebaseClient.set_user_data(id_token, referrer_user_id, referrer_update)

            debug_log(f"Synced referral code {referral_code}: {active_count} active out of {total_count} total referrals")
            return {"success": True, "active_count": active_count, "total_count": total_count, "message": f"Synced {active_count} active referrals"}
            
        except Exception as e:
            debug_log(f"Exception in _sync_referral_code_counts: {e}")
            return {"error": f"Exception syncing referral counts: {str(e)}"}

    @staticmethod
    def update_user_membership(id_token: str, user_id: str, membership_data: dict) -> dict:
        """
        ENHANCED METHOD: Update user membership and automatically trigger referral count updates.
        This replaces the basic membership update to include referral system synchronization.
        Generates a unique membership code when membership is activated.
        """
        try:
            debug_log(f"Updating membership for user {user_id} with data: {membership_data}")
            
            # Generate membership code if membership is being activated
            has_membership = membership_data.get("membership", False)
            if has_membership:
                # Check if membership_code already exists (don't regenerate if already set)
                if "membership_code" not in membership_data:
                    from utils import generate_membership_code
                    membership_code = generate_membership_code(8, user_id)
                    membership_data["membership_code"] = membership_code
                    debug_log(f"Generated membership code {membership_code} for user {user_id}")
            
            # Update the user's membership data
            result = FirebaseClient.set_user_data(id_token, user_id, membership_data)
            if "error" in result:
                return result
            
            # Trigger referral system updates if membership status changed
            membership_type = membership_data.get("membership_type", "none")
            membership_code = membership_data.get("membership_code")
            
            referral_result = FirebaseClient.update_referral_membership_status(
                id_token, user_id, has_membership, membership_type, membership_code
            )
            
            if "error" in referral_result:
                debug_log(f"Membership updated but referral sync failed: {referral_result.get('error', 'Unknown error')}")
            else:
                debug_log(f"Membership and referral counts updated successfully for user {user_id}")
            
            return {"success": True, "membership_updated": True, "referral_sync": referral_result, "membership_code": membership_data.get("membership_code")}
            
        except Exception as e:
            debug_log(f"Exception in update_user_membership: {e}")
            return {"error": f"Exception updating user membership: {str(e)}"}

    @staticmethod
    def get_comprehensive_referral_data(id_token: str, user_id: str) -> dict:
        """
        NEW METHOD: Get comprehensive referral data for a user including all tracking information.
        This provides complete referral system information for display in the UI.
        """
        try:
            debug_log(f"Getting comprehensive referral data for user {user_id}")
            
            # Get user's basic data
            user_data = FirebaseClient.get_user_data(id_token, user_id)
            if "error" in user_data:
                return {"error": "User not found"}
            
            user_fields = user_data.get("fields", {})
            user_referral_code = FirebaseClient._extract_field_value(user_fields.get("referral_code"), "string", "")
            referred_by = FirebaseClient._extract_field_value(user_fields.get("referred_by"), "string", "")
            
            comprehensive_data = {
                "user_id": user_id,
                "referral_code": user_referral_code,
                "referred_by": referred_by,
                "referral_count": 0,
                "total_referred_count": 0,
                "active_referred_count": 0,
                "referred_user_details": [],
                "referred_user_ids": []
            }
            
            # Get detailed referral code data if user has one
            if user_referral_code:
                referral_data = FirebaseClient.get_referral_code_data(id_token, user_referral_code)
                if "error" not in referral_data:
                    referral_fields = referral_data.get("fields", {})
                    
                    comprehensive_data.update({
                        "referral_count": FirebaseClient._extract_field_value(referral_fields.get("referral_count"), "integer", 0),
                        "total_referred_count": FirebaseClient._extract_field_value(referral_fields.get("total_referred_count"), "integer", 0),
                        "active_referred_count": FirebaseClient._extract_field_value(referral_fields.get("active_referred_count"), "integer", 0),
                        "referred_user_details": FirebaseClient._extract_field_value(referral_fields.get("referred_user_details"), "array", []),
                        "referred_user_ids": FirebaseClient._extract_field_value(referral_fields.get("referred_user_ids"), "array", [])
                    })
            
            # Do not forcibly sync here; prefer stored counts to avoid permission-induced zeroing
            
            debug_log(f"Retrieved comprehensive referral data for {user_id}: {comprehensive_data['active_referred_count']} active, {comprehensive_data['total_referred_count']} total")
            return {"success": True, "data": comprehensive_data}
            
        except Exception as e:
            debug_log(f"Exception in get_comprehensive_referral_data: {e}")
            return {"error": f"Exception getting referral data: {str(e)}"}

    @staticmethod
    def sync_referral_data_on_login(id_token: str, user_id: str) -> dict:
        """
        NEW METHOD: Comprehensive referral data synchronization that runs on every login.
        This ensures all referral relationships and counts are accurate.
        """
        try:
            debug_log(f"Starting comprehensive referral sync for user {user_id}")
            
            # Get user's referral code
            user_data = FirebaseClient.get_user_data(id_token, user_id)
            if "error" in user_data:
                return {"error": "User not found"}
            
            user_fields = user_data.get("fields", {})
            user_referral_code = FirebaseClient._extract_field_value(user_fields.get("referral_code"), "string", "")
            
            actions = []
            
            # Sync the user's own referral code if they have one
            if user_referral_code:
                sync_result = FirebaseClient._sync_referral_code_counts(id_token, user_referral_code)
                if "success" in sync_result:
                    actions.append(f"Synced referral code {user_referral_code}: {sync_result['message']}")
                else:
                    actions.append(f"Failed to sync referral code {user_referral_code}: {sync_result.get('error', 'Unknown')}")
            
            # Update membership status in referral tracking
            has_membership = FirebaseClient._extract_field_value(user_fields.get("membership"), "boolean", False)
            membership_type = FirebaseClient._extract_field_value(user_fields.get("membership_type"), "string", "none")
            
            membership_update_result = FirebaseClient.update_referral_membership_status(
                id_token, user_id, has_membership, membership_type
            )
            
            if "success" in membership_update_result:
                actions.extend(membership_update_result.get("results", []))
            else:
                actions.append(f"Failed to update membership status in referral tracking: {membership_update_result.get('error', 'Unknown')}")
            
            debug_log(f"Completed referral sync for user {user_id}: {len(actions)} actions performed")
            return {"success": True, "results": {"actions": actions, "user_id": user_id}}
            
        except Exception as e:
            debug_log(f"Exception in sync_referral_data_on_login: {e}")
            return {"error": f"Exception during referral sync: {str(e)}"}

    # ========== REFERRAL CODE VALIDATION METHODS ==========
    
    @staticmethod
    def _get_anonymous_token() -> str:
        """Get an anonymous authentication token for public operations"""
        try:
            import requests
            url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_API_KEY}"
            payload = {"returnSecureToken": True}
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("idToken", "")
            else:
                debug_log(f"Anonymous auth failed: {resp.status_code} - {resp.text}")
                return ""
        except Exception as e:
            debug_log(f"Anonymous auth error: {e}")
            return ""
    
    @staticmethod
    def validate_referral_code(id_token: str, referral_code: str) -> dict:
        """
        Validate a referral code and return referrer information.
        This method checks if the referral code exists and returns the referrer's details.
        Can work without id_token for public validation during registration.
        """
        try:
            if not referral_code or not referral_code.strip():
                return {"error": "Referral code cannot be empty"}
            
            referral_code = referral_code.strip().upper()
            
            if id_token:
                # Authenticated validation - can access full user data
                referral_data = FirebaseClient.get_referral_code_data(id_token, referral_code)
            else:
                # --- Use Firebase REST API with API key for public read access ---
                try:
                    import requests
                    
                    # Since Firestore rules now allow public read access (allow read: if true),
                    # we can use the API key directly without authentication
                    firestore_url = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/databases/(default)/documents/referral_codes/{referral_code}"
                    params = {"key": FIREBASE_API_KEY}
                    
                    resp = requests.get(firestore_url, params=params, timeout=10)
                    debug_log(f"Firestore API response: {resp.status_code}")
                    
                    if resp.status_code == 404:
                        return {"error": f"Referral code '{referral_code}' not found"}
                    if resp.status_code != 200:
                        debug_log(f"Firestore API error: {resp.status_code} - {resp.text}")
                        return {"error": f"Error accessing database: {resp.status_code}"}
                    
                    referral_data = resp.json()
                    
                except Exception as e:
                    debug_log(f"Referral validation error: {e}")
                    return {"error": f"Unable to validate referral code: {str(e)}"}
            
            if "error" in referral_data:
                return {"error": f"Referral code '{referral_code}' not found"}
            
            # Extract referrer information
            fields = referral_data.get("fields", {})
            referrer_user_id = FirebaseClient._extract_field_value(fields.get("user_id"), "string", "")
            referrer_username = FirebaseClient._extract_field_value(fields.get("username"), "string", "")
            referral_count = FirebaseClient._extract_field_value(fields.get("referral_count"), "integer", 0)
            total_referred_count = FirebaseClient._extract_field_value(fields.get("total_referred_count"), "integer", 0)
            active_referred_count = FirebaseClient._extract_field_value(fields.get("active_referred_count"), "integer", 0)
            
            if not referrer_user_id:
                return {"error": "Invalid referral code - no referrer found"}
            
            # Get referrer's profile for additional info (only if we have id_token)
            referrer_email = ""
            if id_token:
                referrer_profile = FirebaseClient.get_user_data(id_token, referrer_user_id)
                if "error" not in referrer_profile:
                    referrer_fields = referrer_profile.get("fields", {})
                    referrer_email = FirebaseClient._extract_field_value(referrer_fields.get("email"), "string", "")
            
            return {
                "success": True,
                "referral_code": referral_code,
                "referrer_user_id": referrer_user_id,
                "referrer_username": referrer_username,
                "referrer_email": referrer_email,
                "referral_count": referral_count,
                "total_referred_count": total_referred_count,
                "active_referred_count": active_referred_count,
                "message": f"Valid referral code! You will be referred by {referrer_username} (ID: {referrer_user_id})"
            }
            
        except Exception as e:
            debug_log(f"Exception in validate_referral_code: {e}")
            return {"error": f"Exception validating referral code: {str(e)}"}

    # ========== EMAIL VERIFICATION METHODS ==========

    @staticmethod
    def generate_and_send_verification(email: str, password: str) -> tuple:
        """
        Create a Firebase user account and send email verification.
        Returns (success, payload) where payload contains user data or error info.
        """
        try:
            # Create the user account
            signup_result = FirebaseClient.signup(email, password)
            
            if "error" in signup_result:
                return False, signup_result
            
            if "idToken" not in signup_result:
                return False, {"error": {"message": "No idToken received from signup"}}
            
            # Send verification email
            id_token = signup_result["idToken"]
            verification_result = FirebaseClient.send_email_verification(id_token)
            
            if "error" in verification_result:
                # If verification email fails, we still return the user data
                # but indicate the email wasn't sent
                return False, {
                    "error": {"message": f"Account created but verification email failed: {verification_result.get('error', 'Unknown error')}"},
                    "user_data": signup_result
                }
            
            return True, signup_result
            
        except Exception as e:
            return False, {"error": {"message": f"Exception during signup: {str(e)}"}}

    @staticmethod
    def send_email_verification(id_token: str) -> dict:
        """Send email verification to the authenticated user."""
        url = FirebaseClient._auth_url("accounts:sendOobCode")
        payload = {
            "requestType": "VERIFY_EMAIL",
            "idToken": id_token
        }
        try:
            r = requests.post(url, json=payload, timeout=15)
            return r.json()
        except Exception as e:
            return {"error": f"Request failed: {str(e)}"}

    @staticmethod
    def check_email_verification_status(id_token: str, local_id: str) -> tuple:
        """
        Check if the user's email has been verified.
        Returns (is_verified, message)
        """
        try:
            # Get user info to check email verification status
            url = FirebaseClient._auth_url("accounts:lookup")
            payload = {"idToken": id_token}
            
            r = requests.post(url, json=payload, timeout=15)
            data = r.json()
            
            if "error" in data:
                return False, f"Error checking verification: {data.get('error', {}).get('message', 'Unknown error')}"
            
            users = data.get("users", [])
            if not users:
                return False, "No user data found"
            
            user = users[0]
            email_verified = user.get("emailVerified", False)
            
            if email_verified:
                return True, "Email has been verified successfully!"
            else:
                return False, "Email not yet verified. Please check your inbox and click the verification link."
                
        except Exception as e:
            return False, f"Exception checking verification: {str(e)}"

    # ========== REWARDS SYSTEM METHODS ==========

    @staticmethod
    def get_user_rewards(id_token: str, user_id: str) -> dict:
        """Get user's reward data from rewards collection"""
        try:
            result = FirebaseClient.get_document(id_token, "rewards", user_id)
            if "error" in result and result.get("error") == "NOT_FOUND":
                # Return default rewards structure if not found
                return {
                    "success": True,
                    "data": {
                        "user_id": user_id,
                    "monthly_rewards": 0,
                    "weekly_rewards": 0,
                    "total_rewards": 0,
                    "withdrawn_amount": 0,
                    "available_balance": 0,
                    "last_calculated": None,
                    "used_membership_codes": []
                }
                }
            if "error" in result:
                return result
            
            fields = result.get("fields", {})
            used_codes_array = FirebaseClient._extract_field_value(fields.get("used_membership_codes"), "array", [])
            # Convert array of values to list of strings
            used_membership_codes = []
            if isinstance(used_codes_array, list):
                for code_item in used_codes_array:
                    if isinstance(code_item, dict):
                        # Extract string value from Firestore format
                        code_value = FirebaseClient._extract_field_value(code_item, "string", None)
                        if code_value:
                            used_membership_codes.append(code_value)
                    elif isinstance(code_item, str):
                        used_membership_codes.append(code_item)
            
            return {
                "success": True,
                "data": {
                    "user_id": user_id,
                    "monthly_rewards": FirebaseClient._extract_field_value(fields.get("monthly_rewards"), "integer", 0),
                    "weekly_rewards": FirebaseClient._extract_field_value(fields.get("weekly_rewards"), "integer", 0),
                    "total_rewards": FirebaseClient._extract_field_value(fields.get("total_rewards"), "integer", 0),
                    "withdrawn_amount": FirebaseClient._extract_field_value(fields.get("withdrawn_amount"), "integer", 0),
                    "available_balance": FirebaseClient._extract_field_value(fields.get("available_balance"), "integer", 0),
                    "last_calculated": FirebaseClient._extract_field_value(fields.get("last_calculated"), "string", None),
                    "used_membership_codes": used_membership_codes
                }
            }
        except Exception as e:
            debug_log(f"Exception in get_user_rewards: {e}")
            return {"error": f"Exception getting user rewards: {str(e)}"}

    @staticmethod
    def update_user_rewards(id_token: str, user_id: str, rewards_data: dict) -> dict:
        """Update or create user's reward data in rewards collection"""
        try:
            rewards_data["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
            result = FirebaseClient.set_document(id_token, "rewards", user_id, rewards_data)
            if "error" in result:
                return result
            return {"success": True, "data": rewards_data}
        except Exception as e:
            debug_log(f"Exception in update_user_rewards: {e}")
            return {"error": f"Exception updating user rewards: {str(e)}"}

    @staticmethod
    def record_withdrawal(id_token: str, user_id: str, withdrawal_data: dict) -> dict:
        """Record a withdrawal request in withdraw_details collection"""
        try:
            withdrawal_id = withdrawal_data.get("withdrawal_id", f"{user_id}_{int(time.time())}")
            withdrawal_data["withdrawal_id"] = withdrawal_id
            withdrawal_data["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
            withdrawal_data["status"] = "pending"
            
            result = FirebaseClient.set_document(id_token, "withdraw_details", withdrawal_id, withdrawal_data)
            if "error" in result:
                return result
            return {"success": True, "withdrawal_id": withdrawal_id, "data": withdrawal_data}
        except Exception as e:
            debug_log(f"Exception in record_withdrawal: {e}")
            return {"error": f"Exception recording withdrawal: {str(e)}"}