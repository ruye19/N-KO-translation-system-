# N'Ko Translator API: integration guide

This guide is for developers connecting another website, such as Mansa's, to the N'Ko Translator backend. It reflects the code and the live tests of 2026-10-31.

> **Every translation is AI-generated and unverified.** No output of this API has been checked by a qualified N'Ko reviewer. Show the `notice` field with every result. See [What the result means](#3-what-the-result-means).

## 1. Endpoints

All paths are relative to the deployed API origin, for example `https://api.example.org`.

| Method | Path | Access key | Rate limited | Purpose |
|---|---|---|---|---|
| `POST` | `/api/translate` | **Required** | Yes | Translate text. **This is the endpoint Mansa's backend calls.** |
| `GET` | `/api/languages` | No | No | The supported directions, for building menus |
| `GET` | `/api/health` | No | No | Liveness and configuration status. It returns no secrets. |
| `GET` | `/docs`, `/openapi.json` | No | No | Interactive documentation, generated automatically |

### Supported languages

The language codes are `en` (English), `fr` (French) and `nko` (N'Ko, Unicode U+07C0–U+07FF). Codes are case-insensitive.

There are exactly four directions:

| From | To |
|---|---|
| `en` | `nko` |
| `fr` | `nko` |
| `nko` | `en` |
| `nko` | `fr` |

English ↔ French is deliberately not offered.

## 2. `POST /api/translate`

### Request

Headers:

```
Content-Type: application/json
Authorization: Bearer <TRANSLATOR_API_KEY>
```

Body:

```json
{
  "source_language": "fr",
  "target_language": "nko",
  "text": "Bonjour, comment allez-vous ?"
}
```

| Field | Type | Rules |
|---|---|---|
| `source_language` | string | Required. One of `en`, `fr`, `nko`. |
| `target_language` | string | Required. One of the four directions above. |
| `text` | string | Required. Must not be blank. At most `MAX_INPUT_CHARS` characters (default 5,000; `/api/health` reports the current limit). |

No other fields are read. The server checks the rate limit first, then the access key, then the body.

### Success response (`200`)

This shows the shape. The `translation` value is model output and differs from call to call. The access key and rate limit did not change this format.

```json
{
  "translation": "…N'Ko text…",
  "source_language": "fr",
  "target_language": "nko",
  "provider": "gemini",
  "model": "gemini-flash-lite-latest",
  "dictionary_used": false,
  "dictionary_entries_found": 0,
  "dictionary_nko_verified": false,
  "human_verified": false,
  "notice": "AI-assisted translation. Not reviewed by a human N'Ko speaker; accuracy is not guaranteed.",
  "warnings": []
}
```

| Field | Meaning |
|---|---|
| `translation` | AI-generated text. N'Ko output is plain Unicode N'Ko. Output with Private Use Area or legacy-font characters is rejected (see errors). |
| `provider`, `model` | The AI service and model that produced it. |
| `dictionary_used` | `true` only if French headwords from the dictionary were given to the model as background context. |
| `dictionary_entries_found` | How many dictionary headwords matched. A match is **not** a translation. |
| `dictionary_nko_verified` | `true` only if verified N'Ko from the dictionary reached the model. It is always `false` today (see section 3). |
| `human_verified` | Always `false`. Nothing is human-reviewed. |
| `notice` | A disclaimer to show with the result. |
| `warnings` | Advisory strings, for example "hit the output length limit" or "contains no N'Ko characters". Show them if present. |

### Error responses

Every error, including malformed JSON and unknown paths, has the same shape:

```json
{ "error": { "code": "text_too_long", "message": "Text is 5001 characters; the limit is 5000. Translate a shorter passage." } }
```

Branch on `code`. The `message` is written for people and may change.

| Status | `code` | Meaning | What the caller should do |
|---|---|---|---|
| 400 | `empty_text`, `text_too_long`, `unsupported_language`, `unsupported_direction`, `same_language` | Invalid input | Show the message and let the user fix the input |
| 401 | `unauthorized` | Missing, malformed or wrong access key. Also sends `WWW-Authenticate: Bearer`. | Fix the server configuration. Don't retry. |
| 404 | `not_found` | Wrong path | Fix the URL |
| 405 | `method_not_allowed` | Wrong HTTP method | Use `POST` |
| 422 | `invalid_request` | Malformed body: missing field, wrong type, or invalid JSON | Fix the client code |
| 422 | `provider_refused` | The AI provider declined the text | Show the message |
| 429 | `rate_limited` | **This API's** limit was exceeded. Sends a `Retry-After` header in seconds. | Wait `Retry-After` seconds, then retry. Tell the visitor to try again shortly. |
| 429 | `provider_rate_limited` | Gemini's own quota is exhausted, even after the server's retry | Retry later, with backoff |
| 500 | `internal_error`, `provider_unknown` | Server fault or misconfiguration | Report it to the API operator |
| 502 | `provider_unavailable` | The provider is overloaded or erroring, after the server's retry | Show "try again in a moment" |
| 502 | `provider_auth_failed` | The server's Gemini key was rejected | Report it to the API operator |
| 502 | `empty_translation`, `invalid_output_encoding` | Unusable model output was rejected | Retry once |
| 503 | `access_not_configured` | The server has no `TRANSLATOR_API_KEY` set | Report it to the API operator |
| 503 | `provider_not_configured` | No provider key on the server | Report it to the API operator |
| 504 | `provider_timeout` | The provider took longer than `REQUEST_TIMEOUT_SECONDS` | Retry once, or shorten the text |

Error messages never contain keys or provider internals. A 422 never echoes the request body. An unauthenticated caller gets `401` before the body is validated.

### Latency

Translations take seconds, not milliseconds. In testing on 2026-10-31:
- **`gemini-flash-lite-latest`:** 4–9 s.
- **`gemini-3.8-flash`:** up to 78 s, or failed (see section 7).

One server-side retry can add the retry delay (1–5 s) plus a second provider call. Give the request a client timeout a little above the server's `REQUEST_TIMEOUT_SECONDS` (default 60 s), show a loading state, and let the user cancel.

## 3. What the result means

The API mixes three very different kinds of information. Never present one as another.

| Kind | Where it appears | Status today |
|---|---|---|
| **AI-generated translation** | `translation` | Every result. Machine-produced, unreviewed, accuracy unknown. |
| **Dictionary entries found** | `dictionary_used`, `dictionary_entries_found` | A French headword exists in the French–N'Ko dictionary. The model gets only the headword, part of speech and page, never the dictionary's N'Ko. Off by default (`DICTIONARY_ENABLED=false`). |
| **Verified N'Ko** | `dictionary_nko_verified`, `human_verified` | **None exists.** 0 of the 32,057 dictionary entries are marked verified, so both fields are always `false`. |

The machine-decoded dictionary (decoder v1.2, `data/dictionary_decoded.sqlite`) is **not** connected to this API. Its N'Ko is machine-decoded and has not been checked by a qualified reviewer. Using it in translation is a separate, not-yet-approved step, and it would still be labelled unverified.

For a website, the safe wording is: "AI-assisted translation. Not reviewed by a human N'Ko speaker; accuracy is not guaranteed." Show it with every result, which is what `notice` provides. Don't call results "dictionary translations" or "verified".

## 4. Access key

### Generate a key

Use a long random value, at least 32 characters. The server warns at startup if a key is shorter. Either command works:

```
python -c "import secrets; print(secrets.token_urlsafe(32))"
openssl rand -base64 32
```

Generate it on your own machine, and send it to Mansa's developers over a secure channel, such as a password manager share. Don't use email or chat. Never commit it, and never paste it into a ticket or a frontend file.

### Configure the API server

Set it as an environment variable in the host's secret settings:

```
TRANSLATOR_API_KEY=<the generated key>
```

- **Rotation:** several keys may be listed, comma-separated: `TRANSLATOR_API_KEY=<new>,<old>`. Deploy with both, switch Mansa's backend to the new key, then remove the old one.
- **Fail-closed:** if no key is set, `/api/translate` refuses every request with `503 access_not_configured`. The server never silently runs open.
- **Comparison:** keys are compared in constant time, against SHA-256 digests. They are never logged or returned.

### Configure Mansa's backend

Mansa's backend stores the same value in its own secret settings, for example as `NKO_API_KEY`. It sends it on every request:

```
Authorization: Bearer <NKO_API_KEY>
```

The key must stay on Mansa's server. **Never put it in browser JavaScript, HTML, or a `VITE_`/`NEXT_PUBLIC_` variable.** Anything sent to a browser is public. CORS deliberately does not allow the `Authorization` header, so a browser can't send the key cross-origin anyway.

### Local development

The bundled React frontend calls the API directly from the browser, so it can't hold a key. For local work, put this in `backend/.env`:

```
REQUIRE_API_KEY=false
```

The server then logs a warning at startup. **Never set this in production.** To test the protected path locally instead, set `TRANSLATOR_API_KEY` and call the API with curl (section 9).

## 5. Rate limiting

| Setting | Default | Meaning |
|---|---|---|
| `RATE_LIMIT_REQUESTS` | `30` | Requests allowed per window, per client address. `0` disables the limit. |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Window length, as a sliding window |

- **Scope:** only `POST /api/translate` is limited. Requests that fail the key check count too, so key guessing is throttled.
- **Over the limit:** the API answers `429 rate_limited` with `Retry-After: <seconds>`, and does not call Gemini.
- **Why 30 a minute:** with server-to-server integration, every visitor's request arrives from Mansa's server address, so this is effectively **Mansa's total budget**: about one translation every 2 s. Raise it if Mansa's traffic needs more and your Gemini quota allows. Mansa's backend should also limit each visitor, for example 5 a minute, so one visitor can't use the whole budget.

### Behind a reverse proxy

The limiter uses the connection's client address (`request.client.host`). The app **never reads `X-Forwarded-For` itself**, because any caller can set that header.

- **Behind a proxy or load balancer** (nginx, Render, Fly, Railway, etc.), every request appears to come from the proxy, so all callers would share one bucket. Let uvicorn take the real address from the proxy's headers, and trust only that proxy:

  ```
  uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="<proxy IP or CIDR>"
  ```

  Use `--forwarded-allow-ips="*"` only if the app is unreachable except through the proxy, such as a private network. Otherwise a caller can spoof any address.
- **Direct exposure:** if the app is exposed directly, leave the proxy flags off.

### Multiple workers

The counters live in each process's memory:
- with `--workers 4`, the effective limit is 4× the setting;
- they reset when the server restarts.

That is acceptable for one instance with one worker. The endpoint is I/O-bound and one worker serves concurrent requests from a thread pool. If you scale to several workers or instances, move the counter to a shared store such as Redis, or apply the limit at the proxy or gateway. Redis isn't used now, because one worker is enough for the expected traffic and it avoids running another service.

## 6. Provider retry

A temporary Gemini failure is retried **at most once**:

| Situation | Retried? |
|---|---|
| Gemini `429`, `500`, `502` or `503` (for example "high demand") | Yes, once |
| Connection failed before reaching Google | Yes, once. The request never arrived, so it can't be a duplicate. |
| `401`/`403` (bad key), `400` (bad request), `404` (unknown model) | No: these are permanent |
| `504` or a timeout | No: it already used the full deadline, and retrying would double the wait |
| The failed attempt took more than half of `REQUEST_TIMEOUT_SECONDS` | No |
| Google asks for a wait (`Retry-After` header, or `RetryInfo` in a 429) longer than `PROVIDER_RETRY_MAX_DELAY_SECONDS` | No: the error is returned at once |

The wait before the retry is the provider's requested delay if given, and never less than `PROVIDER_RETRY_DELAY_SECONDS` (default 1 s). If the retry also fails, the caller gets the usual error code (`provider_unavailable`, `provider_rate_limited` …), with no provider details. Logs record only the status code.

| Setting | Default |
|---|---|
| `PROVIDER_MAX_RETRIES` | `1` (`0` disables it; higher values are capped at 1) |
| `PROVIDER_RETRY_DELAY_SECONDS` | `1.0` |
| `PROVIDER_RETRY_MAX_DELAY_SECONDS` | `5.0` |

**Callers:** Mansa's backend should **not** add its own automatic retries on `502`/`429`. The server has already retried, and stacked retries multiply load during an outage. Show the visitor a "try again" message instead.

The retry applies to the Gemini provider only. The Anthropic provider uses its SDK's built-in retry (up to 2 by default), which this change does not touch.

## 7. Calling the API from Mansa's backend

The visitor's browser calls a route on Mansa's own backend, which calls this API with the key. Here is an example route for Node 18+ / Express:

```js
// Environment on Mansa's server (never shipped to the browser):
//   NKO_API_BASE=https://translator-api.example.org
//   NKO_API_KEY=<the shared access key>
app.post("/translate", express.json({ limit: "32kb" }), async (req, res) => {
  const { source_language, target_language, text } = req.body ?? {};
  let upstream;
  try {
    upstream = await fetch(`${process.env.NKO_API_BASE}/api/translate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${process.env.NKO_API_KEY}`,
      },
      body: JSON.stringify({ source_language, target_language, text }),
      signal: AbortSignal.timeout(75_000),
    });
  } catch {
    return res.status(504).json({ error: { code: "network_error", message: "Translation service unreachable." } });
  }
  const body = await upstream.json().catch(() => null);
  if (upstream.status === 401 || (upstream.status === 503 && body?.error?.code === "access_not_configured")) {
    console.error("N'Ko API access problem:", body?.error?.code); // never log the key
    return res.status(502).json({ error: { code: "upstream_config", message: "Translation is temporarily unavailable." } });
  }
  const retryAfter = upstream.headers.get("retry-after");
  if (retryAfter) res.set("Retry-After", retryAfter);
  res.status(upstream.status).json(body ?? { error: { code: "bad_gateway", message: "Unexpected reply from the translation service." } });
});
```

The browser then calls Mansa's own `/translate` route, with no key:

```js
const res = await fetch("/translate", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ source_language: "fr", target_language: "nko", text: "Bonjour" }),
  signal: AbortSignal.timeout(80_000),
});
const body = await res.json();
if (res.ok) {
  // show body.translation, body.notice, and any body.warnings
} else {
  // body.error.code, e.g. "rate_limited" → "Please wait a moment and try again"
}
```

To render N'Ko, set `dir="rtl"` and `lang="nqo"` on the element, and use a font with N'Ko coverage, such as Noto Sans NKo or Ebrima on Windows.

## 8. Security summary

The API already does the following:
- **Access key:** `/api/translate` requires a shared key, checked in constant time. It fails closed if no key is configured.
- **Rate limit:** per client address, applied before the key check and before any Gemini call.
- **Server-side secrets:** provider keys and the access key live only in server environment variables. They are never in responses, errors or logs, and never in frontend code.
- **Narrow CORS:** only the listed origins (no `*`), with no credentials, and only `GET`/`POST`/`OPTIONS` with `Content-Type`.
- **Validated input:** language, direction, blank text and length are checked.
- **No request text in logs:** only the direction and character count are logged.
- **Bounded provider retry:** at most one.

The remaining limits:
- The rate limit is per process and in memory (section 5).
- There is no cap on request body size before the text-length check. Put a body-size limit on the reverse proxy, for example nginx `client_max_body_size 64k`.
- `/docs`, `/openapi.json` and `/api/health` are public. Health reveals the provider and model name, but no secrets.
- There is no per-day spending cap. Set a budget alert or quota in the Google Cloud console.

## 9. Deployment and configuration

Run from `backend/`:

```
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
```

Add `--proxy-headers --forwarded-allow-ips=...` behind a proxy (section 5). The health check path is `/api/health`.

The server reads its settings from environment variables, or from `backend/.env` locally. That file is git-ignored; never commit it.

| Variable | Default | Notes |
|---|---|---|
| `TRANSLATOR_API_KEY` | *(none)* | **Required in production.** The shared access key or keys, comma-separated. Secret. |
| `REQUIRE_API_KEY` | `true` | `false` only for local development |
| `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW_SECONDS` | `30`, `60` | Per client address, per worker |
| `PROVIDER_MAX_RETRIES` | `1` | `0` or `1` |
| `PROVIDER_RETRY_DELAY_SECONDS`, `PROVIDER_RETRY_MAX_DELAY_SECONDS` | `1.0`, `5.0` | |
| `TRANSLATION_PROVIDER` | `anthropic` | `gemini` or `anthropic`. The current local setup uses `gemini`. |
| `GEMINI_API_KEY` | *(none)* | Required for `gemini`. Secret. |
| `GEMINI_MODEL` | `gemini-3.8-flash` | See the reliability note below |
| `GEMINI_MAX_TOKENS`, `GEMINI_TEMPERATURE` | `4096`, `0.2` | |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_EFFORT` | *(none)*, `claude-opus-5`, `medium` | Used only when `TRANSLATION_PROVIDER=anthropic` |
| `REQUEST_TIMEOUT_SECONDS` | `60` | Provider deadline. Clients should wait a little longer. |
| `MAX_INPUT_CHARS` | `5000` | |
| `CORS_ORIGINS` | the local Vite dev server | Comma-separated. Only matters for browser calls. Server-to-server calls don't need Mansa's origin here. |
| `DICTIONARY_ENABLED`, `DICTIONARY_DB_PATH` | `false`, *(auto)* | Optional French headword context. Gives the model no N'Ko. |

### Testing locally

From `backend/`, in PowerShell:

```powershell
$env:TRANSLATOR_API_KEY = py -c "import secrets; print(secrets.token_urlsafe(32))"
$env:GEMINI_MODEL = "gemini-flash-lite-latest"   # optional per-process override
py -m uvicorn app.main:app --port 8000
```

In a second PowerShell window, use the same key value. curl.exe ships with Windows:

```powershell
$body = '{"source_language":"fr","target_language":"nko","text":"Bonjour"}'
curl.exe -i -X POST http://localhost:8000/api/translate -H "Content-Type: application/json" -d $body                       # 401
curl.exe -i -X POST http://localhost:8000/api/translate -H "Content-Type: application/json" -H "Authorization: Bearer $env:TRANSLATOR_API_KEY" -d $body   # 200
```

### Provider status found on 2026-10-31

- **Credentials:** the configured Gemini credential is accepted by Google. It starts with `AQ.` rather than `AIza`, and the app logs a startup warning that such tokens may be short-lived. Confirm with Google AI Studio whether it is a long-lived API key before deploying.
- **The configured model is unreliable.** `gemini-3.8-flash` exists for this key but was overloaded during testing. Results were: a `504` at the 60 s deadline, one success after 78 s on a trivial prompt, and several immediate `503 UNAVAILABLE: high demand`. The single retry helps only with brief 503s, not with sustained overload.
- **A lighter model worked.** `gemini-flash-lite-latest` answered all four test directions in 4–9 s, with one transient 503. Its translation quality has **not** been evaluated.
- **Unavailable model.** `gemini-2.5-flash` returns 404 "no longer available to new users".

Before integration, choose a model for reliability and quality, and set `GEMINI_MODEL` in the server environment.

### Production checklist

- [ ] Deploy the API over HTTPS.
- [ ] Generate `TRANSLATOR_API_KEY` and set it in the host's secret store. Give it to Mansa's developers over a secure channel.
- [ ] Make sure `REQUIRE_API_KEY` is **not** set to `false`.
- [ ] Set the Gemini key in the host's secret store. Confirm it is a long-lived `AIza…` key.
- [ ] Choose and set `GEMINI_MODEL`, and re-test.
- [ ] Run one worker, or use a shared rate-limit store. Set `--forwarded-allow-ips` to the proxy only.
- [ ] Limit request body size at the proxy.
- [ ] Set a Google Cloud budget alert.
- [ ] Have Mansa's backend send the key, rate-limit each visitor, and add no automatic retries.
- [ ] Decide whether `/docs` should stay public.
- [ ] Show `notice` and `warnings` with every result.
