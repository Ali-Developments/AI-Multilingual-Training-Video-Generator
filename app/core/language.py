"""Confidence-aware script and language detection, validation, and post-generation verification."""

from dataclasses import dataclass, field
import re
from typing import Dict, Optional, Set, Tuple

from app.services.localization.locale_utils import (
    LANGUAGE_NAMES,
    normalize_locale,
)

# Supported ISO language prefixes across the platform
SUPPORTED_LANGUAGE_PREFIXES: Set[str] = set(LANGUAGE_NAMES.keys())

# Default regional locale per primary language code
DEFAULT_LOCALE_BY_LANG: Dict[str, str] = {
    "ar": "ar-SA",
    "bn": "bn-BD",
    "de": "de-DE",
    "en": "en-US",
    "es": "es-ES",
    "fr": "fr-FR",
    "ur": "ur-PK",
    "zh": "zh-CN",
}

# High-frequency function words for Latin-script disambiguation
_EN_STOPWORDS: Set[str] = {
    "the", "and", "for", "with", "from", "that", "this", "are", "you", "your",
    "always", "never", "check", "how", "into", "when", "before", "after", "should",
    "must", "is", "in", "to", "of", "on", "by", "at", "or", "be", "as", "an",
    "will", "can", "all", "our", "their", "while", "until", "through", "between",
    "prepare", "cooking", "ingredients", "minutes", "bake", "boil", "sauce",
}

_FR_STOPWORDS: Set[str] = {
    "le", "la", "les", "des", "une", "dans", "pour", "avec", "sur", "pas",
    "plus", "sont", "vous", "votre", "cette", "aux", "par", "mais", "comme",
    "être", "faire", "du", "au", "et", "est", "que", "qui", "ne", "se", "ce",
    "nous", "tout", "tous", "sans", "sous", "avant", "après", "pendant", "très",
}

_DE_STOPWORDS: Set[str] = {
    "der", "die", "das", "und", "den", "von", "zu", "mit", "sich", "auf",
    "für", "nicht", "ist", "dem", "ein", "eine", "einer", "eines", "einem", "einen",
    "als", "auch", "es", "an", "werden", "aus", "sind", "nach", "bei", "oder",
    "wir", "sie", "über", "durch", "wie", "vor", "während", "immer", "alle",
}

# Urdu-specific characters not used in standard modern Arabic
_URDU_SPECIFIC_CHARS: Set[str] = set("ٹڈڑںےہھپچژگک")

# Urdu vs Arabic function words for Arabic-script disambiguation
_UR_STOPWORDS: Set[str] = {
    "کے", "میں", "کی", "ہے", "اور", "کو", "سے", "پر", "کا", "ہیں",
    "اس", "لیے", "کریں", "ساتھ", "ہوتا", "ہوتی", "اپنے", "اگر", "تاکہ", "جا",
    "بھی", "یہ", "وہ", "جو", "تک", "بعد", "پہلے", "طرح",
}

_AR_STOPWORDS: Set[str] = {
    "في", "من", "على", "إلى", "عن", "هذا", "هذه", "التي", "الذي", "مع",
    "أو", "أن", "إن", "كل", "عند", "تم", "قبل", "بعد", "ذلك", "حيث",
    "كيف", "يجب", "لا", "ما", "بين", "خلال", "نحو", "حتى", "إلا", "تحت",
    "فوق", "حول", "ضد", "دائما", "دائماً", "أثناء", "طريق", "طريقة",
}

# Arabic-specific characters rarely appearing in Urdu orthography
_ARABIC_SPECIFIC_CHARS: Set[str] = set("ةىأإؤئ")


