"""Deterministic subtitle chunking, timestamp calculation, and SRT/VTT formatting."""

import re
from typing import List, Optional
from app.models.schemas import SubtitleChunk


def format_timestamp_srt(seconds: float) -> str:
    """Format floating-point seconds into standard SRT timestamp HH:MM:SS,mmm."""
    total_ms = max(0, int(round(seconds * 1000)))
    hours = total_ms // 3600000
    minutes = (total_ms % 3600000) // 60000
    secs = (total_ms % 60000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_timestamp_vtt(seconds: float) -> str:
    """Format floating-point seconds into standard WebVTT timestamp HH:MM:SS.mmm."""
    total_ms = max(0, int(round(seconds * 1000)))
    hours = total_ms // 3600000
    minutes = (total_ms % 3600000) // 60000
    secs = (total_ms % 60000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def split_narration_into_chunks(
    narration: str,
    total_duration_seconds: float,
    max_words_per_chunk: int = 8,
) -> List[SubtitleChunk]:
    """
    Deterministically split narration text into timed subtitle chunks proportional to word length.
    
    Guarantees:
    - start < end
    - next.start >= previous.end
    - last.end <= total_duration_seconds
    - Fully preserves UTF-8 non-Latin Unicode (Arabic, Bengali, etc.)
    """
    if not narration or not narration.strip():
        return []

    words = narration.strip().split()
    if not words:
        return []

    raw_chunks: List[str] = []
    current_words: List[str] = []

    # Punctuation markers indicating natural pause across English, Arabic, Bengali
    pause_punctuation = {".", "!", "?", "،", "؛", "。", "।"}

    for word in words:
        current_words.append(word)
        has_pause = any(word.endswith(p) for p in pause_punctuation)
        if len(current_words) >= max_words_per_chunk or (has_pause and len(current_words) >= 4):
            raw_chunks.append(" ".join(current_words))
            current_words = []

    if current_words:
        raw_chunks.append(" ".join(current_words))

    # Weight duration by character length of each chunk
    total_chars = sum(len(c) for c in raw_chunks)
    if total_chars == 0 or total_duration_seconds <= 0:
        return []

    # Calculate exact proportional cumulative boundaries
    raw_boundaries = [0.0]
    cum_chars = 0
    for text in raw_chunks:
        cum_chars += len(text)
        raw_boundaries.append((cum_chars / total_chars) * total_duration_seconds)

    chunks: List[SubtitleChunk] = []
    for idx, text in enumerate(raw_chunks, 1):
        start_t = round(raw_boundaries[idx - 1], 3)
        end_t = round(raw_boundaries[idx], 3)

        if end_t <= start_t:
            end_t = min(round(total_duration_seconds, 3), round(start_t + 0.001, 3))
            if end_t <= start_t:
                start_t = max(0.0, round(end_t - 0.001, 3))

        chunks.append(
            SubtitleChunk(
                index=idx,
                start_seconds=start_t,
                end_seconds=end_t,
                text=text,
            )
        )

    # Final boundary adjustment: ensure last chunk matches total duration exactly
    if chunks:
        final_end = round(total_duration_seconds, 3)
        if final_end > chunks[-1].start_seconds:
            chunks[-1].end_seconds = final_end
        else:
            chunks[-1].start_seconds = max(0.0, round(final_end - 0.001, 3))
            chunks[-1].end_seconds = final_end

    return chunks


def serialize_srt(chunks: List[SubtitleChunk]) -> str:
    """Serialize subtitle chunks to standard SubRip (.srt) format."""
    lines = []
    for chunk in chunks:
        lines.append(str(chunk.index))
        start_str = format_timestamp_srt(chunk.start_seconds)
        end_str = format_timestamp_srt(chunk.end_seconds)
        lines.append(f"{start_str} --> {end_str}")
        lines.append(chunk.text)
        lines.append("")
    return "\n".join(lines)


def serialize_vtt(chunks: List[SubtitleChunk]) -> str:
    """Serialize subtitle chunks to WebVTT (.vtt) format."""
    lines = ["WEBVTT", ""]
    for chunk in chunks:
        lines.append(str(chunk.index))
        start_str = format_timestamp_vtt(chunk.start_seconds)
        end_str = format_timestamp_vtt(chunk.end_seconds)
        lines.append(f"{start_str} --> {end_str}")
        lines.append(chunk.text)
        lines.append("")
    return "\n".join(lines)


def format_timestamp_ass(seconds: float) -> str:
    """Format floating-point seconds into standard ASS timestamp H:MM:SS.cc (centiseconds)."""
    total_cs = max(0, int(round(seconds * 100)))
    hours = total_cs // 360000
    minutes = (total_cs % 360000) // 6000
    secs = (total_cs % 6000) // 100
    centis = total_cs % 100
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"


def serialize_ass(
    chunks: List[SubtitleChunk],
    locale: str = "en-US",
    font_name: Optional[str] = None,
    font_size: Optional[int] = None,
) -> str:
    """
    Serialize subtitle chunks to Advanced SubStation Alpha (.ass) format.
    
    Provides native support for complex RTL shaping (Arabic) and Indic shaping (Bengali)
    via libass without character double-reversal.
    """
    from app.core.config import settings

    norm_locale = locale.lower().replace("_", "-")
    is_arabic = norm_locale.startswith("ar")
    is_bengali = norm_locale.startswith("bn")

    if not font_name:
        if is_arabic:
            font_name = getattr(settings, "SUBTITLE_FONT_NAME_ARABIC", "Segoe UI")
        elif is_bengali:
            font_name = getattr(settings, "SUBTITLE_FONT_NAME_BENGALI", "Nirmala UI")
        else:
            font_name = getattr(settings, "SUBTITLE_FONT_NAME_DEFAULT", "Arial")

    actual_font_size = font_size or getattr(settings, "SUBTITLE_FONT_SIZE", 42)

    lines = [
        "[Script Info]",
        "Title: Multilingual Training Video Subtitles",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font_name},{actual_font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,30,30,50,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for chunk in chunks:
        start_str = format_timestamp_ass(chunk.start_seconds)
        end_str = format_timestamp_ass(chunk.end_seconds)
        clean_text = chunk.text.replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{clean_text}")

    return "\n".join(lines) + "\n"

