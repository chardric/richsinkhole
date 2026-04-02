// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

export interface Stats {
  total: number
  blocked: number
  forwarded: number
  block_pct: number
  unique_clients: number
  top_blocked: Array<{ domain: string; count: number }>
  top_clients: Array<{ ip: string; count: number }>
}

export interface QueryLog {
  id: number
  ts: string
  client_ip: string
  domain: string
  qtype: string
  action: string
  upstream: string | null
  response_ms: number | null
}

export interface Device {
  ip: string
  device_type: string
  confidence: number
  first_seen: string
  last_seen: string
  label: string | null
  profile: string
  parental_enabled: boolean
  parental_block_social: number
  parental_block_gaming: number
  parental_social_limit: number
  parental_gaming_limit: number
  mac: string | null
  vendor: string | null
}

export interface SecurityBlock {
  ip: string
  blocked_at: string
  expires_at: string
  reason: string
  reason_label: string
  query_count: number
}

export interface SecurityEvent {
  ts: string
  event_type: string
  client_ip: string
  domain: string
  detail: string | null
  resolved_ip: string | null
}

export interface Health {
  status: string
  components: Record<string, string>
}

export interface BlocklistPage {
  total: number
  page: number
  limit: number
  pages: number
  domains: Array<{ domain: string; added_at: string }>
}

export interface BlocklistFeed {
  id: number
  url: string
  name: string
  domain_count: number
  last_synced: string | null
  enabled: boolean
  is_builtin: boolean
}

export interface AllowlistDomain {
  domain: string
  note: string | null
  added_at: string
}

export interface AppSettings {
  youtube_redirect_enabled: boolean
  captive_portal_enabled: boolean
  server_ip?: string
}

export interface NtpStatus {
  running: boolean
}

export interface ServiceInfo {
  running: boolean
  status: string
  started_at?: string
}

export interface ServicesStatus {
  dns: ServiceInfo
  unbound: ServiceInfo
  nginx: ServiceInfo
}

export interface UpdateSchedule {
  update_hour: number
  update_minute: number
  update_frequency: 'daily' | 'weekly' | 'monthly'
  update_day_of_week: number    // 0=Mon … 6=Sun
  update_day_of_month: number   // 1-28
  source_stale_days: number     // 30-365
}

export interface UpdaterProgress {
  running: boolean
  stage?: string
  detail?: string
  pct?: number
}

export interface SecurityStats {
  active_blocks: number
  total_blocks: number
  ratelimited_24h: number
  nxdomain_24h: number
  rebinding_24h: number
  anomaly_24h: number
  iot_flood_24h: number
}

export interface ParentalSettings {
  ip: string
  parental_enabled: boolean
  parental_block_social: boolean
  parental_block_gaming: boolean
  parental_social_limit: number
  parental_gaming_limit: number
}

export interface Schedule {
  id: number
  label: string
  client_ip: string
  start_time: string
  end_time: string
  days: string
  days_label: string
  enabled: boolean
  grace_minutes: number
}

export interface NetworkScore {
  score: number
  grade: string
  breakdown: Record<string, { score: number; max: number; detail: string }>
}

export interface PrivacyDevice {
  ip: string
  label: string | null
  total: number
  blocked: number
  categories: Record<string, number>
}

export interface HeatmapData {
  hours: number[]
}

export interface DnsRecord {
  id: number
  hostname: string
  type: string
  value: string
  ttl: number
  enabled: boolean
}

export interface ProxyRule {
  id: number
  hostname: string
  target: string
  enabled: boolean
  created_at: string
}

// Blocked services (AdGuard-style toggleable service blocks)
export interface BlockedServiceGroup {
  id: string
  name: string
}

export interface BlockedService {
  id: string
  name: string
  group: string
  domain_count: number
  enabled: boolean
}

export interface BlockedServicesResponse {
  groups: BlockedServiceGroup[]
  services: BlockedService[]
}

// DNS speed test
export interface SpeedTestResult {
  historical: {
    total_queries: number
    avg_ms: number | null
    min_ms: number | null
    max_ms: number | null
    p50_ms: number | null
    p95_ms: number | null
  }
  live: {
    probes: Array<{ domain: string; latency_ms: number | null }>
    avg_ms: number | null
  }
}

// App usage per device
export interface AppUsage {
  app: string
  queries: number
  sessions: number
  estimated_minutes: number
}

export interface AppUsageResponse {
  ip: string
  range: string
  apps: AppUsage[]
}

// Device stats (extended)
export interface DeviceStats {
  ip: string
  label: string | null
  device_type: string | null
  total: number
  blocked: number
  forwarded: number
  block_pct: number
  bandwidth_saved_mb: number
  bandwidth_used_mb: number
  top_blocked_domains: Array<{ domain: string; count: number }>
  top_forwarded_domains: Array<{ domain: string; count: number }>
  recent_queries: Array<{ ts: string; domain: string; qtype: string; action: string }>
}

// NTP clients
export interface NtpClient {
  ip: string
  ntp_packets: number
  last_sync_ago: number
  label: string
  device_type: string
}

export interface NtpClientsResponse {
  clients: NtpClient[]
}

// Privacy report (updated)
export interface PrivacyReportDevice {
  ip: string
  label: string
  device_type: string
  total_forwarded: number
  companies: Array<{ company: string; count: number; pct: number }>
}
