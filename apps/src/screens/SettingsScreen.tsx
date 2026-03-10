// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost, getServerUrl } from '../api/client'
import type { AppSettings, NtpStatus, ServicesStatus, UpdateSchedule } from '../api/types'
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

  const [settings,      setSettings]     = useState<AppSettings | null>(null)
  const [ntpRunning,    setNtpRunning]   = useState<boolean | null>(null)
  const [services,      setServices]     = useState<ServicesStatus | null>(null)
  const [schedule,      setSchedule]     = useState<UpdateSchedule>({ update_hour: 3, update_minute: 0, update_frequency: 'daily', update_day_of_week: 0, update_day_of_month: 1 })
  const [savingSched,   setSavingSched]  = useState(false)
  const [restarting,    setRestarting]   = useState<string | null>(null)
  const [loading,       setLoading]      = useState(true)
  const [togglingNtp,   setTogglingNtp]  = useState(false)
  const [togglingYt,    setTogglingYt]   = useState(false)
  const [togglingCap,   setTogglingCap]  = useState(false)
  const [showChangePw,  setShowChangePw] = useState(false)

  const fetchAll = useCallback(async () => {
    try {
      const [cfg, ntp, svc, sched] = await Promise.allSettled([
        apiGet<AppSettings>('/api/settings'),
        apiGet<NtpStatus>('/api/ntp/status'),
        apiGet<ServicesStatus>('/api/services/status'),
        apiGet<UpdateSchedule>('/api/settings/update-schedule'),
      ])
      if (cfg.status === 'fulfilled') setSettings(cfg.value)
      if (ntp.status === 'fulfilled') setNtpRunning(ntp.value.running)
      if (svc.status === 'fulfilled') setServices(svc.value)
      if (sched.status === 'fulfilled') setSchedule(sched.value)
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

  const DAYS = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']

  function scheduleLabel(s: UpdateSchedule): string {
    const t = `${String(s.update_hour).padStart(2,'0')}:${String(s.update_minute).padStart(2,'0')}`
    if (s.update_frequency === 'weekly')  return `Every ${DAYS[s.update_day_of_week]} at ${t}`
    if (s.update_frequency === 'monthly') return `Day ${s.update_day_of_month} of every month at ${t}`
    return `Daily at ${t}`
  }

  async function saveSchedule() {
    setSavingSched(true)
    try {
      await apiPost('/api/settings/update-schedule', schedule)
      showToast('success', `Schedule saved: ${scheduleLabel(schedule)}`)
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Failed to save schedule')
    } finally {
      setSavingSched(false)
    }
  }

  async function restartService(name: string) {
    setRestarting(name)
    try {
      await apiPost(`/api/services/restart/${name}`)
      showToast('success', `${name} restarted`)
      // Refresh status after a delay (nginx needs more time)
      setTimeout(async () => {
        try {
          const svc = await apiGet<ServicesStatus>('/api/services/status')
          setServices(svc)
        } catch { /* silent */ }
        setRestarting(null)
      }, name === 'nginx' ? 4000 : 2000)
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : `Failed to restart ${name}`)
      setRestarting(null)
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

        {/* Service Controls */}
        <SectionCard title="Service Controls">
          {(['dns', 'unbound', 'nginx'] as const).map(svc => {
            const info = services?.[svc]
            const labels: Record<string, [string, string]> = {
              dns:     ['DNS Server',  'Port 53 · Blocklist enforcement'],
              unbound: ['Unbound',     'Upstream resolver · DNSSEC'],
              nginx:   ['Nginx',       'Port 80/443 · Reverse proxy'],
            }
            const [label, sub] = labels[svc]
            return (
              <div key={svc} className="flex items-center justify-between gap-3 px-4 py-3 min-h-[56px]">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-[#e6edf3]">{label}</p>
                    {info && (
                      <span className={`pill text-xs ${info.running ? 'bg-green-900/40 text-green-300' : 'bg-red-900/40 text-red-300'}`}>
                        {info.status || (info.running ? 'running' : 'stopped')}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-muted mt-0.5">{sub}</p>
                </div>
                <button
                  onClick={() => restartService(svc)}
                  disabled={restarting === svc}
                  className="btn-secondary text-xs px-3 py-1.5 flex items-center gap-1.5"
                >
                  {restarting === svc ? <LoadingSpinner size={12} /> : null}
                  Restart
                </button>
              </div>
            )
          })}
        </SectionCard>

        {/* Blocklist Update Schedule */}
        <SectionCard title="Blocklist Update Schedule">
          <div className="px-4 py-4 space-y-4">
            <p className="text-xs text-muted">Configure when the blocklist refreshes. Takes effect within 60 seconds.</p>

            {/* Frequency picker */}
            <div className="flex gap-2">
              {(['daily', 'weekly', 'monthly'] as const).map(f => (
                <button
                  key={f}
                  onClick={() => setSchedule(s => ({ ...s, update_frequency: f }))}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                    schedule.update_frequency === f
                      ? 'bg-primary/20 border-primary text-primary'
                      : 'bg-transparent border-border text-muted'
                  }`}
                >
                  {f.charAt(0).toUpperCase() + f.slice(1)}
                </button>
              ))}
            </div>

            <div className="flex gap-3 items-end flex-wrap">
              {/* Day of week — weekly only */}
              {schedule.update_frequency === 'weekly' && (
                <div>
                  <p className="text-xs text-muted mb-1">Day</p>
                  <select
                    value={schedule.update_day_of_week}
                    onChange={e => setSchedule(s => ({ ...s, update_day_of_week: Number(e.target.value) }))}
                    className="input-base"
                    style={{ width: 110 }}
                  >
                    {['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'].map((d, i) => (
                      <option key={i} value={i}>{d}</option>
                    ))}
                  </select>
                </div>
              )}

              {/* Day of month — monthly only */}
              {schedule.update_frequency === 'monthly' && (
                <div>
                  <p className="text-xs text-muted mb-1">Day of month</p>
                  <select
                    value={schedule.update_day_of_month}
                    onChange={e => setSchedule(s => ({ ...s, update_day_of_month: Number(e.target.value) }))}
                    className="input-base"
                    style={{ width: 72 }}
                  >
                    {Array.from({ length: 28 }, (_, i) => (
                      <option key={i + 1} value={i + 1}>{i + 1}</option>
                    ))}
                  </select>
                </div>
              )}

              {/* Hour */}
              <div>
                <p className="text-xs text-muted mb-1">Hour</p>
                <select
                  value={schedule.update_hour}
                  onChange={e => setSchedule(s => ({ ...s, update_hour: Number(e.target.value) }))}
                  className="input-base"
                  style={{ width: 72 }}
                >
                  {Array.from({ length: 24 }, (_, h) => (
                    <option key={h} value={h}>{String(h).padStart(2, '0')}</option>
                  ))}
                </select>
              </div>

              {/* Minute */}
              <div>
                <p className="text-xs text-muted mb-1">Minute</p>
                <select
                  value={schedule.update_minute}
                  onChange={e => setSchedule(s => ({ ...s, update_minute: Number(e.target.value) }))}
                  className="input-base"
                  style={{ width: 72 }}
                >
                  {[0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55].map(m => (
                    <option key={m} value={m}>:{String(m).padStart(2, '0')}</option>
                  ))}
                </select>
              </div>

              <button onClick={saveSchedule} disabled={savingSched} className="btn-primary px-4 py-2">
                {savingSched ? <LoadingSpinner size={14} /> : 'Save'}
              </button>
            </div>

            <p className="text-xs text-muted">
              Current: <span className="text-[#e6edf3]">{scheduleLabel(schedule)}</span>
              <span className="text-muted ml-1">(Asia/Manila)</span>
            </p>
          </div>
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
