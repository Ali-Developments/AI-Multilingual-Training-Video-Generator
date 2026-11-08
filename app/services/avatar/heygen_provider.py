"""HeyGen API provider for cloud-rendered talking-head avatar video synthesis."""

import time
from pathlib import Path
from typing import Optional, Dict, Any
import requests
from app.core.config import settings
from app.core.logging import logger
from app.services.avatar.base import AvatarProvider


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
    Production-ready integration with HeyGen video generation API.
    
    CRITICAL: Guarded by settings.ENABLE_LIVE_API_TESTS to prevent
    unintended credit consumption during automated testing.
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
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _check_live_call_permitted(self) -> None:
        """
        Enforce credit cost safety policy.
        
        - Application runtime (Streamlit/FastAPI): requires ENABLE_LIVE_HEYGEN=True.
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
        Upload a local audio file to HeyGen v3 assets storage and return the public audio URL.
        Does not consume video generation credits.
        """
        headers = {"X-Api-Key": self.api_key}
        file_obj = Path(file_path)
        with open(file_obj, "rb") as f:
            files = {"file": (file_obj.name, f, "audio/mpeg")}
            response = self.session.post(
                f"{self.BASE_URL}/v3/assets",
                headers=headers,
                files=files,
                timeout=30,
            )
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
        audio_path: Path,
        avatar_id: Optional[str] = None,
    ) -> str:
        headers = self._get_headers()
        self._check_live_call_permitted()
        chosen_avatar = avatar_id or settings.HEYGEN_DEFAULT_AVATAR_ID

        # Resolve audio URL: reuse existing cached asset URL if present, otherwise upload
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

        payload = {
            "video_inputs": [
                {
                    "character": {
                        "type": "avatar",
                        "avatar_id": chosen_avatar,
                        "avatar_style": "normal",
                    },
                    "voice": {
                        "type": "audio",
                        "audio_url": resolved_audio_url,
                    },
                }
            ],
            "dimension": {"width": 1920, "height": 1080},
        }

        url = f"{self.BASE_URL}/v2/video/generate"

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.post(url, json=payload, headers=headers, timeout=30)
                if response.status_code == 401 or response.status_code == 403:
                    raise HeyGenAuthError(f"HeyGen authentication error: {response.text}")
                elif response.status_code == 402:
                    raise HeyGenPaymentRequiredError(
                        f"HeyGen payment required (HTTP 402): insufficient account balance or credits. Details: {response.text}"
                    )
                elif response.status_code == 429:
                    if attempt < self.max_retries:
                        time.sleep(2.0 ** attempt)
                        continue
                    raise HeyGenRateLimitError("HeyGen rate limit exceeded.")

                response.raise_for_status()
                data = response.json()
                video_id = data.get("data", {}).get("video_id")
                if not video_id:
                    raise HeyGenAPIError(f"HeyGen response missing video_id: {data}")
                return video_id
            except (HeyGenAuthError, HeyGenRateLimitError, HeyGenPaymentRequiredError):
                raise
            except Exception as e:
                if attempt == self.max_retries:
                    raise HeyGenAPIError(f"HeyGen submission failed: {str(e)}") from e
                time.sleep(1.5 ** attempt)

        raise HeyGenAPIError("HeyGen submission retries exhausted.")

    def poll_avatar_job(self, job_id: str) -> Dict[str, Any]:
        self._check_live_call_permitted()
        headers = self._get_headers()
        url = f"{self.BASE_URL}/v1/video_status.get?video_id={job_id}"

        try:
            response = self.session.get(url, headers=headers, timeout=20)
            if response.status_code == 401:
                raise HeyGenAuthError("Invalid HeyGen credentials.")
            response.raise_for_status()
            data = response.json().get("data", {})
            raw_status = data.get("status", "").lower()

            if raw_status in ("completed", "done", "success"):
                return {"status": "completed", "video_url": data.get("video_url")}
            elif raw_status in ("failed", "error"):
                return {"status": "failed", "error": data.get("error", "HeyGen render failed")}
            else:
                return {"status": "processing"}
        except Exception as e:
            logger.warning("HeyGen status check failed for '%s': %s", job_id, str(e))
            return {"status": "processing"}

    def download_avatar_video(self, video_url: str, destination_path: Path) -> Path:
        self._check_live_call_permitted()
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with self.session.get(video_url, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                with open(destination_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        f.write(chunk)
            return destination_path
        except Exception as e:
            raise HeyGenAPIError(f"Failed to download avatar video from '{video_url}': {str(e)}") from e
