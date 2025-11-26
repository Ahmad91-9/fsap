from PySide6.QtWidgets import QWidget
from widgets.unified_downloader_gui import UnifiedDownloaderGUI


class SoundCloudWidget(UnifiedDownloaderGUI):
	def __init__(self, ffmpeg_location: str | None, parent: QWidget | None = None) -> None:
		super().__init__(
			title="SoundCloud Downloader",
			allowed_hosts=["soundcloud.com"],
			parent=parent,
		)


