from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
import os
import re
import sys
from typing import List, Dict, Tuple, Optional, Callable, Any, Union
from typing import TypedDict
from urllib.parse import urlparse, parse_qs
from functools import lru_cache
from urllib.parse import urlsplit

# FFmpeg and FFprobe paths - look in the main.py directory (project root)
def get_project_root():
    """Get the directory where main.py is located (project root)"""
    # If running as a script, use the directory of the main script
    if hasattr(sys, 'argv') and sys.argv:
        main_script = sys.argv[0]
        if main_script and os.path.isfile(main_script):
            return os.path.dirname(os.path.abspath(main_script))
    # Fallback to current working directory
    return os.getcwd()

FFMPEG_DIR = get_project_root()
FFMPEG_PATH = os.path.join(FFMPEG_DIR, "ffmpeg.exe")
FFPROBE_PATH = os.path.join(FFMPEG_DIR, "ffprobe.exe")

# Print paths for debugging
print(f"Project root: {FFMPEG_DIR}")
print(f"FFmpeg path: {FFMPEG_PATH}")
print(f"FFprobe path: {FFPROBE_PATH}")
print(f"FFmpeg exists: {os.path.exists(FFMPEG_PATH)}")
print(f"FFprobe exists: {os.path.exists(FFPROBE_PATH)}")



@lru_cache(maxsize=128)
def get_url_info(url: str) -> Tuple[str, Dict[str, Any]]:
    try:
        ydl_opts: Dict[str, Any] = {
            'quiet': True,
            'extract_flat': True,
            'no_warnings': True,
            'skip_download': True,
            'playlist_items': '1',
            'ffmpeg_location': FFMPEG_PATH,
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            if info is None:
                parsed_url = urlparse(url)
                query_params = parse_qs(parsed_url.query)

                if '/@' in url or '/channel/' in url or '/c/' in url or '/user/' in url:
                    return 'channel', {}  # type: ignore
                elif 'list' in query_params:
                    return 'playlist', {}  # type: ignore
                else:
                    return 'video', {}  # type: ignore

            content_type = info.get('_type', 'video')

            if content_type == 'playlist':
                if info.get('uploader_id') and ('/@' in url or '/channel/' in url or '/c/' in url or '/user/' in url):
                    return 'channel', info  # type: ignore
                else:
                    return 'playlist', info  # type: ignore

            return content_type, info  # type: ignore

    except Exception:
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)

        if '/@' in url or '/channel/' in url or '/c/' in url or '/user/' in url:
            return 'channel', {}  # type: ignore
        elif 'list' in query_params:
            return 'playlist', {}  # type: ignore
        else:
            return 'video', {}  # type: ignore


def is_playlist_url(url: str) -> bool:
    content_type, _ = get_url_info(url)
    return content_type == 'playlist'


def get_content_type(url: str) -> str:
    content_type, _ = get_url_info(url)
    return content_type


def clean_youtube_url(url: str) -> str:
    """
    Clean YouTube URL by removing playlist/radio parameters that might interfere with video extraction.
    Removes parameters starting from &list, &start_radio, &pp, etc.
    """
    if not url or 'youtube.com' not in url and 'youtu.be' not in url:
        return url
    
    # Remove parameters that might cause issues with video extraction
    parameters_to_remove = ['&list=', '&start_radio=', '&pp=', '&index=', '&t=']
    
    cleaned_url = url
    for param in parameters_to_remove:
        if param in cleaned_url:
            # Find the position of the parameter and remove everything from there
            param_pos = cleaned_url.find(param)
            # Find the next '&' or end of string
            next_param = cleaned_url.find('&', param_pos + 1)
            if next_param != -1:
                cleaned_url = cleaned_url[:param_pos] + cleaned_url[next_param:]
            else:
                cleaned_url = cleaned_url[:param_pos]
    
    return cleaned_url


