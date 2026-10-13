# Encore

A voice study coach for Alexa+. Tell it what you studied, it builds flashcards, then
quizzes you by voice on a spaced schedule that it remembers across sessions.

Built for the Amazon Developer Hackathon (Alexa+ track). Design: [ARCHITECTURE.md](ARCHITECTURE.md).
Work split: [TASKS.md](TASKS.md). Workflow: [CONTRIBUTING.md](CONTRIBUTING.md).

## Run
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows; macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python tests/test_core.py        # unit tests, prints "ok"
python -m pytest tests/test_generate.py -v  # Bedrock card-gen tests (no AWS needed)
python tests/test_integration.py # starts the server, calls every tool over HTTP, prints "ok"
python server.py                 # MCP server at http://127.0.0.1:8000/mcp
```
`ENCORE_PORT` changes the port (default 8000).

Copy `.env.example` to `.env` and fill in AWS credentials for Bedrock.
The flashcard MCP App HTML is included in the repository. To rebuild it after
changing `mcp_apps/flashcards.ts`, use Node.js 20+:
```bash
npm ci
npm run build:mcp-app
```

Run the browser voice-flow tests after `npm ci`, with
`npx playwright install chromium` and `npm run test:e2e`.
Copy `.env.example` to `.env` and fill in AWS credentials.
`BEDROCK_MODEL_ID` defaults to `amazon.nova-lite-v1:0`; change it if needed.

No AWS access? Set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY` (free key from
[Google AI Studio](https://aistudio.google.com)) to use Gemini instead of Bedrock.
`LLM_PROVIDER=none` skips the LLM in card generation (cards come from `question? answer` lines); the web agent still needs bedrock or gemini.

## Layout
| Path | What |
|---|---|
| `server.py` | MCP server and tools |
| `db.py`, `srs.py` | Card storage and spaced repetition |
| `generate.py` | Notes to flashcards (Bedrock); chunking + retry |
| `ingest.py` | Extract text from PDF / VTT / SRT / plain-text files |
| `web/` | Simulated Alexa+ voice client |
| `mcp_apps/` | MCP Apps flashcard UI source and bundled resource |
| `docs/` | Submission notes, product feedback, friction log |

## License
MIT
