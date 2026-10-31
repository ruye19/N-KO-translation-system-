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
      dictionary.py    SQLite lookup: French headwords only (see below)
      nko_mapping.py   Legacy-font mapping; digits recovered, letters blocked
      providers/       Provider abstraction (base, anthropic, gemini, registry)
  tests/            Test suite
frontend/           React + Vite translator UI
docs/
  PROJECT_REQUIREMENTS.md
  TECHNICAL_PLAN.md
  TRANSLATION_SCOPE.md
  DICTIONARY.md
  DICTIONARY_ENCODING_INVESTIGATION.md   Legacy font analysis; what is still blocked
  DICTIONARY_INTEGRATION_REPORT.md       Extraction metrics, schema, and audit (§7)
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

`POST /api/translate` requires an access key (`TRANSLATOR_API_KEY`, sent as
`Authorization: Bearer <key>`). The bundled browser frontend cannot hold a
secret, so for local development add this to `backend\.env`:

```
REQUIRE_API_KEY=false
```

Never set that in production. See
[docs/API_INTEGRATION.md](docs/API_INTEGRATION.md#4-access-key).

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
| `GEMINI_MODEL` | `gemini-3.8-flash` | Model name, changeable without code edits |
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
| `TRANSLATOR_API_KEY` | *(none)* | Access key(s) for `/api/translate`, comma-separated. **Secret.** |
| `REQUIRE_API_KEY` | `true` | `false` only for local development; with `true` and no key, translation is refused |
| `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` | `30` / `60` | Per client address, per worker process; `0` disables |
| `PROVIDER_MAX_RETRIES` | `1` | One retry of a temporary Gemini failure; `0` disables |
| `PROVIDER_RETRY_DELAY_SECONDS` / `PROVIDER_RETRY_MAX_DELAY_SECONDS` | `1.0` / `5.0` | Retry wait, and the longest provider-requested wait that is still honoured |

### Security

- The API key is read from the environment on the server and is never sent to
  the browser, logged, or included in any API response or error message.
- `.env` is git-ignored; `.env.example` contains no real values.
- User-submitted text is not logged — only the direction and character count.
- `/api/translate` requires `Authorization: Bearer <TRANSLATOR_API_KEY>`,
  compared in constant time, and fails closed when no key is configured.
- `/api/translate` is rate limited per client address (in memory; see the
  integration guide for proxies and multiple workers).

---

## API

### `GET /api/health`

```json
{
  "status": "ok",
  "provider": "gemini",
  "provider_configured": true,
  "model": "gemini-3.8-flash",
  "dictionary_enabled": false,
  "max_input_chars": 5000
}
```

### `GET /api/languages`

Returns the four supported directions, so a client never offers an invalid pair.

### `POST /api/translate`

Request (header `Authorization: Bearer <TRANSLATOR_API_KEY>` required):

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
  "model": "gemini-3.8-flash",
  "dictionary_used": false,
  "dictionary_entries_found": 0,
  "dictionary_nko_verified": false,
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
| 401 | `unauthorized` | Missing or invalid access key |
| 404 / 405 | `not_found` / `method_not_allowed` | Wrong path or HTTP method |
| 422 | `invalid_request` | Malformed body: missing field, wrong type or invalid JSON. The input is not echoed back. |
| 422 | `provider_refused` | The provider declined the text |
| 429 | `rate_limited` | This API's rate limit; see the `Retry-After` header |
| 429 | `provider_rate_limited` | Provider rate limit (after one retry) |
| 500 | `internal_error` | Unexpected server error |
| 502 | `provider_auth_failed`, `provider_unavailable`, `empty_translation` | Provider problem |
| 502 | `invalid_output_encoding` | Output contained Private Use Area characters and was rejected rather than silently stripped |
| 503 | `access_not_configured` | No `TRANSLATOR_API_KEY` on the server |
| 503 | `provider_not_configured` | No API key configured |
| 504 | `provider_timeout` | Provider too slow |

### Examples

PowerShell:

```powershell
curl.exe -X POST http://localhost:8000/api/translate `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer $env:TRANSLATOR_API_KEY" `
  -d '{\"source_language\":\"en\",\"target_language\":\"nko\",\"text\":\"How are you?\"}'
```

Python:

```python
import os

import httpx

r = httpx.post("http://localhost:8000/api/translate", json={
    "source_language": "fr",
    "target_language": "nko",
    "text": "Comment allez-vous ?",
}, headers={"Authorization": f"Bearer {os.environ['TRANSLATOR_API_KEY']}"}, timeout=75)
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

## Dictionary integration & pipeline

The project includes a 498-page French–N'Ko dictionary (`dictionnaire Fr_nko.pdf`, Baba Mamadi Diané, 2014).

### Extraction Pipeline & SQLite Store
An extraction pipeline is implemented in [`scripts/extract_dictionary.py`](scripts/extract_dictionary.py):
- Extracts **32,057 entries** (29,526 distinct French headwords, parts of speech, and page references) across 477 pages into `data/dictionary.sqlite`.
- To re-run extraction:
  ```powershell
  python scripts/extract_dictionary.py
  ```

### What the dictionary does and does not give you

The five states below are deliberately kept distinct, because they are easy to
conflate:

| # | State | Count |
|---|---|---|
| 1 | Entries extracted from the PDF | **32,057** |
| 2 | Searchable French headwords (normalised) | **29,526** |
| 3 | Entries whose N'Ko side is raw, undecoded legacy text | **32,057** |
| 4 | Entries with verified Unicode N'Ko | **0** |
| 5 | Entries reviewed by a knowledgeable N'Ko speaker | **0** |

**Lookup is usable today for 1–2 only.** The PDF's N'Ko body text is set in a
legacy pre-Unicode font (`N'ko2Manden-1saDofanen`) whose glyphs land in the
Private Use Area (`U+F120`–`U+F1E1`), so states 3–5 remain blocked.

- With `DICTIONARY_ENABLED=true` and `data/dictionary.sqlite` present, a lookup
  returns the **French headword, its part of speech and its page number**.
- It returns **no N'Ko**. Every entry is stored `is_verified = 0` with an empty
  `verified_nko`; the undecoded text is preserved in `raw_target` for future
  decoding and never leaves the service.
- The prompt labels each entry `N'Ko script undecoded - do not treat as N'Ko`
  and instructs the model not to reconstruct N'Ko from it.
- `dictionary_used: true` means **reference context was added** — a French
  headword matched. It does *not* mean a N'Ko translation was supplied. The
  response also returns `dictionary_entries_found` and
  `dictionary_nko_verified` (always `false` today).
- One mapping *has* been recovered from the legacy encoding: the **digits**
  (`U+0660`–`U+0669` → `U+07C0`–`U+07C9`), confirmed by glyph-shape evidence.
  Verify it yourself with `python scripts/verify_glyph_mappings.py`.
- For complete technical details, see:
  - [`docs/DICTIONARY_ENCODING_INVESTIGATION.md`](docs/DICTIONARY_ENCODING_INVESTIGATION.md): Detailed font analysis and why PUA cannot be blindly converted.
  - [`docs/DICTIONARY_INTEGRATION_REPORT.md`](docs/DICTIONARY_INTEGRATION_REPORT.md): Full extraction metrics, architecture, database schema, and test report.

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

- Backend start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`
  (behind a reverse proxy add `--proxy-headers --forwarded-allow-ips=<proxy IP>`)
- Required server env var: `TRANSLATOR_API_KEY` (and leave `REQUIRE_API_KEY` unset or `true`)
- Frontend build: `npm run build` → static files in `frontend/dist`
- Required server env var: the selected provider's key (`GEMINI_API_KEY` for
  `TRANSLATION_PROVIDER=gemini`, `ANTHROPIC_API_KEY` for `anthropic`)
- Set `CORS_ORIGINS` to the deployed frontend origin
- Health check path: `/api/health`

## Integration with the N'Ko Academy website

The website only needs:

- the endpoint `POST /api/translate`
- the language codes `en`, `fr`, `nko`
- the request/response shapes documented above
- a server-to-server call from the website's backend, sending
  `Authorization: Bearer <TRANSLATOR_API_KEY>` (the key never goes to the browser)

See [docs/API_INTEGRATION.md](docs/API_INTEGRATION.md) for the full integration
guide: the access key, rate limits, retry behaviour, fetch examples, the error
table, and the provider status found in testing.

The frontend in this repository is a working reference implementation and a
testing interface; it does not need to be the final website UI.

## Known limitations

- Translation quality is unmeasured. No evaluation dataset exists yet; building
  one is the next step before this is shown to real users.
- English ↔ N'Ko has no dictionary support even once the dictionary is
  recovered, since the source is organised French → N'Ko.
- The rate limit is kept in memory per worker process; scaling to several
  workers or instances needs a shared store (e.g. Redis) or a gateway limit.
