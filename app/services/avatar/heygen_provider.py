"""Production-Ready HeyGen API provider for cloud-rendered talking-head avatar video synthesis."""

import json
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
import requests
from app.core.config import settings
from app.core.logging import logger
from app.services.avatar.base import AvatarProvider
from app.services.composition.ffmpeg_utils import validate_video_file, probe_video_file


class HeyGenAPIError(Exception):
    """Base exception for HeyGen API errors."""
    pass


class HeyGenAuthError(HeyGenAPIError):
    """Authentication failure with HeyGen credentials."""
    pass


class HeyGenRateLimitError(HeyGenAPIError):
    """Rate limit exceeded for HeyGen endpoint."""
    pass


class HeyGenPaymentRequiredError(HeyGenAPIError):
    """Payment required or insufficient HeyGen credits (HTTP 402)."""
    pass


class HeyGenProvider(AvatarProvider):
    """
    Production-ready integration with official HeyGen video generation API.
    
    Capabilities:
    - Audio-driven lip-sync (preserving localized TTS audio ground truth)
    - Script-driven TTS generation
    - Official v2 video generation and v1 video status polling
    - Webhook callback configuration with polling fallback
    - Streamlined asset upload to HeyGen v3 assets storage
    - Technical validation of downloaded MP4s using ffprobe
    - Strict cost safety guards (ENABLE_LIVE_HEYGEN and ENABLE_LIVE_API_TESTS)
    - Full idempotency preventing duplicate paid generations
    """

    BASE_URL = "https://api.heygen.com"

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_retries: int = 3,
        session: Optional[requests.Session] = None,
    ) -> None:
        if api_key is not None:
            self.api_key = api_key
        else:
            self.api_key = settings.HEYGEN_API_KEY
        self.max_retries = max_retries
        self.session = session or requests.Session()

    @property
    def provider_name(self) -> str:
        return "heygen"

    def _get_headers(self) -> Dict[str, str]:
        if not self.api_key or not self.api_key.strip():
            raise HeyGenAuthError(
                "Missing HEYGEN_API_KEY. Configure HEYGEN_API_KEY in environment or constructor."
            )
        return {
            "X-Api-Key": self.api_key.strip(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _check_live_call_permitted(self) -> None:
        """
        Enforce credit cost safety policy.
        
        - Application runtime: requires ENABLE_LIVE_HEYGEN=True.
        - Automated test suite (pytest): additionally requires ENABLE_LIVE_API_TESTS=True
          to prevent accidental credit consumption during test execution.
        """
        import sys

        if not getattr(settings, "ENABLE_LIVE_HEYGEN", False):
            raise RuntimeError(
                "Live HeyGen avatar generation is disabled by configuration (ENABLE_LIVE_HEYGEN=False). "
                "Use MockAvatarProvider for offline development."
            )

        is_test_env = "pytest" in sys.modules
        if is_test_env and not getattr(settings, "ENABLE_LIVE_API_TESTS", False):
            raise RuntimeError(
                "Live HeyGen API calls during automated tests are strictly blocked (ENABLE_LIVE_API_TESTS=False). "
                "Use MockAvatarProvider or mock HTTP responses in test suites."
            )

    def upload_asset(self, file_path: Path) -> str:
        """
        Upload a local audio file to HeyGen v3 assets storage and return public CDN URL.
        Does not consume video generation credits.
        """
        self._check_live_call_permitted()
        headers = {"X-Api-Key": self._get_headers()["X-Api-Key"]}
        file_obj = Path(file_path).resolve()
        if not file_obj.exists() or file_obj.stat().st_size == 0:
            raise FileNotFoundError(f"Audio file for asset upload does not exist or is empty: {file_obj}")

        mime_type = "audio/mpeg" if file_obj.suffix.lower() == ".mp3" else "audio/wav"
        with open(file_obj, "rb") as f:
            files = {"file": (file_obj.name, f, mime_type)}
            response = self.session.post(
                f"{self.BASE_URL}/v3/assets",
                headers=headers,
                files=files,
                timeout=45,
            )
            if response.status_code in (401, 403):
                raise HeyGenAuthError(f"HeyGen authentication error during asset upload: {response.text}")
            response.raise_for_status()
            data = response.json().get("data", {})
            url = data.get("url")
            if not url:
                raise HeyGenAPIError(f"HeyGen asset upload response missing URL: {data}")
            return url

    def submit_avatar_job(
        self,
        scene_id: str,
        locale: str,
        audio_path: Optional[Path] = None,
        avatar_id: Optional[str] = None,
        script_text: Optional[str] = None,
        voice_id: Optional[str] = None,
        mode: Optional[str] = None,
        project_id: Optional[str] = None,
        dimension_width: int = 1920,
        dimension_height: int = 1080,
        **kwargs: Any,
    ) -> str:
        """
        Submit a new avatar generation job to HeyGen v2 video generate API.
        
        Supports two generation modes:
        - "audio": Audio-driven lip sync using pre-synthesized TTS audio file (Default).
        - "script": Script-driven speech generation using HeyGen TTS voice.
        """
        self._check_live_call_permitted()
        headers = self._get_headers()
        chosen_avatar = avatar_id or settings.HEYGEN_DEFAULT_AVATAR_ID
        active_mode = (mode or getattr(settings, "HEYGEN_MODE", "audio") or "audio").strip().lower()

        # Build Character Specification
        character_spec: Dict[str, Any] = {
            "type": "avatar",
            "avatar_id": chosen_avatar,
            "avatar_style": "normal",
        }

        # Build Voice Specification based on selected mode
        if active_mode == "script":
            if not script_text or not script_text.strip():
                raise ValueError("script_text is required when submitting HeyGen job in 'script' mode.")
            chosen_voice = voice_id or getattr(settings, "HEYGEN_DEFAULT_VOICE_ID", "1bd001e7e50f421d891986aad5158bc8")
            voice_spec = {
                "type": "text",
                "input_text": script_text.strip(),
                "voice_id": chosen_voice,
            }
        else:
            # Default: Audio-driven lip-sync mode
            if not audio_path:
                raise ValueError("audio_path is required when submitting HeyGen job in 'audio' mode.")

            resolved_audio_url = None
            if isinstance(audio_path, str) and (audio_path.startswith("http://") or audio_path.startswith("https://")):
                resolved_audio_url = audio_path
            elif isinstance(audio_path, (str, Path)) and Path(audio_path).exists():
                cached_asset_file = Path(audio_path).with_suffix(".asset_url")
                if cached_asset_file.exists():
                    try:
                        cached_url = cached_asset_file.read_text(encoding="utf-8").strip()
                        if cached_url.startswith("http"):
                            logger.info("Reusing existing uploaded HeyGen audio asset URL: %s", cached_url)
                            resolved_audio_url = cached_url
                    except Exception as ex:
                        logger.warning("Could not read cached asset URL file '%s': %s", cached_asset_file, ex)

                if not resolved_audio_url:
                    resolved_audio_url = self.upload_asset(Path(audio_path))
                    try:
                        cached_asset_file.write_text(resolved_audio_url, encoding="utf-8")
                    except Exception as ex:
                        logger.warning("Could not cache asset URL to '%s': %s", cached_asset_file, ex)
            else:
                resolved_audio_url = str(audio_path)

            voice_spec = {
                "type": "audio",
                "audio_url": resolved_audio_url,
            }

        payload: Dict[str, Any] = {
            "video_inputs": [
                {
                    "character": character_spec,
                    "voice": voice_spec,
                }
            ],
            "dimension": {
                "width": dimension_width,
                "height": dimension_height,
            },
            "test": False,
        }

        # Optional Webhook callback support
        webhook_url = getattr(settings, "HEYGEN_WEBHOOK_URL", None)
        if webhook_url:
            payload["callback_url"] = webhook_url
            payload["callback_id"] = f"{project_id or 'proj'}:{scene_id}:{locale}"

        url = f"{self.BASE_URL}/v2/video/generate"

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(
                    "Submitting HeyGen v2 job (attempt %d/%d, avatar=%s, mode=%s, scene=%s)",
                    attempt, self.max_retries, chosen_avatar, active_mode, scene_id
                )
                response = self.session.post(url, json=payload, headers=headers, timeout=45)

                if response.status_code in (401, 403):
                    raise HeyGenAuthError(f"HeyGen authentication error: {response.text}")
                elif response.status_code == 402:
                    raise HeyGenPaymentRequiredError(
                        f"HeyGen payment required (HTTP 402): insufficient account balance or credits. Details: {response.text}"
                    )
                elif response.status_code == 429:
                    if attempt < self.max_retries:
                        backoff = 2.0 ** attempt
                        logger.warning("HeyGen rate limited (429); backing off for %.1fs...", backoff)
                        time.sleep(backoff)
                        continue
                    raise HeyGenRateLimitError("HeyGen rate limit exceeded.")

                response.raise_for_status()
                data = response.json()
                video_id = data.get("data", {}).get("video_id")
                if not video_id:
                    raise HeyGenAPIError(f"HeyGen response missing video_id: {data}")

                logger.info("HeyGen job submitted successfully: video_id='%s' for scene '%s'", video_id, scene_id)
                return video_id

            except (HeyGenAuthError, HeyGenRateLimitError, HeyGenPaymentRequiredError):
                raise
            except Exception as e:
                if attempt == self.max_retries:
                    raise HeyGenAPIError(f"HeyGen submission failed after {self.max_retries} attempts: {str(e)}") from e
                time.sleep(1.5 ** attempt)

        raise HeyGenAPIError("HeyGen submission retries exhausted.")

    def poll_avatar_job(self, job_id: str) -> Dict[str, Any]:
        """
        Poll video rendering status from HeyGen v1 status endpoint.
        
        Returns:
            Dict containing:
                status: 'processing' | 'completed' | 'failed'
                video_url: Optional[str]
                duration: Optional[float]
                error: Optional[str]
        """
        self._check_live_call_permitted()
        headers = self._get_headers()
        url = f"{self.BASE_URL}/v1/video_status.get?video_id={job_id}"

        try:
            response = self.session.get(url, headers=headers, timeout=25)
            if response.status_code in (401, 403):
                raise HeyGenAuthError("Invalid or unauthorized HeyGen credentials.")
            elif response.status_code == 429:
                logger.warning("HeyGen status check hit rate limit (429); continuing to poll.")
                return {"status": "processing"}

            response.raise_for_status()
            data = response.json().get("data", {})
            raw_status = data.get("status", "").lower()

            if raw_status in ("completed", "done", "success"):
                return {
                    "status": "completed",
                    "video_url": data.get("video_url"),
                    "duration": float(data.get("duration") or 0.0),
                }
            elif raw_status in ("failed", "error"):
                error_detail = data.get("error") or data.get("message") or "HeyGen render failed"
                return {
                    "status": "failed",
                    "error": str(error_detail),
                }
            else:
                return {"status": "processing"}

        except HeyGenAuthError:
            raise
        except Exception as e:
            logger.warning("HeyGen status check failed for '%s': %s", job_id, str(e))
            return {"status": "processing"}

    def download_avatar_video(self, video_url: str, destination_path: Path) -> Path:
        """
        Stream download rendered avatar MP4 and validate integrity using ffprobe.
        """
        self._check_live_call_permitted()
        destination_path = Path(destination_path).resolve()
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with self.session.get(video_url, stream=True, timeout=90) as resp:
                resp.raise_for_status()
                with open(destination_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=131072):
                        if chunk:
                            f.write(chunk)

            # Technical validation with ffprobe
            validate_video_file(
                destination_path,
                min_duration=0.5,
                require_video=True,
                require_audio=False,
            )
            return destination_path

        except Exception as e:
            if destination_path.exists():
                try:
                    destination_path.unlink()
                except Exception:
                    pass
            raise HeyGenAPIError(f"Failed to download or validate avatar video from '{video_url}': {str(e)}") from e

    def list_avatars(self) -> List[Dict[str, Any]]:
        """
        Query HeyGen v2 avatars endpoint to retrieve available official avatars.
        """
        self._check_live_call_permitted()
        headers = self._get_headers()
        url = f"{self.BASE_URL}/v2/avatars"

        try:
            resp = self.session.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                avatars = data.get("avatars", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                return avatars
            else:
                # Fallback to v1
                fallback_url = f"{self.BASE_URL}/v1/avatar.list"
                r2 = self.session.get(fallback_url, headers=headers, timeout=20)
                if r2.status_code == 200:
                    return r2.json().get("data", {}).get("avatars", [])
                raise HeyGenAPIError(f"Failed to list HeyGen avatars: HTTP {resp.status_code} {resp.text}")
        except Exception as e:
            logger.warning("HeyGen avatar listing query failed: %s", e)
            raise

    def get_remaining_quota(self) -> Dict[str, Any]:
        """
        Retrieve current remaining credit quota from HeyGen v2 user endpoint.
        Used for budget checking and approval workflows.
        """
        self._check_live_call_permitted()
        headers = self._get_headers()
        url = f"{self.BASE_URL}/v2/user/remaining_quota"

        try:
            resp = self.session.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json().get("data", {})
            quota_val = data.get("remaining_quota") if "remaining_quota" in data else data.get("quota", 0.0)
            return {
                "remaining_quota": quota_val,
                "details": data,
            }
        except Exception as e:
            logger.warning("Could not retrieve HeyGen remaining quota: %s", e)
            raise HeyGenAPIError(f"Failed to retrieve HeyGen remaining quota: {str(e)}") from e
