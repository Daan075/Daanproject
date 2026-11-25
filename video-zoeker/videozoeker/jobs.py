"""De verwerkingswachtrij: download -> audio/frames -> transcript + geluiden + beeld."""

from __future__ import annotations

import logging
import queue
import threading
import time
import traceback

from . import config, download, media, storage, transcribe, vision
from .claude import ClaudeError

log = logging.getLogger(__name__)

ACTIVE = {"queued", "downloading", "extracting", "analyzing"}


class Cancelled(Exception):
    pass


class Worker:
    """Verwerkt video's één voor één in een achtergrondthread."""

    def __init__(self) -> None:
        self.queue: queue.Queue[str] = queue.Queue()
        self.cancelled: set[str] = set()
        self.to_delete: set[str] = set()
        self.current: str | None = None
        self._lock = threading.Lock()
        self.thread = threading.Thread(target=self._loop, name="video-worker", daemon=True)

    def start(self) -> None:
        # Video's die nog bezig waren toen de app stopte, gaan weer in de wachtrij.
        if config.DATA_DIR.exists():
            for child in config.DATA_DIR.iterdir():
                meta = storage.read_json(child / storage.META) if child.is_dir() else None
                if meta and meta.get("status") == "deleting":
                    storage.delete_video(child.name)
        for meta in reversed(storage.list_videos()):
            if meta.get("status") in ACTIVE:
                storage.update_meta(meta["id"], status="queued")
                self.queue.put(meta["id"])
        self.thread.start()

    def enqueue(self, video_id: str) -> None:
        self.cancelled.discard(video_id)
        storage.update_meta(video_id, status="queued", error=None)
        self.queue.put(video_id)

    def delete(self, video_id: str) -> None:
        """Stop eventuele verwerking en verwijder de video (zodra de worker ermee klaar is)."""
        with self._lock:
            self.cancelled.add(video_id)
            if self.current == video_id:
                storage.update_meta(video_id, status="deleting")
                self.to_delete.add(video_id)
                return
        storage.delete_video(video_id)

    def _loop(self) -> None:
        while True:
            video_id = self.queue.get()
            if video_id in self.cancelled or storage.load_meta(video_id) is None:
                continue
            with self._lock:
                self.current = video_id
            try:
                Pipeline(video_id, self).run()
            except Cancelled:
                log.info("Verwerking van %s gestopt", video_id)
            except Exception as e:  # noqa: BLE001 - elke fout moet zichtbaar worden in de app
                log.error("Verwerking van %s mislukt:\n%s", video_id, traceback.format_exc())
                if storage.load_meta(video_id) is not None:
                    storage.update_meta(video_id, status="error", error=str(e) or e.__class__.__name__)
            finally:
                with self._lock:
                    self.current = None
                    if video_id in self.to_delete:
                        self.to_delete.discard(video_id)
                        storage.delete_video(video_id)


