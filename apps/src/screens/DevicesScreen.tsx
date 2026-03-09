// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPatch, apiPost } from '../api/client'
import type { Device, ParentalSettings } from '../api/types'
import { LoadingSpinner, FullPageSpinner } from '../components/LoadingSpinner'
import { EmptyState } from '../components/EmptyState'
import { useToast } from '../context/ToastContext'

function isGhost(lastSeen: string): boolean {
  const diff = Date.now() - new Date(lastSeen).getTime()
  return diff > 24 * 3600 * 1000
}

function profileBadge(profile: string) {
  switch (profile) {
    case 'strict':      return <span className="pill bg-red-900/50 text-red-300">Strict</span>
    case 'passthrough': return <span className="pill bg-green-900/50 text-green-300">Passthrough</span>
    default:            return <span className="pill bg-blue-900/50 text-blue-300">Normal</span>
  }
}

function typeBadge(type: string) {
  const colors: Record<string, string> = {
    Phone:   'bg-purple-900/50 text-purple-300',
    Tablet:  'bg-indigo-900/50 text-indigo-300',
    PC:      'bg-cyan-900/50 text-cyan-300',
    TV:      'bg-orange-900/50 text-orange-300',
    IoT:     'bg-yellow-900/50 text-yellow-300',
    Router:  'bg-teal-900/50 text-teal-300',
    Unknown: 'bg-[#21262d] text-muted',
  }
  const cls = colors[type] || colors.Unknown
  return <span className={`pill ${cls}`}>{type}</span>
}

