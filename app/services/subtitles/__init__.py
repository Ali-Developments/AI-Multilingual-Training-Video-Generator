"""Subtitle generation and serialization package."""

from app.services.subtitles.formatter import (
    format_timestamp_srt,
    format_timestamp_vtt,
    split_narration_into_chunks,
    serialize_srt,
    serialize_vtt,
)
from app.services.subtitles.base import SubtitleProvider
from app.services.subtitles.deterministic_provider import DeterministicSubtitleProvider
from app.services.subtitles.factory import get_subtitle_provider
from app.services.subtitles.service import SubtitleService

__all__ = [
    "format_timestamp_srt",
    "format_timestamp_vtt",
    "split_narration_into_chunks",
    "serialize_srt",
    "serialize_vtt",
    "SubtitleProvider",
    "DeterministicSubtitleProvider",
    "get_subtitle_provider",
    "SubtitleService",
]
