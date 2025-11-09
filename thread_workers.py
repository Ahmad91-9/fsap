"""
Comprehensive thread workers for all blocking operations in the application.
This ensures the GUI remains responsive during all operations.
"""
import sys
import os
import json
import time
import requests
import tempfile
import shutil
import subprocess
import importlib.util
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from firebase_client import FirebaseClient
from utils import debug_log


class AppLaunchWorker(QThread):
    """Worker for launching applications in background thread"""
    finished = Signal(bool, str, object)  # success, message, window/process
    progress = Signal(str)
    
    def __init__(self, app_name: str, app_type: str, app_path: str = "", username: str = ""):
        super().__init__()
        self.app_name = app_name
        self.app_type = app_type  # 'local', 'github', 'github_gui'
        self.app_path = app_path
        self.username = username
        self.window = None
        self.process = None
    
    def run(self):
        try:
            self.progress.emit(f"Launching {self.app_name}...")
            
            if self.app_type == 'local':
                success = self._launch_local()
            elif self.app_type == 'github':
                success = self._launch_github()
            elif self.app_type == 'github_gui':
                success = self._launch_github_gui()
            else:
                self.finished.emit(False, f"Unknown app type: {self.app_type}", None)
                return
            
            if success:
                self.finished.emit(True, f"{self.app_name} launched successfully", self.window or self.process)
            else:
                self.finished.emit(False, f"Failed to launch {self.app_name}", None)
                
        except Exception as e:
            debug_log(f"Exception in AppLaunchWorker: {e}")
            self.finished.emit(False, f"Exception launching {self.app_name}: {str(e)}", None)
    
    def _launch_local(self):
        """Launch local application"""
        try:
            if not os.path.exists(self.app_path):
                return False
            
            env = os.environ.copy()
            if self.username:
                env["SAAS_USERNAME"] = self.username
            
            cmd_args = [sys.executable, self.app_path]
            if self.username:
                cmd_args.append(self.username)
            
            self.process = subprocess.Popen(cmd_args, env=env)
            debug_log(f"Local app {self.app_name} launched with PID: {self.process.pid}")
            return True
        except Exception as e:
            debug_log(f"Error launching local app: {e}")
            return False
    
    def _launch_github(self):
        """Launch GitHub application"""
        try:
            if not self.app_path:
                debug_log("No GitHub URL provided for app launch")
                return False

            # Download the script to a temp directory
            self.progress.emit("Downloading app from GitHub...")
            response = requests.get(self.app_path, timeout=30)
            response.raise_for_status()

            temp_dir = tempfile.mkdtemp(prefix=f"gh_{self.app_name.replace(' ', '_')}_")
            script_name = os.path.basename(self.app_path) or f"{self.app_name.replace(' ', '_')}.py"
            script_path = os.path.join(temp_dir, script_name)

            with open(script_path, 'wb') as f:
                f.write(response.content)

            env = os.environ.copy()
            if self.username:
                env["SAAS_USERNAME"] = self.username

            cmd_args = [sys.executable, script_path]
            if self.username:
                cmd_args.append(self.username)

            self.progress.emit("Launching downloaded app...")
            self.process = subprocess.Popen(cmd_args, env=env)
            debug_log(f"GitHub app {self.app_name} launched with PID: {self.process.pid}")
            return True
        except Exception as e:
            debug_log(f"Error launching GitHub app: {e}")
            return False
    
    def _launch_github_gui(self):
        """Launch GitHub application with GUI"""
        try:
            if not self.app_path:
                debug_log("No GitHub URL provided for GUI app launch")
                return False

            # Download script
            self.progress.emit("Downloading app (GUI) from GitHub...")
            response = requests.get(self.app_path, timeout=30)
            response.raise_for_status()

            temp_dir = tempfile.mkdtemp(prefix=f"ghgui_{self.app_name.replace(' ', '_')}_")
            script_name = os.path.basename(self.app_path) or f"{self.app_name.replace(' ', '_')}.py"
            script_path = os.path.join(temp_dir, script_name)
            with open(script_path, 'wb') as f:
                f.write(response.content)

            # Import as module and find main window class
            self.progress.emit("Importing downloaded GUI app...")
            with open(script_path, 'r', encoding='utf-8') as f:
                script_content = f.read()

            module_name = f"temp_{self.app_name.lower().replace(' ', '_')}"
            spec = importlib.util.spec_from_loader(module_name, loader=None)
            if spec is None:
                debug_log("Failed to create module spec for GUI app")
                return False
            module = importlib.util.module_from_spec(spec)

            original_env = {"SAAS_USERNAME": os.environ.get("SAAS_USERNAME", ""), "sys_argv": sys.argv.copy()}
            try:
                if self.username:
                    os.environ["SAAS_USERNAME"] = self.username
                    sys.argv = [sys.argv[0], self.username]
            except Exception:
                pass

            exec(script_content, module.__dict__)

            # Find a likely QWidget/QMainWindow class
            candidate_class = None
            possible_names = [
                'MainWindow', 'App', 'Application', 'MainApp', self.app_name.replace(' ', ''), 'OrderAutomationApp'
            ]
            for name in possible_names:
                if hasattr(module, name):
                    candidate_class = getattr(module, name)
                    break
            if candidate_class is None:
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and hasattr(attr, '__bases__') and 
                        any('QWidget' in str(base) or 'QMainWindow' in str(base) for base in attr.__bases__)):
                        candidate_class = attr
                        break

            if candidate_class is None:
                debug_log("No GUI class found in downloaded module")
                return False

            self.window = candidate_class()

            # Restore environment
            try:
                os.environ["SAAS_USERNAME"] = original_env.get("SAAS_USERNAME", "")
                sys.argv = original_env.get("sys_argv", sys.argv)
            except Exception:
                pass

            return True
        except Exception as e:
            debug_log(f"Error launching GitHub GUI app: {e}")
            return False