// ── Toggle component ──────────────────────────────────────────────────────────
function Toggle({ value, onChange, disabled }: { value: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      onClick={() => onChange(!value)}
      disabled={disabled}
      className={`toggle-track w-11 h-6 ${value ? 'bg-primary' : 'bg-[#30363d]'} ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
    >
      <span className={`toggle-thumb ${value ? 'translate-x-5' : 'translate-x-0.5'}`} />
    </button>
  )
}

// ── Device detail bottom sheet ────────────────────────────────────────────────
function DeviceSheet({
  device,
  onClose,
  onSaved,
}: {
  device: Device
  onClose: () => void
  onSaved: () => void
}) {
  const { showToast } = useToast()
  const [label,       setLabel]       = useState(device.label || '')
  const [profile,     setProfile]     = useState(device.profile)
  const [parental,    setParental]    = useState<ParentalSettings | null>(null)
  const [loadingP,    setLoadingP]    = useState(false)
  const [saving,      setSaving]      = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoadingP(true)
    apiGet<ParentalSettings>(`/api/parental/settings/${device.ip}`)
      .then(data => { if (!cancelled) setParental(data) })
      .catch(() => { /* parental not set up */ })
      .finally(() => { if (!cancelled) setLoadingP(false) })
    return () => { cancelled = true }
  }, [device.ip])

  async function handleSave() {
    setSaving(true)
    try {
      if (label !== (device.label || '')) {
        await apiPatch(`/api/devices/${device.ip}`, { label })
      }
      if (profile !== device.profile) {
        await apiPatch(`/api/devices/${device.ip}/profile`, { profile })
      }
      if (parental) {
        await apiPost(`/api/parental/settings/${device.ip}`, parental)
      }
      showToast('success', 'Device settings saved')
      onSaved()
      onClose()
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="sheet-backdrop" onClick={onClose} />
      <div className="sheet-panel px-4 pt-4 pb-8">
        {/* Handle */}
        <div className="w-10 h-1 bg-[#30363d] rounded-full mx-auto mb-4" />

        <h2 className="text-[#e6edf3] font-semibold text-lg mb-1">
          {device.label || device.ip}
        </h2>
        <p className="text-muted text-sm mb-4">{device.ip}</p>

        <div className="space-y-4">
          {/* Label */}
          <div>
            <label className="block text-sm font-medium text-[#e6edf3] mb-1.5">Device Label</label>
            <input
              type="text"
              value={label}
              onChange={e => setLabel(e.target.value)}
              placeholder="e.g. Dad's Phone"
              className="input-base"
              maxLength={64}
            />
          </div>

          {/* Profile */}
          <div>
            <label className="block text-sm font-medium text-[#e6edf3] mb-2">Blocking Profile</label>
            <div className="space-y-2">
              {(['normal', 'strict', 'passthrough'] as const).map(p => (
                <label
                  key={p}
                  className="flex items-center gap-3 p-3 bg-[#0d1117] border border-border rounded-lg cursor-pointer min-h-[44px]"
                >
                  <input
                    type="radio"
                    name="profile"
                    value={p}
                    checked={profile === p}
                    onChange={() => setProfile(p)}
                    className="accent-primary"
                  />
                  <div>
                    <p className="text-sm text-[#e6edf3] capitalize">{p}</p>
                    <p className="text-xs text-muted">
                      {p === 'normal'      && 'Standard blocklist enforcement'}
                      {p === 'strict'      && 'Block all + strict DNS filtering'}
                      {p === 'passthrough' && 'Allow all — bypass blocklist'}
                    </p>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* Parental controls */}
          {loadingP ? (
            <div className="flex items-center gap-2 py-2">
              <LoadingSpinner size={16} />
              <span className="text-muted text-sm">Loading parental settings…</span>
            </div>
          ) : parental && (
            <div>
              <label className="block text-sm font-medium text-[#e6edf3] mb-2">Parental Controls</label>
              <div className="space-y-3 p-3 bg-[#0d1117] border border-border rounded-lg">
                <div className="flex items-center justify-between min-h-[44px]">
                  <span className="text-sm text-[#e6edf3]">Enable Parental Controls</span>
                  <Toggle
                    value={parental.parental_enabled}
                    onChange={v => setParental({ ...parental, parental_enabled: v })}
                  />
                </div>

                {parental.parental_enabled && (
                  <>
                    <div className="border-t border-border pt-3 space-y-3">
                      <div className="flex items-center justify-between min-h-[44px]">
                        <span className="text-sm text-[#e6edf3]">Block Social Media</span>
                        <Toggle
                          value={parental.parental_block_social}
                          onChange={v => setParental({ ...parental, parental_block_social: v })}
                        />
                      </div>
                      <div className="flex items-center justify-between min-h-[44px]">
                        <span className="text-sm text-[#e6edf3]">Block Gaming Sites</span>
                        <Toggle
                          value={parental.parental_block_gaming}
                          onChange={v => setParental({ ...parental, parental_block_gaming: v })}
                        />
                      </div>
                    </div>
                  </>
                )}
              </div>
            </div>
          )}

          {/* MAC info */}
          {(device.mac || device.vendor) && (
            <div className="text-xs text-muted">
              {device.mac && <span className="font-mono">{device.mac}</span>}
              {device.vendor && <span className="ml-2">· {device.vendor}</span>}
            </div>
          )}

          {/* Save */}
          <button onClick={handleSave} className="btn-primary" disabled={saving}>
            {saving ? <LoadingSpinner size={16} /> : 'Save Changes'}
          </button>
        </div>
      </div>
    </>
  )
}

// ── Main screen ───────────────────────────────────────────────────────────────
export function DevicesScreen() {
  const [devices,  setDevices]  = useState<Device[]>([])
  const [loading,  setLoading]  = useState(true)
  const [selected, setSelected] = useState<Device | null>(null)
  const { showToast } = useToast()

  const fetchDevices = useCallback(async () => {
    try {
      const data = await apiGet<Device[]>('/api/devices')
      setDevices(data)
    } catch {
      showToast('error', 'Failed to load devices')
    } finally {
      setLoading(false)
    }
  }, [showToast])

  useEffect(() => { fetchDevices() }, [fetchDevices])

  if (loading) return <FullPageSpinner />

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex-shrink-0 flex items-center justify-between">
        <span className="text-xs text-muted">{devices.length} device{devices.length !== 1 ? 's' : ''} seen</span>
        <button onClick={fetchDevices} className="text-muted hover:text-[#e6edf3] transition-colors p-2">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
      </div>

      {devices.length === 0 ? (
        <EmptyState
          title="No devices seen"
          subtitle="Devices appear here after making DNS queries"
          icon={
            <svg className="w-12 h-12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
            </svg>
          }
        />
      ) : (
        <div className="flex-1 scroll-area divide-y divide-border">
          {devices.map(device => (
            <button
              key={device.ip}
              onClick={() => setSelected(device)}
              className="w-full flex items-center gap-3 px-4 py-3 hover:bg-surface-hover transition-colors text-left min-h-[64px]"
            >
              {/* Device icon */}
              <div className="w-9 h-9 rounded-full bg-surface-2 border border-border flex items-center justify-center flex-shrink-0">
                <svg className="w-4 h-4 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
                </svg>
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-[#e6edf3] truncate">
                    {device.label || device.ip}
                  </span>
                  {isGhost(device.last_seen) && (
                    <span title="No DNS queries in 24h" className="text-base leading-none">👻</span>
                  )}
                </div>
                <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                  {typeBadge(device.device_type)}
                  {profileBadge(device.profile)}
                  {device.label && (
                    <span className="text-xs text-muted">{device.ip}</span>
                  )}
                </div>
                {(device.mac || device.vendor) && (
                  <p className="text-xs text-muted mt-0.5 truncate">
                    {device.mac}{device.vendor ? ` · ${device.vendor}` : ''}
                  </p>
                )}
              </div>

              {/* Chevron */}
              <svg className="w-4 h-4 text-muted flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
              </svg>
            </button>
          ))}
        </div>
      )}

      {selected && (
        <DeviceSheet
          device={selected}
          onClose={() => setSelected(null)}
          onSaved={fetchDevices}
        />
      )}
    </div>
  )
}
