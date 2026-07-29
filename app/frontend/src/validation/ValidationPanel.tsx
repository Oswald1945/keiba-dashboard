import { useCallback, useEffect, useMemo, useState } from 'react'
import Collapsible from '../ui/Collapsible'
import JobLog from '../admin/JobLog'
import { RescoreSection, UpdateSection } from '../admin/AdminPanel'

type Preset = { key: string; label: string; date_from: string | null; date_to: string | null }
type SourceInfo = {
  key: string
  file: string
  label: string
  desc: string
  exists: boolean
  size_mb: number | null
}

type Range = {
  source: string
  source_key: string
  source_label: string
  sources: SourceInfo[]
  accuracy: { from: string; to: string; races: number } | null
  value_formation: { from: string; to: string; races: number } | null
  note: string
  presets: Preset[]
  today: string
}

type Breakdown = {
  key: string
  races: number
  axis_win_rate: number | null
  axis_place_rate: number | null
  pop1_place_rate: number | null
}

type Accuracy = {
  races: number
  avg_field: number | null
  axis_win_rate: number | null
  axis_place_rate: number | null
  top3_overlap: number | null
  spearman: number | null
  pop1_win_rate: number | null
  pop1_place_rate: number | null
  by_year: Breakdown[]
  by_venue: Breakdown[]
  by_class: Breakdown[]
  by_baba: Breakdown[]
  by_surface: Breakdown[]
  axis_definition: string
}

type FactorRow = {
  factor: string
  races: number
  top1_place_rate: number | null
  calibration: { top1: number | null; top2: number | null; top3: number | null; rest: number | null }
  spearman: number | null
  variation_rate: number | null
}

type BetType = {
  bet_type: string
  races: number
  points: number
  hit_races: number
  hit_rate: number | null
  investment: number
  payout: number
  roi: number | null
}

type Value = {
  notice: string
  axis: {
    races: number
    investment: number
    win: { hit_rate: number | null; roi: number | null; payout: number }
    place: { hit_rate: number | null; roi: number | null; payout: number; missing_payout_races: number }
    axis_definition: string
    note: string
  }
  formation: {
    total: { races: number; bet_types: BetType[]; axis: Record<string, number> | null }
    by_verdict: { verdict: string; races: number; bet_types: BetType[] }[]
    axis_definition: string
    note: string
  }
}

const pct = (v: number | null | undefined, d = 1) =>
  v == null ? '-' : `${(v * 100).toFixed(d)}%`
const num = (v: number | null | undefined, d = 2) => (v == null ? '-' : v.toFixed(d))
const yen = (v: number | null | undefined) => (v == null ? '-' : `${Math.round(v).toLocaleString()}円`)
const fmtDate = (d: string | null) => (d && d.length === 8 ? `${d.slice(0, 4)}/${d.slice(4, 6)}/${d.slice(6)}` : '-')

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`エラー (${res.status})`)
  return res.json() as Promise<T>
}

