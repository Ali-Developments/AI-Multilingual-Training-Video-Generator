"""Google Cloud / Vertex AI Veo Video Generation Provider.

Generates high-definition AI B-Roll and instructional video clips using
Google's official Veo video models (veo-3.1-fast-generate-001, veo-3.1-generate-001)
via the Vertex AI predictLongRunning operation protocol.
"""

import base64
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import quote_plus

import requests

from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import LocalizedScene
from app.services.media.base import SceneMediaProvider
from app.services.composition.ffmpeg_utils import validate_video_file, probe_video_file
from app.core.caching import save_asset_metadata, load_asset_metadata, hash_text


# ===========================================================================
# Explicit Veo Error Hierarchy
# ===========================================================================

class VeoError(Exception):
    """Base exception for all Google Veo video operations."""
    pass


class VeoConfigError(VeoError):
    """Configuration error: missing project, location, or unsupported model."""
    pass


class VeoAuthError(VeoError):
    """Authentication failure: invalid token, credentials, or 401/403 status."""
    pass


class VeoQuotaError(VeoError):
    """Quota or budget exhaustion on Google Cloud project."""
    pass


class VeoRateLimitError(VeoError):
    """Rate limit (HTTP 429) exceeded for Vertex AI Veo operations."""
    pass


class VeoTimeoutError(VeoError):
    """Operation timed out waiting for Veo video rendering completion."""
    pass


class VeoGenerationError(VeoError):
    """Vertex AI Veo video generation process failed or reported an internal error."""
    pass


class VeoStorageError(VeoError):
    """Failed to download or retrieve generated video asset from Google Cloud Storage."""
    pass


class VeoValidationError(VeoError):
    """Generated video file failed technical validation (e.g. corrupted MP4, no video stream)."""
    pass


# Supported official models
SUPPORTED_VEO_MODELS = {
    "veo-3.1-fast-generate-001",
    "veo-3.1-generate-001",
    "veo-2.0-generate-001",
    "veo-3.0-generate-preview",
    "veo-3.1-generate-preview",
}


# ===========================================================================
# Google Veo Video Provider Implementation
# ===========================================================================

