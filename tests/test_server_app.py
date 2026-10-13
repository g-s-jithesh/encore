import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["ENCORE_DB"] = str(Path(tempfile.mkdtemp()) / "flashcards.db")

import server


class FlashcardAppTests(unittest.TestCase):
    def test_flashcard_tool_is_bound_to_html_app_resource(self):
        tools = server.apps.tools()
        resources = server.apps.resources()

        self.assertEqual([tool.fn.__name__ for tool in tools], ["list_flashcards"])
        self.assertEqual(tools[0].meta["ui"]["resourceUri"], "ui://encore/flashcards.html")
        self.assertIn("app", tools[0].meta["ui"]["visibility"])
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0].resource.uri, "ui://encore/flashcards.html")
        self.assertEqual(resources[0].resource.mime_type, "text/html;profile=mcp-app")

    def test_flashcard_view_returns_saved_cards_as_json(self):
        server.db.add_cards(
            "Biology",
            [{"question": "What powers the cell?", "answer": "ATP"}],
        )

        self.assertEqual(
            json.loads(server.list_flashcards()),
            {
                "cards": [
                    {
                        "id": 1,
                        "title": "Biology",
                        "question": "What powers the cell?",
                        "answer": "ATP",
                        "box": 0,
                        "due": server.db.list_cards()[0]["due"],
                    }
                ]
            },
        )


if __name__ == "__main__":
    unittest.main()