export default function ValidationPanel() {
  const [range, setRange] = useState<Range | null>(null)
  const [tab, setTab] = useState<'accuracy' | 'factors' | 'value'>('accuracy')
  const [presetKey, setPresetKey] = useState('5y')
  const [source, setSource] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [baba, setBaba] = useState('')
  const [cls, setCls] = useState('')
  const [includeMaiden, setIncludeMaiden] = useState(false)

  const [acc, setAcc] = useState<Accuracy | null>(null)
  const [factors, setFactors] = useState<FactorRow[] | null>(null)
  const [value, setValue] = useState<Value | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 検証データの作り直し（管理画面から移した①②）
  const [jobId, setJobId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [rebuildError, setRebuildError] = useState<string | null>(null)

  const runJob = async (fn: () => Promise<{ job_id: string }>) => {
    setRebuildError(null)
    try {
      const r = await fn()
      setJobId(r.job_id)
      setBusy(true)
    } catch (e: unknown) {
      setRebuildError(e instanceof Error ? e.message : '実行できませんでした')
    }
  }

  useEffect(() => {
    getJson<Range>('/api/validation/range')
      .then((r) => {
        setRange(r)
        setSource(r.source_key)
        const p = r.presets.find((x) => x.key === '5y')
        if (p?.date_from) setFrom(p.date_from)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  const query = useMemo(() => {
    const sp = new URLSearchParams()
    if (from) sp.set('date_from', from)
    if (to) sp.set('date_to', to)
    if (baba) sp.append('babas', baba)
    if (cls) sp.append('classes', cls)
    if (includeMaiden) sp.set('include_maiden', 'true')
    if (source) sp.set('source', source)
    return sp.toString()
  }, [from, to, baba, cls, includeMaiden, source])

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    const url =
      tab === 'accuracy' ? `/api/validation/accuracy?${query}`
        : tab === 'factors' ? `/api/validation/factors?${query}`
          : `/api/validation/value?${query}`
    getJson<Record<string, unknown>>(url)
      .then((d) => {
        if (tab === 'accuracy') setAcc(d as unknown as Accuracy)
        else if (tab === 'factors') setFactors((d as { factors: FactorRow[] }).factors)
        else setValue(d as unknown as Value)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [tab, query])

  useEffect(() => { if (range) load() }, [range, load])

  const applyPreset = (p: Preset) => {
    setPresetKey(p.key)
    setFrom(p.date_from ?? '')
    setTo(p.date_to ?? '')
  }

  if (error && !range) return <div className="note error">検証データを読み込めません: {error}</div>
  if (!range) return <div className="note">読み込み中...</div>

  const covered = range.accuracy
  // 「過去10年」のようにデータが無い期間を選んだときに気づけるようにする
  const outOfRange = from && covered?.from && from < covered.from ? from : null

  return (
    <div className="app">
      <header className="header">
        <h1>検証</h1>
        <div className="sub">的中精度と妙味を、期間・条件を絞って集計します。</div>
      </header>

      {/* 検証データを作り直す流れ（①更新 → ②作り直し）。集計はその下。 */}
      <div className="admin rebuild-block">
        {rebuildError && <div className="note error">{rebuildError}</div>}
        <JobLog jobId={jobId} onFinished={() => setBusy(false)} />
        <UpdateSection step="①" busy={busy} onRun={runJob} />
        <RescoreSection step="②" busy={busy} onRun={runJob} />
      </div>

      <div className="source-row">
        <label className="vf">
          採点データの世代
          <select className="input" value={source} onChange={(e) => setSource(e.target.value)}>
            {range.sources.map((s) => (
              <option key={s.key} value={s.key} disabled={!s.exists}>
                {s.label}{s.exists ? '' : '（未作成）'}
              </option>
            ))}
          </select>
        </label>
        <div className="source-desc">
          {range.sources.find((s) => s.key === source)?.desc}
        </div>
      </div>
      <div className={`note ${range.source_key === 'p4' ? '' : 'warn-box'}`}>{range.note}</div>
      {covered && (
        <div className="note">
          使えるデータ：{fmtDate(covered.from)} 〜 {fmtDate(covered.to)}（{covered.races.toLocaleString()}レース／{range.source}）
        </div>
      )}

      <div className="ev-tabs">
        {[
          ['accuracy', '的中精度'],
          ['factors', '因子ごとの動向'],
          ['value', '妙味'],
        ].map(([k, label]) => (
          <button key={k} className={tab === k ? 'tab active' : 'tab'}
                  onClick={() => setTab(k as typeof tab)}>
            {label}
          </button>
        ))}
      </div>

      <div className="filters val-filters">
        <div className="preset-row">
          {range.presets.map((p) => (
            <button key={p.key} className={presetKey === p.key ? 'chip on' : 'chip'}
                    onClick={() => applyPreset(p)}>
              {p.label}
            </button>
          ))}
        </div>
        <label className="vf">開始<input className="input" placeholder="YYYYMMDD" value={from}
                                       onChange={(e) => { setFrom(e.target.value); setPresetKey('custom') }} /></label>
        <label className="vf">終了<input className="input" placeholder="YYYYMMDD" value={to}
                                       onChange={(e) => { setTo(e.target.value); setPresetKey('custom') }} /></label>
        <label className="vf">馬場
          <select className="input" value={baba} onChange={(e) => setBaba(e.target.value)}>
            <option value="">すべて</option>
            {['良', '稍重', '重', '不良'].map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </label>
        <label className="vf">クラス
          <select className="input" value={cls} onChange={(e) => setCls(e.target.value)}>
            <option value="">すべて</option>
            {['1勝', '2勝', '3勝', 'OP', 'G3', 'G2', 'G1'].map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={includeMaiden} onChange={(e) => setIncludeMaiden(e.target.checked)} />
          新馬・未勝利も含める
        </label>
        <button className="btn primary" onClick={load} disabled={loading}>
          {loading ? '集計中...' : '集計する'}
        </button>
      </div>

      {error && <div className="note error">{error}</div>}
      {outOfRange && (
        <div className="note">
          選んだ期間の開始（{fmtDate(outOfRange)}）より前のデータはありません。
          実際に集計しているのは {fmtDate(covered?.from ?? null)} 以降です。
        </div>
      )}

      {tab === 'accuracy' && acc && <AccuracyView a={acc} />}
      {tab === 'factors' && factors && <FactorView rows={factors} />}
      {tab === 'value' && value && <ValueView v={value} range={range} />}
    </div>
  )
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  )
}

function BreakdownTable({
  title,
  rows,
  defaultOpen = false,
}: {
  title: string
  rows: Breakdown[]
  defaultOpen?: boolean
}) {
  if (!rows.length) return null
  return (
    <Collapsible id={`val.bd.${title}`} title={`${title}別`} sub={`${rows.length}区分`}
                 defaultOpen={defaultOpen} className="bd">
      <div className="table-scroll">
        <table className="val-table">
          <thead>
            <tr><th>{title}</th><th>R数</th><th>軸単勝</th><th>軸複勝</th><th>1番人気複勝</th><th>差</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const diff = r.axis_place_rate != null && r.pop1_place_rate != null
                ? r.axis_place_rate - r.pop1_place_rate : null
              return (
                <tr key={r.key}>
                  <td>{r.key}</td>
                  <td className="n">{r.races.toLocaleString()}</td>
                  <td className="n">{pct(r.axis_win_rate)}</td>
                  <td className="n"><b>{pct(r.axis_place_rate)}</b></td>
                  <td className="n">{pct(r.pop1_place_rate)}</td>
                  <td className={`n ${diff != null && diff < 0 ? 'ev-negative' : 'ev-positive'}`}>
                    {diff == null ? '-' : `${(diff * 100).toFixed(1)}pt`}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Collapsible>
  )
}

function AccuracyView({ a }: { a: Accuracy }) {
  return (
    <>
      <div className="kpi-row">
        <Kpi label="対象レース" value={`${a.races.toLocaleString()}R`} sub={`平均${num(a.avg_field, 1)}頭`} />
        <Kpi label="軸 複勝率" value={pct(a.axis_place_rate)} sub={a.axis_definition} />
        <Kpi label="軸 単勝率" value={pct(a.axis_win_rate)} />
        <Kpi label="1番人気 複勝率" value={pct(a.pop1_place_rate)} sub="市場のベンチマーク" />
        <Kpi label="上位3頭の着3内重複" value={`${num(a.top3_overlap)}/3`} />
        <Kpi label="順位相関" value={num(a.spearman, 3)} sub="スピアマン（平均）" />
      </div>
      <BreakdownTable title="年" rows={a.by_year} defaultOpen />
      <BreakdownTable title="馬場" rows={a.by_baba} defaultOpen />
      <BreakdownTable title="クラス" rows={a.by_class} />
      <BreakdownTable title="会場" rows={a.by_venue} />
      <BreakdownTable title="芝ダ" rows={a.by_surface} />
    </>
  )
}

function FactorView({ rows }: { rows: FactorRow[] }) {
  return (
    <>
      <div className="ev-note">
        単独複勝率＝その因子のptsが1位だった馬の複勝率。キャリブレーションは pts順位ごとの複勝率で、
        上から下へきれいに下がるほど判別できている因子です。
      </div>
      <div className="table-scroll">
        <table className="val-table">
          <thead>
            <tr>
              <th>因子</th><th>R数</th><th>単独複勝率</th>
              <th>1位</th><th>2位</th><th>3位</th><th>残り</th>
              <th>順位相関</th><th>変動率</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.factor}>
                <td>{r.factor}</td>
                <td className="n">{r.races.toLocaleString()}</td>
                <td className="n"><b>{pct(r.top1_place_rate)}</b></td>
                <td className="n">{pct(r.calibration.top1, 0)}</td>
                <td className="n">{pct(r.calibration.top2, 0)}</td>
                <td className="n">{pct(r.calibration.top3, 0)}</td>
                <td className="n">{pct(r.calibration.rest, 0)}</td>
                <td className="n">{num(r.spearman, 3)}</td>
                <td className="n">{pct(r.variation_rate, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function BetTable({ rows }: { rows: BetType[] }) {
  if (!rows.length) return <div className="note">データがありません。</div>
  return (
    <div className="table-scroll">
      <table className="val-table">
        <thead>
          <tr><th>券種</th><th>R数</th><th>的中R</th><th>的中率</th><th>投資</th><th>回収</th><th>回収率</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.bet_type}>
              <td>{r.bet_type}</td>
              <td className="n">{r.races}</td>
              <td className="n">{r.hit_races}</td>
              <td className="n">{pct(r.hit_rate)}</td>
              <td className="n">{yen(r.investment)}</td>
              <td className="n">{yen(r.payout)}</td>
              <td className={`n ${(r.roi ?? 0) >= 1 ? 'ev-positive' : 'ev-negative'}`}>
                <b>{pct(r.roi)}</b>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ValueView({ v, range }: { v: Value; range: Range }) {
  return (
    <>
      <div className="ev-warning">{v.notice}</div>

      <h3 className="ev-h3">軸の単勝・複勝（全期間で計算できます）</h3>
      <div className="ev-note">
        軸＝{v.axis.axis_definition}。{v.axis.note}
      </div>
      <div className="kpi-row">
        <Kpi label="対象レース" value={`${v.axis.races.toLocaleString()}R`} sub={`投資 ${yen(v.axis.investment)}（1点100円）`} />
        <Kpi label="単勝 的中率" value={pct(v.axis.win.hit_rate)} />
        <Kpi label="単勝 回収率" value={pct(v.axis.win.roi)} sub="市場平均は約80%" />
        <Kpi label="複勝 的中率" value={pct(v.axis.place.hit_rate)} />
        <Kpi label="複勝 回収率" value={pct(v.axis.place.roi)} sub="市場平均は約80%" />
      </div>
      {v.axis.place.missing_payout_races > 0 && (
        <div className="note">
          ※ {v.axis.place.missing_payout_races}レースは複勝配当が記録に無く、回収0円として計算しています。
        </div>
      )}

      <h3 className="ev-h3">券種フォーメーション</h3>
      <div className="ev-note">
        軸＝{v.formation.axis_definition}。
        {range.value_formation
          ? `このデータは ${fmtDate(range.value_formation.from)} 〜 ${fmtDate(range.value_formation.to)} 分のみです。`
          : 'データがありません。'}
      </div>
      <BetTable rows={v.formation.total.bet_types} />

      {v.formation.by_verdict.map((g) => (
        <Collapsible key={g.verdict} id={`val.verdict.${g.verdict}`} className="bd"
                     title={`買い判定＝${g.verdict}`} sub={`${g.races}R`}>
          <BetTable rows={g.bet_types} />
        </Collapsible>
      ))}
    </>
  )
}
