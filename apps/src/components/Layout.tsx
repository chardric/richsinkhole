// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

interface NavItem {
  path: string
  label: string
  icon: React.ReactNode
  mobileLabel?: string
}

function Logo() {
  return (
    <svg width="28" height="28" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="16" cy="16" r="14" stroke="#58a6ff" strokeWidth="2" fill="none" />
      <circle cx="16" cy="16" r="9"  stroke="#58a6ff" strokeWidth="2" fill="none" opacity="0.7" />
      <circle cx="16" cy="16" r="4"  fill="#58a6ff" />
    </svg>
  )
}

const HomeIcon = () => (
  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M3 12l9-9 9 9M5 10v9a1 1 0 001 1h4v-5h4v5h4a1 1 0 001-1v-9" />
  </svg>
)
const LogsIcon = () => (
  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 10h16M4 14h10M4 18h7" />
  </svg>
)
const BlocklistIcon = () => (
  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
  </svg>
)
const DevicesIcon = () => (
  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
  </svg>
)
const SecurityIcon = () => (
  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
  </svg>
)
const SettingsIcon = () => (
  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
  </svg>
)
const MoreIcon = () => (
  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
  </svg>
)

const DESKTOP_NAV: NavItem[] = [
  { path: '/dashboard',  label: 'Dashboard',   icon: <HomeIcon /> },
  { path: '/logs',       label: 'Query Logs',  icon: <LogsIcon /> },
  { path: '/blocklist',  label: 'Blocklist',   icon: <BlocklistIcon /> },
  { path: '/devices',    label: 'Devices',     icon: <DevicesIcon /> },
  { path: '/security',   label: 'Security',    icon: <SecurityIcon /> },
  { path: '/settings',   label: 'Settings',    icon: <SettingsIcon /> },
]

const MOBILE_TABS: NavItem[] = [
  { path: '/dashboard',  label: 'Dashboard', mobileLabel: 'Home',     icon: <HomeIcon /> },
  { path: '/logs',       label: 'Logs',                                icon: <LogsIcon /> },
  { path: '/blocklist',  label: 'Blocklist', mobileLabel: 'Block',    icon: <BlocklistIcon /> },
  { path: '/devices',    label: 'Devices',                             icon: <DevicesIcon /> },
  { path: '/more',       label: 'More',                                icon: <MoreIcon /> },
]

const MORE_ITEMS: NavItem[] = [
  { path: '/security',  label: 'Security',  icon: <SecurityIcon /> },
  { path: '/settings',  label: 'Settings',  icon: <SettingsIcon /> },
]

interface LayoutProps {
  children: React.ReactNode
}

export function Layout({ children }: LayoutProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const { serverUrl } = useAuth()

  const isActive = (path: string) => {
    if (path === '/more') {
      return location.pathname === '/security' || location.pathname === '/settings'
    }
    return location.pathname === path
  }

  const serverHost = serverUrl
    ? (() => { try { return new URL(serverUrl).hostname } catch { return serverUrl } })()
    : ''

  return (
    <div className="flex h-full bg-bg overflow-hidden">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex flex-col w-[220px] border-r border-border bg-surface flex-shrink-0">
        {/* Logo */}
        <div className="flex items-center gap-3 px-4 py-4 border-b border-border">
          <Logo />
          <div>
            <p className="text-[#e6edf3] font-semibold text-sm leading-tight">RichSinkhole</p>
            {serverHost && (
              <p className="text-muted text-xs truncate max-w-[140px]">{serverHost}</p>
            )}
          </div>
        </div>

        {/* Nav items */}
        <nav className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {DESKTOP_NAV.map(item => (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              className={`nav-item w-full ${isActive(item.path) ? 'active' : ''}`}
            >
              {item.icon}
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Mobile header */}
        <header className="md:hidden flex items-center gap-3 px-4 py-3 border-b border-border bg-surface flex-shrink-0">
          <Logo />
          <div className="flex-1">
            <p className="text-[#e6edf3] font-semibold text-sm leading-tight">RichSinkhole</p>
            {serverHost && <p className="text-muted text-xs">{serverHost}</p>}
          </div>
        </header>

        {/* Page content */}
        <div className="flex-1 overflow-hidden">
          {location.pathname === '/more' ? (
            <MoreMenu onNavigate={(path) => navigate(path)} />
          ) : (
            children
          )}
        </div>

        {/* Mobile bottom nav */}
        <nav className="md:hidden flex border-t border-border bg-surface flex-shrink-0">
          {MOBILE_TABS.map(item => (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              className={`bottom-nav-item ${isActive(item.path) ? 'active' : ''}`}
            >
              {item.icon}
              <span className="text-[10px]">{item.mobileLabel || item.label}</span>
            </button>
          ))}
        </nav>
      </main>
    </div>
  )
}

function MoreMenu({ onNavigate }: { onNavigate: (path: string) => void }) {
  return (
    <div className="h-full scroll-area">
      <div className="p-4 space-y-2">
        <p className="text-muted text-xs uppercase tracking-wide px-2 mb-3">More Options</p>
        {MORE_ITEMS.map(item => (
          <button
            key={item.path}
            onClick={() => onNavigate(item.path)}
            className="nav-item w-full text-base"
            style={{ minHeight: 52 }}
          >
            {item.icon}
            <span className="ml-1">{item.label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
