from PySide6.QtWidgets import QWidget
from widgets.unified_downloader_gui import UnifiedDownloaderGUI


class InstagramWidget(UnifiedDownloaderGUI):
	def __init__(self, ffmpeg_location: str | None, parent: QWidget | None = None) -> None:
		super().__init__(
			title="Instagram Downloader",
			allowed_hosts=["instagram.com"],
			parent=parent,
		)


