"""Minimal Gemini REST client, used when LLM_PROVIDER=gemini.

Free API key: https://aistudio.google.com -> Get API key. Stdlib only, no SDK.
"""
import json
import os
import time
import urllib.error
import urllib.request

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.1-flash-lite"


def generate(contents: list[dict], system: str = "", tools: list[dict] | None = None, **config) -> dict:
    """POST one generateContent request and return the first candidate's content."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    model = os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
    # thinking adds tens of seconds on the free tier; levels differ per model, so only
    # default it for the model we tested (GEMINI_THINKING_LEVEL overrides, "" disables)
    level = os.environ.get("GEMINI_THINKING_LEVEL", "minimal" if model == DEFAULT_MODEL else "")
    if level:
        config.setdefault("thinkingConfig", {"thinkingLevel": level})
    body: dict = {"contents": contents, "generationConfig": config}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if tools:
        body["tools"] = [{"functionDeclarations": tools}]
    request = urllib.request.Request(
        URL.format(model=model),
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.load(response)
            break
        except urllib.error.HTTPError as error:
            with error:  # close the response, also before a retry
                detail = error.read().decode(errors="replace")[:300]
            if error.code == 503 and attempt < 2:  # "high demand" spikes are usually brief
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f"Gemini {error.code}: {detail}") from None
    try:
        return {"role": "model", **data["candidates"][0]["content"]}
    except (KeyError, IndexError):
        raise RuntimeError(f"Gemini returned no answer: {json.dumps(data)[:300]}") from None
