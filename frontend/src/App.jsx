import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { translate, getHealth, ApiError } from './api.js'

const LANGUAGES = { en: 'English', fr: 'Français', nko: 'N’Ko (Mandenka Kan)' }

// The four directions version 1 supports. Kept in sync with the backend.
const DIRECTIONS = [
  ['en', 'nko'],
  ['fr', 'nko'],
  ['nko', 'en'],
  ['nko', 'fr'],
]

const MAX_CHARS = 5000

const targetsFor = (source) => DIRECTIONS.filter(([s]) => s === source).map(([, t]) => t)
const sources = [...new Set(DIRECTIONS.map(([s]) => s))]

function LanguagePanelLabel({ code }) {
  return (
    <span className="lang-label">
      {LANGUAGES[code]}
      {code === 'nko' && <span className="rtl-hint">right-to-left</span>}
    </span>
  )
}

export default function App() {
  const [source, setSource] = useState('en')
  const [target, setTarget] = useState('nko')
  const [text, setText] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)
  const [health, setHealth] = useState(null)
  const abortRef = useRef(null)

  useEffect(() => {
    getHealth().then(setHealth)
  }, [])

  // Keep the pair valid whenever the source changes.
  useEffect(() => {
    const allowed = targetsFor(source)
    if (!allowed.includes(target)) setTarget(allowed[0])
  }, [source, target])

  const canSwap = useMemo(
    () => DIRECTIONS.some(([s, t]) => s === target && t === source),
    [source, target]
  )

  const reset = () => {
    setResult(null)
    setError(null)
    setCopied(false)
  }

  const onSwap = () => {
    if (!canSwap) return
    const nextText = result?.translation || ''
    setSource(target)
    setTarget(source)
    setText(nextText)
    reset()
  }

  const onClear = () => {
    setText('')
    reset()
  }

  const onSubmit = useCallback(
    async (e) => {
      e?.preventDefault()
      if (!text.trim() || loading) return
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      setLoading(true)
      reset()
      try {
        const data = await translate({
          sourceLanguage: source,
          targetLanguage: target,
          text,
          signal: controller.signal,
        })
        setResult(data)
      } catch (err) {
        if (err.name === 'AbortError') return
        setError(
          err instanceof ApiError
            ? { message: err.message, code: err.code }
            : { message: 'Something went wrong. Please try again.', code: 'unknown' }
        )
      } finally {
        setLoading(false)
      }
    },
    [text, source, target, loading]
  )

  const onCopy = async () => {
    if (!result?.translation) return
    try {
      await navigator.clipboard.writeText(result.translation)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setError({ message: 'Could not copy to the clipboard.', code: 'clipboard' })
    }
  }

  // Ctrl/Cmd+Enter submits, like most translator UIs.
  const onKeyDown = (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') onSubmit(e)
  }

  const overLimit = text.length > MAX_CHARS
  const setupNeeded = health && health.provider_configured === false

  return (
    <div className="page">
      <header className="header">
        <h1>N’Ko (Mandenka Kan) Translator</h1>
        <p className="tagline">
          AI-assisted translation between English, French and N’Ko (Mandenka Kan)
        </p>
      </header>

      {setupNeeded && (
        <div className="banner banner-setup" role="status">
          <strong>Setup needed.</strong> The translation provider is not configured.
          Add <code>ANTHROPIC_API_KEY</code> to <code>backend/.env</code> and restart
          the backend.
        </div>
      )}

      <form className="translator" onSubmit={onSubmit}>
        <div className="lang-bar">
          <label className="field">
            <span className="field-label">From</span>
            <select
              value={source}
              onChange={(e) => {
                setSource(e.target.value)
                reset()
              }}
            >
              {sources.map((code) => (
                <option key={code} value={code}>
                  {LANGUAGES[code]}
                </option>
              ))}
            </select>
          </label>

          <button
            type="button"
            className="swap"
            onClick={onSwap}
            disabled={!canSwap}
            title={canSwap ? 'Swap languages' : 'This pair cannot be reversed'}
            aria-label="Swap languages"
          >
            {'⇄'}
          </button>

          <label className="field">
            <span className="field-label">To</span>
            <select
              value={target}
              onChange={(e) => {
                setTarget(e.target.value)
                reset()
              }}
            >
              {targetsFor(source).map((code) => (
                <option key={code} value={code}>
                  {LANGUAGES[code]}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="panels">
          <section className="panel">
            <div className="panel-head">
              <LanguagePanelLabel code={source} />
              <span className={`counter ${overLimit ? 'counter-over' : ''}`}>
                {text.length.toLocaleString()} / {MAX_CHARS.toLocaleString()}
              </span>
            </div>
            <textarea
              className={`editor ${source === 'nko' ? 'nko' : ''}`}
              dir={source === 'nko' ? 'rtl' : 'ltr'}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={
                source === 'nko'
                  ? 'Enter N’Ko (Mandenka Kan) text…'
                  : 'Enter text to translate…'
              }
              spellCheck={source !== 'nko'}
              aria-label={`Text in ${LANGUAGES[source]}`}
            />
          </section>

          <section className="panel">
            <div className="panel-head">
              <LanguagePanelLabel code={target} />
              {result?.translation && (
                <button type="button" className="ghost" onClick={onCopy}>
                  {copied ? 'Copied' : 'Copy'}
                </button>
              )}
            </div>
            <div
              className={`editor output ${target === 'nko' ? 'nko' : ''}`}
              dir={target === 'nko' ? 'rtl' : 'ltr'}
              aria-live="polite"
              aria-busy={loading}
            >
              {loading ? (
                <span className="spinner-row" dir="ltr">
                  <span className="spinner" aria-hidden="true" />
                  Translating{'…'}
                </span>
              ) : result?.translation ? (
                result.translation
              ) : (
                <span className="placeholder" dir="ltr">
                  The translation will appear here.
                </span>
              )}
            </div>
          </section>
        </div>

        {error && (
          <div className="banner banner-error" role="alert">
            {error.message}
          </div>
        )}

        {result?.warnings?.length > 0 && (
          <div className="banner banner-warn" role="status">
            <ul>
              {result.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="actions">
          <button
            type="submit"
            className="primary"
            disabled={loading || !text.trim() || overLimit}
          >
            {loading ? 'Translating…' : 'Translate'}
          </button>
          <button
            type="button"
            className="secondary"
            onClick={onClear}
            disabled={loading || (!text && !result)}
          >
            Clear
          </button>
          <span className="hint">Ctrl + Enter</span>
        </div>
      </form>

      <footer className="footer">
        <p>
          AI-assisted translation. Results are{' '}
          <strong>not reviewed by a human N’Ko (Mandenka Kan) speaker</strong> and accuracy
          is not very much guaranteed.
        </p>
        {result?.model && (
          <p className="meta">
            {result.provider} {'·'} {result.model}{' '}
            {result.dictionary_used
              ? '· dictionary context used'
              : '· no dictionary context'}
          </p>
        )}
      </footer>
    </div>
  )
}
