from PySide6.QtWidgets import QWidget

from widgets.unified_downloader_gui import UnifiedDownloaderGUI


class VimeoWidget(UnifiedDownloaderGUI):
	def __init__(self, ffmpeg_location: str | None, parent: QWidget | None = None) -> None:
		super().__init__(
			title="Vimeo Downloader",
			allowed_hosts=["vimeo.com", "player.vimeo.com"],
			parent=parent,
		)


