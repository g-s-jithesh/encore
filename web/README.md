# web/ (Teammate B)

Simulated Alexa+ client. See TASKS.md, section "Teammate B".

- `app.py`: agent loop. Connect to `http://127.0.0.1:8000/mcp` with an MCP client, list tools, call Bedrock Converse with those tools, run the tool calls, return the reply text.
- `index.html`: push-to-talk, Web Speech API for speech-to-text and text-to-speech, transcript view, text input fallback.
- `flashcards.html`: MCP App for browsing saved flashcards and revealing answers.

Run the MCP server and web host in separate terminals from the repository root:

```bash
python server.py
python -m web.app
```

Open `http://127.0.0.1:5000`. Configure AWS credentials and `BEDROCK_MODEL_ID`
through environment variables or `.env` before starting both processes.
Ask Encore to show your flashcards to open the interactive `ui://` app in an
MCP Apps-compatible host. The view loads the pinned Apps SDK from `esm.sh`.