@dataclass
class LanguageDetectionResult:
    """Confidence-aware result of source language and script analysis."""

    detected_locale: Optional[str] = None
    detected_language: Optional[str] = None
    primary_script: Optional[str] = None
    confidence: float = 0.0
    is_mixed: bool = False
    is_uncertain: bool = True
    script_ratios: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "detected_locale": self.detected_locale,
            "detected_language": self.detected_language,
            "primary_script": self.primary_script,
            "confidence": round(self.confidence, 3),
            "is_mixed": self.is_mixed,
            "is_uncertain": self.is_uncertain,
            "script_ratios": {k: round(v, 3) for k, v in self.script_ratios.items()},
        }


def _count_scripts(text: str) -> Tuple[Dict[str, int], int]:
    """Count alphabetic characters by script family ('latin', 'arabic', 'bengali')."""
    cleaned = re.sub(r"https?://\S+|[\d\W_]+", "", text)
    counts = {"latin": 0, "arabic": 0, "bengali": 0}
    for char in cleaned:
        cp = ord(char)
        if (0x0041 <= cp <= 0x005A) or (0x0061 <= cp <= 0x007A) or (0x00C0 <= cp <= 0x024F):
            counts["latin"] += 1
        elif (
            (0x0600 <= cp <= 0x06FF)
            or (0x0750 <= cp <= 0x077F)
            or (0x08A0 <= cp <= 0x08FF)
            or (0xFB50 <= cp <= 0xFDFF)
            or (0xFE70 <= cp <= 0xFEFF)
        ):
            counts["arabic"] += 1
        elif 0x0980 <= cp <= 0x09FF:
            counts["bengali"] += 1
    total = sum(counts.values())
    return counts, total


def detect_primary_script(text: Optional[str]) -> Optional[str]:
    """
    Detect primary script ('latin', 'arabic', 'bengali') from text using Unicode heuristics.

    Returns None if text is too short (< 15 relevant characters) or ambiguous.
    """
    if not text:
        return None

    cleaned = re.sub(r"https?://\S+|[\d\W_]+", "", text)
    if len(cleaned) < 15:
        return None

    counts, total = _count_scripts(text)
    if total < 10:
        return None

    for script, count in counts.items():
        if count / total >= 0.60:
            return script

    return None


