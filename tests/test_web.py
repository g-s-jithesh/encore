import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import web.app as web_app


class FakeBedrock:
    def __init__(self):
        self.responses = [
            {
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": "call-1",
                                    "name": "add_material",
                                    "input": {"title": "Biology", "text": "ATP is cellular energy."},
                                }
                            }
                        ],
                    }
                },
                "stopReason": "tool_use",
            },
            {
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [{"text": "Added three cards from Biology."}],
                    }
                },
                "stopReason": "end_turn",
            },
        ]
        self.requests = []

    def converse(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


class FakeClientSession:
    def __init__(self, *_):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def initialize(self):
        return None

    async def list_tools(self):
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="add_material",
                    description="Create flashcards from study notes.",
                    input_schema={
                        "type": "object",
                        "properties": {"title": {"type": "string"}, "text": {"type": "string"}},
                    },
                ),
                SimpleNamespace(
                    name="next_card",
                    description="Get the next flashcard due for review.",
                    input_schema={"type": "object", "properties": {}},
                ),
                SimpleNamespace(
                    name="grade_card",
                    description="Record the answer judgment.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "card_id": {"type": "integer"},
                            "correct": {"type": "boolean"},
                        },
                    },
                ),
                SimpleNamespace(
                    name="progress",
                    description="Get study progress.",
                    input_schema={"type": "object", "properties": {}},
                ),
            ]
        )

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        results = {
            "add_material": {"cards_added": 3},
            "progress": {"total": 3, "due_today": 3, "mastered": 0},
            "next_card": {"id": 17, "title": "Biology", "question": "What powers the cell?"},
            "grade_card": {
                "answer": "ATP is the cell's energy currency.",
                "next_review": "2026-10-13",
            },
        }
        return SimpleNamespace(
            structured_content=results[name],
            content=[],
            is_error=False,
        )


def tool_response(name, arguments, call_id):
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": call_id,
                            "name": name,
                            "input": arguments,
                        }
                    }
                ],
            }
        },
        "stopReason": "tool_use",
    }


class WebAgentTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        web_app._conversations.clear()
        web_app._conversation_locks.clear()

    async def test_failed_turn_does_not_change_saved_conversation(self):
        conversation_id, messages, _ = await web_app._conversation(None)
        saved_turn = {"role": "user", "content": [{"text": "Earlier question"}]}
        messages.append(saved_turn)

        async def receive():
            return {
                "type": "http.request",
                "body": json.dumps(
                    {
                        "conversation_id": conversation_id,
                        "message": "Continue the quiz",
                    }
                ).encode(),
                "more_body": False,
            }

        request = web_app.Request(
            {
                "type": "http",
                "method": "POST",
                "headers": [(b"content-type", b"application/json")],
                "path": "/api/chat",
                "query_string": b"",
                "scheme": "http",
                "server": ("test", 80),
                "client": ("test", 1234),
            },
            receive,
        )
        with patch.object(
            web_app,
            "run_agent",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Bedrock unavailable"),
        ):
            response = await web_app.chat(request)

        self.assertEqual(response.status_code, 502)
        self.assertEqual(messages, [saved_turn])

    async def test_agent_lists_calls_mcp_tools_and_returns_bedrock_reply(self):
        bedrock = FakeBedrock()
        session = FakeClientSession()

        @asynccontextmanager
        async def fake_transport(_):
            yield object(), object()

        with (
            patch.object(web_app, "streamable_http_client", fake_transport),
            patch.object(web_app, "ClientSession", return_value=session),
            patch.object(web_app, "BEDROCK_MODEL_ID", "test-model"),
        ):
            messages = [
                {"role": "user", "content": [{"text": "I studied ATP."}]},
            ]
            reply = await web_app.run_agent(
                messages,
                bedrock_client=bedrock,
                mcp_server_url="http://example.test/mcp",
            )

        self.assertEqual(reply, "Added three cards from Biology.")
        self.assertEqual(
            session.calls,
            [("add_material", {"title": "Biology", "text": "ATP is cellular energy."})],
        )
        self.assertEqual(len(bedrock.requests), 2)
        self.assertEqual(
            bedrock.requests[0]["toolConfig"]["tools"][0]["toolSpec"]["name"],
            "add_material",
        )
        self.assertEqual(messages[2]["content"][0]["toolResult"]["toolUseId"], "call-1")

    async def test_full_study_session_add_quiz_grade_and_progress(self):
        bedrock = FakeBedrock()
        bedrock.responses = [
            tool_response(
                "add_material",
                {"title": "Biology", "text": "ATP powers the cell."},
                "call-add",
            ),
            tool_response("progress", {}, "call-progress-before"),
            tool_response("next_card", {}, "call-next"),
            tool_response("grade_card", {"card_id": 17, "correct": True}, "call-grade"),
            tool_response("progress", {}, "call-progress-after"),
            {
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [{"text": "You reviewed one card. Three cards are saved for later."}],
                    }
                },
                "stopReason": "end_turn",
            },
        ]
        session = FakeClientSession()

        @asynccontextmanager
        async def fake_transport(_):
            yield object(), object()

        with (
            patch.object(web_app, "streamable_http_client", fake_transport),
            patch.object(web_app, "ClientSession", return_value=session),
            patch.object(web_app, "BEDROCK_MODEL_ID", "test-model"),
        ):
            reply = await web_app.run_agent(
                [{"role": "user", "content": [{"text": "Let's study ATP, then quiz me."}]}],
                bedrock_client=bedrock,
                mcp_server_url="http://example.test/mcp",
            )

        self.assertEqual(
            [name for name, _ in session.calls],
            ["add_material", "progress", "next_card", "grade_card", "progress"],
        )
        self.assertEqual(session.calls[2], ("next_card", {}))
        self.assertEqual(
            session.calls[3],
            ("grade_card", {"card_id": 17, "correct": True}),
        )
        self.assertEqual(reply, "You reviewed one card. Three cards are saved for later.")
        self.assertEqual(len(bedrock.requests), 6)


if __name__ == "__main__":
    import unittest

    unittest.main()
