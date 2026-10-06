"""Deterministic audio waveform duration inspection utility."""

import subprocess
import wave
from pathlib import Path
from typing import Union
from app.core.config import settings
from app.core.logging import logger


def get_audio_duration(file_path: Union[str, Path]) -> float:
    """
    Measure exact duration of an audio file in seconds.
    
    Uses ffprobe as primary engine for all formats (.mp3, .wav, .aac, .m4a),
    falling back to Python's wave module for .wav files if ffprobe is unavailable.
    
    Raises:
        FileNotFoundError: If the audio file does not exist.
        ValueError: If the file is 0 bytes or cannot be parsed.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file does not exist: {path}")

    if path.stat().st_size == 0:
        raise ValueError(f"Audio file is empty (0 bytes): {path}")

    # Primary method: ffprobe
    try:
        cmd = [
            settings.FFPROBE_BINARY_PATH,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path.resolve()),
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=10,
        )
        duration_str = result.stdout.strip()
        if duration_str:
            duration = float(duration_str)
            return round(duration, 2)
    except Exception as e:
        logger.debug("ffprobe duration check failed for '%s': %s; attempting fallbacks.", path, str(e))

    # Fallback for WAV files via standard library wave module
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    return round(frames / float(rate), 2)
        except Exception as we:
            logger.debug("wave module fallback failed for '%s': %s", path, str(we))

    raise ValueError(f"Unable to determine audio duration for file: {path}")
