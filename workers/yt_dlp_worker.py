from __future__ import annotations

import threading
from typing import Optional, Dict, Any

from PySide6.QtCore import QObject, Signal


class YtDlpWorker(QObject):
	sig_progress = Signal(float, str, str, str)  # percent, speed, eta, status
	sig_error = Signal(str)
	sig_finished = Signal()
	sig_formats = Signal(list, str)  # (formats, media_kind: 'video' | 'image' | 'other')

	def __init__(self, url: str, out_dir: str, ffmpeg_location: Optional[str]) -> None:
		super().__init__()
		self.url = url
		self.out_dir = out_dir
		self.ffmpeg_location = ffmpeg_location
		self._cancel_event = threading.Event()

	def request_cancel(self) -> None:
		self._cancel_event.set()

	def fetch_formats(self) -> None:
		try:
			from yt_dlp import YoutubeDL
		except Exception as e:
			self.sig_error.emit(f"yt-dlp not available: {e}")
			return
		opts = {
			"quiet": True,
			"no_warnings": True,
		}
		if self.ffmpeg_location:
			opts["ffmpeg_location"] = self.ffmpeg_location
		try:
			with YoutubeDL(opts) as ydl:
				info = ydl.extract_info(self.url, download=False)
		except Exception as e:
			self.sig_error.emit(str(e))
			return
		formats = info.get("formats") or []
		# Determine media kind
		media_kind = "other"
		try:
			ext = (info.get("ext") or "").lower()
			if ext in ("jpg", "jpeg", "png", "webp"):
				media_kind = "image"
			else:
				# Consider it video if any format has a video codec
				for f in formats:
					if f.get("vcodec") and f.get("vcodec") != "none":
						media_kind = "video"
						break
				if media_kind == "other" and info.get("duration"):
					media_kind = "video"
		except Exception:
			pass

		simplified = []
		for f in formats:
			ext = f.get("ext") or ""
			height = f.get("height")
			abr = f.get("abr")
			acodec = f.get("acodec")
			vcodec = f.get("vcodec")
			fid = f.get("format_id")
			tbr = f.get("tbr")
			simplified.append({
				"format_id": fid,
				"ext": ext,
				"height": height,
				"abr": abr,
				"tbr": tbr,
				"acodec": acodec,
				"vcodec": vcodec,
			})
		self.sig_formats.emit(simplified, media_kind)

	def _progress_hook(self, d: Dict[str, Any]) -> None:
		if self._cancel_event.is_set():
			# yt-dlp does not support external cancellation cleanly; raise to abort.
			raise RuntimeError("Cancelled by user")
		status = d.get("status", "")
		percent = 0.0
		speed = ""
		eta = ""

		# Prefer precise byte-based calculation
		downloaded = d.get("downloaded_bytes") or 0
		total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
		if total and downloaded:
			try:
				percent = max(0.0, min(100.0, (float(downloaded) / float(total)) * 100.0))
			except Exception:
				percent = 0.0

		# If fragments info is available (DASH/HLS), fallback to that
		if percent == 0.0:
			fi = d.get("fragment_index")
			fc = d.get("fragment_count")
			if isinstance(fi, int) and isinstance(fc, int) and fc > 0:
				percent = max(0.0, min(100.0, (fi / float(fc)) * 100.0))

		# As last resort, parse percent string
		if percent == 0.0:
			try:
				percent = float(str(d.get("_percent_str", "0%")).strip().strip("%"))
			except Exception:
				percent = 0.0

		# Speed and ETA strings from yt-dlp for nice formatting
		speed = str(d.get("_speed_str", "")).strip()
		eta_val = d.get("eta")
		if eta_val is not None:
			try:
				eta = f"{int(eta_val)}s"
			except Exception:
				eta = str(eta_val)

		if status == "finished":
			percent = 100.0

		# Normalize status for UI
		norm_status = status or "working"
		if norm_status == "downloading":
			norm_status = "Downloading"
		elif norm_status == "finished":
			norm_status = "Processing"
		elif norm_status == "postprocessing":
			norm_status = "Post-processing"

		self.sig_progress.emit(percent, speed, eta, norm_status)

	def run(self) -> None:
		try:
			from yt_dlp import YoutubeDL
		except Exception as e:
			self.sig_error.emit(f"yt-dlp not available: {e}")
			return

		outtmpl = "%(title)s.%(ext)s"
		opts: Dict[str, Any] = {
			"outtmpl": str((self.out_dir.rstrip("/\\") + "/" + outtmpl)),
			"progress_hooks": [self._progress_hook],
			"noprogress": True,
			"quiet": True,
			"no_warnings": True,
		}
		if self.ffmpeg_location:
			opts["ffmpeg_location"] = self.ffmpeg_location

		# Apply desired format if provided
		desired_format = getattr(self, "_desired_format", None)
		if desired_format:
			opts["format"] = desired_format

		# If audio-only mp3 requested, configure postprocessor
		if getattr(self, "_desired_audio", False):
			br = getattr(self, "_desired_mp3_bitrate", 320)
			opts.setdefault("postprocessors", []).append({
				"key": "FFmpegExtractAudio",
				"preferredcodec": "mp3",
				"preferredquality": str(int(br)),
			})

		try:
			with YoutubeDL(opts) as ydl:
				ydl.download([self.url])
		except Exception as e:
			self.sig_error.emit(str(e))
			return

		self.sig_finished.emit()