def _disambiguate_arabic_script(text: str, script_purity: float) -> Tuple[Optional[str], Optional[str], float, bool]:
    """Distinguish Arabic ('ar-SA') vs Urdu ('ur-PK') within Arabic-script text."""
    words = re.findall(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+", text)
    if not words:
        return None, None, 0.0, True

    urdu_char_hits = sum(1 for ch in text if ch in _URDU_SPECIFIC_CHARS)
    arabic_char_hits = sum(1 for ch in text if ch in _ARABIC_SPECIFIC_CHARS)

    urdu_word_hits = sum(1 for w in words if w in _UR_STOPWORDS)
    arabic_word_hits = sum(1 for w in words if w in _AR_STOPWORDS)

    urdu_score = (urdu_char_hits * 1.5) + (urdu_word_hits * 2.5)
    arabic_score = (arabic_char_hits * 1.2) + (arabic_word_hits * 2.5)

    # Check Arabic definite article prefix 'ال' which is very frequent in Arabic
    al_prefix_hits = sum(1 for w in words if len(w) >= 4 and w.startswith("ال"))
    arabic_score += al_prefix_hits * 1.0

    total_score = urdu_score + arabic_score
    if total_score < 1.5:
        # Ambiguous short Arabic-script phrase without clear Urdu or Arabic markers
        return None, None, 0.35, True

    if urdu_score > arabic_score * 1.15:
        conf = min(0.98, 0.55 + (urdu_score / (total_score + 2.0)) * 0.40) * max(0.75, script_purity)
        return "ur-PK", "ur", conf, conf < 0.55

    if arabic_score >= urdu_score:
        conf = min(0.98, 0.55 + (arabic_score / (total_score + 2.0)) * 0.40) * max(0.75, script_purity)
        return "ar-SA", "ar", conf, conf < 0.55

    return None, None, 0.40, True


def _disambiguate_latin_script(text: str, script_purity: float) -> Tuple[Optional[str], Optional[str], float, bool]:
    """Distinguish English ('en-US'), French ('fr-FR'), and German ('de-DE') within Latin-script text."""
    lower_text = text.lower()
    words = re.findall(r"[a-zA-ZÀ-ÿœŒ]+", lower_text)
    if not words:
        return None, None, 0.0, True

    en_hits = sum(1 for w in words if w in _EN_STOPWORDS)
    fr_hits = sum(1 for w in words if w in _FR_STOPWORDS)
    de_hits = sum(1 for w in words if w in _DE_STOPWORDS)

    # Orthographic / diacritic signals
    de_diacritics = len(re.findall(r"[äöüß]", lower_text))
    fr_diacritics = len(re.findall(r"[éèêëàâçùûîïôœ]", lower_text))
    fr_contractions = len(re.findall(r"\b(?:l|d|qu|n|c|s|j|m)'[a-zà-ÿ]", lower_text))

    scores = {
        "en": en_hits * 2.0,
        "fr": (fr_hits * 2.0) + (fr_diacritics * 1.5) + (fr_contractions * 2.5),
        "de": (de_hits * 2.0) + (de_diacritics * 2.0),
    }

    best_lang = max(scores, key=lambda k: scores[k])
    best_score = scores[best_lang]
    sorted_scores = sorted(scores.values(), reverse=True)
    second_score = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
    total_score = sum(scores.values())

    # If very few words or no stopword/diacritic hits, detection is uncertain
    if best_score < 2.0 or (len(words) < 3 and best_score < 3.0):
        return None, None, 0.30, True

    # If top two languages are nearly tied, mark uncertain
    if second_score > 0 and best_score < second_score * 1.25:
        return None, None, 0.45, True

    margin = (best_score - second_score) / max(1.0, total_score)
    length_factor = min(1.0, len(words) / 8.0)
    conf = min(0.98, (0.55 + 0.35 * margin) * (0.7 + 0.3 * length_factor) * max(0.75, script_purity))
    locale = DEFAULT_LOCALE_BY_LANG.get(best_lang, f"{best_lang}-{best_lang.upper()}")
    return locale, best_lang, conf, conf < 0.55


def detect_source_language(
    text: Optional[str] = None,
    topic: Optional[str] = None,
    source_content: Optional[str] = None,
) -> LanguageDetectionResult:
    """
    Confidence-aware source language and script detector supporting:
    - Arabic (ar-SA)
    - Urdu (ur-PK)
    - Bengali (bn-BD)
    - English (en-US)
    - French (fr-FR)
    - German (de-DE)
    - Mixed-language content (e.g., Arabic + English technical terms)

    Inspects both topic and source_content when provided.
    """
    parts = []
    if topic and topic.strip():
        parts.append(topic.strip())
    if source_content and source_content.strip():
        parts.append(source_content.strip())
    if text and text.strip() and not parts:
        parts.append(text.strip())

    combined = "\n".join(parts).strip()
    if not combined:
        return LanguageDetectionResult()

    counts, total = _count_scripts(combined)
    if total < 4:
        return LanguageDetectionResult()

    ratios = {k: (v / total) for k, v in counts.items()}
    active_scripts = [k for k, r in ratios.items() if r >= 0.15 and counts[k] >= 4]
    is_mixed = len(active_scripts) >= 2

    dominant_script = max(ratios, key=lambda k: ratios[k])
    dominant_ratio = ratios[dominant_script]
    primary_script = "mixed" if (is_mixed and dominant_ratio < 0.65) else dominant_script

    if dominant_script == "bengali" and ratios["bengali"] >= 0.35:
        conf = min(0.98, (0.60 + 0.35 * ratios["bengali"]) * min(1.0, total / 15.0))
        return LanguageDetectionResult(
            detected_locale="bn-BD",
            detected_language="bn",
            primary_script=primary_script,
            confidence=conf,
            is_mixed=is_mixed,
            is_uncertain=conf < 0.55,
            script_ratios=ratios,
        )

    if dominant_script == "arabic" or (is_mixed and ratios["arabic"] >= 0.35):
        locale, lang, conf, uncertain = _disambiguate_arabic_script(combined, ratios["arabic"])
        return LanguageDetectionResult(
            detected_locale=locale,
            detected_language=lang,
            primary_script=primary_script,
            confidence=conf,
            is_mixed=is_mixed,
            is_uncertain=uncertain,
            script_ratios=ratios,
        )

    if dominant_script == "latin" and ratios["latin"] >= 0.40:
        locale, lang, conf, uncertain = _disambiguate_latin_script(combined, ratios["latin"])
        return LanguageDetectionResult(
            detected_locale=locale,
            detected_language=lang,
            primary_script=primary_script,
            confidence=conf,
            is_mixed=is_mixed,
            is_uncertain=uncertain,
            script_ratios=ratios,
        )

    return LanguageDetectionResult(
        detected_locale=None,
        detected_language=None,
        primary_script=primary_script,
        confidence=0.30,
        is_mixed=is_mixed,
        is_uncertain=True,
        script_ratios=ratios,
    )


def validate_supported_locale(locale_str: Optional[str], allow_auto: bool = False) -> str:
    """
    Validate and normalize a locale string, ensuring its language code is supported.

    Raises ValueError (HTTP 422 in Pydantic) if malformed or unsupported.
    """
    if not locale_str or not isinstance(locale_str, str) or not locale_str.strip():
        raise ValueError("Locale identifier cannot be empty.")

    cleaned = locale_str.strip()
    if allow_auto and cleaned.lower() == "auto":
        return "auto"

    norm = normalize_locale(cleaned)
    lang_prefix = norm.split("-")[0].lower()
    if lang_prefix not in SUPPORTED_LANGUAGE_PREFIXES:
        supported_list = ", ".join(sorted(SUPPORTED_LANGUAGE_PREFIXES))
        raise ValueError(
            f"Unsupported locale or language code '{locale_str}' (prefix '{lang_prefix}'). "
            f"Supported language prefixes: {supported_list}."
        )
    return norm


def check_source_canonical_mismatch_warning(
    topic: Optional[str],
    source_content: Optional[str],
    canonical_language: str,
    explicit_source_language: Optional[str] = None,
) -> Tuple[Optional[str], LanguageDetectionResult]:
    """
    Evaluate source content against canonical_language and return a non-blocking warning
    if the source language differs from the canonical script language or is mixed.
    """
    detection = detect_source_language(topic=topic, source_content=source_content)
    canon_prefix = canonical_language.strip().lower().replace("_", "-").split("-")[0]
    canon_name = LANGUAGE_NAMES.get(canon_prefix, canonical_language)

    # Check if user explicitly specified a non-auto source language
    if explicit_source_language and explicit_source_language.strip().lower() != "auto":
        src_prefix = explicit_source_language.strip().lower().replace("_", "-").split("-")[0]
        src_name = LANGUAGE_NAMES.get(src_prefix, explicit_source_language)
        if src_prefix != canon_prefix:
            return (
                f"Source language is set to {src_name} ('{explicit_source_language}') while Canonical Script Language "
                f"is {canon_name} ('{canonical_language}'). The canonical script will be generated in {canon_name}."
            ), detection

    if detection.is_mixed:
        return (
            f"Mixed-language source material detected. The canonical script will be unified and authored "
            f"in {canon_name} ('{canonical_language}')."
        ), detection

    if not detection.is_uncertain and detection.detected_language:
        det_lang = detection.detected_language
        det_name = LANGUAGE_NAMES.get(det_lang, det_lang)
        if det_lang != canon_prefix:
            return (
                f"Source content appears to be in {det_name} ('{detection.detected_locale}'), "
                f"while Canonical Script Language is set to {canon_name} ('{canonical_language}'). "
                f"The canonical script will be generated in {canon_name} from your {det_name} source material."
            ), detection

    return None, detection


def validate_source_language_mismatch(
    text: Optional[str],
    base_language: Optional[str],
    topic: Optional[str] = None,
) -> Optional[str]:
    """
    Non-blocking advisory check comparing source text against base_language.

    Returns an advisory warning string if source language/script differs from base_language,
    or None if they match or detection is uncertain.
    """
    if not (text or topic) or not base_language:
        return None

    warning, _ = check_source_canonical_mismatch_warning(
        topic=topic,
        source_content=text,
        canonical_language=base_language,
    )
    return warning


def verify_output_language(
    text: Optional[str],
    expected_locale: str,
) -> Tuple[bool, Optional[str]]:
    """
    Verify that generated script narration/text genuinely matches expected_locale.

    Allows embedded technical terms, product names, and proper nouns in Latin script
    while catching cases where narration was generated in the wrong language (e.g.,
    English narration labeled as 'ar-SA').
    """
    if not text or not text.strip():
        return True, None

    counts, total = _count_scripts(text)
    if total < 15:
        return True, None

    expected_lang = expected_locale.strip().lower().replace("_", "-").split("-")[0]
    expected_name = LANGUAGE_NAMES.get(expected_lang, expected_locale)
    ratios = {k: (v / total) for k, v in counts.items()}

    # 1. Expected Arabic-script languages (Arabic, Urdu)
    if expected_lang in ("ar", "ur", "fa", "he"):
        # Allow up to ~65% Latin technical terms in extreme cases, but require at least 30% Arabic script
        if ratios["arabic"] < 0.30:
            return False, (
                f"Expected narration in {expected_name} ('{expected_locale}', Arabic script), "
                f"but output contains only {ratios['arabic']:.0%} Arabic-script characters "
                f"(Latin: {ratios['latin']:.0%})."
            )
        # Disambiguate Arabic vs Urdu when text is substantial
        if total >= 40 and expected_lang in ("ar", "ur"):
            _, det_lang, conf, uncertain = _disambiguate_arabic_script(text, ratios["arabic"])
            if not uncertain and det_lang and det_lang != expected_lang and conf >= 0.78:
                det_name = LANGUAGE_NAMES.get(det_lang, det_lang)
                return False, (
                    f"Expected narration in {expected_name} ('{expected_locale}'), "
                    f"but output language was detected as {det_name}."
                )
        return True, None

    # 2. Expected Bengali-script language
    if expected_lang == "bn":
        if ratios["bengali"] < 0.30:
            return False, (
                f"Expected narration in Bengali ('{expected_locale}'), "
                f"but output contains only {ratios['bengali']:.0%} Bengali-script characters."
            )
        return True, None

    # 3. Expected Latin-script languages (English, French, German, Spanish, etc.)
    if expected_lang in ("en", "fr", "de", "es", "it", "pt", "nl", "id", "tr", "vi"):
        if (ratios["arabic"] + ratios["bengali"]) > 0.40:
            return False, (
                f"Expected narration in {expected_name} ('{expected_locale}', Latin script), "
                f"but output is predominantly non-Latin script."
            )
        # Disambiguate between English, French, and German when text is substantial
        if expected_lang in ("en", "fr", "de") and total >= 35:
            _, det_lang, conf, uncertain = _disambiguate_latin_script(text, ratios["latin"])
            if not uncertain and det_lang and det_lang != expected_lang and conf >= 0.72:
                det_name = LANGUAGE_NAMES.get(det_lang, det_lang)
                return False, (
                    f"Expected narration in {expected_name} ('{expected_locale}'), "
                    f"but output appears to be written in {det_name}."
                )
        return True, None

    return True, None
