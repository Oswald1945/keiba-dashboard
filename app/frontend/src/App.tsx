import { useEffect, useMemo, useState } from 'react'
import {
  fetchFeatured,
  fetchMode,
  fetchRaces,
  predUrl,
  reviewUrl,
  setFeatured,
  type AppMode,
  type Race,
} from './api'
import MemoPanel from './memo/MemoPanel'
import AdminPanel from './admin/AdminPanel'
import ValidationPanel from './validation/ValidationPanel'
import Collapsible from './ui/Collapsible'
import { usePersistentState } from './ui/store'

const WEEKDAYS = ['日曜日', '月曜日', '火曜日', '水曜日', '木曜日', '金曜日', '土曜日']

/** 「2026年7月26日（日曜日）」の形にする。 */
function formatDateLong(d: string): string {
  if (d.length !== 8) return d
  const y = Number(d.slice(0, 4))
  const m = Number(d.slice(4, 6))
  const day = Number(d.slice(6, 8))
  const w = WEEKDAYS[new Date(y, m - 1, day).getDay()]
  return `${y}年${m}月${day}日（${w}）`
}

/** 「2026年7月26日（日）」の形にする。スマホで1行に収めるための短縮版。 */
function formatDateShort(d: string): string {
  if (d.length !== 8) return d
  const y = Number(d.slice(0, 4))
  const m = Number(d.slice(4, 6))
  const day = Number(d.slice(6, 8))
  const w = WEEKDAYS[new Date(y, m - 1, day).getDay()][0]
  return `${y}年${m}月${day}日（${w}）`
}

/** 「第2回2日目」。race.db から取れないときは空。 */
function kaisaiLabel(r: Race): string {
  if (r.kaiji == null || r.nichiji == null) return ''
  return `第${r.kaiji}回${r.nichiji}日目`
}

// 一覧に並べる会場の順番（JRAの場コード順）
const VENUE_ORDER = ['札幌', '函館', '福島', '新潟', '東京', '中山', '中京', '京都', '阪神', '小倉']

function venueRank(v: string | null): number {
  const i = VENUE_ORDER.indexOf(v ?? '')
  return i < 0 ? 99 : i
}

function RaceTitle({ r }: { r: Race }) {
  // 会場とR番号は別に出しているので、ここでは繰り返さない。
  // レース名が無い（平場）ときは条件をそのまま見出しにする。
  const cond = [r.race_class, r.surface, r.distance ? `${r.distance}m` : null]
    .filter(Boolean)
    .join(' ')
  if (!r.race_name) {
    return (
      <div className="race-title">
        <div className="race-name plain">{cond || '—'}</div>
      </div>
    )
  }
  return (
    <div className="race-title">
      <div className="race-name">{r.race_name}</div>
      {cond && <div className="race-cond">{cond}</div>}
    </div>
  )
}

type ViewerTab = 'pred' | 'review'

function Viewer({
  race,
  initialTab,
  featured,
  onToggleFeatured,
  onClose,
}: {
  race: Race
  initialTab?: ViewerTab
  /** この画面で開いているレースが注目レースかどうか */
  featured: boolean
  onToggleFeatured: () => void
  onClose: () => void
}) {
  const [tab, setTab] = useState<ViewerTab>(
    initialTab ?? (race.has_pred ? 'pred' : 'review'),
  )
  const frameUrl = tab === 'review' ? reviewUrl(race.race_id) : predUrl(race.race_id)
  return (
    <div className="viewer">
      <div className="viewer-bar">
        <button className="link-btn" onClick={onClose}>
          ← 一覧に戻る
        </button>
        <div className="viewer-title">
          {formatDateLong(race.date)} {race.venue}
          {race.race_no}R {race.race_name ?? ''}
          <span
            className={`star${featured ? ' on' : ''}`}
            role="button"
            title={featured ? '注目を外す' : '注目レースにする'}
            onClick={onToggleFeatured}
          >
            {featured ? '★' : '☆'}
          </span>
        </div>
        <div className="tabs">
          <button
            className={tab === 'pred' ? 'tab active' : 'tab'}
            disabled={!race.has_pred}
            onClick={() => setTab('pred')}
          >
            予想
          </button>
          <button
            className={tab === 'review' ? 'tab active' : 'tab'}
            disabled={!race.has_review}
            onClick={() => setTab('review')}
          >
            回顧
          </button>
          <a className="tab" href={frameUrl} target="_blank" rel="noreferrer">
            別タブで開く
          </a>
        </div>
      </div>
      <iframe className="viewer-frame" src={frameUrl} title="dashboard" />
    </div>
  )
}

type View = 'races' | 'memo' | 'admin' | 'validation'

