"""FFmpeg and FFprobe system utilities and execution helpers."""

import subprocess
import shutil
import json
from pathlib import Path
from typing import List, Optional

from app.core.config import settings
from app.core.logging import logger


def check_ffmpeg_available() -> bool:
    """Check if ffmpeg executable is available in PATH or configured path."""
    binary = settings.FFMPEG_BINARY_PATH
    if shutil.which(binary):
        return True
    try:
        res = subprocess.run([binary, "-version"], capture_output=True, text=True, timeout=5)
        return res.returncode == 0
    except Exception:
        return False


def check_ffprobe_available() -> bool:
    """Check if ffprobe executable is available in PATH or configured path."""
    binary = settings.FFPROBE_BINARY_PATH
    if shutil.which(binary):
        return True
    try:
        res = subprocess.run([binary, "-version"], capture_output=True, text=True, timeout=5)
        return res.returncode == 0
    except Exception:
        return False


def get_video_duration(video_path: Path) -> float:
    """Measure exact video duration in seconds using ffprobe."""
    if not video_path.exists():
        return 0.0

    cmd = [
        settings.FFPROBE_BINARY_PATH,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(video_path.resolve()),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            dur_str = data.get("format", {}).get("duration")
            if dur_str:
                return float(dur_str)
    except Exception as e:
        logger.warning("ffprobe probe failed for '%s': %s", video_path, e)
    return 0.0


def escape_ffmpeg_filter_path(file_path: Path) -> str:
    """
    Escape filesystem path for use inside FFmpeg filtergraph strings on Windows and POSIX.
    
    FFmpeg subtitles and ass filters require double-escaping the drive colon
    (e.g. C\\\\:/path/sub.ass) so the filtergraph parser preserves the full path.
    """
    try:
        # If path is inside current working directory, relative posix path avoids drive letters completely
        return file_path.resolve().relative_to(Path.cwd()).as_posix()
    except Exception:
        path_str = str(file_path.resolve()).replace("\\", "/")
        if len(path_str) > 1 and path_str[1] == ":":
            path_str = path_str[0] + "\\\\:" + path_str[2:]
        return path_str

