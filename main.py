import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from downloaders.instagram import InstagramWidget
from downloaders.facebook import FacebookWidget
from downloaders.tiktok import TikTokWidget
from downloaders.dailymotion import DailymotionWidget
from downloaders.soundcloud import SoundCloudWidget
from downloaders.vimeo import VimeoWidget
from downloaders.twitch import TwitchWidget
from downloaders.reddit import RedditWidget
from downloaders.bandcamp import BandcampWidget
from youtube_downloader_gui_patched_fixed_corrected import YouTubeDownloaderGUI


def discover_ffmpeg_location() -> str | None:
	"""
	Attempt to find ffmpeg next to this script.
	Returns a string path or None if not found.
	"""
	app_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)).resolve()
	candidates = [
		app_dir / "ffmpeg.exe",  # Windows common
		app_dir / "ffmpeg",      # Unix-like
	]
	for p in candidates:
		if p.exists():
			return str(p.parent)
	return None


class MainWindow(QMainWindow):
	def __init__(self) -> None:
		super().__init__()
		self.setWindowTitle("All Media Downloader")
		self.resize(750, 500)

		self.tabs = QTabWidget(self)
		self.setCentralWidget(self.tabs)

		ffmpeg_location = discover_ffmpeg_location()

		# Instantiate each platform widget, passing ffmpeg location
		self.tabs.addTab(InstagramWidget(ffmpeg_location), "Instagram")
		self.tabs.addTab(FacebookWidget(ffmpeg_location), "Facebook")
		self.tabs.addTab(TikTokWidget(ffmpeg_location), "TikTok")
		self.tabs.addTab(DailymotionWidget(ffmpeg_location), "Dailymotion")
		self.tabs.addTab(SoundCloudWidget(ffmpeg_location), "SoundCloud")
		self.tabs.addTab(VimeoWidget(ffmpeg_location), "Vimeo")
		self.tabs.addTab(TwitchWidget(ffmpeg_location), "Twitch")
		self.tabs.addTab(RedditWidget(ffmpeg_location), "Reddit")
		self.tabs.addTab(BandcampWidget(ffmpeg_location), "Bandcamp")
		self.tabs.addTab(YouTubeDownloaderGUI(), "YouTube")

		# All content now runs within a single window (no extra YouTube window)


def main() -> None:
	app = QApplication(sys.argv)
	# Apply a simple, modern stylesheet
	app.setStyle("Fusion")
	app.setStyleSheet("""
		QMainWindow { background: #0f1420; color: #e6e9ef; }
		QTabWidget::pane { border: 1px solid #2c3448; border-radius: 6px; }
		QTabBar::tab { background: #1a2030; color: #d0d6e2; padding: 8px 14px; margin: 2px; border-radius: 4px; }
		QTabBar::tab:selected { background: #2a3246; color: #ffffff; }
		QLabel { color: #d0d6e2; }
		QLineEdit { background: #121827; color: #e6e9ef; border: 1px solid #2c3448; border-radius: 4px; padding: 6px; }
		QComboBox { background: #121827; color: #e6e9ef; border: 1px solid #2c3448; border-radius: 4px; padding: 4px; }
		QPushButton { background: #2a60ff; color: white; border: none; border-radius: 4px; padding: 8px 14px; }
		QPushButton:hover { background: #3b6dff; }
		QPushButton:disabled { background: #39435c; color: #9aa3b2; }
		QProgressBar { background: #121827; border: 1px solid #2c3448; border-radius: 4px; color: #e6e9ef; text-align: center; }
		QProgressBar::chunk { background-color: #2a60ff; }
		QFileDialog { background: #0f1420; }
	""")
	win = MainWindow()
	win.show()
	sys.exit(app.exec())


if __name__ == "__main__":
	main()


