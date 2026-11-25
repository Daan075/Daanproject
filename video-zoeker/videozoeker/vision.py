"""Beelden uit de video laten beschrijven door Claude, in batches en parallel."""

from __future__ import annotations

import base64
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from . import claude, config
from .timefmt import hms

log = logging.getLogger(__name__)

SYSTEM = """Je helpt een video doorzoekbaar te maken. Je krijgt een reeks beelden (frames) uit één video, \
elk met een nummer en tijdstip. Beschrijf per frame feitelijk en beknopt (hooguit ~30 woorden, in het Nederlands) \
wat er te zien is: de scène of locatie, wat de maker/persoon doet, welk spel of programma er in beeld is, menu's, \
en opvallende gebeurtenissen zoals het begin of einde van een missie/level/ronde, een laadscherm, cutscene, \
doodgaan/game over, overwinning, scorebord of een opvallende reactie. Is er een facecam te zien, noem dan de \
gezichtsuitdrukking (bijv. lacht, schrikt, geconcentreerd).
Neem belangrijke tekst in beeld letterlijk over in on_screen_text (missie- of questnamen, doelen, levelnamen, \
hoofdstuktitels, scores, ondertitels, overlays) - hooguit ~25 woorden, laat chatberichten weg, lege string als er \
niets belangrijks staat. Verzin niets wat niet zichtbaar is."""

SCHEMA = {
    "type": "object",
    "properties": {
        "frames": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "frame": {"type": "integer"},
                    "description": {"type": "string"},
                    "on_screen_text": {"type": "string"},
                },
                "required": ["frame", "description", "on_screen_text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["frames"],
    "additionalProperties": False,
}


def _signature(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("L").resize((64, 36)), dtype=np.float32)


def mark_duplicates(frames: list[dict], frames_dir: Path, threshold: float = 3.0) -> None:
    """Frames die vrijwel gelijk zijn aan het vorige verschillende frame hoeven niet naar Claude."""
    prev_sig = None
    prev_t = None
    for f in frames:
        if "description" in f or "same_as" in f:
            if "description" in f:
                prev_sig, prev_t = _signature(frames_dir / f["file"]), f["t"]
            continue
        sig = _signature(frames_dir / f["file"])
        if prev_sig is not None and float(np.abs(sig - prev_sig).mean()) < threshold:
            f["same_as"] = prev_t
        else:
            prev_sig, prev_t = sig, f["t"]


def describe_frames(video_id: str, frames: list[dict], frames_dir: Path, title: str,
                    save: Callable[[list[dict]], None], on_progress: Callable[[float], None],
                    should_stop: Callable[[], bool]) -> None:
    """Vul 'description' en 'text' in voor elk frame dat nog niet beschreven is."""
    mark_duplicates(frames, frames_dir)
    save(frames)
    todo = [f for f in frames if "description" not in f and "same_as" not in f]
    total = len(todo)
    if not total:
        on_progress(1.0)
        return

    size = max(1, config.FRAMES_PER_REQUEST)
    batches = [todo[i:i + size] for i in range(0, total, size)]
    lock = threading.Lock()
    abort = threading.Event()
    done = 0
    errors: list[Exception] = []

    def run(batch: list[dict]) -> None:
        if should_stop() or abort.is_set():
            return
        content: list[dict] = [{"type": "text", "text": f"Video: {title}"}]
        for i, f in enumerate(batch, 1):
            data = base64.standard_b64encode((frames_dir / f["file"]).read_bytes()).decode()
            content.append({"type": "text", "text": f"Frame {i} - {hms(f['t'])}"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
        content.append({"type": "text", "text": f"Beschrijf alle {len(batch)} frames."})
        result = claude.ask_json(model=config.VISION_MODEL, system=SYSTEM, content=content, schema=SCHEMA,
                                 effort=config.VISION_EFFORT, max_tokens=16000, usage_for=video_id)
        by_num = {r["frame"]: r for r in result.get("frames", [])}
        with lock:
            for i, f in enumerate(batch, 1):
                r = by_num.get(i)
                if r:
                    f["description"] = r["description"].strip()
                    f["text"] = r["on_screen_text"].strip()
            save(frames)

    with ThreadPoolExecutor(max_workers=max(1, config.VISION_WORKERS)) as pool:
        futures = [pool.submit(run, b) for b in batches]
        for fut in as_completed(futures):
            try:
                fut.result()
            except claude.ClaudeError as e:
                errors.append(e)
                log.warning("Batch frames mislukt: %s", e)
                if e.fatal:
                    abort.set()
            with lock:
                done += 1
                on_progress(done / len(batches))

    fatal = next((e for e in errors if e.fatal), None)
    if fatal or (errors and len(errors) == len(batches)):
        raise fatal or errors[0]
    if errors:
        log.warning("%d van de %d batches mislukt; opnieuw proberen vult de gaten aan.", len(errors), len(batches))
