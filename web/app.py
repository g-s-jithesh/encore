"""Web host for Encore's Bedrock-backed Alexa+ simulator."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Any
from uuid import uuid4

import anyio
import boto3
from botocore.exceptions import BotoCoreError
from dotenv import load_dotenv
from mcp import ClientSession, MCPError
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

load_dotenv()

import gemini  # noqa: E402

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
MCP_SERVER_URL = os.getenv(
    "MCP_SERVER_URL",
    f"http://127.0.0.1:{os.getenv('ENCORE_PORT', '8000')}/mcp",
)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "bedrock")  # or "gemini"
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "")
BEDROCK_REGION = os.getenv("AWS_REGION", "us-east-1")
MAX_TOOL_ROUNDS = 8
MAX_CONVERSATIONS = 100
MAX_MESSAGE_LENGTH = 10_000

SYSTEM_PROMPT = (
    "You are Encore, a warm, concise voice study coach. Use the available MCP tools "
    "to add study material, list or remove topics, quiz the learner, grade answers, "
    "and report progress. Follow each tool's description and speak its plain-language "
    "messages naturally. When asked to be quizzed, get a due card and ask only its "
    "question; when the learner answers, judge it against the card answer, grade that "
    "card, and kindly explain the answer. Confirm with the learner before deleting "
    "study material. Never claim an action succeeded unless its tool call succeeded. "
    "Keep replies short."
)

_conversations: dict[str, list[dict[str, Any]]] = {}
_conversation_locks: dict[str, asyncio.Lock] = {}
_conversations_lock = asyncio.Lock()


class AgentLoopLimitError(RuntimeError):
    """Raised when the model keeps requesting tools without producing a reply."""


def _tool_specs(tools: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "toolSpec": {
                "name": tool.name,
                "description": tool.description or tool.name,
                "inputSchema": {"json": tool.input_schema},
            }
        }
        for tool in tools
    ]


def _mcp_result_text(result: Any) -> str:
    if result.structured_content is not None:
        return json.dumps(result.structured_content, ensure_ascii=False)
    text_parts = [item.text for item in result.content if getattr(item, "type", None) == "text"]
    if text_parts:
        return "\n".join(text_parts)
    return "The tool completed without a text result."


def _text_from_message(message: dict[str, Any]) -> str:
    return "\n".join(
        block["text"]
        for block in message.get("content", [])
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    ).strip()


def _gemini_converse(system: list[dict], messages: list[dict], toolConfig: dict) -> dict:
    """Run one Converse-shaped call on Gemini, so run_agent's loop works for both providers."""
    names: dict[str, str] = {}
    contents = []
    for message in messages:
        parts = []
        for block in message["content"]:
            if "toolUse" in block:
                names[block["toolUse"]["toolUseId"]] = block["toolUse"]["name"]
            elif "toolResult" in block:
                result = block["toolResult"]
                parts.append({"functionResponse": {
                    "name": names[result["toolUseId"]],
                    "response": {"result": result["content"][0]["text"]},
                }})
            elif "text" in block:
                parts.append({"text": block["text"]})
        # replay Gemini's own turn verbatim: it carries thought signatures the API requires back
        contents.append(message.get("_gemini") or {"role": "user", "parts": parts})

    content = gemini.generate(contents, system[0]["text"], [
        {"name": t["toolSpec"]["name"], "description": t["toolSpec"]["description"],
         "parametersJsonSchema": t["toolSpec"]["inputSchema"]["json"]}
        for t in toolConfig["tools"]
    ])
    blocks: list[dict[str, Any]] = []
    for part in content.get("parts", []):
        if "functionCall" in part:
            call = part["functionCall"]
            blocks.append({"toolUse": {"toolUseId": call.get("id") or str(uuid4()),
                                       "name": call["name"], "input": call.get("args") or {}}})
        elif "text" in part and not part.get("thought"):
            blocks.append({"text": part["text"]})
    return {
        "output": {"message": {"role": "assistant", "content": blocks, "_gemini": content}},
        "stopReason": "tool_use" if any("toolUse" in b for b in blocks) else "end_turn",
    }


async def run_agent(
    messages: list[dict[str, Any]],
    bedrock_client: Any | None = None,
    mcp_server_url: str = MCP_SERVER_URL,
) -> str:
    """Run one agent turn, executing requested tools through the MCP server."""
    try:
        return await _run_agent(messages, bedrock_client, mcp_server_url)
    except ExceptionGroup as group:  # the MCP client's task group wraps errors raised inside it
        error: BaseException = group
        while isinstance(error, ExceptionGroup) and len(error.exceptions) == 1:
            error = error.exceptions[0]
        raise error from None


