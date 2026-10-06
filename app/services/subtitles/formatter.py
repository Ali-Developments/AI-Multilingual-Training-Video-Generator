"""Deterministic subtitle chunking, timestamp calculation, and SRT/VTT formatting."""

import re
from typing import List
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
