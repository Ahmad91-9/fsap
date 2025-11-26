from __future__ import annotations

from typing import Optional, List, Dict
from PySide6.QtCore import QObject, Signal

from downloader_core import download_single_video_with_progress


class YouTubeDownloadWorker(QObject):
	sig_progress = Signal(float)  # overall percentage 0-100
	sig_item_progress = Signal(int, float)  # index, percent for current item
	sig_finished = Signal(dict)  # summary
	sig_error = Signal(str)

	def __init__(self, videos: List[Dict], output_dir: str, audio_only: bool) -> None:
		super().__init__()
		self.videos = videos
		self.output_dir = output_dir
		self.audio_only = audio_only
		self._cancelled = False

	def cancel(self) -> None:
		self._cancelled = True

	def run(self) -> None:
		total = len(self.videos)
		completed = 0
		results: List[Dict] = []

		for idx, video in enumerate(self.videos):
			if self._cancelled:
				break

			def hook(d):
				status = d.get("status", "")
				percent = 0.0
				if status == "downloading":
					try:
						downloaded = d.get("downloaded_bytes") or 0
						all_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
						if all_bytes:
							percent = max(0.0, min(100.0, (float(downloaded) / float(all_bytes)) * 100.0))
						else:
							percent = float(str(d.get("_percent_str", "0%")).strip().strip("%"))
					except Exception:
						percent = 0.0
				elif status == "finished":
					percent = 100.0
				self.sig_item_progress.emit(idx, percent)
				overall = ((completed + (percent / 100.0)) / max(1, total)) * 100.0
				self.sig_progress.emit(overall)

			selected_quality: Optional[str] = video.get("selected_quality")
			selected_subtitle: Optional[str] = video.get("selected_subtitle")
			res = download_single_video_with_progress(
				url=video["url"],
				output_path=self.output_dir,
				quality=selected_quality,
				subtitle=selected_subtitle,
				audio_only=self.audio_only,
				progress_hook=hook,
			)
			results.append({"url": video["url"], **res})
			if res.get("success"):
				completed += 1
				self.sig_progress.emit((completed / max(1, total)) * 100.0)
			else:
				# continue to next item
				pass

		self.sig_finished.emit({
			"completed": completed,
			"total": total,
			"results": results,
			"cancelled": self._cancelled,
		})


