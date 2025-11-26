from PySide6.QtWidgets import QVBoxLayout, QLabel, QPushButton, QWidget, QHBoxLayout, QMessageBox, QMainWindow, QGridLayout, QScrollArea, QSizePolicy, QDialog, QApplication, QTabWidget
from PySide6.QtCore import Qt, Signal, QTimer, QThread, QObject, QMetaObject
from datetime import datetime
import os
import sys
import subprocess
import threading
import time
import psutil
from pathlib import Path
try:
    import pygetwindow as gw
except ImportError:
    gw = None
from PySide6.QtGui import QPixmap
from styled_widget import StyledWidget
from loading_widget import LoadingSpinner, LoadingOverlay
from config import GITHUB_APPS, LOCAL_APPS, get_app_icon, LOCAL_APPS_DICT, GITHUB_APPS_DICT
from referral_details_window import ReferralDetailsWindow
from rewards_window import RewardsWindow
from workers import ReferralSyncWorker
from utils import debug_log
from downloaders.instagram import InstagramWidget
from downloaders.facebook import FacebookWidget
from downloaders.tiktok import TikTokWidget
from downloaders.dailymotion import DailymotionWidget
from downloaders.soundcloud import SoundCloudWidget
from downloaders.vimeo import VimeoWidget
from downloaders.twitch import TwitchWidget
from downloaders.reddit import RedditWidget
from downloaders.bandcamp import BandcampWidget
from youtube_downloader_gui_patched_fixed_corrected import YouTubeDownloaderGUI

class PopupWindow(QDialog):
    """Standalone popup window for app launching."""
    _close_requested = Signal()
    
    def __init__(self, window_title):
        super().__init__()
        self.window_title = window_title
        self.setWindowTitle("Launching...")
        self.setModal(False)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        
        # Connect signal for thread-safe closing
        self._close_requested.connect(self.close, Qt.ConnectionType.QueuedConnection)
        
        # Setup UI
        layout = QVBoxLayout(self)
        self.label = QLabel(f"{window_title} is launching, please wait...")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("""
            QLabel {
                color: black;
                font-size: 14px;
                font-weight: bold;
                padding: 20px;
            }
        """)
        layout.addWidget(self.label)
        
        self.setStyleSheet("""
            QDialog {
                background-color: white;
                border-radius: 10px;
                border: 2px solid #2196F3;
            }
        """)
        
        self.resize(400, 100)
        self.center_on_screen()
    
    def request_close(self):
        """Request close safely from any thread."""
        try:
            self._close_requested.emit()
        except Exception as e:
            pass
    
    def center_on_screen(self):
        """Center the popup on screen."""
        try:
            screen = QApplication.primaryScreen().geometry()
            x = (screen.width() - self.width()) // 2
            y = (screen.height() - self.height()) // 2
            self.move(x, y)
        except:
            pass


def watch_and_close_popup(popup, window_title, timeout=90):
    """Watch for app window and close popup when detected."""
    if gw is None:
        time.sleep(5)
        try:
            popup.close()
        except:
            pass
        return

    # Create multiple search patterns from the title
    title_lower = window_title.lower().strip()
    # Extract meaningful words (longer than 3 chars)
    search_words = [w for w in title_lower.split() if len(w) > 3]
    
    start_time = time.time()

    # Track which windows we've already logged
    logged_windows = set()
    check_count = 0

    while time.time() - start_time < timeout:
        try:
            if not popup or not popup.isVisible():
                return

            # Get all window titles
            windows = gw.getAllTitles()
            check_count += 1
            
            # Log all windows every 5 seconds
            if check_count % 10 == 1:  # Every 5 seconds (0.5s * 10)
                new_windows = [w for w in windows if w and w not in logged_windows]
                if new_windows:
                    logged_windows.update(new_windows)
            
            # Check each window
            for w in windows:
                if not w or len(w.strip()) == 0:
                    continue
                    
                w_lower = w.lower()
                
                # Strategy 1: Exact substring match
                if title_lower in w_lower:
                    popup.request_close()
                    return
                
                # Strategy 2: Reverse match
                if w_lower in title_lower:
                    popup.request_close()
                    return
                
                # Strategy 3: Match if at least 2 significant words match
                if len(search_words) >= 2:
                    matches = sum(1 for word in search_words if word in w_lower)
                    if matches >= 2:
                        popup.request_close()
                        return

        except Exception:
            pass

        time.sleep(0.5)

    popup.request_close()



