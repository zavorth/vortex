"""HLS/DASH stream detection and download support."""

import os
import re
import urllib.parse
import requests
from services.logger import logger


def detect_stream_type(url):
    """Detect if a URL is an HLS (.m3u8) or DASH (.mpd) stream."""
    url_lower = url.lower()
    if '.m3u8' in url_lower or 'manifest' in url_lower:
        return 'hls'
    if '.mpd' in url_lower:
        return 'dash'
    return None


def extract_m3u8_variants(m3u8_url, headers=None):
    """Parse an M3U8 playlist and extract available quality variants."""
    try:
        h = headers or {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
        r = requests.get(m3u8_url, headers=h, timeout=15)
        if r.status_code != 200:
            return []

        content = r.text
        variants = []
        lines = content.strip().split('\n')

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('#EXT-X-STREAM-INF:'):
                # Parse bandwidth and resolution
                bandwidth = 0
                resolution = ''
                for param in line.split(','):
                    if 'BANDWIDTH=' in param:
                        try:
                            bandwidth = int(param.split('=')[1])
                        except ValueError:
                            pass
                    if 'RESOLUTION=' in param:
                        resolution = param.split('=')[1]

                # Next line is the URL
                if i + 1 < len(lines):
                    variant_url = lines[i + 1].strip()
                    if not variant_url.startswith('http'):
                        variant_url = urllib.parse.urljoin(m3u8_url, variant_url)
                    variants.append({
                        'url': variant_url,
                        'bandwidth': bandwidth,
                        'resolution': resolution,
                        'bandwidth_str': _format_bandwidth(bandwidth)
                    })
            i += 1

        # Sort by bandwidth (highest first)
        variants.sort(key=lambda x: x['bandwidth'], reverse=True)
        return variants

    except Exception as e:
        logger.warning('HLS', f"Failed to parse M3U8: {e}")
        return []


def _format_bandwidth(bps):
    """Format bandwidth to human-readable string."""
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.1f} Mbps"
    elif bps >= 1_000:
        return f"{bps / 1_000:.0f} Kbps"
    return f"{bps} bps"


def get_best_variant(m3u8_url, preference='highest', headers=None):
    """
    Get the best quality variant from an M3U8 playlist.
    preference: 'highest', 'lowest', or a specific resolution like '1920x1080'
    """
    variants = extract_m3u8_variants(m3u8_url, headers)
    if not variants:
        return m3u8_url  # Return original if no variants found

    if preference == 'lowest':
        return variants[-1]['url']
    elif preference == 'highest':
        return variants[0]['url']
    else:
        # Try to match specific resolution
        for v in variants:
            if v['resolution'] == preference:
                return v['url']
        # Fallback to highest
        return variants[0]['url']


def download_m3u8(m3u8_url, output_path, headers=None, progress_callback=None):
    """
    Download an HLS stream using yt-dlp (if available) or direct segment download.
    Returns (success, output_file, error_message).
    """
    # Try yt-dlp first (most reliable)
    try:
        import yt_dlp
        ydl_opts = {
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
        }
        local_bin = os.path.join(os.getcwd(), 'bin')
        ffmpeg_path = os.path.join(local_bin, 'ffmpeg.exe')
        if os.path.exists(ffmpeg_path):
            ydl_opts['ffmpeg_location'] = local_bin

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([m3u8_url])

        # Find the downloaded file
        for ext in ('.mp4', '.mkv', '.webm'):
            candidate = output_path + ext
            if os.path.exists(candidate):
                return True, candidate, "OK"

        if os.path.exists(output_path):
            return True, output_path, "OK"

        return False, output_path, "File not found after download"

    except ImportError:
        logger.warning('HLS', "yt-dlp not available for M3U8 download")
    except Exception as e:
        logger.warning('HLS', f"yt-dlp M3U8 download failed: {e}")

    return False, output_path, "HLS download requires yt-dlp"


def check_url_is_stream(url):
    """Quick check if a URL points to a stream that needs special handling."""
    stream_type = detect_stream_type(url)
    if stream_type:
        return True, stream_type
    return False, None
