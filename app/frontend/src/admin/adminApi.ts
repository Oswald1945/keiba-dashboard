import { ApiError } from '../api'

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) {
    let detail: unknown = null
    try {
      detail = (await res.json()).detail
    } catch {
      /* JSONでない */
    }
    throw new ApiError(res.status, detail, typeof detail === 'string' ? detail : `エラー (${res.status})`)
  }
  return res.json() as Promise<T>
}

async function post<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
  if (!res.ok) {
    let detail: unknown = null
    try {
      detail = (await res.json()).detail
    } catch {
      /* JSONでない */
    }
    throw new ApiError(res.status, detail, typeof detail === 'string' ? detail : `エラー (${res.status})`)
  }
  return res.json() as Promise<T>
}

export type RaceTarget = { date: string; jyo: string; race_no: number }

export type PredictableRace = {
  race_no: number
  race_id: string
  name: string
  race_class: string
  num_horses: number
  is_maiden: boolean
  rcode: string
}

export type PredictableGroup = {
  date: string
  jyo: string
  venue: string
  kaiji: string
  nichiji: string
  races: PredictableRace[]
}

export type Job = {
  id: string
  name: string
  status: 'queued' | 'running' | 'ok' | 'error' | 'cancelled'
  started_at: string | null
  ended_at: string | null
  error: string | null
  result: Record<string, unknown>
  steps_done: number
  steps_total: number
  line_count: number
  lines: string[]
}

export type AdminStatus = {
  race_db: { ok: boolean; path: string; latest_nl?: string; latest_rt?: string; error?: string }
  jvlink: {
    tool_dir: string
    exe_exists: boolean
    setting_exists: boolean
    update_script_exists: boolean
    checklist: string[]
  }
  realtime: { available: boolean; enabled?: boolean; kaisai_dates?: string[]; error?: string }
  running_job: Job | null
  recent_jobs: Job[]
}

export type ReviewDay = {
  date: string
  count: number
  needs_realtime?: boolean
  races: (RaceTarget & { race_id: string; venue: string; race_name?: string })[]
}

export type ReviewOverview = {
  pending: ReviewDay[]
  pending_total: number
  upgradable: ReviewDay[]
  upgradable_total: number
  realtime_waiting: ReviewDay[]
  realtime_waiting_total: number
  realtime_target_dates: string[]
}

export type BabaVenue = {
  venue: string
  kaisai: string | null
  fetched_date: string | null
  course_used: string | null
  measured_at: { cushion: string | null; moisture: string | null }
  rain_mm: number | null
  suggested: Record<string, string | number | null>
  moisture_detail: Record<string, Record<string, number | null>>
  estimate_note: Record<string, string | null>
  announced: { 芝: string | null; ダート: string | null; 天候: string | null; source: string | null }
  saved: Record<string, string | number>
}

export type BabaPreview = {
  date: string
  error: string | null
  source: string
  notice: string
  venues: BabaVenue[]
}

export type ResultStatus = {
  date: string
  total: number
  confirmed: number
  all_confirmed: boolean
  races: {
    venue: string
    race_no: number
    race_id: string | null
    num_horses: number
    fin_nl: number
    fin_rt: number
    source: string | null
    state: string
  }[]
}

export type GeneratedRace = {
  race_id: string
  date: string
  venue: string | null
  race_no: number
  race_name?: string | null
  race_class?: string | null
  has_pred: boolean
  has_review: boolean
  published_pred: string | null
  published_review: string | null
}

/** サーバーへ反映済みかどうか。available=false は「サーバーに聞けなかった」。 */
export type AppPublishStatus = {
  date: string
  available: boolean
  races: Record<string, { pred: 'sent' | 'pending' | 'none'; review: 'sent' | 'pending' | 'none' }>
}

export const adminApi = {
  status: () => get<AdminStatus>('/api/admin/status'),
  generated: (date: string) =>
    get<{ date: string; races: GeneratedRace[] }>(`/api/admin/generated?date=${date}`),
  generatedDates: () =>
    get<{ dates: { date: string; races: number }[] }>('/api/admin/generated/dates'),
  predictable: () => get<{ groups: PredictableGroup[] }>('/api/admin/races/predictable'),
  reviews: () => get<ReviewOverview>('/api/admin/reviews/status'),
  results: (date: string) => get<ResultStatus>(`/api/admin/results/${date}`),
  babaPreview: (date: string) => get<BabaPreview>(`/api/admin/baba/preview?date=${date}`),
  babaSave: (date: string, venues: Record<string, Record<string, unknown>>) =>
    post<{ date: string; saved: unknown }>('/api/admin/baba/save', { date, venues }),

  job: (id: string, after = 0) => get<Job>(`/api/admin/jobs/${id}?after=${after}`),
  cancel: (id: string) => post<{ cancelled: string }>(`/api/admin/jobs/${id}/cancel`),

  update: () => post<{ job_id: string }>('/api/admin/update'),
  export: (targets: RaceTarget[]) => post<{ job_id: string }>('/api/admin/export', { targets }),
  smartrc: (targets: RaceTarget[]) => post<{ job_id: string }>('/api/admin/smartrc', { targets }),
  predict: (force: boolean) => post<{ job_id: string }>('/api/admin/predict', { force }),
  fetchResults: (date: string) => post<{ job_id: string }>('/api/admin/fetch-results', { date }),
  review: (targets: RaceTarget[]) => post<{ job_id: string }>('/api/admin/review', { targets }),
  reviewAuto: () => post<{ job_id: string }>('/api/admin/review-auto'),
  // GitHub Pages への公開。処理は残してあるが画面からは呼んでいない。
  publish: (raceIds: string[]) => post<{ job_id: string }>('/api/admin/publish', { race_ids: raceIds }),
  appPublish: (raceIds: string[]) =>
    post<{ job_id: string }>('/api/admin/app-publish', { race_ids: raceIds }),
  appPublishStatus: (date: string) =>
    get<AppPublishStatus>(`/api/admin/app-publish/status?date=${date}`),
  rescore: (dateFrom: string, dateTo: string, outFile = 'factor_rows_p4.jsonl') =>
    post<{ job_id: string }>('/api/admin/rescore', {
      date_from: dateFrom, date_to: dateTo, out_file: outFile,
    }),
}
