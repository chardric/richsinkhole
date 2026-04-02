// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

import { useCallback, useEffect, useState } from 'react'
import { apiDelete, apiGet, apiPatch, apiPost } from '../api/client'
import { LoadingSpinner, FullPageSpinner } from '../components/LoadingSpinner'
import { EmptyState } from '../components/EmptyState'
import { useToast } from '../context/ToastContext'

interface Schedule {
  id: number
  label: string
  client_ip: string
  start_time: string
  end_time: string
  days: string         // digit string: "0123456"
  days_label: string
  enabled: boolean
  grace_minutes: number
}

const DAY_DIGITS = ['0', '1', '2', '3', '4', '5', '6'] as const
const DAY_NAMES  = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const

function formatDays(days: string): string {
  // days is a digit string like "0123456"
  if (days.length === 7) return 'Every day'
  if (days === '01234') return 'Weekdays'
  if (days === '56') return 'Weekends'
  return days.split('').map(d => DAY_NAMES[parseInt(d)] || d).join(', ')
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

// ── Schedule modal ────────────────────────────────────────────────────────────
function ScheduleModal({
  schedule,
  onClose,
  onSaved,
  onDeleted,
}: {
  schedule: Schedule | null
  onClose: () => void
  onSaved: () => void
  onDeleted?: () => void
}) {
  const { showToast } = useToast()
  const isEdit = schedule !== null

  const [label,         setLabel]         = useState(schedule?.label || '')
  const [clientIp,      setClientIp]      = useState(schedule?.client_ip || '*')
  const [startTime,     setStartTime]     = useState(schedule?.start_time || '22:00')
  const [endTime,       setEndTime]       = useState(schedule?.end_time || '06:00')
  const [selectedDays,  setSelectedDays]  = useState<Set<string>>(() => {
    if (schedule?.days) return new Set(schedule.days.split(''))
    return new Set(DAY_DIGITS)
  })
  const [graceMinutes,  setGraceMinutes]  = useState(schedule?.grace_minutes || 0)
  const [saving,        setSaving]        = useState(false)
  const [deleting,      setDeleting]      = useState(false)

  function toggleDay(day: string) {
    setSelectedDays(prev => {
      const next = new Set(prev)
      if (next.has(day)) next.delete(day)
      else next.add(day)
      return next
    })
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (selectedDays.size === 0) return
    setSaving(true)
    const body = {
      label: label.trim(),
      client_ip: clientIp.trim() || '*',
      start_time: startTime,
      end_time: endTime,
      days: DAY_DIGITS.filter(d => selectedDays.has(d)).join(''),
      enabled: schedule?.enabled ?? true,
      grace_minutes: graceMinutes,
    }
    try {
      if (isEdit) {
        await apiPatch(`/api/schedules/${schedule.id}`, body)
        showToast('success', 'Schedule updated')
      } else {
        await apiPost('/api/schedules', body)
        showToast('success', 'Schedule created')
      }
      onSaved()
      onClose()
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!isEdit) return
    setDeleting(true)
    try {
      await apiDelete(`/api/schedules/${schedule.id}`)
      showToast('success', 'Schedule deleted')
      onDeleted?.()
      onClose()
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Delete failed')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={e => e.stopPropagation()}>
        <div className="p-4 border-b border-border">
          <h3 className="font-semibold text-[#e6edf3]">{isEdit ? 'Edit Schedule' : 'New Schedule'}</h3>
          <p className="text-muted text-xs mt-0.5">
            {isEdit ? 'Modify this time-based blocking rule' : 'Create a time-based blocking rule'}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          {/* Label */}
          <div>
            <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Label</label>
            <input
              type="text"
              value={label}
              onChange={e => setLabel(e.target.value)}
              placeholder="e.g. Bedtime, School Hours"
              className="input-base"
              maxLength={64}
              autoFocus
            />
          </div>

          {/* Device IP */}
          <div>
            <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Device IP
              <span className="font-normal text-[#6e7681] ml-1">(* for all devices)</span>
            </label>
            <input
              type="text"
              value={clientIp}
              onChange={e => setClientIp(e.target.value)}
              placeholder="*"
              className="input-base font-mono"
            />
          </div>

          {/* Time range */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Start</label>
              <input
                type="time"
                value={startTime}
                onChange={e => setStartTime(e.target.value)}
                className="input-base"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">End</label>
              <input
                type="time"
                value={endTime}
                onChange={e => setEndTime(e.target.value)}
                className="input-base"
              />
            </div>
          </div>

          {/* Days */}
          <div>
            <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Days</label>
            <div className="flex gap-1.5 flex-wrap">
              {DAY_DIGITS.map((digit, i) => (
                <button
                  key={digit}
                  type="button"
                  onClick={() => toggleDay(digit)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors min-h-[36px] border ${
                    selectedDays.has(digit)
                      ? 'bg-primary/20 border-primary text-primary'
                      : 'bg-[#0d1117] border-border text-muted hover:text-[#e6edf3]'
                  }`}
                >
                  {DAY_NAMES[i]}
                </button>
              ))}
            </div>
          </div>

          {/* Grace period */}
          <div>
            <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Grace Period
              <span className="font-normal text-[#6e7681] ml-1">(minutes of warning before block)</span>
            </label>
            <input
              type="number"
              value={graceMinutes}
              onChange={e => setGraceMinutes(Math.max(0, Math.min(60, parseInt(e.target.value) || 0)))}
              min={0}
              max={60}
              className="input-base w-24"
            />
          </div>

          {/* Actions */}
          <div className="flex gap-2 pt-1">
            {isEdit && (
              <button
                type="button"
                onClick={handleDelete}
                disabled={deleting || saving}
                className="btn-danger px-3 py-2 text-sm"
              >
                {deleting ? <LoadingSpinner size={14} /> : 'Delete'}
              </button>
            )}
            <div className="flex-1" />
            <button type="button" onClick={onClose} className="btn-secondary px-4 py-2 text-sm" disabled={saving || deleting}>
              Cancel
            </button>
            <button type="submit" className="btn-primary px-4 py-2 text-sm" disabled={saving || deleting || !label.trim() || selectedDays.size === 0}>
              {saving ? <LoadingSpinner size={14} /> : isEdit ? 'Save' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Main screen ───────────────────────────────────────────────────────────────
export function SchedulesScreen() {
  const { showToast } = useToast()
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [loading,   setLoading]   = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editing,   setEditing]   = useState<Schedule | null>(null)
  const [toggling,  setToggling]  = useState<number | null>(null)

  const fetchSchedules = useCallback(async () => {
    try {
      setSchedules(await apiGet<Schedule[]>('/api/schedules'))
    } catch {
      showToast('error', 'Failed to load schedules')
    } finally {
      setLoading(false)
    }
  }, [showToast])

  useEffect(() => { fetchSchedules() }, [fetchSchedules])

  async function handleToggle(sched: Schedule) {
    setToggling(sched.id)
    try {
      await apiPatch(`/api/schedules/${sched.id}`, { enabled: !sched.enabled })
      setSchedules(prev => prev.map(s => s.id === sched.id ? { ...s, enabled: !s.enabled } : s))
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Toggle failed')
    } finally {
      setToggling(null)
    }
  }

  function openAdd() {
    setEditing(null)
    setShowModal(true)
  }

  function openEdit(sched: Schedule) {
    setEditing(sched)
    setShowModal(true)
  }

  function closeModal() {
    setShowModal(false)
    setEditing(null)
  }

  if (loading) return <FullPageSpinner />

  return (
    <div className="h-full scroll-area">
      <div className="p-4 space-y-4 max-w-2xl mx-auto md:py-6">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-[#e6edf3]">Schedules</h2>
            <p className="text-xs text-muted mt-0.5">{schedules.length} rule{schedules.length !== 1 ? 's' : ''}</p>
          </div>
          <button onClick={openAdd} className="btn-primary px-3 py-1.5 text-xs gap-1.5">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            Add Rule
          </button>
        </div>

        {/* List */}
        {schedules.length === 0 ? (
          <EmptyState
            title="No schedules"
            subtitle="Create time-based rules to control DNS blocking"
            icon={
              <svg className="w-12 h-12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            }
          />
        ) : (
          <div className="bg-surface border border-border rounded-xl divide-y divide-border overflow-hidden">
            {schedules.map(sched => (
              <div key={sched.id} className="flex items-center gap-3 px-4 py-3">
                <button
                  onClick={() => openEdit(sched)}
                  className="flex-1 min-w-0 text-left"
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`text-sm font-medium ${sched.enabled ? 'text-[#e6edf3]' : 'text-muted'}`}>
                      {sched.label || sched.client_ip}
                    </span>
                    {sched.grace_minutes > 0 && (
                      <span className="pill bg-purple-900/50 text-purple-300">{sched.grace_minutes}m grace</span>
                    )}
                    {sched.client_ip !== '*' && (
                      <span className="pill bg-[#21262d] text-muted font-mono">{sched.client_ip}</span>
                    )}
                  </div>
                  <p className={`text-xs mt-0.5 ${sched.enabled ? 'text-muted' : 'text-muted/50'}`}>
                    {sched.start_time} – {sched.end_time} · {formatDays(sched.days)}
                  </p>
                </button>
                <Toggle
                  value={sched.enabled}
                  onChange={() => handleToggle(sched)}
                  disabled={toggling === sched.id}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {showModal && (
        <ScheduleModal
          schedule={editing}
          onClose={closeModal}
          onSaved={fetchSchedules}
          onDeleted={fetchSchedules}
        />
      )}
    </div>
  )
}
