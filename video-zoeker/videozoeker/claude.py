"""Kleine laag rond de Anthropic SDK: JSON-antwoorden, fallbacks en kostenbijhouding."""

from __future__ import annotations

import json
import threading
from typing import Any

import anthropic

from . import config, storage

_client: anthropic.Anthropic | None = None
_client_lock = threading.Lock()

# Modellen waarvoor de server-side fallback bestaat: als het model een verzoek
# weigert, probeert de API het automatisch opnieuw met een geschikt ander model.
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-2", "claude-fable-5-1", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Prijzen in dollar per miljoen tokens (invoer, uitvoer) - alleen voor een schatting.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-2": (8.00, 40.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
}


class ClaudeError(Exception):
    def __init__(self, message: str, fatal: bool = False):
        super().__init__(message)
        self.fatal = fatal  # True = opnieuw proberen heeft geen zin (sleutel/model fout)


def client() -> anthropic.Anthropic:
    global _client
    with _client_lock:
        if _client is None:
            _client = anthropic.Anthropic(max_retries=6)
        return _client


def ask_json(*, model: str, system: Any, content: Any, schema: dict, effort: str | None,
             max_tokens: int = 16000, stream: bool = False, usage_for: str | None = None) -> dict:
    """Stel een vraag en krijg JSON terug dat aan `schema` voldoet."""
    if not config.has_api_key():
        raise ClaudeError("Er is geen Anthropic API-sleutel ingesteld. Zet ANTHROPIC_API_KEY in het .env-bestand en start de app opnieuw.", fatal=True)
    output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
    if effort and not model.startswith("claude-haiku-4"):
        output_config["effort"] = effort
    params: dict[str, Any] = dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_config=output_config,
    )
    if model in FALLBACK_MODELS:
        api = client().beta.messages
        params.update(betas=[FALLBACK_BETA], fallbacks="default")
    else:
        api = client().messages

    try:
        if stream:
            with api.stream(**params) as s:
                msg = s.get_final_message()
        else:
            msg = api.create(**params)
    except anthropic.AuthenticationError as e:
        raise ClaudeError("De Anthropic API-sleutel ontbreekt of is ongeldig. Controleer ANTHROPIC_API_KEY in je .env-bestand.", fatal=True) from e
    except anthropic.PermissionDeniedError as e:
        raise ClaudeError(f"Geen toegang tot model {model}: {e.message}", fatal=True) from e
    except anthropic.NotFoundError as e:
        raise ClaudeError(f"Model {model} niet gevonden. Controleer de modelnaam in .env.", fatal=True) from e
    except anthropic.BadRequestError as e:
        raise ClaudeError(f"Claude weigerde het verzoek: {e.message}") from e
    except anthropic.RateLimitError as e:
        raise ClaudeError("Te veel verzoeken tegelijk (rate limit). Probeer het zo opnieuw.") from e
    except anthropic.APIStatusError as e:
        raise ClaudeError(f"Fout van de Claude API ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise ClaudeError("Kan de Claude API niet bereiken. Controleer je internetverbinding.") from e
    except anthropic.AnthropicError as e:
        raise ClaudeError(f"Fout bij het aanroepen van Claude: {e}") from e

    if usage_for:
        record_usage(usage_for, msg)

    if msg.stop_reason == "refusal":
        raise ClaudeError("Claude heeft dit verzoek geweigerd.")
    if msg.stop_reason == "max_tokens":
        raise ClaudeError("Het antwoord was te lang en is afgebroken.")

    # Bij een fallback kan er een onvolledig stuk tekst vóór het 'fallback'-blok staan.
    text = ""
    for block in msg.content:
        if block.type == "fallback":
            text = ""
        elif block.type == "text":
            text += block.text
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ClaudeError("Claude gaf geen geldig JSON-antwoord terug.") from e


def record_usage(video_id: str, msg: Any) -> None:
    u = msg.usage
    model = getattr(msg, "model", None) or "onbekend"
    with storage._lock:
        meta = storage.load_meta(video_id)
        if meta is None:
            return
        usage = meta.setdefault("usage", {})
        entry = usage.setdefault(model, {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0, "requests": 0})
        entry["input"] += u.input_tokens or 0
        entry["output"] += u.output_tokens or 0
        entry["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        entry["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        entry["requests"] += 1
        meta["cost_estimate"] = estimate_cost(usage)
        storage.save_meta(video_id, meta)


def estimate_cost(usage: dict) -> float | None:
    total = 0.0
    known = False
    for model, u in usage.items():
        price = next((p for m, p in PRICES.items() if model.startswith(m)), None)
        if price is None:
            continue
        known = True
        inp, out = price
        total += (u["input"] + 1.25 * u["cache_write"] + 0.1 * u["cache_read"]) * inp / 1e6
        total += u["output"] * out / 1e6
    return round(total, 4) if known else None