class Pipeline:
    def __init__(self, video_id: str, worker: Worker) -> None:
        self.id = video_id
        self.worker = worker
        self.dir = storage.video_dir(video_id)
        self.meta = storage.load_meta(video_id) or {}

    # -- hulpfuncties -----------------------------------------------------
    def check(self) -> None:
        if self.id in self.worker.cancelled or not (self.dir / storage.META).exists():
            raise Cancelled()

    def progress(self, part: str):
        last = [0.0]

        def cb(value: float) -> None:
            self.check()
            # Niet bij elk klein stapje naar schijf schrijven.
            if value >= 1.0 or value - last[0] >= 0.005 or value < last[0]:
                last[0] = value
                storage.set_progress(self.id, part, value)
        return cb

    def stage(self, status: str) -> None:
        self.check()
        self.meta = storage.update_meta(self.id, status=status, error=None)

    # -- de stappen -------------------------------------------------------
    def run(self) -> None:
        media.check_ffmpeg()
        url = self.meta["url"]
        audio_path = self.dir / storage.AUDIO_RAW
        frames_dir = self.dir / storage.FRAMES_DIR
        transcript_done = (self.dir / storage.TRANSCRIPT).exists()
        audio_done = (self.dir / storage.AUDIO_EVENTS).exists() or not config.AUDIO_EVENTS
        frames_data = storage.read_json(self.dir / storage.FRAMES, {})
        need_audio = not (transcript_done and audio_done)
        need_frames = config.VISION and not frames_data.get("frames")

        # 1. Downloaden (alleen als we het bestand nog nodig hebben)
        video = download.find_video(self.dir)
        info = None
        if (need_audio and not audio_path.exists()) or need_frames:
            if video is None:
                self.stage("downloading")
                info = download.probe(url)
                video = download.download_video(url, self.dir, self.progress("download"))
            storage.set_progress(self.id, "download", 1.0)

        # 2. Audio en frames eruit halen
        if video is not None and ((need_audio and not audio_path.exists()) or need_frames):
            self.stage("extracting")
            probe = media.probe(video)
            duration = probe["duration"] or self.meta.get("duration") or 0
            interval = media.frame_interval(duration)
            if duration and not self.meta.get("duration"):
                storage.update_meta(self.id, duration=duration)
            media.extract_all(
                video, self.dir,
                audio_path=audio_path if need_audio and probe["has_audio"] and not audio_path.exists() else None,
                frames_dir=frames_dir if need_frames and probe["has_video"] else None,
                interval=interval, duration=duration, on_progress=self.progress("extract"),
            )
            if need_frames and probe["has_video"]:
                frames_data = {"interval": interval, "frames": media.list_frames(frames_dir, interval)}
                storage.write_json(self.dir / storage.FRAMES, frames_data)
            storage.set_progress(self.id, "extract", 1.0)

        # 3. Analyseren: geluid (transcript + geluiden) en beeld lopen tegelijk.
        self.stage("analyzing")
        errors: dict[str, str] = {}

        def audio_part() -> None:
            try:
                self.do_transcript(url, info, audio_path)
                self.do_audio_events(audio_path)
            except Cancelled:
                raise
            except Exception as e:  # noqa: BLE001
                log.error("Audio-analyse mislukt:\n%s", traceback.format_exc())
                errors["audio"] = str(e)

        def vision_part() -> None:
            try:
                self.do_vision(frames_dir)
            except Cancelled:
                raise
            except Exception as e:  # noqa: BLE001
                log.error("Beeldanalyse mislukt:\n%s", traceback.format_exc())
                errors["vision"] = str(e)

        t = threading.Thread(target=self._swallow_cancel(vision_part), daemon=True)
        t.start()
        self._swallow_cancel(audio_part)()
        t.join()
        self.check()

        if errors:
            msg = " | ".join(f"{'Geluid/spraak' if k == 'audio' else 'Beeld'}: {v}" for k, v in errors.items())
            storage.update_meta(self.id, status="error", error=msg)
            return

        storage.update_meta(self.id, status="done", error=None, finished_at=time.time())
        self.cleanup()

    @staticmethod
    def _swallow_cancel(fn):
        def wrapped() -> None:
            try:
                fn()
            except Cancelled:
                pass
        return wrapped

    def do_transcript(self, url: str, info: dict | None, audio_path) -> None:
        if (self.dir / storage.TRANSCRIPT).exists():
            storage.set_progress(self.id, "transcript", 1.0)
            return
        segments, source, language = None, None, None
        if config.USE_YOUTUBE_SUBTITLES and self.meta.get("platform") == "youtube":
            try:
                storage.set_progress(self.id, "transcript", 0.0, "ondertitels van YouTube ophalen")
                info = info or download.probe(url)
                subs = download.download_subtitles(url, info, self.dir)
                if subs:
                    segments = transcribe.parse_json3(subs[0])
                    source, language = "youtube-ondertitels", subs[1]
            except Exception as e:  # noqa: BLE001 - dan maar zelf transcriberen
                log.warning("Ondertitels ophalen mislukt: %s", e)
                segments = None
        if not segments:
            if not audio_path.exists():
                storage.write_json(self.dir / storage.TRANSCRIPT, {"source": "geen audio", "segments": []})
                storage.set_progress(self.id, "transcript", 1.0, "geen audio gevonden")
                return
            storage.set_progress(self.id, "transcript", 0.0, f"transcriberen met Whisper ({config.WHISPER_MODEL})")
            segments, language = transcribe.whisper(media.load_audio(audio_path), self.meta.get("duration") or 0,
                                                    self.progress("transcript"))
            source = f"whisper-{config.WHISPER_MODEL}"
        storage.write_json(self.dir / storage.TRANSCRIPT,
                           {"source": source, "language": language, "segments": segments})
        storage.update_meta(self.id, transcript_source=source, language=language or self.meta.get("language"))
        storage.set_progress(self.id, "transcript", 1.0, f"{len(segments)} zinnen ({source})")

    def do_audio_events(self, audio_path) -> None:
        if not config.AUDIO_EVENTS:
            storage.set_progress(self.id, "audio", 1.0, "uitgeschakeld")
            return
        if (self.dir / storage.AUDIO_EVENTS).exists():
            storage.set_progress(self.id, "audio", 1.0)
            return
        if not audio_path.exists():
            storage.write_json(self.dir / storage.AUDIO_EVENTS, {"events": []})
            storage.set_progress(self.id, "audio", 1.0, "geen audio gevonden")
            return
        try:
            from . import audio_events
            storage.set_progress(self.id, "audio", 0.0, "geluiden herkennen")
            events = audio_events.detect(media.load_audio(audio_path), self.progress("audio"))
        except ImportError:
            storage.set_progress(self.id, "audio", 1.0, "overgeslagen: installeer torch en transformers")
            return
        storage.write_json(self.dir / storage.AUDIO_EVENTS, {"model": config.AUDIO_MODEL, "events": events})
        laughs = sum(1 for e in events if e.get("group") == "laughter")
        storage.set_progress(self.id, "audio", 1.0, f"{len(events)} geluiden, waarvan {laughs}× lachen")

    def do_vision(self, frames_dir) -> None:
        if not config.VISION:
            storage.set_progress(self.id, "vision", 1.0, "uitgeschakeld")
            return
        data = storage.read_json(self.dir / storage.FRAMES, {})
        frames = data.get("frames", [])
        if not frames:
            storage.set_progress(self.id, "vision", 1.0, "geen beeld")
            return
        if not config.has_api_key():
            raise ClaudeError("geen ANTHROPIC_API_KEY ingesteld; zet die in .env en klik op 'Opnieuw proberen'")

        def save(fr: list[dict]) -> None:
            storage.write_json(self.dir / storage.FRAMES, {**data, "frames": fr})

        storage.set_progress(self.id, "vision", 0.0, f"{len(frames)} beelden beschrijven met {config.VISION_MODEL}")
        vision.describe_frames(self.id, frames, frames_dir, self.meta.get("title", ""), save,
                               self.progress("vision"), lambda: self.id in self.worker.cancelled)
        missing = sum(1 for f in frames if "description" not in f and "same_as" not in f)
        described = sum(1 for f in frames if "description" in f)
        if missing:
            raise ClaudeError(f"{missing} beelden konden niet beschreven worden; klik op 'Opnieuw proberen'")
        storage.set_progress(self.id, "vision", 1.0,
                             f"{described} beelden beschreven, {len(frames) - described} ongewijzigd overgeslagen")

    def cleanup(self) -> None:
        """Grote bestanden opruimen; frames en resultaten blijven staan."""
        if config.KEEP_MEDIA:
            return
        (self.dir / storage.AUDIO_RAW).unlink(missing_ok=True)
        if self.meta.get("platform") not in {"youtube", "twitch"}:
            return  # geen officiële speler: het videobestand is nodig om af te spelen
        for p in self.dir.glob("video.*"):
            p.unlink(missing_ok=True)
        for p in self.dir.glob("subs*.json3"):
            p.unlink(missing_ok=True)
