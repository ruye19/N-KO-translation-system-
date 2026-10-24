# N'Ko Translator

AI-assisted translation between **English**, **French** and **N'Ko**.

A standalone application (FastAPI backend + React frontend) designed to be
integrated into the N'Ko Academy website later through a single HTTP endpoint.

> **Quality notice.** This is an AI-assisted translator, not a verified one.
> N'Ko is a lower-resource language and output is **not reviewed by a human
> N'Ko speaker**. Accuracy is not guaranteed and must be evaluated with real
> examples before the tool is presented to end users.

## Supported directions (version 1)

| From | To |
|---|---|
| English | N'Ko |
| French | N'Ko |
| N'Ko | English |
| N'Ko | French |

English ↔ French is intentionally **not** supported. Input covers words,
sentences, and short-to-medium paragraphs (5,000 characters by default).
Whole-document and whole-book translation are out of scope.

---

## Project layout

```
backend/            FastAPI service
  app/
    main.py         App entry point, CORS, error normalisation
    config.py       Environment configuration (no secret has a default)
    languages.py    Supported languages and the four directions
    errors.py       Error taxonomy -> HTTP status + machine-readable code
    schemas.py      Request/response models
    routers/        /api/health, /api/languages, /api/translate
    services/
      translation.py   Orchestration: validate -> prompt -> provider -> check
      prompt.py        Prompt construction
      nko_text.py      N'Ko / Private-Use-Area character handling
      dictionary.py    Dictionary interface (disabled - see below)
      providers/       Provider abstraction (base, anthropic, gemini, registry)
  tests/            Test suite
frontend/           React + Vite translator UI
docs/
  PROJECT_REQUIREMENTS.md
  TECHNICAL_PLAN.md
  TRANSLATION_SCOPE.md
  DICTIONARY.md
  DICTIONARY_ENCODING_INVESTIGATION.md   Why the dictionary is not yet wired in
  evidence/                              Rendered glyphs + extracted CMap
  dictionnaire Fr_nko.pdf                Source dictionary (unchanged, read-only)
```

---

## Setup (Windows)

Prerequisites: **Python 3.10+** and **Node.js 18+**.

### 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Open `backend\.env` and choose a provider, then set that provider's key.

**Google Gemini** (default):

```
TRANSLATION_PROVIDER=gemini
GEMINI_API_KEY=AIza...
```

Create a key at <https://aistudio.google.com/apikey>. It starts with `AIza`.
A token starting `AQ.` is a short-lived *ephemeral* token and will expire —
it is not a usable API key here.

**Anthropic Claude**:

```
TRANSLATION_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

Create a key at <https://console.anthropic.com/> → API keys. It starts with
`sk-ant-`. Note that a Claude Pro/Max subscription is **not** API access —
API usage is billed separately.

Only the selected provider's key is needed. The backend warns at startup if a
key does not match the expected format for the chosen provider.

Start the server:

```powershell
uvicorn app.main:app --reload --port 8000
```

- API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/api/health>

**The server starts whether or not a key is configured.** Without one it runs
normally and `/api/translate` returns a clear setup message (HTTP 503) instead
of crashing.

### 2. Frontend

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>.

To point the UI at a different backend, copy `frontend\.env.example` to
`frontend\.env` and set `VITE_API_BASE_URL`. Note that anything prefixed
`VITE_` is bundled into the browser build and is publicly readable — never put
a secret there.

---

## Configuration

All backend settings live in `backend/.env` (git-ignored). See
`backend/.env.example` for the full list.

| Variable | Default | Purpose |
|---|---|---|
| `TRANSLATION_PROVIDER` | `gemini` | `gemini` or `anthropic` |
| `GEMINI_API_KEY` | *(none)* | Google credential. **Server-side only.** |
| `GEMINI_MODEL` | `gemini-2.5-pro` | Model name, changeable without code edits |
| `GEMINI_MAX_TOKENS` | `4096` | Output length cap |
| `GEMINI_TEMPERATURE` | `0.2` | Low: translation should be faithful, not creative |
| `ANTHROPIC_API_KEY` | *(none)* | Anthropic credential. **Server-side only.** |
| `ANTHROPIC_MODEL` | `claude-opus-5` | Model name, changeable without code edits |
| `ANTHROPIC_MAX_TOKENS` | `4096` | Output length cap |
| `ANTHROPIC_EFFORT` | `medium` | How hard the model works: `low`…`max` |
| `REQUEST_TIMEOUT_SECONDS` | `60` | Provider timeout |
| `MAX_INPUT_CHARS` | `5000` | Input length limit |
| `DICTIONARY_ENABLED` | `false` | See *Dictionary status* below |
| `CORS_ORIGINS` | `http://localhost:5173,…` | Origins allowed to call the API |

### Security

- The API key is read from the environment on the server and is never sent to
  the browser, logged, or included in any API response or error message.
- `.env` is git-ignored; `.env.example` contains no real values.
- User-submitted text is not logged — only the direction and character count.

---

## API

### `GET /api/health`

```json
{
  "status": "ok",
  "provider": "gemini",
  "provider_configured": true,
  "model": "gemini-2.5-pro",
  "dictionary_enabled": false,
  "max_input_chars": 5000
}
```