export default function App() {
  const [view, setView] = useState<View>('races')
  // 管理モードは「誤操作を防ぐための表示切替」。パスワードによる権限分離ではない。
  const [adminMode, setAdminMode] = usePersistentState('adminMode', false)
  // どのモードで動いているかが分かるまでは、上のバーを描画しない。
  // 公開サーバーで管理モードの切替が一瞬でも見えると、無い機能があるように見えるため。
  const [mode, setMode] = useState<AppMode | null>(null)

  useEffect(() => {
    fetchMode()
      .then(setMode)
      .catch(() => {
        // 取れないときは「このPC」とみなす。
        // 公開サーバーはログインしないと画面自体が読み込まれず、
        // ログイン後にこの取得が失敗することはない。失敗するのは
        // このPCのアプリが /api/mode を持たない古いままのときだけなので、
        // そちらに寄せないと管理・検証タブが出せなくなる。
        setMode({ public_mode: false, user_id: null })
      })
  }, [])

  // 公開サーバーには管理・検証のAPIがそもそも無いので、切替もタブも出さない。
  const canAdmin = mode !== null && !mode.public_mode

  const tabs: { key: View; label: string; adminOnly?: boolean }[] = [
    { key: 'races', label: 'レース' },
    { key: 'memo', label: 'メモ馬' },
    { key: 'admin', label: '管理', adminOnly: true },
    { key: 'validation', label: '検証', adminOnly: true },
  ]
  const visible = tabs.filter((t) => !t.adminOnly || (adminMode && canAdmin))
  const current = visible.some((t) => t.key === view) ? view : 'races'

  return (
    <>
      {canAdmin && (
        <div className="modebar">
          <label className="check">
            <input
              type="checkbox"
              checked={adminMode}
              onChange={(e) => {
                setAdminMode(e.target.checked)
                if (!e.target.checked) setView('races')
              }}
            />
            管理モード
          </label>
          <span className="muted small">
            {adminMode ? '生成・公開・検証の操作ができます' : '閲覧と、メモ馬・オッズの入力だけできます'}
          </span>
        </div>
      )}

      {mode?.public_mode && (
        <div className="modebar">
          <span className="muted small">
            {mode.user_id ? `ログイン中：${mode.user_id}` : 'ログイン中'}
          </span>
          <a className="logout" href="/logout">
            ログアウト
          </a>
        </div>
      )}

      <nav className="globalnav">
        {visible.map((t) => (
          <button
            key={t.key}
            className={current === t.key ? 'navbtn active' : 'navbtn'}
            onClick={() => setView(t.key)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main className="viewhost">
        {current === 'races' && <RaceView mode={mode} />}
        {current === 'memo' && <MemoPanel />}
        {current === 'admin' && <AdminPanel />}
        {current === 'validation' && <ValidationPanel />}
      </main>
    </>
  )
}

function RaceView({ mode }: { mode: AppMode | null }) {
  const [races, setRaces] = useState<Race[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [date, setDate] = useState('')
  const [venue, setVenue] = useState('')
  const [selected, setSelected] = useState<{ race: Race; tab?: ViewerTab } | null>(null)
  const [featured, setFeaturedIds] = useState<Set<string>>(new Set())
  const [onlyFeatured, setOnlyFeatured] = useState(false)

  useEffect(() => {
    let alive = true
    setLoading(true)
    fetchRaces({ limit: 2000 })
      .then((d) => {
        if (alive) {
          setRaces(d.races)
          setError(null)
        }
      })
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    fetchFeatured()
      .then((d) => setFeaturedIds(new Set(d.race_ids)))
      .catch(() => setFeaturedIds(new Set()))
  }, [])

  const toggleFeatured = (raceId: string) => {
    const on = !featured.has(raceId)
    setFeaturedIds((prev) => {
      const next = new Set(prev)
      on ? next.add(raceId) : next.delete(raceId)
      return next
    })
    setFeatured(raceId, on).catch(() => {
      // 失敗したら見た目を戻す
      setFeaturedIds((prev) => {
        const next = new Set(prev)
        on ? next.delete(raceId) : next.add(raceId)
        return next
      })
    })
  }

  const dates = useMemo(
    () => Array.from(new Set(races.map((r) => r.date))),
    [races],
  )
  const venues = useMemo(
    () =>
      Array.from(new Set(races.map((r) => r.venue).filter(Boolean))) as string[],
    [races],
  )

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return races.filter((r) => {
      if (date && r.date !== date) return false
      if (venue && r.venue !== venue) return false
      if (onlyFeatured && !featured.has(r.race_id)) return false
      if (!needle) return true
      return (
        (r.race_name ?? '').toLowerCase().includes(needle) ||
        (r.race_class ?? '').toLowerCase().includes(needle) ||
        r.race_id.toLowerCase().includes(needle) ||
        (r.horse_names ?? []).some((n) => n.toLowerCase().includes(needle))
      )
    })
  }, [races, q, date, venue, onlyFeatured, featured])

  const byDate = useMemo(() => {
    const map = new Map<string, Race[]>()
    shown.forEach((r) => {
      const list = map.get(r.date)
      if (list) list.push(r)
      else map.set(r.date, [r])
    })
    return [...map.entries()]
      .sort((a, b) => (a[0] < b[0] ? 1 : -1))
      .map(([date, races]) => {
        // 会場ごとに縦に並べる。列は最大3つ（2場開催なら2列）。
        const vmap = new Map<string, Race[]>()
        races.forEach((r) => {
          const k = r.venue ?? r.venue_code
          const list = vmap.get(k)
          if (list) list.push(r)
          else vmap.set(k, [r])
        })
        const venues = [...vmap.entries()]
          .map(([venue, list]) => ({
            venue,
            kaisai: kaisaiLabel(list[0]),
            races: [...list].sort((a, b) => a.race_no - b.race_no),
          }))
          .sort((a, b) => venueRank(a.venue) - venueRank(b.venue))
        return { date, races, venues }
      })
  }, [shown])

  if (selected) {
    return (
      <Viewer
        race={selected.race}
        initialTab={selected.tab}
        featured={featured.has(selected.race.race_id)}
        onToggleFeatured={() => toggleFeatured(selected.race.race_id)}
        onClose={() => setSelected(null)}
      />
    )
  }

  return (
    <div className="app">
      <header className="header">
        <h1>競馬予想 / 回顧ダッシュボード</h1>
        {mode && (
          <div className="sub">
            {mode.public_mode
              ? '招待された方だけが閲覧できます'
              : 'このPCの中だけで動いています（外部には公開されていません）'}
          </div>
        )}
      </header>

      <div className="filters">
        <input
          className="input"
          placeholder="レース名・クラス・馬名で検索"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select
          className="input"
          value={date}
          onChange={(e) => setDate(e.target.value)}
        >
          <option value="">すべての日付</option>
          {dates.map((d) => (
            <option key={d} value={d}>
              {formatDateLong(d)}
            </option>
          ))}
        </select>
        <select
          className="input"
          value={venue}
          onChange={(e) => setVenue(e.target.value)}
        >
          <option value="">すべての会場</option>
          {venues.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
        <label className="check">
          <input
            type="checkbox"
            checked={onlyFeatured}
            onChange={(e) => setOnlyFeatured(e.target.checked)}
          />
          注目レースのみ（{featured.size}）
        </label>
      </div>

      {loading && <div className="note">読み込み中...</div>}
      {error && <div className="note error">読み込みに失敗しました: {error}</div>}
      {!loading && !error && (
        <div className="note">{shown.length} レース</div>
      )}

      {byDate.map((g, i) => (
        <Collapsible
          key={g.date}
          id={`races.date.${g.date}`}
          title={
            <>
              {/* スマホは「（日）」と短くしてレース数も隠し、見出しを1行に収める */}
              <span className="only-wide">{formatDateLong(g.date)}</span>
              <span className="only-narrow">{formatDateShort(g.date)}</span>
            </>
          }
          sub={
            <>
              {g.venues.map((v) => v.venue).join('・')}
              <span className="only-wide">　{g.races.length}レース</span>
            </>
          }
          defaultOpen={i === 0}
        >
          <div
            className="venue-cols"
            style={{ ['--cols' as string]: String(Math.min(g.venues.length, 3)) }}
          >
            {g.venues.map((v) => (
              <div key={v.venue ?? '?'} className="venue-col">
                <div className="venue-head">
                  <span className="venue-name">{v.venue ?? '会場不明'}</span>
                  {v.kaisai && <span className="venue-kaisai">{v.kaisai}</span>}
                  <span className="venue-count">{v.races.length}R</span>
                </div>
                <ul className="race-list">
                  {v.races.map((r) => (
                    <li
                      key={r.race_id}
                      className={
                        `race-item${r.has_pred || r.has_review ? '' : ' empty'}` +
                        (featured.has(r.race_id) ? ' featured' : '')
                      }
                      onClick={() => {
                        if (r.has_pred) setSelected({ race: r, tab: 'pred' })
                        else if (r.has_review) setSelected({ race: r, tab: 'review' })
                      }}
                    >
                      <span
                        className={`star${featured.has(r.race_id) ? ' on' : ''}`}
                        role="button"
                        title={featured.has(r.race_id) ? '注目を外す' : '注目レースにする'}
                        onClick={(e) => {
                          e.stopPropagation()
                          toggleFeatured(r.race_id)
                        }}
                      >
                        {featured.has(r.race_id) ? '★' : '☆'}
                      </span>
                      <span className="race-no">{r.race_no}R</span>
                      {r.start_time && <span className="race-time">{r.start_time}</span>}
                      <RaceTitle r={r} />
                      <div className="badges">
                        {r.has_pred && (
                          <button
                            className="badge badge-pred"
                            onClick={(e) => {
                              e.stopPropagation()
                              setSelected({ race: r, tab: 'pred' })
                            }}
                          >
                            予想
                          </button>
                        )}
                        {r.has_review && (
                          <button
                            className={`badge badge-review${r.review_is_realtime ? ' rt' : ''}`}
                            title={
                              r.review_is_realtime
                                ? '速報成績で作った回顧（確定情報で作り直せます）'
                                : '確定成績で作った回顧'
                            }
                            onClick={(e) => {
                              e.stopPropagation()
                              setSelected({ race: r, tab: 'review' })
                            }}
                          >
                            回顧
                          </button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Collapsible>
      ))}
    </div>
  )
}
