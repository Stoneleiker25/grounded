# Grounded

## Run it

Requirements: Python 3.10+ and an Anthropic API key.

### Windows

```powershell
copy .env.example .env
notepad .env          # paste your key into GROUNDED_ANTHROPIC_API_KEY
.\start.ps1
```

### macOS / Linux

```bash
cp .env.example .env
$EDITOR .env          # paste your key into GROUNDED_ANTHROPIC_API_KEY
./start.sh
```

The startup scripts create the virtual environment, install dependencies, start the API and frontend, wait for the backend health check, and open the app. The app runs at `http://127.0.0.1:5173` and the API docs at `http://127.0.0.1:8000/docs`.

If ports are busy:

```powershell
.\start.ps1 -ApiPort 8001 -WebPort 5174
```

```bash
API_PORT=8001 WEB_PORT=5174 ./start.sh
```

### Tests

```powershell
.\start.ps1 -Test
```

```bash
./start.sh test
```

## Architecture

This is a local Python FastAPI backend with a lightweight frontend that generates briefings from notes, verifies each claim against the source text, and flags contradictions rather than silently resolving them. The application stores note snapshots and briefing data in SQLite so the provenance trail remains auditable.

## AI Tools Used

- Anthropic Claude / Claude Opus — primary code generation, implementation, debugging, and code editing.
- ChatGPT — independent verification, debugging, code review, and reasoning.
- Gemini — secondary AI support, visualizing the challenge requirements, and image-related support.
- VS Code + Copilot — coding assistance and implementation.
- Perplexity — independent sanity checks during debugging and root-cause investigation.

I intentionally did not rely on a single AI tool. I independently checked outputs and used different AI systems to verify behavior and catch incorrect assumptions.

## Three Key Decisions

### 1. How citations are proven
Every grounded claim must include a verbatim quote, and the server verifies that the quote exists in the cited note before the bullet can be marked as cited. The model's own label is never trusted.

### 2. What happens when notes disagree
Conflicting notes are surfaced as a contradiction with both sides shown; the app does not silently pick a winner.

### 3. What happens when notes are garbage / unsupported claims
The app avoids manufacturing unsupported bullets. The LLM can generate approximately 5–8 candidate bullets, but each claim is verified against the source notes. Unsupported claims are explicitly marked as invented rather than falsely cited.

### Development issue caught and fixed
During testing, I found a persistent 2-bullet issue. I traced the execution path instead of assuming the LLM was responsible and found that `groundedness_budget()` in `app/backend/analysis.py` was using character count as a hard proxy for how many grounded claims could be extracted.

A 139-character note with `chars_per_bullet = 65` resulted in:

`139 // 65 = 2`

That value was passed to the LLM before generation, artificially limiting the request to two bullets. Character count was a poor proxy for grounded claim density because a short note can contain several distinct, useful claims. I independently tested the same source with Perplexity without that application-level budget and confirmed that more claims could be extracted.

I removed the character-based restriction while keeping the grounding verification layer. The final live test produced 5 bullets, with supported claims cited and unsupported claims explicitly marked as invented.

I also encountered intermittent `401` errors during local testing. I independently traced those to stale Grounded processes running on different ports. After stopping the stale processes and restarting `start.ps1` cleanly, the normal local configuration worked correctly.

## Known Issues

- Quote verification is intentionally conservative: messy but valid quotes can be marked invented if the match is too loose.
- Contradiction detection is focused on numerical or measurement-based conflicts; qualitative disputes are not currently detected.
- This is a single-user local app; it does not include auth, multi-user collaboration, or production-scale deployment features.
