from PySide6.QtWidgets import QWidget

from widgets.unified_downloader_gui import UnifiedDownloaderGUI


class RedditWidget(UnifiedDownloaderGUI):
	def __init__(self, ffmpeg_location: str | None, parent: QWidget | None = None) -> None:
		super().__init__(
			title="Reddit Downloader",
			allowed_hosts=["reddit.com", "redd.it", "v.redd.it"],
			parent=parent,
		)


