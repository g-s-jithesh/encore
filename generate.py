"""Turn study material into flashcards via Amazon Bedrock.

OWNER: Mano (@Mkkumar2006)
Contract (do not change without a PR + team agreement):
    make_cards(text: str) -> list[{"question": str, "answer": str}]

Provider: LLM_PROVIDER=bedrock (default), gemini (see gemini.py), or none
(offline regex parser only, used by the tests).
Bedrock model is read from the BEDROCK_MODEL_ID env var (required).
AWS credentials are picked up from the environment (AWS_ACCESS_KEY_ID,
AWS_SECRET_ACCESS_KEY, AWS_REGION) or from any standard boto3 credential
chain (instance profile, ~/.aws/credentials, etc.).

Chunking: text longer than CHUNK_CHARS is split on paragraph boundaries and
each chunk is sent separately; results are deduplicated by question.

Retry: if the model returns malformed JSON, we retry once with a stricter
prompt. If that also fails we fall back to the regex parser so the pipeline
keeps running.
"""
from __future__ import annotations

import json
import logging
import os
import re

import boto3

import gemini

logger = logging.getLogger(__name__)

# ── tunables ──────────────────────────────────────────────────────────────────
CHUNK_CHARS = 3_000          # split input if longer than this
MIN_CARDS   = 5
MAX_CARDS   = 10
_MODEL_ID   = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")

# ── prompt templates ──────────────────────────────────────────────────────────
_SYSTEM = (
    "You are a spaced-repetition flashcard generator. "
    "Respond ONLY with a JSON array of objects, each with exactly two keys: "
    '"question" and "answer". No markdown fences, no commentary, no extra keys.'
)

_USER_TMPL = (
    "Generate {min_cards} to {max_cards} high-quality flashcard question-answer "
    "pairs from the study notes below. The questions should be clear and "
    "unambiguous when read aloud; the answers should be concise.\n\n"
    "Study notes:\n{text}"
)

_STRICT_TMPL = (
    "Your previous response was not valid JSON. "
    "Reply with ONLY a JSON array like: "
    '[{{"question":"Q1","answer":"A1"}}, ...]. '
    "No other text. Study notes:\n{text}"
)


# ── Bedrock client (lazy singleton) ──────────────────────────────────────────
_client = None


def _bedrock():
    global _client
    if _client is None:
        _client = boto3.client(
            "bedrock-runtime",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
    return _client


# ── core LLM call ─────────────────────────────────────────────────────────────
def _call_bedrock(user_message: str) -> str:
    """Send a single Converse request and return the text content."""
    response = _bedrock().converse(
        modelId=_MODEL_ID,
        system=[{"text": _SYSTEM}],
        messages=[{"role": "user", "content": [{"text": user_message}]}],
        inferenceConfig={"maxTokens": 1024, "temperature": 0.3},
    )
    return response["output"]["message"]["content"][0]["text"].strip()


def _call_gemini(user_message: str) -> str:
    """Same contract as _call_bedrock, via Gemini (LLM_PROVIDER=gemini)."""
    content = gemini.generate(
        [{"role": "user", "parts": [{"text": user_message}]}],
        _SYSTEM,
        responseMimeType="application/json",
    )
    return "".join(part.get("text", "") for part in content.get("parts", [])).strip()


def _parse_json(raw: str) -> list[dict]:
    """Extract a JSON array from raw text, stripping any markdown fences."""
    # strip optional ```json ... ``` fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array")
    cards = []
    for item in data:
        q = str(item.get("question", "")).strip()
        a = str(item.get("answer", "")).strip()
        if q and a:
            cards.append({"question": q, "answer": a})
    return cards


def _llm_cards(text: str, *, strict: bool = False) -> list[dict]:
    """Ask Bedrock once, parse JSON, raise on failure."""
    tmpl = _STRICT_TMPL if strict else _USER_TMPL
    prompt = tmpl.format(text=text, min_cards=MIN_CARDS, max_cards=MAX_CARDS)
    call = _call_gemini if os.environ.get("LLM_PROVIDER") == "gemini" else _call_bedrock
    return _parse_json(call(prompt))


# ── fallback regex parser (keeps pipeline alive on total failure) ─────────────
def _regex_fallback(text: str) -> list[dict]:
    """Minimal parser: matches 'question? answer' lines (original scaffold)."""
    cards = []
    for line in text.splitlines():
        if "?" in line:
            q, _, a = line.partition("?")
            if a.strip():
                cards.append({"question": q.strip() + "?", "answer": a.strip()})
    return cards


# ── chunking ──────────────────────────────────────────────────────────────────
def _chunks(text: str) -> list[str]:
    """Split long text on blank lines; each chunk ≤ CHUNK_CHARS."""
    if len(text) <= CHUNK_CHARS:
        return [text]
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if buf and len(buf) + len(para) + 2 > CHUNK_CHARS:
            chunks.append(buf.strip())
            buf = para
        else:
            buf = (buf + "\n\n" + para) if buf else para
    if buf.strip():
        chunks.append(buf.strip())
    return chunks or [text]


# ── deduplication ─────────────────────────────────────────────────────────────
def _dedupe(cards: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for c in cards:
        key = c["question"].lower().strip()
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


# ── public API ────────────────────────────────────────────────────────────────
def make_cards(text: str) -> list[dict]:
    """Return [{\"question\": str, \"answer\": str}, ...].

    Calls Amazon Bedrock (boto3 Converse). Handles:
    - Long inputs by chunking on paragraph boundaries.
    - Malformed JSON by retrying once with a stricter prompt.
    - Total failure by falling back to the regex parser.
    """
    if os.environ.get("LLM_PROVIDER") == "none":  # offline: tests and demos without an LLM
        return _dedupe(_regex_fallback(text))

    all_cards: list[dict] = []

    for chunk in _chunks(text):
        cards: list[dict] | None = None

        # first attempt
        try:
            cards = _llm_cards(chunk)
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.warning("Bedrock returned malformed JSON (%s); retrying…", exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("Bedrock call failed (%s); using fallback.", exc)
            cards = _regex_fallback(chunk)

        # retry once with stricter prompt on bad JSON
        if cards is None:
            try:
                cards = _llm_cards(chunk, strict=True)
            except Exception as exc:  # noqa: BLE001
                logger.error("Retry also failed (%s); using fallback.", exc)
                cards = _regex_fallback(chunk)

        all_cards.extend(cards or [])

    return _dedupe(all_cards)