def parse_multiple_urls(input_string: str) -> List[str]:
    urls = re.split(r'[,\s\n\t]+', input_string.strip())
    urls = [url.strip() for url in urls if url.strip()]

    valid_urls = []
    for url in urls:
        # Clean the URL first
        cleaned_url = clean_youtube_url(url)
        
        if ('youtube.com' in cleaned_url or 'youtu.be' in cleaned_url) and (
            '/watch?' in cleaned_url or
            '/playlist?' in cleaned_url or
            '/shorts/' in cleaned_url or
            '/@' in cleaned_url or
            '/channel/' in cleaned_url or
            '/c/' in cleaned_url or
            '/user/' in cleaned_url or
            'youtu.be/' in cleaned_url
        ):
            valid_urls.append(cleaned_url)

    return valid_urls


def parse_multiple_urls_for_hosts(input_string: str, allowed_hosts: Optional[List[str]] = None) -> List[str]:
    """
    Parse text into URLs and optionally filter by allowed hostnames.
    If allowed_hosts is None or empty, all URLs are accepted.
    """
    urls = re.split(r'[,\s\n\t]+', input_string.strip())
    urls = [url.strip() for url in urls if url.strip()]

    if not urls:
        return []

    if not allowed_hosts:
        # Return all strings that look like URLs
        return [u for u in urls if re.match(r'^https?://', u, re.IGNORECASE)]

    def hostname(url: str) -> str:
        try:
            netloc = urlsplit(url).netloc.lower()
            if ":" in netloc:
                netloc = netloc.split(":", 1)[0]
            if netloc.startswith("www."):
                netloc = netloc[4:]
            return netloc
        except Exception:
            return ""

    allowed = [h.lower().lstrip(".") for h in allowed_hosts]
    accepted: List[str] = []
    for u in urls:
        if not re.match(r'^https?://', u, re.IGNORECASE):
            continue
        h = hostname(u)
        for a in allowed:
            if h == a or h.endswith("." + a):
                accepted.append(u)
                break
    return accepted


def format_duration(seconds: int) -> str:
    if not seconds:
        return "Unknown"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"


def fetch_video_info(url: str, audio_only: bool = False) -> Dict[str, Any]:
    ydl_opts: Dict[str, Any] = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'ffmpeg_location': FFMPEG_PATH,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

        if not info:
            raise Exception("Failed to fetch video information")

        video_id = info.get('id', 'unknown')
        title = info.get('title', 'Unknown Title')
        duration = format_duration(info.get('duration') or 0)
        thumbnail_url = info.get('thumbnail', '')

        qualities = []
        if not audio_only:
            formats = info.get('formats') or []
            quality_set = set()

            for fmt in formats:
                if fmt.get('vcodec') != 'none' and fmt.get('acodec') != 'none':
                    height = fmt.get('height')
                    if height:
                        quality_str = f"{height}p"
                        if quality_str not in quality_set:
                            quality_set.add(quality_str)

            # Also check for video-only formats to include 4K and 2K options
            for fmt in formats:
                if fmt.get('vcodec') != 'none' and fmt.get('acodec') == 'none':
                    height = fmt.get('height')
                    if height and height >= 1440:  # Include 2K (1440p) and 4K (2160p)
                        quality_str = f"{height}p"
                        if quality_str not in quality_set:
                            quality_set.add(quality_str)

            if quality_set:
                sorted_qualities = sorted(
                    quality_set,
                    key=lambda x: int(x.replace('p', '')),
                    reverse=True
                )
                qualities = sorted_qualities
            else:
                qualities = ['Best Available']
        else:
            # MP3 quality options
            qualities = ['320 kbps', '192 kbps', '128 kbps', 'Best Audio']

        subtitles = []
        if info.get('subtitles'):
            subtitles = list(info.get('subtitles', {}).keys())

        return {
            'type': 'video',
            'id': video_id,
            'url': url,
            'title': title,
            'duration': duration,
            'thumbnail_url': thumbnail_url,
            'qualities': qualities,
            'subtitles': subtitles
        }


