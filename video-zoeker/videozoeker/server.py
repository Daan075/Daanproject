"""De webserver: een kleine JSON-API plus de webpagina."""

from __future__ import annotations

import logging
import re
import shutil
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, download, search, storage
from .claude import ClaudeError
from .jobs import Worker

log = logging.getLogger(__name__)
worker = Worker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    worker.start()
    yield


app = FastAPI(title="Video Zoeker", lifespan=lifespan)


class AddVideo(BaseModel):
    url: str


class SearchQuery(BaseModel):
    query: str


def _meta_or_404(video_id: str) -> dict:
    try:
        meta = storage.load_meta(video_id)
    except ValueError:
        meta = None
    if not meta or meta.get("status") == "deleting":
        raise HTTPException(404, "Video niet gevonden")
    return meta


def _public(meta: dict) -> dict:
    vdir = storage.video_dir(meta["id"])
    out = {**meta, "has_file": download.find_video(vdir) is not None}
    if not out.get("thumbnail"):
        # Geen plaatje van het platform: neem een frame uit de video zelf.
        for name in ("f_000002.jpg", "f_000001.jpg"):
            if (vdir / storage.FRAMES_DIR / name).exists():
                out["thumbnail"] = f"/api/videos/{meta['id']}/frames/{name}"
                break
    return out


@app.get("/api/status")
def status() -> dict:
    return {
        "has_api_key": config.has_api_key(),
        "ffmpeg": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
        "vision_model": config.VISION_MODEL,
        "search_model": config.SEARCH_MODEL,
        "whisper_model": config.WHISPER_MODEL,
        "vision": config.VISION,
        "audio_events": config.AUDIO_EVENTS,
    }


@app.get("/api/videos")
def list_videos() -> list[dict]:
    return [_public(m) for m in storage.list_videos()]


@app.post("/api/videos")
def add_video(body: AddVideo) -> dict:
    url = body.url.strip()
    if not re.match(r"^https?://", url):
        raise HTTPException(400, "Plak een volledige link, beginnend met https://")
    try:
        info = download.probe(url)
    except download.DownloadError as e:
        raise HTTPException(400, str(e)) from e
    details = download.describe(info)
    video_id = storage.slug(f"{details['platform']}-{details['platform_id']}")
    existing = storage.load_meta(video_id)
    if existing and existing.get("status") != "deleting":
        if existing.get("status") == "error":
            worker.enqueue(video_id)
        return _public(storage.load_meta(video_id))
    storage.create_video_dir(video_id)
    storage.save_meta(video_id, {
        "id": video_id,
        "url": details["webpage_url"] or url,
        **details,
        "status": "queued",
        "progress": {},
        "notes": {},
        "created_at": time.time(),
    })
    worker.enqueue(video_id)
    return _public(storage.load_meta(video_id))


@app.get("/api/videos/{video_id}")
def get_video(video_id: str) -> dict:
    return _public(_meta_or_404(video_id))


@app.delete("/api/videos/{video_id}")
def delete_video(video_id: str) -> dict:
    _meta_or_404(video_id)
    worker.delete(video_id)
    return {"ok": True}


@app.post("/api/videos/{video_id}/retry")
def retry(video_id: str) -> dict:
    meta = _meta_or_404(video_id)
    if meta.get("status") in {"queued", "downloading", "extracting", "analyzing"} and worker.current == video_id:
        return _public(meta)
    worker.enqueue(video_id)
    return _public(storage.load_meta(video_id))


@app.get("/api/videos/{video_id}/timeline")
def timeline(video_id: str) -> dict:
    _meta_or_404(video_id)
    vdir = storage.video_dir(video_id)
    frames = storage.read_json(vdir / storage.FRAMES, {})
    return {
        "transcript": storage.read_json(vdir / storage.TRANSCRIPT, {}).get("segments", []),
        "audio_events": storage.read_json(vdir / storage.AUDIO_EVENTS, {}).get("events", []),
        "frames": [f for f in frames.get("frames", []) if f.get("description")],
        "frame_interval": frames.get("interval"),
    }


@app.get("/api/videos/{video_id}/searches")
def searches(video_id: str) -> list[dict]:
    _meta_or_404(video_id)
    return storage.read_json(storage.video_dir(video_id) / storage.SEARCHES, [])


@app.post("/api/videos/{video_id}/search")
def do_search(video_id: str, body: SearchQuery) -> dict:
    _meta_or_404(video_id)
    query = body.query.strip()
    if not query:
        raise HTTPException(400, "Typ eerst een zoekvraag.")
    try:
        return search.search(video_id, query[:2000])
    except ClaudeError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/videos/{video_id}/frames/{name}")
def frame(video_id: str, name: str) -> FileResponse:
    _meta_or_404(video_id)
    if not re.fullmatch(r"f_\d{6}\.jpg", name):
        raise HTTPException(404)
    path = storage.video_dir(video_id) / storage.FRAMES_DIR / name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@app.get("/api/videos/{video_id}/file")
def video_file(video_id: str) -> FileResponse:
    _meta_or_404(video_id)
    path = download.find_video(storage.video_dir(video_id))
    if path is None:
        raise HTTPException(404, "Het videobestand is niet (meer) aanwezig.")
    media_type = {".mp4": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska"}.get(path.suffix)
    return FileResponse(path, media_type=media_type)


app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")
