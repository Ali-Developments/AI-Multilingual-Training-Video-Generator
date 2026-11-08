"""Application configuration settings using Pydantic Settings."""

from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Global application settings and environment variables."""

    # Application Information
    APP_NAME: str = "AI Training Video Generation Platform"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = Field(default="development", description="Environment: development, staging, production")
    DEBUG: bool = Field(default=True, description="Debug mode flag")
    APP_HOST: str = Field(default="0.0.0.0", description="FastAPI host")
    APP_PORT: int = Field(default=8000, description="FastAPI port")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL")

    # Local Storage Directory
    STORAGE_PATH: Path = Field(default=Path("./storage/projects"), description="Base directory for project assets")

    # LLM Settings (Groq is default, extensible to others)
    DEFAULT_LLM_PROVIDER: str = Field(default="groq", description="Default LLM provider")
    GROQ_API_KEY: Optional[str] = Field(default=None, description="Groq API Key")
    GROQ_MODEL: str = Field(default="openai/gpt-oss-20b", description="Active Groq LLM model ID")

    # TTS Settings (Edge-TTS is default free tier)
    DEFAULT_TTS_PROVIDER: str = Field(default="edge_tts", description="Default TTS provider (edge_tts, azure, mock)")
    TTS_TIMEOUT_SECONDS: int = Field(default=60, description="Timeout in seconds for TTS generation")
    TTS_DEFAULT_VOICES: dict = Field(
        default={
            "en-US": "en-US-ChristopherNeural",
            "en": "en-US-ChristopherNeural",
            "ar-SA": "ar-SA-HamedNeural",
            "ar": "ar-SA-HamedNeural",
            "bn-BD": "bn-BD-PradeepNeural",
            "bn": "bn-BD-PradeepNeural",
            "es-ES": "es-ES-AlvaroNeural",
            "es": "es-ES-AlvaroNeural",
            "fr-FR": "fr-FR-HenriNeural",
            "fr": "fr-FR-HenriNeural",
            "de-DE": "de-DE-ConradNeural",
            "de": "de-DE-ConradNeural",
            "zh-CN": "zh-CN-YunxiNeural",
            "zh": "zh-CN-YunxiNeural",
        },
        description="Default locale-to-voice mapping for TTS providers"
    )
    AZURE_SPEECH_KEY: Optional[str] = Field(default=None, description="Azure Speech API Key")
    AZURE_SPEECH_REGION: str = Field(default="eastus", description="Azure Speech Region")

    # Avatar Settings (HeyGen)
    DEFAULT_AVATAR_PROVIDER: str = Field(default="mock", description="Default avatar provider: heygen, mock")
    HEYGEN_API_KEY: Optional[str] = Field(default=None, description="HeyGen API Key")
    HEYGEN_DEFAULT_AVATAR_ID: str = Field(default="469ba809c9f6441ba74a580058d41c4b", description="Default HeyGen avatar ID (Brody - Office)")
    HEYGEN_POLL_INTERVAL_SECONDS: float = Field(default=2.0, description="Polling interval in seconds for HeyGen video rendering")
    HEYGEN_JOB_TIMEOUT_SECONDS: int = Field(default=300, description="Timeout in seconds for HeyGen video generation")
    ENABLE_LIVE_API_TESTS: bool = Field(default=False, description="Guard ensuring zero live paid API calls during testing")
    ENABLE_LIVE_HEYGEN: bool = Field(default=False, description="Separate live safety gate permitting paid HeyGen API generation at runtime")

    # SadTalker Settings (Free Local Avatar Provider)
    SADTALKER_ENABLED: bool = Field(default=False, description="Flag indicating if SadTalker local provider is enabled")
    SADTALKER_PYTHON_PATH: Path = Field(
        default=Path(".sadtalker-venv/Scripts/python.exe"),
        description="Path to isolated Python executable with SadTalker environment"
    )
    SADTALKER_ROOT: Path = Field(
        default=Path("tools/sadtalker"),
        description="Root directory of SadTalker repository containing inference.py"
    )
    SADTALKER_CHECKPOINT_PATH: Path = Field(
        default=Path("tools/sadtalker/checkpoints"),
        description="Directory containing SadTalker model checkpoints"
    )
    SADTALKER_DEFAULT_SOURCE_IMAGE: Path = Field(
        default=Path("assets/avatars/local_presenter.png"),
        description="Default project-owned source portrait image for SadTalker synthesis"
    )
    SADTALKER_RESULT_DIR: Path = Field(
        default=Path("storage/sadtalker_temp"),
        description="Temporary output directory for SadTalker batch generation"
    )
    SADTALKER_TIMEOUT_SECONDS: int = Field(
        default=600,
        description="Maximum seconds before SadTalker local inference times out"
    )
    SADTALKER_PREPROCESS: str = Field(
        default="crop",
        description="SadTalker image preprocessing mode: crop, extcrop, resize, full, extfull"
    )
    SADTALKER_STILL: bool = Field(
        default=True,
        description="Whether to use SadTalker still mode (avoids unnatural full-head shaking)"
    )
    SADTALKER_SIZE: int = Field(
        default=256,
        description="SadTalker output resolution face size (256 or 512)"
    )

    # Subtitle Settings (Whisper / Faster-Whisper / ASS Styling)
    WHISPER_MODEL_SIZE: str = Field(default="base", description="Whisper model size (tiny, base, small, medium, large)")
    WHISPER_DEVICE: str = Field(default="cpu", description="Device for Whisper inference (cpu, cuda)")
    SUBTITLE_FONT_NAME_DEFAULT: str = Field(default="Arial", description="Default font family for rendered subtitles")
    SUBTITLE_FONT_NAME_ARABIC: str = Field(default="Segoe UI", description="Font family for Arabic/RTL subtitles with complex shaping")
    SUBTITLE_FONT_NAME_BENGALI: str = Field(default="Nirmala UI", description="Font family for Bengali subtitles with complex shaping")
    SUBTITLE_FONT_SIZE: int = Field(default=42, description="Font size for burned subtitles at 1080p")

    # Supporting Visuals Settings (Step 8)
    DEFAULT_VISUAL_PROVIDER: str = Field(default="local", description="Default visual asset provider: local, mock")
    VISUAL_WIDTH: int = Field(default=1920, description="Default visual image width in pixels")
    VISUAL_HEIGHT: int = Field(default=1080, description="Default visual image height in pixels")

    # Video Composition Settings (Step 9)
    DEFAULT_COMPOSITION_PROVIDER: str = Field(default="ffmpeg", description="Default composition provider: ffmpeg, mock")
    FFMPEG_BINARY_PATH: str = Field(default="ffmpeg", description="Path to ffmpeg binary")
    FFPROBE_BINARY_PATH: str = Field(default="ffprobe", description="Path to ffprobe binary")
    VIDEO_WIDTH: int = Field(default=1920, description="Target composition video width in pixels")
    VIDEO_HEIGHT: int = Field(default=1080, description="Target composition video height in pixels")
    VIDEO_FPS: int = Field(default=30, description="Target video framerate")
    VIDEO_CODEC: str = Field(default="libx264", description="Video codec for FFmpeg rendering")
    AUDIO_CODEC: str = Field(default="aac", description="Audio codec for FFmpeg rendering")
    BURN_SUBTITLES: bool = Field(default=True, description="Whether to burn subtitles into final video render")
    AUDIO_SAMPLE_RATE: int = Field(default=48000, description="Standardized audio sample rate (Hz) for scene composition")
    AUDIO_CHANNELS: int = Field(default=2, description="Standardized audio channel count for scene composition")
    AUDIO_BITRATE: str = Field(default="192k", description="Standardized audio bitrate for scene composition")
    AVATAR_LAYOUT: str = Field(default="pip", description="Avatar layout style in composite scenes: 'pip', 'centered', 'fullscreen'")

    # Post-TTS Duration Reconciliation Settings (Step 3.5)
    POST_TTS_RECONCILIATION_ENABLED: bool = Field(default=True, description="Enable post-TTS script condensation if real audio deviates from target")
    MAX_POST_TTS_REVISIONS: int = Field(default=2, description="Maximum post-TTS narration revision attempts (safety limit)")
    POST_TTS_MAX_REVISIONS: int = Field(default=2, description="Alias for backwards compatibility with earlier iterations")
    POST_TTS_DURATION_TOLERANCE_SECONDS: float = Field(default=2.0, description="Allowed deviation in seconds between real TTS audio and target duration")
    POST_TTS_TOLERANCE_PERCENT: int = Field(default=15, description="Allowed deviation percentage between real TTS audio and target duration")

    # Script Generation & Validation Settings
    SCRIPT_WORDS_PER_MINUTE: int = Field(default=140, description="Estimated spoken words per minute for narration timing")
    SCRIPT_DURATION_TOLERANCE_PERCENT: int = Field(default=20, description="Allowed deviation percentage from target duration")
    SCRIPT_DEFAULT_MAX_REVISIONS: int = Field(default=1, description="Maximum revision iterations in LangGraph workflow")

    # Localization Settings (Step 4)
    LOCALIZATION_MAX_REVISIONS: int = Field(default=1, description="Maximum revision attempts for invalid localized scripts")
    LOCALIZATION_DEFAULT_ADAPTATION_LEVEL: str = Field(default="cultural_adaptation", description="Default adaptation level: translation, natural_localization, cultural_adaptation")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def ensure_directories(self) -> None:
        """Ensure necessary storage directories exist."""
        self.STORAGE_PATH.mkdir(parents=True, exist_ok=True)


# Singleton settings instance
settings = Settings()
settings.ensure_directories()
