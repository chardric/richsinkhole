// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

type CardColor = 'default' | 'red' | 'green' | 'blue'

interface StatCardProps {
  title: string
  value: number | string
  subtitle?: string
  color?: CardColor
}

const COLOR_CLASSES: Record<CardColor, string> = {
  default: 'text-[#e6edf3]',
  red:     'text-danger',
  green:   'text-success',
  blue:    'text-primary',
}

const BORDER_CLASSES: Record<CardColor, string> = {
  default: 'border-border',
  red:     'border-red-800/50',
  green:   'border-green-800/50',
  blue:    'border-blue-800/50',
}

export function StatCard({ title, value, subtitle, color = 'default' }: StatCardProps) {
  const isHot = color === 'red' && typeof value === 'number' && value > 0

  return (
    <div
      className={`
        bg-surface border rounded-xl p-4 flex flex-col gap-1
        ${BORDER_CLASSES[color]}
        ${isHot ? 'stat-card--hot' : ''}
      `}
    >
      <p className="text-muted text-xs uppercase tracking-wide font-medium">{title}</p>
      <p className={`text-2xl font-bold tabular-nums ${COLOR_CLASSES[color]}`}>
        {typeof value === 'number' ? value.toLocaleString() : value}
      </p>
      {subtitle && <p className="text-muted text-xs">{subtitle}</p>}
    </div>
  )
}
