from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Qt
from PySide6.QtGui import QIcon, QMovie
from PySide6.QtWidgets import (
	QWidget,
	QVBoxLayout,
	QHBoxLayout,
	QLabel,
	QLineEdit,
	QComboBox,
	QPushButton,
	QProgressBar,
	QFileDialog,
	QDialog,
)

from workers.yt_dlp_worker import YtDlpWorker


def get_default_desktop() -> Path:
	desktop = Path.home() / "Desktop"
	if desktop.exists():
		return desktop
	return Path.home()


@dataclass
class ProgressState:
	percent: float = 0.0
	speed: str = ""
	eta: str = ""
	status: str = "Idle"


class DownloadWidget(QWidget):
	def __init__(
		self,
		ffmpeg_location: Optional[str],
		placeholder_url: str,
		title: str,
		allowed_hosts: Optional[list[str]] = None,
		parent: Optional[QWidget] = None,
	) -> None:
		super().__init__(parent)
		self.ffmpeg_location = ffmpeg_location
		self.placeholder_url = placeholder_url
		self.title = title
		self.allowed_hosts = allowed_hosts or []
		self._media_kind: str = "other"
		self._image_mode: bool = False

		self._progress_state = ProgressState()
		self._progress_lock = threading.Lock()
		self._thread: Optional[QThread] = None
		self._worker: Optional[YtDlpWorker] = None
		self._fmt_thread: Optional[QThread] = None
		self._fmt_worker: Optional[YtDlpWorker] = None
		self._available_formats = []
		self._available_heights = []
		self._available_abrs = []

		self._build_ui()
		self._setup_timer()
		self._set_initial_ui_state()

	def _build_ui(self) -> None:
		root = QVBoxLayout(self)
		root.setContentsMargins(12, 4, 12, 12)
		root.setSpacing(4)

		# Title
		title_label = QLabel(self.title, self)
		font = title_label.font()
		font.setPointSize(font.pointSize() + 2)
		font.setBold(True)
		title_label.setFont(font)
		root.addWidget(title_label)

		# URL row
		url_row = QHBoxLayout()
		url_label = QLabel("Media URL:", self)
		self.url_edit = QLineEdit(self)
		self.url_edit.setPlaceholderText(self.placeholder_url)
		load_btn = QPushButton("Load", self)
		load_btn.setToolTip("Fetch available qualities")
		load_btn.clicked.connect(self._on_load_formats)
		url_row.addWidget(url_label)
		url_row.addWidget(self.url_edit, 1)
		url_row.addWidget(load_btn)
		self._url_row = url_row
		root.addLayout(self._url_row)

		# Type/Quality row
		tq_row = QHBoxLayout()
		type_label = QLabel("Type:", self)
		self.type_combo = QComboBox(self)
		self.type_combo.addItems(["MP4 (video)", "MP3 (audio)"])
		self.type_combo.currentIndexChanged.connect(self._update_quality_combo_items)
		quality_label = QLabel("Quality:", self)
		self.quality_combo = QComboBox(self)
		self.quality_combo.setEditable(False)
		self.quality_combo.setMinimumWidth(140)
		tq_row.addWidget(type_label)
		tq_row.addWidget(self.type_combo)
		tq_row.addSpacing(12)
		tq_row.addWidget(quality_label)
		tq_row.addWidget(self.quality_combo, 1)
		self._tq_row = tq_row
		root.addLayout(self._tq_row)

		# Output row
		out_row = QHBoxLayout()
		out_label = QLabel("Output folder:", self)
		self.out_edit = QLineEdit(self)
		self.out_edit.setText(str(get_default_desktop()))
		browse_btn = QPushButton("Browse…", self)
		browse_btn.clicked.connect(self._on_browse)
		out_row.addWidget(out_label)
		out_row.addWidget(self.out_edit, 1)
		out_row.addWidget(browse_btn)
		self._out_row = out_row
		root.addLayout(self._out_row)

		# Progress
		self.progress = QProgressBar(self)
		self.progress.setRange(0, 100)
		self.progress.setValue(0)
		self.progress.setVisible(True)
		root.addWidget(self.progress)

		# Loading spinner popup (created on demand). No inline status under the bar.
		self._spinner_dialog: QDialog | None = None
		self._spinner_movie: QMovie | None = None

		# Actions
		actions = QHBoxLayout()
		self.download_btn = QPushButton("Download", self)
		self.download_btn.clicked.connect(self._on_download)
		self.cancel_btn = QPushButton("Cancel", self)
		self.cancel_btn.setEnabled(False)
		self.cancel_btn.clicked.connect(self._on_cancel)
		actions.addStretch(1)
		actions.addWidget(self.download_btn)
		actions.addWidget(self.cancel_btn)
		self._actions_row = actions
		root.addLayout(self._actions_row)

	def _setup_timer(self) -> None:
		self.timer = QTimer(self)
		self.timer.setInterval(500)  # 0.5 sec
		self.timer.timeout.connect(self._refresh_progress_ui)
		self.timer.start()

	def _on_load_formats(self) -> None:
		url = self.url_edit.text().strip()
		if not url:
			return
		if not self._is_url_allowed(url):
			self._flash_url_invalid()
			return
		self._show_loading_popup()
		self._start_formats_worker(url)

	def _on_browse(self) -> None:
		start_dir = Path(self.out_edit.text()).expanduser()
		if not start_dir.exists():
			start_dir = get_default_desktop()
		chosen = QFileDialog.getExistingDirectory(self, "Choose output folder", str(start_dir))
		if chosen:
			self.out_edit.setText(chosen)

	def _on_download(self) -> None:
		url = self.url_edit.text().strip()
		if not url:
			self.status_label.setText("Please enter a valid URL.")
			return
		if not self._is_url_allowed(url):
			self._flash_url_invalid()
			return
		out_dir = Path(self.out_edit.text().strip()).expanduser()
		if not out_dir.exists():
			try:
				out_dir.mkdir(parents=True, exist_ok=True)
			except Exception as e:
				return

		# Reset progress bar when starting a new download
		self.progress.setValue(0)
		self.download_btn.setEnabled(False)
		self.cancel_btn.setEnabled(True)
		with self._progress_lock:
			self._progress_state = ProgressState(status="Starting…")
		selected_format = self._build_format_selector()
		self._start_worker(url, str(out_dir), selected_format)

	def _on_cancel(self) -> None:
		if self._worker is not None:
			self._worker.request_cancel()
		self.cancel_btn.setEnabled(False)

	def _start_worker(self, url: str, out_dir: str, format_selector: Optional[str]) -> None:
		self._thread = QThread(self)
		self._worker = YtDlpWorker(
			url=url,
			out_dir=out_dir,
			ffmpeg_location=self.ffmpeg_location,
		)
		self._worker.moveToThread(self._thread)
		self._thread.started.connect(self._worker.run)
		self._worker.sig_progress.connect(self._on_worker_progress)
		self._worker.sig_error.connect(self._on_worker_error)
		self._worker.sig_finished.connect(self._on_worker_finished)
		# Real-time progress: update immediately on signal as well
		self._worker.sig_progress.connect(lambda p, s, e, st: self._refresh_progress_ui_immediate(p, s, e, st))
		# Configure desired format by setting attributes on worker (read inside run)
		setattr(self._worker, "_desired_format", format_selector)
		setattr(self._worker, "_desired_audio", self.type_combo.currentIndex() == 1)
		setattr(self._worker, "_desired_mp3_bitrate", self._selected_mp3_bitrate())

		self._thread.start()

	def _on_worker_progress(self, percent: float, speed: str, eta: str, status: str) -> None:
		with self._progress_lock:
			self._progress_state.percent = max(0.0, min(100.0, percent))
			self._progress_state.speed = speed
			self._progress_state.eta = eta
			self._progress_state.status = status

	def _on_worker_error(self, message: str) -> None:
		with self._progress_lock:
			self._progress_state.status = f"Error: {message}"
		self.download_btn.setEnabled(True)
		self.cancel_btn.setEnabled(False)
		self._cleanup_thread()

	def _on_worker_finished(self) -> None:
		with self._progress_lock:
			self._progress_state.percent = 100.0
			self._progress_state.status = "Completed"
		self.download_btn.setEnabled(True)
		self.cancel_btn.setEnabled(False)
		# Clear the URL field after completion
		self.url_edit.setText("")
		# After a short visual completion, reset progress bar to 0
		self.progress.setValue(100)
		QTimer.singleShot(400, lambda: (self.progress.setValue(0), None))
		self._cleanup_thread()

	def _cleanup_thread(self) -> None:
		if self._worker is not None:
			self._worker.deleteLater()
			self._worker = None
		if self._thread is not None:
			self._thread.quit()
			self._thread.wait()
			self._thread.deleteLater()
			self._thread = None
		if self._fmt_worker is not None:
			self._fmt_worker.deleteLater()
			self._fmt_worker = None
		if self._fmt_thread is not None:
			self._fmt_thread.quit()
			self._fmt_thread.wait()
			self._fmt_thread.deleteLater()
			self._fmt_thread = None

	def _refresh_progress_ui(self) -> None:
		with self._progress_lock:
			ps = ProgressState(
				percent=self._progress_state.percent,
				speed=self._progress_state.speed,
				eta=self._progress_state.eta,
				status=self._progress_state.status,
			)
		self.progress.setValue(int(ps.percent))
		# No textual status under progress bar per request

	def _refresh_progress_ui_immediate(self, percent: float, speed: str, eta: str, status: str) -> None:
		# Update UI immediately on progress signal
		self.progress.setValue(int(percent))
		# No textual status under progress bar per request

	def _start_formats_worker(self, url: str) -> None:
		self._fmt_thread = QThread(self)
		self._fmt_worker = YtDlpWorker(url=url, out_dir=str(get_default_desktop()), ffmpeg_location=self.ffmpeg_location)
		self._fmt_worker.moveToThread(self._fmt_thread)
		self._fmt_thread.started.connect(self._fmt_worker.fetch_formats)
		self._fmt_worker.sig_formats.connect(self._on_formats_ready)
		self._fmt_worker.sig_error.connect(self._on_formats_error)
		self._fmt_thread.start()

	def _on_formats_ready(self, fmts: list, media_kind: str) -> None:
		self._available_formats = fmts or []
		self._media_kind = media_kind or "other"
		self._image_mode = (self._media_kind == "image")
		# collect unique heights for mp4 and unique audio bitrates for mp3
		heights = sorted({f["height"] for f in self._available_formats if f.get("height")}, reverse=True)
		abrs = sorted({int(f["abr"]) for f in self._available_formats if f.get("abr")}, reverse=True)
		self._available_heights = heights
		self._available_abrs = abrs or [320, 192, 128]
		self._update_quality_combo_items()
		self._hide_loading_popup()
		self._update_visibility_after_load()

	def _update_quality_combo_items(self) -> None:
		self.quality_combo.blockSignals(True)
		self.quality_combo.clear()
		if self.type_combo.currentIndex() == 0:
			# MP4 video: show heights
			items = [f"{h}p" for h in self._available_heights] or ["1080p", "720p", "480p"]
			self.quality_combo.addItems(items)
			# preselect 1080p if available
			idx = self.quality_combo.findText("1080p")
			if idx >= 0:
				self.quality_combo.setCurrentIndex(idx)
		else:
			# MP3 audio: show bitrates
			items = [f"{br}k" for br in self._available_abrs] or ["320k", "192k", "128k"]
			self.quality_combo.addItems(items)
			idx = self.quality_combo.findText("320k")
			if idx >= 0:
				self.quality_combo.setCurrentIndex(idx)
		self.quality_combo.blockSignals(False)

	def _selected_mp4_height(self) -> int:
		text = self.quality_combo.currentText().strip().lower().rstrip("p")
		try:
			return int(text)
		except Exception:
			return 1080

	def _selected_mp3_bitrate(self) -> int:
		text = self.quality_combo.currentText().strip().lower().rstrip("k")
		try:
			return int(text)
		except Exception:
			return 320

	def _build_format_selector(self) -> Optional[str]:
		# Build yt-dlp format selector depending on type/quality
		if self._image_mode:
			# For images/posts, rely on yt-dlp best (highest quality available)
			return "best"
		if self.type_combo.currentIndex() == 0:
			# MP4: prefer mp4 at selected height
			height = self._selected_mp4_height()
			return f"bestvideo[ext=mp4][height<={height}]+bestaudio[ext=m4a]/best[ext=mp4][height<={height}]"
		else:
			# MP3: we will use postprocessor; return bestaudio
			return "bestaudio/best"

	def _set_initial_ui_state(self) -> None:
		# Only URL row visible initially
		self._tq_row.parentWidget()  # no-op to ensure it's constructed
		for layout in (self._tq_row, self._out_row, self._actions_row):
			self._set_layout_visible(layout, False)
		self.progress.setVisible(False)

	def _update_visibility_after_load(self) -> None:
		# Show output, actions and progress always after load
		self._set_layout_visible(self._out_row, True)
		self._set_layout_visible(self._actions_row, True)
		self.progress.setVisible(True)
		# Show type/quality only for videos
		self._set_layout_visible(self._tq_row, not self._image_mode)

	def _set_layout_visible(self, layout: QHBoxLayout, visible: bool) -> None:
		# Helper to show/hide all widgets in a layout
		for i in range(layout.count()):
			item = layout.itemAt(i)
			w = item.widget()
			if w is not None:
				w.setVisible(visible)

	def _ensure_spinner_dialog(self) -> None:
		if self._spinner_dialog is None:
			self._spinner_dialog = QDialog(self.window(), Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
			self._spinner_dialog.setModal(True)  # modal only for Load
			self._spinner_dialog.setWindowModality(Qt.ApplicationModal)
			self._spinner_dialog.setAttribute(Qt.WA_TranslucentBackground, True)
			v = QVBoxLayout(self._spinner_dialog)
			v.setContentsMargins(16, 16, 16, 16)
			label = QLabel(self._spinner_dialog)
			label.setAlignment(Qt.AlignCenter)
			# Load spinner gif located at project root: loading_spin.gif
			try:
				from pathlib import Path as _Path
				gif_path = str(_Path(__file__).resolve().parents[1] / "loading_spin.gif")
			except Exception:
				gif_path = "loading_spin.gif"
			self._spinner_movie = QMovie(gif_path)
			label.setMovie(self._spinner_movie)
			v.addWidget(label)
			self._spinner_dialog.resize(120, 120)

	def _show_loading_popup(self) -> None:
		self._ensure_spinner_dialog()
		if self._spinner_dialog and self._spinner_movie:
			self._spinner_movie.start()
			# Center over main window
			parent = self.window()
			if parent is not None:
				center_point = parent.frameGeometry().center()
				dialog_rect = self._spinner_dialog.frameGeometry()
				dialog_rect.moveCenter(center_point)
				self._spinner_dialog.move(dialog_rect.topLeft())
			self._spinner_dialog.show()

	def _hide_loading_popup(self) -> None:
		if self._spinner_dialog and self._spinner_movie:
			self._spinner_movie.stop()
			self._spinner_dialog.hide()

	def _on_formats_error(self, message: str) -> None:
		# Hide spinner and keep UI interactive
		self._hide_loading_popup()
		# No textual status under progress bar
		self._cleanup_thread()

	def _is_url_allowed(self, url: str) -> bool:
		if not self.allowed_hosts:
			return True
		try:
			host = urlparse(url).netloc.lower()
		except Exception:
			return False
		# Strip port and www.
		if ":" in host:
			host = host.split(":", 1)[0]
		if host.startswith("www."):
			host = host[4:]
		for allowed in self.allowed_hosts:
			a = allowed.lower().lstrip(".")
			if host == a or host.endswith("." + a):
				return True
		return False

	def _flash_url_invalid(self) -> None:
		orig = self.url_edit.styleSheet()
		self.url_edit.setStyleSheet(orig + ";border: 1px solid #ff4d4f;")
		QTimer.singleShot(900, lambda: self.url_edit.setStyleSheet(orig))