def fetch_playlist_info(url: str, audio_only: bool = False) -> Dict[str, Any]:
    ydl_opts: Dict[str, Any] = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': 'in_playlist',
        'ffmpeg_location': FFMPEG_PATH,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

        if not info:
            raise Exception("Failed to fetch playlist information")

        content_type = 'playlist' if info.get('_type') == 'playlist' else 'channel'
        title = info.get('title', 'Unknown')
        entries = info.get('entries', [])

        videos = []
        for entry in entries:
            if entry:
                video_id = entry.get('id', 'unknown')
                video_title = entry.get('title', 'Unknown Title')
                video_url = entry.get('url', '') or f"https://www.youtube.com/watch?v={video_id}"
                duration = format_duration(entry.get('duration') or 0)

                thumbnail_url = (
                    entry.get('thumbnail') or
                    entry.get('thumbnails', [{}])[0].get('url', '') or
                    f"https://i.ytimg.com/vi/{video_id}/default.jpg"
                )

                # Determine quality options based on audio_only setting
                if audio_only:
                    qualities = ['Best Audio','320 kbps', '192 kbps', '128 kbps']
                else:
                    # For video, we'll use a default set since we can't easily get all qualities without full extraction
                    qualities = ['Best Available','2160p', '1440p', '1080p', '720p', '480p', '360p', '240p', '144p']

                videos.append({
                    'type': 'video',
                    'id': video_id,
                    'url': video_url,
                    'title': video_title,
                    'duration': duration,
                    'thumbnail_url': thumbnail_url,
                    'qualities': qualities,
                    'subtitles': []
                })

        return {
            'type': content_type,
            'title': title,
            'videos': videos
        }


def fetch_generic_info(url: str, audio_only: bool = False) -> Dict[str, Any]:
    """
    Generic info fetcher for non-YouTube platforms using yt_dlp.
    Attempts to extract video metadata, available qualities (heights for video, bitrates for audio),
    and subtitles when available.
    """
    ydl_opts: Dict[str, Any] = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'ffmpeg_location': FFMPEG_PATH,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            raise Exception("Failed to fetch media information")

        # If it's a playlist/container, defer to playlist handler
        if info.get('_type') == 'playlist':
            return fetch_generic_playlist_info(url, audio_only)

        media_id = info.get('id', 'unknown')
        title = info.get('title', 'Unknown Title')
        duration = format_duration(info.get('duration') or 0)
        thumbnail_url = info.get('thumbnail', '') or (info.get('thumbnails', [{}])[0].get('url', '') if info.get('thumbnails') else '')

        # Check if this is an image-only post
        is_image_post = False
        if 'facebook.com' in url and '/share/p/' in url:
            is_image_post = True
        
        qualities: List[str] = []
        if not audio_only and not is_image_post:
            formats = info.get('formats') or []
            heights = sorted([fmt.get('height') for fmt in formats if fmt.get('height') is not None], reverse=True)  # type: ignore
            if heights:
                qualities = [f"{h}p" for h in heights]
            else:
                qualities = ['Best Available']
        elif is_image_post:
            # For image posts, we just want to download the image
            qualities = ['Original']
        else:
            # MP3 quality options
            qualities = ['Best Audio','320 kbps', '192 kbps', '128 kbps']

        subtitles = []
        if info.get('subtitles'):
            subtitles = list(info.get('subtitles', {}).keys())

        return {
            'type': 'video',
            'id': media_id,
            'url': url,
            'title': title,
            'duration': duration,
            'thumbnail_url': thumbnail_url,
            'qualities': qualities,
            'subtitles': subtitles,
        }


def fetch_generic_playlist_info(url: str, audio_only: bool = False) -> Dict[str, Any]:
    """
    Generic playlist/channel info using yt_dlp. Builds a minimal list of entries.
    """
    ydl_opts: Dict[str, Any] = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': 'in_playlist',
        'ffmpeg_location': FFMPEG_PATH,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            raise Exception("Failed to fetch playlist information")

        content_type = 'playlist' if info.get('_type') == 'playlist' else 'playlist'
        title = info.get('title', 'Unknown')
        entries = info.get('entries', []) or []

        videos: List[Dict] = []
        for entry in entries:
            if not entry:
                continue
            media_id = entry.get('id', 'unknown')
            media_title = entry.get('title', 'Unknown Title')
            media_url = entry.get('url') or entry.get('webpage_url') or url
            duration = format_duration(entry.get('duration') or 0)
            thumb = entry.get('thumbnail') or (entry.get('thumbnails', [{}])[0].get('url', '') if entry.get('thumbnails') else '')
            if audio_only:
                qualities = [ 'Best Audio','320 kbps', '192 kbps', '128 kbps']
            else:
                qualities = ['Best Available']
            videos.append({
                'type': 'video',
                'id': media_id,
                'url': media_url,
                'title': media_title,
                'duration': duration,
                'thumbnail_url': thumb,
                'qualities': qualities,
                'subtitles': [],
            })

        return {
            'type': content_type,
            'title': title,
            'videos': videos,
        }