class FirebaseOperationWorker(QThread):
    """Worker for Firebase operations in background thread"""
    finished = Signal(bool, dict)
    progress = Signal(str)
    
    def __init__(self, operation: str, **kwargs):
        super().__init__()
        self.operation = operation
        self.kwargs = kwargs
    
    def run(self):
        try:
            self.progress.emit(f"Executing {self.operation}...")
            
            if self.operation == 'get_user_data':
                result = FirebaseClient.get_user_data(
                    self.kwargs['id_token'], 
                    self.kwargs['user_id']
                )
            elif self.operation == 'set_user_data':
                result = FirebaseClient.set_user_data(
                    self.kwargs['id_token'], 
                    self.kwargs['user_id'], 
                    self.kwargs['data']
                )
            elif self.operation == 'update_user_membership':
                result = FirebaseClient.update_user_membership(
                    self.kwargs['id_token'], 
                    self.kwargs['user_id'], 
                    self.kwargs['membership_data']
                )
            elif self.operation == 'get_comprehensive_referral_data':
                result = FirebaseClient.get_comprehensive_referral_data(
                    self.kwargs['id_token'], 
                    self.kwargs['user_id']
                )
            elif self.operation == 'sync_referral_data_on_login':
                result = FirebaseClient.sync_referral_data_on_login(
                    self.kwargs['id_token'], 
                    self.kwargs['user_id']
                )
            elif self.operation == 'validate_referral_code':
                result = FirebaseClient.validate_referral_code(
                    self.kwargs['id_token'], 
                    self.kwargs['referral_code']
                )
            elif self.operation == 'process_referral_during_registration':
                result = FirebaseClient.process_referral_during_registration(
                    self.kwargs['id_token'], 
                    self.kwargs['new_user_id'], 
                    self.kwargs['username'], 
                    self.kwargs['referral_code']
                )
            elif self.operation == 'create_referral_code_entry':
                result = FirebaseClient.create_referral_code_entry(
                    self.kwargs['id_token'], 
                    self.kwargs['user_id'], 
                    self.kwargs['username'], 
                    self.kwargs['referral_code']
                )
            else:
                result = {"error": f"Unknown operation: {self.operation}"}
            
            self.finished.emit(True, result)
            
        except Exception as e:
            debug_log(f"Exception in FirebaseOperationWorker: {e}")
            self.finished.emit(False, {"error": f"Exception in {self.operation}: {str(e)}"})


