// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

import { useCallback, useEffect, useState } from 'react'
import { apiDelete, apiGet } from '../api/client'
import type { SecurityBlock, SecurityEvent } from '../api/types'
import { LoadingSpinner, FullPageSpinner } from '../components/LoadingSpinner'
import { EmptyState } from '../components/EmptyState'
import { useInterval } from '../hooks/useInterval'
import { useToast } from '../context/ToastContext'

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

function eventTypeBadge(type: string) {
  const styles: Record<string, string> = {
    dga_suspect:   'bg-purple-900/50 text-purple-300',
    dns_tunnel:    'bg-orange-900/50 text-orange-300',
    burst_limit:   'bg-yellow-900/50 text-yellow-300',
    iot_flood:     'bg-yellow-900/50 text-yellow-300',
    typosquat:     'bg-pink-900/50 text-pink-300',
    nrd_flagged:   'bg-red-900/50 text-red-300',
    rebinding:     'bg-red-900/50 text-red-300',
    rate_limit:    'bg-yellow-900/50 text-yellow-300',
    query_burst:   'bg-yellow-900/50 text-yellow-300',
  }
  const cls = styles[type] || 'bg-[#21262d] text-muted'
  const label = type.replace(/_/g, ' ')
  return <span className={`pill ${cls} uppercase text-[10px] tracking-wide`}>{label}</span>
}

export function SecurityScreen() {
  const { showToast } = useToast()
  const [blocks,   setBlocks]   = useState<SecurityBlock[]>([])
  const [events,   setEvents]   = useState<SecurityEvent[]>([])
  const [loading,  setLoading]  = useState(true)
  const [unblockg, setUnblockg] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    try {
      const [b, e] = await Promise.all([
        apiGet<SecurityBlock[]>('/api/security/blocks'),
        apiGet<SecurityEvent[]>('/api/security/events?limit=100'),
      ])
      setBlocks(b)
      setEvents(e)
    } catch {
      // silent — keep last data
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])
  useInterval(fetchData, 30_000)

  async function handleUnblock(ip: string) {
    setUnblockg(ip)
    try {
      await apiDelete(`/api/security/blocks/${encodeURIComponent(ip)}`)
      showToast('success', `Unblocked ${ip}`)
      setBlocks(prev => prev.filter(b => b.ip !== ip))
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Unblock failed')
    } finally {
      setUnblockg(null)
    }
  }

  if (loading) return <FullPageSpinner />

  return (
    <div className="h-full scroll-area">
      <div className="p-4 space-y-5 max-w-2xl mx-auto md:py-6">

        {/* Active blocks */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold text-[#e6edf3]">Active Blocks</h2>
            <span className={`pill ${blocks.length > 0 ? 'pill-blocked' : 'bg-[#21262d] text-muted'}`}>
              {blocks.length}
            </span>
          </div>

          {blocks.length === 0 ? (
            <div className="bg-surface border border-border rounded-xl p-5 text-center">
              <div className="text-success text-2xl mb-1">✓</div>
              <p className="text-muted text-sm">No active blocks</p>
            </div>
          ) : (
            <div className="bg-surface border border-border rounded-xl divide-y divide-border overflow-hidden">
              {blocks.map(block => (
                <div key={block.ip} className="flex items-center gap-3 px-4 py-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-mono text-[#e6edf3]">{block.ip}</span>
                      <span className="pill pill-blocked text-[10px] uppercase tracking-wide">
                        {block.reason_label || block.reason}
                      </span>
                    </div>
                    <p className="text-xs text-muted mt-0.5">
                      Blocked {relativeTime(block.blocked_at)} · {block.query_count} queries
                    </p>
                    <p className="text-xs text-muted">
                      Expires {relativeTime(block.expires_at)}
                    </p>
                  </div>
                  <button
                    onClick={() => handleUnblock(block.ip)}
                    disabled={unblockg === block.ip}
                    className="btn-secondary px-3 py-1.5 text-xs flex-shrink-0"
                  >
                    {unblockg === block.ip ? <LoadingSpinner size={12} /> : 'Unblock'}
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Recent security events */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold text-[#e6edf3]">Recent Events</h2>
            <span className="text-xs text-muted">{events.length} total</span>
          </div>

          {events.length === 0 ? (
            <EmptyState
              title="No security events"
              subtitle="Threats and anomalies will appear here"
              icon={
                <svg className="w-12 h-12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                </svg>
              }
            />
          ) : (
            <div className="bg-surface border border-border rounded-xl divide-y divide-border overflow-hidden">
              {events.map((ev, idx) => (
                <div key={`${ev.ts}-${idx}`} className="px-4 py-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      {eventTypeBadge(ev.event_type)}
                      <span className="text-xs font-mono text-muted">{ev.client_ip}</span>
                    </div>
                    <span className="text-xs text-muted flex-shrink-0">{relativeTime(ev.ts)}</span>
                  </div>
                  {ev.domain && (
                    <p className="text-sm text-[#e6edf3] font-mono truncate mt-1">{ev.domain}</p>
                  )}
                  {ev.detail && (
                    <p className="text-xs text-muted mt-0.5 truncate">{ev.detail}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
