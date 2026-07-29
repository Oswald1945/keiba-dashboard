import { useCallback, useEffect, useMemo, useState } from 'react'
import JobLog from './JobLog'
import Collapsible from '../ui/Collapsible'
import {
  adminApi,
  type AdminStatus,
  type BabaPreview,
  type GeneratedRace,
  type PredictableGroup,
  type RaceTarget,
  type ResultStatus,
  type ReviewOverview,
} from './adminApi'

const fmtDate = (d: string) => (d.length === 8 ? `${d.slice(0, 4)}/${d.slice(4, 6)}/${d.slice(6)}` : d)
const keyOf = (t: RaceTarget) => `${t.date}|${t.jyo}|${t.race_no}`

// ①〜④は使う頻度が高いので開いた状態、⑤以降は閉じた状態から始める
const OPEN_BY_DEFAULT = new Set(['①', '②', '③', '④'])

function Section({
  step,
  title,
  children,
  note,
}: {
  step: string
  title: string
  note?: string
  children: React.ReactNode
}) {
  return (
    <Collapsible
      id={`admin.${step}`}
      className="admin-section"
      defaultOpen={OPEN_BY_DEFAULT.has(step)}
      title={<><span className="step">{step}</span>{title}</>}
    >
      {note && <div className="ev-note">{note}</div>}
      {children}
    </Collapsible>
  )
}

