from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QProgressBar,
    QComboBox, QSpinBox, QFileDialog, QGroupBox, QRadioButton,
    QButtonGroup, QScrollArea, QFrame, QCheckBox, QSplitter
)
from PySide6.QtCore import Qt, Signal, QObject, QSize, QRunnable, QThreadPool, QTimer, QThread
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from yt_dlp import YoutubeDL
import os
import sys
from datetime import datetime
import time
from typing import Optional, Dict, List
from downloader_core import (
    parse_multiple_urls,
    get_content_type,
    fetch_video_info,
    fetch_playlist_info,
    download_single_video_with_progress
)


class URLParsingWorker(QThread):
    """QThread worker for parsing URLs"""
    urls_parsed = Signal(list)
    error_occurred = Signal(str)
    
    def __init__(self, urls_text):
        super().__init__()
        self.urls_text = urls_text
    
    def run(self):
        try:
            urls = parse_multiple_urls(self.urls_text)
            self.urls_parsed.emit(urls)
        except Exception as e:
            self.error_occurred.emit(str(e))


class DirectoryCreationWorker(QThread):
    """QThread worker for directory operations"""
    directory_created = Signal(str)
    error_occurred = Signal(str)
    
    def __init__(self, directory_path):
        super().__init__()
        self.directory_path = directory_path
    
    def run(self):
        try:
            os.makedirs(self.directory_path, exist_ok=True)
            self.directory_created.emit(self.directory_path)
        except Exception as e:
            self.error_occurred.emit(str(e))


class ThumbnailCache:
    def __init__(self):
        self.cache = {}

    def get(self, url: str) -> Optional[QPixmap]:
        return self.cache.get(url)

    def set(self, url: str, pixmap: QPixmap):
        self.cache[url] = pixmap


class ThumbnailLoader(QObject):
    thumbnail_loaded = Signal(str, QPixmap)

    def __init__(self, cache: ThumbnailCache):
        super().__init__()
        self.cache = cache
        self.network_manager = QNetworkAccessManager()

    def load_thumbnail(self, video_id: str, url: str):
        """Load thumbnail with proper QThread handling"""
        cached = self.cache.get(url)
        if cached:
            self.thumbnail_loaded.emit(video_id, cached)
            return

        try:
            request = QNetworkRequest(url)
            reply = self.network_manager.get(request)
            reply.finished.connect(lambda: self.on_thumbnail_downloaded(video_id, url, reply))
        except Exception as e:
            print(f"Thumbnail loading error: {e}")

    def on_thumbnail_downloaded(self, video_id: str, url: str, reply: QNetworkReply):
        if reply.error() == QNetworkReply.NoError:
            data = reply.readAll()
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(120, 68, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.cache.set(url, scaled_pixmap)
                self.thumbnail_loaded.emit(video_id, scaled_pixmap)
        reply.deleteLater()


class FetchInfoWorker(QObject):
    info_fetched = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, url: str, audio_only: bool):
        super().__init__()
        self.url = url
        self.audio_only = audio_only

    def run(self):
        try:
            content_type = get_content_type(self.url)

            if content_type in ['playlist', 'channel']:
                info = fetch_playlist_info(self.url, self.audio_only)
                self.info_fetched.emit(info)
            else:
                info = fetch_video_info(self.url, self.audio_only)
                self.info_fetched.emit(info)
        except Exception as e:
            self.error_occurred.emit(str(e))

class WorkerRunnable(QRunnable):
    """Simple QRunnable wrapper that runs a QObject worker's run() method.
    We keep the worker object alive (it's referenced here) so it won't be GC'd
    while running. Signals emitted by the worker will be handled in the main thread
    as usual.
    """
    def __init__(self, worker: QObject):
        super().__init__()
        self.worker = worker

    def run(self):
        try:
            # worker.run() is expected to emit signals for results/errors
            self.worker.run()
        except Exception as e:
            # Emit error if possible
            try:
                if hasattr(self.worker, 'error_occurred'):
                    self.worker.error_occurred.emit(str(e))
            except Exception:
                pass