def download_single_video_with_progress(
    url: str,
    output_path: str,
    quality: Optional[str],
    subtitle: Optional[str],
    audio_only: bool,
    fetch_images: bool = False,
    fetch_all: bool = False,
    progress_hook: Optional[Callable] = None
) -> dict:
    # Enhanced options for maximum download speed and SSL support
    enhanced_opts: Dict[str, Any] = {
        # SSL/TLS options for secure connections
        'hls_prefer_native': True,
        'external_downloader': {
            'default': 'ffmpeg',
            'm3u8': 'ffmpeg',
            'm3u8_native': 'ffmpeg',
        },
        'external_downloader_args': {
            'ffmpeg': [
                '-loglevel', 'error',
                '-reconnect', '1',
                '-reconnect_streamed', '1',
                '-reconnect_delay_max', '5',
                '-rw_timeout', '30000000',  # 30 seconds timeout
                '-bufsize', '256K',  # Smaller buffer for more frequent updates
                '-maxrate', '0',  # No limit
                '-minrate', '0',  # No limit
                '-fflags', '+discardcorrupt',
                '-fflags', '+fastseek',
                '-fflags', '+genpts',
                '-fflags', '+igndts',
            ]
        },
        # Network optimization options
        'socket_timeout': 30,
        'retries': 10,
        'fragment_retries': 10,
        'retry_sleep_functions': {
            'http': lambda n: 2 ** n,
            'fragment': lambda n: 2 ** n,
            'file_access': lambda n: 2 ** n,
        },
        'buffersize': 256 * 1024,  # 256KB buffer for more frequent updates
        'concurrent_fragment_downloads': 3,  # Reduced for better progress tracking
        # Security options
        'no_check_certificate': False,
        'prefer_insecure': False,
        # Performance options
        'no_mtime': True,
        'nopart': False,
        'continuedl': True,
        # Progress tracking options
        'progress_delta': 0.5,  # Update progress every 0.5%
    }
    
    # Handle image fetching for social media platforms
    if fetch_images or fetch_all:
        # Special handling for images from social media platforms
        image_ydl_opts: Dict[str, Any] = {
            'skip_download': False,
            'writethumbnail': True,
            'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
            'ignoreerrors': False,
            'no_warnings': False,
            'ffmpeg_location': FFMPEG_PATH,
            'ffprobe_location': FFPROBE_PATH,
        }
        
        # Apply enhanced options
        image_ydl_opts.update(enhanced_opts)
        
        # Apply enhanced options
        image_ydl_opts.update(enhanced_opts)
        
        # Special handling for YouTube - download only thumbnails
        if 'youtube.com' in url or 'youtu.be' in url:
            # For YouTube, when image format is selected, download only the thumbnail
            image_ydl_opts['skip_download'] = True  # Don't download the video
            image_ydl_opts['writethumbnail'] = True  # But do write the thumbnail
            image_ydl_opts['format'] = 'best'  # This is needed for extraction
        else:
            # For other platforms, download the best available image format
            image_ydl_opts['format'] = 'best'
            
            # Special handling for Facebook image posts
            if 'facebook.com' in url and '/share/p/' in url:
                # For Facebook image posts, we might need to adjust the options
                image_ydl_opts['format'] = 'best[ext=jpg]/best[ext=png]/best'
        
        if progress_hook:
            image_ydl_opts['progress_hooks'] = [progress_hook]
        
        try:
            with YoutubeDL(image_ydl_opts) as ydl:  # type: ignore  # type: ignore
                ydl.download([url])
            
            if not (audio_only or fetch_all):
                return {
                    'success': True,
                    'message': 'Image download completed successfully'
                }
        except Exception as e:
            if not (audio_only or fetch_all):
                return {
                    'success': False,
                    'message': f'Image download failed: {str(e)}'
                }
    
    # Handle audio/video downloading
    if audio_only or fetch_all:
        # Handle MP3 quality selection
        if quality and quality.endswith('kbps'):
            # Extract bitrate from quality string (e.g., "320 kbps" -> "320")
            bitrate = quality.split()[0]
            format_selector = f'bestaudio[abr<={bitrate}]/bestaudio/best'
        else:
            format_selector = 'bestaudio/best'
        
        file_extension = 'mp3'
        # For MP3, we'll download the best audio format and convert it separately to avoid ffprobe issues
        postprocessors = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '0',
        }]
    else:
        if quality and quality != 'Best Available':
            height = quality.replace('p', '')
            # For 2K (1440p) and 4K (2160p), we need to use bestvideo+bestaudio
            # as YouTube typically provides separate video and audio streams for these resolutions
            try:
                height_int = int(height)
                if height_int >= 1440:  # 2K and above
                    format_selector = f'bestvideo[height={height}]+bestaudio/bestvideo[height<={height}]+bestaudio/best[height<={height}]/best'
                else:
                    format_selector = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]/best'
            except ValueError:
                format_selector = 'bestvideo+bestaudio/best'
        else:
            format_selector = 'bestvideo+bestaudio/best'

        file_extension = 'mp4'
        postprocessors = []

    ydl_opts: Dict[str, Any] = {
        'format': format_selector,
        'outtmpl': os.path.join(output_path, f'%(title)s.%(ext)s'),
        'ignoreerrors': False,
        'no_warnings': False,
        'postprocessors': postprocessors,
        'keepvideo': False,
        'ffmpeg_location': FFMPEG_PATH,
        'ffprobe_location': FFPROBE_PATH,
        # Skip thumbnail embedding completely
        'writethumbnail': False,
        'embedthumbnail': False,
        'addmetadata': True,
        # Use preferred format for better compatibility
        'prefer_ffmpeg': True,
        'merge_output_format': 'mp4' if not audio_only else 'mp3',
    }
    
    # Apply enhanced options for maximum speed and SSL support
    ydl_opts.update(enhanced_opts)

    if subtitle:
        ydl_opts['writesubtitles'] = True
        ydl_opts['subtitleslangs'] = [subtitle]

    if progress_hook:
        ydl_opts['progress_hooks'] = [progress_hook]

    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        return {
            'success': True,
            'message': 'Download completed successfully'
        }

    except Exception as e:
        error_msg = str(e)
        
        # If ffprobe error, try again with different options
        if 'ffprobe' in error_msg.lower() or 'audio codec' in error_msg.lower():
            print("FFprobe error detected, retrying with alternative options...")
            
            # Remove ffprobe_location and try again
            ydl_opts.pop('ffprobe_location', None)
            
            # Also remove embedthumbnail to avoid codec detection issues
            ydl_opts.pop('embedthumbnail', None)
            
            try:
                with YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

                return {
                    'success': True,
                    'message': 'Download completed successfully (without embedded thumbnail)'
                }
            except Exception as e2:
                # Try one more time with even more minimal options
                try:
                    minimal_opts: Dict[str, Any] = {
                        'format': format_selector,
                        'outtmpl': os.path.join(output_path, f'%(title)s.%(ext)s'),
                        'ignoreerrors': False,
                        'no_warnings': False,
                        'postprocessors': postprocessors,
                        'keepvideo': False,
                        'ffmpeg_location': FFMPEG_PATH,
                        'prefer_ffmpeg': True,
                        'merge_output_format': 'mp4' if not audio_only else 'mp3',
                        'writethumbnail': True,  # Still write thumbnail but don't embed it
                    }
                    
                    # Apply enhanced options
                    minimal_opts.update(enhanced_opts)
                    
                    with YoutubeDL(minimal_opts) as ydl:  # type: ignore
                        ydl.download([url])
                    
                    return {
                        'success': True,
                        'message': 'Download completed successfully (minimal options)'
                    }
                except Exception as e3:
                    return {
                        'success': False,
                        'message': f'Download failed even with minimal options: {str(e3)}'
                    }
        
        return {
            'success': False,
            'message': str(e)
        }


