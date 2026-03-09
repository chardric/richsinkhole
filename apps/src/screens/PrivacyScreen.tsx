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
  label: string | null
  total: number
  blocked: number
  categories: Record<string, number>
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
  const [loading, setLoading] = useState(true)

  const fetchData = useCallback(async () => {
    try {
      const [s, d, h] = await Promise.all([
        apiGet<NetworkScore>('/api/network-score'),
        apiGet<PrivacyDevice[]>('/api/privacy-report'),
        apiGet<HeatmapData>('/api/heatmap'),
      ])
      setScore(s)
      setDevices(d.sort((a, b) => b.total - a.total))
      setHeatmap(h.hours)
    } catch {
      // silent — keep last data
    } finally {
      setLoading(false)
    }
  }, [])

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
            <span className="text-xs text-muted">{devices.length} devices</span>
          </div>

          {devices.length === 0 ? (
            <div className="bg-surface border border-border rounded-xl p-5 text-center">
              <p className="text-muted text-sm">No device data available</p>
            </div>
          ) : (
            <div className="bg-surface border border-border rounded-xl divide-y divide-border overflow-hidden">
              {devices.map(dev => {
                const blockPct = dev.total > 0 ? ((dev.blocked / dev.total) * 100).toFixed(1) : '0.0'
                const cats = Object.entries(dev.categories)
                  .sort(([, a], [, b]) => b - a)
                  .slice(0, 5)

                return (
                  <div key={dev.ip} className="px-4 py-3">
                    <div className="flex items-center justify-between">
                      <div className="min-w-0">
                        <span className="text-sm font-mono text-[#e6edf3]">
                          {dev.label || dev.ip}
                        </span>
                        {dev.label && (
                          <span className="text-xs text-muted ml-2">{dev.ip}</span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <span className="text-xs text-muted">
                          {dev.total.toLocaleString()} queries
                        </span>
                        <span className="pill pill-blocked text-[10px]">
                          {blockPct}% blocked
                        </span>
                      </div>
                    </div>
                    {cats.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {cats.map(([cat, count]) => (
                          <span
                            key={cat}
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-[#21262d] text-muted"
                          >
                            {cat}
                            <span className="text-[#58a6ff]">{count}</span>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
