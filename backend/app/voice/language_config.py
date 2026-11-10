"""Supported languages and their Gnani STT locale / TTS voice mapping.

Pure Python (no SDK import) so it is usable and testable without the Gnani package.
Voices and locales follow the Gnani Python SDK docs for timbre-v2.5.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LanguageConfig:
    key: str
    name: str
    native_name: str
    stt_locale: str          # one locale per realtime STT session
    tts_voice: str
    tts_language: str        # value for `language=` on timbre-v2.5 ("auto" for Hinglish)
    script: str              # expected script of replies: latin | devanagari | ...
    confirmation: str        # static "language selected" reply, in that language


LANGUAGES: dict[str, LanguageConfig] = {c.key: c for c in [
    LanguageConfig("english", "English", "English", "en-IN", "Kaveri", "en-IN", "latin",
                   "Sure, I'll continue in English. How can I help you today?"),
    LanguageConfig("hindi", "Hindi", "हिंदी", "hi-IN", "Nalini", "hi-IN", "devanagari",
                   "ठीक है, अब हम हिंदी में बात करेंगे। मैं आपकी क्या मदद कर सकती हूँ?"),
    LanguageConfig("marathi", "Marathi", "मराठी", "mr-IN", "Ishaan", "mr-IN", "devanagari",
                   "ठीक आहे, आता आपण मराठीत बोलूया. मी तुमची काय मदत करू शकते?"),
    # Hinglish: STT uses en-IN (documented to accept mixed English-Hindi audio, Latin output);
    # TTS uses the dedicated Hinglish voice with language="auto".
    LanguageConfig("hinglish", "Hinglish", "Hinglish", "en-IN", "Poorvi", "auto", "latin",
                   "Theek hai, ab hum Hinglish mein baat karenge. Main aapki kya madad kar sakti hoon?"),
    LanguageConfig("tamil", "Tamil", "தமிழ்", "ta-IN", "Trisha", "ta-IN", "tamil",
                   "சரி, நாம் தமிழில் தொடர்வோம். இன்று நான் உங்களுக்கு எப்படி உதவலாம்?"),
    LanguageConfig("telugu", "Telugu", "తెలుగు", "te-IN", "Suhana", "te-IN", "telugu",
                   "సరే, మనం తెలుగులో కొనసాగిద్దాం. ఈ రోజు నేను మీకు ఎలా సహాయం చేయగలను?"),
    LanguageConfig("kannada", "Kannada", "ಕನ್ನಡ", "kn-IN", "Saanvi", "kn-IN", "kannada",
                   "ಸರಿ, ನಾವು ಕನ್ನಡದಲ್ಲಿ ಮುಂದುವರಿಯೋಣ. ಇಂದು ನಾನು ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಬಹುದು?"),
    LanguageConfig("malayalam", "Malayalam", "മലയാളം", "ml-IN", "Reshma", "ml-IN", "malayalam",
                   "ശരി, നമുക്ക് മലയാളത്തിൽ തുടരാം. ഇന്ന് ഞാൻ നിങ്ങളെ എങ്ങനെ സഹായിക്കണം?"),
    LanguageConfig("bengali", "Bengali", "বাংলা", "bn-IN", "Kirra", "bn-IN", "bengali",
                   "ঠিক আছে, আমরা বাংলায় কথা বলব। আজ আমি আপনাকে কীভাবে সাহায্য করতে পারি?"),
    LanguageConfig("gujarati", "Gujarati", "ગુજરાતી", "gu-IN", "Falak", "gu-IN", "gujarati",
                   "ઠીક છે, આપણે ગુજરાતીમાં વાત કરીશું. આજે હું તમારી કેવી રીતે મદદ કરી શકું?"),
    LanguageConfig("punjabi", "Punjabi", "ਪੰਜਾਬੀ", "pa-IN", "Mehuli", "pa-IN", "gurmukhi",
                   "ਠੀਕ ਹੈ, ਅਸੀਂ ਪੰਜਾਬੀ ਵਿੱਚ ਗੱਲ ਕਰਾਂਗੇ। ਅੱਜ ਮੈਂ ਤੁਹਾਡੀ ਕਿਵੇਂ ਮਦਦ ਕਰ ਸਕਦੀ ਹਾਂ?"),
]}

DEFAULT_LANGUAGE = "english"
GREETING = "Hello! Welcome to customer support. Which language would you prefer to speak in today?"
LANGUAGE_REPROMPT = ("Sorry, I couldn't tell which language you meant. You can choose English, Hindi, Marathi, "
                     "Hinglish, Tamil, Telugu, Kannada, Malayalam, Bengali, Gujarati or Punjabi.")

# Unicode ranges used for output language-consistency checks.
SCRIPT_RANGES: dict[str, tuple[int, int]] = {
    "devanagari": (0x0900, 0x097F), "bengali": (0x0980, 0x09FF), "gurmukhi": (0x0A00, 0x0A7F),
    "gujarati": (0x0A80, 0x0AFF), "tamil": (0x0B80, 0x0BFF), "telugu": (0x0C00, 0x0C7F),
    "kannada": (0x0C80, 0x0CFF), "malayalam": (0x0D00, 0x0D7F),
}

# Preferred-language codes used in the customers table -> language key
LOCALE_TO_KEY = {"en-IN": "english", "hi-IN": "hindi", "mr-IN": "marathi", "ta-IN": "tamil", "te-IN": "telugu",
                 "kn-IN": "kannada", "ml-IN": "malayalam", "bn-IN": "bengali", "gu-IN": "gujarati",
                 "pa-IN": "punjabi"}


def get_language(key: str | None) -> LanguageConfig | None:
    return LANGUAGES.get((key or "").lower())


def is_supported(key: str | None) -> bool:
    return (key or "").lower() in LANGUAGES


def supported_keys() -> list[str]:
    return list(LANGUAGES)


def validate_against_sdk() -> list[str]:
    """Warn (don't crash) if a configured voice/locale is unknown to the installed Gnani SDK."""
    problems: list[str] = []
    try:
        from gnani.stt import GnaniSTTStreamClient
        from gnani.tts import GnaniTTSClient

        voices = set(GnaniTTSClient.supported_voices("timbre-v2.5"))
        locales = set(GnaniSTTStreamClient.supported_languages())
    except Exception as exc:  # noqa: BLE001
        return [f"Gnani SDK not available for validation: {exc}"]
    for cfg in LANGUAGES.values():
        if cfg.tts_voice not in voices:
            problems.append(f"{cfg.key}: voice '{cfg.tts_voice}' not offered by SDK")
        if cfg.stt_locale not in locales:
            problems.append(f"{cfg.key}: STT locale '{cfg.stt_locale}' not offered by SDK")
    for p in problems:
        log.warning(p)
    return problems
