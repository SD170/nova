"""Tiny Gemini helper: one JSON-schema call with model fallback."""

import asyncio
import json
import logging
from typing import Any

import httpx

from .events import track

log = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


async def gemini_json(api_key: str, models: list[str], system: str, user_text: str,
                      schema: dict[str, Any], timeout: float = 30,
                      temperature: float = 0, retries: int = 0) -> Any:
    """Try each model in order; return the parsed JSON. Raises RuntimeError if all fail.
    retries > 0: when every model failed with a temporary overload (HTTP 429/5xx), wait and
    try the list again (2 s, 4 s, ...)."""
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {"temperature": temperature,
                             "responseMimeType": "application/json",
                             "responseSchema": schema},
    }
    last: Exception | None = None
    for attempt in range(retries + 1):
        temporary = False
        for model in models:
            try:
                with track("gemini", "Ask Gemini for structured JSON",
                            note=model):
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        resp = await client.post(GEMINI_URL.format(model=model),
                                                 headers={"x-goog-api-key": api_key}, json=body)
                if resp.status_code != 200:
                    temporary = temporary or resp.status_code in (429, 500, 502, 503, 504)
                    raise RuntimeError(f"Gemini HTTP {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)
            except (httpx.HTTPError, RuntimeError, KeyError, IndexError, ValueError) as exc:
                log.warning("Gemini %s failed: %s", model, exc)
                last = exc
        if attempt < retries and temporary:
            await asyncio.sleep(2 * (attempt + 1))
        else:
            break
    raise RuntimeError(f"All Gemini models failed: {last}")
