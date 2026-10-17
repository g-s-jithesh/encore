# Submission notes

**Name:** Encore
**Pitch:** Tell Alexa+ what you studied today. Encore turns it into flashcards and quizzes you by voice on a spaced schedule, picking up where you left off every session.
**Problem:** Students forget most of what they hear within days, and nobody has time to turn notes into review material.
**Track:** Alexa+ (simulated Alexa+ experience + self-hosted MCP server). **Mini challenge:** Open Source.
**Built with:** Python, MCP Python SDK 2.x (Streamable HTTP, MCP Apps), SQLite, Gemini API, Starlette, Web Speech API, TypeScript, Playwright.

## Text description
**Inspiration.** Students forget most of a lecture within days. Spaced repetition fixes that, but making flashcards takes time nobody has. With Alexa+ you can just say what you learned.

**What it does.** Tell Encore what you studied, by speaking or pasting notes. Encore turns it into flashcards, then quizzes you by voice: it asks a question, you answer out loud, it judges your answer and tells you when that card comes back. Cards you miss return tomorrow; cards you know return in 3, 7, then 14 days. Progress persists, so every session picks up where the last one ended. You can quiz one topic ("quiz me on photosynthesis"), ask how you're doing, list topics, delete one, and view your cards in an interactive MCP App. Typing works too, for when you can't talk.

**How we built it.** A self-hosted MCP server (Python, official MCP SDK 2.x, Streamable HTTP, spec 2025-11-25) exposes seven tools: add notes, get the next card, grade it, check progress, list and delete topics, and view flashcards. State lives in SQLite with a Leitner spaced-repetition schedule, so it survives restarts and sessions. Gemini turns notes into flashcards and runs the conversation. A web app simulates Alexa+: browser speech recognition and synthesis, plus an agent loop that connects to the server as a real MCP client (initialize, tools/list, tools/call) and lets the model call the tools. Every tool result includes a sentence that reads naturally aloud. The flashcard view is a `ui://` MCP App resource, with a plain-text result for clients that don't support Apps. Because it's a standard MCP server, the same server also works unchanged in other MCP clients such as Claude Code.

**Challenges.** Our new AWS account was never cleared for Amazon Bedrock (every call returned "Operation not allowed"; other regions said the account was still being verified), so with a week to go we added a provider switch and moved to Gemini's free tier. The free tier was often overloaded or slow, so we added retries, picked the fastest model, turned its thinking down, and made the UI explain long waits. The MCP SDK's v2 API also differs from most tutorials (`FastMCP` is now `MCPServer`).

**Accomplishments.** It remembers: cards, schedule and progress persist across sessions, which turns a one-off Q&A bot into a study habit. The MCP server works with any MCP client, not just our simulator. The voice simulator, the MCP App view and the server are covered by unit, integration and browser tests that run in CI on every pull request.

**What we learned.** Writing every tool result as a sentence that can be read aloud makes the agent's job easy: it just reads the result instead of turning data into prose. Tool results can serve both a voice conversation (text) and a richer view (structured content for the MCP App) at once. And speech input and output are separate browser capabilities, so a typed fallback matters.

**What's next.** Real Alexa+ integration once add-on tooling opens up, importing lecture PDFs and transcripts (`ingest.py` already extracts their text), and shared decks for study groups.

## Open Source mini challenge (Devpost fields)
- **Contribution URL:** https://github.com/g-s-jithesh/python-sdk/commit/6ecfa04ece6032816c7d3a087fd8c841cb0c43e1
  (branch `fix/bare-container-structured-output` on our fork; reported upstream as
  https://github.com/modelcontextprotocol/python-sdk/issues/3725)
- **Project repository URL:** https://github.com/g-s-jithesh/encore
- **GitHub username:** g-s-jithesh
- **What:** a bug fix for the official MCP Python SDK. A tool whose return type is a bare `dict`, `list` or
  `tuple` silently lost its structured output (no `outputSchema`, `structuredContent` always `None`), while
  `dict[str, Any]` worked; with `structured_output=True` it even claimed a dict "is not serializable".
- **How:** bare containers fell through to the SDK's "other class" case, where `get_type_hints(dict)` is
  empty, so no output model was built. The fix adds one case that treats bare `dict` like `dict[str, ...]`
  and wraps bare `list` / `tuple` like their generic forms, with a regression test (fails before, passes
  after) and a docs note. The full SDK suite passes (6206 tests), plus pyright strict, ruff, and 100%
  coverage of the new lines. Following the SDK's contribution rules, we filed the issue first; the PR
  follows once a maintainer assigns it.
- **Why it matters:** we hit this building Encore. Our tools returned `-> dict`, and our client expected
  structured data that never came, with no error to explain why. Any MCP server written the natural way
  (`-> dict`) loses its structured results, and so does every MCP App or client that reads them.

## Demo video script (under 3:00, best part first)
- 0:00-0:20 Problem, then "Encore: a voice study coach for Alexa+"
- 0:20-1:00 Speak your notes, flashcards get created
- 1:00-2:00 Voice quiz: question, spoken answer, graded, "comes back tomorrow"
- 2:00-2:30 Next session: "How am I doing?" shows progress and schedule persisted
- 2:30-2:45 Same MCP server in another AI app (Claude Code): the FAQ calls this a bonus
- 2:45-3:00 Architecture in one shot (MCP server over Streamable HTTP, SQLite, Gemini), impact

## Checklist
- [x] Text description: features and how it works
- [ ] Repo public with MIT visible in About, or private and shared with testing@devpost.com + the Amazon team (see TASKS.md)
- [ ] Setup and run instructions work from a clean clone
- [ ] Simulator source is in the repo; MCP server (spec 2025-11-25, Streamable HTTP) shown running
- [ ] Demo video: YouTube or Vimeo, public, under 3 minutes, English, no copyrighted music
- [x] Product feedback for every tool used (see FEEDBACK.md)
- [x] Open Source: contribution URL, repo URL, GitHub username, what/how/why (section above)
- [x] Optional: feature requests and friction log