class FileDownloadWorker(QThread):
    """Worker for downloading files in background thread"""
    finished = Signal(bool, str, str)  # success, message, file_path
    progress = Signal(str)
    
    def __init__(self, url: str, filename: str = None, temp_dir: str = None):
        super().__init__()
        self.url = url
        self.filename = filename
        self.temp_dir = temp_dir or tempfile.gettempdir()
    
    def run(self):
        try:
            self.progress.emit("Downloading file...")
            
            response = requests.get(self.url, timeout=30)
            response.raise_for_status()
            
            if not self.filename:
                self.filename = os.path.basename(self.url) or "downloaded_file"
            
            file_path = os.path.join(self.temp_dir, self.filename)
            
            with open(file_path, 'wb') as f:
                f.write(response.content)
            
            self.finished.emit(True, f"File downloaded successfully", file_path)
            
        except Exception as e:
            debug_log(f"Exception in FileDownloadWorker: {e}")
            self.finished.emit(False, f"Download failed: {str(e)}", "")


class AppImportWorker(QThread):
    """Worker for importing and setting up applications in background thread"""
    finished = Signal(bool, str, object)  # success, message, app_instance
    progress = Signal(str)
    
    def __init__(self, app_name: str, file_path: str, username: str = ""):
        super().__init__()
        self.app_name = app_name
        self.file_path = file_path
        self.username = username
        self.app_instance = None
    
    def run(self):
        try:
            self.progress.emit(f"Reading {self.app_name}...")
            
            # Read the script content
            with open(self.file_path, 'r', encoding='utf-8') as f:
                script_content = f.read()
            
            self.progress.emit(f"Processing {self.app_name}...")
            
            # Replace username placeholder if present
            if self.username:
                script_content = script_content.replace("PLACEHOLDER_USERNAME", self.username)
            
            # Create a temporary module name
            module_name = f"temp_{self.app_name.lower().replace(' ', '_')}"
            
            self.progress.emit(f"Creating module for {self.app_name}...")
            
            # Create module from the script
            spec = importlib.util.spec_from_loader(module_name, loader=None)
            if spec is None:
                self.finished.emit(False, f"Could not create spec for {module_name}", None)
                return
            
            module = importlib.util.module_from_spec(spec)
            
            # Set up environment variables
            original_env = {}
            try:
                original_env['SAAS_USERNAME'] = os.environ.get('SAAS_USERNAME', '')
                original_env['sys_argv'] = sys.argv.copy()
                
                if self.username:
                    os.environ['SAAS_USERNAME'] = self.username
                    sys.argv = [sys.argv[0], self.username]
            except Exception as e:
                debug_log(f"Warning: Could not set environment variables: {e}")
            
            self.progress.emit(f"Executing {self.app_name}...")
            
            # Execute the script in the module namespace with timeout protection
            # This is the potentially blocking operation
            import signal
            
            def timeout_handler(signum, frame):
                raise TimeoutError("Script execution timed out")
            
            # Set up timeout (only works on Unix systems)
            if hasattr(signal, 'SIGALRM'):
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(30)  # 30 second timeout
            
            try:
                exec(script_content, module.__dict__)
            finally:
                # Cancel timeout
                if hasattr(signal, 'SIGALRM'):
                    signal.alarm(0)
            
            self.progress.emit(f"Finding main class for {self.app_name}...")
            
            # Find the main application class
            app_class = None
            possible_names = ['MainWindow', 'App', 'Application', 'MainApp', 
                            self.app_name.replace(' ', ''), 'OrderAutomationApp']
            
            for name in possible_names:
                if hasattr(module, name):
                    app_class = getattr(module, name)
                    break
            
            if not app_class:
                # Try to find any class that looks like a QWidget
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and 
                        hasattr(attr, '__bases__') and 
                        any('QWidget' in str(base) or 'QMainWindow' in str(base) for base in attr.__bases__)):
                        app_class = attr
                        break
            
            if not app_class:
                self.finished.emit(False, f"Could not find main application class in {self.app_name}", None)
                return
            
            self.progress.emit(f"Creating instance of {self.app_name}...")
            
            # Create the app instance
            self.app_instance = app_class()
            
            # Restore original environment
            try:
                if 'SAAS_USERNAME' in original_env:
                    os.environ['SAAS_USERNAME'] = original_env['SAAS_USERNAME']
                if 'sys_argv' in original_env:
                    sys.argv = original_env['sys_argv']
            except Exception as e:
                debug_log(f"Warning: Could not restore environment: {e}")
            
            self.finished.emit(True, f"{self.app_name} imported successfully", self.app_instance)
            
        except Exception as e:
            debug_log(f"Exception in AppImportWorker: {e}")
            self.finished.emit(False, f"Import failed: {str(e)}", None)


