// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost } from '../api/client'
import type { QueryLog } from '../api/types'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { EmptyState } from '../components/EmptyState'
import { useInterval } from '../hooks/useInterval'
import { useToast } from '../context/ToastContext'

type Filter = 'all' | 'blocked' | 'allowed' | 'forwarded' | 'parental'

function relativeTime(ts: string): string {
  const diffMs = Date.now() - new Date(ts).getTime()
  const s = Math.floor(diffMs / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return new Date(ts).toLocaleDateString()
}

function actionPillClass(action: string): string {
  switch (action) {
    case 'blocked':       return 'pill-blocked'
    case 'allowed':       return 'pill-allowed'
    case 'parental_block': return 'pill-parental'
    case 'parental_warn':  return 'pill-warn'
    default:              return 'pill-forwarded'
  }
}

function actionLabel(action: string): string {
  switch (action) {
    case 'parental_block': return 'parental'
    case 'parental_warn':  return 'warn'
    default: return action
  }
}

function matchesFilter(log: QueryLog, filter: Filter): boolean {
  if (filter === 'all') return true
  if (filter === 'blocked')   return log.action === 'blocked'
  if (filter === 'allowed')   return log.action === 'allowed'
  if (filter === 'forwarded') return ['forwarded', 'cached', 'nxdomain'].includes(log.action)
  if (filter === 'parental')  return log.action.startsWith('parental_')
  return true
}

// ── Log entry row with quick actions ─────────────────────────────────────────
function LogRow({
  log,
  onBlock,
  onAllow,
  acting,
}: {
  log:     QueryLog
  onBlock: (domain: string) => void
  onAllow: (domain: string) => void
  acting:  string | null
}) {
  const isActing = acting === log.domain

  return (
    <>
      {/* Desktop row */}
      <tr className="hidden md:table-row hover:bg-surface transition-colors group">
        <td className="px-4 py-2.5 text-muted text-xs whitespace-nowrap">{relativeTime(log.ts)}</td>
        <td className="px-4 py-2.5 text-[#e6edf3] font-mono text-xs truncate max-w-xs">
          <span className="group-hover:text-[#58a6ff] transition-colors">{log.domain}</span>
        </td>
        <td className="px-4 py-2.5 text-muted text-xs whitespace-nowrap">{log.client_ip}</td>
        <td className="px-4 py-2.5">
          <span className={`pill ${actionPillClass(log.action)}`}>{actionLabel(log.action)}</span>
        </td>
        <td className="px-4 py-2.5">
          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            {log.action !== 'blocked' && (
              <button
                onClick={() => onBlock(log.domain)}
                disabled={isActing}
                title={`Block ${log.domain}`}
                className="text-xs text-muted hover:text-danger transition-colors px-2 py-1 rounded border border-border hover:border-danger/50 whitespace-nowrap"
              >
                {isActing ? <LoadingSpinner size={10} /> : 'Block'}
              </button>
            )}
            {log.action === 'blocked' && (
              <button
                onClick={() => onAllow(log.domain)}
                disabled={isActing}
                title={`Allow ${log.domain}`}
                className="text-xs text-muted hover:text-success transition-colors px-2 py-1 rounded border border-border hover:border-success/50 whitespace-nowrap"
              >
                {isActing ? <LoadingSpinner size={10} /> : 'Allow'}
              </button>
            )}
          </div>
        </td>
      </tr>

      {/* Mobile row */}
      <div className="md:hidden px-4 py-3 border-b border-border">
        <div className="flex items-start justify-between gap-2">
          <span className="text-sm text-[#e6edf3] font-mono truncate flex-1 min-w-0">{log.domain}</span>
          <span className={`pill ${actionPillClass(log.action)} flex-shrink-0`}>{actionLabel(log.action)}</span>
        </div>
        <div className="flex items-center gap-2 mt-1.5 flex-wrap">
          <span className="text-xs text-muted">{log.client_ip}</span>
          <span className="text-xs text-muted">·</span>
          <span className="text-xs text-muted">{relativeTime(log.ts)}</span>
          {log.response_ms !== null && (
            <><span className="text-xs text-muted">·</span>
            <span className="text-xs text-muted">{log.response_ms}ms</span></>
          )}
          {log.action !== 'blocked' && (
            <button onClick={() => onBlock(log.domain)} disabled={isActing}
              className="ml-auto text-xs text-muted hover:text-danger transition-colors px-2 py-0.5 rounded border border-border">
              {isActing ? <LoadingSpinner size={10} /> : 'Block'}
            </button>
          )}
          {log.action === 'blocked' && (
            <button onClick={() => onAllow(log.domain)} disabled={isActing}
              className="ml-auto text-xs text-muted hover:text-success transition-colors px-2 py-0.5 rounded border border-border">
              {isActing ? <LoadingSpinner size={10} /> : 'Allow'}
            </button>
          )}
        </div>
      </div>
    </>
  )
}

// ── Main screen ───────────────────────────────────────────────────────────────
export function LogsScreen() {
  const { showToast } = useToast()
  const [logs,    setLogs]    = useState<QueryLog[]>([])
  const [search,  setSearch]  = useState('')
  const [filter,  setFilter]  = useState<Filter>('all')
  const [loading, setLoading] = useState(true)
  const [acting,  setActing]  = useState<string | null>(null)

  const fetchLogs = useCallback(async () => {
    try {
      setLogs(await apiGet<QueryLog[]>('/api/logs?limit=200'))
    } catch {
      // silent — keep last data
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchLogs() }, [fetchLogs])
  useInterval(fetchLogs, 15_000)

  // Pull-to-refresh
  useEffect(() => {
    let startY = 0
    const onStart = (e: TouchEvent) => { startY = e.touches[0].clientY }
    const onEnd   = (e: TouchEvent) => { if (e.changedTouches[0].clientY - startY > 80) fetchLogs() }
    document.addEventListener('touchstart', onStart, { passive: true })
    document.addEventListener('touchend',   onEnd,   { passive: true })
    return () => {
      document.removeEventListener('touchstart', onStart)
      document.removeEventListener('touchend',   onEnd)
    }
  }, [fetchLogs])

  async function handleBlock(domain: string) {
    setActing(domain)
    try {
      await apiPost('/api/blocklist', { domain })
      showToast('success', `Blocked: ${domain}`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed'
      showToast('error', msg.includes('already blocked') ? `${domain} is already blocked` : msg)
    } finally {
      setActing(null)
    }
  }

  async function handleAllow(domain: string) {
    setActing(domain)
    try {
      await apiPost('/api/allowlist', { domain, note: 'Added from Query Logs' })
      showToast('success', `Allowed: ${domain}`)
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Failed')
    } finally {
      setActing(null)
    }
  }

  const filtered = logs.filter(l =>
    matchesFilter(l, filter) &&
    (!search.trim() || l.domain.includes(search.toLowerCase()) || l.client_ip.includes(search) || l.action.includes(search.toLowerCase()))
  )

  const filterChips: Array<{ id: Filter; label: string; count: number }> = ([
    { id: 'all'       as Filter, label: 'All',       count: logs.length },
    { id: 'blocked'   as Filter, label: 'Blocked',   count: logs.filter(l => l.action === 'blocked').length },
    { id: 'allowed'   as Filter, label: 'Allowed',   count: logs.filter(l => l.action === 'allowed').length },
    { id: 'forwarded' as Filter, label: 'Forwarded', count: logs.filter(l => ['forwarded','cached','nxdomain'].includes(l.action)).length },
    { id: 'parental'  as Filter, label: 'Parental',  count: logs.filter(l => l.action.startsWith('parental_')).length },
  ] as Array<{ id: Filter; label: string; count: number }>).filter(c => c.id === 'all' || c.count > 0)

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Search */}
      <div className="px-4 pt-3 pb-2 border-b border-border flex-shrink-0 space-y-2">
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 11A6 6 0 115 11a6 6 0 0112 0z" />
          </svg>
          <input type="search" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Filter by domain, IP, or action..." className="input-base pl-9" />
        </div>
        {/* Filter chips */}
        <div className="flex gap-1.5 overflow-x-auto pb-0.5">
          {filterChips.map(chip => (
            <button
              key={chip.id}
              onClick={() => setFilter(chip.id)}
              className={`flex-shrink-0 px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
                filter === chip.id
                  ? 'bg-primary text-[#0d1117]'
                  : 'bg-surface border border-border text-muted hover:text-[#e6edf3]'
              }`}
            >
              {chip.label}
              {chip.id !== 'all' && chip.count > 0 && (
                <span className="ml-1.5 opacity-70">{chip.count}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Count row */}
      <div className="px-4 py-1.5 flex-shrink-0 flex items-center justify-between">
        <span className="text-xs text-muted">
          {filtered.length} {filtered.length === 1 ? 'entry' : 'entries'}
          {search && ` matching "${search}"`}
        </span>
        {loading && <LoadingSpinner size={14} />}
      </div>

      {loading && logs.length === 0 ? (
        <div className="flex items-center justify-center flex-1"><LoadingSpinner size={28} /></div>
      ) : filtered.length === 0 ? (
        <EmptyState
          title="No logs found"
          subtitle={search || filter !== 'all' ? 'Try a different filter' : 'No DNS queries yet'}
          icon={
            <svg className="w-12 h-12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 10h16M4 14h10M4 18h7" />
            </svg>
          }
        />
      ) : (
        <div className="flex-1 scroll-area">
          {/* Desktop table */}
          <table className="hidden md:table w-full text-sm">
            <thead className="sticky top-0 bg-bg border-b border-border z-10">
              <tr>
                <th className="text-left px-4 py-2 text-muted font-medium text-xs uppercase tracking-wide w-24">Time</th>
                <th className="text-left px-4 py-2 text-muted font-medium text-xs uppercase tracking-wide">Domain</th>
                <th className="text-left px-4 py-2 text-muted font-medium text-xs uppercase tracking-wide w-32">Client</th>
                <th className="text-left px-4 py-2 text-muted font-medium text-xs uppercase tracking-wide w-24">Action</th>
                <th className="px-4 py-2 w-20" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filtered.map(log => (
                <LogRow key={log.id} log={log} onBlock={handleBlock} onAllow={handleAllow} acting={acting} />
              ))}
            </tbody>
          </table>

          {/* Mobile list */}
          <div className="md:hidden">
            {filtered.map(log => (
              <LogRow key={log.id} log={log} onBlock={handleBlock} onAllow={handleAllow} acting={acting} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
