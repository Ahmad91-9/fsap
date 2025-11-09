import sys
import os
import time
import atexit
import ctypes
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel, QMessageBox, QStackedWidget, QHBoxLayout
from PySide6.QtCore import QThread, Signal, QTimer, Qt, QSize
from PySide6.QtGui import QColor, QPalette, QIcon

from config import GITHUB_APPS, _TEMP_SIGNUPS, CACHE_PATH
from firebase_client import FirebaseClient
from workers import SignupWorker, VerifyWorker, LoginWorker, DeleteTempWorker, ReferralSyncWorker
from thread_workers import (
    AppLaunchWorker, FirebaseOperationWorker, FileDownloadWorker, 
    CleanupWorker, ProfileUpdateWorker, 
    ReferralSyncWorker as ThreadReferralSyncWorker, MembershipUpdateWorker
)
from login_page import LoginPage
from register_page import RegisterPage
from membership_page import MembershipPage
from dashboard_page import DashboardPage
from free_trial_page import FreeTrialPage
from utils import debug_log
from cleanup_utils import cleanup_manager, register_temp_dir, register_temp_file, register_process, cleanup_on_exit
from app_config import get_local_app_path, get_github_app_url, list_all_apps
from improved_launcher import ImprovedLauncherManager

print("\n[main_window.py] ===== MODULE LOADED =====")
print(f"[main_window.py] Module: {__name__}")
print(f"[main_window.py] File: {__file__}")

# Global launcher manager instance
app_launcher_manager = None
print(f"[main_window.py] Global app_launcher_manager set to: {app_launcher_manager}")
print("[main_window.py] ===== MODULE INIT COMPLETE =====\n")

def launch_app(app_name: str, username: str = "", show_loader: bool = True):
    """Launch an app using the improved launcher"""
    global app_launcher_manager
    print(f"[launch_app] Checking global manager: {app_launcher_manager}")
    if app_launcher_manager:
        # Note: improved launcher doesn't use show_loader parameter (uses popup instead)
        return app_launcher_manager.launch_app(app_name, username)
    print(f"[launch_app] ERROR: Manager is None!")
    return False
def get_app_version() -> str:
    """Return the current version of the app."""
    return "1.0.0"

def stop_app(app_name: str):
    """Stop a running app"""
    global app_launcher_manager
    if app_launcher_manager:
        app_launcher_manager.stop_app(app_name)

def stop_all_apps():
    """Stop all running apps"""
    global app_launcher_manager
    if app_launcher_manager:
        app_launcher_manager.stop_all()

def close_all_apps():
    """Close all running apps"""
    global app_launcher_manager
    if app_launcher_manager:
        app_launcher_manager.stop_all()

def initialize_app_launcher_manager(parent, local_apps, github_apps, gif_path=None):
    """Initialize the global launcher manager"""
    global app_launcher_manager
    print(f"[MainWindow] Initializing launcher manager...")
    print(f"[MainWindow] Local apps count: {len(local_apps)}")
    print(f"[MainWindow] GitHub apps count: {len(github_apps)}")
    
    app_launcher_manager = ImprovedLauncherManager(
        parent=parent,
        local_apps=local_apps,
        github_apps=github_apps
    )
    
    print(f"[MainWindow] Launcher manager initialized: {app_launcher_manager}")
    print(f"[MainWindow] Manager has {len(app_launcher_manager.local_apps)} local apps")
    print(f"[MainWindow] Manager has {len(app_launcher_manager.github_apps)} github apps")

