from __future__ import annotations

from pathlib import Path
from typing import Optional, List, Dict

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
	QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox,
	QFileDialog, QScrollArea, QGroupBox, QCheckBox, QProgressBar, QWidget as _QW
)

from widgets.download_widget import get_default_desktop
from workers.youtube_info_worker import YouTubeInfoWorker
from workers.youtube_download_worker import YouTubeDownloadWorker


class _PlaylistItemRow(QWidget):
	def __init__(self, video: Dict) -> None:
		super().__init__()
		self.video = video
		row = QHBoxLayout(self)
		row.setContentsMargins(4, 4, 4, 4)
		self.chk = QCheckBox(self)
		self.chk.setChecked(True)
		row.addWidget(self.chk)
		self.title = QLabel(video.get("title", "Unknown"), self)
		self.title.setToolTip(video.get("title", ""))
		row.addWidget(self.title, 1)
		# Quality
		row.addWidget(QLabel("Quality:", self))
		self.quality = QComboBox(self)
		for q in video.get("qualities", []):
			self.quality.addItem(q)
		row.addWidget(self.quality)
		# Subtitles
		self.subtitle = None
		subs = video.get("subtitles") or []
		if subs:
			row.addWidget(QLabel("Subtitles:", self))
			self.subtitle = QComboBox(self)
			self.subtitle.addItem("None")
			for s in subs:
				self.subtitle.addItem(s)
			row.addWidget(self.subtitle)

	def is_selected(self) -> bool:
		return self.chk.isChecked()

	def selected_quality(self) -> Optional[str]:
		return self.quality.currentText() if self.quality.count() > 0 else None

	def selected_subtitle(self) -> Optional[str]:
		if self.subtitle is None:
			return None
		text = self.subtitle.currentText()
		return None if text == "None" else text


