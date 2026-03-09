// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

interface EmptyStateProps {
  icon?: React.ReactNode
  title: string
  subtitle?: string
}

export function EmptyState({ icon, title, subtitle }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
      {icon && (
        <div className="text-muted mb-3 opacity-40">
          {icon}
        </div>
      )}
      <p className="text-[#e6edf3] font-medium">{title}</p>
      {subtitle && <p className="text-muted text-sm mt-1">{subtitle}</p>}
    </div>
  )
}
