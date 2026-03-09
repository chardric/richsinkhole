// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

import { useCallback, useEffect, useState } from 'react'
import { apiDelete, apiGet, apiPatch, apiPost } from '../api/client'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { EmptyState } from '../components/EmptyState'
import { useToast } from '../context/ToastContext'

// ── Types ────────────────────────────────────────────────────────────────────

interface ProxyRule {
  id: number
  hostname: string
  target: string
  enabled: boolean
  created_at: string
}

interface DnsRecord {
  id: number
  hostname: string
  type: string
  value: string
  ttl: number
  enabled: boolean
}

type Tab = 'proxy' | 'dns'

const DNS_TYPES = ['A', 'AAAA', 'CNAME', 'TXT'] as const

// ── Toggle switch ────────────────────────────────────────────────────────────

function Toggle({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 flex-shrink-0 rounded-full border-2 border-transparent transition-colors cursor-pointer ${
        checked ? 'bg-[#58a6ff]' : 'bg-[#30363d]'
      } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
    >
      <span className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform ${
        checked ? 'translate-x-4' : 'translate-x-0'
      }`} />
    </button>
  )
}

// ── Proxy Rule Modal ─────────────────────────────────────────────────────────

function ProxyRuleModal({
  rule, onClose, onSaved, onDeleted,
}: {
  rule?: ProxyRule
  onClose: () => void
  onSaved: () => void
  onDeleted?: () => void
}) {
  const { showToast } = useToast()
  const isEdit = !!rule

  const [hostname, setHostname] = useState(rule ? rule.hostname.replace(/\.lan$/, '') : '')
  const [target,   setTarget]   = useState(rule?.target ?? '')
  const [enabled,  setEnabled]  = useState(rule?.enabled ?? true)
  const [saving,   setSaving]   = useState(false)
  const [deleting, setDeleting] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!hostname.trim() || !target.trim()) return
    setSaving(true)
    const fullHostname = hostname.trim().endsWith('.lan') ? hostname.trim() : `${hostname.trim()}.lan`
    try {
      if (isEdit) {
        await apiPatch(`/api/proxy-rules/${rule!.id}`, { hostname: fullHostname, target: target.trim(), enabled })
        showToast('success', `Updated proxy rule: ${fullHostname}`)
      } else {
        await apiPost('/api/proxy-rules', { hostname: fullHostname, target: target.trim(), enabled })
        showToast('success', `Created proxy rule: ${fullHostname}`)
      }
      onSaved()
      onClose()
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Failed to save proxy rule')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!rule) return
    setDeleting(true)
    try {
      await apiDelete(`/api/proxy-rules/${rule.id}`)
      showToast('success', `Deleted proxy rule: ${rule.hostname}`)
      onDeleted?.()
      onClose()
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Failed to delete proxy rule')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={e => e.stopPropagation()}>
        <div className="p-4 border-b border-border">
          <h3 className="font-semibold text-[#e6edf3]">{isEdit ? 'Edit Proxy Rule' : 'Add Proxy Rule'}</h3>
          <p className="text-muted text-xs mt-0.5">Route a .lan hostname to a backend target</p>
        </div>
        <form onSubmit={handleSubmit} className="p-4 space-y-3">
          <div>
            <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Hostname</label>
            <div className="relative">
              <input
                type="text"
                value={hostname}
                onChange={e => setHostname(e.target.value)}
                placeholder="myservice"
                className="input-base pr-12"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                autoFocus
                disabled={saving}
              />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted">.lan</span>
            </div>
          </div>
          <div>
            <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Target URL</label>
            <input
              type="text"
              value={target}
              onChange={e => setTarget(e.target.value)}
              placeholder="http://192.168.1.100:8080"
              className="input-base"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              disabled={saving}
            />
          </div>
          <div className="flex items-center justify-between">
            <label className="text-xs font-semibold text-[#8b949e] uppercase tracking-wider">Enabled</label>
            <Toggle checked={enabled} onChange={setEnabled} disabled={saving} />
          </div>
          <div className="flex gap-2 pt-1">
            {isEdit && (
              <button type="button" onClick={handleDelete} className="btn-danger px-3" disabled={saving || deleting}>
                {deleting ? <LoadingSpinner size={14} /> : 'Delete'}
              </button>
            )}
            <button type="button" onClick={onClose} className="btn-secondary flex-1" disabled={saving || deleting}>Cancel</button>
            <button type="submit" className="btn-primary flex-1" disabled={saving || deleting || !hostname.trim() || !target.trim()}>
              {saving ? <LoadingSpinner size={14} /> : isEdit ? 'Save' : 'Add Rule'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── DNS Record Modal ─────────────────────────────────────────────────────────

function DnsRecordModal({
  record, onClose, onSaved, onDeleted,
}: {
  record?: DnsRecord
  onClose: () => void
  onSaved: () => void
  onDeleted?: () => void
}) {
  const { showToast } = useToast()
  const isEdit = !!record

  const [hostname, setHostname] = useState(record?.hostname ?? '')
  const [type,     setType]     = useState(record?.type ?? 'A')
  const [value,    setValue]    = useState(record?.value ?? '')
  const [ttl,      setTtl]      = useState(record?.ttl ?? 300)
  const [enabled,  setEnabled]  = useState(record?.enabled ?? true)
  const [saving,   setSaving]   = useState(false)
  const [deleting, setDeleting] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!hostname.trim() || !value.trim()) return
    setSaving(true)
    try {
      const body = { hostname: hostname.trim(), type, value: value.trim(), ttl, enabled }
      if (isEdit) {
        await apiPatch(`/api/dns-records/${record!.id}`, body)
        showToast('success', `Updated DNS record: ${hostname.trim()}`)
      } else {
        await apiPost('/api/dns-records', body)
        showToast('success', `Created DNS record: ${hostname.trim()}`)
      }
      onSaved()
      onClose()
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Failed to save DNS record')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!record) return
    setDeleting(true)
    try {
      await apiDelete(`/api/dns-records/${record.id}`)
      showToast('success', `Deleted DNS record: ${record.hostname}`)
      onDeleted?.()
      onClose()
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Failed to delete DNS record')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={e => e.stopPropagation()}>
        <div className="p-4 border-b border-border">
          <h3 className="font-semibold text-[#e6edf3]">{isEdit ? 'Edit DNS Record' : 'Add DNS Record'}</h3>
          <p className="text-muted text-xs mt-0.5">Create a local DNS override</p>
        </div>
        <form onSubmit={handleSubmit} className="p-4 space-y-3">
          <div>
            <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Hostname</label>
            <input
              type="text"
              value={hostname}
              onChange={e => setHostname(e.target.value)}
              placeholder="myhost.local"
              className="input-base"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              autoFocus
              disabled={saving}
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Type</label>
            <select
              value={type}
              onChange={e => setType(e.target.value)}
              className="input-base"
              disabled={saving}
            >
              {DNS_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Value</label>
            <input
              type="text"
              value={value}
              onChange={e => setValue(e.target.value)}
              placeholder={type === 'A' ? '192.168.1.100' : type === 'AAAA' ? '::1' : type === 'CNAME' ? 'target.example.com' : 'v=spf1 ...'}
              className="input-base"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              disabled={saving}
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">TTL (seconds)</label>
            <input
              type="number"
              value={ttl}
              onChange={e => setTtl(Math.max(0, parseInt(e.target.value) || 0))}
              min={0}
              className="input-base"
              disabled={saving}
            />
          </div>
          <div className="flex items-center justify-between">
            <label className="text-xs font-semibold text-[#8b949e] uppercase tracking-wider">Enabled</label>
            <Toggle checked={enabled} onChange={setEnabled} disabled={saving} />
          </div>
          <div className="flex gap-2 pt-1">
            {isEdit && (
              <button type="button" onClick={handleDelete} className="btn-danger px-3" disabled={saving || deleting}>
                {deleting ? <LoadingSpinner size={14} /> : 'Delete'}
              </button>
            )}
            <button type="button" onClick={onClose} className="btn-secondary flex-1" disabled={saving || deleting}>Cancel</button>
            <button type="submit" className="btn-primary flex-1" disabled={saving || deleting || !hostname.trim() || !value.trim()}>
              {saving ? <LoadingSpinner size={14} /> : isEdit ? 'Save' : 'Add Record'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Proxy Rules tab ──────────────────────────────────────────────────────────

function ProxyRulesTab() {
  const { showToast } = useToast()
  const [rules,    setRules]    = useState<ProxyRule[]>([])
  const [loading,  setLoading]  = useState(true)
  const [showAdd,  setShowAdd]  = useState(false)
  const [editing,  setEditing]  = useState<ProxyRule | null>(null)

  const fetchRules = useCallback(async () => {
    try {
      setRules(await apiGet<ProxyRule[]>('/api/proxy-rules'))
    } catch {
      showToast('error', 'Failed to load proxy rules')
    } finally {
      setLoading(false)
    }
  }, [showToast])

  useEffect(() => { fetchRules() }, [fetchRules])

  if (loading) return (
    <div className="flex items-center justify-center flex-1"><LoadingSpinner size={28} /></div>
  )

  return (
    <>
      <div className="px-4 py-3 border-b border-border flex items-center justify-between flex-shrink-0">
        <span className="text-xs text-muted">{rules.length} proxy rule{rules.length !== 1 ? 's' : ''}</span>
        <button onClick={() => setShowAdd(true)} className="btn-primary px-3 py-1.5 text-xs gap-1.5">
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Add Rule
        </button>
      </div>

      {rules.length === 0 ? (
        <EmptyState title="No proxy rules" subtitle="Route .lan hostnames to backend services" />
      ) : (
        <div className="flex-1 scroll-area divide-y divide-border">
          {rules.map(rule => (
            <button
              key={rule.id}
              onClick={() => setEditing(rule)}
              className="w-full text-left flex items-center gap-3 px-4 py-3 hover:bg-[#161b22] transition-colors"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-[#e6edf3] font-mono truncate">{rule.hostname}</span>
                  {rule.enabled ? (
                    <span className="pill bg-green-950/60 text-green-400 text-[10px]">active</span>
                  ) : (
                    <span className="pill bg-[#1f2937] text-[#6e7681] text-[10px]">disabled</span>
                  )}
                </div>
                <p className="text-xs text-muted truncate mt-0.5">{rule.target}</p>
              </div>
              <svg className="w-4 h-4 text-muted flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
              </svg>
            </button>
          ))}
        </div>
      )}

      {showAdd && (
        <ProxyRuleModal onClose={() => setShowAdd(false)} onSaved={fetchRules} />
      )}
      {editing && (
        <ProxyRuleModal
          rule={editing}
          onClose={() => setEditing(null)}
          onSaved={fetchRules}
          onDeleted={fetchRules}
        />
      )}
    </>
  )
}

// ── DNS Records tab ──────────────────────────────────────────────────────────

function DnsRecordsTab() {
  const { showToast } = useToast()
  const [records,  setRecords]  = useState<DnsRecord[]>([])
  const [loading,  setLoading]  = useState(true)
  const [showAdd,  setShowAdd]  = useState(false)
  const [editing,  setEditing]  = useState<DnsRecord | null>(null)

  const fetchRecords = useCallback(async () => {
    try {
      setRecords(await apiGet<DnsRecord[]>('/api/dns-records'))
    } catch {
      showToast('error', 'Failed to load DNS records')
    } finally {
      setLoading(false)
    }
  }, [showToast])

  useEffect(() => { fetchRecords() }, [fetchRecords])

  if (loading) return (
    <div className="flex items-center justify-center flex-1"><LoadingSpinner size={28} /></div>
  )

  return (
    <>
      <div className="px-4 py-3 border-b border-border flex items-center justify-between flex-shrink-0">
        <span className="text-xs text-muted">{records.length} DNS record{records.length !== 1 ? 's' : ''}</span>
        <button onClick={() => setShowAdd(true)} className="btn-primary px-3 py-1.5 text-xs gap-1.5">
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Add Record
        </button>
      </div>

      {records.length === 0 ? (
        <EmptyState title="No DNS records" subtitle="Add local DNS overrides for your network" />
      ) : (
        <div className="flex-1 scroll-area divide-y divide-border">
          {records.map(record => (
            <button
              key={record.id}
              onClick={() => setEditing(record)}
              className="w-full text-left flex items-center gap-3 px-4 py-3 hover:bg-[#161b22] transition-colors"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-[#e6edf3] font-mono truncate">{record.hostname}</span>
                  <span className="pill bg-blue-950/60 text-blue-400 text-[10px]">{record.type}</span>
                  {!record.enabled && (
                    <span className="pill bg-[#1f2937] text-[#6e7681] text-[10px]">disabled</span>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <p className="text-xs text-muted truncate">{record.value}</p>
                  <span className="text-[10px] text-muted/60 flex-shrink-0">TTL {record.ttl}s</span>
                </div>
              </div>
              <svg className="w-4 h-4 text-muted flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
              </svg>
            </button>
          ))}
        </div>
      )}

      {showAdd && (
        <DnsRecordModal onClose={() => setShowAdd(false)} onSaved={fetchRecords} />
      )}
      {editing && (
        <DnsRecordModal
          record={editing}
          onClose={() => setEditing(null)}
          onSaved={fetchRecords}
          onDeleted={fetchRecords}
        />
      )}
    </>
  )
}

// ── Main screen ──────────────────────────────────────────────────────────────

export function ProxyScreen() {
  const [activeTab, setActiveTab] = useState<Tab>('proxy')

  const tabs: Array<{ id: Tab; label: string; icon: React.ReactNode }> = [
    {
      id: 'proxy', label: 'Proxy Rules',
      icon: <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" /></svg>,
    },
    {
      id: 'dns', label: 'DNS Records',
      icon: <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01" /></svg>,
    },
  ]

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex border-b border-border flex-shrink-0">
        {tabs.map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className={`flex-1 flex items-center justify-center gap-1.5 py-3 text-xs font-medium transition-colors min-h-[44px] ${
              activeTab === tab.id ? 'text-primary border-b-2 border-primary' : 'text-muted hover:text-[#e6edf3]'
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'proxy' && <ProxyRulesTab />}
      {activeTab === 'dns'   && <DnsRecordsTab />}
    </div>
  )
}