# Access the shared launcher manager from main_window
def get_launcher_manager():
    """Get the global launcher manager from main_window"""
    try:
        # CRITICAL: Use the SAME import path as main.py uses
        # Import the main_window module that actually gets executed
        import main_window
        
        manager = main_window.app_launcher_manager
        return manager
    except Exception:
        return None

def launch_app(app_name: str, username: str = "", show_loader: bool = True, dashboard_instance=None):
    """Launch an app using the improved launcher"""
    
    # Get manager from dashboard instance if provided, otherwise use get_launcher_manager
    manager = None
    if dashboard_instance and hasattr(dashboard_instance, 'launcher_manager'):
        manager = dashboard_instance.launcher_manager
    else:
        manager = get_launcher_manager()
    
    if manager is None:
        return False
    
    # Note: improved launcher doesn't use show_loader parameter (uses popup instead)
    result = manager.launch_app(app_name, username)
    return result

def stop_app(app_name: str):
    """Stop a running app"""
    manager = get_launcher_manager()
    if manager:
        manager.stop_app(app_name)

def is_app_running(app_name: str) -> bool:
    """Check if an app is running"""
    manager = get_launcher_manager()
    if manager:
        return app_name in manager.active_apps
    return False

class DashboardPage(StyledWidget):
    logout = Signal()
    membership_expired = Signal()  # Signal to notify main window that membership has expired

    def __init__(self, launcher_manager=None):
        super().__init__()
        self.profile = {}
        self._id_token = None
        self._local_id = None
        self.loading_overlay = None
        # legacy workers removed
        self.referral_sync_worker = None
        self.rewards_worker = None
        
        # Store launcher manager reference
        self.launcher_manager = launcher_manager
        
        # Sidebar state
        self.sidebar_visible = False
        self.sidebar_width = 280
        
        self.init_ui()
        self.setup_loading_overlay()

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QWidget()
        header.setStyleSheet("background-color: #2D2D30; padding: 10px;")
        header.setFixedHeight(60)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(15, 0, 15, 0)
        header_layout.setSpacing(15)

        # Hamburger menu button
        self.menu_btn = QPushButton("☰")
        self.menu_btn.setFixedSize(40, 40)
        self.menu_btn.setStyleSheet("""
            QPushButton {
                background-color: #3E3E42;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4E4E52;
            }
            QPushButton:pressed {
                background-color: #5E5E62;
            }
        """)
        self.menu_btn.clicked.connect(self.toggle_sidebar)
        header_layout.addWidget(self.menu_btn)

        # Title
        title = QLabel("Dashboard")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: white;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        # Logout button
        logout_btn = QPushButton("Logout")
        logout_btn.setMinimumHeight(40)
        logout_btn.setStyleSheet("""
            QPushButton {
                background-color: #D32F2F;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #C62828;
            }
            QPushButton:pressed {
                background-color: #B71C1C;
            }
        """)
        logout_btn.clicked.connect(lambda: self.logout.emit())
        header_layout.addWidget(logout_btn)

        main_layout.addWidget(header)

        # Create container widget for content area (sidebar will overlay this)
        content_container = QWidget()
        content_container_layout = QVBoxLayout(content_container)
        content_container_layout.setSpacing(0)
        content_container_layout.setContentsMargins(0, 0, 0, 0)

        # Create sidebar (will overlay the main content)
        self.sidebar = QWidget(content_container)  # Parent is content_container for overlay
        self.sidebar.setStyleSheet("""
            QWidget {
                background-color: #252526;
                border-right: 1px solid #3E3E42;
            }
        """)
        
        self.sidebar_scroll = QScrollArea(content_container)  # Parent is content_container for overlay
        self.sidebar_scroll.setWidget(self.sidebar)
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar_scroll.setFixedWidth(0)  # Initially hidden
        self.sidebar_scroll.setFixedHeight(0)  # Will be set to match parent height
        self.sidebar_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #252526;
            }
            QScrollBar:vertical {
                background-color: #1E1E1E;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: #3E3E42;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #4E4E52;
            }
        """)
        # Raise sidebar to appear on top
        self.sidebar_scroll.raise_()
        
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setSpacing(15)
        sidebar_layout.setContentsMargins(15, 15, 15, 15)

        # User info container (Account Details)
        user_info_container = QWidget()
        user_info_container.setStyleSheet("""
            QWidget {
                background-color: #3E3E42;
                border-radius: 6px;
                padding: 10px;
            }
        """)
        user_info_layout = QVBoxLayout(user_info_container)
        user_info_layout.setSpacing(8)

        # Account Details title
        account_title = QLabel("Account Details")
        account_title.setStyleSheet("font-size: 16px; font-weight: bold; color: white; margin-bottom: 5px;")
        user_info_layout.addWidget(account_title)

        # User info labels
        self.email_label = QLabel("")
        self.email_label.setStyleSheet("font-size: 13px; color: #CCCCCC;")
        user_info_layout.addWidget(self.email_label)

        self.username_label = QLabel("")
        self.username_label.setStyleSheet("font-size: 13px; color: #CCCCCC;")
        user_info_layout.addWidget(self.username_label)

        self.membership_label = QLabel("")
        self.membership_label.setStyleSheet("font-size: 13px; color: #CCCCCC;")
        user_info_layout.addWidget(self.membership_label)

        # Membership time remaining label
        self.membership_time_label = QLabel("")
        self.membership_time_label.setStyleSheet("font-size: 13px; color: #FF9800; font-weight: bold;")
        user_info_layout.addWidget(self.membership_time_label)

        sidebar_layout.addWidget(user_info_container)

        # Referral details button
        self.referral_btn = QPushButton("View Referral Details")
        self.referral_btn.setMinimumHeight(40)
        self.referral_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:pressed {
                background-color: #1565C0;
            }
        """)
        self.referral_btn.clicked.connect(self.open_referral_details)
        sidebar_layout.addWidget(self.referral_btn)
        
        # Calculate Rewards button
        self.calculate_rewards_btn = QPushButton("Calculate Rewards")
        self.calculate_rewards_btn.setMinimumHeight(40)
        self.calculate_rewards_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
            QPushButton:pressed {
                background-color: #E65100;
            }
        """)
        self.calculate_rewards_btn.clicked.connect(self.open_rewards_window)
        sidebar_layout.addWidget(self.calculate_rewards_btn)

        # Version details container
        version_info_container = QWidget()
        version_info_container.setStyleSheet("""
            QWidget {
                background-color: #3E3E42;
                border-radius: 6px;
                padding: 10px;
            }
        """)
        version_info_layout = QVBoxLayout(version_info_container)
        version_info_layout.setSpacing(8)

        # Version title
        version_title = QLabel("Version Details")
        version_title.setStyleSheet("font-size: 16px; font-weight: bold; color: white; margin-bottom: 5px;")
        version_info_layout.addWidget(version_title)

        # Version labels
        try:
            from main_window import get_app_version
            app_version = get_app_version()
        except Exception as e:
            debug_log(f"Error importing app version: {e}")
            app_version = "Unknown"
        
        self.app_version_label = QLabel(f"App Version: {app_version}")
        self.app_version_label.setStyleSheet("font-size: 13px; color: #CCCCCC;")
        version_info_layout.addWidget(self.app_version_label)

        self.build_date_label = QLabel("Build Date: November 2025")
        self.build_date_label.setStyleSheet("font-size: 13px; color: #CCCCCC;")
        version_info_layout.addWidget(self.build_date_label)

        # Check for update button
        self.check_update_btn = QPushButton("Check for Update")
        self.check_update_btn.setMinimumHeight(40)
        self.check_update_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                margin-top: 5px;
            }
            QPushButton:hover {
                background-color: #45A049;
            }
            QPushButton:pressed {
                background-color: #3D8B40;
            }
        """)
        self.check_update_btn.clicked.connect(self.check_for_updates)
        version_info_layout.addWidget(self.check_update_btn)

        sidebar_layout.addWidget(version_info_container)
        sidebar_layout.addStretch()

        # Main content area for downloaders (scrollable)
        main_content = QWidget()
        main_content_layout = QVBoxLayout(main_content)
        main_content_layout.setSpacing(15)
        main_content_layout.setContentsMargins(15, 15, 15, 15)

        # Media Downloaders section title
        downloaders_title = QLabel("Media Downloaders")
        downloaders_title.setStyleSheet("font-size: 20px; font-weight: bold; color: white; margin-bottom: 10px;")
        main_content_layout.addWidget(downloaders_title)

        # Create tab widget for downloaders
        self.downloader_tabs = QTabWidget()
        self.downloader_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #2c3448;
                border-radius: 6px;
                background-color: #1E1E1E;
            }
            QTabBar::tab {
                background: #2D2D30;
                color: #d0d6e2;
                padding: 8px 14px;
                margin: 2px;
                border-radius: 4px;
            }
            QTabBar::tab:selected {
                background: #3E3E42;
                color: #ffffff;
            }
            QTabBar::tab:hover {
                background: #4E4E52;
            }
        """)

        # Discover ffmpeg location
        ffmpeg_location = self.discover_ffmpeg_location()

        # Add downloader tabs
        self.downloader_tabs.addTab(InstagramWidget(ffmpeg_location, self), "Instagram")
        self.downloader_tabs.addTab(FacebookWidget(ffmpeg_location, self), "Facebook")
        self.downloader_tabs.addTab(TikTokWidget(ffmpeg_location, self), "TikTok")
        self.downloader_tabs.addTab(DailymotionWidget(ffmpeg_location, self), "Dailymotion")
        self.downloader_tabs.addTab(SoundCloudWidget(ffmpeg_location, self), "SoundCloud")
        self.downloader_tabs.addTab(VimeoWidget(ffmpeg_location, self), "Vimeo")
        self.downloader_tabs.addTab(TwitchWidget(ffmpeg_location, self), "Twitch")
        self.downloader_tabs.addTab(RedditWidget(ffmpeg_location, self), "Reddit")
        self.downloader_tabs.addTab(BandcampWidget(ffmpeg_location, self), "Bandcamp")
        self.downloader_tabs.addTab(YouTubeDownloaderGUI(), "YouTube")

        main_content_layout.addWidget(self.downloader_tabs)
        main_content_layout.addStretch()

        # Wrap main content in scroll area for vertical scrolling
        main_content_scroll = QScrollArea()
        main_content_scroll.setWidget(main_content)
        main_content_scroll.setWidgetResizable(True)
        main_content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        main_content_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        main_content_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #1E1E1E;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #3E3E42;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #4E4E52;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        # Add scrollable main content to container
        content_container_layout.addWidget(main_content_scroll)

        # Add container to main layout
        main_layout.addWidget(content_container)
        self.setLayout(main_layout)
        
        # Store references for positioning
        self.content_container = content_container
    
    def toggle_sidebar(self):
        """Toggle sidebar visibility"""
        if self.sidebar_visible:
            # Hide sidebar
            self.sidebar_scroll.setFixedWidth(0)
            self.sidebar_scroll.setFixedHeight(0)
            self.sidebar_scroll.lower()  # Lower it when hidden
            self.sidebar_visible = False
        else:
            # Show sidebar - overlay on top of content
            self.sidebar_scroll.raise_()  # Raise to top first
            # Use QTimer to ensure container has proper size
            QTimer.singleShot(10, self._position_sidebar)
            self.sidebar_visible = True
    
    def _position_sidebar(self):
        """Position sidebar after widget is shown"""
        if self.sidebar_visible and hasattr(self, 'content_container'):
            container_height = self.content_container.height()
            self.sidebar_scroll.setFixedWidth(self.sidebar_width)
            self.sidebar_scroll.setFixedHeight(container_height if container_height > 0 else self.height())
            self.sidebar_scroll.move(0, 0)
            self.sidebar_scroll.raise_()  # Ensure it's on top
    
    def discover_ffmpeg_location(self) -> str | None:
        """Attempt to find ffmpeg next to this script. Returns a string path or None if not found."""
        app_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)).resolve()
        candidates = [
            app_dir / "ffmpeg.exe",  # Windows common
            app_dir / "ffmpeg",      # Unix-like
        ]
        for p in candidates:
            if p.exists():
                return str(p.parent)
        return None
    
    def setup_loading_overlay(self):
        """Set up the loading overlay for this page"""
        self.loading_overlay = LoadingOverlay(self, "Processing...")
        # Add timeout timer for heavy apps
        self.loading_timeout = QTimer()
        self.loading_timeout.timeout.connect(self._on_loading_timeout)
        self.loading_timeout.setSingleShot(True)
    
    def resizeEvent(self, event):
        """Handle resize events to properly position loading overlay and sidebar"""
        super().resizeEvent(event)
        # Handle loading overlay
        if self.loading_overlay:
            self.loading_overlay.resize(self.size())
        # Handle sidebar positioning when visible
        if hasattr(self, 'content_container') and self.sidebar_visible:
            container_height = self.content_container.height()
            self.sidebar_scroll.setFixedHeight(container_height)
            self.sidebar_scroll.move(0, 0)
            self.sidebar_scroll.raise_()
    
    def on_app_clicked(self, name: str, url_or_path: str, is_local: bool):
        """Launch app using universal app launcher with window detection popup."""
        # Get username from profile, fallback to email if username not available
        username = self.profile.get("username", "")
        if not username:
            username = self.profile.get("email", "guest")
        
        try:
            # Clean up any dead apps first
            from improved_launcher import ImprovedLauncherManager
            # Get global launcher manager
            manager = get_launcher_manager()
            if manager:
                manager._periodic_cleanup()
            
            # Check if app is already running
            if is_app_running(name):
                QMessageBox.information(self, "App Running", f"{name} is already running!")
                return
            
            # Get app info from config dictionaries (which are actually lists)
            app_info = None
            if is_local:
                # Search through LOCAL_APPS_DICT list
                for app in LOCAL_APPS_DICT:
                    if app.get("name") == name:
                        app_info = app
                        break
            else:
                # Search through GITHUB_APPS_DICT list
                for app in GITHUB_APPS_DICT:
                    if app.get("name") == name:
                        app_info = app
                        break
            
            if not app_info:
                app_info = {"entry": url_or_path, "name": name, "title": name}
            
            # Get window title for popup detection
            window_title = app_info.get("window_title", app_info.get("title", app_info.get("name", name)))
            
            # Create popup window for launch notification
            popup = PopupWindow(window_title)
            popup.show()
            
            # Start window watcher thread
            watcher = threading.Thread(
                target=watch_and_close_popup,
                args=(popup, window_title),
                daemon=True
            )
            watcher.start()
            
            # Launch the app using improved launcher (handles GitHub downloads automatically)
            success = launch_app(name, username, show_loader=False, dashboard_instance=self)
            
            if success:
                # Connect to manager signals for this specific app
                manager = get_launcher_manager()
                if manager:
                    manager.signals.finished.connect(
                        lambda app_name, result: self.on_app_launch_finished(app_name, result) if app_name == name else None
                    )
                    manager.signals.error.connect(
                        lambda app_name, error, trace: self.on_app_launch_error(app_name, error) if app_name == name else None
                    )
                    manager.signals.progress.connect(
                        lambda app_name, message: self.on_app_launch_progress(app_name, message) if app_name == name else None
                    )
            else:
                QMessageBox.critical(self, "Launch Failed", f"Could not launch {name}. The app may not be available or there was an error.")
                try:
                    popup.request_close()
                except:
                    pass
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Launch Error", f"Failed to launch {name}: {str(e)}")

    
    def on_app_launch_finished(self, app_name: str, result):
        """Handle when app launch is finished"""
        if not result.success:
            QMessageBox.critical(self, "Launch Failed", f"Failed to launch {app_name}: {result.message}")

    def on_launched_app_ready(self, app_name: str):
        """Called when a GUI app instance is ready to be shown."""
        pass

    def _on_loading_timeout(self):
        """Handle loading timeout for heavy apps"""
        pass
    
    def on_app_launch_error(self, app_name: str, error: str):
        """Handle app launch errors"""
        QMessageBox.critical(self, "Launch Error", f"Error launching {app_name}: {error}")
    
    def on_app_launch_progress(self, app_name: str, message: str):
        """Handle app launch progress updates"""
        pass

    def cleanup_workers(self):
        """Clean up any running workers"""
        # legacy workers removed; nothing to cleanup here
        
        if self.referral_sync_worker:
            self.referral_sync_worker = None
    
    def cleanup_loading_overlay(self):
        """Clean up the loading overlay and its resources"""
        try:
            if self.loading_overlay:
                self.loading_overlay.cleanup()
        except Exception as e:
            debug_log(f"Error cleaning up loading overlay: {e}")
    
    def closeEvent(self, event):
        """Handle close event to cleanup workers and timers"""
        # Stop membership timer if active
        if hasattr(self, "membership_timer") and self.membership_timer.isActive():
            self.membership_timer.stop()
        self.cleanup_workers()
        super().closeEvent(event)

    def update_membership_time(self, membership, membership_expires):
        """Update membership time remaining with real-time timer"""
        # Stop any existing timer to avoid duplicates
        if hasattr(self, "membership_timer") and self.membership_timer.isActive():
            self.membership_timer.stop()

        # If no membership, show message and return
        if not (membership and membership_expires):
            self.membership_time_label.setText("No active membership")
            return

        def refresh_label():
            try:
                expires_date = datetime.fromisoformat(membership_expires.replace('Z', '+00:00'))
                current_date = datetime.now(expires_date.tzinfo)
                time_remaining = expires_date - current_date

                if time_remaining.days > 0:
                    self.membership_time_label.setText(f"Membership expires in: {time_remaining.days} days")
                elif time_remaining.total_seconds() > 3600:
                    hours = int(time_remaining.total_seconds() // 3600)
                    self.membership_time_label.setText(f"Membership expires in: {hours} hours")
                elif time_remaining.total_seconds() > 60:
                    minutes = int(time_remaining.total_seconds() // 60)
                    self.membership_time_label.setText(f"Membership expires in: {minutes} minutes")
                elif time_remaining.total_seconds() > 0:
                    seconds = int(time_remaining.total_seconds())
                    self.membership_time_label.setText(f"Membership expires in: {seconds} seconds")
                else:
                    self.membership_time_label.setText("Membership expired")
                    self.membership_timer.stop()
                    # Check if membership expired and emit signal
                    from utils import is_membership_expired
                    if membership and is_membership_expired(membership, membership_expires):
                        self.membership_expired.emit()
            except:
                self.membership_time_label.setText("Membership time: Unknown")
                self.membership_timer.stop()

        # Create and start timer to update every second
        self.membership_timer = QTimer(self)
        self.membership_timer.timeout.connect(refresh_label)
        self.membership_timer.start(1000)  # update every 1 second

        # Update immediately once when called
        refresh_label()

    def set_profile(self, id_token: str, local_id: str, profile: dict):
        self._id_token = id_token
        self._local_id = local_id
        self.profile = profile or {}
        email = self.profile.get("email", "")
        username = self.profile.get("username", "")
        membership = self.profile.get("membership", False)
        membership_expires = self.profile.get("membership_expires", "")

        # Check if membership has expired
        from utils import is_membership_expired
        if membership and is_membership_expired(membership, membership_expires):
            debug_log(f"Membership expired for user {username}, redirecting to membership page")
            self.membership_expired.emit()
            return

        self.email_label.setText(f"Email: {email}")
        self.username_label.setText(f"Username: {username}")
        self.membership_label.setText(f"Membership: {'Active' if membership else 'Inactive'}")

        # Referral info removed from dashboard UI

        # Update membership time remaining with real-time timer
        self.update_membership_time(membership, membership_expires)

    def open_referral_details(self):
        """Open the referral details window with referral sync and loading indicators."""
        try:
            if not self._id_token or not self._local_id:
                QMessageBox.warning(self, "Error", "User authentication required.")
                return
            
            # Show loading while syncing referral data
            if self.loading_overlay:
                self.loading_overlay.show_loading("Syncing referral data...")
            
            # Disable the referral button during loading
            self.referral_btn.setEnabled(False)
            
            debug_log(f"Starting referral sync for user: {self._local_id}, username: {self.profile.get('username', 'Unknown')}")
            
            # Start referral sync worker first
            self.referral_sync_worker = ReferralSyncWorker(self._id_token, self._local_id)
            self.referral_sync_worker.progress.connect(self.on_referral_sync_progress)
            self.referral_sync_worker.finished.connect(self.on_referral_sync_completed)
            self.referral_sync_worker.start()
            
        except Exception as e:
            # Hide loading and re-enable button on error
            if self.loading_overlay:
                self.loading_overlay.hide_loading()
            self.referral_btn.setEnabled(True)
            
            debug_log(f"Exception in open_referral_details: {e}")
            QMessageBox.critical(self, "Error", f"Failed to start referral sync: {e}")
    
    def on_referral_sync_progress(self, message: str):
        """Handle referral sync progress updates"""
        if self.loading_overlay:
            self.loading_overlay.show_loading(f"Syncing referral data... {message}")
    
    def on_referral_sync_completed(self, success: bool, result: dict):
        """Handle referral sync completion"""
        try:
            if not success:
                debug_log(f"Referral sync failed: {result}")
                # Still show referral details even if sync failed
            else:
                debug_log(f"Referral sync completed successfully: {result}")
                # Update current user data with sync results
                if hasattr(self, 'parent') and hasattr(self.parent(), 'current_user'):
                    main_window = self.parent()
                    while main_window and not hasattr(main_window, 'current_user'):
                        main_window = main_window.parent()
                    if main_window and hasattr(main_window, 'current_user'):
                        try:
                            if isinstance(result, dict) and result.get("results"):
                                main_window.current_user.update(result.get("results"))
                        except Exception as e:
                            debug_log(f"Failed to update current_user with sync results: {e}")
            
            # Now open the referral details window
            if self.loading_overlay:
                self.loading_overlay.show_loading("Loading referral details...")
            
            username = self.profile.get("username", "Unknown")
            referral_window = ReferralDetailsWindow(self._id_token, self._local_id, username, self)
            
            # Connect to window's finished signal to hide loading
            referral_window.finished.connect(self.on_referral_details_closed)
            
            referral_window.show()
            
        except Exception as e:
            # Hide loading and re-enable button on error
            if self.loading_overlay:
                self.loading_overlay.hide_loading()
            self.referral_btn.setEnabled(True)
            
            debug_log(f"Exception in on_referral_sync_completed: {e}")
            QMessageBox.critical(self, "Error", f"Failed to open referral details: {e}")
    
    def on_referral_details_closed(self):
        """Handle when referral details window is closed"""
        if self.loading_overlay:
            self.loading_overlay.hide_loading()
        self.referral_btn.setEnabled(True)
    
    def open_rewards_window(self):
        """Open the rewards window with referral data and rewards calculation"""
        try:
            if not self._id_token or not self._local_id:
                QMessageBox.warning(self, "Error", "User authentication required.")
                return
            
            username = self.profile.get("username", "Unknown")
            
            # Show loading while loading rewards data
            if self.loading_overlay:
                self.loading_overlay.show_loading("Loading rewards data...")
            
            # Disable button during loading
            self.calculate_rewards_btn.setEnabled(False)
            
            # Start worker to load referral data for rewards calculation
            from thread_workers import RewardsDataWorker
            self.rewards_worker = RewardsDataWorker(self._id_token, self._local_id)
            self.rewards_worker.progress.connect(self.on_rewards_progress)
            self.rewards_worker.finished.connect(self.on_rewards_data_loaded)
            self.rewards_worker.start()
            
        except Exception as e:
            if self.loading_overlay:
                self.loading_overlay.hide_loading()
            self.calculate_rewards_btn.setEnabled(True)
            debug_log(f"Exception in open_rewards_window: {e}")
            QMessageBox.critical(self, "Error", f"Failed to open rewards window: {e}")
    
    def on_rewards_progress(self, message: str):
        """Handle rewards data loading progress"""
        if self.loading_overlay:
            self.loading_overlay.show_loading(f"Loading rewards data... {message}")
    
    def on_rewards_data_loaded(self, success: bool, result: dict):
        """Handle when rewards data is loaded"""
        try:
            if self.loading_overlay:
                self.loading_overlay.hide_loading()
            self.calculate_rewards_btn.setEnabled(True)
            
            if not success:
                error_msg = result.get("error", "Unknown error")
                debug_log(f"Failed to load rewards data: {error_msg}")
                QMessageBox.warning(self, "Error", f"Failed to load rewards data: {error_msg}")
                return
            
            username = self.profile.get("username", "Unknown")
            
            # Open rewards window
            rewards_window = RewardsWindow(self._id_token, self._local_id, username, self)
            rewards_window.show()
            
        except Exception as e:
            debug_log(f"Exception in on_rewards_data_loaded: {e}")
            QMessageBox.critical(self, "Error", f"Failed to open rewards window: {e}")

    def check_for_updates(self):
        """Check if a new version is available"""
        try:
            # Get current app version
            from main_window import get_app_version
            current_version = get_app_version()
            
            # Get latest version from version.py
            from version import get_latest_version
            latest_version = get_latest_version()
            
            debug_log(f"Current version: {current_version}, Latest version: {latest_version}")
            
            # Compare versions
            if current_version == latest_version:
                QMessageBox.information(
                    self, 
                    "No Updates Available", 
                    "You are already updated!"
                )
            else:
                QMessageBox.information(
                    self, 
                    "Update Available", 
                    f"New update version {latest_version} is available!"
                )
        except Exception as e:
            debug_log(f"Error checking for updates: {e}")
            QMessageBox.critical(
                self, 
                "Error", 
                f"Failed to check for updates: {str(e)}"
            )
