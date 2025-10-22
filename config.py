# config.py
"""
Application configuration for RBPK launcher.

Provides:
- Dictionary-style app definitions for scalability
- Backwards-compatible LOCAL_APPS and GITHUB_APPS tuple lists
- get_app_icon utility for QPixmap loading
- get_local_apps(), get_github_apps() helpers
- CACHE_PATH constant
"""

from pathlib import Path
import base64
import os

# Firebase / Google API (kept from original)
FIREBASE_API_KEY = "AIzaSyBwR56UKtgCSpScPbZsicLKm3gADPedb5o"
FIREBASE_PROJECT_ID = "rbpkorderdb"

# File cache path for id token caching
CACHE_PATH = Path.home() / ".rbpk_auth_cache.json"

# ----------------- New structured config -----------------

# Use dictionary entries for readability & extensibility.
# Fields (recommended):
#   - name: display name
#   - icon: base64 image or path (string)
#   - type: "local" | "pyside6_gui" | "console"
#   - entry: local path (for local) OR url (for github/raw)
#   - version: optional semantic version
#   - description: optional short description

LOCAL_APPS_DICT = [
    {
        "name": "YouTube Downloader Professional",
        "icon": "[REMOVED_BASE64_IMAGE]",
        "type": "local",
        "entry": "youtube_downloader_gui_patched_fixed_corrected.py",
        "description": "Local patched YouTube downloader GUI"
    },
    {
        "name": "PDF and Word Watermark Remover",
        "icon": "[REMOVED_BASE64_IMAGE]",
        "type": "local",
        "entry": "PDF_word Watermarkremover/prod.py",
        "description": "Local PDF & Word watermark remover"
    },
    {
        "name": "PDF OCR for Urdu",
        "icon": "[REMOVED_BASE64_IMAGE]",
        "type": "local",
        "entry": "PDFOCR/pdf_urdu_ocr_app.py",
        "description": "Local OCR app for Urdu PDFs"
    },
    {
        "name": "Spotify Downloader",
        "icon": "[REMOVED_BASE64_IMAGE]",
        "type": "local",
        "entry": "spotdl_gui_simple.py",
        "description": "Local Spotify downloader GUI"
    },
    {
        "name": "Archive Downloader",
        "icon": "[REMOVED_BASE64_IMAGE]",
        "type": "local",
        "entry": "archivedownloader.py",
        "description": "Local downloader for archives"
    },
    {
        "name": "Anime Upscaler",
        "icon": "[REMOVED_BASE64_IMAGE]",
        "type": "local",
        "entry": "Anime_Upscaler.py",
        "description": "Local anime upscaler GUI"
    },
    {
        "name": "PDF Delete_Erase text",
        "icon": "[REMOVED_BASE64_IMAGE]",
        "type": "local",
        "entry": "pageremoverpdf.py",
        "description": "Remove text from PDF pages"
    }
]

GITHUB_APPS_DICT = [
    {
        "name": "RBPK Automation App",
        "icon": "[REMOVED_BASE64_IMAGE]",
        "type": "pyside6_gui",
        "entry": "https://raw.githubusercontent.com/Ahmad91-9/rbpk-script/main/rbpk.py",
        "version": "0.0.0",
        "description": "Remote RBPK automation PySide6 app (raw .py)"
    }
]

# ---------------- Compatibility: legacy tuple lists ----------------
# Many parts of your codebase may expect the old tuple format
# (name, icon, path_or_url). We provide these derived variables
# so older code won't crash.

# Convert dicts to legacy tuples for compatibility
LOCAL_APPS = [
    (a.get("name"), a.get("icon"), a.get("entry"))
    for a in LOCAL_APPS_DICT
]

GITHUB_APPS = [
    (a.get("name"), a.get("icon"), a.get("entry"))
    for a in GITHUB_APPS_DICT
]

# ---------------- Helper getters ----------------

def get_local_apps():
    """
    Return the modern dict list of local apps.
    If a caller expects the legacy tuple list, see LOCAL_APPS variable.
    """
    return LOCAL_APPS_DICT

def get_github_apps():
    """
    Return the modern dict list of github apps.
    If a caller expects the legacy tuple list, see GITHUB_APPS variable.
    """
    return GITHUB_APPS_DICT

# ----------------- Icon helper -----------------

def get_app_icon(icon_data: str):
    """
    Return a QPixmap from base64 data or a path string.
    If icon_data looks like a data URL or long base64, decode it.
    """
    try:
        from PySide6.QtGui import QPixmap
    except Exception:
        # If PySide6 not available at import time (e.g., unit tests),
        # return None to avoid import errors.
        return None

    if not icon_data:
        return QPixmap()

    try:
        # detect data URL format
        if isinstance(icon_data, str) and icon_data.startswith("data:image/"):
            header, b64 = icon_data.split(",", 1)
            binary = base64.b64decode(b64)
            pix = QPixmap()
            pix.loadFromData(binary)
            return pix

        # detect likely base64 raw content (heuristic: long string without slashes)
        if isinstance(icon_data, str) and len(icon_data) > 100 and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r" for c in icon_data[:100]):
            binary = base64.b64decode(icon_data)
            pix = QPixmap()
            pix.loadFromData(binary)
            return pix

        # else it's a file path
        if isinstance(icon_data, str) and os.path.exists(icon_data):
            return QPixmap(icon_data)

        # fallback
        return QPixmap()
    except Exception:
        return QPixmap()

# ---------------- temp signup tracking (kept from original) ----------------
_TEMP_SIGNUPS = []  # list of tuples (idToken, localId)
