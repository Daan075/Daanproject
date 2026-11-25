"""Instellingen, te overschrijven via omgevingsvariabelen of een .env-bestand."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent.parent
load_dotenv(APP_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "ja", "on"}


DATA_DIR = Path(os.environ.get("DATA_DIR", APP_DIR / "data")).resolve()
WEB_DIR = APP_DIR / "web"

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = _int("PORT", 8765)

# --- Downloaden -----------------------------------------------------------
# Lage resolutie is genoeg om het beeld te begrijpen en scheelt veel downloadtijd.
VIDEO_MAX_HEIGHT = _int("VIDEO_MAX_HEIGHT", 480)
# Video- en audiobestand na de analyse weggooien (frames en resultaten blijven bewaard).
# Voor YouTube/Twitch speelt de app de video toch af via de officiële speler.
KEEP_MEDIA = _bool("KEEP_MEDIA", False)
# Cookies uit je browser gebruiken (bv. "chrome", "firefox", "edge"): nodig voor Twitch-VOD's
# die alleen voor abonnees zijn, of als YouTube vraagt te bevestigen dat je geen bot bent.
COOKIES_FROM_BROWSER = os.environ.get("COOKIES_FROM_BROWSER", "").strip()

# --- Transcriptie (spraak naar tekst, lokaal met faster-whisper) ---------
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "auto")  # auto | cpu | cuda
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE") or None  # bv. "nl"; leeg = automatisch
# YouTube-ondertitels gebruiken als die er zijn (veel sneller dan zelf transcriberen).
USE_YOUTUBE_SUBTITLES = _bool("USE_YOUTUBE_SUBTITLES", True)

# --- Geluidsherkenning (lachen, schreeuwen, applaus, ...) ----------------
AUDIO_EVENTS = _bool("AUDIO_EVENTS", True)
AUDIO_MODEL = os.environ.get("AUDIO_MODEL", "MIT/ast-finetuned-audioset-10-10-0.4593")
AUDIO_WINDOW_SECONDS = _float("AUDIO_WINDOW_SECONDS", 10.0)
AUDIO_HOP_SECONDS = _float("AUDIO_HOP_SECONDS", 5.0)
AUDIO_THRESHOLD = _float("AUDIO_THRESHOLD", 0.2)
LAUGH_THRESHOLD = _float("LAUGH_THRESHOLD", 0.12)

# --- Beeldanalyse met Claude ----------------------------------------------
VISION = _bool("VISION", True)
# 0 = automatisch: elke 10 s, maar nooit meer dan MAX_FRAMES frames voor de hele video.
FRAME_INTERVAL = _float("FRAME_INTERVAL", 0)
MAX_FRAMES = _int("MAX_FRAMES", 900)
FRAME_WIDTH = _int("FRAME_WIDTH", 640)
FRAMES_PER_REQUEST = _int("FRAMES_PER_REQUEST", 12)
VISION_WORKERS = _int("VISION_WORKERS", 4)

# --- Claude-modellen ------------------------------------------------------
VISION_MODEL = os.environ.get("VISION_MODEL", "claude-opus-5-5")
VISION_EFFORT = os.environ.get("VISION_EFFORT", "low")
SEARCH_MODEL = os.environ.get("SEARCH_MODEL", "claude-opus-5-5")
SEARCH_EFFORT = os.environ.get("SEARCH_EFFORT", "medium")
# Grootte (geschat in tokens) waarboven de tijdlijn in stukken wordt doorzocht.
SEARCH_CHUNK_TOKENS = _int("SEARCH_CHUNK_TOKENS", 700_000)


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
