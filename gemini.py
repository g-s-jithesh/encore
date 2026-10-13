"""Minimal Gemini REST client, used when LLM_PROVIDER=gemini.

Free API key: https://aistudio.google.com -> Get API key. Stdlib only, no SDK.
"""
import json
import os
import urllib.error
import urllib.request

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def generate(contents: list[dict], system: str = "", tools: list[dict] | None = None, **config) -> dict:
    """POST one generateContent request and return the first candidate's content."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    body: dict = {"contents": contents, "generationConfig": config}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if tools:
        body["tools"] = [{"functionDeclarations": tools}]
    request = urllib.request.Request(
        URL.format(model=os.environ.get("GEMINI_MODEL", "gemini-flash-latest")),
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Gemini {error.code}: {error.read().decode(errors='replace')[:300]}") from None
    try:
        return {"role": "model", **data["candidates"][0]["content"]}
    except (KeyError, IndexError):
        raise RuntimeError(f"Gemini returned no answer: {json.dumps(data)[:300]}") from None