async def _run_agent(messages: list[dict[str, Any]], bedrock_client: Any | None, mcp_server_url: str) -> str:
    if LLM_PROVIDER == "gemini":
        converse = _gemini_converse
    else:
        if not BEDROCK_MODEL_ID:
            raise RuntimeError("BEDROCK_MODEL_ID is not configured.")
        client = bedrock_client or boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
        converse = partial(client.converse, modelId=BEDROCK_MODEL_ID)

    async with streamable_http_client(mcp_server_url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listed_tools = await session.list_tools()
            tool_config = {"tools": _tool_specs(listed_tools.tools)}

            for _ in range(MAX_TOOL_ROUNDS):
                response = await anyio.to_thread.run_sync(
                    partial(
                        converse,
                        system=[{"text": SYSTEM_PROMPT}],
                        messages=messages,
                        toolConfig=tool_config,
                    )
                )
                message = response["output"]["message"]
                messages.append(message)

                tool_uses = [
                    block["toolUse"]
                    for block in message.get("content", [])
                    if isinstance(block, dict) and "toolUse" in block
                ]
                if response.get("stopReason") != "tool_use":
                    reply = _text_from_message(message)
                    if not reply:
                        raise RuntimeError("Bedrock returned no reply text.")
                    return reply

                if not tool_uses:
                    raise RuntimeError("Bedrock requested tools but returned no tool calls.")

                tool_results = []
                for tool_use in tool_uses:
                    result = await session.call_tool(
                        tool_use["name"],
                        tool_use.get("input") or {},
                    )
                    tool_result: dict[str, Any] = {
                        "toolUseId": tool_use["toolUseId"],
                        "content": [{"text": _mcp_result_text(result)}],
                    }
                    if result.is_error:
                        tool_result["status"] = "error"
                    tool_results.append({"toolResult": tool_result})

                messages.append({"role": "user", "content": tool_results})

    raise AgentLoopLimitError(f"Bedrock requested tools more than {MAX_TOOL_ROUNDS} times.")


async def _conversation(conversation_id: str | None) -> tuple[str, list[dict[str, Any]], asyncio.Lock]:
    async with _conversations_lock:
        if conversation_id is None:
            conversation_id = str(uuid4())
            _conversations[conversation_id] = []
            _conversation_locks[conversation_id] = asyncio.Lock()
            if len(_conversations) > MAX_CONVERSATIONS:
                oldest_id = next(iter(_conversations))
                _conversations.pop(oldest_id)
                _conversation_locks.pop(oldest_id)
        elif conversation_id not in _conversations:
            raise KeyError("Conversation not found. Start a new conversation.")
        return conversation_id, _conversations[conversation_id], _conversation_locks[conversation_id]


async def home(_: Request) -> Response:
    return FileResponse(BASE_DIR / "index.html")


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


async def chat(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"error": "Send a valid JSON request."}, status_code=400)

    if not isinstance(payload, dict):
        return JSONResponse({"error": "Send a JSON object with a message."}, status_code=400)

    text = payload.get("message")
    if not isinstance(text, str) or not text.strip():
        return JSONResponse({"error": "Please say or type a message first."}, status_code=400)
    if len(text) > MAX_MESSAGE_LENGTH:
        return JSONResponse({"error": "That message is too long. Please shorten it."}, status_code=413)

    conversation_id = payload.get("conversation_id")
    if conversation_id is not None and not isinstance(conversation_id, str):
        return JSONResponse({"error": "The conversation id is invalid."}, status_code=400)
    try:
        conversation_id, messages, lock = await _conversation(conversation_id)
    except KeyError as error:
        return JSONResponse({"error": str(error.args[0])}, status_code=404)

    async with lock:
        turn_messages = [*messages, {"role": "user", "content": [{"text": text.strip()}]}]
        try:
            reply = await run_agent(turn_messages)
        except (BotoCoreError, MCPError, AgentLoopLimitError, TimeoutError, OSError) as error:
            logger.exception("Encore agent request failed: %s", error)
            return JSONResponse(
                {"error": "I couldn't reach the study service. Please try again."},
                status_code=502,
            )
        except RuntimeError as error:
            logger.exception("Encore agent returned an invalid response: %s", error)
            return JSONResponse(
                {"error": "I couldn't finish that request. Please try again."},
                status_code=502,
            )
        except Exception as error:  # e.g. httpx ConnectError when server.py isn't running; the page needs JSON
            logger.exception("Encore agent request failed: %s", error)
            return JSONResponse(
                {"error": "I couldn't reach the study service. Please try again."},
                status_code=502,
            )
        messages[:] = turn_messages

    return JSONResponse({"reply": reply, "conversation_id": conversation_id})


@asynccontextmanager
async def lifespan(_: Starlette):
    try:
        await anyio.to_thread.run_sync(partial(urllib.request.urlopen, MCP_SERVER_URL, timeout=2))
    except urllib.error.HTTPError:
        pass  # any HTTP answer means the MCP server is up
    except OSError:
        logger.warning("No MCP server at %s. Start it first: python server.py", MCP_SERVER_URL)
    yield
    async with _conversations_lock:
        _conversations.clear()
        _conversation_locks.clear()


app = Starlette(
    routes=[
        Route("/", home),
        Route("/health", health),
        Route("/api/chat", chat, methods=["POST"]),
    ],
    lifespan=lifespan,
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web.app:app", host="127.0.0.1", port=5000, reload=False)