class CleanupWorker(QThread):
    """Worker for cleanup operations in background thread"""
    finished = Signal(bool, str)
    progress = Signal(str)
    
    def __init__(self, cleanup_type: str, **kwargs):
        super().__init__()
        self.cleanup_type = cleanup_type
        self.kwargs = kwargs
    
    def run(self):
        try:
            self.progress.emit(f"Performing {self.cleanup_type} cleanup...")
            
            if self.cleanup_type == 'temp_files':
                self._cleanup_temp_files()
            elif self.cleanup_type == 'processes':
                self._cleanup_processes()
            elif self.cleanup_type == 'cache':
                self._cleanup_cache()
            else:
                self.finished.emit(False, f"Unknown cleanup type: {self.cleanup_type}")
                return
            
            self.finished.emit(True, f"{self.cleanup_type} cleanup completed")
            
        except Exception as e:
            debug_log(f"Exception in CleanupWorker: {e}")
            self.finished.emit(False, f"Cleanup failed: {str(e)}")
    
    def _cleanup_temp_files(self):
        """Clean up temporary files"""
        temp_dirs = self.kwargs.get('temp_dirs', [])
        for temp_dir in temp_dirs:
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    debug_log(f"Cleaned up temp directory: {temp_dir}")
            except Exception as e:
                debug_log(f"Error cleaning temp dir {temp_dir}: {e}")
    
    def _cleanup_processes(self):
        """Clean up processes"""
        processes = self.kwargs.get('processes', [])
        for process in processes:
            try:
                if hasattr(process, 'terminate'):
                    process.terminate()
                    debug_log(f"Terminated process: {process}")
            except Exception as e:
                debug_log(f"Error terminating process {process}: {e}")
    
    def _cleanup_cache(self):
        """Clean up cache files"""
        cache_paths = self.kwargs.get('cache_paths', [])
        for cache_path in cache_paths:
            try:
                if os.path.exists(cache_path):
                    os.unlink(cache_path)
                    debug_log(f"Cleaned up cache file: {cache_path}")
            except Exception as e:
                debug_log(f"Error cleaning cache {cache_path}: {e}")


class ProfileUpdateWorker(QThread):
    """Worker for updating user profiles in background thread"""
    finished = Signal(bool, dict)
    progress = Signal(str)
    
    def __init__(self, id_token: str, user_id: str, profile_data: dict):
        super().__init__()
        self.id_token = id_token
        self.user_id = user_id
        self.profile_data = profile_data
    
    def run(self):
        try:
            self.progress.emit("Updating user profile...")
            
            result = FirebaseClient.set_user_data(self.id_token, self.user_id, self.profile_data)
            
            if "error" in result:
                self.finished.emit(False, result)
            else:
                self.finished.emit(True, result)
                
        except Exception as e:
            debug_log(f"Exception in ProfileUpdateWorker: {e}")
            self.finished.emit(False, {"error": f"Exception updating profile: {str(e)}"})


