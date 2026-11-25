"""Zoeken in een geanalyseerde video: de tijdlijn gaat met de vraag naar Claude."""

from __future__ import annotations

import time
import uuid

from . import claude, config, storage
from .timefmt import hms, parse

INSTRUCTIONS = """You search inside a video for the user. You cannot watch the video yourself; instead you get an \
automatically generated, time-coded log of it. Line types:
- SAY: speech transcript from automatic speech recognition. It can contain recognition errors, especially in names.
- SOUND: non-speech sounds found by an audio classifier, with its confidence (e.g. Laughter, Giggle, Screaming, \
Applause, Cheering, Gunshot, Explosion, Music). The range covers the detection windows; the sound itself is \
somewhere inside it.
- SEE: a description of a sampled video frame, with on-screen text after "TEXT:". A frame is only listed when the \
picture changed noticeably, so the previous SEE line still applies until the next one.
Timestamps are h:mm:ss from the start of the video.

Find the moments that answer the user's question. Combine all evidence: for "when is he laughing", use SOUND \
laughter detections, laughing in the transcript ("haha", "lol", "(laughs)") and a laughing facecam in SEE lines; \
for "when does mission X start", look for the mission title on screen, the creator announcing it, briefing or \
loading screens, and the end of the previous mission.

Rules:
- If the question asks for all moments, list every match in chronological order; merge matches less than \
~15 seconds apart into one result.
- If the question asks for one moment, put the best match first, followed by plausible alternatives (if any).
- start is where the moment begins; when in doubt start a few seconds early rather than late. end may equal start.
- Use only times supported by the log. Never invent moments. If nothing matches, return no results and say so.
- Keep title short (max ~8 words) and explanation to one or two sentences that cite the evidence.
- Write answer, title and explanation in the language of the user's question."""

SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "h:mm:ss"},
                    "end": {"type": "string", "description": "h:mm:ss"},
                    "title": {"type": "string"},
                    "explanation": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["start", "end", "title", "explanation", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer", "results"],
    "additionalProperties": False,
}


def build_lines(video_id: str) -> list[tuple[float, str]]:
    vdir = storage.video_dir(video_id)
    lines: list[tuple[float, int, str]] = []
    for seg in storage.read_json(vdir / storage.TRANSCRIPT, {}).get("segments", []):
        lines.append((seg["start"], 0, f"[{hms(seg['start'])}] SAY: {seg['text']}"))
    for ev in storage.read_json(vdir / storage.AUDIO_EVENTS, {}).get("events", []):
        lines.append((ev["start"], 1,
                      f"[{hms(ev['start'])}-{hms(ev['end'])}] SOUND: {ev['label']} {round(ev['score'] * 100)}%"))
    for fr in storage.read_json(vdir / storage.FRAMES, {}).get("frames", []):
        if not fr.get("description"):
            continue
        text = f" | TEXT: {fr['text']}" if fr.get("text") else ""
        lines.append((fr["t"], 2, f"[{hms(fr['t'])}] SEE: {fr['description']}{text}"))
    lines.sort(key=lambda x: (x[0], x[1]))
    return [(t, line) for t, _, line in lines]


def header(meta: dict, frames: dict) -> str:
    parts = [f"VIDEO: {meta.get('title', '')}"]
    if meta.get("uploader"):
        parts.append(f"CREATOR/CHANNEL: {meta['uploader']}")
    parts.append(f"DURATION: {hms(meta.get('duration') or 0)}")
    if frames.get("interval"):
        parts.append(f"FRAME SAMPLING: one frame every {frames['interval']:g} seconds")
    return "\n".join(parts)


def _estimate_tokens(text: str) -> int:
    return len(text) // 3


def _chunks(lines: list[tuple[float, str]], limit_tokens: int) -> list[list[tuple[float, str]]]:
    chunks, cur, size = [], [], 0
    for item in lines:
        n = _estimate_tokens(item[1]) + 1
        if cur and size + n > limit_tokens:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(item)
        size += n
    if cur:
        chunks.append(cur)
    return chunks


def search(video_id: str, query: str) -> dict:
    meta = storage.load_meta(video_id)
    if not meta:
        raise claude.ClaudeError("Video niet gevonden.")
    vdir = storage.video_dir(video_id)
    frames = storage.read_json(vdir / storage.FRAMES, {})
    lines = build_lines(video_id)
    if not lines:
        raise claude.ClaudeError("Er is nog niets geanalyseerd voor deze video.")

    head = header(meta, frames)
    parts = _chunks(lines, config.SEARCH_CHUNK_TOKENS)
    answers, results = [], []
    started = time.time()
    for i, part in enumerate(parts, 1):
        log_text = head + "\n"
        if len(parts) > 1:
            log_text += (f"NOTE: the log is too long for one request; this is part {i} of {len(parts)}, "
                         f"covering {hms(part[0][0])} to {hms(part[-1][0])}.\n")
        log_text += "\nLOG:\n" + "\n".join(line for _, line in part)
        system = [
            {"type": "text", "text": INSTRUCTIONS},
            # De tijdlijn is per video steeds gelijk: cachen maakt volgende zoekvragen goedkoper en sneller.
            {"type": "text", "text": log_text, "cache_control": {"type": "ephemeral"}},
        ]
        out = claude.ask_json(model=config.SEARCH_MODEL, system=system, content=query, schema=SCHEMA,
                              effort=config.SEARCH_EFFORT, max_tokens=32000, stream=True, usage_for=video_id)
        if out.get("answer"):
            answers.append(out["answer"].strip())
        results.extend(out.get("results", []))

    duration = meta.get("duration") or 0
    clean = []
    for r in results:
        start = parse(r.get("start"))
        if start is None:
            continue
        end = parse(r.get("end"))
        if end is None or end < start:
            end = start
        if duration:
            start, end = min(start, duration), min(end, duration)
        clean.append({
            "start": round(start, 1),
            "end": round(end, 1),
            "title": r.get("title", ""),
            "explanation": r.get("explanation", ""),
            "confidence": r.get("confidence", "medium"),
            "frame": nearest_frame(frames, start),
        })
    if len(parts) > 1:
        clean.sort(key=lambda r: r["start"])

    record = {
        "id": uuid.uuid4().hex[:12],
        "query": query,
        "answer": "\n\n".join(answers),
        "results": clean,
        "created_at": time.time(),
        "seconds": round(time.time() - started, 1),
    }
    with storage._lock:
        history = storage.read_json(vdir / storage.SEARCHES, [])
        history.insert(0, record)
        storage.write_json(vdir / storage.SEARCHES, history[:200])
    return record


def nearest_frame(frames: dict, t: float) -> str | None:
    """Bestandsnaam van het frame dat het dichtst bij (en liefst net na) tijdstip t ligt."""
    best, best_d = None, None
    for f in frames.get("frames", []):
        d = abs(f["t"] - (t + 2))
        if best_d is None or d < best_d:
            best, best_d = f["file"], d
    return best