### `GET /api/languages`

Returns the four supported directions, so a client never offers an invalid pair.

### `POST /api/translate`

Request:

```json
{
  "source_language": "en",
  "target_language": "nko",
  "text": "How are you?"
}
```

Language codes: `en`, `fr`, `nko`.

Success (`200`):

```json
{
  "translation": "…",
  "source_language": "en",
  "target_language": "nko",
  "provider": "gemini",
  "model": "gemini-2.5-pro",
  "dictionary_used": false,
  "human_verified": false,
  "notice": "AI-assisted translation. Not reviewed by a human N'Ko speaker; accuracy is not guaranteed.",
  "warnings": []
}
```

Errors always use the same shape:

```json
{ "error": { "code": "provider_not_configured", "message": "…" } }
```

| Status | Code | Meaning |
|---|---|---|
| 400 | `empty_text`, `text_too_long`, `unsupported_language`, `unsupported_direction`, `same_language` | Invalid request |
| 422 | `provider_refused` | The provider declined the text |
| 429 | `provider_rate_limited` | Provider rate limit |
| 500 | `internal_error` | Unexpected server error |
| 502 | `provider_auth_failed`, `provider_unavailable`, `empty_translation` | Provider problem |
| 503 | `provider_not_configured` | No API key configured |
| 504 | `provider_timeout` | Provider too slow |

### Examples

PowerShell:

```powershell
curl.exe -X POST http://localhost:8000/api/translate `
  -H "Content-Type: application/json" `
  -d '{\"source_language\":\"en\",\"target_language\":\"nko\",\"text\":\"How are you?\"}'
```

Python:

```python
import httpx

r = httpx.post("http://localhost:8000/api/translate", json={
    "source_language": "fr",
    "target_language": "nko",
    "text": "Comment allez-vous ?",
})
print(r.json()["translation"])
```

---

## Switching providers

Change one line in `backend/.env` and restart:

```
TRANSLATION_PROVIDER=gemini      # or: anthropic
```

Nothing else changes — same endpoint, same request and response shapes, same
frontend.

## Adding another AI provider

1. Implement `TranslationProvider` in
   `backend/app/services/providers/` (`is_configured`, `model_name`,
   `complete`). Raise the errors from `app/errors.py` — never a raw SDK
   exception.
2. Register it in `providers/registry.py`.
3. Select it with `TRANSLATION_PROVIDER=<name>`.

No other part of the application imports a vendor SDK.

---

## Dictionary status — pending encoding recovery

The project includes a 498-page French–N'Ko dictionary
(`dictionnaire Fr_nko.pdf`, Baba Mamadi Diané, 2014). **It is not yet wired
into translation, on purpose.**

The PDF's French text extracts cleanly, but its N'Ko is set in a legacy
embedded font (`N'ko2Manden-1saDofanen`) that maps characters into the
**Private Use Area** (`U+F120`–`U+F1E1`) rather than Unicode N'Ko
(`U+07C0`–`U+07FF`). The embedded font subset contains no `cmap` and no glyph
names, so no mapping can be derived from the file itself. A glyph-shape
matching experiment against two real Unicode N'Ko fonts produced **0 verified
and only 5 plausible mappings out of 90**.

Using that text today would silently corrupt translations, so:

- `DICTIONARY_ENABLED` defaults to `false`.
- `NullDictionaryService` returns no entries and never invents one.
- `dictionary_used` is `false` in every response, and says so honestly.
- Any Private Use Area characters in model output are stripped and flagged.

The interface (`DictionaryService` in `app/services/dictionary.py`) is in place
so a verified implementation — e.g. SQLite FTS5 over extracted entries — can be
dropped in without changing the API or the UI.

**Full findings, method, evidence, and the recommended unblock:
[`docs/DICTIONARY_ENCODING_INVESTIGATION.md`](docs/DICTIONARY_ENCODING_INVESTIGATION.md).**
The most direct fix is obtaining the original `N'ko2 Manden` font or its
keyboard/encoding chart, which would make the conversion deterministic.

---

## Tests

```powershell
cd backend
python -m pytest -q
```

Covers input validation, all four directions, unsupported directions, missing
credentials, provider failure mapping, response structure, Private-Use-Area
handling, and the health endpoint. Tests use a fake provider and make **no
network calls**, so they run without an API key.

---

## Deployment notes

- Backend start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Frontend build: `npm run build` → static files in `frontend/dist`
- Required server env var: `ANTHROPIC_API_KEY`
- Set `CORS_ORIGINS` to the deployed frontend origin
- Health check path: `/api/health`

## Integration with the N'Ko Academy website

The website only needs:

- the endpoint `POST /api/translate`
- the language codes `en`, `fr`, `nko`
- the request/response shapes documented above
- the deployed API origin added to `CORS_ORIGINS`

The frontend in this repository is a working reference implementation and a
testing interface; it does not need to be the final website UI.

## Known limitations

- Translation quality is unmeasured. No evaluation dataset exists yet; building
  one is the next step before this is shown to real users.
- English ↔ N'Ko has no dictionary support even once the dictionary is
  recovered, since the source is organised French → N'Ko.
- No authentication or rate limiting on the API yet — add both before exposing
  it publicly.
