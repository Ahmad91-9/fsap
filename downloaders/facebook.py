from PySide6.QtWidgets import QWidget

from widgets.unified_downloader_gui import UnifiedDownloaderGUI


class FacebookWidget(UnifiedDownloaderGUI):
	def __init__(self, ffmpeg_location: str | None, parent: QWidget | None = None) -> None:
		super().__init__(
			title="Facebook Downloader",
			allowed_hosts=["facebook.com", "fb.watch"],
			parent=parent,
		)


