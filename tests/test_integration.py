"""Start server.py as a real process and drive every tool over Streamable HTTP.

Run: python tests/test_integration.py
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from mcp import Client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port: int) -> subprocess.Popen:
    env = {**os.environ, "ENCORE_PORT": str(port),
           "ENCORE_DB": os.path.join(tempfile.mkdtemp(), "it.db")}
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):  # up to ~10s
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/mcp", timeout=0.5)
        except urllib.error.HTTPError:
            return proc  # any HTTP answer means it's listening
        except OSError:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError("server did not start")


async def call(client: Client, name: str, args: dict | None = None):
    r = await client.call_tool(name, args or {})
    assert not r.is_error, r
    text = r.content[0].text
    try:
        return json.loads(text)  # dict-returning tools arrive as JSON text
    except ValueError:
        return text


async def run(url: str) -> None:
    async with Client(url) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        assert tools >= {"add_material", "next_card", "grade_card", "progress",
                         "list_materials", "delete_material", "list_flashcards"}, tools

        flashcard_tool = next(t for t in (await client.list_tools()).tools
                              if t.name == "list_flashcards")
        assert flashcard_tool.meta["ui"]["resourceUri"] == "ui://encore/flashcards.html"
        app = await client.read_resource("ui://encore/flashcards.html")
        assert app.contents[0].mime_type == "text/html;profile=mcp-app"
        assert "Reveal answer" in app.contents[0].text
        assert (await call(client, "list_flashcards"))["cards"] == []

        p = await call(client, "progress")
        assert "don't have any flashcards" in str(p)

        msg = await call(client, "add_material", {
            "title": "biology",
            "text": "What is ATP? Cell energy currency\nWhat is DNA? Genetic code",
        })
        assert "Added 2 flashcards" in str(msg), msg

        card = await call(client, "next_card")
        assert card["question"] == "What is ATP?", card
        g = await call(client, "grade_card", {"card_id": card["id"], "correct": True})
        assert g["answer"] == "Cell energy currency" and g["comes_back"] == "in 3 days", g

        card = await call(client, "next_card")
        g = await call(client, "grade_card", {"card_id": card["id"], "correct": False})
        assert g["comes_back"] == "tomorrow", g

        assert (await call(client, "next_card"))["done"] is True
        assert "error" in await call(client, "grade_card", {"card_id": 999, "correct": True})
        p = await call(client, "progress")
        assert p["total"] == 2 and p["due_today"] == 0, p

        await call(client, "add_material", {"title": "chem", "text": "What is H2O? water"})
        card = await call(client, "next_card", {"title": "chem"})
        assert card["question"] == "What is H2O?", card
        m = await call(client, "list_materials")
        assert [x["title"] for x in m["materials"]] == ["biology", "chem"], m
        assert "Deleted 1 flashcard" in await call(client, "delete_material", {"title": "chem"})


def test_integration():
    port = free_port()
    proc = start_server(port)
    try:
        asyncio.run(run(f"http://127.0.0.1:{port}/mcp"))
    finally:
        proc.kill()
        proc.wait()


if __name__ == "__main__":
    test_integration()
    print("ok")
