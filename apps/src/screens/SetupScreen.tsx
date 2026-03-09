// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, ApiError } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { LoadingSpinner } from '../components/LoadingSpinner'

type Protocol = 'http' | 'https'

function buildUrl(proto: Protocol, host: string): string {
  return `${proto}://${host.trim()}/richsinkhole`
}

function classifyError(err: unknown, url: string): string {
  if (err instanceof ApiError) {
    if (err.status === 401 || err.status === 403) return 'Incorrect password.'
    if (err.status === 404) return `Endpoint not found at ${url} — make sure the dashboard is updated to the latest version.`
    if (err.status >= 500) return `Server error (${err.status}). The dashboard may be starting up — try again in a moment.`
    return err.detail || `Connection failed (${err.status})`
  }
  return 'Cannot reach the server. Check the IP address and make sure you\'re on the same network.'
}

export function SetupScreen() {
  const navigate        = useNavigate()
  const { refreshAuth } = useAuth()

  const [proto,    setProto]    = useState<Protocol>('http')
  const [host,     setHost]     = useState('')
  const [password, setPassword] = useState('')
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState('')

  const trimmedHost = host.trim().replace(/^https?:\/\//, '').replace(/\/.*$/, '')
  const previewUrl  = trimmedHost ? buildUrl(proto, trimmedHost) : null

  async function handleConnect(e: React.FormEvent) {
    e.preventDefault()
    setError('')

    if (!trimmedHost) { setError('Enter the server IP address'); return }
    if (!password)    { setError('Enter your admin password');   return }

    const url = buildUrl(proto, trimmedHost)
    setLoading(true)
    try {
      await login(url, password)
      refreshAuth()
      navigate('/dashboard', { replace: true })
    } catch (err) {
      setError(classifyError(err, url))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-full flex items-center justify-center bg-bg px-4 py-8">
      <div className="w-full max-w-[400px] animate-slide-up">

        {/* ── Logo ── */}
        <div className="flex flex-col items-center mb-10">
          <div className="relative mb-5">
            <div className="absolute inset-0 rounded-full blur-2xl opacity-25"
                 style={{ background: 'radial-gradient(circle, #58a6ff 0%, transparent 70%)' }} />
            <svg width="80" height="80" viewBox="0 0 80 80" fill="none"
                 xmlns="http://www.w3.org/2000/svg" className="relative">
              <circle cx="40" cy="40" r="38" fill="#0d1117" />
              <circle cx="40" cy="40" r="34" stroke="#58a6ff" strokeWidth="2"   fill="none" />
              <circle cx="40" cy="40" r="23" stroke="#58a6ff" strokeWidth="2"   fill="none" opacity="0.7" />
              <circle cx="40" cy="40" r="13" stroke="#79c0ff" strokeWidth="1.5" fill="none" opacity="0.5" />
              <circle cx="40" cy="40" r="4"  fill="#cae8ff" />
            </svg>
          </div>
          <h1 className="text-[#e6edf3] text-3xl font-bold tracking-tight">RichSinkhole</h1>
          <p className="text-muted text-sm mt-1.5">DNS Sinkhole Manager</p>
        </div>

        {/* ── Form card ── */}
        <div className="bg-surface border border-border rounded-2xl p-6 shadow-2xl">
          <form onSubmit={handleConnect} className="space-y-5">

            {/* Protocol + IP row */}
            <div>
              <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-2">
                Server
              </label>
              <div className="flex gap-2">
                {/* Protocol toggle */}
                <div className="flex rounded-lg border border-border overflow-hidden flex-shrink-0">
                  {(['http', 'https'] as Protocol[]).map(p => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => setProto(p)}
                      className={`px-3 py-2.5 text-sm font-medium transition-colors ${
                        proto === p
                          ? 'bg-[#58a6ff] text-[#0d1117]'
                          : 'bg-[#0d1117] text-muted hover:text-[#e6edf3]'
                      }`}
                    >
                      {p}
                    </button>
                  ))}
                </div>

                {/* IP / hostname */}
                <input
                  type="text"
                  value={host}
                  onChange={e => { setHost(e.target.value); setError('') }}
                  placeholder="10.254.254.4"
                  className="input-base flex-1 font-mono text-sm"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  inputMode="url"
                  disabled={loading}
                />
              </div>

              {/* URL preview */}
              <div className="mt-2 flex items-center gap-1.5">
                <span className="text-[11px] text-muted">Will connect to:</span>
                <code className="text-[11px] text-[#58a6ff] truncate">
                  {previewUrl ?? `${proto}://<ip>/richsinkhole`}
                </code>
              </div>
            </div>

            {/* Password */}
            <div>
              <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-2">
                Admin Password
              </label>
              <input
                type="password"
                value={password}
                onChange={e => { setPassword(e.target.value); setError('') }}
                placeholder="Your admin password"
                className="input-base"
                autoComplete="current-password"
                disabled={loading}
              />
            </div>

            {/* Error */}
            {error && (
              <div className="bg-red-950/40 border border-red-800/50 rounded-xl px-3.5 py-3">
                <p className="text-danger text-sm">{error}</p>
              </div>
            )}

            {/* Submit */}
            <button
              type="submit"
              className="btn-primary"
              disabled={loading || !trimmedHost}
            >
              {loading
                ? <><LoadingSpinner size={16} /> Connecting…</>
                : 'Connect to Server'
              }
            </button>
          </form>
        </div>

        {/* Footer */}
        <p className="text-muted text-xs text-center mt-5 leading-relaxed">
          First time? Use the password you set during initial dashboard setup.
        </p>
        <p className="text-[11px] text-muted/50 text-center mt-1">© 2026 DownStreamTech</p>
      </div>
    </div>
  )
}
