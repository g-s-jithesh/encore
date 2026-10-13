"""Encore MCP server (Streamable HTTP, MCP spec 2025-11-25+).

Run: python server.py   ->  http://127.0.0.1:8000/mcp
"""
import json
from pathlib import Path

import logging
from datetime import date

from dotenv import load_dotenv
from mcp.server.apps import Apps, ResourceCsp
from mcp.server.mcpserver import MCPServer

import db
from generate import make_cards

load_dotenv()
log = logging.getLogger("encore")
MAX_TEXT = 20_000  # ponytail: hard cap keeps one Bedrock call cheap; raise once generate.py chunks

apps = Apps()
FLASHCARD_APP_URI = "ui://encore/flashcards.html"
apps.add_html_resource(
    FLASHCARD_APP_URI,
    (Path(__file__).parent / "web" / "flashcards.html").read_text(encoding="utf-8"),
    name="Encore flashcards",
    title="Your flashcards",
    description="Browse saved flashcards and reveal their answers.",
    csp=ResourceCsp(resource_domains=["https://esm.sh"]),
    prefers_border=True,
)

@apps.tool(
    resource_uri=FLASHCARD_APP_URI,
    visibility=["model", "app"],
    title="Show saved flashcards",
    description="Display the learner's saved flashcards in the interactive flashcard view.",
)
def list_flashcards() -> str:
    """Return saved flashcards and open the interactive flashcard view."""
    cards = db.list_cards()
    return json.dumps({"cards": cards}, ensure_ascii=False)


mcp = MCPServer(
    "Encore",
    instructions=(
        "Voice study coach. add_material turns notes into flashcards. To quiz: call "
        "next_card, ask the question aloud, judge the user's spoken answer yourself, "
        "then call grade_card, and keep going until next_card says done. For 'quiz me on X' "
        "pass title=X. Cards return on a spaced schedule across sessions. list_materials "
        "names the topics; confirm with the user before delete_material. "
        "Tool results include plain sentences (message, error, comes_back) you can read aloud. "
        "When the learner asks to see their flashcards, call list_flashcards."
    ),
    extensions=[apps],
)


def _when(due: str) -> str:
    """Spoken form of a due date: 'tomorrow', 'in 3 days'."""
    days = (date.fromisoformat(due) - date.today()).days
    return "today" if days <= 0 else "tomorrow" if days == 1 else f"in {days} days"


@mcp.tool()
def add_material(title: str, text: str) -> str:
    """Create flashcards from study notes or a lecture summary."""
    title, text = title.strip() or "your notes", text.strip()
    if not text:
        return "I didn't get any notes. Tell me what you studied and I'll make flashcards."
    if len(text) > MAX_TEXT:
        return "That's a lot at once. Try one topic or chapter at a time."
    try:
        cards = make_cards(text)
    except Exception:
        log.exception("make_cards failed")
        return "I couldn't make flashcards right now. Please try again in a moment."
    if not cards:
        return f"I couldn't find anything to quiz you on in {title}. Try adding a few key facts."
    n = db.add_cards(title, cards)
    return f"Added {n} flashcard{'s' if n != 1 else ''} from {title}. Say 'quiz me' to start."


@mcp.tool()
def next_card(title: str = "") -> dict:
    """Get the next flashcard due for review (question only). Pass title to quiz one topic."""
    c = db.next_due(title)
    if c:
        return {"id": c["id"], "title": c["title"], "question": c["question"]}
    upcoming = db.next_review(title)
    topic = f" on {title.strip()}" if title.strip() else ""
    if not upcoming:
        msg = f"You don't have any flashcards{topic} yet. Tell me what you studied to get started."
    else:
        msg = f"You're all caught up{topic}. Your next review is {_when(upcoming)}."
    return {"done": True, "message": msg}


@mcp.tool()
def list_materials() -> dict:
    """List study topics with how many cards each has and how many are due today."""
    items = db.materials()
    if not items:
        return {"materials": [], "message": "You haven't added any study material yet."}
    names = ", ".join(f"{m['title']} ({m['cards']} cards)" for m in items)
    return {"materials": items, "message": f"Your topics: {names}."}


@mcp.tool()
def delete_material(title: str) -> str:
    """Delete every flashcard for a topic. Confirm with the user before calling."""
    n = db.delete_material(title)
    if not n:
        return f"I couldn't find a topic called {title.strip() or 'that'}."
    return f"Deleted {n} flashcard{'s' if n != 1 else ''} from {title.strip()}."


@mcp.tool()
def grade_card(card_id: int, correct: bool) -> dict:
    """Record whether the user answered correctly; returns the right answer."""
    c = db.grade(card_id, correct)
    if not c:
        return {"error": "I couldn't find that card. Say 'next card' to keep going."}
    return {"answer": c["answer"], "next_review": c["due"], "comes_back": _when(c["due"])}


@mcp.tool()
def progress() -> dict:
    """Study stats: total cards, due today, mastered, plus a sentence to speak."""
    s = db.stats()
    if not s["total"]:
        msg = "You don't have any flashcards yet. Tell me what you studied to get started."
    else:
        msg = f"You have {s['total']} cards, {s['due_today']} due today, and {s['mastered']} mastered."
    return {**s, "message": msg}


if __name__ == "__main__":
    import os

    mcp.run(transport="streamable-http", port=int(os.environ.get("ENCORE_PORT", "8000")))
