import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  EV_CORE_VERSION,
  buildBetPlan,
  detailBets,
  evCell,
  formationBets,
  tableRows,
  type BetPlan,
  type EvHorse,
  type EvRow,
} from './evCore'
import { fetchEvData, fetchOdds, saveOdds } from '../api'
import Collapsible from '../ui/Collapsible'

const WAKU_BG: Record<number, string> = {
  1: '#ffffff', 2: '#555555', 3: '#ee3333', 4: '#4488ff',
  5: '#dddd00', 6: '#22bb22', 7: '#ff8822', 8: '#ffaacc',
}
const WAKU_FG: Record<number, string> = {
  1: '#111', 2: '#eee', 3: '#fff', 4: '#fff', 5: '#111', 6: '#fff', 7: '#111', 8: '#111',
}

function UmaChip({ uma, waku }: { uma: number | null; waku: number | null }) {
  const w = waku ?? 0
  return (
    <span
      className="uma-chip"
      style={{ background: WAKU_BG[w] ?? '#888', color: WAKU_FG[w] ?? '#fff' }}
    >
      {uma ?? '?'}
    </span>
  )
}

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`
}

/** 保存はまとめて少し遅らせて行う（1文字ごとにPUTしない）。 */
function useDebouncedSave(raceId: string) {
  const timer = useRef<number | null>(null)
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const run = useCallback(
    (tansho: Record<string, number>, bets: Record<string, number>) => {
      if (timer.current) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => {
        setState('saving')
        saveOdds(raceId, { tansho, bets, ev_core_version: EV_CORE_VERSION })
          .then(() => setState('saved'))
          .catch(() => setState('error'))
      }, 600)
    },
    [raceId],
  )
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current) }, [])
  return { save: run, state }
}

export default function EvPanel({ raceId }: { raceId: string }) {
  const [horses, setHorses] = useState<EvHorse[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<'tansho' | 'fukusho'>('tansho')
  const [userOdds, setUserOdds] = useState<Record<string, number>>({})
  // 入力欄の見た目用。9 ではなく 9.0 と出す（既存ダッシュボードと揃える）
  const [oddsText, setOddsText] = useState<Record<string, string>>({})
  const [betOdds, setBetOdds] = useState<Record<string, number>>({})
  const [loadedOdds, setLoadedOdds] = useState(false)
  const { save, state: saveState } = useDebouncedSave(raceId)

  useEffect(() => {
    let alive = true
    setHorses(null)
    setError(null)
    setLoadedOdds(false)
    Promise.all([fetchEvData(raceId), fetchOdds(raceId).catch(() => null)])
      .then(([ev, saved]) => {
        if (!alive) return
        setHorses(ev.horses)
        setUserOdds(saved?.tansho ? { ...saved.tansho } : {})
        setBetOdds(saved?.bets ? { ...saved.bets } : {})
        setLoadedOdds(true)
      })
      .catch((e: Error) => alive && setError(e.message))
    return () => { alive = false }
  }, [raceId])

  // 未入力の馬は採算オッズで初期化される（既存の期待値シミュレーターと同じ挙動）
  const rows: EvRow[] = useMemo(() => {
    if (!horses) return []
    const work = { ...userOdds }
    const r = tableRows(horses, { tab, userOdds: work })
    return r
  }, [horses, tab, userOdds])

  const initialised = useRef(false)
  useEffect(() => {
    // 初回だけ、採算オッズによる初期値を state に取り込む
    if (!horses || !loadedOdds || initialised.current) return
    const work = { ...userOdds }
    tableRows(horses, { tab: 'tansho', userOdds: work })
    setUserOdds(work)
    initialised.current = true
  }, [horses, loadedOdds, userOdds])

  const plan: BetPlan | null = useMemo(
    () => (horses ? buildBetPlan(horses) : null),
    [horses],
  )
  const forms = useMemo(() => (plan ? formationBets(plan) : []), [plan])
  const details = useMemo(() => (plan ? detailBets(plan) : []), [plan])

  const onOdds = (uma: number | null, value: string) => {
    if (uma == null) return
    setOddsText((t) => ({ ...t, [String(uma)]: value }))
    const v = parseFloat(value)
    const next = { ...userOdds }
    if (v > 0) next[String(uma)] = v
    else delete next[String(uma)]
    setUserOdds(next)
    save(next, betOdds)
  }

  /** 入力を離れたら小数第1位に整える（9 → 9.0）。 */
  const onOddsBlur = (uma: number | null) => {
    if (uma == null) return
    const v = userOdds[String(uma)]
    setOddsText((t) => ({ ...t, [String(uma)]: v != null ? v.toFixed(1) : '' }))
  }

  const onBetOdds = (key: string, value: string) => {
    const v = parseFloat(value)
    const next = { ...betOdds }
    if (v > 0) next[key] = v
    else delete next[key]
    setBetOdds(next)
    save(userOdds, next)
  }

  if (error) return <div className="note error">EVデータを読み込めません: {error}</div>
  if (!horses) return <div className="note">読み込み中...</div>

  const isFuku = tab === 'fukusho'
  const sorted = [...rows].sort((a, b) => b._prob - a._prob)

  return (
    <div className="ev-panel">
      <div className="ev-warning">
        <b>この画面は「監視・確認」のためのものです。</b>
        モデルは市場に妙味では勝てないことが5年・10以上のアプローチで検証済みです
        （単勝EV・三連系オーバーレイ・条件スライス・重み再最適化のいずれも控除率を超えません）。
        収益を前提とした道具ではありません。
      </div>

      <div className="ev-tabs">
        <button className={!isFuku ? 'tab active' : 'tab'} onClick={() => setTab('tansho')}>単勝</button>
        <button className={isFuku ? 'tab active' : 'tab'} onClick={() => setTab('fukusho')}>複勝</button>
        <span className="save-state">
          {saveState === 'saving' && '保存中...'}
          {saveState === 'saved' && '保存しました'}
          {saveState === 'error' && <span className="error">保存に失敗しました</span>}
        </span>
      </div>

      <div className="ev-note">
        {isFuku
          ? '複勝率はHarville式による3着以内確率の推定値。複勝EV = 複勝率 × 複勝オッズ下限 − 1。複勝オッズは手入力できません。'
          : '勝率はスコアのsoftmax変換による推定値（参考馬は分布から除外）。単勝EV = 勝率 × 入力オッズ − 1。採算オッズ以上ならEVプラスの可能性。'}
      </div>

      <ul className="ev-list">
        {sorted.map((h) => (
          <li key={h.馬名} className={h._isLocal ? 'ev-item local' : 'ev-item'}>
            <div className="ev-head">
              <UmaChip uma={h.馬番} waku={h.枠番} />
              <span className="ev-name">{h.馬名}</span>
              {h.is_memo && <span className="badge badge-note">メモ</span>}
              {h._isLocal && <span className="badge badge-note">📎参考(地方のみ)</span>}
            </div>
            <div className="ev-facts">
              <span>スコア <b>{Number(h.表示スコア ?? h.スコア).toFixed(1)}</b></span>
              <span>予想 <b>{h.順位予想}位</b></span>
              <span>推定人気 <b>{h.SmartRC推定人気順 ?? '-'}</b></span>
              <span>{isFuku ? '複勝率' : '勝率'} <b>{h._isLocal ? '参考' : pct(h._prob)}</b></span>
            </div>
            <div className="ev-input-row">
              {!isFuku && (
                <>
                  <label className="ev-label">採算オッズ</label>
                  <span className="be-odds">
                    {h._breakEven ? `${h._breakEven.toFixed(1)}倍` : '-'}
                  </span>
                  <label className="ev-label">実オッズ</label>
                  <input
                    type="text"
                    inputMode="decimal"
                    className="odds-input"
                    value={
                      h.馬番 != null && oddsText[String(h.馬番)] !== undefined
                        ? oddsText[String(h.馬番)]
                        : h.馬番 != null && userOdds[String(h.馬番)] != null
                          ? userOdds[String(h.馬番)].toFixed(1)
                          : ''
                    }
                    placeholder={h._breakEven ? h._breakEven.toFixed(1) : ''}
                    onChange={(e) => onOdds(h.馬番, e.target.value)}
                    onBlur={() => onOddsBlur(h.馬番)}
                  />
                </>
              )}
              {isFuku && (
                <>
                  <label className="ev-label">複勝オッズ幅</label>
                  <span className="be-odds">
                    {h.複勝下限
                      ? `${h.複勝下限.toFixed(1)}〜${(h.複勝上限 ?? 0).toFixed(1)}倍`
                      : '-'}
                  </span>
                </>
              )}
              <span className={`ev-value ${h._cls}`}>
                {h._ev != null && !h._isLocal ? `EV ${h._ev.toFixed(3)}` : ''}
              </span>
              <span className={`ev-judge ${h._cls}`}>{h._judgement}</span>
            </div>
          </li>
        ))}
      </ul>

      <h3 className="ev-h3">🎯 買い目提案</h3>
      {!plan?.ok ? (
        <div className="note">買い目を出せません（{plan?.reason ?? 'データ不足'}）</div>
      ) : (
        <>
          <div className={plan.buy ? 'bet-banner buy' : 'bet-banner nobuy'}>
            <div className="bet-badge">{plan.buy ? '🟢 購入推奨' : '🔴 購入非推奨'}</div>
            <div className="bet-reason">{plan.reason}</div>
          </div>

          <div className="bet-anchor">
            軸: <UmaChip uma={plan.axisUma} waku={horses.find((h) => h.馬名 === plan.axis)?.枠番 ?? null} />{' '}
            <b>{plan.axis}</b>
            （偏差値{plan.axisDev.toFixed(1)}・勝率1位(オッズ勘案) / 勝率{(plan.axisWin * 100).toFixed(0)}%
            {' / '}想定{plan.axisPop < 99 ? `${plan.axisPop}番人気` : '-'}）
          </div>
          {plan.axisDiffersFromScoreTop && plan.scoreTop && (
            <div className="axis-note">
              ※スコア1位は <UmaChip uma={plan.scoreTop.馬番} waku={plan.scoreTop.枠番} />{' '}
              <b>{plan.scoreTop.馬名}</b>
              （{plan.scoreTop.オッズ ? `${plan.scoreTop.オッズ}倍で人気薄` : '人気薄'}）。
              市場と乖離した人気薄の過剰評価を抑えるため、勝率cap適用で軸は{' '}
              <UmaChip uma={plan.axisUma} waku={null} /> <b>{plan.axis}</b> に調整。
            </div>
          )}
          <div className="bet-cols">
            <div>1着列: {plan.col1.map((n) => plan.um[n]).join(' / ') || '-'}</div>
            <div>2着列: {plan.col2.map((n) => plan.um[n]).join(' / ') || '-'}</div>
            <div>3着列: {plan.col3.map((n) => plan.um[n]).join(' / ') || '-'}</div>
          </div>

          <h4 className="bet-h4">フォーメーション</h4>
          <ul className="bet-list">
            {forms.map((b) => {
              const status = b.status
              if (status === 'no_partner') {
                return <li key={b.key} className="bet-item"><b>{b.bt}</b><span className="muted">相手不足</span></li>
              }
              if (status === 'too_many') {
                return <li key={b.key} className="bet-item"><b>{b.bt}</b><span className="warn">多点数のため非推奨</span></li>
              }
              const c = evCell(b.P, betOdds[b.key] ?? null)
              const uma = b.cols.map((col) => col.join(',')).join(b.sep)
              return (
                <li key={b.key} className="bet-item">
                  <div className="bet-line1">
                    <b>{b.bt}</b>
                    <span className="bet-uma">{uma}</span>
                    <span className="muted">{b.M}点</span>
                  </div>
                  <div className="bet-line2">
                    <span>的中率 <b>{pct(c.hitRate)}</b></span>
                    <span>採算 <b className="be-odds">{c.breakEven > 0 ? `${c.breakEven.toFixed(1)}倍` : '-'}</b></span>
                    <label className="ev-label">実オッズ</label>
                    <input
                      type="number"
                      inputMode="decimal"
                      min="0"
                      step="0.1"
                      className="odds-input"
                      value={betOdds[b.key] ?? ''}
                      onChange={(e) => onBetOdds(b.key, e.target.value)}
                    />
                    <span className={`ev-value ${c.cls}`}>{c.ev != null ? c.ev.toFixed(2) : ''}</span>
                    <span className={`ev-judge ${c.cls}`}>{c.judge}</span>
                  </div>
                </li>
              )
            })}
          </ul>

          <Collapsible id={`ev.detail.${raceId}`} title="内訳（1点ずつ）" sub={`${details.length}点`}>
            <ul className="bet-list">
              {details.map((b) => {
                const c = evCell(b.P, betOdds[b.key] ?? null)
                return (
                  <li key={b.key} className="bet-item">
                    <div className="bet-line1">
                      <b>{b.bt}</b>
                      <span className="bet-uma">{b.uma.join(b.sep)}</span>
                      <span className="muted">1点</span>
                    </div>
                    <div className="bet-line2">
                      <span>的中率 <b>{pct(c.hitRate)}</b></span>
                      <span>採算 <b className="be-odds">{c.breakEven > 0 ? `${c.breakEven.toFixed(1)}倍` : '-'}</b></span>
                      <label className="ev-label">実オッズ</label>
                      <input
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="0.1"
                        className="odds-input"
                        value={betOdds[b.key] ?? ''}
                        onChange={(e) => onBetOdds(b.key, e.target.value)}
                      />
                      <span className={`ev-value ${c.cls}`}>{c.ev != null ? c.ev.toFixed(2) : ''}</span>
                      <span className={`ev-judge ${c.cls}`}>{c.judge}</span>
                    </div>
                  </li>
                )
              })}
            </ul>
          </Collapsible>
        </>
      )}
    </div>
  )
}