class ReferralSyncWorker(QThread):
    """Worker for referral synchronization in background thread"""
    finished = Signal(bool, dict)
    progress = Signal(str)
    
    def __init__(self, id_token: str, user_id: str):
        super().__init__()
        self.id_token = id_token
        self.user_id = user_id
    
    def run(self):
        try:
            self.progress.emit("Synchronizing referral data...")
            
            result = FirebaseClient.sync_referral_data_on_login(self.id_token, self.user_id)
            
            if "error" in result:
                self.finished.emit(False, result)
            else:
                self.finished.emit(True, result)
                
        except Exception as e:
            debug_log(f"Exception in ReferralSyncWorker: {e}")
            self.finished.emit(False, {"error": f"Exception syncing referrals: {str(e)}"})


class MembershipUpdateWorker(QThread):
    """Worker for membership updates in background thread"""
    finished = Signal(bool, dict)
    progress = Signal(str)
    
    def __init__(self, id_token: str, user_id: str, membership_data: dict):
        super().__init__()
        self.id_token = id_token
        self.user_id = user_id
        self.membership_data = membership_data
    
    def run(self):
        try:
            self.progress.emit("Updating membership...")
            
            result = FirebaseClient.update_user_membership(
                self.id_token, 
                self.user_id, 
                self.membership_data
            )
            
            if "error" in result:
                self.finished.emit(False, result)
            else:
                self.finished.emit(True, result)
                
        except Exception as e:
            debug_log(f"Exception in MembershipUpdateWorker: {e}")
            self.finished.emit(False, {"error": f"Exception updating membership: {str(e)}"})


class FreeTrialActivationWorker(QThread):
    """Worker for activating free trial membership"""
    finished = Signal(bool, dict)  # success, result
    progress = Signal(str)
    
    def __init__(self, id_token: str, local_id: str, membership_data: dict):
        super().__init__()
        self.id_token = id_token
        self.local_id = local_id
        self.membership_data = membership_data
    
    def run(self):
        try:
            self.progress.emit("Activating free trial...")
            result = FirebaseClient.update_user_membership(
                self.id_token,
                self.local_id,
                self.membership_data
            )
            if "error" in result:
                self.finished.emit(False, result)
            else:
                self.progress.emit("Free trial activated successfully!")
                self.finished.emit(True, result)
        except Exception as e:
            debug_log(f"Exception in FreeTrialActivationWorker: {e}")
            import traceback
            traceback.print_exc()
            self.finished.emit(False, {"error": f"Exception: {str(e)}"})


class RegistrationCompletionWorker(QThread):
    """Worker for completing user registration"""
    finished = Signal(bool, dict)  # success, result
    progress = Signal(str)
    
    def __init__(self, id_token: str, local_id: str, user_data: dict, referral_code: str = ""):
        super().__init__()
        self.id_token = id_token
        self.local_id = local_id
        self.user_data = user_data
        self.referral_code = referral_code
    
    def run(self):
        try:
            self.progress.emit("Processing referral code...")
            referrer_id = ""
            if self.referral_code:
                referral_result = FirebaseClient.process_referral_during_registration(
                    self.id_token, self.local_id, 
                    self.user_data.get("username", ""), 
                    self.referral_code
                )
                
                if "error" in referral_result:
                    self.finished.emit(False, {"error": referral_result["error"]})
                    return
                
                if "success" in referral_result:
                    referrer_id = referral_result.get("referrer_user_id", "")
                    self.user_data["referred_by"] = referrer_id
            
            self.progress.emit("Saving user profile...")
            result = FirebaseClient.set_user_data(self.id_token, self.local_id, self.user_data)
            if "error" in result:
                self.finished.emit(False, result)
                return
            
            self.progress.emit("Creating referral code entry...")
            referral_code = self.user_data.get("referral_code", "")
            username = self.user_data.get("username", "")
            referral_result = FirebaseClient.create_referral_code_entry(
                self.id_token, self.local_id, username, referral_code
            )
            
            if "error" in referral_result:
                debug_log(f"Referral code creation failed: {referral_result.get('error')}")
            
            self.finished.emit(True, {
                "success": True,
                "referrer_id": referrer_id,
                "referral_code": referral_code
            })
            
        except Exception as e:
            debug_log(f"Exception in RegistrationCompletionWorker: {e}")
            import traceback
            traceback.print_exc()
            self.finished.emit(False, {"error": f"Exception: {str(e)}"})


