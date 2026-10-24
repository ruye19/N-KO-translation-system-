const BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '')

/** Error carrying the backend's machine-readable code. */
export class ApiError extends Error {
  constructor(message, code) {
    super(message)
    this.code = code
  }
}

async function parseError(response) {
  let code = 'http_error'
  let message = `Request failed (${response.status}).`
  try {
    const body = await response.json()
    if (body?.error?.message) {
      message = body.error.message
      code = body.error.code || code
    } else if (Array.isArray(body?.detail) && body.detail.length) {
      // FastAPI schema-validation shape.
      message = 'The request was missing a required field.'
      code = 'invalid_request'
    }
  } catch {
    /* non-JSON body; keep the generic message */
  }
  return new ApiError(message, code)
}

export async function translate({ sourceLanguage, targetLanguage, text, signal }) {
  let response
  try {
    response = await fetch(`${BASE_URL}/api/translate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_language: sourceLanguage,
        target_language: targetLanguage,
        text,
      }),
      signal,
    })
  } catch (err) {
    if (err.name === 'AbortError') throw err
    throw new ApiError(
      `Could not reach the translation server at ${BASE_URL}. Is the backend running?`,
      'network_error'
    )
  }
  if (!response.ok) throw await parseError(response)
  return response.json()
}

export async function getHealth() {
  try {
    const r = await fetch(`${BASE_URL}/api/health`)
    if (!r.ok) return null
    return await r.json()
  } catch {
    return null
  }
}
