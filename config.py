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



import os
import base64

# ---------------- App Definitions ----------------

GITHUB_APPS_DICT = [
    {
        "name": "YouTube Downloader Professional",
        "order": 2,
        "window_title": "YouTube Multi-Content Downloader Pro",
        "title": "YouTube Multi-Content Downloader Pro",
        "icon": iconyt,
        "type": "pyside6_gui",
        "entry": "https://raw.githubusercontent.com/Ahmad91-9/fsap/main/youtube_downloader_gui_patched_fixed_corrected.py",
        "version": "0.0.0",
        "description": "Local patched YouTube downloader GUI",
    },
    {
        "name": "Spotify Downloader",
        "order": 1,
        "window_title": "spotDL Professional - Music Downloader",
        "title": "spotDL Professional - Music Downloader",
        "icon": iconspt,
        "type": "pyside6_gui",
        "entry": "https://raw.githubusercontent.com/Ahmad91-9/fsap/main/spotdl_gui_simple.py",
        "version": "0.0.0",
        "description": "Local Spotify downloader GUI",
    },
    {
        "name": "RBPK Automation App",
        "order": 3,
        "window_title": "RB-PK Order Automation",
        "title": "RB-PK Order Automation",
        "icon": iconrb,
        "type": "pyside6_gui",
        "entry": "https://raw.githubusercontent.com/Ahmad91-9/rbpk-script/main/rbpk.py",
        "version": "0.0.0",
        "description": "Remote RBPK automation PySide6 app (raw .py)",
    },
    {
        "name": "Archive Downloader",
        "order": 4,
        "window_title": "Archive.org Downloader",
        "title": "Archive.org Downloader",
        "icon": iconarh,
        "type": "pyside6_gui",
        "entry": "https://raw.githubusercontent.com/Ahmad91-9/fsap/main/archivedownloader.py",
        "version": "0.0.0",
        "description": "Local downloader for archives",
    },
    {
        "name": "PDF OCR for Urdu",
        "order": 5,
        "window_title": "PDF Urdu OCR — Desktop",
        "title": "PDF Urdu OCR — Desktop",
        "icon": iconocr,
        "type": "pyside6_gui",
        "version": "0.0.0",
        "entry": "https://raw.githubusercontent.com/Ahmad91-9/fsap/main/pdf_urdu_ocr_app.py",
        "description": "Local OCR app for Urdu PDFs",
    },
    {
        "name": "PDF Delete_Erase text",
        "order": 6,
        "window_title": "PDF Editor Pro",
        "title": "PDF Editor Pro",
        "icon": iconopdf_d_e,
        "type": "local",
        "entry": "https://raw.githubusercontent.com/Ahmad91-9/fsap/main/pageremoverpdf.py",
        "description": "Remove text from PDF pages",
    },
    {
        "name": "Anime Upscaler",
        "order": 7,
        "window_title": "Anime Image Upscaler",
        "title": "Anime Image Upscaler",
        "icon": iconau,
        "type": "pyside6_gui",
        "entry": "https://raw.githubusercontent.com/Ahmad91-9/fsap/main/Anime_Upscaler.py",
        "version": "0.0.0",
        "description": "Local anime upscaler GUI",
    },
    {
        "name": "Real Image Upscaler",
        "order": 8,
        "window_title": "General Image Upscaler",
        "title": "General Image Upscaler",
        "icon": iconru,
        "type": "pyside6_gui",
        "entry": "https://raw.githubusercontent.com/Ahmad91-9/fsap/main/Upscaler.py",
        "version": "0.0.0",
        "description": "Image upscaler",
    },
]

LOCAL_APPS_DICT = [
    {
        "name": "PDF and Word Watermark Remover",
        "order": 1,
        "window_title": "Watermark Remover Tool",
        "title": "Watermark Remover Tool",
        "icon": iconrem,
        "type": "local",
        "entry": "PDF_word Watermarkremover/prod.py",
        "description": "Local PDF & Word watermark remover",
    }
]

GITHUB_AUTOMATION_APPS_DICT = [
    # Add automation apps here
    # Example:
    # {
    #     "name": "RBPK Automation App",
    #     "order": 1,
    #     "window_title": "RB-PK Order Automation",
    #     "title": "RB-PK Order Automation",
    #     "icon": iconrb,
    #     "type": "github_automation",
    #     "entry": "https://raw.githubusercontent.com/Ahmad91-9/rbpk-script/main/rbpk.py",
    #     "version": "0.0.0",
    #     "description": "Remote RBPK automation PySide6 app (raw .py)",
    # },
]

# ---------------- Sorting by Order ----------------

# Ensure stable ordering; missing order gets pushed to the end
GITHUB_APPS_DICT = sorted(GITHUB_APPS_DICT, key=lambda a: a.get("order", 999))
LOCAL_APPS_DICT = sorted(LOCAL_APPS_DICT, key=lambda a: a.get("order", 999))
GITHUB_AUTOMATION_APPS_DICT = sorted(GITHUB_AUTOMATION_APPS_DICT, key=lambda a: a.get("order", 999))

# ---------------- Compatibility: legacy tuple lists ----------------

LOCAL_APPS = [(a.get("name"), a.get("icon"), a.get("entry")) for a in LOCAL_APPS_DICT]
GITHUB_APPS = [(a.get("name"), a.get("icon"), a.get("entry")) for a in GITHUB_APPS_DICT]

# ---------------- Helper getters ----------------

def get_local_apps():
    """Return the modern dict list of local apps."""
    return LOCAL_APPS_DICT


def get_github_apps():
    """Return the modern dict list of github apps."""
    return GITHUB_APPS_DICT


def get_github_automation_apps():
    """Return the modern dict list of github automation apps."""
    return GITHUB_AUTOMATION_APPS_DICT


# ----------------- Icon helper -----------------

def get_app_icon(icon_data: str):
    """Return a QPixmap from base64 data or a path string."""
    try:
        from PySide6.QtGui import QPixmap
    except Exception:
        return None

    if not icon_data:
        return QPixmap()

    try:
        if isinstance(icon_data, str) and icon_data.startswith("data:image/"):
            header, b64 = icon_data.split(",", 1)
            binary = base64.b64decode(b64)
            pix = QPixmap()
            pix.loadFromData(binary)
            return pix

        if (
            isinstance(icon_data, str)
            and len(icon_data) > 100
            and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r" for c in icon_data[:100])
        ):
            binary = base64.b64decode(icon_data)
            pix = QPixmap()
            pix.loadFromData(binary)
            return pix

        if isinstance(icon_data, str) and os.path.exists(icon_data):
            return QPixmap(icon_data)

        return QPixmap()
    except Exception:
        return QPixmap()


# ---------------- Temp signup tracking ----------------

_TEMP_SIGNUPS = []  # list of tuples (idToken, localId)

# ========== REWARD SYSTEM CONFIGURATION ==========

def monthly_reward_on_a_successful_referral():
    """Returns the monthly reward amount for a successful referral"""
    return 60

def weekly_reward_on_a_successful_referral():
    """Returns the weekly reward amount for a successful referral"""

    return 20