class VideoItemWidget(QWidget):
    def __init__(self, video_data: dict, thumbnail_loader: ThumbnailLoader):
        super().__init__()
        self.video_data = video_data
        self.thumbnail_loader = thumbnail_loader

        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(True)
        layout.addWidget(self.checkbox)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(120, 68)
        self.thumbnail_label.setStyleSheet("border: 1px solid #ccc; background: #f0f0f0;")
        self.thumbnail_label.setScaledContents(True)
        layout.addWidget(self.thumbnail_label)

        if video_data.get('thumbnail_url'):
            thumbnail_loader.thumbnail_loaded.connect(self.on_thumbnail_loaded)
            thumbnail_loader.load_thumbnail(video_data['id'], video_data['thumbnail_url'])

        info_layout = QVBoxLayout()
        title_label = QLabel(video_data['title'])
        title_label.setWordWrap(True)
        title_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(title_label)

        if video_data.get('duration'):
            duration_label = QLabel(f"Duration: {video_data['duration']}")
            duration_label.setStyleSheet("color: #666; font-size: 11px;")
            info_layout.addWidget(duration_label)

        layout.addLayout(info_layout, stretch=1)

        if video_data.get('qualities'):
            quality_label = QLabel("Quality:")
            layout.addWidget(quality_label)
            self.quality_combo = QComboBox()
            self.quality_combo.addItems(video_data['qualities'])
            self.quality_combo.setMaximumWidth(150)
            layout.addWidget(self.quality_combo)
        else:
            self.quality_combo = None

        if video_data.get('subtitles'):
            subtitle_label = QLabel("Subtitles:")
            layout.addWidget(subtitle_label)
            self.subtitle_combo = QComboBox()
            self.subtitle_combo.addItem("None")
            self.subtitle_combo.addItems(video_data['subtitles'])
            self.subtitle_combo.setMaximumWidth(100)
            layout.addWidget(self.subtitle_combo)
        else:
            self.subtitle_combo = None

    def on_thumbnail_loaded(self, video_id: str, pixmap: QPixmap):
        if video_id == self.video_data['id']:
            self.thumbnail_label.setPixmap(pixmap)

    def is_selected(self) -> bool:
        return self.checkbox.isChecked()

    def get_selected_quality(self) -> Optional[str]:
        if self.quality_combo:
            return self.quality_combo.currentText()
        return None

    def get_selected_subtitle(self) -> Optional[str]:
        if self.subtitle_combo:
            subtitle = self.subtitle_combo.currentText()
            return subtitle if subtitle != "None" else None
        return None


