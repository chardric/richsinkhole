// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiDelete, apiGet, apiPost } from '../api/client'
import type { AllowlistDomain, BlocklistFeed, UpdaterProgress } from '../api/types'
import { LoadingSpinner } from '../components/LoadingSpinner'
import { EmptyState } from '../components/EmptyState'
import { useToast } from '../context/ToastContext'

type Tab = 'subscriptions' | 'custom' | 'allowlist'

function relativeTime(ts: string | null): string {
  if (!ts) return 'Never'
  const diff = Date.now() - new Date(ts).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1)  return 'Just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000)     return `${(n / 1000).toFixed(0)}K`
  return n.toLocaleString()
}

// ── Add feed modal ────────────────────────────────────────────────────────────
function AddFeedModal({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const { showToast } = useToast()
  const [url,     setUrl]     = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!url.trim()) return
    setLoading(true)
    try {
      const r = await apiPost<{ imported: number }>('/api/blocklist/feeds', { url: url.trim() })
      showToast('success', `Feed added — ${r.imported.toLocaleString()} domains imported`)
      onAdded()
      onClose()
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Failed to add feed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={e => e.stopPropagation()}>
        <div className="p-4 border-b border-border">
          <h3 className="font-semibold text-[#e6edf3]">Add Subscription Feed</h3>
          <p className="text-muted text-xs mt-0.5">Supports hosts file and plain domain list formats</p>
        </div>
        <form onSubmit={handleSubmit} className="p-4 space-y-4">
          <div>
            <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Feed URL</label>
            <input
              type="url"
              value={url}
              onChange={e => setUrl(e.target.value)}
              placeholder="https://example.com/blocklist.txt"
              className="input-base"
              autoFocus
              disabled={loading}
            />
          </div>
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className="btn-secondary flex-1" disabled={loading}>Cancel</button>
            <button type="submit" className="btn-primary flex-1" disabled={loading || !url.trim()}>
              {loading ? <LoadingSpinner size={14} /> : 'Subscribe'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Add domain modal ──────────────────────────────────────────────────────────
function AddDomainModal({
  tab, onClose, onAdded,
}: { tab: 'custom' | 'allowlist'; onClose: () => void; onAdded: () => void }) {
  const { showToast } = useToast()
  const [domain, setDomain] = useState('')
  const [note,   setNote]   = useState('')
  const [saving, setSaving] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!domain.trim()) return
    setSaving(true)
    try {
      if (tab === 'custom') {
        await apiPost('/api/blocklist', { domain: domain.trim() })
      } else {
        await apiPost('/api/allowlist', { domain: domain.trim(), note: note.trim() })
      }
      showToast('success', `Domain added to ${tab === 'custom' ? 'blocked list' : 'allowlist'}`)
      onAdded()
      onClose()
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Failed to add domain')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={e => e.stopPropagation()}>
        <div className="p-4 border-b border-border">
          <h3 className="font-semibold text-[#e6edf3]">
            {tab === 'custom' ? 'Block a Domain' : 'Allow a Domain'}
          </h3>
          <p className="text-muted text-xs mt-0.5">
            {tab === 'custom'
              ? 'Manually block a specific domain'
              : 'This domain will bypass the blocklist entirely'}
          </p>
        </div>
        <form onSubmit={handleSubmit} className="p-4 space-y-3">
          <div>
            <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Domain</label>
            <input
              type="text"
              value={domain}
              onChange={e => setDomain(e.target.value)}
              placeholder="example.com"
              className="input-base"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              autoFocus
            />
          </div>
          {tab === 'allowlist' && (
            <div>
              <label className="block text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-1.5">Note (optional)</label>
              <input
                type="text"
                value={note}
                onChange={e => setNote(e.target.value)}
                placeholder="Why this domain is allowed"
                className="input-base"
              />
            </div>
          )}
          <div className="flex gap-2 pt-1">
            <button type="button" onClick={onClose} className="btn-secondary flex-1">Cancel</button>
            <button type="submit" className="btn-primary flex-1" disabled={saving || !domain.trim()}>
              {saving ? <LoadingSpinner size={14} /> : tab === 'custom' ? 'Block Domain' : 'Allow Domain'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Feed card ─────────────────────────────────────────────────────────────────
function FeedCard({
  feed, onDelete, onSync, deleting, syncing,
}: {
  feed: BlocklistFeed
  onDelete: (f: BlocklistFeed) => void
  onSync:   (f: BlocklistFeed) => void
  deleting: boolean
  syncing:  boolean
}) {
  const hostname = (() => { try { return new URL(feed.url).hostname } catch { return feed.url } })()
  return (
    <div className="bg-surface border border-border rounded-xl px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-[#e6edf3] truncate">{feed.name}</span>
            {feed.domain_count > 0 && (
              <span className="pill bg-[#1f2937] text-[#9ca3af] text-[10px]">{formatCount(feed.domain_count)}</span>
            )}
            {feed.is_builtin && (
              <span className="pill bg-blue-950/60 text-blue-400 text-[10px]">built-in</span>
            )}
          </div>
          <p className="text-xs text-muted truncate mt-0.5">{hostname}</p>
          <p className="text-xs text-muted mt-0.5">
            Synced: <span className="text-[#8b949e]">{relativeTime(feed.last_synced)}</span>
          </p>
        </div>
        {!feed.is_builtin && (
          <div className="flex items-center gap-1 flex-shrink-0">
            <button
              onClick={() => onSync(feed)}
              disabled={syncing || deleting}
              title="Re-sync"
              className="text-muted hover:text-[#58a6ff] transition-colors p-1.5 rounded min-w-[36px] min-h-[36px] flex items-center justify-center"
            >
              {syncing ? <LoadingSpinner size={14} /> : (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              )}
            </button>
            <button
              onClick={() => onDelete(feed)}
              disabled={deleting || syncing}
              title="Remove feed"
              className="text-muted hover:text-danger transition-colors p-1.5 rounded min-w-[36px] min-h-[36px] flex items-center justify-center"
            >
              {deleting ? <LoadingSpinner size={14} /> : (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Subscriptions tab ─────────────────────────────────────────────────────────
function SubscriptionsTab() {
  const { showToast } = useToast()
  const [feeds,        setFeeds]        = useState<BlocklistFeed[]>([])
  const [loading,      setLoading]      = useState(true)
  const [showAdd,      setShowAdd]      = useState(false)
  const [deleting,     setDeleting]     = useState<number | null>(null)
  const [syncing,      setSyncing]      = useState<number | null>(null)
  const [totalDomains, setTotalDomains] = useState(0)
  const [updating,     setUpdating]     = useState(false)
  const [progress,     setProgress]     = useState<{ stage: string; detail: string; pct: number } | null>(null)

  const fetchFeeds = useCallback(async () => {
    try {
      const [feedList, counts] = await Promise.all([
        apiGet<BlocklistFeed[]>('/api/blocklist/feeds'),
        apiGet<{ total: number }>('/api/blocklist?limit=1'),
      ])
      setFeeds(feedList)
      setTotalDomains(counts.total)
    } catch {
      showToast('error', 'Failed to load feeds')
    } finally {
      setLoading(false)
    }
  }, [showToast])

  useEffect(() => { fetchFeeds() }, [fetchFeeds])

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function triggerUpdate() {
    setUpdating(true)
    try {
      await apiPost('/api/updater/run', {})
      showToast('info', 'Update triggered')
      // Start polling progress
      pollRef.current = setInterval(async () => {
        try {
          const p = await apiGet<UpdaterProgress>('/api/updater/progress')
          if (!p.running) {
            setProgress(null)
            setUpdating(false)
            if (pollRef.current) clearInterval(pollRef.current)
            pollRef.current = null
            fetchFeeds()
            return
          }
          setProgress({ stage: p.stage || '', detail: p.detail || '', pct: p.pct || 0 })
        } catch { /* ignore */ }
      }, 2000)
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Update failed')
      setUpdating(false)
    }
  }

  useEffect(() => { return () => { if (pollRef.current) clearInterval(pollRef.current) } }, [])

  async function handleDelete(feed: BlocklistFeed) {
    setDeleting(feed.id)
    try {
      await apiDelete(`/api/blocklist/feeds/${feed.id}`)
      showToast('success', `Removed feed: ${feed.name}`)
      fetchFeeds()
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Delete failed')
    } finally {
      setDeleting(null)
    }
  }

  async function handleSync(feed: BlocklistFeed) {
    setSyncing(feed.id)
    try {
      const r = await apiPost<{ synced: number }>(`/api/blocklist/feeds/${feed.id}/sync`, {})
      showToast('success', `Synced ${r.synced.toLocaleString()} domains`)
      fetchFeeds()
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Sync failed')
    } finally {
      setSyncing(null)
    }
  }

  if (loading) return (
    <div className="flex items-center justify-center flex-1"><LoadingSpinner size={28} /></div>
  )

  const builtinFeeds = feeds.filter(f => f.is_builtin)
  const customFeeds  = feeds.filter(f => !f.is_builtin)

  return (
    <>
      <div className="px-4 py-3 border-b border-border flex items-center justify-between flex-shrink-0">
        <div>
          <span className="text-sm font-semibold text-[#e6edf3]">{formatCount(totalDomains)} domains</span>
          <span className="text-xs text-muted ml-2">from {feeds.length} source{feeds.length !== 1 ? 's' : ''}</span>
        </div>
        <div className="flex gap-2">
          <button onClick={triggerUpdate} disabled={updating} className="btn-secondary px-3 py-1.5 text-xs">
            {updating ? <LoadingSpinner size={12} /> : 'Update Now'}
          </button>
          <button onClick={() => setShowAdd(true)} className="btn-primary px-3 py-1.5 text-xs gap-1.5">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            Add Feed
          </button>
        </div>
      </div>

      {/* Update progress bar */}
      {progress && (
        <div className="px-4 py-2 border-b border-border bg-[#161b22]">
          <div className="flex justify-between text-xs mb-1">
            <span className="text-[#e6edf3]">{progress.stage}</span>
            <span className="text-muted font-mono">{progress.pct}%</span>
          </div>
          <div className="w-full h-1.5 bg-[#21262d] rounded-full overflow-hidden">
            <div className="h-full bg-blue-500 rounded-full transition-all duration-300" style={{ width: `${progress.pct}%` }} />
          </div>
          {progress.detail && <p className="text-[10px] text-muted mt-1">{progress.detail}</p>}
        </div>
      )}

      <div className="flex-1 scroll-area">
        {feeds.length === 0 ? (
          <EmptyState title="No subscription feeds" subtitle="Add a blocklist feed URL to start blocking domains" />
        ) : (
          <div className="p-4 space-y-5">
            {builtinFeeds.length > 0 && (
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <svg className="w-3.5 h-3.5 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                  </svg>
                  <span className="text-xs font-semibold text-muted uppercase tracking-wider">Built-in Sources</span>
                  <span className="text-xs text-muted/60">· managed via sources.yml</span>
                </div>
                <div className="space-y-2">
                  {builtinFeeds.map(feed => (
                    <FeedCard key={feed.id} feed={feed} onDelete={handleDelete} onSync={handleSync}
                      deleting={deleting === feed.id} syncing={syncing === feed.id} />
                  ))}
                </div>
              </div>
            )}

            {customFeeds.length > 0 && (
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <svg className="w-3.5 h-3.5 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                  </svg>
                  <span className="text-xs font-semibold text-muted uppercase tracking-wider">My Subscriptions</span>
                </div>
                <div className="space-y-2">
                  {customFeeds.map(feed => (
                    <FeedCard key={feed.id} feed={feed} onDelete={handleDelete} onSync={handleSync}
                      deleting={deleting === feed.id} syncing={syncing === feed.id} />
                  ))}
                </div>
              </div>
            )}

            <div className="flex items-start gap-2.5 bg-blue-950/30 border border-blue-800/30 rounded-xl px-3.5 py-3">
              <svg className="w-4 h-4 text-[#58a6ff] flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <p className="text-xs text-[#8b949e] leading-relaxed">
                Built-in feeds auto-sync daily. To unblock a specific domain, add it to the{' '}
                <strong className="text-[#e6edf3]">Allowlist</strong> tab — it stays whitelisted even after re-sync.
              </p>
            </div>
          </div>
        )}
      </div>

      {showAdd && <AddFeedModal onClose={() => setShowAdd(false)} onAdded={fetchFeeds} />}
    </>
  )
}

// ── Custom blocked tab ────────────────────────────────────────────────────────
function CustomTab() {
  const { showToast } = useToast()
  const [domains,  setDomains]  = useState<Array<{ domain: string; added_at: string }>>([])
  const [search,   setSearch]   = useState('')
  const [total,    setTotal]    = useState(0)
  const [loading,  setLoading]  = useState(true)
  const [showAdd,  setShowAdd]  = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)

  const fetchDomains = useCallback(async () => {
    try {
      const data = await apiGet<{ total: number; domains: Array<{ domain: string; added_at: string }> }>(
        `/api/blocklist/custom?limit=500&search=${encodeURIComponent(search)}`
      )
      setDomains(data.domains)
      setTotal(data.total)
    } catch {
      showToast('error', 'Failed to load custom domains')
    } finally {
      setLoading(false)
    }
  }, [showToast, search])

  useEffect(() => {
    const t = setTimeout(() => fetchDomains(), 300)
    return () => clearTimeout(t)
  }, [fetchDomains])

  async function handleDelete(domain: string) {
    setDeleting(domain)
    try {
      await apiDelete(`/api/blocklist/${encodeURIComponent(domain)}`)
      showToast('success', `Removed ${domain}`)
      setDomains(prev => prev.filter(d => d.domain !== domain))
      setTotal(prev => Math.max(0, prev - 1))
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Delete failed')
    } finally {
      setDeleting(null)
    }
  }

  return (
    <>
      <div className="px-4 py-3 border-b border-border space-y-2 flex-shrink-0">
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 11A6 6 0 115 11a6 6 0 0112 0z" />
          </svg>
          <input type="search" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search custom blocked domains..." className="input-base pl-9" />
        </div>
        <button onClick={() => setShowAdd(true)} className="btn-primary w-full gap-2">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Block a Domain
        </button>
      </div>

      <div className="px-4 py-2 flex-shrink-0 flex items-center justify-between border-b border-border">
        <span className="text-xs text-muted">{total} custom domain{total !== 1 ? 's' : ''} blocked</span>
        {loading && <LoadingSpinner size={14} />}
      </div>

      {loading && domains.length === 0 ? (
        <div className="flex items-center justify-center flex-1"><LoadingSpinner size={28} /></div>
      ) : domains.length === 0 ? (
        <EmptyState
          title={search ? 'No matches' : 'No custom blocks'}
          subtitle={search ? 'Try a different search term' : 'Manually blocked domains appear here'}
        />
      ) : (
        <div className="flex-1 scroll-area divide-y divide-border">
          {domains.map(item => (
            <div key={item.domain} className="flex items-center gap-3 px-4 py-3">
              <span className="flex-1 text-sm text-[#e6edf3] font-mono truncate">{item.domain}</span>
              <button onClick={() => handleDelete(item.domain)} disabled={deleting === item.domain}
                className="text-muted hover:text-danger transition-colors p-1.5 rounded flex-shrink-0 min-w-[44px] min-h-[44px] flex items-center justify-center">
                {deleting === item.domain ? <LoadingSpinner size={14} /> : (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                )}
              </button>
            </div>
          ))}
        </div>
      )}
      {showAdd && <AddDomainModal tab="custom" onClose={() => setShowAdd(false)} onAdded={fetchDomains} />}
    </>
  )
}

// ── Allowlist tab ─────────────────────────────────────────────────────────────
function AllowlistTab() {
  const { showToast } = useToast()
  const [domains,  setDomains]  = useState<AllowlistDomain[]>([])
  const [search,   setSearch]   = useState('')
  const [loading,  setLoading]  = useState(true)
  const [showAdd,  setShowAdd]  = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)

  const fetchList = useCallback(async () => {
    try {
      setDomains(await apiGet<AllowlistDomain[]>('/api/allowlist'))
    } catch {
      showToast('error', 'Failed to load allowlist')
    } finally {
      setLoading(false)
    }
  }, [showToast])

  useEffect(() => { fetchList() }, [fetchList])

  async function handleDelete(domain: string) {
    setDeleting(domain)
    try {
      await apiDelete(`/api/allowlist/${encodeURIComponent(domain)}`)
      showToast('success', `Removed ${domain}`)
      setDomains(prev => prev.filter(d => d.domain !== domain))
    } catch (err: unknown) {
      showToast('error', err instanceof Error ? err.message : 'Delete failed')
    } finally {
      setDeleting(null)
    }
  }

  const filtered = search.trim()
    ? domains.filter(d => d.domain.includes(search.toLowerCase()))
    : domains

  return (
    <>
      <div className="px-4 py-3 border-b border-border space-y-2 flex-shrink-0">
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 11A6 6 0 115 11a6 6 0 0112 0z" />
          </svg>
          <input type="search" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search allowed domains..." className="input-base pl-9" />
        </div>
        <button onClick={() => setShowAdd(true)} className="btn-secondary w-full gap-2">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
          </svg>
          Allow a Domain
        </button>
      </div>

      <div className="px-4 py-2 flex-shrink-0 border-b border-border">
        <span className="text-xs text-muted">{filtered.length} domain{filtered.length !== 1 ? 's' : ''} allowed</span>
      </div>

      {loading ? (
        <div className="flex items-center justify-center flex-1"><LoadingSpinner size={28} /></div>
      ) : filtered.length === 0 ? (
        <EmptyState
          title="No domains"
          subtitle={search ? 'No allowed domains match your search' : 'Add domains that should never be blocked'}
        />
      ) : (
        <div className="flex-1 scroll-area divide-y divide-border">
          {filtered.map(item => (
            <div key={item.domain} className="flex items-center gap-3 px-4 py-3">
              <div className="flex-1 min-w-0">
                <p className="text-sm text-[#e6edf3] font-mono truncate">{item.domain}</p>
                {item.note && <p className="text-xs text-muted truncate mt-0.5">{item.note}</p>}
              </div>
              <button onClick={() => handleDelete(item.domain)} disabled={deleting === item.domain}
                className="text-muted hover:text-danger transition-colors p-1.5 rounded flex-shrink-0 min-w-[44px] min-h-[44px] flex items-center justify-center">
                {deleting === item.domain ? <LoadingSpinner size={14} /> : (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                )}
              </button>
            </div>
          ))}
        </div>
      )}
      {showAdd && <AddDomainModal tab="allowlist" onClose={() => setShowAdd(false)} onAdded={fetchList} />}
    </>
  )
}

// ── Main screen ───────────────────────────────────────────────────────────────
export function BlocklistScreen() {
  const [activeTab, setActiveTab] = useState<Tab>('subscriptions')

  const tabs: Array<{ id: Tab; label: string; icon: React.ReactNode }> = [
    {
      id: 'subscriptions', label: 'Subscriptions',
      icon: <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 10h16M4 14h10M4 18h7" /></svg>,
    },
    {
      id: 'custom', label: 'Custom',
      icon: <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" /></svg>,
    },
    {
      id: 'allowlist', label: 'Allowlist',
      icon: <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>,
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

      {activeTab === 'subscriptions' && <SubscriptionsTab />}
      {activeTab === 'custom'        && <CustomTab />}
      {activeTab === 'allowlist'     && <AllowlistTab />}
    </div>
  )
}
