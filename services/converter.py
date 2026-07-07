"""Automatic media format conversion using FFmpeg."""

import os
import subprocess
import shutil
from services.logger import logger


def get_ffmpeg_path():
    """Find FFmpeg binary path."""
    # Check local bin first
    local_bin = os.path.join(os.getcwd(), 'bin')
    local_ffmpeg = os.path.join(local_bin, 'ffmpeg.exe')
    if os.path.exists(local_ffmpeg):
        return local_ffmpeg

    # Check system PATH
    system_ffmpeg = shutil.which('ffmpeg')
    if system_ffmpeg:
        return system_ffmpeg

    return None


def convert_media(input_path, output_format='mp4', quality='medium'):
    """
    Convert a media file to a different format.
    
    Args:
        input_path: Path to input file
        output_format: Target format (mp4, mkv, mp3, webm, etc.)
        quality: 'low', 'medium', 'high'
    
    Returns:
        (success, output_path, error_message)
    """
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        return False, input_path, "FFmpeg not installed"

    if not os.path.exists(input_path):
        return False, input_path, "Input file not found"

    base_name = os.path.splitext(input_path)[0]
    output_path = f"{base_name}.{output_format}"

    # Quality presets
    quality_settings = {
        'low': {'video': ['-crf', '28', '-preset', 'fast'], 'audio': ['-b:a', '96k']},
        'medium': {'video': ['-crf', '23', '-preset', 'medium'], 'audio': ['-b:a', '128k']},
        'high': {'video': ['-crf', '18', '-preset', 'slow'], 'audio': ['-b:a', '192k']},
    }
    settings = quality_settings.get(quality, quality_settings['medium'])

    # Audio-only conversion
    audio_formats = {'mp3', 'aac', 'ogg', 'wav', 'flac'}
    if output_format in audio_formats:
        cmd = [
            ffmpeg, '-y', '-i', input_path,
            '-vn', '-acodec', 'libmp3lame' if output_format == 'mp3' else 'copy',
            *settings['audio'],
            output_path
        ]
    else:
        # Video conversion
        cmd = [
            ffmpeg, '-y', '-i', input_path,
            '-c:v', 'libx264' if output_format == 'mp4' else 'libvpx-vp9' if output_format == 'webm' else 'copy',
            *settings['video'],
            '-c:a', 'aac' if output_format == 'mp4' else 'copy',
            output_path
        ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0 and os.path.exists(output_path):
            logger.info('CONVERT', f"Converted: {os.path.basename(input_path)} -> {output_format}")
            return True, output_path, "OK"
        else:
            return False, output_path, result.stderr[:200] if result.stderr else "Conversion failed"
    except subprocess.TimeoutExpired:
        return False, output_path, "Conversion timed out"
    except Exception as e:
        return False, output_path, str(e)[:200]


def get_media_info(file_path):
    """Get basic media info using FFprobe."""
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        return None

    ffprobe = ffmpeg.replace('ffmpeg', 'ffprobe').replace('ffmpeg.exe', 'ffprobe.exe')
    if not os.path.exists(ffprobe):
        ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        return None

    try:
        result = subprocess.run(
            [ffprobe, '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', file_path],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            import json
            return json.loads(result.stdout)
    except Exception:
        pass
    return None
