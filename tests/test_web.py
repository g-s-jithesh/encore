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
                )
            ]
        )

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return SimpleNamespace(
            structured_content={"cards_added": 3},
            content=[],
            is_error=False,
        )


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
            patch.object(web_app, "LLM_PROVIDER", "bedrock"),  # .env may select gemini locally
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

    async def test_gemini_provider_runs_the_same_tool_loop(self):
        session = FakeClientSession()
        replies = [
            {"role": "model", "parts": [{"functionCall": {"name": "add_material",
                                                          "args": {"title": "Biology", "text": "ATP"}},
                                         "thoughtSignature": "sig"}]},
            {"role": "model", "parts": [{"text": "Added three cards from Biology."}]},
        ]
        requests = []

        def fake_generate(contents, system, tools):
            requests.append([dict(c) for c in contents])
            return replies.pop(0)

        @asynccontextmanager
        async def fake_transport(_):
            yield object(), object()

        with (
            patch.object(web_app, "streamable_http_client", fake_transport),
            patch.object(web_app, "ClientSession", return_value=session),
            patch.object(web_app, "LLM_PROVIDER", "gemini"),
            patch.object(web_app.gemini, "generate", fake_generate),
        ):
            reply = await web_app.run_agent([{"role": "user", "content": [{"text": "I studied ATP."}]}])

        self.assertEqual(reply, "Added three cards from Biology.")
        self.assertEqual(session.calls, [("add_material", {"title": "Biology", "text": "ATP"})])
        second = requests[1]
        self.assertEqual(second[1]["parts"][0]["thoughtSignature"], "sig")  # model turn replayed verbatim
        self.assertEqual(second[2]["parts"][0]["functionResponse"]["name"], "add_material")

    async def test_errors_inside_mcp_client_are_unwrapped(self):
        @asynccontextmanager
        async def failing_transport(_):
            raise ExceptionGroup("task group", [OSError("connection refused")])
            yield

        with (
            patch.object(web_app, "streamable_http_client", failing_transport),
            patch.object(web_app, "BEDROCK_MODEL_ID", "test-model"),
            patch.object(web_app, "LLM_PROVIDER", "bedrock"),
        ):
            with self.assertRaises(OSError):
                await web_app.run_agent([], bedrock_client=FakeBedrock())


if __name__ == "__main__":
    import unittest

    unittest.main()