class TransactionRecordingWorker(QThread):
    """Worker for recording membership transactions"""
    finished = Signal(bool, dict)  # success, result
    progress = Signal(str)
    
    def __init__(self, id_token: str, local_id: str, transaction_data: dict, transaction_id: str, whatsapp: str):
        super().__init__()
        self.id_token = id_token
        self.local_id = local_id
        self.transaction_data = transaction_data
        self.transaction_id = transaction_id
        self.whatsapp = whatsapp
    
    def run(self):
        try:
            self.progress.emit("Recording transaction...")
            result = FirebaseClient.set_document(
                self.id_token, 
                "membership_transactions", 
                self.transaction_id, 
                self.transaction_data
            )
            
            if "error" in result:
                self.finished.emit(False, result)
                return
            
            self.progress.emit("Updating user profile...")
            update_result = FirebaseClient.set_user_data(
                self.id_token, 
                self.local_id, 
                {"whatsapp": self.whatsapp}
            )
            
            if "error" in update_result:
                debug_log(f"Failed to update WhatsApp: {update_result.get('error', 'Unknown error')}")
            
            self.finished.emit(True, {
                "success": True,
                "transaction_id": self.transaction_id,
                "transaction_data": self.transaction_data
            })
            
        except Exception as e:
            debug_log(f"Exception in TransactionRecordingWorker: {e}")
            import traceback
            traceback.print_exc()
            self.finished.emit(False, {"error": f"Exception: {str(e)}"})


class SkipTrialWorker(QThread):
    """Worker for marking free trial as used when user skips"""
    finished = Signal(bool, dict)  # success, result
    
    def __init__(self, id_token: str, local_id: str):
        super().__init__()
        self.id_token = id_token
        self.local_id = local_id
    
    def run(self):
        try:
            result = FirebaseClient.set_user_data(
                self.id_token,
                self.local_id,
                {"free_trial_used": True}
            )
            if "error" in result:
                self.finished.emit(False, result)
            else:
                self.finished.emit(True, {"success": True})
        except Exception as e:
            debug_log(f"Exception in SkipTrialWorker: {e}")
            self.finished.emit(False, {"error": f"Exception: {str(e)}"})


class RewardsDataWorker(QThread):
    """Worker to load referral data for rewards calculation on dashboard"""
    finished = Signal(bool, dict)
    progress = Signal(str)
    
    def __init__(self, id_token: str, user_id: str):
        super().__init__()
        self.id_token = id_token
        self.user_id = user_id
    
    def run(self):
        try:
            self.progress.emit("Loading referral data...")
            referral_data = FirebaseClient.get_comprehensive_referral_data(self.id_token, self.user_id)
            if "error" in referral_data:
                self.finished.emit(False, referral_data)
                return
            
            self.progress.emit("Loading rewards data...")
            rewards_data = FirebaseClient.get_user_rewards(self.id_token, self.user_id)
            if "error" in rewards_data:
                self.finished.emit(False, rewards_data)
                return
            
            self.finished.emit(True, {
                "success": True,
                "referral_data": referral_data.get("data", {}),
                "rewards_data": rewards_data.get("data", {})
            })
            
        except Exception as e:
            debug_log(f"Exception in RewardsDataWorker: {e}")
            self.finished.emit(False, {"error": f"Exception loading rewards data: {str(e)}"})