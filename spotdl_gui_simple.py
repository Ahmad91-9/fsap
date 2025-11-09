"""
Professional PySide6 GUI for spotDL with automatic ffmpeg detection,
song listing, progress tracking, and folder browsing capabilities.

Features:
- Automatic ffmpeg detection in parent directories
- Song listing from URLs
- Browse output folder
- Live download progress updates
- Professional UI design
- Direct integration with spotdl library
"""

import os
import sys
import json
import time
import logging
import subprocess
import re
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
import shutil

from PySide6.QtCore import QObject, QThread, Signal, Slot, QTimer, QSettings
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QWidget,
    QProgressBar,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QGroupBox,
    QSplitter,
    QCheckBox,
    QFrame,
    QScrollArea,
    QMessageBox,
    QComboBox,
    QSpinBox,
)
from PySide6.QtGui import QFont, QIcon, QPixmap, QPalette, QColor
from PySide6.QtCore import Qt

# Import spotdl library components
# Automatically detect spotify-downloader-master folder using same approach as PDFOCR detection
def find_spotdl_path() -> Optional[str]:
    """Find spotify-downloader-master directory using same robust search strategy as PDFOCR detection.
    
    Search strategy (exactly like pdf_urdu_ocr_app.py):
    1. If script directory is already spotify-downloader-master (script is inside it)
    2. Look for spotify-downloader-master folder in the same directory as script
    3. Go up directory tree (up to 5 levels) to find spotify-downloader-master
    4. Search in sys.path entries (crucial when launched from main.py)
    5. Verify with spotdl subdirectory to confirm it's the right folder
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    folder_name = "spotify-downloader-master"
    
    # Strategy 1: Current directory is already spotify-downloader-master (script is inside it)
    if os.path.basename(script_dir) == folder_name:
        spotdl_path = script_dir
        # Verify it contains spotdl module
        spotdl_check = os.path.join(spotdl_path, 'spotdl')
        if os.path.isdir(spotdl_check) and os.path.exists(os.path.join(spotdl_check, '__init__.py')):
            return spotdl_path
    
    # Strategy 2: Look for spotify-downloader-master folder in the same directory as script
    spotdl_same_level = os.path.join(script_dir, folder_name)
    if os.path.isdir(spotdl_same_level):
        # Verify it contains spotdl module
        spotdl_check = os.path.join(spotdl_same_level, 'spotdl')
        if os.path.isdir(spotdl_check) and os.path.exists(os.path.join(spotdl_check, '__init__.py')):
            return spotdl_same_level
    
    # Strategy 3: Go up directory tree to find spotify-downloader-master folder
    current = script_dir
    for _ in range(5):  # Search up to 5 levels
        parent = os.path.dirname(current)
        if parent == current:  # Reached root
            break
        spotdl_in_parent = os.path.join(parent, folder_name)
        if os.path.isdir(spotdl_in_parent):
            # Verify it contains spotdl module
            spotdl_check = os.path.join(spotdl_in_parent, 'spotdl')
            if os.path.isdir(spotdl_check) and os.path.exists(os.path.join(spotdl_check, '__init__.py')):
                return spotdl_in_parent
        current = parent
    
    # Strategy 4: Search in sys.path entries (for when launched from main.py)
    # This is crucial when script is downloaded to temp but main.py root is in sys.path
    for path_entry in sys.path:
        if isinstance(path_entry, str) and os.path.isdir(path_entry):
            spotdl_in_syspath = os.path.join(path_entry, folder_name)
            if os.path.isdir(spotdl_in_syspath):
                # Verify it's the right spotify-downloader-master by checking for spotdl subdirectory
                spotdl_check = os.path.join(spotdl_in_syspath, 'spotdl')
                if os.path.isdir(spotdl_check) and os.path.exists(os.path.join(spotdl_check, '__init__.py')):
                    return spotdl_in_syspath
    
    # Strategy 5: Check if spotdl subdirectory exists nearby (script might be in spotify-downloader-master already)
    spotdl_dir = os.path.join(script_dir, 'spotdl')
    if os.path.isdir(spotdl_dir) and os.path.exists(os.path.join(spotdl_dir, '__init__.py')):
        # Script is likely in spotify-downloader-master already
        return script_dir
    
    return None

# Try to import spotdl, with automatic path detection
try:
    from spotdl.download.downloader import Downloader, DownloaderError
    from spotdl.download.progress_handler import ProgressHandler, SongTracker
    from spotdl.types.song import Song
    from spotdl.utils.search import get_simple_songs
    from spotdl.utils.spotify import SpotifyClient, SpotifyError
    from spotdl.utils.config import DOWNLOADER_OPTIONS, create_settings_type
    from argparse import Namespace
except ImportError:
    # Try to find and add spotify-downloader-master to path
    spotdl_path = find_spotdl_path()
    if spotdl_path and os.path.isdir(spotdl_path):
        # CRITICAL: Remove it first if already in path, then insert at position 0
        # This ensures spotify-downloader-master is FIRST, before other paths
        if spotdl_path in sys.path:
            sys.path.remove(spotdl_path)
        sys.path.insert(0, spotdl_path)
    else:
        # Fallback: try relative to current file
        script_dir = os.path.dirname(os.path.abspath(__file__))
        spotdl_path = os.path.join(script_dir, "spotify-downloader-master")
        if os.path.isdir(spotdl_path):
            if spotdl_path not in sys.path:
                sys.path.insert(0, spotdl_path)
    
    from spotdl.download.downloader import Downloader, DownloaderError
    from spotdl.download.progress_handler import ProgressHandler, SongTracker
    from spotdl.types.song import Song
    from spotdl.utils.search import get_simple_songs
    from spotdl.utils.spotify import SpotifyClient, SpotifyError
    from spotdl.utils.config import DOWNLOADER_OPTIONS, create_settings_type
    from argparse import Namespace


class FFmpegDetector:
    """Utility class for automatic ffmpeg detection in parent directories."""
    
    @staticmethod
    def find_ffmpeg() -> Optional[str]:
        """Find ffmpeg in multiple likely locations (Windows-first), including
        app root next to main.py/main.exe, PATH, env, and current/parent dirs.
        """
        # 1) Explicit environment override
        env_path = os.environ.get("FFMPEG_PATH")
        if env_path and Path(env_path).exists():
            return str(Path(env_path))

        # 2) Check PATH (global install)
        which_path = shutil.which("ffmpeg")
        if which_path:
            return str(Path(which_path))

        # Helper to yield candidate directories to probe
        def candidate_directories() -> List[Path]:
            candidates: List[Path] = []

            # Parent process executable directory (helps when launched by main.exe)
            try:
                ppid = os.getppid()
                if ppid and os.name == "nt":
                    # Try PowerShell first
                    try:
                        ps_cmd = [
                            "powershell",
                            "-NoProfile",
                            "-Command",
                            f"(Get-Process -Id {ppid}).Path"
                        ]
                        r = subprocess.run(ps_cmd, capture_output=True, text=True, timeout=2)
                        parent_path = (r.stdout or "").strip()
                    except Exception:
                        parent_path = ""

                    # Fallback to WMIC if PowerShell path not available
                    if not parent_path:
                        try:
                            wmic_cmd = [
                                "wmic",
                                "process",
                                "where",
                                f"processid={ppid}",
                                "get",
                                "ExecutablePath",
                                "/value",
                            ]
                            r = subprocess.run(wmic_cmd, capture_output=True, text=True, timeout=2)
                            # Output like: ExecutablePath=C:\\path\\to\\main.exe
                            for line in (r.stdout or "").splitlines():
                                line = line.strip()
                                if line.lower().startswith("executablepath="):
                                    parent_path = line.split("=", 1)[1].strip()
                                    break
                        except Exception:
                            parent_path = ""

                    if parent_path:
                        parent_dir = Path(parent_path).resolve().parent
                        candidates.append(parent_dir)
                        candidates.extend(parent_dir.parents)
            except Exception:
                pass

            # Current file and its parents (useful when running from source)
            this_file_dir = Path(__file__).parent
            candidates.append(this_file_dir)
            candidates.extend(this_file_dir.parents)

            # Working directory
            try:
                cwd = Path(os.getcwd())
                candidates.append(cwd)
                candidates.extend(cwd.parents)
            except Exception:
                pass

            # Script path (argv[0])
            try:
                script_dir = Path(sys.argv[0]).resolve().parent
                candidates.append(script_dir)
                candidates.extend(script_dir.parents)
            except Exception:
                pass

            # Executable directory (PyInstaller/frozen apps)
            try:
                exe_dir = Path(sys.executable).resolve().parent
                candidates.append(exe_dir)
                candidates.extend(exe_dir.parents)
            except Exception:
                pass

            # Common env-provided roots from a launcher
            for var in ("APP_ROOT", "MAIN_DIR", "MAIN_APP_DIR", "MAIN_EXE_DIR", "PROGRAM_DIR"):
                val = os.environ.get(var)
                if val:
                    p = Path(val)
                    candidates.append(p)
                    candidates.extend(p.parents)

            # Try to locate a directory that contains a main marker
            for base in list({p for p in candidates}):
                try:
                    for parent in [base, *base.parents]:
                        if (parent / "main.exe").exists() or (parent / "main.py").exists():
                            candidates.append(parent)
                            candidates.extend(parent.parents)
                            break
                except Exception:
                    continue

            # De-duplicate while preserving order
            seen = set()
            unique: List[Path] = []
            for c in candidates:
                if c not in seen:
                    seen.add(c)
                    unique.append(c)
            return unique

        # 3) Probe candidate directories for ffmpeg(.exe)
        exe_names = [
            "ffmpeg.exe",  # Windows
            "ffmpeg",      # POSIX
        ]
        # Prefer directory that contains main.py/main.exe (main app dir)
        for directory in candidate_directories():
            try:
                if (directory / "main.py").exists() or (directory / "main.exe").exists():
                    for name in exe_names:
                        fp = directory / name
                        if fp.exists():
                            return str(fp)
                    for sub in ("bin", "src"):
                        for name in exe_names:
                            fp = directory / sub / name
                            if fp.exists():
                                return str(fp)
            except Exception:
                pass

        for directory in candidate_directories():
            for name in exe_names:
                fp = (directory / name)
                if fp.exists():
                    return str(fp)

            # Also check common subfolder where binaries may reside
            for sub in ("bin", "src"):
                for name in exe_names:
                    fp = directory / sub / name
                    if fp.exists():
                        return str(fp)

        return None
    
    @staticmethod
    def set_ffmpeg_path(ffmpeg_path: str) -> bool:
        """Set ffmpeg path in environment variables."""
        try:
            os.environ["FFMPEG_PATH"] = ffmpeg_path
            return True
        except Exception:
            return False


class SongInfo:
    """Data class for song information."""
    def __init__(self, title: str, artist: str, album: str = "", duration: str = "", url: str = ""):
        self.title = title
        self.artist = artist
        self.album = album
        self.duration = duration
        self.url = url
    
    def __str__(self):
        return f"{self.artist} - {self.title}"
    
    @staticmethod
    def from_song(song: Song) -> "SongInfo":
        """Create SongInfo from spotdl Song object."""
        return SongInfo(
            title=song.name,
            artist=song.artist,
            album=song.album_name,
            duration=str(song.duration) if song.duration else "",
            url=song.url
        )


class SpotdlWorker(QObject):
    finished = Signal()
    errored = Signal(str)
    logged = Signal(str)
    progress_updated = Signal(int, str, int, int)  # progress percentage, current song, current number, total
    songs_found = Signal(list)  # list of SongInfo objects
    download_started = Signal(str, int, int)  # song title, current number, total

    def __init__(self, url: str, output_dir: str = "", ffmpeg_path: str = ""):
        super().__init__()
        self.url = url
        self.output_dir = output_dir
        self.ffmpeg_path = ffmpeg_path
        self.songs: List[Song] = []
        self.current_song_index = 0
        self.total_songs = 0
        self.downloader: Optional[Downloader] = None
        self.is_cancelled = False
        self.current_tracker: Optional[SongTracker] = None
        self.failed_songs: List[str] = []  # Track failed songs for summary
        self.downloading_songs: set = set()  # Track songs that are currently downloading to avoid duplicate logs
        self.converting_songs: set = set()  # Track songs that are currently converting to avoid duplicate logs
        self.completed_count = 0  # Track completed songs for counter
        
        # Initialize Spotify client if not already initialized
        # This will be done lazily when needed in run() or list_songs()
        self._spotify_initialized = False

    @Slot()
    def cancel(self):
        """Cancel the current download properly."""
        self.is_cancelled = True
        self.logged.emit("🛑 Cancelling download...")
        
        # Stop the downloader's event loop if it exists
        if self.downloader and hasattr(self.downloader, 'loop'):
            try:
                import asyncio
                loop = self.downloader.loop
                if loop and loop.is_running():
                    # Cancel all pending tasks
                    tasks = [task for task in asyncio.all_tasks(loop) if not task.done()]
                    for task in tasks:
                        task.cancel()
                    # Stop the loop
                    loop.stop()
            except Exception as e:
                self.logged.emit(f"Error stopping downloader: {e}")

    def _ensure_spotify_client(self):
        """Ensure Spotify client is initialized."""
        if self._spotify_initialized:
            return
        
        try:
            SpotifyClient()
            self._spotify_initialized = True
        except (SpotifyError, Exception):
            # Try to initialize with settings from config or use defaults
            try:
                from spotdl.utils.config import get_config, SPOTIFY_OPTIONS
                
                # Try to get config, but don't fail if it doesn't exist
                try:
                    config = get_config()
                    spotify_settings = config.get("spotify", {})
                    client_id = spotify_settings.get("client_id", "")
                    client_secret = spotify_settings.get("client_secret", "")
                except Exception:
                    # Config file doesn't exist or can't be read, use defaults
                    client_id = ""
                    client_secret = ""
                    spotify_settings = {}
                
                # Use default credentials from SPOTIFY_OPTIONS if not in config
                if not client_id or not client_secret:
                    client_id = SPOTIFY_OPTIONS["client_id"]
                    client_secret = SPOTIFY_OPTIONS["client_secret"]
                    self.logged.emit("ℹ️ Using default Spotify credentials")
                
                SpotifyClient.init(
                    client_id=client_id,
                    client_secret=client_secret,
                    user_auth=spotify_settings.get("user_auth", SPOTIFY_OPTIONS["user_auth"]),
                    headless=spotify_settings.get("headless", True),
                    cache_path=spotify_settings.get("cache_path", SPOTIFY_OPTIONS["cache_path"]),
                    no_cache=spotify_settings.get("no_cache", SPOTIFY_OPTIONS["no_cache"]),
                    max_retries=spotify_settings.get("max_retries", SPOTIFY_OPTIONS["max_retries"]),
                    use_cache_file=spotify_settings.get("use_cache_file", SPOTIFY_OPTIONS["use_cache_file"]),
                )
                self._spotify_initialized = True
            except Exception as e:
                # If initialization still fails, raise a user-friendly error
                raise SpotifyError(
                    f"Failed to initialize Spotify client: {str(e)}\n"
                    "Please ensure you have a valid internet connection and try again."
                )

    @Slot()
    def list_songs(self):
        """List songs from the URL without downloading."""
        try:
            self._ensure_spotify_client()
            self.logged.emit("🔍 Fetching songs from URL...")
            
            # Use spotdl's get_simple_songs to get songs from URL
            songs = get_simple_songs(
                [self.url],
                use_ytm_data=False,
                playlist_numbering=False,
                album_type=None,
                playlist_retain_track_cover=False,
            )
            
            if not songs:
                self.errored.emit("No songs found for the given URL.")
                return

            # Convert to SongInfo objects
            song_infos = [SongInfo.from_song(song) for song in songs]
            
            self.songs = songs
            self.total_songs = len(songs)
            self.songs_found.emit(song_infos)
            self.logged.emit(f"✅ Found {len(songs)} song(s)")

        except Exception as exc:
            self.errored.emit(f"Failed to list songs: {str(exc)}")
        finally:
            # Always signal completion so UI can re-enable controls
            self.finished.emit()

    def progress_callback(self, tracker: SongTracker, message: str):
        """Custom progress callback for GUI updates."""
        if self.is_cancelled:
            # Raise exception to stop the download
            raise KeyboardInterrupt("Download cancelled by user")
        
        song_name = tracker.song.display_name
        progress = tracker.progress
        
        # Find current song index
        try:
            current_index = next(
                (i for i, song in enumerate(self.songs) if song.url == tracker.song.url),
                0
            )
            self.current_song_index = current_index
        except:
            pass
        
        # Calculate current song number (1-based) and remaining
        current_number = self.current_song_index + 1
        remaining = max(0, self.total_songs - self.completed_count)
        
        # Update current song label
        if message and message != "Processing":
            status_emoji = ""
            if "Downloading" in message:
                # Only log downloading once per song
                if song_name not in self.downloading_songs:
                    status_emoji = "⬇️"
                    self.downloading_songs.add(song_name)
                    self.download_started.emit(song_name, current_number, self.total_songs)
                    # Show with counter: "Downloading 1/167: Song Name"
                    self.logged.emit(f"⬇️ Downloading {current_number}/{self.total_songs}: {song_name}")
            elif "Converting" in message:
                # Only log converting once per song
                if song_name not in self.converting_songs:
                    status_emoji = "🔄"
                    self.converting_songs.add(song_name)
                    self.logged.emit(f"🔄 Converting {current_number}/{self.total_songs}: {song_name}")
            elif "Embedding" in message:
                status_emoji = "💾"
                # Remove from converting set when embedding starts
                self.converting_songs.discard(song_name)
                self.logged.emit(f"💾 Embedding metadata {current_number}/{self.total_songs}: {song_name}")
            elif "Done" in message or "Complete" in message or "Skipped" in message:
                status_emoji = "✅"
                self.completed_count += 1
                self.current_song_index += 1
                # Remove from downloading and converting sets
                self.downloading_songs.discard(song_name)
                self.converting_songs.discard(song_name)
                remaining = max(0, self.total_songs - self.completed_count)
                self.logged.emit(f"✅ Completed {self.completed_count}/{self.total_songs} ({remaining} remaining): {song_name}")
            elif "Error" in message:
                status_emoji = "❌"
                self.completed_count += 1
                self.current_song_index += 1
                # Remove from downloading and converting sets
                self.downloading_songs.discard(song_name)
                self.converting_songs.discard(song_name)
                # Track failed songs
                if song_name not in self.failed_songs:
                    self.failed_songs.append(song_name)
                remaining = max(0, self.total_songs - self.completed_count)
                # Show more user-friendly error message with counter
                if "No results found" in message or "LookupError" in message:
                    self.logged.emit(f"❌ Failed {self.completed_count}/{self.total_songs} ({remaining} remaining): {song_name} - Not available on YouTube/SoundCloud")
                else:
                    self.logged.emit(f"❌ Failed {self.completed_count}/{self.total_songs} ({remaining} remaining): {song_name} - {message}")
        
        # Calculate overall progress
        if self.total_songs > 0:
            # Progress is 0-100 per song, so we need to calculate overall
            base_progress = (self.current_song_index * 100)
            current_song_progress = min(progress, 100)
            overall_progress = int((base_progress + current_song_progress) / self.total_songs)
            self.progress_updated.emit(overall_progress, song_name, current_number, self.total_songs)

    @Slot()
    def run(self):
        """Download songs directly from URL using spotdl library."""
        try:
            # Add SSL certificate fix for Windows
            try:
                import certifi
                os.environ["SSL_CERT_FILE"] = certifi.where()
            except ImportError:
                pass
            
            self._ensure_spotify_client()
            self.logged.emit("🔍 Fetching songs from URL...")
            
            # Get songs from URL
            songs = get_simple_songs(
                [self.url],
                use_ytm_data=False,
                playlist_numbering=False,
                album_type=None,
                playlist_retain_track_cover=False,
            )
            
            if not songs:
                self.errored.emit("No songs found for the given URL.")
                self.finished.emit()
                return
            
            self.songs = songs
            self.total_songs = len(songs)
            self.failed_songs = []  # Reset failed songs list for this download
            self.downloading_songs = set()  # Reset downloading songs set
            self.converting_songs = set()  # Reset converting songs set
            self.completed_count = 0  # Reset completed count
            self.logged.emit(f"✅ Found {len(songs)} song(s)")
            
            # Get playlist/album name from first song if available
            playlist_name = None
            if songs and hasattr(songs[0], 'list_name') and songs[0].list_name:
                playlist_name = songs[0].list_name
            elif "playlist" in self.url.lower():
                # Try to extract playlist name from URL or fetch it
                try:
                    from spotdl.types.playlist import Playlist
                    playlist = Playlist.from_url(self.url, fetch_songs=False)
                    playlist_name = playlist.name
                except:
                    playlist_name = "Playlist"
            elif "album" in self.url.lower():
                try:
                    from spotdl.types.album import Album
                    album = Album.from_url(self.url, fetch_songs=False)
                    playlist_name = album.name
                except:
                    playlist_name = "Album"
            else:
                playlist_name = "Downloads"
            
            # Sanitize playlist name for folder name (remove invalid characters)
            safe_playlist_name = re.sub(r'[<>:"/\\|?*]', '', playlist_name)
            safe_playlist_name = safe_playlist_name.strip()
            if not safe_playlist_name:
                safe_playlist_name = "Downloads"
            
            # Prepare downloader settings
            # If output_dir is specified, create playlist folder inside it
            if self.output_dir:
                # Create playlist folder in output directory
                playlist_folder = Path(self.output_dir) / safe_playlist_name
                playlist_folder.mkdir(parents=True, exist_ok=True)
                output_template = str(playlist_folder / "{artist} - {title}.{output-ext}")
                self.logged.emit(f"📁 Saving to: {playlist_folder}")
            else:
                # Use current directory with playlist folder
                playlist_folder = Path.cwd() / safe_playlist_name
                playlist_folder.mkdir(parents=True, exist_ok=True)
                output_template = str(playlist_folder / "{artist} - {title}.{output-ext}")
                self.logged.emit(f"📁 Saving to: {playlist_folder}")
            
            # Create downloader settings
            # Use multiple audio providers as fallback for better success rate
            downloader_settings = {
                "output": output_template,
                "ffmpeg": self.ffmpeg_path if self.ffmpeg_path else "ffmpeg",
                "format": "mp3",
                "bitrate": "auto",
                "threads": 1,  # Single thread for better GUI responsiveness
                "simple_tui": True,  # Use simple TUI mode
                "overwrite": "skip",
                "scan_for_songs": False,
                "audio_providers": ["youtube-music", "youtube", "soundcloud"],  # Multiple providers as fallback
                "lyrics_providers": [],
                "log_level": "ERROR",  # Reduce logging noise
                "filter_results": False,  # Don't filter results - try to find any match
                "only_verified_results": False,  # Allow unverified results
            }
            
            # Create settings with defaults
            settings_dict = create_settings_type(
                Namespace(config=False),
                downloader_settings,
                DOWNLOADER_OPTIONS
            )
            
            # Create custom progress handler with callback
            progress_handler = ProgressHandler(
                simple_tui=True,
                update_callback=self.progress_callback,
                web_ui=False
            )
            
            # Initialize downloader
            self.downloader = Downloader(settings_dict)
            # Replace the progress handler with our custom one
            self.downloader.progress_handler = progress_handler
            
            self.logged.emit(f"⬇️ Starting download of {len(songs)} song(s)...")
            
            # Download songs with cancellation support
            results = []
            try:
                # Check for cancellation before starting
                if self.is_cancelled:
                    raise KeyboardInterrupt("Download cancelled")
                
                # Download songs - wrap in a way that allows cancellation
                # The progress_callback will check is_cancelled and raise exception
                results = self.downloader.download_multiple_songs(songs)
                
                # Check cancellation after download completes
                if self.is_cancelled:
                    self.logged.emit("❌ Download cancelled")
                    self.finished.emit()
                    return
                    
            except (KeyboardInterrupt, asyncio.CancelledError) as exc:
                if self.is_cancelled or "cancelled" in str(exc).lower():
                    self.logged.emit("❌ Download cancelled by user")
                    # Clean up any partial downloads
                    if self.downloader and hasattr(self.downloader, 'loop'):
                        try:
                            import asyncio
                            loop = self.downloader.loop
                            if loop:
                                # Cancel all pending tasks
                                tasks = [task for task in asyncio.all_tasks(loop) if not task.done()]
                                for task in tasks:
                                    task.cancel()
                        except:
                            pass
                    self.finished.emit()
                    return
                else:
                    # Re-raise if it's not a cancellation
                    raise
            except Exception as exc:
                # Handle other exceptions
                if self.is_cancelled:
                    self.logged.emit("❌ Download cancelled")
                    self.finished.emit()
                    return
                raise
            
            # Check results
            successful = sum(1 for _, path in results if path is not None)
            failed = len(results) - successful
            
            if self.is_cancelled:
                self.logged.emit("❌ Download cancelled")
            elif failed > 0:
                self.logged.emit(f"⚠️ Download completed: {successful} successful, {failed} failed")
                if self.failed_songs:
                    self.logged.emit(f"📋 Failed songs ({len(self.failed_songs)}):")
                    for failed_song in self.failed_songs[:10]:  # Show first 10 failed songs
                        self.logged.emit(f"   • {failed_song}")
                    if len(self.failed_songs) > 10:
                        self.logged.emit(f"   ... and {len(self.failed_songs) - 10} more")
                    self.logged.emit("💡 Tip: Some songs may not be available on YouTube/SoundCloud (remixes, slowed versions, etc.)")
            else:
                self.logged.emit(f"✅ Download completed successfully! ({successful} songs)")
            
            # Clean up
            if self.downloader:
                self.downloader.progress_handler.close()

            self.finished.emit()
            
        except Exception as exc:
            error_msg = f"❌ Error: {str(exc)}"
            self.errored.emit(error_msg)
            self.logged.emit(error_msg)
            if self.downloader:
                try:
                    self.downloader.progress_handler.close()
                except:
                    pass
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("spotDL Professional - Music Downloader")
        self.setMinimumSize(1000, 700)
        
        # Initialize settings
        self.settings = QSettings("spotDL", "Professional")
        
        # Initialize ffmpeg path
        self.ffmpeg_path = FFmpegDetector.find_ffmpeg()
        if self.ffmpeg_path:
            FFmpegDetector.set_ffmpeg_path(self.ffmpeg_path)
        
        # Initialize worker
        self.worker_thread: Optional[QThread] = None
        self.worker: Optional[SpotdlWorker] = None
        self.songs = []
        self.is_downloading = False
        
        # Timer for frequent log updates
        self.log_timer = QTimer()
        self.log_timer.timeout.connect(self.force_log_update)
        self.log_timer.setInterval(1000)  # Update every second
        
        self.setup_ui()
        self.apply_styles()
        self.load_settings()

    def setup_ui(self):
        """Setup the professional UI layout."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # Header
        self.create_header(main_layout)
        
        # URL input section
        self.create_url_section(main_layout)
        
        # Output folder section
        self.create_output_section(main_layout)
        
        # FFmpeg status
        self.create_ffmpeg_section(main_layout)
        
        # Progress and log section
        self.create_progress_section(main_layout)
        
        # Control buttons
        self.create_control_buttons(main_layout)

    def create_header(self, layout):
        """Create the header section."""
        header_frame = QFrame()
        header_frame.setFrameStyle(QFrame.Box)
        header_layout = QHBoxLayout(header_frame)
        
        title_label = QLabel("🎵 spotDL Professional")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        status_label = QLabel("Ready")
        status_label.setStyleSheet("color: green; font-weight: bold;")
        self.status_label = status_label
        header_layout.addWidget(status_label)
        
        layout.addWidget(header_frame)

    def create_url_section(self, layout):
        """Create URL input section."""
        url_group = QGroupBox("Enter Spotify URL (playlist/album/track)")
        url_layout = QVBoxLayout(url_group)
        
        url_input_layout = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://open.spotify.com/playlist/... or track/album URL")
        self.url_edit.returnPressed.connect(self.start_download)
        url_input_layout.addWidget(self.url_edit)
        
        self.download_btn = QPushButton("Download All")
        self.download_btn.clicked.connect(self.start_download)
        self.download_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #666666;
            }
        """)
        url_input_layout.addWidget(self.download_btn)
        
        url_layout.addLayout(url_input_layout)
        layout.addWidget(url_group)

    def create_output_section(self, layout):
        """Create output folder selection section."""
        output_group = QGroupBox("Output Folder")
        output_layout = QHBoxLayout(output_group)
        
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("Select output folder for downloads...")
        self.output_path_edit.setText(self.settings.value("output_path", ""))
        output_layout.addWidget(self.output_path_edit)
        
        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self.browse_output_folder)
        self.browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        output_layout.addWidget(self.browse_btn)
        
        layout.addWidget(output_group)

    def create_ffmpeg_section(self, layout):
        """Create FFmpeg status section."""
        ffmpeg_group = QGroupBox("FFmpeg Status")
        ffmpeg_layout = QHBoxLayout(ffmpeg_group)
        
        if self.ffmpeg_path:
            ffmpeg_label = QLabel(f"✅ FFmpeg found: {self.ffmpeg_path}")
            ffmpeg_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            ffmpeg_label = QLabel("❌ FFmpeg not found - please ensure ffmpeg.exe is in the application directory")
            ffmpeg_label.setStyleSheet("color: red; font-weight: bold;")
        
        ffmpeg_layout.addWidget(ffmpeg_label)
        ffmpeg_layout.addStretch()
        
        layout.addWidget(ffmpeg_group)


    def create_progress_section(self, layout):
        """Create progress and log section."""
        # Progress section
        progress_group = QGroupBox("Download Progress")
        progress_group_layout = QVBoxLayout(progress_group)
        
        # Playlist/Song title display
        self.title_label = QLabel("")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #2196F3;")
        self.title_label.setVisible(False)
        progress_group_layout.addWidget(self.title_label)
        
        
        self.current_song_label = QLabel("")
        self.current_song_label.setStyleSheet("font-weight: bold; color: #2196F3;")
        self.current_song_label.setVisible(False)
        progress_group_layout.addWidget(self.current_song_label)
        
        layout.addWidget(progress_group)
        
        # Log section
        log_group = QGroupBox("Download Log")
        log_group_layout = QVBoxLayout(log_group)
        
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(200)
        log_group_layout.addWidget(self.log_view)
        
        layout.addWidget(log_group)

    def create_control_buttons(self, layout):
        """Create control buttons."""
        button_layout = QHBoxLayout()
        
        self.cancel_btn = QPushButton("Cancel Download")
        self.cancel_btn.clicked.connect(self.cancel_download)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #f57c00;
            }
            QPushButton:disabled {
                background-color: #333333;
                color: #666666;
            }
        """)
        button_layout.addWidget(self.cancel_btn)
        
        button_layout.addStretch()
        
        self.clear_btn = QPushButton("Clear Log")
        self.clear_btn.clicked.connect(self.clear_log)
        button_layout.addWidget(self.clear_btn)
        
        self.close_btn = QPushButton("Exit")
        self.close_btn.clicked.connect(self.close)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)

    def apply_styles(self):
        """Apply professional styling to the application."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #000000;
                color: #ffffff;
            }
            QWidget {
                background-color: #000000;
                color: #ffffff;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #333333;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: #111111;
                color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #ffffff;
            }
            QLineEdit {
                padding: 8px;
                border: 2px solid #333333;
                border-radius: 4px;
                font-size: 12px;
                background-color: #111111;
                color: #ffffff;
            }
            QLineEdit:focus {
                border-color: #2196F3;
            }
            QListWidget {
                border: 1px solid #333333;
                border-radius: 4px;
                background-color: #111111;
                color: #ffffff;
                alternate-background-color: #222222;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #333333;
                color: #ffffff;
            }
            QListWidget::item:selected {
                background-color: #2196F3;
                color: #ffffff;
            }
            QTextEdit {
                border: 1px solid #333333;
                border-radius: 4px;
                background-color: #000000;
                color: #ffffff;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11px;
            }
            QProgressBar {
                border: 2px solid #333333;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
                background-color: #111111;
                color: #ffffff;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 3px;
            }
            QLabel {
                color: #ffffff;
            }
            QPushButton {
                background-color: #333333;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #444444;
            }
            QPushButton:disabled {
                background-color: #222222;
                color: #666666;
            }
        """)

    def load_settings(self):
        """Load saved settings."""
        output_path = self.settings.value("output_path", "")
        if output_path:
            self.output_path_edit.setText(output_path)

    def save_settings(self):
        """Save current settings."""
        self.settings.setValue("output_path", self.output_path_edit.text())

    @Slot()
    def browse_output_folder(self):
        """Open folder browser for output directory."""
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_path_edit.setText(folder)
            self.save_settings()

    def extract_title_from_url(self, url):
        """Extract a simple title from Spotify URL for display."""
        try:
            if "playlist" in url:
                return "Spotify Playlist"
            elif "album" in url:
                return "Spotify Album"
            elif "track" in url:
                return "Spotify Track"
            else:
                return "Spotify Content"
        except:
            return "Spotify Content"


    @Slot()
    def start_download(self):
        """Start downloading all songs from the URL."""
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Warning", "Please enter a Spotify URL.")
            return
        if not (url.startswith("https://open.spotify.com/") or url.startswith("spotify:")):
            QMessageBox.warning(self, "Warning", "Only Spotify URLs are supported.")
            return

        # Show title
        title = self.extract_title_from_url(url)
        self.title_label.setText(f"Downloading: {title}")
        self.title_label.setVisible(True)
        self.current_song_label.setVisible(True)

        self.download_btn.setEnabled(False)
        self.status_label.setText("Downloading...")
        self.status_label.setStyleSheet("color: orange; font-weight: bold;")
        
        self.append_log("🔍 Fetching your Link Data...")

        # Set downloading state
        self.is_downloading = True
        self.cancel_btn.setEnabled(True)

        # Create worker for direct download
        self.worker_thread = QThread()
        self.worker = SpotdlWorker(url, self.output_path_edit.text(), self.ffmpeg_path)
        self.worker.moveToThread(self.worker_thread)
        
        self.worker_thread.started.connect(self.worker.run)
        self.worker.logged.connect(self.append_log)
        self.worker.errored.connect(self.on_error)
        self.worker.download_started.connect(self.on_download_started)
        self.worker.progress_updated.connect(self.update_progress)
        self.worker.finished.connect(self.on_download_finished)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        
        self.worker_thread.start()
        
        # Start the log update timer
        self.log_timer.start()

    def force_log_update(self):
        """Force log view to update and scroll to bottom."""
        if self.is_downloading:
            # Force the log view to update and scroll
            self.log_view.verticalScrollBar().setValue(
                self.log_view.verticalScrollBar().maximum()
            )
            # Process any pending events to ensure UI updates
            QApplication.processEvents()

    @Slot(int, str, int, int)
    def update_progress(self, progress, song_title, current_number, total):
        """Update download progress."""
        remaining = total - current_number + 1
        self.current_song_label.setText(f"Downloading {current_number}/{total} ({remaining} remaining): {song_title}")

    @Slot(str, int, int)
    def on_download_started(self, song_title, current_number, total):
        """Handle when a song download starts."""
        remaining = total - current_number + 1
        self.current_song_label.setText(f"Downloading {current_number}/{total} ({remaining} remaining): {song_title}")

    @Slot()
    def cancel_download(self):
        """Cancel the current download."""
        if self.is_downloading and self.worker:
            self.append_log("❌ Cancelling download...")
            self.worker.cancel()
            self.is_downloading = False
            self.cancel_btn.setEnabled(False)
            self.download_btn.setEnabled(True)
            self.current_song_label.setVisible(False)
            self.title_label.setVisible(False)
            self.status_label.setText("Download cancelled")
            self.status_label.setStyleSheet("color: orange; font-weight: bold;")
            # Stop the log update timer
            self.log_timer.stop()

    @Slot()
    def on_download_finished(self):
        """Handle when download is finished."""
        self.is_downloading = False
        self.cancel_btn.setEnabled(False)
        self.download_btn.setEnabled(True)
        self.current_song_label.setVisible(False)
        self.title_label.setVisible(False)
        self.status_label.setText("Download completed!")
        self.status_label.setStyleSheet("color: green; font-weight: bold;")
        # Stop the log update timer
        self.log_timer.stop()

    @Slot(str)
    def on_error(self, error_message):
        """Handle errors."""
        self.append_log(f"❌ {error_message}")
        self.is_downloading = False
        self.cancel_btn.setEnabled(False)
        self.download_btn.setEnabled(True)
        self.current_song_label.setVisible(False)
        self.title_label.setVisible(False)
        self.status_label.setText("Error occurred")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        # Stop the log update timer
        self.log_timer.stop()

    @Slot()
    def clear_log(self):
        """Clear the log view."""
        self.log_view.clear()

    @Slot(str)
    def append_log(self, message: str):
        """Append message to log view with immediate update."""
        timestamp = time.strftime("%H:%M:%S")
        self.log_view.append(f"[{timestamp}] {message}")
        # Force immediate UI update
        QApplication.processEvents()
        # Auto-scroll to bottom
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum()
        )

    def closeEvent(self, event):
        """Handle application close event."""
        if self.is_downloading and self.worker:
            # Cancel any ongoing download
            self.append_log("Application closing - cancelling download...")
            self.worker.cancel()
            
            # Close downloader if it exists
            if self.worker.downloader:
                try:
                    self.worker.downloader.progress_handler.close()
                except:
                    pass
        
        self.save_settings()
        event.accept()


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    app.setApplicationName("spotDL Professional")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("spotDL")
    
    # Set application style
    app.setStyle('Fusion')
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()


