"""Spraak naar tekst: YouTube-ondertitels als die er zijn, anders lokaal met faster-whisper."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

import numpy as np

from . import config

log = logging.getLogger(__name__)


def parse_json3(path: Path, max_len: float = 12.0) -> list[dict]:
    """YouTube json3-ondertitels omzetten naar segmenten van hooguit ~max_len seconden."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    lines = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs or "tStartMs" not in ev:
            continue
        text = "".join(s.get("utf8", "") for s in segs).replace("\n", " ").strip()
        if not text:
            continue
        start = ev["tStartMs"] / 1000
        end = start + ev.get("dDurationMs", 0) / 1000
        lines.append((start, end, text))

    segments: list[dict] = []
    for start, end, text in lines:
        cur = segments[-1] if segments else None
        if cur and start - cur["start"] < max_len and start - cur["end"] < 2.0:
            cur["text"] += " " + text
            cur["end"] = max(cur["end"], end)
        else:
            segments.append({"start": round(start, 2), "end": round(end, 2), "text": text})
    for s in segments:
        s["end"] = round(s["end"], 2)
    return segments


def _load_whisper(device: str):
    from faster_whisper import WhisperModel

    if device == "auto":
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    log.info("Whisper-model %s laden op %s (%s)", config.WHISPER_MODEL, device, compute_type)
    return WhisperModel(config.WHISPER_MODEL, device=device, compute_type=compute_type), device


def whisper(audio_int16: np.ndarray, duration: float,
            on_progress: Callable[[float], None]) -> tuple[list[dict], str | None]:
    """Transcribeer de audio. Valt terug op de CPU als de GPU niet werkt."""
    audio = np.asarray(audio_int16, dtype=np.float32) / 32768.0
    if audio.size == 0:
        return [], None
    try:
        return _whisper_run(audio, duration, on_progress, config.WHISPER_DEVICE)
    except Exception as e:
        if config.WHISPER_DEVICE == "cpu":
            raise
        log.warning("Transcriptie op GPU mislukt (%s), opnieuw op de CPU", e)
        on_progress(0.0)
        return _whisper_run(audio, duration, on_progress, "cpu")


def _whisper_run(audio: np.ndarray, duration: float, on_progress, device: str):
    model, device = _load_whisper(device)
    opts = dict(language=config.WHISPER_LANGUAGE, vad_filter=True, beam_size=5,
                condition_on_previous_text=False)
    try:
        from faster_whisper import BatchedInferencePipeline
        pipeline = BatchedInferencePipeline(model=model)
        segments, info = pipeline.transcribe(audio, batch_size=16 if device == "cuda" else 8, **opts)
    except ImportError:
        segments, info = model.transcribe(audio, **opts)

    total = duration or len(audio) / 16_000
    out = []
    for seg in segments:
        text = seg.text.strip()
        if text:
            out.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": text})
        if total:
            on_progress(seg.end / total)
    on_progress(1.0)
    return out, getattr(info, "language", None)