class VeoVideoProvider(SceneMediaProvider):
    """
    Production-ready Google Veo video provider using official Vertex AI APIs.
    
    Adheres strictly to:
    - Long-running operation (predictLongRunning) asynchronous lifecycle
    - Text-to-Video and Image-to-Video modalities
    - 16:9 aspect ratio and configurable resolution (720p/1080p)
    - Structured pricing metadata and budget safety gates
    - Safe idempotency preventing duplicate paid generation
    - Technical validation using ffprobe
    - Zero silent fallbacks (reports true failures)
    """

    def __init__(
        self,
        project: Optional[str] = None,
        location: Optional[str] = None,
        credentials_path: Optional[str] = None,
        model: Optional[str] = None,
        storage_bucket: Optional[str] = None,
        poll_interval: Optional[float] = None,
        timeout_seconds: Optional[int] = None,
        access_token: Optional[str] = None,
        session: Optional[requests.Session] = None,
        max_retries: int = 3,
    ) -> None:
        if project is not None:
            self.project = project.strip()
        else:
            self.project = (getattr(settings, "GOOGLE_CLOUD_PROJECT", None) or getattr(settings, "GCP_PROJECT_ID", None) or "").strip()

        if location is not None:
            self.location = location.strip()
        else:
            self.location = (getattr(settings, "GOOGLE_CLOUD_LOCATION", "us-central1") or "us-central1").strip()
        self.credentials_path = credentials_path or getattr(settings, "GOOGLE_APPLICATION_CREDENTIALS", None)
        self.model = (model or getattr(settings, "VEO_MODEL", "veo-3.1-fast-generate-001") or "veo-3.1-fast-generate-001").strip()
        self.storage_bucket = storage_bucket or getattr(settings, "GOOGLE_CLOUD_STORAGE_BUCKET", None) or getattr(settings, "VEO_GCS_OUTPUT_BUCKET", None)
        self.poll_interval = poll_interval or getattr(settings, "VEO_POLL_INTERVAL_SECONDS", 5.0)
        self.timeout_seconds = timeout_seconds or getattr(settings, "VEO_JOB_TIMEOUT_SECONDS", 600)
        self.access_token = access_token
        self.session = session or requests.Session()
        self.max_retries = max_retries

    @property
    def provider_name(self) -> str:
        return "veo"

    def supports_media_type(self, media_type: str) -> bool:
        """Return True if media_type indicates an AI video or B-Roll requirement."""
        if not media_type:
            return False
        mt = str(media_type).strip().lower()
        return mt in ("veo", "ai_video", "broll", "motion_visual")

    def validate_configuration(self) -> None:
        """
        Validate that required GCP project, location, and supported model are configured.
        Raises VeoConfigError if invalid.
        """
        if not self.project:
            raise VeoConfigError(
                "Missing GOOGLE_CLOUD_PROJECT configuration. Specify project ID in environment or constructor."
            )
        if not self.location:
            raise VeoConfigError(
                "Missing GOOGLE_CLOUD_LOCATION configuration. Specify GCP region (e.g. 'us-central1')."
            )
        if self.model not in SUPPORTED_VEO_MODELS:
            logger.warning(
                "Model '%s' is not in standard verified Veo models list (%s). Proceeding with configured model.",
                self.model, SUPPORTED_VEO_MODELS
            )

    def _check_live_call_permitted(self) -> None:
        """
        Enforce credit and budget safety guard:
        - Application runtime requires ENABLE_LIVE_VEO=True.
        - Automated test suite (pytest) requires ENABLE_LIVE_API_TESTS=True.
        """
        if not getattr(settings, "ENABLE_LIVE_VEO", False):
            raise RuntimeError(
                "Live Google Veo video generation is disabled by configuration (ENABLE_LIVE_VEO=False). "
                "Set ENABLE_LIVE_VEO=True to permit paid Vertex AI generation, or use LocalMotionVisualProvider."
            )

        is_test_env = "pytest" in sys.modules
        if is_test_env and not getattr(settings, "ENABLE_LIVE_API_TESTS", False):
            raise RuntimeError(
                "Live Veo API calls during automated tests are strictly blocked (ENABLE_LIVE_API_TESTS=False). "
                "Mock Vertex AI API responses or use MockMediaProvider in test suites."
            )

    def _get_bearer_token(self) -> str:
        """
        Resolve an active OAuth 2.0 Bearer access token for Vertex AI.
        
        Attempts in order:
        1. Explicitly configured access_token
        2. google.auth.default Application Default Credentials (ADC)
        3. Service account key file at GOOGLE_APPLICATION_CREDENTIALS
        4. gcloud CLI fallback (local dev environment)
        """
        if self.access_token and self.access_token.strip():
            return self.access_token.strip()

        # 1. Try google.auth
        try:
            import google.auth
            from google.auth.transport.requests import Request as AuthRequest

            scopes = ["https://www.googleapis.com/auth/cloud-platform"]
            credentials, detected_project = google.auth.default(scopes=scopes)
            if not self.project and detected_project:
                self.project = detected_project

            auth_req = AuthRequest()
            credentials.refresh(auth_req)
            if credentials.token:
                return credentials.token
        except Exception as e:
            logger.debug("google.auth token acquisition failed or not configured: %s", e)

        # 2. Try gcloud CLI auth in dev
        try:
            res = subprocess.run(
                ["gcloud", "auth", "print-access-token"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass

        raise VeoAuthError(
            "Could not obtain Google Cloud OAuth 2.0 access token for Vertex AI. "
            "Configure GOOGLE_APPLICATION_CREDENTIALS or log in via 'gcloud auth application-default login'."
        )

    def _get_headers(self) -> Dict[str, str]:
        """Prepare secure headers containing authorization bearer token."""
        token = self._get_bearer_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def calculate_pricing_metadata(
        self,
        model: Optional[str] = None,
        resolution: str = "1080p",
        duration_seconds: float = 5.0,
    ) -> Dict[str, Any]:
        """
        Calculate structured pricing metadata based on official Vertex AI pricing SKUs.
        
        Billing Unit: per-second of generated video output.
        Estimated Rates:
        - veo-3.1-fast-generate-001: ~$0.15 / second
        - veo-3.1-generate-001: ~$0.40 / second
        """
        active_model = model or self.model
        dur = max(float(duration_seconds), 1.0)
        
        is_fast = "fast" in active_model.lower()
        default_rate = getattr(settings, "VEO_PRICE_PER_SECOND_FAST", 0.15) if is_fast else getattr(settings, "VEO_PRICE_PER_SECOND_STANDARD", 0.40)
        
        return {
            "model_id": active_model,
            "resolution": resolution,
            "output_modality": "video",
            "billing_unit": "per_second",
            "rate_per_unit": float(default_rate),
            "duration_seconds": round(dur, 2),
            "estimated_cost": round(float(default_rate) * dur, 4),
            "actual_cost": None,  # Explicitly marked None if provider doesn't report it
            "pricing_source": "Google Cloud Vertex AI Generative AI Video Pricing SKU",
            "pricing_last_verified_at": "2026-11-08",
        }

    def build_prompt_from_scene(self, scene: LocalizedScene) -> str:
        """
        Extract and format a rich visual motion prompt from the scene specification.
        Never hardcodes topic-specific details into the general provider.
        """
        visual_desc = getattr(scene, "visual_description", None)
        motion_desc = getattr(scene, "motion_description", None)
        title = getattr(scene, "title", "Training scene")
        narration = getattr(scene, "narration", "")

        prompt_parts = []
        if visual_desc and visual_desc.strip():
            prompt_parts.append(visual_desc.strip())
        elif title:
            prompt_parts.append(f"Cinematic instructional footage illustrating: {title}.")

        if motion_desc and motion_desc.strip():
            prompt_parts.append(f"Motion: {motion_desc.strip()}.")
        else:
            prompt_parts.append("Smooth camera movement, professional studio lighting, 4k ultra-high definition.")

        if narration and len(prompt_parts) == 1:
            snippet = narration[:120].strip()
            prompt_parts.append(f"Context: {snippet}")

        full_prompt = " ".join(prompt_parts).strip()
        return full_prompt

    def submit_generation_operation(
        self,
        prompt: str,
        image_path: Optional[Path] = None,
        duration_seconds: float = 5.0,
        resolution: str = "1080p",
        aspect_ratio: str = "16:9",
        project_id: Optional[str] = None,
        scene_id: Optional[str] = None,
    ) -> str:
        """
        Submit asynchronous video generation request to Vertex AI Veo :predictLongRunning.
        
        Returns:
            operation_name: Unique GCP operation path, e.g.:
            'projects/{project}/locations/{location}/operations/{op_id}'
        """
        self._check_live_call_permitted()
        self.validate_configuration()
        headers = self._get_headers()

        # Build Instance (Text-to-Video or Image-to-Video)
        instance: Dict[str, Any] = {"prompt": prompt}

        if image_path:
            img_file = Path(image_path).resolve()
            if not img_file.exists() or img_file.stat().st_size == 0:
                raise VeoConfigError(f"Provided source image file does not exist or is empty: {image_path}")

            mime_type, _ = mimetypes.guess_type(str(img_file))
            if not mime_type or not mime_type.startswith("image/"):
                mime_type = "image/png"

            img_bytes = img_file.read_bytes()
            b64_str = base64.b64encode(img_bytes).decode("ascii")
            instance["image"] = {
                "bytesBase64Encoded": b64_str,
                "mimeType": mime_type,
            }
            logger.info("Configured Veo Image-to-Video generation using reference image: '%s'", img_file.name)
        else:
            logger.info("Configured Veo Text-to-Video generation.")

        # Clamp duration to supported ranges (typically 5 to 8 seconds)
        dur_int = max(min(int(round(duration_seconds)), 8), 5)

        parameters: Dict[str, Any] = {
            "aspectRatio": aspect_ratio,
            "durationSeconds": dur_int,
            "resolution": resolution,
            "sampleCount": 1,
            "personGeneration": "allow_all",
        }

        # Optional GCS bucket output destination
        if self.storage_bucket:
            bucket_clean = self.storage_bucket.replace("gs://", "").strip().rstrip("/")
            proj_folder = project_id or "default_project"
            sc_folder = scene_id or "scene"
            parameters["storageUri"] = f"gs://{bucket_clean}/veo_outputs/{proj_folder}/{sc_folder}"

        payload = {
            "instances": [instance],
            "parameters": parameters,
        }

        url = (
            f"https://{self.location}-aiplatform.googleapis.com/v1/"
            f"projects/{self.project}/locations/{self.location}/publishers/google/models/{self.model}:predictLongRunning"
        )

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(
                    "Submitting Veo predictLongRunning (attempt %d/%d, model=%s, dur=%ds, res=%s)",
                    attempt, self.max_retries, self.model, dur_int, resolution
                )
                response = self.session.post(url, json=payload, headers=headers, timeout=45)

                if response.status_code in (401, 403):
                    raise VeoAuthError(f"Vertex AI authentication failure: {response.text}")
                elif response.status_code == 429:
                    if attempt < self.max_retries:
                        backoff = 2.0 ** attempt
                        logger.warning("Veo rate limited (429); backing off for %.1fs...", backoff)
                        time.sleep(backoff)
                        continue
                    raise VeoRateLimitError("Vertex AI Veo rate limit exceeded.")
                elif response.status_code == 400:
                    raise VeoConfigError(f"Vertex AI invalid request parameters: {response.text}")
                elif response.status_code == 404:
                    raise VeoConfigError(f"Vertex AI resource or model not found: {response.text}")

                response.raise_for_status()
                data = response.json()
                operation_name = data.get("name")
                if not operation_name:
                    raise VeoGenerationError(f"Veo operation submission response missing 'name': {data}")

                logger.info("Veo operation submitted successfully: '%s'", operation_name)
                return operation_name

            except (VeoAuthError, VeoRateLimitError, VeoConfigError):
                raise
            except Exception as e:
                if attempt == self.max_retries:
                    raise VeoGenerationError(f"Veo submission failed after {self.max_retries} attempts: {str(e)}") from e
                time.sleep(1.5 ** attempt)

        raise VeoGenerationError("Veo operation submission retries exhausted.")

    def poll_operation(self, operation_name: str) -> Dict[str, Any]:
        """
        Poll status of an asynchronous Vertex AI operation.
        
        Returns:
            Dict containing:
                done: bool
                status: 'processing' | 'completed' | 'failed'
                video_bytes: Optional[bytes]
                gcs_uri: Optional[str]
                error: Optional[str]
        """
        self._check_live_call_permitted()
        headers = self._get_headers()
        
        # Operation URL
        op_path = operation_name.lstrip("/")
        url = f"https://{self.location}-aiplatform.googleapis.com/v1/{op_path}"

        try:
            response = self.session.get(url, headers=headers, timeout=30)
            if response.status_code in (401, 403):
                raise VeoAuthError(f"Vertex AI authentication failure during polling: {response.text}")
            elif response.status_code == 429:
                logger.warning("Veo polling hit rate limit (429); returning processing status.")
                return {"done": False, "status": "processing"}

            response.raise_for_status()
            data = response.json()
            is_done = bool(data.get("done", False))

            if not is_done:
                return {"done": False, "status": "processing"}

            # Check for operation level error
            if "error" in data:
                err_info = data["error"]
                err_msg = err_info.get("message") or str(err_info)
                code = err_info.get("code")
                if code == 8 or "quota" in err_msg.lower():
                    raise VeoQuotaError(f"Vertex AI Veo quota exhausted: {err_msg}")
                return {"done": True, "status": "failed", "error": err_msg}

            # Parse prediction response
            resp_body = data.get("response", {})
            gen_resp = resp_body.get("generateVideoResponse", {})
            samples = gen_resp.get("generatedSamples") or []

            if not samples:
                # Check direct output in response
                samples = resp_body.get("generatedSamples") or []

            if not samples:
                return {"done": True, "status": "failed", "error": "Operation completed but returned no video samples."}

            first_sample = samples[0]
            video_info = first_sample.get("video", {})

            # 1. Base64 encoded video bytes
            b64_video = video_info.get("bytesBase64Encoded")
            if b64_video:
                raw_bytes = base64.b64decode(b64_video)
                return {
                    "done": True,
                    "status": "completed",
                    "video_bytes": raw_bytes,
                    "gcs_uri": None,
                }

            # 2. GCS URI
            gcs_uri = video_info.get("uri") or video_info.get("gcsUri")
            if gcs_uri:
                return {
                    "done": True,
                    "status": "completed",
                    "video_bytes": None,
                    "gcs_uri": gcs_uri,
                }

            return {"done": True, "status": "failed", "error": f"Unrecognized sample structure in response: {first_sample}"}

        except (VeoAuthError, VeoQuotaError):
            raise
        except Exception as e:
            logger.warning("Veo status polling request failed for '%s': %s", operation_name, e)
            return {"done": False, "status": "processing"}

    def download_gcs_asset(self, gcs_uri: str, destination_path: Path) -> Path:
        """
        Download video from Google Cloud Storage URI to local destination.
        Uses Cloud Storage REST API with OAuth Bearer token or google-cloud-storage if available.
        """
        self._check_live_call_permitted()
        destination_path = Path(destination_path).resolve()
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        # Parse gs://bucket/object/path.mp4
        match = re.match(r"^gs://([^/]+)/(.+)$", gcs_uri)
        if not match:
            raise VeoStorageError(f"Invalid GCS URI format: {gcs_uri}")

        bucket_name, object_name = match.group(1), match.group(2)
        headers = self._get_headers()
        api_url = f"https://storage.googleapis.com/storage/v1/b/{bucket_name}/o/{quote_plus(object_name)}?alt=media"

        try:
            with self.session.get(api_url, headers=headers, stream=True, timeout=90) as resp:
                if resp.status_code == 404:
                    raise VeoStorageError(f"GCS object not found: {gcs_uri}")
                elif resp.status_code in (401, 403):
                    raise VeoAuthError(f"Unauthorized to access GCS URI '{gcs_uri}': {resp.text}")
                resp.raise_for_status()

                with open(destination_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=131072):
                        if chunk:
                            f.write(chunk)

            return destination_path

        except (VeoStorageError, VeoAuthError):
            raise
        except Exception as e:
            raise VeoStorageError(f"Failed to download GCS video asset from '{gcs_uri}': {str(e)}") from e

    def generate_scene_media(
        self,
        scene: LocalizedScene,
        locale: str,
        output_dir: Path,
        duration_seconds: float,
        background_image_path: Optional[Path] = None,
        custom_media_path: Optional[Path] = None,
        force_regenerate: bool = False,
        project_id: Optional[str] = None,
        resolution: str = "1080p",
    ) -> Path:
        """
        High-level entrypoint satisfying SceneMediaProvider abstraction.
        Orchestrates submit -> poll -> retrieve -> validate with full idempotency.
        """
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        out_video = output_dir / f"{scene.scene_id}_veo.mp4"
        job_file = output_dir / f"{scene.scene_id}.veo_job.json"

        target_dur = max(duration_seconds, 1.0)
        cache_key = f"{scene.scene_id}:{locale}:{target_dur:.2f}:{self.model}:{resolution}"
        cache_hash = hash_text(cache_key)

        # 1. Content-aware idempotency check: reuse completed asset if valid
        if not force_regenerate and out_video.exists() and out_video.stat().st_size > 1024:
            meta = load_asset_metadata(out_video)
            if meta and meta.get("veo_hash") == cache_hash and meta.get("status") == "completed":
                try:
                    validate_video_file(out_video, min_duration=0.5, require_video=True)
                    logger.info("Reusing existing validated Veo video for scene '%s' (locale='%s')", scene.scene_id, locale)
                    return out_video
                except Exception as ex:
                    logger.warning("Existing Veo file '%s' failed validation (%s); regenerating.", out_video, ex)

        # 2. Check for in-flight operation in existing job record
        operation_name = None
        if not force_regenerate and job_file.exists():
            try:
                saved_job = json.loads(job_file.read_text(encoding="utf-8"))
                saved_op = saved_job.get("operation_name")
                saved_status = saved_job.get("status")
                if saved_op and saved_status in ("submitted", "processing"):
                    logger.info("Found in-flight Veo operation '%s'; resuming polling instead of resubmitting.", saved_op)
                    operation_name = saved_op
            except Exception as ex:
                logger.warning("Could not read existing Veo job file '%s': %s", job_file, ex)

        # 3. Submit operation if not already in flight
        if not operation_name:
            prompt = self.build_prompt_from_scene(scene)
            source_img = custom_media_path or background_image_path
            pricing = self.calculate_pricing_metadata(model=self.model, resolution=resolution, duration_seconds=target_dur)

            operation_name = self.submit_generation_operation(
                prompt=prompt,
                image_path=source_img,
                duration_seconds=target_dur,
                resolution=resolution,
                project_id=project_id,
                scene_id=scene.scene_id,
            )

            # Persist job record immediately to prevent duplicate paid requests
            job_record = {
                "operation_name": operation_name,
                "scene_id": scene.scene_id,
                "locale": locale,
                "model": self.model,
                "resolution": resolution,
                "prompt": prompt,
                "has_source_image": bool(source_img),
                "pricing": pricing,
                "submitted_at": time.time(),
                "status": "processing",
            }
            try:
                job_file.write_text(json.dumps(job_record, indent=2), encoding="utf-8")
                logger.info("Persisted Veo operation '%s' to '%s'", operation_name, job_file)
            except Exception as ex:
                logger.warning("Failed to persist Veo job record to '%s': %s", job_file, ex)

        # 4. Polling loop
        start_time = time.time()
        poll_interval = self.poll_interval

        while True:
            elapsed = time.time() - start_time
            if elapsed > self.timeout_seconds:
                raise VeoTimeoutError(
                    f"Veo video generation timed out for scene '{scene.scene_id}' after {self.timeout_seconds}s (Op: {operation_name})."
                )

            status_result = self.poll_operation(operation_name)
            if status_result.get("done"):
                if status_result.get("status") == "completed":
                    # Retrieve video asset
                    if status_result.get("video_bytes"):
                        out_video.write_bytes(status_result["video_bytes"])
                    elif status_result.get("gcs_uri"):
                        self.download_gcs_asset(status_result["gcs_uri"], out_video)
                    else:
                        raise VeoGenerationError("Operation completed without video bytes or GCS URI.")

                    # Technical stream validation
                    try:
                        probe_meta = validate_video_file(out_video, min_duration=0.5, require_video=True)
                        dur = probe_meta["duration"]
                        logger.info(
                            "Technical validation passed for Veo video '%s': %dx%d, %.2fs, codec=%s",
                            scene.scene_id, probe_meta["width"], probe_meta["height"], dur, probe_meta["video_codec"]
                        )
                    except Exception as ex:
                        if out_video.exists():
                            out_video.unlink()
                        raise VeoValidationError(f"Downloaded Veo video failed technical validation: {ex}") from ex

                    # Update job file on completion
                    try:
                        if job_file.exists():
                            rec = json.loads(job_file.read_text(encoding="utf-8"))
                            rec["status"] = "completed"
                            rec["completed_at"] = time.time()
                            rec["duration_seconds"] = dur
                            rec["video_path"] = str(out_video.resolve())
                            rec["dimensions"] = f"{probe_meta['width']}x{probe_meta['height']}"
                            job_file.write_text(json.dumps(rec, indent=2), encoding="utf-8")
                    except Exception:
                        pass

                    save_asset_metadata(
                        out_video,
                        {
                            "veo_hash": cache_hash,
                            "scene_id": scene.scene_id,
                            "locale": locale,
                            "duration": dur,
                            "model": self.model,
                            "status": "completed",
                        },
                    )
                    return out_video

                elif status_result.get("status") == "failed":
                    err_msg = status_result.get("error", "Unknown Vertex AI failure")
                    try:
                        if job_file.exists():
                            rec = json.loads(job_file.read_text(encoding="utf-8"))
                            rec["status"] = "failed"
                            rec["error"] = err_msg
                            job_file.write_text(json.dumps(rec, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                    raise VeoGenerationError(f"Veo operation '{operation_name}' failed: {err_msg}")

            time.sleep(poll_interval)
