"""FFmpeg and FFprobe system utilities and execution helpers."""

import subprocess
import shutil
import json
from pathlib import Path
from typing import List, Optional, Dict, Any

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


def probe_video_file(video_path: Path) -> Dict[str, Any]:
    """
    Run detailed ffprobe analysis on a video file and extract stream metadata.

    Returns:
        dict with keys:
            duration: float,
            width: int,
            height: int,
            video_codec: Optional[str],
            audio_codec: Optional[str],
            has_video: bool,
            has_audio: bool,
            fps: float,
            bitrate: int,
            size_bytes: int,
    """
    path_obj = Path(video_path)
    if not path_obj.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    size_bytes = path_obj.stat().st_size
    cmd = [
        settings.FFPROBE_BINARY_PATH,
        "-v", "error",
        "-show_format",
        "-show_streams",
        "-of", "json",
        str(path_obj.resolve()),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if res.returncode != 0:
            raise RuntimeError(f"ffprobe execution failed with code {res.returncode}: {res.stderr}")
        data = json.loads(res.stdout)
    except Exception as e:
        logger.warning("ffprobe probe error on '%s': %s", video_path, e)
        raise

    format_info = data.get("format", {})
    streams = data.get("streams", [])

    duration = float(format_info.get("duration") or 0.0)
    bitrate = int(format_info.get("bit_rate") or 0)

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    width = int(video_stream.get("width") or 0) if video_stream else 0
    height = int(video_stream.get("height") or 0) if video_stream else 0
    video_codec = video_stream.get("codec_name") if video_stream else None
    audio_codec = audio_stream.get("codec_name") if audio_stream else None

    # Calculate FPS from r_frame_rate or avg_frame_rate
    fps = 0.0
    if video_stream:
        rate_str = video_stream.get("r_frame_rate") or video_stream.get("avg_frame_rate")
        if rate_str and "/" in rate_str:
            num, den = rate_str.split("/", 1)
            try:
                num_f, den_f = float(num), float(den)
                if den_f > 0:
                    fps = round(num_f / den_f, 2)
            except Exception:
                fps = 0.0

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "has_video": video_stream is not None,
        "has_audio": audio_stream is not None,
        "fps": fps,
        "bitrate": bitrate,
        "size_bytes": size_bytes,
    }


def validate_video_file(
    video_path: Path,
    min_duration: float = 0.5,
    require_video: bool = True,
    require_audio: bool = False,
    min_width: int = 128,
    min_height: int = 128,
) -> Dict[str, Any]:
    """
    Validate that video file exists, is non-empty, and has valid media streams.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If file is empty or fails stream requirements.
    """
    path_obj = Path(video_path)
    if not path_obj.exists():
        raise FileNotFoundError(f"Video file does not exist: {video_path}")

    if path_obj.stat().st_size == 0:
        raise ValueError(f"Video file is 0 bytes: {video_path}")

    meta = probe_video_file(path_obj)

    if require_video and not meta["has_video"]:
        raise ValueError(f"Video file contains no video stream: {video_path}")

    if require_video and (meta["width"] < min_width or meta["height"] < min_height):
        raise ValueError(
            f"Video resolution {meta['width']}x{meta['height']} is below minimum {min_width}x{min_height}: {video_path}"
        )

    if require_audio and not meta["has_audio"]:
        raise ValueError(f"Video file contains no audio stream: {video_path}")

    if meta["duration"] < min_duration:
        raise ValueError(
            f"Video duration {meta['duration']:.2f}s is below minimum {min_duration:.2f}s: {video_path}"
        )

    return meta


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