export default function AdminPanel() {
  const [status, setStatus] = useState<AdminStatus | null>(null)
  const [groups, setGroups] = useState<PredictableGroup[]>([])
  const [reviews, setReviews] = useState<ReviewOverview | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [checklistOk, setChecklistOk] = useState(false)

  const reload = useCallback(() => {
    adminApi.status().then(setStatus).catch((e: Error) => setError(e.message))
    adminApi.predictable().then((d) => setGroups(d.groups)).catch(() => setGroups([]))
    adminApi.reviews().then(setReviews).catch(() => setReviews(null))
  }, [])

  useEffect(() => { reload() }, [reload])

  const run = async (fn: () => Promise<{ job_id: string }>) => {
    setError(null)
    try {
      const r = await fn()
      setJobId(r.job_id)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '実行できませんでした')
    }
  }

  const targets: RaceTarget[] = useMemo(
    () =>
      groups.flatMap((g) =>
        g.races
          .filter((r) => selected.has(keyOf({ date: g.date, jyo: g.jyo, race_no: r.race_no })))
          .map((r) => ({ date: g.date, jyo: g.jyo, race_no: r.race_no })),
      ),
    [groups, selected],
  )

  const toggle = (t: RaceTarget) => {
    const k = keyOf(t)
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(k) ? next.delete(k) : next.add(k)
      return next
    })
  }

  const selectGroup = (g: PredictableGroup, includeMaiden: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev)
      g.races.forEach((r) => {
        if (!includeMaiden && r.is_maiden) return
        next.add(keyOf({ date: g.date, jyo: g.jyo, race_no: r.race_no }))
      })
      return next
    })
  }

  const clearGroup = (g: PredictableGroup) => {
    setSelected((prev) => {
      const next = new Set(prev)
      g.races.forEach((r) => next.delete(keyOf({ date: g.date, jyo: g.jyo, race_no: r.race_no })))
      return next
    })
  }

  const busy = status?.running_job?.status === 'running'

  return (
    <div className="app admin">
      <header className="header">
        <h1>管理者画面</h1>
      </header>

      {error && <div className="note error">{error}</div>}

      {/* 状態 */}
      <div className="admin-status">
        <div>
          race.db：
          {status?.race_db.ok ? (
            <b className="ok">読み取りOK（蓄積 {status.race_db.latest_nl} / 速報 {status.race_db.latest_rt ?? '-'}）</b>
          ) : (
            <b className="ng">{status?.race_db.error ?? '確認中'}</b>
          )}
        </div>
        <div>
          速報の対象開催日：
          <b>{status?.realtime.kaisai_dates?.join(', ') || '（未設定）'}</b>
          {status?.realtime.enabled === false && <span className="ng">（速報系が無効）</span>}
        </div>
        {busy && <div className="ng">実行中のジョブがあります。終わるまで他は押せません。</div>}
      </div>

      <JobLog jobId={jobId} onFinished={() => reload()} />

      {/* ① 更新 */}
      <Section step="①" title="データ更新（JV-Link差分）">
        <div className="checklist">
          {status?.jvlink.checklist.map((c) => (
            <div key={c}>・{c}</div>
          ))}
          <label className="check">
            <input type="checkbox" checked={checklistOk} onChange={(e) => setChecklistOk(e.target.checked)} />
            確認しました
          </label>
          <div className="muted">
            JV-Linkキーの有効化は画面操作のため自動化できません。忘れると RC=-303 で失敗します。
          </div>
        </div>
        <button className="btn primary" disabled={!checklistOk || busy} onClick={() => run(adminApi.update)}>
          データを更新する
        </button>
      </Section>

      {/* ② レース選択 */}
      <Section
        step="②"
        title="レースを選ぶ／エクスポート"
        note="結果が確定していない＝これから予想できるレースです。新馬・未勝利は既定で選びません。"
      >
        {groups.length === 0 && <div className="note">予想できるレースがありません。</div>}
        {groups.map((g) => {
          const chosen = g.races.filter((r) =>
            selected.has(keyOf({ date: g.date, jyo: g.jyo, race_no: r.race_no })),
          ).length
          return (
            <div key={`${g.date}${g.jyo}`} className="race-group">
              <div className="group-head">
                <b>
                  {fmtDate(g.date)} {g.venue}
                </b>
                <span className="muted">
                  第{Number(g.kaiji)}回{Number(g.nichiji)}日・{g.races.length}レース（選択 {chosen}）
                </span>
                <button className="btn" onClick={() => selectGroup(g, false)}>新馬・未勝利以外を全部</button>
                <button className="btn" onClick={() => selectGroup(g, true)}>全部</button>
                <button className="btn" onClick={() => clearGroup(g)}>解除</button>
              </div>
              <div className="race-chips">
                {g.races.map((r) => {
                  const t = { date: g.date, jyo: g.jyo, race_no: r.race_no }
                  const on = selected.has(keyOf(t))
                  return (
                    <button
                      key={r.race_no}
                      className={`chip${on ? ' on' : ''}${r.is_maiden ? ' maiden' : ''}`}
                      onClick={() => toggle(t)}
                      title={`${r.race_class} ${r.name}`}
                    >
                      R{r.race_no}
                      <span className="chip-sub">
                        {r.is_maiden ? `${r.race_class}` : r.race_class}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })}
        <div className="form-actions">
          <button className="btn primary" disabled={!targets.length || busy}
                  onClick={() => run(() => adminApi.export(targets))}>
            選んだ {targets.length} レースをエクスポート
          </button>
          <button className="btn" disabled={!targets.length || busy}
                  onClick={() => run(() => adminApi.smartrc(targets))}>
            SmartRCを取得（{targets.length}レース）
          </button>
        </div>
        <div className="muted">
          SmartRCの rcode は race.db から自動で組み立てます（手入力は不要です）。
        </div>
      </Section>

      {/* ③ 馬場 */}
      <BabaSection dates={groups.map((g) => g.date)} busy={busy} />

      {/* ⑤ 採点・生成 */}
      <Section step="④" title="採点して予想を作る" note="作るだけで、公開はしません。">
        <div className="form-actions">
          <button className="btn primary" disabled={busy} onClick={() => run(() => adminApi.predict(false))}>
            予想を作る
          </button>
          <button className="btn" disabled={busy} onClick={() => run(() => adminApi.predict(true))}>
            作り直す（--force）
          </button>
        </div>
      </Section>

      {/* 確認と公開 */}
      <PublishSection dates={groups.map((g) => g.date)} busy={busy} onRun={run} />

      {/* ⑥⑦ 結果と回顧 */}
      <ResultSection reviews={reviews} busy={busy} onRun={run} />

      {/* 検証データ */}
      <RescoreSection busy={busy} onRun={run} />
    </div>
  )
}

// ── 検証データの作り直し ────────────────────────────────────────
function RescoreSection({
  busy,
  onRun,
}: {
  busy: boolean
  onRun: (fn: () => Promise<{ job_id: string }>) => void
}) {
  const [from, setFrom] = useState('20210601')
  const [to, setTo] = useState('20260628')

  return (
    <Section
      step="⑧"
      title="検証データを作り直す（採点ロジックを変えたとき）"
      note="採点ロジックを変えると、検証タブが読んでいる5年データは古い世代のままになります。ここで現行ロジックで採点し直せます。"
    >
      <div className="checklist">
        <div>・出力先は <b>factor_rows_p4.jsonl</b>。既存の検証データは上書きしません。</div>
        <div>・実測 約2.8秒／レース。<b>5年分（約16,000レース）で約12〜13時間</b>かかります。</div>
        <div>・途中で止めても、もう一度押せば<b>続きから再開</b>します。</div>
        <div>・実行中は他の操作ができなくなるので、夜間など使わない時間帯に。</div>
      </div>
      <div className="form-actions">
        <label className="vf">開始<input className="input" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="vf">終了<input className="input" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        <button className="btn primary" disabled={busy}
                onClick={() => onRun(() => adminApi.rescore(from, to))}>
          この期間を採点し直す
        </button>
      </div>
    </Section>
  )
}

// ── ③ 馬場 ──────────────────────────────────────────────────────
function BabaSection({ dates, busy }: { dates: string[]; busy: boolean }) {
  const today = new Date()
  const iso = `${today.getFullYear()}${String(today.getMonth() + 1).padStart(2, '0')}${String(today.getDate()).padStart(2, '0')}`
  const options = Array.from(new Set([...dates, iso])).sort().reverse()
  const [date, setDate] = useState(options[0] ?? iso)
  const [data, setData] = useState<BabaPreview | null>(null)
  const [edit, setEdit] = useState<Record<string, Record<string, string>>>({})
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    setMsg(null)
    setErr(null)
    try {
      const d = await adminApi.babaPreview(date)
      setData(d)
      const init: Record<string, Record<string, string>> = {}
      d.venues.forEach((v) => {
        const s = v.saved ?? {}
        init[v.venue] = {
          芝: String(s['芝'] ?? v.announced.芝 ?? v.suggested['芝'] ?? ''),
          ダート: String(s['ダート'] ?? v.announced.ダート ?? v.suggested['ダート'] ?? ''),
          天候: String(s['天候'] ?? v.announced.天候 ?? v.suggested['天候'] ?? ''),
          クッション値: String(s['クッション値'] ?? v.suggested['クッション値'] ?? ''),
          含水率_芝: String(s['含水率_芝'] ?? v.suggested['含水率_芝'] ?? ''),
          含水率_ダート: String(s['含水率_ダート'] ?? v.suggested['含水率_ダート'] ?? ''),
          含水率_芝_4コーナー: String(s['含水率_芝_4コーナー'] ?? v.suggested['含水率_芝_4コーナー'] ?? ''),
          含水率_ダート_4コーナー: String(s['含水率_ダート_4コーナー'] ?? v.suggested['含水率_ダート_4コーナー'] ?? ''),
        }
      })
      setEdit(init)
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : '取得に失敗しました')
    } finally {
      setLoading(false)
    }
  }

  const save = async () => {
    setErr(null)
    try {
      await adminApi.babaSave(date, edit)
      setMsg('baba_manual.json に保存しました。')
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : '保存に失敗しました')
    }
  }

  const setField = (venue: string, field: string, value: string) =>
    setEdit((p) => ({ ...p, [venue]: { ...(p[venue] ?? {}), [field]: value } }))

  return (
    <Section step="③" title="馬場を入れる" note="JRAの馬場情報から自動で取ってきます。内容を確認してから保存してください。">
      <div className="form-actions">
        <select className="input" value={date} onChange={(e) => setDate(e.target.value)}>
          {options.map((d) => (
            <option key={d} value={d}>{fmtDate(d)}</option>
          ))}
        </select>
        <button className="btn primary" disabled={loading} onClick={load}>
          JRAから取得する
        </button>
      </div>
      {err && <div className="note error">{err}</div>}
      {msg && <div className="note">{msg}</div>}
      {data?.error && <div className="note error">自動取得に失敗しました: {data.error}</div>}
      {data && (
        <>
          <div className="note warn-box">{data.notice}</div>
          <div className="ev-note">
            含水率はゴール前と4コーナーの両方を保存します。採点（トラックバイアス）に使われるのは
            <b>ゴール前</b>の値です。
          </div>
          {data.venues.map((v) => (
            <div key={v.venue} className="baba-card">
              <div className="baba-head">
                <b>{v.venue}</b>
                <span className="muted">{v.kaisai}</span>
                {v.course_used && <span className="badge badge-note">{v.course_used}</span>}
                {v.announced.芝 || v.announced.ダート ? (
                  <span className="badge badge-outline">
                    発表馬場あり（芝{v.announced.芝 ?? '-'}／ダ{v.announced.ダート ?? '-'}）
                  </span>
                ) : null}
              </div>
              <div className="muted small">
                クッション測定 {v.measured_at.cushion ?? '-'} ／ 含水率測定 {v.measured_at.moisture ?? '-'}
                {v.rain_mm != null && ` ／ 当日雨量 ${v.rain_mm}mm`}
              </div>
              <div className="muted small">
                JRA配信値の含水率: 芝 ゴール前 {v.moisture_detail['芝']?.['ゴール前'] ?? '-'} / 4コーナー{' '}
                {v.moisture_detail['芝']?.['4コーナー'] ?? '-'} ／ ダート ゴール前{' '}
                {v.moisture_detail['ダート']?.['ゴール前'] ?? '-'} / 4コーナー{' '}
                {v.moisture_detail['ダート']?.['4コーナー'] ?? '-'}
              </div>
              <div className="baba-grid">
                {(['芝', 'ダート'] as const).map((f) => (
                  <label key={f}>
                    {f}
                    <select className="input" value={edit[v.venue]?.[f] ?? ''}
                            onChange={(e) => setField(v.venue, f, e.target.value)}>
                      <option value="">（未設定）</option>
                      {['良', '稍重', '重', '不良'].map((o) => (
                        <option key={o} value={o}>{o}</option>
                      ))}
                    </select>
                  </label>
                ))}
                {([
                  ['天候', '天候'],
                  ['クッション値', 'クッション値（芝）'],
                  ['含水率_芝', '含水率 芝：ゴール前 ※採点に使用'],
                  ['含水率_芝_4コーナー', '含水率 芝：4コーナー'],
                  ['含水率_ダート', '含水率 ダート：ゴール前 ※採点に使用'],
                  ['含水率_ダート_4コーナー', '含水率 ダート：4コーナー'],
                ] as const).map(([f, label]) => (
                  <label key={f}>
                    {label}
                    <input className="input" value={edit[v.venue]?.[f] ?? ''}
                           onChange={(e) => setField(v.venue, f, e.target.value)} />
                  </label>
                ))}
              </div>
            </div>
          ))}
          <div className="form-actions">
            <button className="btn primary" disabled={busy} onClick={save}>
              確認したので保存する
            </button>
          </div>
        </>
      )}
    </Section>
  )
}

// ── 確認と公開 ───────────────────────────────────────────────────
function PublishSection({
  dates,
  busy,
  onRun,
}: {
  dates: string[]
  busy: boolean
  onRun: (fn: () => Promise<{ job_id: string }>) => void
}) {
  const [date, setDate] = useState(dates[0] ?? '')
  const [races, setRaces] = useState<GeneratedRace[]>([])
  const [picked, setPicked] = useState<Set<string>>(new Set())

  useEffect(() => { if (!date && dates.length) setDate(dates[0]) }, [dates, date])

  const load = useCallback(() => {
    if (!date) return
    adminApi.generated(date).then((d) => setRaces(d.races)).catch(() => setRaces([]))
  }, [date])
  useEffect(() => { load() }, [load])

  const toggle = (id: string) =>
    setPicked((p) => {
      const n = new Set(p)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })

  const unpublished = races.filter((r) => (r.has_pred && !r.published_pred) || (r.has_review && !r.published_review))

  return (
    <Section step="⑤" title="中身を確認してから公開する" note="ここを押すまで、外部には公開されません。">
      <div className="form-actions">
        <select className="input" value={date} onChange={(e) => setDate(e.target.value)}>
          {Array.from(new Set(dates.concat(date ? [date] : []))).sort().reverse().map((d) => (
            <option key={d} value={d}>{fmtDate(d)}</option>
          ))}
        </select>
        <button className="btn" onClick={load}>一覧を更新</button>
        <button className="btn" onClick={() => setPicked(new Set(unpublished.map((r) => r.race_id)))}>
          未公開をすべて選ぶ（{unpublished.length}）
        </button>
      </div>
      <ul className="gen-list">
        {races.map((r) => (
          <li key={r.race_id} className="gen-item">
            <label className="check">
              <input type="checkbox" checked={picked.has(r.race_id)} onChange={() => toggle(r.race_id)} />
              <b>{r.venue}{r.race_no}R</b> {r.race_name ?? ''}
            </label>
            <span className="gen-links">
              {r.has_pred && (
                <a href={`/api/races/${r.race_id}/pred.html`} target="_blank" rel="noreferrer">予想を確認</a>
              )}
              {r.has_review && (
                <a href={`/api/races/${r.race_id}/review.html`} target="_blank" rel="noreferrer">回顧を確認</a>
              )}
              {r.published_pred && <span className="badge badge-outline">予想 公開済み</span>}
              {r.published_review && <span className="badge badge-outline">回顧 公開済み</span>}
            </span>
          </li>
        ))}
      </ul>
      <button className="btn primary" disabled={!picked.size || busy}
              onClick={() => onRun(() => adminApi.publish([...picked]))}>
        選んだ {picked.size} レースを公開する
      </button>
    </Section>
  )
}

// ── ⑥⑦ 結果・回顧 ──────────────────────────────────────────────
function ResultSection({
  reviews,
  busy,
  onRun,
}: {
  reviews: ReviewOverview | null
  busy: boolean
  onRun: (fn: () => Promise<{ job_id: string }>) => void
}) {
  const [results, setResults] = useState<ResultStatus | null>(null)

  if (!reviews) return null

  return (
    <>
      <Section step="⑥" title="結果を取り込む"
               note="当日・前日は速報系から取り込みます。対象開催日は自動で設定します。">
        {reviews.pending.length === 0 && <div className="note">回顧待ちのレースはありません。</div>}
        {reviews.pending.map((d) => (
          <div key={d.date} className="pending-row">
            <b>{fmtDate(d.date)}</b>
            <span className="muted">{d.count}レースが回顧未作成</span>
            {d.needs_realtime ? (
              <>
                <span className="badge badge-todo">速報の取り込みが必要</span>
                <button className="btn" disabled={busy} onClick={() => onRun(() => adminApi.fetchResults(d.date))}>
                  この日の結果を取り込む
                </button>
              </>
            ) : (
              <span className="muted">確定成績のはずです（①の更新で取り込まれます）</span>
            )}
            <button className="btn" onClick={() => adminApi.results(d.date).then(setResults).catch(() => setResults(null))}>
              確定状況を見る
            </button>
            <button className="btn primary" disabled={busy}
                    onClick={() => onRun(() => adminApi.review(d.races))}>
              回顧を作る（{d.count}レース）
            </button>
          </div>
        ))}
        {results && (
          <div className="result-box">
            <b>{fmtDate(results.date)}：{results.confirmed} / {results.total} レース確定</b>
            <div className="result-grid">
              {results.races.map((r) => (
                <span key={`${r.venue}${r.race_no}`} className={`result-chip ${r.state}`}>
                  {r.venue}{r.race_no}R {r.state}
                  {r.source ? `[${r.source}]` : ''}
                </span>
              ))}
            </div>
          </div>
        )}
      </Section>

      <Section step="⑦" title="速報で作った回顧を確定情報で作り直す"
               note="レースラップなど、速報では取れなかった項目が確定成績で埋まります。">
        {reviews.upgradable_total === 0 && reviews.realtime_waiting_total === 0 && (
          <div className="note">作り直しが必要な回顧はありません。</div>
        )}
        {reviews.upgradable.map((d) => (
          <div key={d.date} className="pending-row">
            <b>{fmtDate(d.date)}</b>
            <span className="muted">{d.count}レースが速報のまま</span>
            <button className="btn primary" disabled={busy}
                    onClick={() => onRun(() => adminApi.review(d.races))}>
              確定情報で作り直す
            </button>
          </div>
        ))}
        {reviews.realtime_waiting.map((d) => (
          <div key={d.date} className="pending-row">
            <b>{fmtDate(d.date)}</b>
            <span className="muted">{d.count}レースが速報のまま</span>
            <span className="badge badge-todo">確定成績がまだ届いていません（①の更新後に再確認）</span>
          </div>
        ))}
      </Section>
    </>
  )
}
