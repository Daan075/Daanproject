"""Geluiden herkennen (lachen, schreeuwen, applaus, explosies, ...) met een AudioSet-model.

Het model (Audio Spectrogram Transformer) kent 527 geluidscategorieën. We laten
een venster van 10 s met stappen van 5 s over de audio lopen en bewaren elke
categorie die boven de drempel uitkomt. Spraak zelf slaan we over: daarvoor is
het transcript er al.
"""

from __future__ import annotations

import logging
import os
from typing import Callable

import numpy as np

from . import config

log = logging.getLogger(__name__)

LAUGH_LABELS = {"Laughter", "Baby laughter", "Giggle", "Snicker", "Belly laugh", "Chuckle, chortle"}

# Bijna altijd aanwezig of al gedekt door het transcript: niet opslaan.
IGNORE_LABELS = {
    "Speech", "Male speech, man speaking", "Female speech, woman speaking",
    "Child speech, kid speaking", "Conversation", "Narration, monologue",
    "Speech synthesizer", "Inside, small room", "Inside, large room or hall",
    "Inside, public space", "Silence", "Outside, urban or manmade",
    "Outside, rural or natural", "Echo", "Reverberation", "Noise", "Hubbub, speech noise, speech babble",
}

SAMPLE_RATE = 16_000
BATCH = 8


def _label_group(label: str) -> str | None:
    if label in LAUGH_LABELS:
        return "laughter"
    return None


def detect(audio_int16: np.ndarray, on_progress: Callable[[float], None]) -> list[dict]:
    import torch
    from transformers import ASTFeatureExtractor, ASTForAudioClassification

    torch.set_num_threads(max(1, os.cpu_count() or 1))
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("Geluidsmodel %s laden op %s", config.AUDIO_MODEL, device)
    extractor = ASTFeatureExtractor.from_pretrained(config.AUDIO_MODEL)
    model = ASTForAudioClassification.from_pretrained(config.AUDIO_MODEL).eval().to(device)
    id2label = model.config.id2label

    win = int(config.AUDIO_WINDOW_SECONDS * SAMPLE_RATE)
    hop = int(config.AUDIO_HOP_SECONDS * SAMPLE_RATE)
    n = len(audio_int16)
    if n == 0:
        return []
    starts = list(range(0, max(1, n - win + hop), hop))

    keep_idx = [i for i, name in id2label.items() if name not in IGNORE_LABELS]
    laugh_idx = {i for i, name in id2label.items() if name in LAUGH_LABELS}
    thresholds = np.array([config.LAUGH_THRESHOLD if i in laugh_idx else config.AUDIO_THRESHOLD
                           for i in keep_idx])

    hits: list[tuple[float, float, str, float]] = []
    for b in range(0, len(starts), BATCH):
        chunk_starts = starts[b:b + BATCH]
        clips = []
        for s in chunk_starts:
            clip = np.asarray(audio_int16[s:s + win], dtype=np.float32) / 32768.0
            if len(clip) < win:
                clip = np.pad(clip, (0, win - len(clip)))
            clips.append(clip)
        inputs = extractor(clips, sampling_rate=SAMPLE_RATE, return_tensors="pt")
        with torch.inference_mode():
            logits = model(**{k: v.to(device) for k, v in inputs.items()}).logits
        probs = torch.sigmoid(logits).cpu().numpy()[:, keep_idx]
        for row, s in zip(probs, chunk_starts):
            t0 = s / SAMPLE_RATE
            t1 = min(n, s + win) / SAMPLE_RATE
            for j in np.nonzero(row >= thresholds)[0]:
                hits.append((t0, t1, id2label[keep_idx[j]], float(row[j])))
        on_progress(min(1.0, (b + BATCH) / len(starts)))

    return merge_hits(hits)


def merge_hits(hits: list[tuple[float, float, str, float]]) -> list[dict]:
    """Opeenvolgende/overlappende vensters met hetzelfde geluid samenvoegen tot één moment."""
    by_label: dict[str, list[dict]] = {}
    for t0, t1, label, p in sorted(hits):
        events = by_label.setdefault(label, [])
        last = events[-1] if events else None
        if last and t0 <= last["end"] + 0.01:
            last["end"] = max(last["end"], t1)
            if p > last["score"]:
                last["score"] = p
                last["peak"] = (t0 + t1) / 2
        else:
            events.append({"start": t0, "end": t1, "label": label, "score": p, "peak": (t0 + t1) / 2})
    merged = [e for events in by_label.values() for e in events]
    for e in merged:
        e["start"] = round(e["start"], 1)
        e["end"] = round(e["end"], 1)
        e["peak"] = round(e["peak"], 1)
        e["score"] = round(e["score"], 3)
        e["group"] = _label_group(e["label"])
    merged.sort(key=lambda e: (e["start"], -e["score"]))
    return merged
