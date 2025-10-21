# Configuration (hardcoded)
# Firebase / Google API
FIREBASE_API_KEY = "AIzaSyBwR56UKtgCSpScPbZsicLKm3gADPedb5o"
FIREBASE_PROJECT_ID = "rbpkorderdb"

# File cache path for id token caching
from pathlib import Path
CACHE_PATH = Path.home() / ".rbpk_auth_cache.json"

# Helper function to get icon QPixmap for app launcher
def get_app_icon(icon_data: str):
    """
    Get QPixmap for app icon from binary data or file path
    
    Args:
        icon_data: Either binary data string or file path
        
    Returns:
        QPixmap object for the icon
    """
    from PySide6.QtGui import QPixmap
    from PySide6.QtCore import QByteArray
    import base64
    
    try:
        # Check if it's binary data (base64 encoded)
        if icon_data.startswith("data:image/") or len(icon_data) > 100:
            # It's likely binary data
            if icon_data.startswith("data:image/"):
                # Handle data URL format: "[REMOVED_BASE64_IMAGE]"...
                header, data = icon_data.split(",", 1)
                binary_data = base64.b64decode(data)
            else:
                # Assume it's raw base64 data
                binary_data = base64.b64decode(icon_data)
            
            pixmap = QPixmap()
            pixmap.loadFromData(binary_data)
            return pixmap
        else:
            # It's a file path
            return QPixmap(icon_data)
    except Exception as e:
        # Fallback: return empty pixmap
        return QPixmap()

# Apps listed for the launcher
# Original format (name, icon_data, url_or_path, is_local)
# We now split into two separate lists for clarity:
#   - GITHUB_APPS: entries with remote raw URLs (is_local == False)
#   - LOCAL_APPS: entries with local script paths (is_local == True)

LOCAL_APPS = [
    ("YouTube Downloader Professional", "[REMOVED_BASE64_IMAGE]", "youtube_downloader_gui_patched_fixed_corrected.py"),
    ("PDF and Word Watermark Remover", "[REMOVED_BASE64_IMAGE]", "PDF_word Watermarkremover/prod.py"),
    ("PDF OCR for Urdu", "[REMOVED_BASE64_IMAGE]", "PDFOCR/pdf_urdu_ocr_app.py"),
    ("Spotify Downloader", "[REMOVED_BASE64_IMAGE]", "spotdl_gui_simple.py"),
    ("Archive Downloader", "[REMOVED_BASE64_IMAGE]", "archivedownloader.py"),
    ("Anime Upscaler", "[REMOVED_BASE64_IMAGE]", "Anime_Upscaler.py"),
]

GITHUB_APPS = [
    ("RBPK Automation App", "[REMOVED_BASE64_IMAGE]", "https://raw.githubusercontent.com/Ahmad91-9/rbpk-script/main/rbpk.py"),
    ("PDF Delete_Erase text", "[REMOVED_BASE64_IMAGE]", "https://raw.githubusercontent.com/Ahmad91-9/cf/blob/main/pageremoverpdf.py"),
]

# Helper getters for external imports
def get_github_apps():
    return GITHUB_APPS


def get_local_apps():
    return LOCAL_APPS
        

# Keep track of temporary signups to clean up if user abandons registration
_TEMP_SIGNUPS = []  # list of tuples (idToken, localId)