class MainWindow(QMainWindow):
    def __init__(self):
        print("\n" + "="*80)
        print("[MainWindow.__init__] STARTING MainWindow initialization")
        print("="*80 + "\n")
        super().__init__()
        
        # Set window icon BEFORE setting title
        icon_path = os.path.join(Path(__file__).parent.parent, 'autonix.ico')
        if os.path.exists(icon_path):
            # Set icon on the window
            self.setWindowIcon(QIcon(icon_path))
            # Also set it on the QApplication instance
            app = QApplication.instance()
            if app:
                app.setWindowIcon(QIcon(icon_path))
        
        self.setWindowTitle("Autonix")
        
        # Make the app full screen and non-resizable
        self.showMaximized()
        self.setFixedSize(self.size())  # Will be set after maximized
        
        # Use a timer to set fixed size after the window is shown
        QTimer.singleShot(100, self.set_fixed_fullscreen)

        # Apply dark theme
        self.apply_dark_theme()

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Stack for pages
        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack)

        # Pages - pass self as main_window reference
        self.login_page = LoginPage()
        self.register_page = RegisterPage(main_window=self)  # Pass self here
        self.membership_page = MembershipPage()
        self.free_trial_page = FreeTrialPage()
        # Dashboard will receive launcher manager after initialization
        self.dashboard_page = None

        self.stack.addWidget(self.login_page)      # index 0
        self.stack.addWidget(self.register_page)   # index 1
        self.stack.addWidget(self.membership_page) # index 2
        self.stack.addWidget(self.free_trial_page) # index 3
        # Dashboard will be added after launcher manager is initialized (index 4 will be added later)

        # Wire signals (dashboard signals will be connected after initialization)
        self.login_page.request_login.connect(self.start_login)
        self.login_page.go_register.connect(lambda: self.stack.setCurrentWidget(self.register_page))
        self.register_page.start_signup.connect(self.start_signup)
        self.register_page.verify_email.connect(self.start_verify)
        self.register_page.cancel_signup.connect(self.start_cancel_signup)
        self.register_page.go_login.connect(lambda: self.stack.setCurrentWidget(self.login_page))
        self.register_page.registration_complete.connect(self.go_to_free_trial)  # Navigate to free trial after registration
        self.membership_page.logout.connect(self.handle_logout)
        self.membership_page.go_back.connect(self.on_membership_back)
        # Connect free trial page signals
        self.free_trial_page.trial_activated.connect(self.on_trial_activated)
        self.free_trial_page.skip_trial.connect(self.go_to_membership_after_skip)
        self.free_trial_page.go_back.connect(lambda: self.stack.setCurrentWidget(self.login_page))

        # Keep current user session
        self.current_user = None  # dict with idToken, localId, profile...
        
        # Sub-applications management
        self.sub_apps = []  # Track launched sub-applications
        self.app_launching = False  # Track if an app is currently launching
        self.loading_screen = None  # Loading screen for app launches
        
        # App management removed - missing app_manager module
        
        # Thread workers for background operations
        self.active_workers = []  # Track active workers
        self.app_launch_worker = None
        self.app_import_worker = None
        self.firebase_worker = None
        self.cleanup_worker = None

        # Ensure cleanup on exit
        atexit.register(self.cleanup_temp_signups)
        atexit.register(self.cleanup_on_exit)
        
        # Set up GUI responsiveness timer
        self.responsiveness_timer = QTimer()
        self.responsiveness_timer.timeout.connect(self._keep_gui_responsive)
        self.responsiveness_timer.start(100)  # Process events every 100ms

        # Initialize app launcher manager
        print("[MainWindow.__init__] About to initialize launcher manager...")
        try:
            from config import get_local_apps, get_github_apps
            print("[MainWindow.__init__] Config imported successfully")
            gif_path = "Animation - 1749282768380.gif"
            local_apps_list = get_local_apps()
            github_apps_list = get_github_apps()
            print(f"[MainWindow.__init__] Got {len(local_apps_list)} local apps, {len(github_apps_list)} github apps")
            
            initialize_app_launcher_manager(
                parent=self,
                local_apps=local_apps_list,
                github_apps=github_apps_list,
                gif_path=gif_path
            )
            print("[MainWindow.__init__] Launcher manager initialized successfully")
            
            # NOW create dashboard with the initialized launcher manager
            global app_launcher_manager
            self.dashboard_page = DashboardPage(launcher_manager=app_launcher_manager)
            self.stack.addWidget(self.dashboard_page)  # index 4
            
            # Connect dashboard signals
            self.dashboard_page.logout.connect(self.handle_logout)
            self.dashboard_page.membership_expired.connect(self.handle_membership_expired)
            print("[MainWindow.__init__] Dashboard initialized with launcher manager")
        except Exception as e:
            print(f"[MainWindow.__init__] ERROR initializing launcher manager: {e}")
            import traceback
            traceback.print_exc()

        # Start at login
        self.stack.setCurrentWidget(self.login_page)

    def apply_dark_theme(self):
        """Apply a dark theme to the application."""
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(45, 45, 48))
        palette.setColor(QPalette.WindowText, QColor(255, 255, 255))
        palette.setColor(QPalette.Base, QColor(62, 62, 66))
        palette.setColor(QPalette.AlternateBase, QColor(45, 45, 48))
        palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 255))
        palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
        palette.setColor(QPalette.Text, QColor(255, 255, 255))
        palette.setColor(QPalette.Button, QColor(62, 62, 66))
        palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
        palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
        palette.setColor(QPalette.Link, QColor(0, 122, 204))
        palette.setColor(QPalette.Highlight, QColor(0, 122, 204))
        palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
        self.setPalette(palette)

        # Set application stylesheet
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2D2D30;
            }
            QStackedWidget {
                background-color: #2D2D30;
            }
            QToolTip {
                background-color: #3E3E42;
                color: white;
                border: 1px solid #555;
                padding: 5px;
            }
        """)

    def set_fixed_fullscreen(self):
        """Set the window to be fixed in fullscreen mode."""
        from PySide6.QtCore import Qt
        # Get current screen size and set fixed size
        screen = self.screen()
        if screen:
            screen_size = screen.size()
            self.setFixedSize(screen_size)
        self.setWindowState(self.windowState() | Qt.WindowMaximized)

    # ---------------- Launcher: download, run, auto-delete ----------------
    def download_and_run_app(self, appname: str, raw_url: str, username: str):
        """
        Downloads and runs a GitHub app using the universal app launcher.
        """
        try:
            # Set launching state
            self.app_launching = True
            self.setEnabled(False)  # Disable main app UI
            
            # Show loading screen
            self.show_loading_screen(appname)
            
            # Use improved app launcher
            # Note: launch_app now takes (app_name, username) format
            success = launch_app(appname, username)
            
            if success:
                debug_log(f"Started improved launcher for {appname}")
                # The launcher manager handles signals internally
                # Re-enable UI after successful launch initiation
                self._re_enable_ui()
            else:
                self._re_enable_ui()
                QMessageBox.critical(self, "Launch Error", f"Failed to create launcher for {appname}")
                
        except Exception as e:
            self._re_enable_ui()
            debug_log(f"Error in download_and_run_app: {e}")
            QMessageBox.critical(self, "Launch Error", f"Failed to launch {appname}: {str(e)}")

    def _show_launch_error(self, appname: str, message: str):
        QMessageBox.critical(self, f"{appname} error", message)
    
    def _re_enable_ui(self):
        """Re-enable the main app UI after app launch."""
        self.app_launching = False
        self.setEnabled(True)
        # Close loading screen if it exists
        if self.loading_screen:
            self.loading_screen.close_loading_screen()
            self.loading_screen = None
    
    def _on_app_launch_finished(self, success: bool, message: str, window_or_process):
        """Handle app launch completion"""
        self.hide_loading_screen()
        self._re_enable_ui()
        
        if success and window_or_process:
            # Get the app name from the launcher
            app_name = getattr(self.app_launcher, 'app_name', 'Unknown App')
            
            # App manager functionality removed - missing app_manager module
            # Add to sub-apps list for tracking
            self.sub_apps.append(window_or_process)
            
            # Connect close event if it's a window
            if hasattr(window_or_process, 'destroyed'):
                window_or_process.destroyed.connect(lambda: self._remove_sub_app(window_or_process))
            
            # Ensure the launched app appears above the main window
            self._bring_app_to_front(window_or_process)
        else:
            QMessageBox.critical(self, "Launch Error", message)
            # Reset launching state since launch failed
            # app_manager.finish_launch() - removed due to missing module
        
        # Remove worker from active workers
        if self.app_launch_worker in self.active_workers:
            self.active_workers.remove(self.app_launch_worker)
        self.app_launch_worker = None
    
    def _on_app_launch_progress(self, message: str):
        """Handle app launch progress updates"""
        debug_log(f"App launch progress: {message}")
        # Force GUI update to keep it responsive
        QApplication.processEvents()
    
    def _on_app_launch_blocked(self, app_name: str, reason: str):
        """Handle when app launch is blocked"""
        self.hide_loading_screen()
        self._re_enable_ui()
        QMessageBox.warning(self, "App Launch Blocked", f"{app_name}: {reason}")
        # Reset launching state since launch was blocked
        # app_manager.finish_launch() - removed due to missing module
    
    def _on_app_closed(self, app_name: str):
        """Handle when an app is closed"""
        debug_log(f"App {app_name} was closed")
        # Remove from sub_apps list if it exists
        self.sub_apps = [app for app in self.sub_apps if not (hasattr(app, 'pid') and app.poll() is not None)]
    
    def _bring_app_to_front(self, window_or_process):
        """Bring the launched app to the front and above the main window"""
        try:
            if hasattr(window_or_process, 'raise_'):
                # It's a Qt widget
                window_or_process.raise_()
                window_or_process.activateWindow()
                window_or_process.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
                window_or_process.show()
                debug_log("Brought Qt widget to front")
            elif hasattr(window_or_process, 'pid'):
                # It's a subprocess - try to bring its window to front
                try:
                    # psutil import removed - missing dependency
                    # import psutil
                    # process = psutil.Process(window_or_process.pid)
                    # On Windows, we can try to bring the window to front
                    if os.name == 'nt':
                        import ctypes
                        from ctypes import wintypes
                        
                        # Get the main window handle for the process
                        def enum_windows_callback(hwnd, windows):
                            if ctypes.windll.user32.IsWindowVisible(hwnd):
                                _, pid = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None)
                                if pid == window_or_process.pid:
                                    windows.append(hwnd)
                            return True
                        
                        windows = []
                        ctypes.windll.user32.EnumWindows(enum_windows_callback, windows)
                        
                        if windows:
                            # Bring the first visible window to front
                            hwnd = windows[0]
                            ctypes.windll.user32.SetForegroundWindow(hwnd)
                            ctypes.windll.user32.BringWindowToTop(hwnd)
                            debug_log(f"Brought subprocess window to front (PID: {window_or_process.pid})")
                except Exception as e:
                    debug_log(f"Could not bring subprocess to front: {e}")
        except Exception as e:
            debug_log(f"Error bringing app to front: {e}")
    
    def show_loading_screen(self, app_name: str):
        """Show loading screen for app launch"""
        if self.loading_screen:
            self.loading_screen.close_loading_screen()
        
        # AppLoadingScreen removed - missing app_loading_screen module
        # self.loading_screen = AppLoadingScreen(app_name)
        # self.loading_screen.show()
        QApplication.processEvents()  # Force UI update
    
    def hide_loading_screen(self):
        """Hide loading screen"""
        if self.loading_screen:
            self.loading_screen.close_loading_screen()
            self.loading_screen = None
    
    def launch_watermark_remover(self, username: str):
        """Launch the watermark remover app as a separate window."""
        app_name = "PDF and Word Watermark Remover"
        
        # App manager check removed - missing app_manager module
        
        # Show loading screen
        self.show_loading_screen(app_name)
        
        # Resolve path to PDF_word Watermarkremover
        from pathlib import Path
        
        # In PyInstaller, use the executable directory
        if getattr(sys, 'frozen', False):
            # Running as PyInstaller executable
            base_dir = Path(sys.executable).parent
        else:
            # Running as script
            current_file = Path(__file__).resolve()
            base_dir = current_file.parent.parent.parent
        
        candidate = base_dir / 'PDF_word Watermarkremover' / 'prod.py'
        
        if not candidate.exists():
            self.hide_loading_screen()
            # app_manager.finish_launch() - removed due to missing module
            QMessageBox.critical(self, "File Not Found", f"Could not locate PDF_word Watermarkremover/prod.py at: {candidate}")
            return
        
        # SubprocessAppLauncher removed - missing subprocess_app_launcher module
        QMessageBox.warning(self, "App Launch", "App launching functionality has been disabled due to missing modules.")
    
    def launch_pdf_ocr_urdu(self, username: str):
        """Launch the PDF OCR Urdu app as a separate window."""
        app_name = "PDFOCR For URDU"
        
        # App manager check removed - missing app_manager module
        
        # Show loading screen
        self.show_loading_screen(app_name)
        
        # Resolve path to PDF OCR app
        from pathlib import Path
        
        # In PyInstaller, use the executable directory
        if getattr(sys, 'frozen', False):
            # Running as PyInstaller executable
            base_dir = Path(sys.executable).parent
        else:
            # Running as script
            current_file = Path(__file__).resolve()
            base_dir = current_file.parent.parent.parent
        
        candidate = base_dir / 'PDFOCR' / 'pdf_urdu_ocr_app.py'
        
        if not candidate.exists():
            self.hide_loading_screen()
            # app_manager.finish_launch() - removed due to missing module
            QMessageBox.critical(self, "File Not Found", f"Could not locate PDFOCR/pdf_urdu_ocr_app.py at: {candidate}")
            return
        
        # SubprocessAppLauncher removed - missing subprocess_app_launcher module
        QMessageBox.warning(self, "App Launch", "App launching functionality has been disabled due to missing modules.")
    
    def launch_youtube_downloader(self, username: str):
        """Launch the YouTube Downloader app as a separate window."""
        app_name = "YouTube Downloader Professional"
        
        # App manager check removed - missing app_manager module
        
        # Show loading screen
        self.show_loading_screen(app_name)
        
        # Resolve path to YouTube downloader
        from pathlib import Path
        
        # In PyInstaller, use the executable directory
        if getattr(sys, 'frozen', False):
            # Running as PyInstaller executable
            base_dir = Path(sys.executable).parent
        else:
            # Running as script
            current_file = Path(__file__).resolve()
            base_dir = current_file.parent.parent.parent
        
        candidate = base_dir / 'youtube_downloader_gui_patched_fixed_corrected.py'
        
        if not candidate.exists():
            self.hide_loading_screen()
            # app_manager.finish_launch() - removed due to missing module
            QMessageBox.critical(self, "File Not Found", f"Could not locate YouTube downloader at: {candidate}")
            return
        
        # SubprocessAppLauncher removed - missing subprocess_app_launcher module
        QMessageBox.warning(self, "App Launch", "App launching functionality has been disabled due to missing modules.")
    
    def launch_github_app_native(self, app_name: str, raw_url: str, username: str):
        """Launch a GitHub app natively by downloading and importing it."""
        # App manager check removed - missing app_manager module
        
        # Show loading screen
        self.show_loading_screen(app_name)
        
        # DirectAppLauncher removed - missing subprocess_app_launcher module
        QMessageBox.warning(self, "App Launch", "App launching functionality has been disabled due to missing modules.")
    
    def _remove_sub_app(self, app):
        """Remove a sub-app from the tracking list."""
        if app in self.sub_apps:
            self.sub_apps.remove(app)
    
    def _on_app_launch_finished(self, success: bool, message: str, process_or_window):
        """Handle app launch completion"""
        self.hide_loading_screen()
        
        if success and process_or_window:
            # Add to sub-apps list for tracking
            self.sub_apps.append(process_or_window)
            
            # If it's a process, we can track it
            if hasattr(process_or_window, 'pid'):
                debug_log(f"App launched as subprocess with PID: {process_or_window.pid}")
            
            debug_log(f"App launched successfully: {message}")
        else:
            QMessageBox.critical(self, "Launch Error", message)
        
        # Remove worker from active workers
        if self.app_launcher in self.active_workers:
            self.active_workers.remove(self.app_launcher)
        self.app_launcher = None
    
    def _on_app_launch_progress(self, message: str):
        """Handle app launch progress updates"""
        debug_log(f"App launch progress: {message}")
        # Force GUI update to keep it responsive
        QApplication.processEvents()
    
    def _keep_gui_responsive(self):
        """Keep GUI responsive by processing events periodically"""
        try:
            # Process all pending events
            QApplication.processEvents()
        except Exception as e:
            debug_log(f"Error in responsiveness timer: {e}")
    
    def _on_universal_app_finished(self, result):
        """Handle universal app launcher finished"""
        self.hide_loading_screen()
        self._re_enable_ui()
        
        if result.success:
            debug_log(f"Universal app launched successfully: {result.message}")
            # Add to sub-apps list for tracking
            if result.app_instance or result.process:
                self.sub_apps.append(result.app_instance or result.process)
        else:
            QMessageBox.critical(self, "Launch Error", result.message)
    
    def _on_universal_app_error(self, error: str):
        """Handle universal app launcher error"""
        self.hide_loading_screen()
        self._re_enable_ui()
        QMessageBox.critical(self, "Launch Error", error)
    
    def _on_universal_app_progress(self, message: str):
        """Handle universal app launcher progress"""
        debug_log(f"Universal app progress: {message}")
        QApplication.processEvents()
    
    
    def close_all_sub_apps(self):
        """Close all launched sub-applications immediately."""
        print(f"Closing {len(self.sub_apps)} sub-applications...")
        
        # Use universal app launcher manager
        stop_all_apps()
        
        # Also close any remaining apps in sub_apps list
        for app in self.sub_apps[:]:  # Use slice to avoid modification during iteration
            try:
                if hasattr(app, 'close'):
                    print(f"Closing app: {type(app).__name__}")
                    app.close()
                elif hasattr(app, 'terminate'):
                    print(f"Terminating app: {type(app).__name__}")
                    app.terminate()
                elif hasattr(app, 'kill'):
                    print(f"Killing app: {type(app).__name__}")
                    app.kill()
                else:
                    print(f"Unknown app type: {type(app).__name__}")
            except Exception as e:
                print(f"Error closing sub-app {type(app).__name__}: {e}")
        
        # Force clear the list and wait a moment for processes to close
        self.sub_apps.clear()
        import time
        time.sleep(0.5)  # Give processes a moment to close
        print("All sub-applications closed.")

    # ---------------- Signup flow ----------------
    def start_signup(self, email: str, password: str):
        self.signup_worker = SignupWorker(email, password)
        self.signup_worker.progress.connect(lambda s: print("[SIGNUP]", s))
        self.signup_worker.finished.connect(self.on_signup_finished)
        self.signup_worker.start()

    def on_signup_finished(self, success: bool, payload: dict):
        # forward to register page so it can update UI
        self.register_page.handle_signup_result(success, payload)

    def start_verify(self, id_token: str, local_id: str):
        self.verify_worker = VerifyWorker(id_token, local_id)
        self.verify_worker.finished.connect(self.on_verify_finished)
        self.verify_worker.start()

    def on_verify_finished(self, ok: bool, msg: str):
        self.register_page.handle_verify_result(ok, msg)

    def start_cancel_signup(self, id_token: str, local_id: str):
        # delete temp signup (verification doc + account)
        self.del_worker = DeleteTempWorker(id_token, local_id)
        self.del_worker.finished.connect(lambda ok, info: QMessageBox.information(self, "Canceled", "Temporary signup deleted."))
        self.del_worker.start()

    # ---------------- Login flow ----------------
    def start_login(self, email: str, password: str):
        self.login_worker = LoginWorker(email, password)
        self.login_worker.finished.connect(self.on_login_finished)
        self.login_worker.start()

    
    def on_login_finished(self, ok: bool, payload: dict):
        """
        Handler called when LoginWorker finishes.

        Behavior:
        - If login failed: hide loading overlay and show error.
        - If login succeeded: hide loading overlay and navigate based on:
          1. Free trial status (if not used, show free trial page)
          2. Membership status (if active, show dashboard; else show membership page)
        """
        if not ok:
            # Ensure loading overlay is hidden and re-enable the form
            try:
                self.login_page.login_completed()
            except Exception:
                pass

            err_msg = payload.get("error", {}).get("message") if isinstance(payload, dict) else None
            if not err_msg:
                err_msg = str(payload)
            QMessageBox.critical(self, "Login failed", f"{err_msg}")
            return

        # Successful login - store user data and navigate directly
        user = payload
        self.current_user = user

        # Hide loading overlay and re-enable the login form
        try:
            self.login_page.login_completed()
        except Exception:
            pass

        # Check free trial status first
        free_trial_used = user.get("free_trial_used", False)
        
        # If free trial not used, navigate to free trial page
        if not free_trial_used:
            debug_log(f"User {user.get('email', 'unknown')} hasn't used free trial, navigating to free trial page")
            self.go_to_free_trial(user.get("idToken"), user.get("localId"))
            return
        
        # Navigate based on membership status
        from utils import is_membership_expired
        membership = user.get("membership", False)
        membership_expires = user.get("membership_expires", "")
        
        # If membership is expired, update the user data to reflect inactive status
        if membership and is_membership_expired(membership, membership_expires):
            debug_log(f"Membership expired for user {user.get('email', 'unknown')}, updating status to inactive")
            # Update the current user data to reflect expired status
            user["membership"] = False
            self.current_user = user  # Update the stored user data
            # Update the database to reflect expired status
            self.update_membership_status_in_database(user.get("idToken"), user.get("localId"), False)
        
        if membership and not is_membership_expired(membership, membership_expires):
            self.proceed_to_dashboard(user.get("idToken"), user.get("localId"))
        else:
            self.go_to_membership(user.get("idToken"), user.get("localId"))

    def on_referral_sync_finished(self, success: bool, result: dict, user: dict):
        """
        Called on the main thread when ReferralSyncWorker finishes.
        Hides the login overlay and proceeds to the appropriate page.
        """
        try:
            # Hide login loading overlay and re-enable the login form
            try:
                self.login_page.login_completed()
            except Exception:
                pass

            if not success:
                debug_log(f"Referral sync failed for user {user.get('localId')}: {result}")
            else:
                # Optionally merge returned results into current_user
                try:
                    if isinstance(result, dict) and result.get("results"):
                        self.current_user.update(result.get("results"))
                except Exception:
                    pass

            # Continue navigation after sync
            # Check if membership has expired
            from utils import is_membership_expired
            membership = user.get("membership", False)
            membership_expires = user.get("membership_expires", "")
            
            # If membership is expired, update the user data to reflect inactive status
            if membership and is_membership_expired(membership, membership_expires):
                debug_log(f"Membership expired for user {user.get('email', 'unknown')}, updating status to inactive")
                # Update the current user data to reflect expired status
                user["membership"] = False
                self.current_user = user  # Update the stored user data
                # Update the database to reflect expired status
                self.update_membership_status_in_database(user.get("idToken"), user.get("localId"), False)
            
            if membership and not is_membership_expired(membership, membership_expires):
                self.proceed_to_dashboard(user.get("idToken"), user.get("localId"))
            else:
                self.go_to_membership(user.get("idToken"), user.get("localId"))
        except Exception as e:
            debug_log(f"Exception in on_referral_sync_finished: {e}")
            # As a fallback, attempt to navigate
            try:
                from utils import is_membership_expired
                membership = user.get("membership", False)
                membership_expires = user.get("membership_expires", "")
                
                # If membership is expired, update the user data to reflect inactive status
                if membership and is_membership_expired(membership, membership_expires):
                    debug_log(f"Membership expired for user {user.get('email', 'unknown')}, updating status to inactive")
                    # Update the current user data to reflect expired status
                    user["membership"] = False
                    self.current_user = user  # Update the stored user data
                    # Update the database to reflect expired status
                    self.update_membership_status_in_database(user.get("idToken"), user.get("localId"), False)
                
                if membership and not is_membership_expired(membership, membership_expires):
                    self.proceed_to_dashboard(user.get("idToken"), user.get("localId"))
                else:
                    self.go_to_membership(user.get("idToken"), user.get("localId"))
            except Exception:
                pass

    def check_and_update_all_referral_data(self, user):
        """
        Comprehensive referral checking system that runs on every login.
        This validates and updates all referral relationships and counts using the new system.
        """
        try:
            id_token = user.get("idToken")
            local_id = user.get("localId")
            
            debug_log(f"Starting comprehensive referral sync for user: {local_id}")
            
            # Use thread worker for referral sync
            self.referral_sync_worker = ThreadReferralSyncWorker(id_token, local_id)
            self.referral_sync_worker.finished.connect(self._on_referral_sync_completed)
            self.referral_sync_worker.progress.connect(self._on_referral_sync_progress)
            self.referral_sync_worker.start()
            
            # Add to active workers
            self.active_workers.append(self.referral_sync_worker)
            
            # Store user context for callback
            self._referral_sync_context = user
                
        except Exception as e:
            debug_log(f"Exception during comprehensive referral check: {e}")
    
    def _on_referral_sync_completed(self, success: bool, result: dict):
        """Handle referral sync completion"""
        user = getattr(self, '_referral_sync_context', {})
        
        if success and "success" in result:
            results = result.get("results", {})
            actions = results.get("actions", [])
            local_id = user.get("localId", "unknown")
            debug_log(f"Referral sync completed for {local_id}: {len(actions)} actions performed")
            
            for action in actions:
                debug_log(f"  - {action}")
                
            # Get updated comprehensive referral data using another worker
            self.firebase_worker = FirebaseOperationWorker('get_comprehensive_referral_data', 
                                                          id_token=user.get("idToken", ""), 
                                                          user_id=user.get("localId", ""))
            self.firebase_worker.finished.connect(self._on_referral_data_loaded)
            self.firebase_worker.start()
            
            # Add to active workers
            self.active_workers.append(self.firebase_worker)
        else:
            local_id = user.get("localId", "unknown")
            debug_log(f"Referral sync failed for {local_id}: {result.get('error', 'Unknown error')}")
        
        # Remove worker from active workers
        if self.referral_sync_worker in self.active_workers:
            self.active_workers.remove(self.referral_sync_worker)
        self.referral_sync_worker = None
    
    def _on_referral_sync_progress(self, message: str):
        """Handle referral sync progress updates"""
        debug_log(f"Referral sync progress: {message}")
    
    def _on_referral_data_loaded(self, success: bool, result: dict):
        """Handle referral data loading completion"""
        user = getattr(self, '_referral_sync_context', {})
        
        if success and "success" in result:
            referral_data = result["data"]
            
            # Update user object with latest referral information
            user.update({
                "referral_count": referral_data.get("referral_count", 0),
                "referral_code": referral_data.get("referral_code", ""),
                "referred_by": referral_data.get("referred_by", ""),
                "total_referred_count": referral_data.get("total_referred_count", 0),
                "active_referred_count": referral_data.get("active_referred_count", 0)
            })
            
            debug_log(f"Updated user referral data: {referral_data.get('active_referred_count', 0)} active referrals")
        
        # Remove worker from active workers
        if self.firebase_worker in self.active_workers:
            self.active_workers.remove(self.firebase_worker)
        self.firebase_worker = None

    def update_referrer_count_for_user(self, id_token: str, user_id: str, referral_code: str):
        """
        Update the referral count for a user based on their current referred users' membership status.
        """
        try:
            # Get referral code data to find referred users
            referral_data = FirebaseClient.get_referral_code_data(id_token, referral_code)
            if "error" in referral_data:
                debug_log(f"Could not find referral data for code {referral_code}")
                return
            
            # Get current user's profile
            user_profile = FirebaseClient.get_user_data(id_token, user_id)
            if "error" in user_profile:
                debug_log(f"Could not find user profile for {user_id}")
                return
            
            fields = user_profile.get("fields", {})
            referred_user_ids = fields.get("referred_user_ids", {}).get("arrayValue", {}).get("values", [])
            
            # Count how many referred users have active membership
            valid_referral_count = 0
            updated_referred_user_ids = []
            
            for user_val in referred_user_ids:
                referred_user_id = None
                if isinstance(user_val, dict) and "stringValue" in user_val:
                    referred_user_id = user_val["stringValue"]
                elif isinstance(user_val, str):
                    referred_user_id = user_val
                
                if referred_user_id:
                    # Check if referred user has active membership
                    referred_profile = FirebaseClient.get_user_data(id_token, referred_user_id)
                    if "error" not in referred_profile:
                        referred_fields = referred_profile.get("fields", {})
                        has_membership = referred_fields.get("membership", {}).get("booleanValue", False)
                        
                        # Always keep the user in the list
                        updated_referred_user_ids.append(referred_user_id)
                        
                        # Only count if they have membership
                        if has_membership:
                            valid_referral_count += 1
                            debug_log(f"User {referred_user_id} has active membership - counted")
                        else:
                            debug_log(f"User {referred_user_id} does not have active membership - not counted")
                    else:
                        debug_log(f"Could not find profile for referred user {referred_user_id}")
            
            # Update the user's referral count
            update_data = {
                "referral_count": valid_referral_count,
                "referred_user_ids": updated_referred_user_ids
            }
            
            result = FirebaseClient.set_user_data(id_token, user_id, update_data)
            if "error" not in result:
                debug_log(f"Updated referral count for user {user_id} to {valid_referral_count}")
                # Update current user data
                if self.current_user and self.current_user.get("localId") == user_id:
                    self.current_user["referral_count"] = valid_referral_count
            else:
                debug_log(f"Failed to update referral count for user {user_id}: {result}")
                
        except Exception as e:
            debug_log(f"Exception in update_referrer_count_for_user: {e}")

    # ---------------- Navigation methods ----------------
    def go_to_free_trial(self, id_token: str, local_id: str):
        """Navigate to free trial page"""
        try:
            # Use current_user data if available, otherwise fetch fresh
            if self.current_user:
                profile = self.current_user
                self.free_trial_page.set_user(id_token, local_id, profile)
                self.stack.setCurrentWidget(self.free_trial_page)
            else:
                # Use Firebase worker to fetch profile data
                self.firebase_worker = FirebaseOperationWorker('get_user_data', 
                                                              id_token=id_token, 
                                                              user_id=local_id)
                self.firebase_worker.finished.connect(self._on_free_trial_profile_loaded)
                self.firebase_worker.start()
                
                # Add to active workers
                self.active_workers.append(self.firebase_worker)
                
                # Store context
                self._free_trial_context = {'id_token': id_token, 'local_id': local_id}
        except Exception as e:
            debug_log(f"Exception in go_to_free_trial: {e}")
    
    def _on_free_trial_profile_loaded(self, success: bool, result: dict):
        """Handle free trial profile loading completion"""
        if success and 'error' not in result:
            fields = result.get("fields", {}) if isinstance(result, dict) else {}
            profile = self.extract_profile_from_fields(fields)
        else:
            profile = self.get_default_profile()
        
        # Get context
        context = getattr(self, '_free_trial_context', {})
        id_token = context.get('id_token', '')
        local_id = context.get('local_id', '')
        
        self.free_trial_page.set_user(id_token, local_id, profile)
        self.stack.setCurrentWidget(self.free_trial_page)
        
        # Remove worker from active workers
        if self.firebase_worker in self.active_workers:
            self.active_workers.remove(self.firebase_worker)
        self.firebase_worker = None
    
    def go_to_membership_after_skip(self):
        """Navigate to membership page after user skips free trial"""
        if self.current_user:
            id_token = self.current_user.get("idToken")
            local_id = self.current_user.get("localId")
            if id_token and local_id:
                self.go_to_membership(id_token, local_id)
    
    # ---------------- Membership / Dashboard transitions ----------------
    def go_to_membership(self, id_token: str, local_id: str):
        # Use Firebase worker to fetch profile data
        self.firebase_worker = FirebaseOperationWorker('get_user_data', 
                                                      id_token=id_token, 
                                                      user_id=local_id)
        self.firebase_worker.finished.connect(self._on_membership_profile_loaded)
        self.firebase_worker.start()
        
        # Add to active workers
        self.active_workers.append(self.firebase_worker)
        
        # Store context for callback
        self._membership_context = {'id_token': id_token, 'local_id': local_id}
    
    def _on_membership_profile_loaded(self, success: bool, result: dict):
        """Handle membership profile loading completion"""
        if success and 'error' not in result:
            fields = result.get("fields", {}) if isinstance(result, dict) else {}
            profile = self.extract_profile_from_fields(fields)
        else:
            profile = self.get_default_profile()
        
        # Get context
        context = getattr(self, '_membership_context', {})
        id_token = context.get('id_token', '')
        local_id = context.get('local_id', '')
        
        self.membership_page.set_user(id_token, local_id, profile)
        self.stack.setCurrentWidget(self.membership_page)
        
        # Remove worker from active workers
        if self.firebase_worker in self.active_workers:
            self.active_workers.remove(self.firebase_worker)
        self.firebase_worker = None

    def proceed_to_dashboard(self, id_token: str, local_id: str):
        # Use current_user data if available, otherwise fetch fresh
        if self.current_user:
            profile = self.current_user
            self.dashboard_page.set_profile(id_token, local_id, profile)
            self.stack.setCurrentWidget(self.dashboard_page)
        else:
            # Use Firebase worker to fetch profile data
            self.firebase_worker = FirebaseOperationWorker('get_user_data', 
                                                          id_token=id_token, 
                                                          user_id=local_id)
            self.firebase_worker.finished.connect(self._on_dashboard_profile_loaded)
            self.firebase_worker.start()
            
            # Add to active workers
            self.active_workers.append(self.firebase_worker)
            
            # Store context for callback
            self._dashboard_context = {'id_token': id_token, 'local_id': local_id}
    
    def _on_dashboard_profile_loaded(self, success: bool, result: dict):
        """Handle dashboard profile loading completion"""
        if success and 'error' not in result:
            fields = result.get("fields", {}) if isinstance(result, dict) else {}
            profile = self.extract_profile_from_fields(fields)
        else:
            profile = self.get_default_profile()
        
        # Get context
        context = getattr(self, '_dashboard_context', {})
        id_token = context.get('id_token', '')
        local_id = context.get('local_id', '')
        
        self.dashboard_page.set_profile(id_token, local_id, profile)
        self.stack.setCurrentWidget(self.dashboard_page)
        
        # Remove worker from active workers
        if self.firebase_worker in self.active_workers:
            self.active_workers.remove(self.firebase_worker)
        self.firebase_worker = None

    def extract_profile_from_fields(self, fields: dict) -> dict:
        """Extract and normalize profile data from Firestore fields."""
        profile = {
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
            "referral_code": FirebaseClient._extract_field_value(fields.get("referral_code"), "string", ""),
            "referral_count": FirebaseClient._extract_field_value(fields.get("referral_count"), "integer", 0),
            "referred_by": FirebaseClient._extract_field_value(fields.get("referred_by"), "string", ""),
        }

        debug_log(f"Extracted profile - referral_code: {profile['referral_code']}, referral_count: {profile['referral_count']}, referred_by: {profile['referred_by']}, free_trial_used: {profile['free_trial_used']}")
        
        return profile

    def get_default_profile(self) -> dict:
        """Get default profile with empty values."""
        return {
            "email": "", 
            "username": "", 
            "whatsapp": "",
            "membership": False, 
            "email_verified": False, 
            "membership_expires": "", 
            "membership_type": "none",
            "membership_activated_at": "",
            "membership_activated_by": "",
            "free_trial_used": False,
            "referral_code": "", 
            "referral_count": 0, 
            "referred_by": ""
        }
    
    def on_trial_activated(self):
        """Handle when free trial is activated - navigate to login page"""
        try:
            debug_log("Free trial activated, navigating to login page")
            # Navigate directly to login page
            self.stack.setCurrentWidget(self.login_page)
            # Clear current user session to force re-login
            self.current_user = None
        except Exception as e:
            debug_log(f"Exception in on_trial_activated: {e}")
    
    def on_membership_back(self):
        """Handle back button from membership page - navigate based on free_trial_used"""
        try:
            # Get user profile from membership page
            user_profile = self.membership_page._user_profile
            free_trial_used = user_profile.get("free_trial_used", False)
            
            if free_trial_used:
                # If free trial was used, go to login page
                debug_log("Free trial used, navigating to login page")
                self.stack.setCurrentWidget(self.login_page)
            else:
                # If free trial not used, go to free trial page
                debug_log("Free trial not used, navigating to free trial page")
                if self.current_user:
                    id_token = self.current_user.get("idToken")
                    local_id = self.current_user.get("localId")
                    if id_token and local_id:
                        self.go_to_free_trial(id_token, local_id)
                else:
                    # Fallback to login if no current user
                    self.stack.setCurrentWidget(self.login_page)
        except Exception as e:
            debug_log(f"Exception in on_membership_back: {e}")
            # Fallback to login on error
            self.stack.setCurrentWidget(self.login_page)

    # ---------------- Logout / Cleanup ----------------

    def cleanup_temp_signups(self):
        """Clean up any temporary signups that were abandoned."""
        for id_token, local_id in _TEMP_SIGNUPS:
            try:
                FirebaseClient.delete_account(id_token)
            except Exception:
                pass
        _TEMP_SIGNUPS.clear()
    
    def cleanup_on_exit(self):
        """Comprehensive cleanup when the application exits."""
        try:
            print("Starting application cleanup...")
            
            # Close all sub-applications first
            self.close_all_sub_apps()
            
            # Clean up temp signups first
            self.cleanup_temp_signups()
            
            # Use cleanup worker for background cleanup
            self.cleanup_worker = CleanupWorker('temp_files', 
                                               temp_dirs=[], 
                                               processes=self.sub_apps.copy(), 
                                               cache_paths=[str(CACHE_PATH)] if CACHE_PATH.exists() else [])
            self.cleanup_worker.finished.connect(self._on_cleanup_completed)
            self.cleanup_worker.start()
            
            # Add to active workers
            self.active_workers.append(self.cleanup_worker)
            
        except Exception as e:
            print(f"Error during cleanup: {e}")
    
    def _on_cleanup_completed(self, success: bool, message: str):
        """Handle cleanup completion"""
        if success:
            print(f"Background cleanup completed: {message}")
        else:
            print(f"Background cleanup failed: {message}")
        
        # Trigger comprehensive cleanup
        try:
            total_cleaned = cleanup_on_exit()
            print(f"Application cleanup completed. Total items cleaned: {total_cleaned}")
        except Exception as e:
            print(f"Error in final cleanup: {e}")
        
        # Remove worker from active workers
        if self.cleanup_worker in self.active_workers:
            self.active_workers.remove(self.cleanup_worker)
        self.cleanup_worker = None
    
    def closeEvent(self, event):
        """Handle application close event."""
        try:
            print("Application is closing, performing cleanup...")
            self.cleanup_on_exit()
        except Exception as e:
            print(f"Error during close cleanup: {e}")
        finally:
            # Accept the close event
            event.accept()
    
    def update_membership_status_in_database(self, id_token: str, user_id: str, membership_status: bool):
        """Update membership status in the database when expiration is detected."""
        try:
            from firebase_client import FirebaseClient
            debug_log(f"Updating membership status in database for user {user_id} to {membership_status}")
            
            # Update membership status in Firebase
            result = FirebaseClient.set_user_data(id_token, user_id, {"membership": membership_status})
            
            if "error" in result:
                debug_log(f"Failed to update membership status in database: {result.get('error', 'Unknown error')}")
            else:
                debug_log(f"Successfully updated membership status in database for user {user_id}")
                
        except Exception as e:
            debug_log(f"Exception updating membership status in database: {e}")

    def handle_membership_expired(self):
        """Handle when user's membership has expired - redirect to membership page."""
        debug_log("Membership expired, redirecting to membership page")
        
        if self.current_user:
            # Redirect to membership page with current user data
            self.go_to_membership(self.current_user.get("idToken"), self.current_user.get("localId"))
        else:
            # Fallback - go to login page
            debug_log("No current user data available, redirecting to login")
            self.stack.setCurrentWidget(self.login_page)

    def handle_logout(self):
        """Handle user logout and cleanup."""
        print("User logging out - closing all applications...")
        
        # Close all launched applications first
        close_all_apps()
        
        # Close all sub-applications immediately
        self.close_all_sub_apps()
        
        # App manager functionality removed - missing app_manager module
        print("App manager functionality disabled due to missing module")
        
        # Use cleanup worker for background cleanup
        self.cleanup_worker = CleanupWorker('cache', 
                                           cache_paths=[str(CACHE_PATH)] if CACHE_PATH.exists() else [])
        self.cleanup_worker.finished.connect(self._on_logout_cleanup_completed)
        self.cleanup_worker.start()
        
        # Add to active workers
        self.active_workers.append(self.cleanup_worker)
        
        # Reset session
        self.current_user = None
        print("User session cleared")
        
        # Go to login
        self.stack.setCurrentWidget(self.login_page)
        print("Returned to login screen")
    
    def _on_logout_cleanup_completed(self, success: bool, message: str):
        """Handle logout cleanup completion"""
        if success:
            print(f"Logout cleanup completed: {message}")
        else:
            print(f"Logout cleanup failed: {message}")
        
        # Remove worker from active workers
        if self.cleanup_worker in self.active_workers:
            self.active_workers.remove(self.cleanup_worker)
        self.cleanup_worker = None
    
    # Simplified launcher methods
    def launch_app_simple(self, app_name: str, username: str = ""):
        """
        Simple launcher that automatically detects if app is local or GitHub
        and launches it accordingly
        """
        try:
            # App manager check removed - missing app_manager module
            
            # Show loading screen
            self.show_loading_screen(app_name)
            
            # Check if it's a local app
            local_path = get_local_app_path(app_name)
            if local_path and os.path.exists(local_path):
                debug_log(f"Launching local app: {app_name}")
                # Use AppLaunchWorker for local apps
                self.app_launch_worker = AppLaunchWorker(app_name, 'local', local_path, username)
                self.app_launch_worker.finished.connect(self._on_app_launch_finished)
                self.app_launch_worker.progress.connect(self._on_app_launch_progress)
                self.app_launch_worker.start()
                
                # Add to active workers
                self.active_workers.append(self.app_launch_worker)
                return True
            
            # Check if it's a GitHub app
            github_url = get_github_app_url(app_name)
            if github_url:
                debug_log(f"Launching GitHub app: {app_name}")
                # DirectAppLauncher removed - missing subprocess_app_launcher module
                QMessageBox.warning(self, "App Launch", "App launching functionality has been disabled due to missing modules.")
                return True
            
            # App not found
            self.hide_loading_screen()
            QMessageBox.warning(self, "App Not Found", f"Application '{app_name}' not found in configuration")
            return False
            
        except Exception as e:
            debug_log(f"Error in simple launcher: {e}")
            self.hide_loading_screen()
            QMessageBox.critical(self, "Launch Error", f"Failed to launch {app_name}: {str(e)}")
            return False
    
    def launch_local_app_simple(self, app_name: str, username: str = ""):
        """Launch a local app using the simplified launcher"""
        # App manager check removed - missing app_manager module False
        
        # Show loading screen
        self.show_loading_screen(app_name)
        
        local_path = get_local_app_path(app_name)
        if not local_path:
            self.hide_loading_screen()
            # app_manager.finish_launch() - removed due to missing module
            QMessageBox.warning(self, "App Not Found", f"Local app '{app_name}' not configured")
            return False
        
        if not os.path.exists(local_path):
            self.hide_loading_screen()
            # app_manager.finish_launch() - removed due to missing module
            QMessageBox.critical(self, "File Not Found", f"Local app file not found: {local_path}")
            return False
        
        # Use AppLaunchWorker for local apps
        self.app_launch_worker = AppLaunchWorker(app_name, 'local', local_path, username)
        # Store app name for later use
        self.app_launch_worker.app_name = app_name
        self.app_launch_worker.finished.connect(self._on_app_launch_finished)
        self.app_launch_worker.progress.connect(self._on_app_launch_progress)
        self.app_launch_worker.start()
        
        # Add to active workers
        self.active_workers.append(self.app_launch_worker)
        return True
    
    def launch_github_app_simple(self, app_name: str, username: str = ""):
        """Launch a GitHub app using the simplified launcher"""
        # App manager check removed - missing app_manager module False
        
        # Show loading screen
        self.show_loading_screen(app_name)
        
        github_url = get_github_app_url(app_name)
        if not github_url:
            self.hide_loading_screen()
            # app_manager.finish_launch() - removed due to missing module
            QMessageBox.warning(self, "App Not Found", f"GitHub app '{app_name}' not configured")
            return False
        
        # DirectAppLauncher removed - missing subprocess_app_launcher module
        QMessageBox.warning(self, "App Launch", "App launching functionality has been disabled due to missing modules.")
        return True