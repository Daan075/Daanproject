"""Opslag per video: één map met meta.json en de resultaten van elke stap."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from . import config

_lock = threading.RLock()

# Bestandsnamen binnen een videomap
META = "meta.json"
TRANSCRIPT = "transcript.json"
AUDIO_EVENTS = "audio_events.json"
FRAMES = "frames.json"
SEARCHES = "searches.json"
FRAMES_DIR = "frames"
AUDIO_RAW = "audio.s16"  # 16 kHz mono, 16-bit PCM zonder header


def slug(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-")
    return text[:80] or "video"


def video_dir(video_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", video_id):
        raise ValueError("ongeldig video-id")
    return config.DATA_DIR / video_id


def write_json(path: Path, data: Any) -> None:
    # Bewust geen mkdir: een verwijderde video mag niet "herrijzen" door een late schrijfactie.
    tmp = path.with_suffix(path.suffix + f".{threading.get_ident()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    # Op Windows mislukt vervangen even als iemand het bestand op dat moment leest: kort opnieuw proberen.
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def load_meta(video_id: str) -> dict | None:
    with _lock:
        return read_json(video_dir(video_id) / META)


def create_video_dir(video_id: str) -> Path:
    path = video_dir(video_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_meta(video_id: str, meta: dict) -> None:
    with _lock:
        if not video_dir(video_id).exists():
            return
        meta["updated_at"] = time.time()
        write_json(video_dir(video_id) / META, meta)


def update_meta(video_id: str, **changes: Any) -> dict:
    with _lock:
        meta = load_meta(video_id) or {"id": video_id}
        meta.update(changes)
        save_meta(video_id, meta)
        return meta


def set_progress(video_id: str, part: str, value: float, note: str | None = None) -> None:
    """Voortgang (0..1) van een onderdeel: download, transcript, audio, vision."""
    with _lock:
        meta = load_meta(video_id) or {"id": video_id}
        progress = meta.setdefault("progress", {})
        progress[part] = round(max(0.0, min(1.0, value)), 4)
        if note is not None:
            meta.setdefault("notes", {})[part] = note
        save_meta(video_id, meta)


def list_videos() -> list[dict]:
    if not config.DATA_DIR.exists():
        return []
    videos = []
    for child in config.DATA_DIR.iterdir():
        meta = read_json(child / META) if child.is_dir() else None
        if meta and meta.get("status") != "deleting":
            videos.append(meta)
    videos.sort(key=lambda m: m.get("created_at", 0), reverse=True)
    return videos


def delete_video(video_id: str) -> None:
    with _lock:
        shutil.rmtree(video_dir(video_id), ignore_errors=True)
