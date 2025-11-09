from yt_dlp import YoutubeDL
import os
import re
import sys
from typing import List, Dict, Tuple, Optional, Callable
from urllib.parse import urlparse, parse_qs
from functools import lru_cache

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
def get_url_info(url: str) -> Tuple[str, Dict]:
    try:
        ydl_opts = {
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
                    return 'channel', {}
                elif 'list' in query_params:
                    return 'playlist', {}
                else:
                    return 'video', {}

            content_type = info.get('_type', 'video')

            if content_type == 'playlist':
                if info.get('uploader_id') and ('/@' in url or '/channel/' in url or '/c/' in url or '/user/' in url):
                    return 'channel', info
                else:
                    return 'playlist', info

            return content_type, info

    except Exception:
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)

        if '/@' in url or '/channel/' in url or '/c/' in url or '/user/' in url:
            return 'channel', {}
        elif 'list' in query_params:
            return 'playlist', {}
        else:
            return 'video', {}


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


def fetch_video_info(url: str, audio_only: bool = False) -> dict:
    ydl_opts = {
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
        duration = format_duration(info.get('duration', 0))
        thumbnail_url = info.get('thumbnail', '')

        qualities = []
        if not audio_only:
            formats = info.get('formats', [])
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
            subtitles = list(info['subtitles'].keys())

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


def fetch_playlist_info(url: str, audio_only: bool = False) -> dict:
    ydl_opts = {
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
                duration = format_duration(entry.get('duration', 0))

                thumbnail_url = (
                    entry.get('thumbnail') or
                    entry.get('thumbnails', [{}])[0].get('url', '') or
                    f"https://i.ytimg.com/vi/{video_id}/default.jpg"
                )

                # Determine quality options based on audio_only setting
                if audio_only:
                    qualities = ['320 kbps', '192 kbps', '128 kbps', 'Best Audio']
                else:
                    # For video, we'll use a default set since we can't easily get all qualities without full extraction
                    qualities = ['2160p', '1440p', '1080p', '720p', '480p', '360p', '240p', '144p', 'Best Available']

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


def download_single_video_with_progress(
    url: str,
    output_path: str,
    quality: Optional[str],
    subtitle: Optional[str],
    audio_only: bool,
    progress_hook: Optional[Callable] = None
) -> dict:
    if audio_only:
        # Handle MP3 quality selection
        if quality and quality.endswith('kbps'):
            # Extract bitrate from quality string (e.g., "320 kbps" -> "320")
            bitrate = quality.split()[0]
            format_selector = f'bestaudio[abr<={bitrate}]/bestaudio/best'
        else:
            format_selector = 'bestaudio/best'
        
        file_extension = 'mp3'
        # Try without postprocessors first to avoid ffprobe issues
        postprocessors = []
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
        # Try without postprocessors first to avoid ffprobe issues
        postprocessors = []

    ydl_opts = {
        'format': format_selector,
        'outtmpl': os.path.join(output_path, f'%(title)s.{file_extension}'),
        'ignoreerrors': False,
        'no_warnings': False,
        'postprocessors': postprocessors,
        'keepvideo': False,
        'retries': 3,
        'fragment_retries': 3,
        'ffmpeg_location': FFMPEG_PATH,
        'ffprobe_location': FFPROBE_PATH,
        'external_downloader_args': {
            'ffmpeg': ['-loglevel', 'error']
        },
        # Additional options to help with ffprobe issues
        'prefer_ffmpeg': True,
        'merge_output_format': 'mp4' if not audio_only else None,
    }

    if not audio_only:
        ydl_opts['merge_output_format'] = 'mp4'

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
        
        # If ffprobe error, try again without ffprobe_location
        if 'ffprobe' in error_msg.lower() or 'audio codec' in error_msg.lower():
            print("FFprobe error detected, retrying without explicit ffprobe path...")
            
            # Remove ffprobe_location and try again
            ydl_opts.pop('ffprobe_location', None)
            
            try:
                with YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

                return {
                    'success': True,
                    'message': 'Download completed successfully (without ffprobe)'
                }
            except Exception as e2:
                return {
                    'success': False,
                    'message': f'Download failed even without ffprobe: {str(e2)}'
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
        # Try without postprocessors first to avoid ffprobe issues
        postprocessors = []
    else:
        format_selector = (
            'bestvideo[height<=1080]+bestaudio/best[height<=1080]/'
            'best'
        )
        file_extension = 'mp4'
        # Try without postprocessors first to avoid ffprobe issues
        postprocessors = []

    ydl_opts = {
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
        }
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
