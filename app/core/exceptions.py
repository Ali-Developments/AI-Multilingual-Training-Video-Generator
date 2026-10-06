"""Structured domain exception hierarchy for AI Training Video Generation Platform."""


class VideoAutomationError(Exception):
    """Base exception for all domain errors."""
    pass


class LLMProviderError(VideoAutomationError):
    """Error during LLM provider operations or inference."""
    pass


class LLMAuthenticationError(LLMProviderError):
    """Error with LLM API keys or authentication."""
    pass


class LocalizationError(VideoAutomationError):
    """Error during script localization or cultural adaptation."""
    pass


class TTSError(VideoAutomationError):
    """Error during speech synthesis or audio duration probing."""
    pass


class AvatarError(VideoAutomationError):
    """Error during avatar generation or job polling."""
    pass


class SubtitleError(VideoAutomationError):
    """Error during subtitle generation or formatting."""
    pass


class VisualError(VideoAutomationError):
    """Error during visual slide graphics creation."""
    pass


class CompositionError(VideoAutomationError):
    """Error during FFmpeg composition or video rendering."""
    pass


class OrchestratorError(VideoAutomationError):
    """Error during pipeline orchestration."""
    pass