class DownloadItemWidget(QWidget):
    def __init__(self, title: str, item_id: str):
        super().__init__()
        self.item_id = item_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        title_layout = QHBoxLayout()
        self.status_label = QLabel("⏳")
        title_layout.addWidget(self.status_label)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-weight: bold;")
        title_layout.addWidget(self.title_label, stretch=1)

        self.progress_text = QLabel("0%")
        self.progress_text.setMinimumWidth(50)
        title_layout.addWidget(self.progress_text)

        layout.addLayout(title_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_text = QLabel("Waiting...")
        self.status_text.setStyleSheet("color: #666; font-size: 10px;")
        layout.addWidget(self.status_text)

    def update_progress(self, percentage: float, status: str = ""):
        self.progress_bar.setValue(int(percentage))
        self.progress_text.setText(f"{int(percentage)}%")
        if status:
            self.status_text.setText(status)

    def set_status(self, status: str, icon: str = ""):
        if icon:
            self.status_label.setText(icon)
        self.status_text.setText(status)

    def set_queued(self):
        self.status_label.setText("⏳")
        self.set_status("Queued...")

    def set_downloading(self):
        self.status_label.setText("⬇️")
        self.set_status("Downloading...")

    def set_completed(self):
        self.status_label.setText("✅")
        self.progress_bar.setValue(100)
        self.progress_text.setText("100%")
        self.set_status("Completed")

    def set_failed(self, error: str):
        self.status_label.setText("❌")
        self.set_status(f"Failed: {error}")

    def set_paused(self):
        self.status_label.setText("⏸️")
        self.set_status("Paused")


class DownloadWorker(QObject):
    progress = Signal(str, float, str)
    finished = Signal(str, dict)
    progress_display = Signal(str, str, float, str, str, str)  # item_id, filename, percent, speed, eta, progress_msg

    def __init__(self, item_id: str, video_data: dict, output_path: str, quality: str, subtitle: str, audio_only: bool):
        super().__init__()
        self.item_id = item_id
        self.video_data = video_data
        self.output_path = output_path
        self.quality = quality
        self.subtitle = subtitle
        self.audio_only = audio_only
        self._is_running = True
        self._is_paused = False
        
        # Track download stages
        self.download_stage = "starting"  # starting, video_download, audio_download, merging, completed
        self.stage_progress = 0.0  # 0-100 for current stage
        self.overall_progress = 0.0  # 0-100 overall
        self.current_format = ""
        self.total_formats = 0
        self.completed_formats = 0
        self.last_progress_update = 0  # For throttling console output

    def run(self):
        if not self._is_running:
            return

        def progress_hook(d):
            if not self._is_running:
                raise Exception("Download cancelled")

            while self._is_paused:
                if not self._is_running:
                    raise Exception("Download cancelled")
                time.sleep(0.1)

            status = d.get('status', '')
            filename = d.get('filename', 'Unknown')
            if filename:
                filename = os.path.basename(filename)

            # Handle different download stages
            if status == 'downloading':
                import re
                # Strip ANSI color codes from percentage string
                percent_raw = d.get('_percent_str', '0%')
                percent = re.sub(r'\x1b\[[0-9;]*m', '', percent_raw).replace('%', '').strip()
                try:
                    percent_float = float(percent)
                    # Strip ANSI codes from speed and ETA strings
                    speed_raw = d.get('_speed_str', 'N/A')
                    eta_raw = d.get('_eta_str', 'N/A')
                    speed = re.sub(r'\x1b\[[0-9;]*m', '', speed_raw) if speed_raw != 'N/A' else 'N/A'
                    eta = re.sub(r'\x1b\[[0-9;]*m', '', eta_raw) if eta_raw != 'N/A' else 'N/A'
                    
                    # Extract file size information
                    total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded_bytes = d.get('downloaded_bytes', 0)
                    
                    # Format file size
                    if total_bytes > 0:
                        if total_bytes >= 1024 * 1024 * 1024:  # GB
                            total_size = f"{total_bytes / (1024 * 1024 * 1024):.2f}GiB"
                        elif total_bytes >= 1024 * 1024:  # MB
                            total_size = f"{total_bytes / (1024 * 1024):.2f}MiB"
                        elif total_bytes >= 1024:  # KB
                            total_size = f"{total_bytes / 1024:.2f}KiB"
                        else:
                            total_size = f"{total_bytes}B"
                    else:
                        total_size = "Unknown"
                    
                    # Determine download stage based on filename
                    if '.f' in filename and '.mp4' in filename:
                        self.download_stage = "video_download"
                        self.current_format = "Video"
                    elif '.f' in filename and ('.webm' in filename or '.m4a' in filename):
                        self.download_stage = "audio_download"
                        self.current_format = "Audio"
                    else:
                        self.download_stage = "downloading"
                        self.current_format = "Format"
                    
                    # Calculate overall progress based on stage
                    if self.download_stage == "video_download":
                        self.overall_progress = percent_float * 0.5  # First 50% for video
                    elif self.download_stage == "audio_download":
                        self.overall_progress = 50 + (percent_float * 0.4)  # Next 40% for audio
                    else:
                        self.overall_progress = percent_float
                    
                    # Format speed and ETA
                    formatted_speed = speed if speed and speed != 'N/A' else "Unknown"
                    formatted_eta = eta if eta and eta != 'N/A' else "Unknown"
                    
                    # Create user-friendly progress message
                    stage_msg = f"Downloading {self.current_format}"
                    progress_msg = f"[download] {percent_float:.1f}% of {total_size} at {formatted_speed} ETA {formatted_eta}"
                    
                    status_text = f"{stage_msg} - {formatted_speed} | ETA: {formatted_eta}"
                    
                    # Emit progress updates for live updates
                    self.progress.emit(self.item_id, self.overall_progress, status_text)
                    
                    # Throttle console output to avoid spam, but keep progress bar live
                    import time
                    current_time = time.time()
                    if current_time - self.last_progress_update >= 0.5:  # Update console every 0.5 seconds
                        self.progress_display.emit(self.item_id, filename, self.overall_progress, formatted_speed, formatted_eta, progress_msg)
                        self.last_progress_update = current_time
                        print(f"DEBUG: Progress update - {self.item_id}: {self.overall_progress:.1f}%")
                    
                    # Force immediate UI update
                    QApplication.processEvents()
                    
                except Exception as e:
                    print(f"Progress hook error: {e}")
                    pass
                    
            elif status == 'finished':
                # Handle completed downloads
                if 'merger' in d.get('info_dict', {}).get('_filename', '').lower() or 'merging' in str(d):
                    self.download_stage = "merging"
                    self.overall_progress = 90
                    progress_msg = "[Merger] Merging formats..."
                    status_text = "Merging video and audio formats"
                    self.progress.emit(self.item_id, self.overall_progress, status_text)
                    self.progress_display.emit(self.item_id, filename, self.overall_progress, "N/A", "N/A", progress_msg)
                else:
                    # Format download completed
                    self.completed_formats += 1
                    if self.download_stage == "video_download":
                        self.overall_progress = 50
                    elif self.download_stage == "audio_download":
                        self.overall_progress = 90
                    
                    progress_msg = f"[download] 100% of format completed"
                    status_text = f"{self.current_format} download completed"
                    self.progress.emit(self.item_id, self.overall_progress, status_text)
                    self.progress_display.emit(self.item_id, filename, self.overall_progress, "N/A", "N/A", progress_msg)

        try:
            result = download_single_video_with_progress(
                self.video_data['url'],
                self.output_path,
                self.quality,
                self.subtitle,
                self.audio_only,
                progress_hook
            )
            
            # Set final progress to 100% on completion
            if result.get('success', False):
                self.download_stage = "completed"
                self.overall_progress = 100.0
                progress_msg = "[download] 100% - Download completed successfully!"
                status_text = "Download completed"
                self.progress.emit(self.item_id, self.overall_progress, status_text)
                self.progress_display.emit(self.item_id, "Final", self.overall_progress, "N/A", "N/A", progress_msg)
            
            self.finished.emit(self.item_id, result)
        except Exception as e:
            self.finished.emit(self.item_id, {
                'success': False,
                'message': str(e)
            })

    def pause(self):
        self._is_paused = True

    def resume(self):
        self._is_paused = False

    def stop(self):
        self._is_running = False


class YouTubeDownloaderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.threads = []
        self.workers = {}
        # thread pool for running background tasks (fetch/download)
        self.thread_pool = QThreadPool.globalInstance()
        # Set maximum thread count to match our concurrent download limit
        self.thread_pool.setMaxThreadCount(2)
        self.download_widgets = {}
        self.video_items = []
        self.fetched_videos = []
        self.active_downloads = 0
        self.completed_downloads = 0
        self.failed_downloads = 0
        self.output_directory = os.path.join(os.getcwd(), 'downloads')
        self.thumbnail_cache = ThumbnailCache()
        self.thumbnail_loader = ThumbnailLoader(self.thumbnail_cache)
        self.is_paused = False
        
        # Download queue management
        self.download_queue = []
        self.max_concurrent_downloads = 1
        self.current_downloads = 0
        
        # Timer for smooth progress updates
        self.progress_timer = QTimer()
        self.progress_timer.timeout.connect(self.update_progress_bars)
        self.progress_timer.start(100)  # Update every 100ms

        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("YouTube Multi-Content Downloader Pro")
        self.setMinimumSize(1100, 800)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create main scroll area for entire content
        main_scroll = QScrollArea()
        main_scroll.setWidgetResizable(True)
        main_scroll.setFrameShape(QFrame.NoFrame)
        
        # Container widget for scrollable content
        scroll_container = QWidget()
        main_layout = QVBoxLayout(scroll_container)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Set scroll area widget
        main_scroll.setWidget(scroll_container)
        
        # Add scroll area to central widget
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.addWidget(main_scroll)

        title_label = QLabel("📥 YouTube Multi-Content Downloader Pro")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        url_group = QGroupBox("URLs Input")
        url_layout = QVBoxLayout()

        info_label = QLabel(
            "💡 Supported: Single videos, Shorts, Playlists, Channels\n"
            "📝 Enter URLs (one per line or separated by commas/spaces)"
        )
        info_label.setStyleSheet("color: #666; font-size: 11px;")
        url_layout.addWidget(info_label)

        self.url_input = QTextEdit()
        self.url_input.setPlaceholderText(
            "Enter YouTube URLs here...\n\n"
            "Examples:\n"
            "https://www.youtube.com/watch?v=...\n"
            "https://www.youtube.com/shorts/...\n"
            "https://www.youtube.com/playlist?list=...\n"
            "https://www.youtube.com/@channelname"
        )
        self.url_input.setMaximumHeight(100)
        url_layout.addWidget(self.url_input)

        # Format selection above fetch button
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Format:"))
        self.format_group = QButtonGroup()
        self.mp4_radio = QRadioButton("🎥 MP4 Video")
        self.mp3_radio = QRadioButton("🎵 MP3 Audio Only")
        self.mp4_radio.setChecked(True)
        self.format_group.addButton(self.mp4_radio)
        self.format_group.addButton(self.mp3_radio)
        format_layout.addWidget(self.mp4_radio)
        format_layout.addWidget(self.mp3_radio)
        format_layout.addStretch()
        url_layout.addLayout(format_layout)

        fetch_button_layout = QHBoxLayout()
        self.fetch_info_button = QPushButton("🔍 Fetch Info")
        self.fetch_info_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                padding: 8px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #0b7dda;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        self.fetch_info_button.clicked.connect(self.fetch_info)
        fetch_button_layout.addWidget(self.fetch_info_button)
        fetch_button_layout.addStretch()
        url_layout.addLayout(fetch_button_layout)

        url_group.setLayout(url_layout)
        main_layout.addWidget(url_group)

        self.video_list_group = QGroupBox("Video Selection")
        video_list_layout = QVBoxLayout()

        select_all_layout = QHBoxLayout()
        self.select_all_checkbox = QCheckBox("Select All")
        self.select_all_checkbox.setChecked(True)
        self.select_all_checkbox.stateChanged.connect(self.toggle_select_all)
        select_all_layout.addWidget(self.select_all_checkbox)
        select_all_layout.addStretch()
        video_list_layout.addLayout(select_all_layout)

        self.video_scroll_area = QScrollArea()
        self.video_scroll_area.setWidgetResizable(True)
        self.video_scroll_area.setMinimumHeight(150)
        self.video_scroll_area.setMaximumHeight(250)

        self.video_list_widget = QWidget()
        self.video_list_layout = QVBoxLayout(self.video_list_widget)
        self.video_list_layout.setAlignment(Qt.AlignTop)
        self.video_scroll_area.setWidget(self.video_list_widget)

        video_list_layout.addWidget(self.video_scroll_area)
        self.video_list_group.setLayout(video_list_layout)
        self.video_list_group.setVisible(False)
        main_layout.addWidget(self.video_list_group)

        # Create a horizontal layout for settings and status
        settings_status_layout = QHBoxLayout()
        
        # Download Settings Group
        settings_group = QGroupBox("Download Settings")
        settings_layout = QVBoxLayout()

        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("Output Directory:"))
        self.output_path_input = QLineEdit(self.output_directory)
        self.output_path_input.setReadOnly(True)
        output_layout.addWidget(self.output_path_input)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.setMaximumWidth(100)
        self.browse_button.clicked.connect(self.browse_output_directory)
        output_layout.addWidget(self.browse_button)
        settings_layout.addLayout(output_layout)

        workers_layout = QHBoxLayout()
        workers_layout.addWidget(QLabel("Concurrent Downloads:"))
        self.workers_spinbox = QSpinBox()
        self.workers_spinbox.setMinimum(1)
        self.workers_spinbox.setMaximum(2)
        self.workers_spinbox.setValue(1)
        self.workers_spinbox.setMaximumWidth(80)
        workers_layout.addWidget(self.workers_spinbox)
        workers_layout.addStretch()
        settings_layout.addLayout(workers_layout)
        
        # Connect spinbox to update max concurrent downloads
        self.workers_spinbox.valueChanged.connect(self.update_max_concurrent_downloads)

        settings_group.setLayout(settings_layout)
        main_layout.addWidget(settings_group)

        # Enhanced progress display - moved below settings
        progress_group = QGroupBox("Download Progress")
        progress_layout = QVBoxLayout()
        
        self.progress_output = QTextEdit()
        self.progress_output.setReadOnly(True)
        self.progress_output.setMaximumHeight(120)
        self.progress_output.setStyleSheet("""
            QTextEdit {
                background-color: #0d1117;
                color: #58a6ff;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11px;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        progress_layout.addWidget(self.progress_output)
        
        progress_group.setLayout(progress_layout)
        main_layout.addWidget(progress_group)

        button_layout = QHBoxLayout()
        self.download_button = QPushButton("🚀 Start Download")
        self.download_button.setMinimumHeight(45)
        self.download_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        self.download_button.clicked.connect(self.start_download)
        button_layout.addWidget(self.download_button)

        self.pause_button = QPushButton("⏸ Pause")
        self.pause_button.setMinimumHeight(45)
        self.pause_button.setEnabled(False)
        self.pause_button.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #e68900;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        self.pause_button.clicked.connect(self.toggle_pause)
        button_layout.addWidget(self.pause_button)

        self.cancel_button = QPushButton("❌ Cancel All")
        self.cancel_button.setMinimumHeight(45)
        self.cancel_button.setEnabled(False)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        self.cancel_button.clicked.connect(self.cancel_downloads)
        button_layout.addWidget(self.cancel_button)

        main_layout.addLayout(button_layout)

        # Download Status Group
        status_group = QGroupBox("Download Status")
        status_layout = QVBoxLayout()

        stats_layout = QHBoxLayout()
        self.active_label = QLabel("Active: 0")
        self.completed_label = QLabel("✅ Completed: 0")
        self.failed_label = QLabel("❌ Failed: 0")
        stats_layout.addWidget(self.active_label)
        stats_layout.addWidget(self.completed_label)
        stats_layout.addWidget(self.failed_label)
        stats_layout.addStretch()
        status_layout.addLayout(stats_layout)

        self.overall_progress = QProgressBar()
        self.overall_progress.setMaximum(100)
        self.overall_progress.setValue(0)
        status_layout.addWidget(self.overall_progress)

        self.download_items_scroll = QScrollArea()
        self.download_items_scroll.setWidgetResizable(True)
        self.download_items_scroll.setMinimumHeight(150)
        self.download_items_scroll.setMaximumHeight(200)

        self.download_items_widget = QWidget()
        self.download_items_layout = QVBoxLayout(self.download_items_widget)
        self.download_items_layout.setAlignment(Qt.AlignTop)
        self.download_items_scroll.setWidget(self.download_items_widget)

        status_layout.addWidget(self.download_items_scroll)

        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)

        self.log_message("Welcome to YouTube Multi-Content Downloader Pro!")
        self.log_message("Click 'Fetch Info' to preview videos before downloading.")

    def update_max_concurrent_downloads(self, value):
        """Update maximum concurrent downloads when spinbox value changes"""
        self.max_concurrent_downloads = value
        self.thread_pool.setMaxThreadCount(value)
        self.log_message(f"🔧 Max concurrent downloads set to: {value}")

    def browse_output_directory(self):
        """Browse for output directory using QThread for GUI sustainability"""
        # File dialog operations are already GUI-safe in Qt
        # But we can still use QThread for any additional processing
        try:
            directory = QFileDialog.getExistingDirectory(
                self,
                "Select Output Directory",
                self.output_directory
            )
            if directory:
                self.output_directory = directory
                self.output_path_input.setText(directory)
                self.log_message(f"📁 Output directory set to: {directory}")
        except Exception as e:
            self.log_message(f"❌ Error browsing directory: {e}")

    def log_message(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Filter out YouTube extraction messages and only show download progress
        if any(keyword in message.lower() for keyword in [
            'extracting url', 'downloading webpage', 'downloading tv client config',
            'downloading tv player api json', 'downloading web safari player api json',
            'downloading m3u8 information', 'downloading 1 format', 'has already been downloaded'
        ]):
            return  # Skip these messages
        
        # Show only download progress and important messages
        if any(keyword in message.lower() for keyword in [
            'download', 'progress', 'completed', 'failed', 'error', 'success'
        ]) or message.startswith('[') and '%' in message:
            self.progress_output.append(f"[{timestamp}] {message}")
            self.progress_output.verticalScrollBar().setValue(
                self.progress_output.verticalScrollBar().maximum()
            )

    def show_download_progress(self, item_id: str, filename: str, percent: float, speed: str, eta: str, progress_msg: str):
        """Display beautiful download progress in the progress output"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Format the progress message beautifully
        if percent >= 100:
            progress_display = f"✅ [{timestamp}] Download completed successfully!"
        elif "merging" in progress_msg.lower() or "merger" in progress_msg.lower():
            progress_display = f"🔧 [{timestamp}] {progress_msg}"
        elif "100%" in progress_msg:
            progress_display = f"📦 [{timestamp}] {progress_msg}"
        else:
            progress_display = f"⬇️ [{timestamp}] {progress_msg}"
        
        self.progress_output.append(progress_display)
        self.progress_output.verticalScrollBar().setValue(
            self.progress_output.verticalScrollBar().maximum()
        )

    def update_progress_bars(self):
        """Update progress bars smoothly"""
        try:
            # Force UI updates for all active downloads
            for item_id, widget in self.download_widgets.items():
                if hasattr(widget, 'progress_bar'):
                    widget.progress_bar.repaint()
                    widget.progress_text.repaint()
                    widget.status_text.repaint()
        except Exception as e:
            pass  # Ignore errors in timer updates

    def update_stats(self):
        self.active_label.setText(f"Active: {self.active_downloads}")
        self.completed_label.setText(f"✅ Completed: {self.completed_downloads}")
        self.failed_label.setText(f"❌ Failed: {self.failed_downloads}")

        total = self.completed_downloads + self.failed_downloads + self.active_downloads
        if total > 0:
            progress = int((self.completed_downloads + self.failed_downloads) / total * 100)
            self.overall_progress.setValue(progress)

    def toggle_select_all(self, state):
        for item_widget in self.video_items:
            item_widget.checkbox.setChecked(state == Qt.Checked)

    def fetch_info(self):
        """Fetch video info using QThread for GUI sustainability"""
        urls_text = self.url_input.toPlainText().strip()

        if not urls_text:
            self.log_message("❌ Error: No URLs entered!")
            return

        # Disable button immediately
        self.fetch_info_button.setEnabled(False)
        self.fetch_info_button.setText("⏳ Parsing URLs...")

        # Create and start URL parsing worker
        self.url_worker = URLParsingWorker(urls_text)
        self.url_worker.urls_parsed.connect(self.on_urls_parsed)
        self.url_worker.error_occurred.connect(self.on_url_parsing_error)
        self.url_worker.finished.connect(self.url_worker.deleteLater)
        self.url_worker.start()

    def on_urls_parsed(self, urls):
        """Handle parsed URLs"""
        if not urls:
            self.log_message("❌ Error: No valid YouTube URLs found!")
            self.fetch_info_button.setEnabled(True)
            self.fetch_info_button.setText("🔍 Fetch Info")
            return

        self.log_message(f"🔍 Fetching info for {len(urls)} URL(s)...")
        self.fetch_info_button.setText("⏳ Fetching...")

        # Clear existing widgets
        while self.video_list_layout.count():
            child = self.video_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self.video_items.clear()
        self.fetched_videos.clear()

        audio_only = self.mp3_radio.isChecked()

        # Start fetch workers
        for url in urls:
            worker = FetchInfoWorker(url, audio_only)
            worker.info_fetched.connect(self.on_info_fetched)
            worker.error_occurred.connect(self.on_fetch_error)
            worker.info_fetched.connect(worker.deleteLater)
            worker.error_occurred.connect(worker.deleteLater)
            runnable = WorkerRunnable(worker)
            self.thread_pool.start(runnable)

    def on_url_parsing_error(self, error):
        """Handle URL parsing error"""
        self.log_message(f"❌ Error parsing URLs: {error}")
        self.fetch_info_button.setEnabled(True)
        self.fetch_info_button.setText("🔍 Fetch Info")


    def on_info_fetched(self, info: dict):
        if info.get('type') == 'video':
            video_item = VideoItemWidget(info, self.thumbnail_loader)
            self.video_list_layout.addWidget(video_item)
            self.video_items.append(video_item)
            self.fetched_videos.append(info)
            self.log_message(f"✅ Fetched: {info['title']}")

        elif info.get('type') in ['playlist', 'channel']:
            videos = info.get('videos', [])
            self.log_message(f"✅ Fetched {info['type']}: {info.get('title', 'Unknown')} ({len(videos)} videos)")

            for video in videos:
                video_item = VideoItemWidget(video, self.thumbnail_loader)
                self.video_list_layout.addWidget(video_item)
                self.video_items.append(video_item)
                self.fetched_videos.append(video)

        self.video_list_group.setVisible(True)
        self.fetch_info_button.setEnabled(True)
        self.fetch_info_button.setText("🔍 Fetch Info")

    def on_fetch_error(self, error: str):
        self.log_message(f"❌ Fetch error: {error}")
        self.fetch_info_button.setEnabled(True)
        self.fetch_info_button.setText("🔍 Fetch Info")

    def start_download(self):
        """Start download process using QThread for GUI sustainability"""
        if not self.fetched_videos:
            self.log_message("❌ Please fetch video info first!")
            return

        selected_videos = []
        for i, item_widget in enumerate(self.video_items):
            if item_widget.is_selected():
                video_data = self.fetched_videos[i].copy()
                video_data['selected_quality'] = item_widget.get_selected_quality()
                video_data['selected_subtitle'] = item_widget.get_selected_subtitle()
                selected_videos.append(video_data)

        if not selected_videos:
            self.log_message("❌ No videos selected!")
            return

        self.log_message(f"\n{'='*60}")
        self.log_message(f"🚀 Starting download of {len(selected_videos)} video(s)")
        self.log_message(f"📁 Output: {self.output_directory}")

        # Disable buttons immediately
        self.download_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.fetch_info_button.setEnabled(False)
        
        # Hide video selection section to free up space
        self.video_list_group.setVisible(False)

        # Store selected videos for later use
        self.pending_selected_videos = selected_videos

        # Create directory creation worker
        self.dir_worker = DirectoryCreationWorker(self.output_directory)
        self.dir_worker.directory_created.connect(self.on_directory_created)
        self.dir_worker.error_occurred.connect(self.on_directory_error)
        self.dir_worker.finished.connect(self.dir_worker.deleteLater)
        self.dir_worker.start()

    def on_directory_created(self, directory_path):
        """Handle directory creation completion"""
        try:
            # Clear existing widgets
            while self.download_items_layout.count():
                child = self.download_items_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

            self.download_widgets.clear()
            self.workers.clear()
            self.threads.clear()

            self.active_downloads = len(self.pending_selected_videos)
            self.completed_downloads = 0
            self.failed_downloads = 0
            self.current_downloads = 0
            self.update_stats()

            audio_only = self.mp3_radio.isChecked()

            # Create download queue instead of starting all at once
            self.download_queue = []
            for video in self.pending_selected_videos:
                item_id = video['id']
                download_widget = DownloadItemWidget(video['title'], item_id)
                self.download_items_layout.addWidget(download_widget)
                self.download_widgets[item_id] = download_widget
                
                # Add to queue with status
                download_widget.set_queued()
                self.download_queue.append({
                    'item_id': item_id,
                    'video': video,
                    'download_widget': download_widget
                })

            # Start initial downloads (up to max_concurrent_downloads)
            self.log_message(f"📋 Queue created with {len(self.download_queue)} items")
            self.log_message(f"🔧 Max concurrent downloads: {self.max_concurrent_downloads}")
            self.start_next_downloads()
                
        except Exception as e:
            self.log_message(f"❌ Error setting up downloads: {e}")
            self.reset_download_buttons()

    def start_next_downloads(self):
        """Start next downloads from queue up to max_concurrent_downloads"""
        # Don't start new downloads if paused
        if self.is_paused:
            self.log_message("⏸ Queue is paused - not starting new downloads")
            return
            
        self.log_message(f"🔄 Starting downloads: current={self.current_downloads}, max={self.max_concurrent_downloads}, queue={len(self.download_queue)}")
        
        while (self.current_downloads < self.max_concurrent_downloads and 
               len(self.download_queue) > 0 and 
               not self.is_paused):  # Check pause status in loop
            
            # Get next item from queue
            queue_item = self.download_queue.pop(0)
            item_id = queue_item['item_id']
            video = queue_item['video']
            download_widget = queue_item['download_widget']
            
            # Start download
            audio_only = self.mp3_radio.isChecked()
            worker = DownloadWorker(
                item_id,
                video,
                self.output_directory,
                video.get('selected_quality'),
                video.get('selected_subtitle'),
                audio_only
            )
            worker.progress.connect(self.on_download_progress)
            worker.progress_display.connect(self.show_download_progress)
            worker.finished.connect(self.on_download_finished)
            worker.finished.connect(worker.deleteLater)
            
            # Keep worker reference for pause/cancel control
            self.workers[item_id] = worker
            runnable = WorkerRunnable(worker)
            self.thread_pool.start(runnable)
            
            # Update status
            download_widget.set_downloading()
            self.current_downloads += 1
            
            self.log_message(f"🚀 Started download {self.current_downloads}/{self.max_concurrent_downloads}: {video['title'][:50]}...")
        
        if len(self.download_queue) > 0 and not self.is_paused:
            self.log_message(f"⏳ {len(self.download_queue)} downloads queued, waiting for slots...")
        elif len(self.download_queue) > 0 and self.is_paused:
            self.log_message(f"⏸ {len(self.download_queue)} downloads queued and paused")

    def on_directory_error(self, error):
        """Handle directory creation error"""
        self.log_message(f"❌ Error creating directory: {error}")
        self.reset_download_buttons()

    def reset_download_buttons(self):
        """Reset download buttons"""
        self.download_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.fetch_info_button.setEnabled(True)
        self.video_list_group.setVisible(True)

    def on_download_progress(self, item_id: str, percent: float, status: str):
        """Update progress bar for a single download item."""
        try:
            print(f"DEBUG: on_download_progress called - {item_id}: {percent:.1f}%")
            if item_id in self.download_widgets:
                item_widget = self.download_widgets[item_id]
                if hasattr(item_widget, 'progress_bar'):
                    item_widget.progress_bar.setValue(int(percent))
                    item_widget.progress_text.setText(f"{int(percent)}%")
                    item_widget.status_text.setText(status)
                    print(f"DEBUG: Progress bar updated - {item_id}: {percent:.1f}%")
                    
                    # Force immediate UI update
                    QApplication.processEvents()
        except Exception as e:
            print(f"Progress update error: {e}")
    def on_download_finished(self, item_id: str, result: dict):
        # Decrease current downloads and active downloads
        self.current_downloads -= 1
        self.active_downloads -= 1

        if item_id in self.download_widgets:
            if result['success']:
                self.completed_downloads += 1
                self.download_widgets[item_id].set_completed()
                self.log_message(f"✅ {result.get('message', 'Download completed')}")
            else:
                self.failed_downloads += 1
                self.download_widgets[item_id].set_failed(result.get('message', 'Unknown error'))
                self.log_message(f"❌ {result.get('message', 'Download failed')} - Skipping to next video")

        # Remove worker reference
        if item_id in self.workers:
            del self.workers[item_id]

        # Start next download from queue if available and not paused
        if len(self.download_queue) > 0 and not self.is_paused:
            self.log_message(f"🔄 Download slot freed, starting next from queue...")
            self.start_next_downloads()
        elif len(self.download_queue) > 0 and self.is_paused:
            self.log_message(f"⏸ Download slot freed, but queue is paused - {len(self.download_queue)} downloads remain queued")

        self.update_stats()

        # Only call all_downloads_finished if no active downloads AND no queued downloads
        if self.active_downloads == 0 and len(self.download_queue) == 0:
            self.all_downloads_finished()
        elif self.active_downloads == 0 and len(self.download_queue) > 0 and self.is_paused:
            self.log_message(f"⏸ All active downloads completed, but {len(self.download_queue)} downloads remain paused in queue")

    def all_downloads_finished(self):
        """Handle download completion"""
        self.log_message(f"\n{'='*60}")
        self.log_message("📊 DOWNLOAD SUMMARY")
        self.log_message(f"{'='*60}")
        self.log_message(f"✅ Successful: {self.completed_downloads}")
        self.log_message(f"❌ Failed: {self.failed_downloads}")

        if self.completed_downloads > 0:
            self.log_message(f"\n🎉 Files saved to: {self.output_directory}")

        self.log_message(f"{'='*60}\n")

        # Reset UI elements
        self.download_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.fetch_info_button.setEnabled(True)
        self.is_paused = False
        self.pause_button.setText("⏸ Pause")
        
        # Clear download queue
        self.download_queue.clear()
        
        # Show video selection section again
        self.video_list_group.setVisible(True)

    def toggle_pause(self):
        self.is_paused = not self.is_paused

        if self.is_paused:
            self.pause_button.setText("▶️ Resume")
            self.log_message("⏸ Downloads paused - current downloads will complete, queue paused")
            
            # Pause only the workers that are currently downloading
            for worker in self.workers.values():
                worker.pause()
                
            # Update UI for downloading items to show paused status
            for item_id, widget in self.download_widgets.items():
                if widget.status_label.text() == "⬇️":
                    widget.set_paused()
                    
            # Don't start new downloads from queue while paused
            self.log_message("⏳ Queue paused - remaining downloads will stay queued until resume")
            
        else:
            self.pause_button.setText("⏸ Pause")
            self.log_message("▶️ Downloads resumed")
            
            # Resume workers that are currently paused
            for worker in self.workers.values():
                worker.resume()
                
            # Update UI for paused items back to downloading
            for item_id, widget in self.download_widgets.items():
                if widget.status_label.text() == "⏸️":
                    widget.set_downloading()
                    
            # Resume queue processing - start next downloads if slots are available
            if len(self.download_queue) > 0:
                self.log_message("🔄 Resuming queue processing...")
                self.start_next_downloads()

    def cancel_downloads(self):
        self.log_message("\n❌ Cancelling all downloads...")

        for worker in self.workers.values():
            worker.stop()

        # Clear download queue and reset pause state
        self.download_queue.clear()
        self.is_paused = False
        self.pause_button.setText("⏸ Pause")

        self.update_stats()
        self.all_downloads_finished()

        self.log_message("❌ All downloads cancelled.\n")


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    window = YouTubeDownloaderGUI()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()