class YouTubeWidget(QWidget):
	def __init__(self, ffmpeg_location: Optional[str], parent: Optional[_QW] = None) -> None:
		super().__init__(parent)
		self.ffmpeg_location = ffmpeg_location
		self._info_thread: Optional[QThread] = None
		self._info_worker: Optional[YouTubeInfoWorker] = None
		self._dl_thread: Optional[QThread] = None
		self._dl_worker: Optional[YouTubeDownloadWorker] = None
		self._info: Optional[Dict] = None

		root = QVBoxLayout(self)
		root.setContentsMargins(12, 4, 12, 12)
		root.setSpacing(4)

		# Title
		title = QLabel("YouTube Downloader", self)
		f = title.font()
		f.setPointSize(f.pointSize() + 2)
		f.setBold(True)
		title.setFont(f)
		root.addWidget(title)

		# URL row (top, under title)
		url_row = QHBoxLayout()
		url_row.addWidget(QLabel("Media URL:", self))
		self.url = QLineEdit(self)
		self.url.setPlaceholderText("https://www.youtube.com/watch?v=...")
		url_row.addWidget(self.url, 1)
		self.btn_load = QPushButton("Load", self)
		self.btn_load.clicked.connect(self._on_load)
		url_row.addWidget(self.btn_load)
		root.addLayout(url_row)

		# For single video
		self.single_box = QGroupBox("Video", self)
		sv = QVBoxLayout(self.single_box)
		# Type/quality/subtitles
		r1 = QHBoxLayout()
		r1.addWidget(QLabel("Type:", self.single_box))
		self.type_combo = QComboBox(self.single_box)
		self.type_combo.addItems(["MP4 (video)", "MP3 (audio)"])
		r1.addWidget(self.type_combo)
		r1.addSpacing(8)
		r1.addWidget(QLabel("Quality:", self.single_box))
		self.quality_combo = QComboBox(self.single_box)
		r1.addWidget(self.quality_combo)
		r1.addSpacing(8)
		r1.addWidget(QLabel("Subtitles:", self.single_box))
		self.subtitle_combo = QComboBox(self.single_box)
		self.subtitle_combo.addItem("None")
		r1.addWidget(self.subtitle_combo)
		sv.addLayout(r1)
		# Output
		orow = QHBoxLayout()
		orow.addWidget(QLabel("Output folder:", self.single_box))
		self.out_edit = QLineEdit(self.single_box)
		self.out_edit.setText(str(get_default_desktop()))
		orow.addWidget(self.out_edit, 1)
		ob = QPushButton("Browse…", self.single_box)
		ob.clicked.connect(self._on_browse)
		orow.addWidget(ob)
		sv.addLayout(orow)
		# Progress and actions
		self.progress = QProgressBar(self.single_box)
		self.progress.setRange(0, 100)
		self.progress.setValue(0)
		sv.addWidget(self.progress)
		arow = QHBoxLayout()
		arow.addStretch(1)
		self.btn_download = QPushButton("Download", self.single_box)
		self.btn_download.clicked.connect(self._on_download_single)
		arow.addWidget(self.btn_download)
		self.btn_cancel = QPushButton("Cancel", self.single_box)
		self.btn_cancel.setEnabled(False)
		self.btn_cancel.clicked.connect(self._on_cancel)
		arow.addWidget(self.btn_cancel)
		sv.addLayout(arow)
		root.addWidget(self.single_box)

		# For playlist/channel
		self.playlist_box = QGroupBox("Playlist/Channel", self)
		pv = QVBoxLayout(self.playlist_box)
		self.scroll = QScrollArea(self.playlist_box)
		self.list_widget = QWidget(self.scroll)
		self.list_layout = QVBoxLayout(self.list_widget)
		self.list_layout.setAlignment(Qt.AlignTop)
		self.scroll.setWidgetResizable(True)
		self.scroll.setWidget(self.list_widget)
		pv.addWidget(self.scroll)
		# Output
		pr = QHBoxLayout()
		pr.addWidget(QLabel("Output folder:", self.playlist_box))
		self.playlist_out = QLineEdit(self.playlist_box)
		self.playlist_out.setText(str(get_default_desktop()))
		pr.addWidget(self.playlist_out, 1)
		pb = QPushButton("Browse…", self.playlist_box)
		pb.clicked.connect(self._on_browse_playlist)
		pr.addWidget(pb)
		pv.addLayout(pr)
		# Progress and actions
		self.playlist_progress = QProgressBar(self.playlist_box)
		self.playlist_progress.setRange(0, 100)
		self.playlist_progress.setValue(0)
		pv.addWidget(self.playlist_progress)
		par = QHBoxLayout()
		par.addStretch(1)
		self.btn_download_all = QPushButton("Download Selected", self.playlist_box)
		self.btn_download_all.clicked.connect(self._on_download_playlist)
		par.addWidget(self.btn_download_all)
		self.btn_cancel_all = QPushButton("Cancel", self.playlist_box)
		self.btn_cancel_all.setEnabled(False)
		self.btn_cancel_all.clicked.connect(self._on_cancel)
		par.addWidget(self.btn_cancel_all)
		pv.addLayout(par)
		root.addWidget(self.playlist_box)

		# Initial state
		self.single_box.hide()
		self.playlist_box.hide()

	def _on_browse(self) -> None:
		start = Path(self.out_edit.text()).expanduser()
		if not start.exists():
			start = get_default_desktop()
		chosen = QFileDialog.getExistingDirectory(self, "Choose output folder", str(start))
		if chosen:
			self.out_edit.setText(chosen)

	def _on_browse_playlist(self) -> None:
		start = Path(self.playlist_out.text()).expanduser()
		if not start.exists():
			start = get_default_desktop()
		chosen = QFileDialog.getExistingDirectory(self, "Choose output folder", str(start))
		if chosen:
			self.playlist_out.setText(chosen)

	def _on_load(self) -> None:
		url = self.url.text().strip()
		if not url:
			return
		self.btn_load.setEnabled(False)
		audio_only = False  # we will offer MP3 later in single view
		self._info_thread = QThread(self)
		self._info_worker = YouTubeInfoWorker(url, audio_only)
		self._info_worker.moveToThread(self._info_thread)
		self._info_thread.started.connect(self._info_worker.run)
		self._info_worker.sig_info.connect(self._on_info)
		self._info_worker.sig_error.connect(self._on_info_error)
		self._info_thread.start()

	def _on_info(self, info: Dict) -> None:
		self.btn_load.setEnabled(True)
		self._teardown_thread("info")
		self._info = info
		ctype = info.get("type")
		if ctype == "video":
			self._populate_single(info)
			self.single_box.show()
			self.playlist_box.hide()
		else:
			self._populate_playlist(info)
			self.single_box.hide()
			self.playlist_box.show()

	def _on_info_error(self, msg: str) -> None:
		self.btn_load.setEnabled(True)
		self._teardown_thread("info")

	def _populate_single(self, info: Dict) -> None:
		self.quality_combo.clear()
		for q in info.get("qualities", []):
			self.quality_combo.addItem(q)
		self.subtitle_combo.clear()
		self.subtitle_combo.addItem("None")
		for s in info.get("subtitles", []):
			self.subtitle_combo.addItem(s)
		# default type MP4
		self.type_combo.setCurrentIndex(0)
		self.progress.setValue(0)

	def _populate_playlist(self, info: Dict) -> None:
		# clear existing
		while self.list_layout.count():
			item = self.list_layout.takeAt(0)
			if item.widget():
				item.widget().deleteLater()
		videos = info.get("videos", [])
		for v in videos:
			row = _PlaylistItemRow(v)
			self.list_layout.addWidget(row)
		self.playlist_progress.setValue(0)

	def _on_download_single(self) -> None:
		if not self._info or self._info.get("type") != "video":
			return
		url = self._info.get("url")
		audio_only = self.type_combo.currentIndex() == 1
		quality = self.quality_combo.currentText() if self.quality_combo.count() > 0 else None
		subtitle = self.subtitle_combo.currentText()
		if subtitle == "None":
			subtitle = None
		video_entry = {"url": url, "selected_quality": quality, "selected_subtitle": subtitle}
		self._start_download([video_entry], self.out_edit.text().strip(), audio_only, single=True)

	def _on_download_playlist(self) -> None:
		if not self._info or self._info.get("type") not in ("playlist", "channel"):
			return
		entries: List[Dict] = []
		for i in range(self.list_layout.count()):
			w: _PlaylistItemRow = self.list_layout.itemAt(i).widget()
			if w and w.is_selected():
				entries.append({
					"url": self._info["videos"][i]["url"],
					"selected_quality": w.selected_quality(),
					"selected_subtitle": w.selected_subtitle(),
				})
		if not entries:
			return
		self._start_download(entries, self.playlist_out.text().strip(), audio_only=False, single=False)

	def _start_download(self, videos: List[Dict], out_dir: str, audio_only: bool, single: bool) -> None:
		Path(out_dir).mkdir(parents=True, exist_ok=True)
		self._dl_thread = QThread(self)
		self._dl_worker = YouTubeDownloadWorker(videos, out_dir, audio_only)
		self._dl_worker.moveToThread(self._dl_thread)
		self._dl_thread.started.connect(self._dl_worker.run)
		if single:
			self._dl_worker.sig_item_progress.connect(lambda idx, p: self.progress.setValue(int(p)))
			self._dl_worker.sig_progress.connect(lambda p: None)
		else:
			self._dl_worker.sig_progress.connect(lambda p: self.playlist_progress.setValue(int(p)))
		self._dl_worker.sig_finished.connect(self._on_download_finished)
		self._dl_worker.sig_error.connect(self._on_download_error)
		self._dl_thread.start()
		# toggle buttons
		if single:
			self.btn_download.setEnabled(False)
			self.btn_cancel.setEnabled(True)
		else:
			self.btn_download_all.setEnabled(False)
			self.btn_cancel_all.setEnabled(True)

	def _on_download_error(self, msg: str) -> None:
		self._teardown_thread("dl")
		self.btn_download.setEnabled(True)
		self.btn_cancel.setEnabled(False)
		self.btn_download_all.setEnabled(True)
		self.btn_cancel_all.setEnabled(False)

	def _on_download_finished(self, summary: Dict) -> None:
		self._teardown_thread("dl")
		self.btn_download.setEnabled(True)
		self.btn_cancel.setEnabled(False)
		self.btn_download_all.setEnabled(True)
		self.btn_cancel_all.setEnabled(False)
		self.progress.setValue(0)
		self.playlist_progress.setValue(0)
		self.url.setText("")

	def _on_cancel(self) -> None:
		if self._dl_worker:
			self._dl_worker.cancel()
		self.btn_cancel.setEnabled(False)
		self.btn_cancel_all.setEnabled(False)

	def _teardown_thread(self, kind: str) -> None:
		if kind == "info":
			if self._info_worker is not None:
				self._info_worker.deleteLater()
				self._info_worker = None
			if self._info_thread is not None:
				self._info_thread.quit()
				self._info_thread.wait()
				self._info_thread.deleteLater()
				self._info_thread = None
		elif kind == "dl":
			if self._dl_worker is not None:
				self._dl_worker.deleteLater()
				self._dl_worker = None
			if self._dl_thread is not None:
				self._dl_thread.quit()
				self._dl_thread.wait()
				self._dl_thread.deleteLater()
				self._dl_thread = None


