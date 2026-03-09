// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost, getServerUrl } from '../api/client'
import type { AppSettings, NtpStatus } from '../api/types'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { useToast } from '../context/ToastContext'
import { useAuth } from '../context/AuthContext'
import { useNavigate } from 'react-router-dom'

// ── Toggle component ──────────────────────────────────────────────────────────
function Toggle({
  value,
  onChange,
  disabled,
}: {
  value: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      onClick={() => onChange(!value)}
      disabled={disabled}
      className={`
        toggle-track w-11 h-6 flex-shrink-0
        ${value ? 'bg-primary' : 'bg-[#30363d]'}
        ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
      `}
    >
      <span className={`toggle-thumb ${value ? 'translate-x-5' : 'translate-x-0.5'}`} />
    </button>
  )
}

// ── Change password modal ─────────────────────────────────────────────────────
function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const { showToast } = useToast()
  const [current,  setCurrent]  = useState('')
  const [next,     setNext]     = useState('')
  const [confirm,  setConfirm]  = useState('')
  const [saving,   setSaving]   = useState(false)
  const [error,    setError]    = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!current) { setError('Enter current password'); return }
    if (next.length < 8) { setError('New password must be at least 8 characters'); return }
    if (next !== confirm) { setError('Passwords do not match'); return }

    setSaving(true)
    try {
      await apiPost('/api/auth/change-password', {
        current_password: current,
        new_password: next,
      })
      showToast('success', 'Password changed successfully')
      onClose()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to change password')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={e => e.stopPropagation()}>
        <div className="p-4 border-b border-border">
          <h3 className="font-semibold text-[#e6edf3]">Change Password</h3>
        </div>
        <form onSubmit={handleSubmit} className="p-4 space-y-3">
          <div>
            <label className="block text-sm font-medium text-[#e6edf3] mb-1.5">Current Password</label>
            <input
              type="password"
              value={current}
              onChange={e => setCurrent(e.target.value)}
              className="input-base"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-[#e6edf3] mb-1.5">New Password</label>
            <input
              type="password"
              value={next}
              onChange={e => setNext(e.target.value)}
              className="input-base"
              placeholder="At least 8 characters"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-[#e6edf3] mb-1.5">Confirm New Password</label>
            <input
              type="password"
              value={confirm}
              onChange={e => setConfirm(e.target.value)}
              className="input-base"
            />
          </div>

          {error && (
            <div className="bg-red-900/20 border border-red-800/40 rounded-lg px-3 py-2">
              <p className="text-danger text-sm">{error}</p>
            </div>
          )}

          <div className="flex gap-2 pt-1">
            <button type="button" onClick={onClose} className="btn-secondary flex-1">Cancel</button>
            <button type="submit" className="btn-primary flex-1" disabled={saving}>
              {saving ? <LoadingSpinner size={14} /> : 'Change Password'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Settings row ──────────────────────────────────────────────────────────────
function SettingRow({
  label,
  subtitle,
  right,
}: {
  label: string
  subtitle?: string
  right: React.ReactNode
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 px-4 min-h-[56px]">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-[#e6edf3]">{label}</p>
        {subtitle && <p className="text-xs text-muted mt-0.5">{subtitle}</p>}
      </div>
      <div className="flex-shrink-0">{right}</div>
    </div>
  )
}

// ── Section card ──────────────────────────────────────────────────────────────
function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs text-muted uppercase tracking-wide px-1 mb-2">{title}</p>
      <div className="bg-surface border border-border rounded-xl overflow-hidden divide-y divide-border">
        {children}
      </div>
    </div>
  )
}

// ── Main screen ───────────────────────────────────────────────────────────────
export function SettingsScreen() {
  const { showToast } = useToast()
  const { logout, serverUrl } = useAuth()
  const navigate = useNavigate()

  const [settings,     setSettings]     = useState<AppSettings | null>(null)
  const [ntpRunning,   setNtpRunning]   = useState<boolean | null>(null)
  const [loading,      setLoading]      = useState(true)
  const [togglingNtp,  setTogglingNtp]  = useState(false)
  const [togglingYt,   setTogglingYt]   = useState(false)
  const [togglingCap,  setTogglingCap]  = useState(false)
  const [showChangePw, setShowChangePw] = useState(false)

  const fetchAll = useCallback(async () => {
    try {
      const [cfg, ntp] = await Promise.allSettled([
        apiGet<AppSettings>('/api/settings'),
        apiGet<NtpStatus>('/api/ntp/status'),
      ])
      if (cfg.status === 'fulfilled') setSettings(cfg.value)
      if (ntp.status === 'fulfilled') setNtpRunning(ntp.value.running)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  async function toggleNtp(val: boolean) {
    setTogglingNtp(true)
    try {
      await apiPost('/api/ntp/enabled', { enabled: val })
      setNtpRunning(val)
      showToast('success', `NTP server ${val ? 'started' : 'stopped'}`)
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Failed to toggle NTP')
    } finally {
      setTogglingNtp(false)
    }
  }

  async function toggleYouTube(val: boolean) {
    if (!settings) return
    setTogglingYt(true)
    const next = { ...settings, youtube_redirect_enabled: val }
    try {
      await apiPost('/api/settings', {
        youtube_redirect_enabled: val,
        captive_portal_enabled: settings.captive_portal_enabled,
      })
      setSettings(next)
      showToast('success', `YouTube redirect ${val ? 'enabled' : 'disabled'}`)
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Failed to save settings')
    } finally {
      setTogglingYt(false)
    }
  }

  async function toggleCaptive(val: boolean) {
    if (!settings) return
    setTogglingCap(true)
    const next = { ...settings, captive_portal_enabled: val }
    try {
      await apiPost('/api/settings', {
        youtube_redirect_enabled: settings.youtube_redirect_enabled,
        captive_portal_enabled: val,
      })
      setSettings(next)
      showToast('success', `Captive portal ${val ? 'enabled' : 'disabled'}`)
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Failed to save settings')
    } finally {
      setTogglingCap(false)
    }
  }

  function handleDisconnect() {
    logout()
    navigate('/setup', { replace: true })
  }

  const serverHost = serverUrl
    ? (() => { try { return new URL(serverUrl).hostname } catch { return serverUrl } })()
    : 'Not connected'

  return (
    <div className="h-full scroll-area">
      <div className="p-4 space-y-5 max-w-lg mx-auto md:py-6">

        {/* Server card */}
        <SectionCard title="Server">
          <SettingRow
            label="Server"
            subtitle={serverHost || getServerUrl()}
            right={
              <span className="pill bg-green-900/40 text-green-300 text-xs">Connected</span>
            }
          />
        </SectionCard>

        {/* Toggles */}
        <SectionCard title="Features">
          <SettingRow
            label="NTP Server"
            subtitle="Serve time to local network devices"
            right={
              loading || ntpRunning === null
                ? <LoadingSpinner size={16} />
                : <Toggle value={ntpRunning} onChange={toggleNtp} disabled={togglingNtp} />
            }
          />
          <SettingRow
            label="YouTube Ad Filter"
            subtitle="Redirect YouTube through ad-stripping proxy"
            right={
              loading || !settings
                ? <LoadingSpinner size={16} />
                : <Toggle
                    value={settings.youtube_redirect_enabled}
                    onChange={toggleYouTube}
                    disabled={togglingYt}
                  />
            }
          />
          <SettingRow
            label="Captive Portal"
            subtitle="Show portal page for new devices"
            right={
              loading || !settings
                ? <LoadingSpinner size={16} />
                : <Toggle
                    value={settings.captive_portal_enabled}
                    onChange={toggleCaptive}
                    disabled={togglingCap}
                  />
            }
          />
        </SectionCard>

        {/* Account */}
        <SectionCard title="Account">
          <button
            onClick={() => setShowChangePw(true)}
            className="w-full flex items-center justify-between px-4 py-3 min-h-[56px] hover:bg-surface-hover transition-colors"
          >
            <span className="text-sm font-medium text-[#e6edf3]">Change Password</span>
            <svg className="w-4 h-4 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </SectionCard>

        {/* About */}
        <SectionCard title="About">
          <div className="px-4 py-4 space-y-1">
            <p className="text-sm font-semibold text-[#e6edf3]">RichSinkhole v1.0</p>
            <p className="text-xs text-muted">DNS Sinkhole & Network Protection</p>
            <div className="pt-2 space-y-0.5">
              <p className="text-xs text-muted">© 2026 DownStreamTech</p>
              <p className="text-xs text-muted">Developed by Richard R. Ayuyang, PhD</p>
              <p className="text-xs text-muted">Professor II, CSU</p>
            </div>
            <div className="pt-2 space-y-0.5">
              <p className="text-xs text-muted">Stack: FastAPI · SQLite · Unbound</p>
              <p className="text-xs text-muted">App: React · Electron · Capacitor</p>
            </div>
          </div>
        </SectionCard>

        {/* Disconnect */}
        <div className="pb-4">
          <button onClick={handleDisconnect} className="btn-danger w-full">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
            Disconnect from Server
          </button>
        </div>
      </div>

      {showChangePw && (
        <ChangePasswordModal onClose={() => setShowChangePw(false)} />
      )}
    </div>
  )
}
