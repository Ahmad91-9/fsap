from PySide6.QtWidgets import QWidget

from widgets.unified_downloader_gui import UnifiedDownloaderGUI


class TikTokWidget(UnifiedDownloaderGUI):
	def __init__(self, ffmpeg_location: str | None, parent: QWidget | None = None) -> None:
		super().__init__(
			title="TikTok Downloader",
			allowed_hosts=["tiktok.com", "vt.tiktok.com"],
			parent=parent,
		)


