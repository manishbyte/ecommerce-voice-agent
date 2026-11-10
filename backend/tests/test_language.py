import pytest

from app.voice.language_config import GREETING, LANGUAGES, get_language
from app.voice.language_detection import detect_language_change_request, detect_language_preference

EXPECTED = {"english": ("en-IN", "Kaveri"), "hindi": ("hi-IN", "Nalini"), "marathi": ("mr-IN", "Ishaan"),
            "hinglish": ("en-IN", "Poorvi"), "tamil": ("ta-IN", "Trisha"), "telugu": ("te-IN", "Suhana"),
            "kannada": ("kn-IN", "Saanvi"), "malayalam": ("ml-IN", "Reshma"), "bengali": ("bn-IN", "Kirra"),
            "gujarati": ("gu-IN", "Falak"), "punjabi": ("pa-IN", "Mehuli")}


def test_language_table_matches_spec():
    assert set(LANGUAGES) == set(EXPECTED)
    for key, (loc, voice) in EXPECTED.items():
        assert (get_language(key).stt_locale, get_language(key).tts_voice) == (loc, voice)
    assert get_language("hinglish").tts_language == "auto"


def test_greeting_text():
    assert GREETING == "Hello! Welcome to customer support. Which language would you prefer to speak in today?"


@pytest.mark.parametrize("text,key", [("English please", "english"), ("हिंदी", "hindi"), ("I want to speak in Tamil", "tamil"),
                                      ("Hinglish", "hinglish"), ("hindi and english both", "hinglish"), ("మరాఠీ", None),
                                      ("తెలుగు", "telugu"), ("tamil or telugu", None), ("hello", None)])
def test_language_selection(text, key):
    assert detect_language_preference(text) == key


def test_explicit_language_change():
    assert detect_language_change_request("please switch to Hindi", "english") == "hindi"
    assert detect_language_change_request("switch to english", "english") is None
    assert detect_language_change_request("hindi", "english") is None      # needs a change cue
