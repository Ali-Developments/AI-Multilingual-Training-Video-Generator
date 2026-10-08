"""Lightweight script and language detection heuristics."""

import re
from typing import Optional


def detect_primary_script(text: Optional[str]) -> Optional[str]:
    """
    Detect primary script ('latin', 'arabic', 'bengali') from text using Unicode heuristics.
    
    Returns None if text is too short (< 15 relevant characters) or ambiguous.
    """
    if not text:
        return None

    # Strip URLs, digits, punctuation, and whitespace
    cleaned = re.sub(r"https?://\S+|[\d\W_]+", "", text)
    if len(cleaned) < 15:
        return None

    counts = {
        "latin": 0,
        "arabic": 0,
        "bengali": 0,
    }

    for char in cleaned:
        cp = ord(char)
        # Latin: Basic Latin + Latin-1 Supplement + Latin Extended
        if (0x0041 <= cp <= 0x005A) or (0x0061 <= cp <= 0x007A) or (0x00C0 <= cp <= 0x024F):
            counts["latin"] += 1
        # Arabic: Arabic block + Arabic Supplement + Arabic Extended-A
        elif (0x0600 <= cp <= 0x06FF) or (0x0750 <= cp <= 0x077F) or (0x08A0 <= cp <= 0x08FF):
            counts["arabic"] += 1
        # Bengali: Bengali block
        elif 0x0980 <= cp <= 0x09FF:
            counts["bengali"] += 1

    total = sum(counts.values())
    if total < 10:
        return None

    for script, count in counts.items():
        if count / total >= 0.60:
            return script

    return None


def validate_source_language_mismatch(
    text: Optional[str],
    base_language: Optional[str]
) -> Optional[str]:
    """
    Check if the text script obviously mismatches base_language.
    
    Returns an error message string if an obvious mismatch is found, otherwise None.
    """
    if not text or not base_language:
        return None

    detected_script = detect_primary_script(text)
    if not detected_script:
        return None

    lang_prefix = base_language.strip().lower().replace("_", "-").split("-")[0]

    script_names = {
        "latin": "English/Latin",
        "arabic": "Arabic",
        "bengali": "Bengali",
    }

    if detected_script == "latin" and lang_prefix in ["ar", "bn"]:
        return (
            f"Source content appears to be in {script_names[detected_script]} script, "
            f"but Source / Base Language is set to '{base_language}'. "
            f"Please set Source / Base Language to match your source content (e.g., 'en-US'), "
            f"and select '{base_language}' in Target Languages for localized translation."
        )

    if detected_script == "arabic" and lang_prefix in ["en", "bn"]:
        return (
            f"Source content appears to be in {script_names[detected_script]} script, "
            f"but Source / Base Language is set to '{base_language}'. "
            f"Please set Source / Base Language to match your Arabic source content ('ar-SA')."
        )

    if detected_script == "bengali" and lang_prefix in ["en", "ar"]:
        return (
            f"Source content appears to be in {script_names[detected_script]} script, "
            f"but Source / Base Language is set to '{base_language}'. "
            f"Please set Source / Base Language to match your Bengali source content ('bn-BD')."
        )

    return None
