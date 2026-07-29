export type Race = {
  race_id: string
  date: string
  venue: string | null
  venue_code: string
  race_no: number
  is_jra: boolean
  scored: boolean
  has_pred: boolean
  has_review: boolean
  /** 回顧が速報成績のままか（確定情報で作り直すと false になる） */
  review_is_realtime: boolean
  has_result: boolean
  pred_file: string | null
  review_file: string | null
  race_name?: string | null
  race_class?: string | null
  surface?: string | null
  distance?: number | null
  num_horses?: number | null
  baba?: string | null
  has_local_only?: boolean
  horse_names?: string[]
  kaiji?: number
  nichiji?: number
  start_time?: string
  error?: string
}

export type RaceList = {
  total: number
  offset: number
  limit: number
  races: Race[]
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) {
    let detail = `${res.status}`
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* 本文がJSONでない場合はステータスのみ */
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

/** サーバーが公開モードで動いているか、誰でログインしているか。 */
export type AppMode = {
  public_mode: boolean
  user_id: string | null
}

export function fetchMode(): Promise<AppMode> {
  return getJson<AppMode>('/api/mode')
}

export function fetchRaces(params: {
  date?: string
  venue?: string
  q?: string
  jraOnly?: boolean
  limit?: number
}): Promise<RaceList> {
  const sp = new URLSearchParams()
  if (params.date) sp.set('date', params.date)
  if (params.venue) sp.set('venue', params.venue)
  if (params.q) sp.set('q', params.q)
  if (params.jraOnly) sp.set('jra_only', 'true')
  sp.set('limit', String(params.limit ?? 500))
  return getJson<RaceList>(`/api/races?${sp.toString()}`)
}

import type { EvHorse } from './ev/evCore'

export type SavedOdds = {
  race_id: string
  updated_at: string | null
  ev_core_version: string | null
  tansho: Record<string, number>
  bets: Record<string, number>
}

export function fetchEvData(raceId: string): Promise<{ race_id: string; horses: EvHorse[] }> {
  return getJson(`/api/races/${raceId}/ev-data`)
}

export function fetchOdds(raceId: string): Promise<SavedOdds> {
  return getJson(`/api/races/${raceId}/odds`)
}

export async function saveOdds(
  raceId: string,
  body: { tansho: Record<string, number>; bets: Record<string, number>; ev_core_version: string },
): Promise<SavedOdds> {
  const res = await fetch(`/api/races/${raceId}/odds`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`保存に失敗しました (${res.status})`)
  return res.json() as Promise<SavedOdds>
}

// ── メモ馬 ─────────────────────────────────────────────────────
export type SourceRace = {
  日付: string
  場所: string
  R: number | string
  レース名: string
  クラス: string
}

export type MemoEntry = {
  key: string
  馬名: string
  登録日: string
  追加者: string
  元レース: SourceRace
  メモ: string
  days_left?: number
}

export type MemoHorse = {
  name: string
  entries: MemoEntry[]
  entry_count: number
  latest_race_date: string
  has_memo: boolean
  registered_at: string
}

export type MemoList = {
  file_hash: string
  total_entries: number
  total_horses: number
  horses: MemoHorse[]
}

/** 409（競合・重複）を呼び出し側で見分けられるようにする。 */
export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, detail: unknown, message: string) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail: unknown = null
    try {
      detail = (await res.json()).detail
    } catch {
      /* 本文がJSONでない */
    }
    const msg = typeof detail === 'string' ? detail : `エラー (${res.status})`
    throw new ApiError(res.status, detail, msg)
  }
  return res.json() as Promise<T>
}

export function fetchMemo(): Promise<MemoList> {
  return getJson('/api/memo')
}

export function checkMemoName(
  name: string,
): Promise<{ name: string; exists: boolean; entries: MemoEntry[] }> {
  return getJson(`/api/memo/check?name=${encodeURIComponent(name)}`)
}

export function addMemo(body: {
  馬名: string
  元レース: SourceRace
  メモ: string
  追加者: string
  expected_hash: string | null
  overwrite: boolean
}) {
  return postJson<{ key: string; file_hash: string; entry: MemoEntry }>('/api/memo/add', body)
}

export function updateMemo(body: {
  key: string
  メモ?: string
  追加者?: string
  expected_hash: string | null
}) {
  return postJson<{ key: string; file_hash: string; entry: MemoEntry }>('/api/memo/update', body)
}

export function archiveMemo(body: { key: string; expected_hash: string | null }) {
  return postJson<{ key: string; file_hash: string }>('/api/memo/archive', body)
}

export function restoreMemo(body: { key: string; expected_hash: string | null }) {
  return postJson<{ key: string; file_hash: string }>('/api/memo/restore', body)
}

export function fetchArchivedMemo(): Promise<{ total: number; entries: MemoEntry[] }> {
  return getJson('/api/memo/archived')
}

// ── 注目レース ───────────────────────────────────────────────
export function fetchFeatured(): Promise<{ race_ids: string[] }> {
  return getJson('/api/featured')
}

export function setFeatured(raceId: string, featured: boolean) {
  return postJson<{ race_id: string; featured: boolean; total: number }>(
    '/api/featured', { race_id: raceId, featured },
  )
}

export function predUrl(raceId: string): string {
  return `/api/races/${raceId}/pred.html`
}

export function reviewUrl(raceId: string): string {
  return `/api/races/${raceId}/review.html`
}