def download_single_video(url: str, output_path: str, thread_id: int = 0, audio_only: bool = False) -> dict:
    if audio_only:
        # Default to best audio quality for this function
        format_selector = 'bestaudio/best'
        file_extension = 'mp3'
        # Add postprocessor to convert to MP3
        postprocessors = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '0',
        }]
    else:
        format_selector = (
            'bestvideo[height<=1080]+bestaudio/best[height<=1080]/'
            'best'
        )
        file_extension = 'mp4'
        # Try without postprocessors first to avoid ffprobe issues
        postprocessors = []

    ydl_opts: Dict[str, Any] = {
        'format': format_selector,
        'ignoreerrors': True,
        'no_warnings': False,
        'extract_flat': False,
        'writesubtitles': False,
        'writethumbnail': False,
        'writeautomaticsub': False,
        'postprocessors': postprocessors,
        'keepvideo': False,
        'clean_infojson': True,
        'retries': 3,
        'fragment_retries': 3,
        'noplaylist': False,
        'ffmpeg_location': FFMPEG_PATH,
        'ffprobe_location': FFPROBE_PATH,
        'external_downloader_args': {
            'ffmpeg': ['-loglevel', 'error']
        },
        # Progress tracking
        'progress_delta': 0.5,  # Update progress every 0.5%
    }

    if not audio_only:
        ydl_opts['merge_output_format'] = 'mp4'

    content_type, cached_info = get_url_info(url)

    if content_type == 'playlist':
        ydl_opts['outtmpl'] = os.path.join(
            output_path, '%(playlist_title)s', f'%(playlist_index)s-%(title)s.{file_extension}')
    elif content_type == 'channel':
        ydl_opts['outtmpl'] = os.path.join(
            output_path, '%(uploader)s', f'%(upload_date)s-%(title)s.{file_extension}')
    else:
        ydl_opts['outtmpl'] = os.path.join(
            output_path, f'%(title)s.{file_extension}')

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            if info is None:
                return {
                    'url': url,
                    'success': False,
                    'message': f"❌ [Thread {thread_id}] Failed to extract video information. Video may be private or unavailable."
                }

            if info.get('_type') == 'playlist':
                title = info.get('title', 'Unknown Playlist')
                video_count = len(info.get('entries', []))

                if video_count == 0:
                    return {
                        'url': url,
                        'success': False,
                        'message': f"❌ [Thread {thread_id}] {content_type.title()} appears to be empty or private"
                    }

            ydl.download([url])

            if info.get('_type') == 'playlist':
                title = info.get('title', f'Unknown {content_type.title()}')
                video_count = len(info.get('entries', []))
                return {
                    'url': url,
                    'success': True,
                    'message': f"✅ [Thread {thread_id}] {content_type.title()} '{title}' download completed! ({video_count} {'MP3s' if audio_only else 'videos'})"
                }
            else:
                return {
                    'url': url,
                    'success': True,
                    'message': f"✅ [Thread {thread_id}] {'Audio' if audio_only else 'Video'} download completed successfully!"
                }

    except Exception as e:
        error_msg = str(e)
        
        # If ffprobe error, try again without ffprobe_location
        if 'ffprobe' in error_msg.lower() or 'audio codec' in error_msg.lower():
            print(f"[Thread {thread_id}] FFprobe error detected, retrying without explicit ffprobe path...")
            
            # Remove ffprobe_location and try again
            ydl_opts.pop('ffprobe_location', None)
            
            try:
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    ydl.download([url])

                if info and info.get('_type') == 'playlist':
                    title = info.get('title', f'Unknown {content_type.title()}')
                    video_count = len(info.get('entries', []))
                    return {
                        'url': url,
                        'success': True,
                        'message': f"✅ [Thread {thread_id}] {content_type.title()} '{title}' download completed! ({video_count} {'MP3s' if audio_only else 'videos'}) - without ffprobe"
                    }
                else:
                    return {
                        'url': url,
                        'success': True,
                        'message': f"✅ [Thread {thread_id}] {'Audio' if audio_only else 'Video'} download completed successfully! - without ffprobe"
                    }
            except Exception as e2:
                return {
                    'url': url,
                    'success': False,
                    'message': f"❌ [Thread {thread_id}] Error even without ffprobe: {str(e2)}"
                }
        
        return {
            'url': url,
            'success': False,
            'message': f"❌ [Thread {thread_id}] Error: {str(e)}"
        }
