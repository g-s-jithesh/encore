# Tasks and split

Deadline: **Oct 23, 2026, 12:00 pm PT** (Oct 24, 12:30 am IST). Feature freeze **Oct 20**, then demo and submission only.

**2026-10-17: Bedrock dropped.** Our AWS account was never cleared for Bedrock, so the model is Gemini (free tier) and the
only mini challenge is **Open Source**. The Bedrock code path stays (`LLM_PROVIDER=bedrock`), covered by mocked tests.
Create one GitHub Issue per item below, labelled `core`, `gen` or `web`. One PR per issue.

Issues: https://github.com/g-s-jithesh/encore/issues

## Core, 40% (Jithesh, @g-s-jithesh): MCP server, state, integration
- [x] Scaffold: `srs.py`, `db.py`, `server.py`, `tests/test_core.py`
- [x] Input validation and error messages that sound right when spoken
- [x] `list_materials` / `delete_material` tools
- [x] Integration test: an MCP client calls every tool against the running server
- [ ] Review and merge PRs, keep `main` green
- [ ] Own the Devpost submission form and the repo settings (make public with MIT: **overdue, was Oct 16**)
- [x] Open Source mini challenge: MCP Python SDK fix + issue #3725 (see `docs/SUBMISSION.md`)

## Mano (@Mkkumar2006), 30%: AI generation
- [x] `generate.make_cards`, JSON output, 5-10 cards per input (Gemini by default; Bedrock path with mocked tests)
- [x] Long input (chunking) and malformed model output (retry once, then fall back)
- [x] Unit test with a mocked Bedrock client
- [x] AWS/Bedrock rows in `docs/FEEDBACK.md`
- [ ] Stretch: import a PDF or transcript file into `add_material` (`ingest.py` extracts the text; not wired into a tool yet)

## Bee (@abinaya-mani-11), 30%: Alexa+ simulator + demo
- [x] `web/app.py`: agent loop. List tools from the MCP server, call the model with tool use, run tool calls through an MCP client
- [x] `web/index.html`: voice UI (Web Speech API speech-to-text and text-to-speech), Alexa-style look, text fallback
- [x] End-to-end by voice: add notes, quiz, grade, progress (browser tests with simulated speech; live run with Gemini verified 2026-10-17)
- [ ] Record the demo video using the script in `docs/SUBMISSION.md`
- [x] Stretch: MCP App flashcard view (`ui://` resource) using the MCP Python SDK Apps extension

## Everyone
- [x] Log friction in `docs/FEEDBACK.md` (up to +10% judging bonus); keep adding until submission
- [ ] Test the README run steps from a clean clone before submitting

## Private-repo collaborators (add at submission time, invites expire in 7 days)
chris-trag, knmeiss, giolaq, anishamalde, mosesroth, emersonsklar, plus share with testing@devpost.com
