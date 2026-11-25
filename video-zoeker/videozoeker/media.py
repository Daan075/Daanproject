"""Audio en losse beelden uit de video halen met ffmpeg."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable

import numpy as np

from . import config

SAMPLE_RATE = 16_000


class MediaError(Exception):
    pass


def check_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise MediaError("ffmpeg is niet gevonden. Installeer ffmpeg en zorg dat het in je PATH staat (zie README).")


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise MediaError(f"ffprobe kon het bestand niet lezen: {out.stderr.strip()[:300]}")
    data = json.loads(out.stdout or "{}")
    types = {s.get("codec_type") for s in data.get("streams", [])}
    return {
        "duration": float(data.get("format", {}).get("duration") or 0),
        "has_audio": "audio" in types,
        "has_video": "video" in types,
    }


def frame_interval(duration: float) -> float:
    if config.FRAME_INTERVAL > 0:
        return config.FRAME_INTERVAL
    interval = 10.0
    if duration > 0 and config.MAX_FRAMES > 0:
        interval = max(interval, duration / config.MAX_FRAMES)
    return round(interval, 1)


def extract(video: Path, out_dir: Path, *, audio_path: Path | None, frames_dir: Path | None,
            interval: float, duration: float, on_progress: Callable[[float], None]) -> None:
    """Eén ffmpeg-run die zowel de audio (16 kHz mono PCM) als de frames wegschrijft."""
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-nostdin", "-progress", "pipe:1"]
    if frames_dir is not None and audio_path is None:
        # Alleen keyframes decoderen: tientallen keren sneller, nauwkeurig genoeg (±1-2 s).
        args += ["-skip_frame", "nokey"]
    args += ["-i", str(video)]
    if audio_path is not None:
        args += ["-map", "0:a:0", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", str(audio_path)]
    if frames_dir is not None:
        frames_dir.mkdir(parents=True, exist_ok=True)
        for old in frames_dir.glob("f_*.jpg"):
            old.unlink()
        vf = f"fps=1/{interval},scale={config.FRAME_WIDTH}:-2"
        args += ["-map", "0:v:0", "-vf", vf, "-q:v", "5", str(frames_dir / "f_%06d.jpg")]

    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        key, _, value = line.strip().partition("=")
        if key == "out_time_us" and duration > 0 and value.isdigit():
            on_progress(int(value) / 1e6 / duration)
    stderr = proc.stderr.read() if proc.stderr else ""
    if proc.wait() != 0:
        raise MediaError(f"ffmpeg gaf een fout: {stderr.strip()[:500]}")
    on_progress(1.0)


def extract_all(video: Path, out_dir: Path, *, audio_path: Path | None, frames_dir: Path | None,
                interval: float, duration: float, on_progress: Callable[[float], None]) -> None:
    """Audio en frames ophalen. Frames apart, zodat die met de snelle keyframe-modus kunnen."""
    jobs = [j for j in (("audio", audio_path), ("frames", frames_dir)) if j[1] is not None]
    for i, (kind, _) in enumerate(jobs):
        def sub(p: float, i=i) -> None:
            on_progress((i + p) / len(jobs))
        extract(video, out_dir,
                audio_path=audio_path if kind == "audio" else None,
                frames_dir=frames_dir if kind == "frames" else None,
                interval=interval, duration=duration, on_progress=sub)


def list_frames(frames_dir: Path, interval: float) -> list[dict]:
    """Frames met hun tijdstip: f_000001.jpg hoort bij 0 s, f_000002.jpg bij interval s, ..."""
    frames = []
    for p in sorted(frames_dir.glob("f_*.jpg")):
        n = int(p.stem[2:])
        frames.append({"file": p.name, "t": round((n - 1) * interval, 1)})
    return frames


def load_audio(path: Path) -> np.ndarray:
    """De ruwe PCM als int16-array (memory-mapped, dus zuinig met geheugen)."""
    if not path.exists() or path.stat().st_size < 2:
        return np.zeros(0, dtype=np.int16)
    return np.memmap(path, dtype=np.int16, mode="r")
