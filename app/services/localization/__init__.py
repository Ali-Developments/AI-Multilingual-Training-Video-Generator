"""Localization and Cultural Adaptation service package."""

from app.services.localization.locale_utils import (
    normalize_locale,
    get_text_direction,
    get_language_name,
    get_region_name,
)
from app.services.localization.validators import (
    normalize_localized_structure_and_durations,
    validate_localized_script,
)
from app.services.localization.service import LocalizationService
from app.services.localization.prompts import (
    SYSTEM_PROMPT_LOCALIZER,
    SYSTEM_PROMPT_LOCALIZATION_REVISER,
    build_localization_prompt,
    build_localization_revision_prompt,
)

__all__ = [
    "LocalizationService",
    "normalize_locale",
    "get_text_direction",
    "get_language_name",
    "get_region_name",
    "normalize_localized_structure_and_durations",
    "validate_localized_script",
    "SYSTEM_PROMPT_LOCALIZER",
    "SYSTEM_PROMPT_LOCALIZATION_REVISER",
    "build_localization_prompt",
    "build_localization_revision_prompt",
]
