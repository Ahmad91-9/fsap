from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from downloader_core import get_content_type, fetch_video_info, fetch_playlist_info


class YouTubeInfoWorker(QObject):
	sig_info = Signal(dict)  # emits info dict from downloader_core
	sig_error = Signal(str)

	def __init__(self, url: str, audio_only: bool) -> None:
		super().__init__()
		self.url = url
		self.audio_only = audio_only

	def run(self) -> None:
		try:
			content_type = get_content_type(self.url)
			if content_type in ["playlist", "channel"]:
				info = fetch_playlist_info(self.url, self.audio_only)
			else:
				info = fetch_video_info(self.url, self.audio_only)
			self.sig_info.emit(info)
		except Exception as e:
			self.sig_error.emit(str(e))


