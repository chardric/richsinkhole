// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

import { useCallback, useEffect, useState } from 'react'
import { apiGet } from '../api/client'
import { FullPageSpinner } from '../components/LoadingSpinner'

interface ScoreBreakdownItem {
  score: number
  max: number
  detail: string
}

interface NetworkScore {
  score: number
  grade: string
  breakdown: {
    protection: ScoreBreakdownItem
    security: ScoreBreakdownItem
    performance: ScoreBreakdownItem
    system: ScoreBreakdownItem
  }
}

interface PrivacyDevice {
  ip: string
  label: string
  device_type: string
  total_forwarded: number
  companies: Array<{ company: string; count: number; pct: number }>
}

interface HeatmapData {
  hours: number[]
}

const GRADE_COLORS: Record<string, string> = {
  A: '#22c55e',
  B: '#58a6ff',
  C: '#eab308',
  D: '#f97316',
  F: '#ef4444',
}

function gradeColor(grade: string): string {
  return GRADE_COLORS[grade.charAt(0).toUpperCase()] || '#58a6ff'
}

function BreakdownBar({ label, item }: { label: string; item: ScoreBreakdownItem }) {
  const pct = item.max > 0 ? (item.score / item.max) * 100 : 0

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-[#e6edf3] capitalize font-medium">{label}</span>
        <span className="text-muted">{item.score}/{item.max}</span>
      </div>
      <div className="h-1.5 bg-[#21262d] rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{
            width: `${pct}%`,
            backgroundColor: pct >= 80 ? '#22c55e' : pct >= 50 ? '#eab308' : '#ef4444',
          }}
        />
      </div>
      <p className="text-xs text-muted">{item.detail}</p>
    </div>
  )
}

function HeatmapCell({ hour, count, max }: { hour: number; count: number; max: number }) {
  const opacity = max > 0 ? Math.max(0.08, count / max) : 0.08

  return (
    <div
      title={`${String(hour).padStart(2, '0')}:00 — ${count.toLocaleString()} queries`}
      className="flex items-center justify-center rounded text-[10px] font-mono aspect-square cursor-default select-none"
      style={{
        backgroundColor: `rgba(88, 166, 255, ${opacity})`,
        color: opacity > 0.5 ? '#e6edf3' : '#8b949e',
      }}
    >
      {hour}
    </div>
  )
}

