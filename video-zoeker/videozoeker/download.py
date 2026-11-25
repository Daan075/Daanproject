"""Video's en ondertitels ophalen met yt-dlp (YouTube, Twitch-VOD's en nog veel meer sites)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import yt_dlp

from . import config


class DownloadError(Exception):
    pass


def _base_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "noprogress": True,
    }
    if config.COOKIES_FROM_BROWSER:
        opts["cookiesfrombrowser"] = (config.COOKIES_FROM_BROWSER,)
    return opts


def probe(url: str) -> dict:
    """Haal informatie over de video op zonder te downloaden."""
    try:
        with yt_dlp.YoutubeDL({**_base_opts(), "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(_clean(str(e))) from e
    if info is None:
        raise DownloadError("Kon geen video vinden op deze link.")
    if info.get("_type") == "playlist":
        raise DownloadError("Dit is een afspeellijst. Plak de link van één video.")
    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
        raise DownloadError("Deze stream is nog live (of nog niet begonnen). Probeer het opnieuw als hij afgelopen is.")
    return info


def describe(info: dict) -> dict:
    """De velden die de app bewaart."""
    extractor = (info.get("extractor_key") or info.get("extractor") or "").lower()
    if extractor.startswith("youtube"):
        platform = "youtube"
    elif extractor.startswith("twitch"):
        platform = "twitch"
    else:
        platform = "other"
    return {
        "platform": platform,
        "platform_id": str(info.get("id") or ""),
        "title": info.get("title") or info.get("fulltitle") or "Onbekende video",
        "uploader": info.get("uploader") or info.get("channel") or "",
        "duration": float(info.get("duration") or 0),
        "thumbnail": info.get("thumbnail") or "",
        "webpage_url": info.get("webpage_url") or info.get("original_url") or "",
        "language": info.get("language") or None,
    }


def download_video(url: str, dest: Path, on_progress: Callable[[float], None]) -> Path:
    """Download de video in lage resolutie naar dest/video.<ext>."""
    h = config.VIDEO_MAX_HEIGHT
    # YouTube: losse video- en audiostream samenvoegen; Twitch: gecombineerde stream.
    fmt = f"bv[height<={h}]+ba/b[height<={h}]/w"

    def hook(d: dict) -> None:
        if d.get("status") != "downloading":
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if total:
            on_progress(d.get("downloaded_bytes", 0) / total)
        elif d.get("fragment_count"):
            on_progress((d.get("fragment_index") or 0) / d["fragment_count"])

    opts = {
        **_base_opts(),
        "format": fmt,
        "outtmpl": str(dest / "video.%(ext)s"),
        # H.264 + AAC in mp4 speelt in elke browser af; anders mkv als het niet anders kan.
        "format_sort": ["vcodec:h264", "acodec:aac"],
        "merge_output_format": "mp4/mkv",
        "concurrent_fragment_downloads": 4,
        "progress_hooks": [hook],
        "retries": 10,
        "fragment_retries": 10,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(_clean(str(e))) from e
    path = find_video(dest)
    if path is None:
        raise DownloadError("Download leek te lukken, maar het videobestand is niet gevonden.")
    return path


def find_video(dest: Path) -> Path | None:
    for p in sorted(dest.glob("video.*")):
        if p.suffix not in {".part", ".ytdl", ".json3", ".tmp"} and ".f" not in p.stem[5:]:
            return p
    return None


def pick_subtitle_track(info: dict) -> tuple[str, bool] | None:
    """Kies een ondertitelspoor in de originele taal: (taalcode, is_automatisch)."""
    lang = info.get("language")
    manual = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat"}
    auto = info.get("automatic_captions") or {}

    if lang:
        for key in manual:
            if key == lang or key.split("-")[0] == lang:
                return key, False
        for key in (f"{lang}-orig", lang):
            if key in auto:
                return key, True
    else:
        orig = [k for k in auto if k.endswith("-orig")]
        if orig:
            return orig[0], True
        if len(manual) == 1:
            return next(iter(manual)), False
    return None


def download_subtitles(url: str, info: dict, dest: Path) -> tuple[Path, str] | None:
    """Download de ondertitels (json3-formaat). Geeft (pad, taal) of None."""
    track = pick_subtitle_track(info)
    if not track:
        return None
    key, is_auto = track
    opts = {
        **_base_opts(),
        "skip_download": True,
        "writesubtitles": not is_auto,
        "writeautomaticsub": is_auto,
        "subtitleslangs": [key],
        "subtitlesformat": "json3",
        "outtmpl": str(dest / "subs.%(ext)s"),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError:
        return None
    files = sorted(dest.glob("subs*.json3"))
    if not files:
        return None
    return files[0], key.removesuffix("-orig")


def _clean(message: str) -> str:
    message = message.replace("ERROR: ", "").strip()
    low = message.lower()
    if "sign in" in low or "login" in low or "subscriber" in low or "not a bot" in low:
        message += (" — Tip: zet COOKIES_FROM_BROWSER=chrome (of firefox/edge) in .env, zodat de app je "
                    "ingelogde browsersessie gebruikt.")
    elif "javascript" in low or "js runtime" in low or "n challenge" in low or "signature" in low:
        message += " — Tip: installeer Deno (zie README) en werk yt-dlp bij met: pip install -U \"yt-dlp[default]\""
    return message
