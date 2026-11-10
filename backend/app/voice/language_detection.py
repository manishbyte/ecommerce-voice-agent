"""Rule-based language preference detection (English + native-script names).

Deterministic on purpose: language selection is the first turn of every call and must be
reliable even when the LLM is unavailable. Pure Python.
"""
from __future__ import annotations

import re

from app.voice.language_config import LANGUAGES

_ALIASES: dict[str, list[str]] = {
    "english": ["english", "angrezi", "angreji", "अंग्रेज़ी", "अंग्रेजी", "इंग्लिश", "इंग्लीश", "en-in", "en"],
    "hindi": ["hindi", "हिंदी", "हिन्दी", "hi-in", "hi"],
    "marathi": ["marathi", "मराठी", "मराठीत", "mr-in", "mr"],
    "hinglish": ["hinglish", "हिंग्लिश", "hindi english", "mix of hindi and english"],
    "tamil": ["tamil", "தமிழ்", "தமிழில்", "ta-in", "ta"],
    "telugu": ["telugu", "తెలుగు", "తెలుగులో", "te-in", "te"],
    "kannada": ["kannada", "ಕನ್ನಡ", "ಕನ್ನಡದಲ್ಲಿ", "kn-in", "kn"],
    "malayalam": ["malayalam", "മലയാളം", "മലയാളത്തിൽ", "ml-in", "ml"],
    "bengali": ["bengali", "bangla", "বাংলা", "বাংলায়", "bn-in", "bn"],
    "gujarati": ["gujarati", "ગુજરાતી", "ગુજરાતીમાં", "gu-in", "gu"],
    "punjabi": ["punjabi", "panjabi", "ਪੰਜਾਬੀ", "ਪੰਜਾਬੀ ਵਿੱਚ", "pa-in", "pa"],
}
assert set(_ALIASES) == set(LANGUAGES)

_CHANGE_CUE = re.compile(
    r"(switch|change|speak|talk|continue|conversation|language|please|in\s+\w+\s*$|बदल|बात|बोल|बोला|में|मध्ये|"
    r"மாற்ற|మార్చ|ಬದಲ|മാറ്റ|বদল|બદલ|ਬਦਲ)", re.I)


def _contains(text: str, alias: str) -> bool:
    if alias.isascii():
        return re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", text) is not None
    return alias in text


def detect_languages(text: str) -> list[str]:
    t = (text or "").lower()
    found: list[str] = []
    for key, aliases in _ALIASES.items():
        # 1-2 letter codes are only trusted when the whole utterance is that code
        for a in aliases:
            if len(a) <= 2 and t.strip() != a:
                continue
            if _contains(t, a):
                found.append(key)
                break
    return found


def detect_language_preference(text: str) -> str | None:
    """Return a language key if the utterance clearly names exactly one language (or Hinglish)."""
    found = detect_languages(text)
    if not found:
        return None
    if "hinglish" in found:
        return "hinglish"
    if set(found) == {"english", "hindi"}:
        return "hinglish"          # "Hindi and English" == code-mixed preference
    if len(found) == 1:
        return found[0]
    return None                    # ambiguous (e.g. "Tamil or Telugu") -> re-ask


def detect_language_change_request(text: str, current: str | None) -> str | None:
    """Detect an explicit mid-call request to switch language."""
    target = detect_language_preference(text)
    if target is None or target == current:
        return None
    if not _CHANGE_CUE.search((text or "").lower()):
        return None
    return target
