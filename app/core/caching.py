"""Content-aware caching and stale-asset invalidation utilities."""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

from app.core.logging import logger


def hash_text(text: Optional[str]) -> str:
    """Compute deterministic SHA-256 hash of normalized text."""
    if text is None:
        return ""
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def hash_file(path: Union[str, Path]) -> str:
    """Compute SHA-256 hash of file content."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return ""
    hasher = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()[:16]


def get_sidecar_meta_path(asset_path: Path) -> Path:
    """Get canonical .meta.json sidecar file path for an asset."""
    return asset_path.with_name(f"{asset_path.name}.meta.json")


def save_asset_metadata(asset_path: Path, metadata: Dict[str, Any]) -> None:
    """Persist structured sidecar metadata alongside an asset file."""
    meta_path = get_sidecar_meta_path(asset_path)
    try:
        meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to save asset metadata to '%s': %s", meta_path, str(e))


def load_asset_metadata(asset_path: Path) -> Optional[Dict[str, Any]]:
    """Load asset metadata from sidecar .meta.json file if present."""
    meta_path = get_sidecar_meta_path(asset_path)
    if not meta_path.exists() or meta_path.stat().st_size == 0:
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Corrupted sidecar metadata at '%s': %s", meta_path, str(e))
        return None


def is_audio_asset_valid(
    audio_path: Path,
    expected_narration: str,
    expected_voice: str,
    expected_provider: str,
) -> bool:
    """
    Check if an existing audio file is valid and matches the current narration content.
    Prevents stale asset reuse when script narration has been condensed or altered.
    """
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        return False

    meta = load_asset_metadata(audio_path)
    if not meta:
        # Legacy or untracked audio file without metadata
        return False

    current_narration_hash = hash_text(expected_narration)
    if meta.get("narration_hash") != current_narration_hash:
        logger.info(
            "Audio cache invalidated for '%s': narration hash mismatch (%s vs %s)",
            audio_path.name,
            meta.get("narration_hash"),
            current_narration_hash,
        )
        return False

    if meta.get("voice_id") != expected_voice or meta.get("provider") != expected_provider:
        logger.info("Audio cache invalidated for '%s': voice/provider mismatch", audio_path.name)
        return False

    return True


def is_avatar_asset_valid(
    avatar_video_path: Path,
    audio_path: Path,
    expected_provider: str,
    source_portrait_path: Optional[Path] = None,
) -> bool:
    """
    Check if an existing avatar MP4 matches current audio and portrait hashes.
    Automatically invalidates avatar if scene audio was regenerated.
    """
    if not avatar_video_path.exists() or avatar_video_path.stat().st_size == 0:
        return False

    meta = load_asset_metadata(avatar_video_path)
    if not meta:
        return False

    current_audio_hash = hash_file(audio_path)
    if meta.get("audio_hash") != current_audio_hash:
        logger.info(
            "Avatar cache invalidated for '%s': input audio changed (%s vs %s)",
            avatar_video_path.name,
            meta.get("audio_hash"),
            current_audio_hash,
        )
        return False

    if source_portrait_path and source_portrait_path.exists():
        current_portrait_hash = hash_file(source_portrait_path)
        if meta.get("portrait_hash") and meta.get("portrait_hash") != current_portrait_hash:
            logger.info("Avatar cache invalidated for '%s': source portrait changed", avatar_video_path.name)
            return False

    if meta.get("provider") != expected_provider:
        return False

    return True


def is_rendered_scene_valid(
    rendered_scene_path: Path,
    audio_path: Path,
    expected_duration: float,
    tolerance_seconds: float = 0.5,
) -> bool:
    """
    Validate that an existing rendered scene matches audio ground truth within technical tolerance.
    """
    if not rendered_scene_path.exists() or rendered_scene_path.stat().st_size == 0:
        return False

    meta = load_asset_metadata(rendered_scene_path)
    if not meta:
        return False

    current_audio_hash = hash_file(audio_path)
    if meta.get("audio_hash") != current_audio_hash:
        logger.info(
            "Rendered scene cache invalidated for '%s': audio hash mismatch",
            rendered_scene_path.name,
        )
        return False

    cached_duration = meta.get("duration", 0.0)
    if abs(cached_duration - expected_duration) > tolerance_seconds:
        logger.info(
            "Rendered scene cache invalidated for '%s': duration drift (cached=%.2fs, expected=%.2fs)",
            rendered_scene_path.name,
            cached_duration,
            expected_duration,
        )
        return False

    return True