export function PrivacyScreen() {
  const [score, setScore] = useState<NetworkScore | null>(null)
  const [devices, setDevices] = useState<PrivacyDevice[]>([])
  const [heatmap, setHeatmap] = useState<number[]>([])
  const [range, setRange] = useState<'24h' | '7d'>('24h')
  const [loading, setLoading] = useState(true)

  const fetchData = useCallback(async () => {
    try {
      const [s, d, h] = await Promise.all([
        apiGet<NetworkScore>('/api/network-score'),
        apiGet<PrivacyDevice[]>(`/api/privacy-report?range=${range}`),
        apiGet<HeatmapData>('/api/heatmap'),
      ])
      setScore(s)
      setDevices(d.sort((a, b) => b.total_forwarded - a.total_forwarded))
      setHeatmap(h.hours)
    } catch {
      // silent — keep last data
    } finally {
      setLoading(false)
    }
  }, [range])

  useEffect(() => { fetchData() }, [fetchData])

  if (loading) return <FullPageSpinner />

  const gc = score ? gradeColor(score.grade) : '#58a6ff'
  const heatMax = Math.max(...heatmap, 1)

  return (
    <div className="h-full scroll-area">
      <div className="p-4 space-y-5 max-w-2xl mx-auto md:py-6">

        {/* Network Score */}
        <section>
          <h2 className="text-sm font-semibold text-[#e6edf3] mb-2">Network Score</h2>
          <div className="bg-surface border border-border rounded-xl p-5">
            {score ? (
              <>
                <div className="flex items-center justify-center gap-4 mb-5">
                  <div className="relative flex items-center justify-center w-28 h-28">
                    <div
                      className="absolute inset-0 rounded-full border-4"
                      style={{ borderColor: `${gc}33` }}
                    />
                    <div
                      className="absolute inset-1 rounded-full border-[3px]"
                      style={{ borderColor: `${gc}66` }}
                    />
                    <div
                      className="absolute inset-2 rounded-full border-2"
                      style={{ borderColor: gc }}
                    />
                    <div className="text-center z-10">
                      <div className="text-3xl font-bold text-[#e6edf3] leading-none">
                        {score.score}
                      </div>
                      <span
                        className="inline-block mt-1 px-2 py-0.5 rounded text-xs font-bold"
                        style={{ backgroundColor: `${gc}22`, color: gc }}
                      >
                        {score.grade}
                      </span>
                    </div>
                  </div>
                </div>
                <div className="space-y-3">
                  {(['protection', 'security', 'performance', 'system'] as const).map(key => (
                    <BreakdownBar key={key} label={key} item={score.breakdown[key]} />
                  ))}
                </div>
              </>
            ) : (
              <p className="text-muted text-sm text-center">Unable to load score</p>
            )}
          </div>
        </section>

        {/* Activity Heatmap */}
        <section>
          <h2 className="text-sm font-semibold text-[#e6edf3] mb-2">Activity Heatmap</h2>
          <div className="bg-surface border border-border rounded-xl p-4">
            {heatmap.length > 0 ? (
              <div className="grid grid-cols-6 gap-1.5">
                {heatmap.map((count, hour) => (
                  <HeatmapCell key={hour} hour={hour} count={count} max={heatMax} />
                ))}
              </div>
            ) : (
              <p className="text-muted text-sm text-center">No activity data</p>
            )}
          </div>
        </section>

        {/* Privacy Report */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold text-[#e6edf3]">Privacy Report</h2>
            <div className="flex items-center gap-2">
              <div className="flex rounded-lg overflow-hidden border border-border">
                {(['24h', '7d'] as const).map(r => (
                  <button
                    key={r}
                    onClick={() => { setRange(r); setLoading(true) }}
                    className={`px-2.5 py-0.5 text-[10px] font-medium transition-colors ${
                      range === r ? 'bg-primary/20 text-primary' : 'text-muted'
                    }`}
                  >
                    {r === '24h' ? '24h' : '7d'}
                  </button>
                ))}
              </div>
              <span className="text-xs text-muted">{devices.length} devices</span>
            </div>
          </div>

          {devices.length === 0 ? (
            <div className="bg-surface border border-border rounded-xl p-5 text-center">
              <p className="text-muted text-sm">No device data available</p>
            </div>
          ) : (
            <div className="bg-surface border border-border rounded-xl divide-y divide-border overflow-hidden">
              {devices.map(dev => (
                  <div key={dev.ip} className="px-4 py-3">
                    <div className="flex items-center justify-between">
                      <div className="min-w-0">
                        <span className="text-sm font-medium text-[#e6edf3]">
                          {dev.label || dev.ip}
                        </span>
                        {dev.device_type && (
                          <span className="text-[10px] text-muted ml-2">{dev.device_type}</span>
                        )}
                      </div>
                      <span className="text-xs text-muted flex-shrink-0">
                        {dev.total_forwarded.toLocaleString()} fwd
                      </span>
                    </div>
                    {dev.companies.length > 0 && (
                      <div className="mt-2 space-y-1">
                        {dev.companies.slice(0, 6).map(c => (
                          <div key={c.company} className="flex items-center gap-2 text-xs">
                            <span className="w-20 truncate text-muted">{c.company}</span>
                            <div className="flex-1 h-1 bg-[#21262d] rounded-full overflow-hidden">
                              <div className="h-full bg-blue-500 rounded-full" style={{ width: `${c.pct}%` }} />
                            </div>
                            <span className="text-muted w-10 text-right">{c.pct}%</span>
                          </div>
                        ))}
                      </div>
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
