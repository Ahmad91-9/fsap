from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit, QPushButton, QLabel,
    QProgressBar, QComboBox, QSpinBox, QFileDialog, QGroupBox, QRadioButton,
    QButtonGroup, QScrollArea, QFrame, QCheckBox
)
from PySide6.QtCore import Qt, Signal, QObject, QThreadPool, QTimer, QRunnable
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt, Signal, QObject, QThreadPool, QTimer, QRunnable
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from datetime import datetime
import os
import time
from typing import Optional, List

from downloader_core import (
    parse_multiple_urls_for_hosts,
    fetch_generic_info,
    fetch_generic_playlist_info,
    download_single_video_with_progress,
)


class _ThumbnailCache:
    def __init__(self):
        self.cache = {}
    def get(self, url: str) -> Optional[QPixmap]:
        return self.cache.get(url)
    def set(self, url: str, pixmap: QPixmap):
        self.cache[url] = pixmap


class _ThumbnailLoader(QObject):
    thumbnail_loaded = Signal(str, QPixmap)
    def __init__(self, cache: _ThumbnailCache):
        super().__init__()
        self.cache = cache
        self.network_manager = QNetworkAccessManager()
    def load_thumbnail(self, video_id: str, url: str):
        cached = self.cache.get(url)
        if cached:
            self.thumbnail_loaded.emit(video_id, cached)
            return
        try:
            request = QNetworkRequest(url)
            reply = self.network_manager.get(request)
            reply.finished.connect(lambda: self._on_downloaded(video_id, url, reply))
        except Exception:
            pass
    def _on_downloaded(self, video_id: str, url: str, reply: QNetworkReply):
        if reply.error() == QNetworkReply.NetworkError.NoError:
            data = reply.readAll()
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            if not pixmap.isNull():
                scaled = pixmap.scaled(120, 68, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.cache.set(url, scaled)
                self.thumbnail_loaded.emit(video_id, scaled)
        reply.deleteLater()


class _WorkerRunnable(QRunnable):
    def __init__(self, worker: QObject):
        super().__init__()
        self.worker = worker
    def run(self):
        try:
            if hasattr(self.worker, "run"):
                getattr(self.worker, "run")()
        except Exception:
            try:
                if hasattr(self.worker, "error_occurred"):
                    if hasattr(self.worker, 'error_occurred'):
                        getattr(self.worker, 'error_occurred').emit("Worker error")
            except Exception:
                pass


class _VideoItem(QWidget):
    def __init__(self, video_data: dict, loader: _ThumbnailLoader):
        super().__init__()
        self.data = video_data
        row = QHBoxLayout(self)
        row.setContentsMargins(5, 5, 5, 5)
        self.chk = QCheckBox()
        self.chk.setChecked(True)
        row.addWidget(self.chk)
        self.thumb = QLabel()
        self.thumb.setFixedSize(120, 68)
        self.thumb.setStyleSheet("border: 1px solid #ccc; background: #f0f0f0;")
        self.thumb.setScaledContents(True)
        row.addWidget(self.thumb)
        if video_data.get('thumbnail_url'):
            loader.thumbnail_loaded.connect(self._on_thumb)
            loader.load_thumbnail(video_data['id'], video_data['thumbnail_url'])
        info = QVBoxLayout()
        title = QLabel(video_data.get('title', 'Unknown'))
        title.setWordWrap(True)
        title.setStyleSheet("font-weight: bold;")
        info.addWidget(title)
        if video_data.get('duration'):
            d = QLabel(f"Duration: {video_data['duration']}")
            d.setStyleSheet("color: #666; font-size: 11px;")
            info.addWidget(d)
        
        # Add format selection radio buttons
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Download as:"))
        self.format_group = QButtonGroup()
        self.mp4_radio = QRadioButton("🎥 MP4")
        self.mp3_radio = QRadioButton("🎵 MP3")
        self.image_radio = QRadioButton("🖼️ Image")
        self.format_group.addButton(self.mp4_radio, 0)
        self.format_group.addButton(self.mp3_radio, 1)
        self.format_group.addButton(self.image_radio, 2)
        self.mp4_radio.setChecked(True)  # Default to MP4
        format_layout.addWidget(self.mp4_radio)
        format_layout.addWidget(self.mp3_radio)
        format_layout.addWidget(self.image_radio)
        info.addLayout(format_layout)
        
        row.addLayout(info, 1)
        
        # Quality selection (will be updated based on format)
        self.quality_label = QLabel("Quality:")
        row.addWidget(self.quality_label)
        self.quality = QComboBox()
        self.quality.addItems(video_data.get('qualities', ['Best Available']))
        self.quality.setMaximumWidth(150)
        row.addWidget(self.quality)
        
        if video_data.get('subtitles'):
            row.addWidget(QLabel("Subtitles:"))
            self.subtitle = QComboBox()
            self.subtitle.addItem("None")
            self.subtitle.addItems(video_data['subtitles'])
            self.subtitle.setMaximumWidth(100)
            row.addWidget(self.subtitle)
        else:
            self.subtitle = None
        
        # Connect radio buttons to update quality options
        self.format_group.buttonClicked.connect(self._on_format_changed)
    def _on_thumb(self, vid: str, pm: QPixmap):
        if vid == self.data['id']:
            self.thumb.setPixmap(pm)
    def is_selected(self) -> bool:
        return self.chk.isChecked()
    def selected_quality(self) -> Optional[str]:
        return self.quality.currentText() if self.quality else None
    
    def selected_format(self) -> str:
        if self.mp4_radio.isChecked():
            return 'mp4'
        elif self.mp3_radio.isChecked():
            return 'mp3'
        elif self.image_radio.isChecked():
            return 'image'
        return 'mp4'  # Default
    
    def _on_format_changed(self, button):
        """Update quality options based on selected format"""
        if self.mp3_radio.isChecked():
            # Update to MP3 qualities
            self.quality.clear()
            self.quality.addItems(['320 kbps', '192 kbps', '128 kbps', 'Best Audio'])
        elif self.mp4_radio.isChecked():
            # Update to MP4 qualities
            self.quality.clear()
            qualities = self.data.get('qualities', ['Best Available'])
            self.quality.addItems(qualities)
        elif self.image_radio.isChecked():
            # For images, we don't need quality selection
            self.quality.clear()
            self.quality.addItems(['Original'])
            
        # Update quality label
        if self.image_radio.isChecked():
            self.quality_label.setText("Image:")
        else:
            self.quality_label.setText("Quality:")
    def selected_subtitle(self) -> Optional[str]:
        if not self.subtitle:
            return None
        t = self.subtitle.currentText()
        return None if t == "None" else t


class _DownloadItem(QWidget):
    def __init__(self, title: str, item_id: str):
        super().__init__()
        self.item_id = item_id
        v = QVBoxLayout(self)
        v.setContentsMargins(5, 5, 5, 5)
        top = QHBoxLayout()
        self.status_icon = QLabel("⏳")
        top.addWidget(self.status_icon)
        self.title = QLabel(title)
        self.title.setStyleSheet("font-weight: bold;")
        top.addWidget(self.title, 1)
        self.percent_text = QLabel("0%")
        self.percent_text.setMinimumWidth(50)
        top.addWidget(self.percent_text)
        v.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setMaximum(100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        v.addWidget(self.bar)
        self.status = QLabel("Waiting...")
        self.status.setStyleSheet("color: #666; font-size: 10px;")
        v.addWidget(self.status)
    def set_queued(self):
        self.status_icon.setText("⏳")
        self.status.setText("Queued...")
    def set_downloading(self):
        self.status_icon.setText("⬇️")
        self.status.setText("Downloading...")
    def set_paused(self):
        self.status_icon.setText("⏸️")
        self.status.setText("Paused")
    def set_completed(self):
        self.status_icon.setText("✅")
        self.bar.setValue(100)
        self.percent_text.setText("100%")
        self.status.setText("Completed")
    def set_failed(self, error: str):
        self.status_icon.setText("❌")
        self.status.setText(f"Failed: {error}")


class _DownloadWorker(QObject):
    progress = Signal(str, float, str)
    finished = Signal(str, dict)
    progress_display = Signal(str, str, float, str, str, str)
    def __init__(self, item_id: str, video_data: dict, out_dir: str, quality: str, subtitle: str, audio_only: bool, fetch_images: bool = False, fetch_all: bool = False):
        super().__init__()
        self.item_id = item_id
        self.video_data = video_data
        self.out_dir = out_dir
        self.quality = quality
        self.subtitle = subtitle
        self.audio_only = audio_only
        self.fetch_images = fetch_images
        self.fetch_all = fetch_all
        self._running = True
        self._paused = False
        self.last_progress_update = 0.0
    def run(self):
        if not self._running:
            return
        def hook(d):
            if not self._running:
                raise Exception("Cancelled")
            while self._paused:
                if not self._running:
                    raise Exception("Cancelled")
                time.sleep(0.1)
            status = d.get('status', '')
            if status == 'downloading':
                import re
                percent_raw = d.get('_percent_str', '0%')
                percent = re.sub(r'\x1b\[[0-9;]*m', '', percent_raw).replace('%', '').strip()
                try:
                    p = float(percent)
                except Exception:
                    p = 0.0
                speed_raw = d.get('_speed_str', 'N/A')
                eta_raw = d.get('_eta_str', 'N/A')
                speed = re.sub(r'\x1b\[[0-9;]*m', '', speed_raw) if speed_raw != 'N/A' else 'N/A'
                eta = re.sub(r'\x1b\[[0-9;]*m', '', eta_raw) if eta_raw != 'N/A' else 'N/A'
                txt = f"Downloading - {speed} | ETA: {eta}"
                self.progress.emit(self.item_id, p, txt)
                now = time.time()
                if now - self.last_progress_update >= 0.5:
                    self.progress_display.emit(self.item_id, os.path.basename(d.get('filename','') or 'file'), p, speed, eta, f"[download] {p:.1f}%")
                    self.last_progress_update = now
        try:
            result = download_single_video_with_progress(
                self.video_data['url'], self.out_dir, self.quality, self.subtitle, self.audio_only, self.fetch_images, self.fetch_all, hook
            )
            if result.get('success'):
                self.progress.emit(self.item_id, 100.0, "Download completed")
                self.progress_display.emit(self.item_id, "Final", 100.0, "N/A", "N/A", "[download] 100% - Download completed successfully!")
            self.finished.emit(self.item_id, result)
        except Exception as e:
            self.finished.emit(self.item_id, {'success': False, 'message': str(e)})
    def pause(self): self._paused = True
    def resume(self): self._paused = False
    def stop(self): self._running = False


class UnifiedDownloaderGUI(QWidget):
    def __init__(self, title: str, allowed_hosts: Optional[List[str]] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.title = title
        self.allowed_hosts = allowed_hosts or []
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(2)
        self.thumbnail_cache = _ThumbnailCache()
        self.thumbnail_loader = _ThumbnailLoader(self.thumbnail_cache)
        self.download_widgets = {}
        self.video_items = []
        self.fetched_videos = []
        self.download_queue = []
        self.max_concurrent_downloads = 1
        self.current_downloads = 0
        self.active_downloads = 0
        self.completed_downloads = 0
        self.failed_downloads = 0
        self.output_directory = os.path.join(os.getcwd(), 'downloads')
        self.is_paused = False
        self.workers = {}
        self.selected_format = 'mp4'  # Default to MP4
        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(100)
        self.progress_timer.timeout.connect(self._update_progress_bars)
        self.progress_timer.start()
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        # Title
        title_label = QLabel(f"📥 {self.title}")
        f = QFont()
        f.setPointSize(16)
        f.setBold(True)
        title_label.setFont(f)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title_label)
        # URLs
        url_group = QGroupBox("URLs Input")
        url_v = QVBoxLayout(url_group)
        info = QLabel("💡 Enter URLs (one per line or separated by commas/spaces)")
        info.setStyleSheet("color: #666; font-size: 11px;")
        url_v.addWidget(info)
        self.url_input = QTextEdit()
        self.url_input.setPlaceholderText("https://example.com/media/...\nPaste one or more links...")
        self.url_input.setMaximumHeight(100)
        url_v.addWidget(self.url_input)
        # Remove format selection dropdown - fetch all by default
        # Add toggle buttons for MP4, MP3, and Images after fetching
        self.format_toggle_row = QHBoxLayout()
        self.format_toggle_row.addWidget(QLabel("Download Type:"))
        self.mp4_toggle = QPushButton("🎥 MP4 Video")
        self.mp4_toggle.setCheckable(True)
        self.mp4_toggle.setChecked(True)
        self.mp4_toggle.clicked.connect(lambda: self._toggle_format('mp4'))
        self.format_toggle_row.addWidget(self.mp4_toggle)
        
        self.mp3_toggle = QPushButton("🎵 MP3 Audio")
        self.mp3_toggle.setCheckable(True)
        self.mp3_toggle.clicked.connect(lambda: self._toggle_format('mp3'))
        self.format_toggle_row.addWidget(self.mp3_toggle)
        
        self.image_toggle = QPushButton("🖼️ Images")
        self.image_toggle.setCheckable(True)
        self.image_toggle.clicked.connect(lambda: self._toggle_format('image'))
        self.format_toggle_row.addWidget(self.image_toggle)
        
        # Remove format selection - will show radio buttons in video selection frame
        self.selected_format = 'mp4'  # Default to MP4
        fb_row = QHBoxLayout()
        self.fetch_btn = QPushButton("🔍 Fetch Info")
        self.fetch_btn.clicked.connect(self._fetch_info)
        fb_row.addWidget(self.fetch_btn)
        fb_row.addStretch()
        url_v.addLayout(fb_row)
        root.addWidget(url_group)
        # Video selection
        self.video_list_group = QGroupBox("Media Selection")
        v_v = QVBoxLayout(self.video_list_group)
        sa_row = QHBoxLayout()
        self.chk_all = QCheckBox("Select All")
        self.chk_all.setChecked(True)
        self.chk_all.stateChanged.connect(self._toggle_select_all)
        sa_row.addWidget(self.chk_all)
        sa_row.addStretch()
        v_v.addLayout(sa_row)
        self.video_scroll_area = QScrollArea()
        self.video_scroll_area.setWidgetResizable(True)
        self.video_scroll_area.setMinimumHeight(150)
        self.video_scroll_area.setMaximumHeight(250)
        self.video_list_widget = QWidget()
        self.video_list_layout = QVBoxLayout(self.video_list_widget)
        self.video_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.video_scroll_area.setWidget(self.video_list_widget)
        v_v.addWidget(self.video_scroll_area)
        self.video_list_group.setVisible(False)
        root.addWidget(self.video_list_group)
        # Settings
        settings = QGroupBox("Download Settings")
        s_v = QVBoxLayout(settings)
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output Directory:"))
        self.output_path_input = QLineEdit(self.output_directory)
        self.output_path_input.setReadOnly(True)
        out_row.addWidget(self.output_path_input)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self._browse_dir)
        out_row.addWidget(self.browse_button)
        s_v.addLayout(out_row)
        workers_row = QHBoxLayout()
        workers_row.addWidget(QLabel("Concurrent Downloads:"))
        self.workers_spinbox = QSpinBox()
        self.workers_spinbox.setRange(1, 2)
        self.workers_spinbox.setValue(1)
        self.workers_spinbox.valueChanged.connect(self._update_max_concurrent)
        workers_row.addWidget(self.workers_spinbox)
        workers_row.addStretch()
        s_v.addLayout(workers_row)
        root.addWidget(settings)
        # Progress console
        progress_group = QGroupBox("Download Progress")
        p_v = QVBoxLayout(progress_group)
        self.progress_output = QTextEdit()
        self.progress_output.setReadOnly(True)
        self.progress_output.setMaximumHeight(120)
        self.progress_output.setStyleSheet("QTextEdit { background:#0d1117; color:#58a6ff; font-family:Consolas,monospace; font-size:11px; }")
        p_v.addWidget(self.progress_output)
        root.addWidget(progress_group)
        # Buttons
        btn_row = QHBoxLayout()
        self.download_button = QPushButton("🚀 Start Download")
        self.download_button.clicked.connect(self._start_download)
        btn_row.addWidget(self.download_button)
        self.pause_button = QPushButton("⏸ Pause")
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self._toggle_pause)
        btn_row.addWidget(self.pause_button)
        self.cancel_button = QPushButton("❌ Cancel All")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_all)
        btn_row.addWidget(self.cancel_button)
        root.addLayout(btn_row)
        # Status
        status = QGroupBox("Download Status")
        st_v = QVBoxLayout(status)
        top = QHBoxLayout()
        self.active_label = QLabel("Active: 0")
        self.completed_label = QLabel("✅ Completed: 0")
        self.failed_label = QLabel("❌ Failed: 0")
        top.addWidget(self.active_label)
        top.addWidget(self.completed_label)
        top.addWidget(self.failed_label)
        top.addStretch()
        st_v.addLayout(top)
        self.download_items_scroll = QScrollArea()
        self.download_items_scroll.setWidgetResizable(True)
        self.download_items_scroll.setMinimumHeight(150)
        self.download_items_scroll.setMaximumHeight(200)
        self.download_items_widget = QWidget()
        self.download_items_layout = QVBoxLayout(self.download_items_widget)
        self.download_items_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.download_items_scroll.setWidget(self.download_items_widget)
        st_v.addWidget(self.download_items_scroll)
        root.addWidget(status)
        self._log("Ready. Click 'Fetch Info' to preview media.")

    def _log(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.progress_output.append(f"[{ts}] {message}")
        self.progress_output.verticalScrollBar().setValue(self.progress_output.verticalScrollBar().maximum())

    def _toggle_format(self, format_type: str):
        """Toggle between MP4, MP3, and image download formats"""
        self.selected_format = format_type
        
        # Update button states
        self.mp4_toggle.setChecked(format_type == 'mp4')
        self.mp3_toggle.setChecked(format_type == 'mp3')
        self.image_toggle.setChecked(format_type == 'image')
        
        # Update video items based on selected format
        self._update_video_items_for_format(format_type)

    def _update_video_items_for_format(self, format_type: str):
        """Update video items display based on selected format"""
        # This would update the display of video items based on the selected format
        # For now, we'll just log the change
        self._log(f"Switched to {format_type.upper()} format")

    def _toggle_select_all(self, state):
        for it in self.video_items:
            it.chk.setChecked(state == Qt.CheckState.Checked)

    def _browse_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory", self.output_directory)
        if directory:
            self.output_directory = directory
            self.output_path_input.setText(directory)

    def _update_max_concurrent(self, value: int):
        self.max_concurrent_downloads = value
        self.thread_pool.setMaxThreadCount(value)
        self._log(f"🔧 Max concurrent downloads set to: {value}")

    def _fetch_info(self):
        text = self.url_input.toPlainText().strip()
        if not text:
            self._log("❌ Error: No URLs entered!")
            return
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("⏳ Fetching...")
        urls = parse_multiple_urls_for_hosts(text, self.allowed_hosts)
        if not urls:
            self._log("❌ Error: No valid URLs found for this platform!")
            self.fetch_btn.setEnabled(True)
            self.fetch_btn.setText("🔍 Fetch Info")
            return
        # clear list
        while self.video_list_layout.count():
            item = self.video_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.video_items.clear()
        self.fetched_videos.clear()
        # Fetch all formats by default
        audio_only = False
        fetch_all = True
        fetch_images = True
        # fetch in background threads pool (simple loop here)
        class _InfoWorker(QObject):
            sig_ok = Signal(dict)
            sig_err = Signal(str)
            def __init__(self, u: str, ao: bool):
                super().__init__()
                self.u = u
                self.ao = ao
            def run(self):
                try:
                    # For "all" or "image" format types, we need to fetch all available formats
                    info = fetch_generic_info(self.u, self.ao)
                    # Add image information if needed
                    if fetch_all or fetch_images:
                        # We'll modify the info to include image data
                        pass
                    if info.get('type') in ('playlist', 'channel', 'playlist_channel'):
                        info = fetch_generic_playlist_info(self.u, self.ao)
                    self.sig_ok.emit(info)
                except Exception as e:
                    self.sig_err.emit(str(e))
        self._pending = len(urls)
        def _on_ok(info: dict):
            if info.get('type') == 'video':
                row = _VideoItem(info, self.thumbnail_loader)
                self.video_list_layout.addWidget(row)
                self.video_items.append(row)
                self.fetched_videos.append(info)
                self._log(f"✅ Fetched: {info.get('title','Unknown')}")
            else:
                videos = info.get('videos', [])
                self._log(f"✅ Fetched collection: {info.get('title','Unknown')} ({len(videos)} items)")
                for v in videos:
                    row = _VideoItem(v, self.thumbnail_loader)
                    self.video_list_layout.addWidget(row)
                    self.video_items.append(row)
                    self.fetched_videos.append(v)
            self._pending -= 1
            if self._pending == 0:
                self.video_list_group.setVisible(True)
                self.fetch_btn.setEnabled(True)
                self.fetch_btn.setText("🔍 Fetch Info")
        def _on_err(err: str):
            self._log(f"❌ Fetch error: {err}")
            self._pending -= 1
            if self._pending == 0:
                self.video_list_group.setVisible(True)
                self.fetch_btn.setEnabled(True)
                self.fetch_btn.setText("🔍 Fetch Info")
        for u in urls:
            w = _InfoWorker(u, audio_only)
            w.sig_ok.connect(_on_ok)
            w.sig_err.connect(_on_err)
            self.thread_pool.start(_WorkerRunnable(w))

    def _start_download(self):
        if not self.fetched_videos:
            self._log("❌ Please fetch media info first!")
            return
        selected = []
        for i, widget in enumerate(self.video_items):
            if widget.is_selected():
                vd = self.fetched_videos[i].copy()
                vd['selected_quality'] = widget.selected_quality()
                vd['selected_subtitle'] = widget.selected_subtitle()
                vd['selected_format'] = widget.selected_format()  # Add selected format
                selected.append(vd)
        if not selected:
            self._log("❌ No media selected!")
            return
        self._log(f"\n{'='*60}")
        self._log(f"🚀 Starting download of {len(selected)} item(s)")
        self._log(f"📁 Output: {self.output_directory}")
        self.download_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.fetch_btn.setEnabled(False)
        self.video_list_group.setVisible(False)
        # clear current list
        while self.download_items_layout.count():
            item = self.download_items_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.download_widgets.clear()
        self.workers.clear()
        self.download_queue.clear()
        self.active_downloads = len(selected)
        self.completed_downloads = 0
        self.failed_downloads = 0
        self.current_downloads = 0
        self._refresh_stats()
        for v in selected:
            item_id = v['id']
            w = _DownloadItem(v.get('title','Unknown'), item_id)
            self.download_items_layout.addWidget(w)
            self.download_widgets[item_id] = w
            w.set_queued()
            self.download_queue.append({'item_id': item_id, 'video': v, 'widget': w})
        self._log(f"📋 Queue created with {len(self.download_queue)} items")
        self._log(f"🔧 Max concurrent downloads: {self.max_concurrent_downloads}")
        self._start_next()

    def _start_next(self):
        if self.is_paused:
            self._log("⏸ Queue is paused - not starting new downloads")
            return
        while self.current_downloads < self.max_concurrent_downloads and self.download_queue and not self.is_paused:
            q = self.download_queue.pop(0)
            item_id = q['item_id']
            video = q['video']
            w = q['widget']
            # Use the selected format from radio buttons
            audio_only = video.get('selected_format') == "mp3"
            fetch_all = False
            fetch_images = video.get('selected_format') == "image"
            worker = _DownloadWorker(item_id, video, self.output_directory, video.get('selected_quality'), video.get('selected_subtitle'), audio_only, fetch_images, fetch_all)
            worker.progress.connect(self._on_item_progress)
            worker.progress_display.connect(self._on_progress_console)
            worker.finished.connect(self._on_item_finished)
            self.workers[item_id] = worker
            self.thread_pool.start(_WorkerRunnable(worker))
            w.set_downloading()
            self.current_downloads += 1
            self._log(f"🚀 Started download {self.current_downloads}/{self.max_concurrent_downloads}: {video.get('title','')[:50]}...")
        if self.download_queue and not self.is_paused:
            self._log(f"⏳ {len(self.download_queue)} downloads queued, waiting for slots...")
        elif self.download_queue and self.is_paused:
            self._log(f"⏸ {len(self.download_queue)} downloads queued and paused")

    def _on_item_progress(self, item_id: str, percent: float, status: str):
        if item_id in self.download_widgets:
            w = self.download_widgets[item_id]
            w.bar.setValue(int(percent))
            w.percent_text.setText(f"{int(percent)}%")
            w.status.setText(status)

    def _on_progress_console(self, item_id: str, filename: str, percent: float, speed: str, eta: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        if percent >= 100:
            line = f"✅ [{ts}] Download completed successfully!"
        elif "merging" in msg.lower() or "merger" in msg.lower():
            line = f"🔧 [{ts}] {msg}"
        elif "100%" in msg:
            line = f"📦 [{ts}] {msg}"
        else:
            line = f"⬇️ [{ts}] {msg}"
        self.progress_output.append(line)
        self.progress_output.verticalScrollBar().setValue(self.progress_output.verticalScrollBar().maximum())

    def _on_item_finished(self, item_id: str, result: dict):
        self.current_downloads -= 1
        self.active_downloads -= 1
        if item_id in self.download_widgets:
            if result.get('success'):
                self.completed_downloads += 1
                self.download_widgets[item_id].set_completed()
                self._log(f"✅ {result.get('message','Download completed')}")
            else:
                self.failed_downloads += 1
                self.download_widgets[item_id].set_failed(result.get('message','Unknown error'))
                self._log(f"❌ {result.get('message','Download failed')} - Skipping to next item")
        if item_id in self.workers:
            del self.workers[item_id]
        if self.download_queue and not self.is_paused:
            self._log("🔄 Download slot freed, starting next from queue...")
            self._start_next()
        elif self.download_queue and self.is_paused:
            self._log(f"⏸ Download slot freed, but queue is paused - {len(self.download_queue)} downloads remain queued")
        self._refresh_stats()
        if self.active_downloads == 0 and not self.download_queue:
            self._all_finished()

    def _all_finished(self):
        self._log(f"\n{'='*60}")
        self._log("📊 DOWNLOAD SUMMARY")
        self._log(f"{'='*60}")
        self._log(f"✅ Successful: {self.completed_downloads}")
        self._log(f"❌ Failed: {self.failed_downloads}")
        if self.completed_downloads > 0:
            self._log(f"\n🎉 Files saved to: {self.output_directory}")
        self._log(f"{'='*60}\n")
        self.download_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.fetch_btn.setEnabled(True)
        self.is_paused = False
        self.pause_button.setText("⏸ Pause")
        self.download_queue.clear()
        self.video_list_group.setVisible(True)

    def _toggle_pause(self):
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.pause_button.setText("▶️ Resume")
            self._log("⏸ Downloads paused - current downloads will complete, queue paused")
            for w in self.workers.values():
                w.pause()
            for item_id, widget in self.download_widgets.items():
                if widget.status_icon.text() == "⬇️":
                    widget.set_paused()
            self._log("⏳ Queue paused - remaining downloads will stay queued until resume")
        else:
            self.pause_button.setText("⏸ Pause")
            self._log("▶️ Downloads resumed")
            for w in self.workers.values():
                w.resume()
            for item_id, widget in self.download_widgets.items():
                if widget.status_icon.text() == "⏸️":
                    widget.set_downloading()
            if self.download_queue:
                self._log("🔄 Resuming queue processing...")
                self._start_next()

    def _cancel_all(self):
        self._log("\n❌ Cancelling all downloads...")
        for w in self.workers.values():
            w.stop()
        self.download_queue.clear()
        self.is_paused = False
        self.pause_button.setText("⏸ Pause")
        self._refresh_stats()
        self._all_finished()
        self._log("❌ All downloads cancelled.\n")

    def _refresh_stats(self):
        self.active_label.setText(f"Active: {self.active_downloads}")
        self.completed_label.setText(f"✅ Completed: {self.completed_downloads}")
        self.failed_label.setText(f"❌ Failed: {self.failed_downloads}")

    def _update_progress_bars(self):
        try:
            for _, w in self.download_widgets.items():
                if hasattr(w, 'bar'):
                    w.bar.repaint()
                    w.percent_text.repaint()
                    w.status.repaint()
        except Exception:
            pass


