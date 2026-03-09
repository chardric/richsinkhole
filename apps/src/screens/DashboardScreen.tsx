// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

import { useCallback, useEffect, useState } from 'react'
import { apiGet } from '../api/client'
import type { Health, QueryLog, Stats } from '../api/types'
import { StatCard } from '../components/StatCard'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { useInterval } from '../hooks/useInterval'

function relativeTime(ts: string): string {
  const diffMs = Date.now() - new Date(ts).getTime()
  const s = Math.floor(diffMs / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

function actionClass(action: string): string {
  if (action === 'blocked' || action === 'parental_block') return 'pill-blocked'
  if (action === 'allowed') return 'pill-allowed'
  if (action === 'parental_warn') return 'pill-warn'
  return 'pill-forwarded'
}

function HealthDot({ status }: { status: string }) {
  const color =
    status === 'healthy'  ? 'bg-success' :
    status === 'degraded' ? 'bg-warning' :
    'bg-danger'

  return (
    <span className={`inline-block w-2.5 h-2.5 rounded-full flex-shrink-0 animate-pulse-dot ${color}`} />
  )
}

export function DashboardScreen() {
  const [stats,     setStats]     = useState<Stats | null>(null)
  const [health,    setHealth]    = useState<Health | null>(null)
  const [recentLog, setRecentLog] = useState<QueryLog[]>([])
  const [loading,   setLoading]   = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  const fetchData = useCallback(async () => {
    try {
      const [s, h, logs] = await Promise.all([
        apiGet<Stats>('/api/stats'),
        apiGet<Health>('/health'),
        apiGet<QueryLog[]>('/api/logs?limit=10'),
      ])
      setStats(s)
      setHealth(h)
      setRecentLog(logs)
      setLastUpdated(new Date())
    } catch {
      // If we can't reach the server, show degraded state
      if (!stats) setHealth({ status: 'offline', components: {} })
    } finally {
      setLoading(false)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchData() }, [fetchData])
  useInterval(fetchData, 30_000)

  // Pull-to-refresh on mobile
  useEffect(() => {
    let startY = 0
    const handleTouchStart = (e: TouchEvent) => { startY = e.touches[0].clientY }
    const handleTouchEnd = (e: TouchEvent) => {
      const dy = e.changedTouches[0].clientY - startY
      if (dy > 80) fetchData()
    }
    document.addEventListener('touchstart', handleTouchStart, { passive: true })
    document.addEventListener('touchend', handleTouchEnd, { passive: true })
    return () => {
      document.removeEventListener('touchstart', handleTouchStart)
      document.removeEventListener('touchend', handleTouchEnd)
    }
  }, [fetchData])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <LoadingSpinner size={32} />
      </div>
    )
  }

  const statusText =
    health?.status === 'healthy'  ? 'Healthy' :
    health?.status === 'degraded' ? 'Degraded' :
    'Offline'

  return (
    <div className="h-full scroll-area">
      <div className="p-4 space-y-4 max-w-2xl mx-auto md:py-6">
        {/* Health row */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <HealthDot status={health?.status ?? 'offline'} />
            <span className="text-sm font-medium text-[#e6edf3]">{statusText}</span>
          </div>
          {lastUpdated && (
            <span className="text-xs text-muted">Updated {relativeTime(lastUpdated.toISOString())}</span>
          )}
        </div>

        {/* Stat cards 2×2 grid */}
        <div className="grid grid-cols-2 gap-3">
          <StatCard
            title="Total Queries"
            value={stats?.total ?? 0}
          />
          <StatCard
            title="Blocked"
            value={stats?.blocked ?? 0}
            color="red"
          />
          <StatCard
            title="Block Rate"
            value={stats ? `${stats.block_pct.toFixed(1)}%` : '0%'}
            color="blue"
          />
          <StatCard
            title="Clients"
            value={stats?.unique_clients ?? 0}
            color="green"
          />
        </div>

        {/* Recent activity */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold text-[#e6edf3]">Recent Activity</h2>
            <span className="text-xs text-muted">Last 10 queries</span>
          </div>

          {recentLog.length === 0 ? (
            <div className="bg-surface border border-border rounded-xl p-6 text-center">
              <p className="text-muted text-sm">No queries yet</p>
            </div>
          ) : (
            <div className="bg-surface border border-border rounded-xl divide-y divide-border overflow-hidden">
              {recentLog.map(entry => (
                <div
                  key={entry.id}
                  className="flex items-center gap-3 px-3 py-2.5 min-h-[48px]"
                >
                  <span className={`pill ${actionClass(entry.action)} flex-shrink-0 w-[68px] justify-center`}>
                    {entry.action.replace('parental_', '')}
                  </span>
                  <span className="text-sm text-[#e6edf3] truncate flex-1 min-w-0">{entry.domain}</span>
                  <span className="text-xs text-muted flex-shrink-0">{entry.client_ip}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Top blocked domains */}
        {stats && stats.top_blocked && stats.top_blocked.length > 0 && (
          <div>
            <h2 className="text-sm font-semibold text-[#e6edf3] mb-2">Top Blocked Domains</h2>
            <div className="bg-surface border border-border rounded-xl divide-y divide-border overflow-hidden">
              {stats.top_blocked.slice(0, 5).map(item => (
                <div key={item.domain} className="flex items-center justify-between px-3 py-2.5">
                  <span className="text-sm text-[#e6edf3] truncate flex-1 mr-3">{item.domain}</span>
                  <span className="pill pill-blocked">{item.count.toLocaleString()}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
