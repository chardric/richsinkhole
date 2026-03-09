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
  name: string
  start_time: string
  end_time: string
  days: string
  target_profile: string
  enabled: boolean
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
