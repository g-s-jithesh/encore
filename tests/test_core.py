import os
import sys
import tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["ENCORE_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["LLM_PROVIDER"] = "none"  # never call a real LLM from tests

import db
import srs
from generate import make_cards


def test_srs():
    d = date(2026, 1, 1)
    assert srs.review(0, True, d) == (1, d + timedelta(days=3))
    assert srs.review(3, True, d)[0] == 3  # capped
    assert srs.review(2, False, d) == (0, d + timedelta(days=1))


def test_flow():
    assert db.add_cards("t", make_cards("What is ATP? Cell energy currency")) == 1
    c = db.next_due()
    assert c["question"] == "What is ATP?"
    g = db.grade(c["id"], True)
    assert g["box"] == 1 and db.next_due() is None
    assert db.stats() == {"total": 1, "due_today": 0, "mastered": 0}


def test_server_validation():
    import server

    assert "didn't get any notes" in server.add_material("x", "   ")
    assert "one topic" in server.add_material("x", "a" * (server.MAX_TEXT + 1))
    assert "couldn't find anything" in server.add_material("x", "no questions here")
    assert "error" in server.grade_card(999999, True)

    import logging

    real = server.make_cards
    server.make_cards = lambda t: 1 / 0  # simulate a Bedrock failure
    logging.disable(logging.CRITICAL)
    try:
        assert "try again" in server.add_material("x", "What is ATP? energy")
    finally:
        server.make_cards = real
        logging.disable(logging.NOTSET)

    assert server.add_material("  ", "What is DNA? Genetic code").startswith("Added 1 flashcard from your notes")
    c = server.next_card()
    assert server.grade_card(c["id"], False)["comes_back"] == "tomorrow"
    assert "cards" in server.progress()["message"]


def test_materials():
    import server

    for t in [x["title"] for x in db.materials()]:  # isolate from earlier tests
        db.delete_material(t)
    assert "haven't added" in server.list_materials()["message"]
    assert "don't have any flashcards" in server.next_card()["message"]

    server.add_material("Bio", "What is ATP? energy\nWhat is DNA? code")
    server.add_material("chem", "What is H2O? water")
    assert server.next_card("CHEM")["question"] == "What is H2O?"  # case-insensitive topic
    assert server.next_card("bio")["title"] == "Bio"
    assert "on physics" in server.next_card("physics")["message"]

    m = server.list_materials()
    assert [(x["title"], x["cards"]) for x in m["materials"]] == [("Bio", 2), ("chem", 1)]
    assert "Bio (2 cards)" in m["message"]

    c = server.next_card("chem")
    server.grade_card(c["id"], True)
    assert server.next_card("chem")["message"] == "You're all caught up on chem. Your next review is in 3 days."

    assert server.delete_material("bio") == "Deleted 2 flashcards from bio."
    assert "couldn't find" in server.delete_material("bio")
    assert "couldn't find" in server.delete_material("  ")
    assert db.stats()["total"] == 1


def test_gemini_thinking_config():
    import io
    import json
    from unittest.mock import patch

    import gemini

    def body_for(model):
        sent = {}

        def fake_urlopen(request, timeout):
            sent.update(json.loads(request.data))
            return io.BytesIO(b'{"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}')

        env = {"GEMINI_API_KEY": "k", **({"GEMINI_MODEL": model} if model else {})}
        with patch.dict(os.environ, env), patch("urllib.request.urlopen", fake_urlopen):
            os.environ.pop("GEMINI_THINKING_LEVEL", None)
            if not model:
                os.environ.pop("GEMINI_MODEL", None)
            gemini.generate([{"role": "user", "parts": [{"text": "hi"}]}])
        return sent["generationConfig"]

    assert body_for(None) == {"thinkingConfig": {"thinkingLevel": "minimal"}}  # tested default model
    assert body_for("gemini-2.5-flash") == {}  # other models keep their own thinking defaults


if __name__ == "__main__":
    test_srs(); test_flow(); test_server_validation(); test_materials(); test_gemini_thinking_config(); print("ok")
