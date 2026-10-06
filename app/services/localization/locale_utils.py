"""Deterministic locale normalization and text direction utilities for script localization."""

import re
from typing import Optional

# BCP 47 simplified pattern: 2-3 letter language, optional 4-letter script, optional 2-letter region or 3-digit UN M.49 code
LOCALE_PATTERN = re.compile(
    r"^[a-zA-Z]{2,3}(?:[_-][a-zA-Z]{4})?(?:[_-](?:[a-zA-Z]{2}|\d{3}))?$"
)

# Common RTL language family codes
RTL_LANGUAGE_CODES = {
    "ar",  # Arabic
    "he",  # Hebrew
    "fa",  # Persian / Farsi
    "ur",  # Urdu
    "ps",  # Pashto
    "yi",  # Yiddish
    "sd",  # Sindhi
    "ug",  # Uyghur
}

# Common language names for metadata and prompt construction
LANGUAGE_NAMES = {
    "ar": "Arabic",
    "bn": "Bengali",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "hi": "Hindi",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "nl": "Dutch",
    "pt": "Portuguese",
    "ru": "Russian",
    "tr": "Turkish",
    "ur": "Urdu",
    "vi": "Vietnamese",
    "zh": "Chinese",
}

# Common region names for cultural metadata
REGION_NAMES = {
    "SA": "Saudi Arabia",
    "AE": "United Arab Emirates",
    "EG": "Egypt",
    "BD": "Bangladesh",
    "US": "United States",
    "GB": "United Kingdom",
    "IN": "India",
    "PK": "Pakistan",
    "BR": "Brazil",
    "MX": "Mexico",
    "FR": "France",
    "DE": "Germany",
    "ES": "Spain",
    "JP": "Japan",
    "CN": "China",
}


def normalize_locale(locale_str: str) -> str:
    """
    Deterministically normalize and validate a locale identifier.
    
    Examples:
        en-us -> en-US
        ar-sa -> ar-SA
        bn-bd -> bn-BD
        zh-hans-cn -> zh-Hans-CN
        es-419 -> es-419
        ar -> ar (does not invent regions if only language provided)
        en -> en
        
    Raises:
        ValueError: If the locale string is empty, malformed, or contains invalid characters.
    """
    if not locale_str or not isinstance(locale_str, str):
        raise ValueError(f"Invalid locale: '{locale_str}'. Locale identifier cannot be empty.")

    cleaned = locale_str.strip()
    if not cleaned or not LOCALE_PATTERN.match(cleaned):
        raise ValueError(
            f"Malformed locale identifier: '{locale_str}'. "
            "Must follow standard language/region format (e.g., 'ar-SA', 'bn-BD', 'en')."
        )

    parts = cleaned.replace("_", "-").split("-")

    if len(parts) == 1:
        # Language only (e.g. 'ar', 'en') -> keep language only without inventing region
        return parts[0].lower()

    if len(parts) == 2:
        lang = parts[0].lower()
        second = parts[1]
        if len(second) == 2 and second.isalpha():
            # Region code (e.g. 'SA', 'US', 'BD')
            return f"{lang}-{second.upper()}"
        elif len(second) == 3 and second.isdigit():
            # UN M.49 numeric region code (e.g. '419')
            return f"{lang}-{second}"
        elif len(second) == 4 and second.isalpha():
            # Script code (e.g. 'Hans')
            return f"{lang}-{second.capitalize()}"
        else:
            return f"{lang}-{second.upper()}"

    if len(parts) == 3:
        lang = parts[0].lower()
        script = parts[1].capitalize()
        region = parts[2].upper()
        return f"{lang}-{script}-{region}"

    return cleaned


def get_text_direction(locale_str: str) -> str:
    """
    Determine text reading direction (ltr or rtl) from a locale identifier.
    
    Returns:
        'rtl' for Arabic, Hebrew, Urdu, Persian, and other RTL language families.
        'ltr' for all others.
    """
    try:
        norm = normalize_locale(locale_str)
        lang = norm.split("-")[0]
        return "rtl" if lang in RTL_LANGUAGE_CODES else "ltr"
    except Exception:
        # Fallback inspection of raw string prefix
        raw_prefix = locale_str.strip().lower().split("-")[0].split("_")[0]
        return "rtl" if raw_prefix in RTL_LANGUAGE_CODES else "ltr"


def get_language_name(locale_str: str) -> str:
    """Return human-readable language name for a locale code."""
    try:
        norm = normalize_locale(locale_str)
        lang = norm.split("-")[0]
        return LANGUAGE_NAMES.get(lang, lang.upper())
    except Exception:
        return locale_str


def get_region_name(locale_str: str) -> Optional[str]:
    """Return human-readable region name if present in locale code."""
    try:
        norm = normalize_locale(locale_str)
        parts = norm.split("-")
        if len(parts) > 1 and len(parts[-1]) == 2:
            return REGION_NAMES.get(parts[-1], parts[-1])
        return None
    except Exception:
        return None
