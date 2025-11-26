from PySide6.QtWidgets import QWidget

from widgets.unified_downloader_gui import UnifiedDownloaderGUI


class DailymotionWidget(UnifiedDownloaderGUI):
	def __init__(self, ffmpeg_location: str | None, parent: QWidget | None = None) -> None:
		super().__init__(
			title="Dailymotion Downloader",
			allowed_hosts=["dailymotion.com", "dai.ly"],
			parent=parent,
		)


